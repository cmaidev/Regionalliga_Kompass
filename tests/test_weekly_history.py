import copy
import csv
from datetime import date, datetime
import json
from pathlib import Path

import pytest

import kompass
import kompass_weekly as weekly
from kompass_history import summarize_snapshots
from kompass_report import create_index_html, render_weekly_history
from kompass_utils import load_verified_stadiums


def match(kickoff, home="A", away="B", score=(2, 0)):
    return dict(id=kickoff, kickoff=kickoff, home=home, away=away,
                home_goals=score[0], away_goals=score[1])


def league(matches, name="Test", kind="regionalliga"):
    return dict(name=name, kind=kind, second_sort="goal_diff", matches=matches,
                teams=[dict(team=team, level="1", penalty_points=0) for team in "ABCDEF"])


def test_cutoff_uses_berlin_midnight_and_actual_played_date():
    source = league([match("2026-08-30T21:59:00+00:00"),
                     match("2026-08-30T22:00:00+00:00", "B", "A")])
    rows = {row["team"]: row for row in weekly.reconstruct_table(source, date(2026, 8, 30))}
    assert rows["A"]["games"] == 1 and rows["A"]["points"] == 3
    assert rows["B"]["goals_against"] == 2
    later = weekly.reconstruct_table(source, date(2026, 9, 6))
    assert next(row for row in later if row["team"] == "A")["games"] == 2


def test_current_penalties_and_fully_tied_rows_are_explicit():
    source = league([match("2026-08-01T12:00:00+00:00")])
    source["teams"][0]["penalty_points"] = 3
    rows = weekly.reconstruct_table(source, date(2026, 8, 30))
    assert rows[0]["team"] == "A" and rows[0]["points"] == 0
    c = next(row for row in rows if row["team"] == "C")
    assert c["ranking_tie"] == ["D", "E", "F"]
    assert all(row["mark"] is None for row in rows)


def test_third_liga_relegation_marks_follow_historical_bottom_four():
    rows = weekly.reconstruct_table(league([match("2026-08-01T12:00:00+00:00")], kind="third_liga"), date(2026, 8, 30))
    assert [row["rank"] for row in rows if row["mark"] == "down"] == [3, 4, 5, 6]


def test_all_leagues_must_have_started_and_sunday_must_be_complete():
    sources = [league([match("2026-08-01T12:00:00+00:00")], str(i)) for i in range(19)]
    sources.append(league([match("2026-08-28T12:00:00+00:00")], "last"))
    cutoffs, openings = weekly.weekly_cutoffs(sources, date(2026, 9, 6), date(2026, 9, 6))
    assert cutoffs == [date(2026, 8, 30)] and openings["last"] == date(2026, 8, 28)
    assert weekly.weekly_cutoffs(sources, date(2026, 9, 7))[0][-1] == date(2026, 9, 6)
    with pytest.raises(ValueError, match="20 input leagues"):
        weekly.weekly_cutoffs(sources[:-1], date(2026, 9, 7))
    sources[-1]["matches"] = []
    assert weekly.weekly_cutoffs(sources, date(2026, 9, 7))[0] == []


@pytest.mark.parametrize("day, expected", [(19, 18), (21, 18), (24, 18), (25, 18), (26, 25)])
def test_midweek_and_sunday_runs_reference_the_last_completed_sunday(day, expected):
    today = date(2026, 10, day)
    assert weekly.latest_completed_sunday(today, today) == date(2026, 10, expected)
    assert weekly.latest_completed_sunday(date(2026, 10, 18), date(2026, 10, 21)) == date(2026, 10, 18)


@pytest.mark.parametrize("retrieved_at, download", [("2026-10-21T10:00:00Z", False),
                                                   ("2026-10-18T10:00:00Z", True)])
def test_midweek_update_catches_up_sundays_and_refreshes_only_if_needed(tmp_path, monkeypatch, retrieved_at, download):
    dataset = json.loads(Path("data/weekly_results_2026_27.json").read_text(encoding="utf-8"))
    dataset["retrieved_at"] = retrieved_at
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    Path("data/weekly_results_2026_27.json").write_text(json.dumps(dataset), encoding="utf-8")

    class Friday(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 23, 12, tzinfo=weekly.BERLIN).astimezone(tz)

    monkeypatch.setattr(weekly, "datetime", Friday)
    fetched = []
    def fetch(spec, season, through, session):
        fetched.append(spec["name"])
        return next(source for source in dataset["leagues"] if source["name"] == spec["name"])
    monkeypatch.setattr(weekly, "fetch_league", fetch)
    monkeypatch.setattr(weekly, "build_weekly_projections", lambda data, weeks, *args: weeks)
    weeks = weekly.update_weekly_history()
    assert len(fetched) == (20 if download else 0)
    assert len(weeks) == 8 and weeks[-1]["as_of"] == "2026-10-18"
    assert all(date.fromisoformat(week["as_of"]).weekday() == 6 for week in weeks)


def test_persistent_sunday_solutions_survive_deleted_runtime_cache(tmp_path, monkeypatch):
    prior = json.loads(Path("data/weekly_projections/2026_27_to_2027_28.json").read_text(encoding="utf-8"))
    dataset = json.loads(Path("data/weekly_results_2026_27.json").read_text(encoding="utf-8"))
    directory = tmp_path / "archive"
    directory.mkdir()
    (directory / "2026_27_to_2027_28.json").write_text(json.dumps(prior), encoding="utf-8")
    monkeypatch.setattr(weekly, "WEEKLY_DIR", directory)
    def unexpected_search(*args, **kwargs):
        pytest.fail("A stored Sunday with the same pool and search settings must be reused")
    monkeypatch.setattr(kompass, "run_multi_start_search", unexpected_search)
    weeks = [{key: snapshot[key] for key in ("as_of", "teams", "tables", "selection_ties", "transitions")}
             for snapshot in prior["snapshots"]]
    result = weekly.build_weekly_projections(dataset, weeks, prior["league_openings"], tmp_path / "work", prior["search_profile"]["phase1_runs"])
    assert [week["id"] for week in result["snapshots"]] == [week["id"] for week in prior["snapshots"]]
    assert [week["calculated_at"] for week in result["snapshots"]] == [week["calculated_at"] for week in prior["snapshots"]]
    assert result["summary"]["switch_total"] == prior["summary"]["switch_total"]


def test_dashboard_uses_sunday_metrics_and_keeps_run_archive_in_details(tmp_path):
    from lxml import html

    payload = json.loads(Path("data/weekly_projections/2026_27_to_2027_28.json").read_text(encoding="utf-8"))
    path = tmp_path / "index.html"
    create_index_html(dict(weekly_history=payload, source_season="2026/27", target_season="2027/28",
                           variants=[dict(id="rank1", overall_avg_km=150.0)]), str(path))
    document = html.fromstring(path.read_text(encoding="utf-8"))
    ids = document.xpath('//@id')
    assert len(ids) == len(set(ids))
    assert document.xpath('//*[@data-view-panel]/@id') == ["overview", "weekly", "models"]
    assert document.xpath('//*[@id="projection-history"]/ancestor::section[@data-view-panel]/@id') == ["models"]
    assert document.xpath('//h2[text()="Stabilität der Prognose"]/ancestor::section[@data-view-panel]/@id') == ["weekly"]
    latest = payload["summary"]["latest"]
    stats = document.xpath('//*[@id="weekly-history"]//div[@class="summary-card"]/strong/text()')
    assert stats[1:] == [str(latest["switch_count"]), str(len(latest["entered"])), str(len(payload["snapshots"]))]
    expected_stability = f'{100 * (latest["shared_count"] - latest["switch_count"]) / latest["shared_count"]:.1f} %'.replace(".", ",")
    assert stats[0] == expected_stability


def test_first_team_and_reserve_names_remain_distinct():
    team = {"name": {"full": "Fortuna Düsseldorf"}, "level": "1"}
    assert weekly.fupa_team_name(team) == "Fortuna Düsseldorf"
    assert weekly.fupa_team_name(dict(team, level="2")) == "Fortuna Düsseldorf II"
    assert kompass.TEAM_NAME_NORMALIZATION_OVERRIDES_BY_SEASON["2025/26"]["Fortuna Düsseldorf"] == "Fortuna Düsseldorf II"


def test_only_completed_league_results_enter_reconstruction():
    teams = [{"id": i, "name": {"full": team}, "level": "1"} for i, team in enumerate("AB", 1)]
    rows = [dict(team=team, rank=i, matches=1, points=3 if i == 1 else 0,
                 ownGoals=2 if i == 1 else 0, againstGoals=0 if i == 1 else 2,
                 penaltyPoints=0) for i, team in enumerate(teams, 1)]
    played = dict(id=1, slug="played", kickoff="2026-08-01T12:00:00Z", category="league",
                  section="POST", homeTeam={"id": 1}, awayTeam={"id": 2}, homeGoal=2, awayGoal=0,
                  flags=["verdict"])
    raw = {"table": {"standings": rows, "secondSort": "goal_diff"},
           "matches": [played, dict(played, id=2, section="PRE"),
                       dict(played, id=3, category="cup"), dict(played, id=4, homeGoal=None)]}
    spec = dict(name="Test", kind="regionalliga", sources={"fupa": "example"}, table_pick=0)
    result = weekly.normalize_league(raw, spec)
    assert len(result["matches"]) == 1 and result["matches"][0]["awarded"] is True
    raw["matches"].append(played)
    with pytest.raises(ValueError, match="Duplicate match"):
        weekly.normalize_league(raw, spec)


def test_historical_inputs_never_fall_back_and_restore_live_state(tmp_path):
    sources = {"fupa": "https://example.org/table"}
    key = json.dumps([sources, 0], sort_keys=True)
    original_paths = (kompass.SEASON_TRANSITIONS_FILE, kompass.CACHE_FILE)
    original_standings = kompass.RECALCULATION_STANDINGS
    with pytest.raises(RuntimeError, match="Missing historical table"):
        with weekly.historical_inputs({key: [{"team": "A", "rank": 1}]}, tmp_path):
            rows, provider, _ = kompass.extract_standings_rows_with_fallback(sources)
            assert rows[0]["team"] == "A" and provider == "reconstructed_fupa"
            kompass.extract_standings_rows_with_fallback({"fupa": "missing"})
    assert kompass.TABLE_SNAPSHOT_OVERRIDE is None
    assert kompass.RECALCULATION_STANDINGS is original_standings
    assert (kompass.SEASON_TRANSITIONS_FILE, kompass.CACHE_FILE) == original_paths


def test_cached_results_reproduce_all_twenty_published_tables():
    dataset = json.loads(Path("data/weekly_results_2026_27.json").read_text(encoding="utf-8"))
    assert len(dataset["leagues"]) == 20
    for source in dataset["leagues"]:
        weekly.validate_current_totals(source)
    changed = copy.deepcopy(dataset["leagues"][0])
    changed["matches"][0]["home_goals"] += 1
    with pytest.raises(ValueError, match="published table"):
        weekly.validate_current_totals(changed)


def test_eight_historical_pools_use_the_live_reform_selection(tmp_path):
    dataset = json.loads(Path("data/weekly_results_2026_27.json").read_text(encoding="utf-8"))
    weeks, _ = weekly.prepare_weeks(dataset, date(2026, 10, 21), tmp_path)
    assert [weeks[0]["as_of"], weeks[-1]["as_of"]] == ["2026-08-30", "2026-10-18"]
    assert len(weeks) == 8
    grounds = load_verified_stadiums("2026/27")
    for week in weeks:
        assert len(set(week["teams"])) == 80
        assert set(week["teams"]) <= set(grounds)
        assert len(week["tables"]) == 20 and not week["selection_ties"]
    tables = {source["table_key"]: weekly.reconstruct_table(source, date(2026, 8, 30)) for source in dataset["leagues"]}
    with weekly.historical_inputs(tables, tmp_path / "reference"):
        assert kompass.build_reform_12_4_14_team_pool(80) == weeks[0]["teams"]


def test_weekly_csv_baseline_is_blank_and_group_renaming_is_ignored(tmp_path):
    assignments = {team: "Nord" if team in "AB" else "Süd" for team in "ABCD"}
    renamed = {team: "Süd" if value == "Nord" else "Nord" for team, value in assignments.items()}
    snapshots = [dict(id=str(i), as_of=f"2026-09-{i:02d}", captured_at=f"2026-09-{i:02d}T21:59:00Z",
                      assignments=value, score_avg_away_km=150, selection_ties=[], tables=[])
                 for i, value in enumerate([assignments, renamed], 1)]
    payload = dict(source_season="2026/27", target_season="2027/28", valuation_note=weekly.VALUATION_NOTE,
                   snapshots=snapshots, search_profile={"phase1_runs": 50},
                   summary=summarize_snapshots(snapshots, renamed, "2026/27", "2027/28"))
    weekly.export_weekly_metrics(payload, tmp_path)
    with (tmp_path / "csv/kompass_weekly_changes.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["switch_count"] == "" and rows[1]["switch_count"] == "0"
    assert "weekly-date" in render_weekly_history(payload)
    assert "Spielwertungs- und Punktabzugsstand" in render_weekly_history(payload)
