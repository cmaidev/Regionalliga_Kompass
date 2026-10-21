import csv
import json

import pytest

import kompass
from kompass_history import (
    build_history_report, compare_assignments, export_history_report, fingerprint,
    history_path, load_history, record_output_snapshot, record_snapshot,
)
from kompass_report import render_recalculation_history


SOURCE = "2026/27"
TARGET = "2027/28"
BASE = {team: "Nord" if team < "E" else "Süd" for team in "ABCDEFGH"}


def snapshot(number, assignments, standings="table-a", settings="search-a"):
    return {"id": str(number), "captured_at": f"2026-10-{number:02d}T12:00:00+00:00",
            "assignments": assignments, "standings_hash": standings,
            "search_config_hash": settings, "rules_hash": "rules-a"}


def report_for(tmp_path, snapshots):
    for entry in snapshots:
        record_snapshot(SOURCE, TARGET, entry, tmp_path)
    return build_history_report(SOURCE, TARGET, snapshots[-1]["assignments"], snapshots[-1]["id"], tmp_path)


def test_returning_club_switches_use_shared_pool_as_denominator():
    current = dict(BASE, A="Süd", E="Nord")
    current["I"] = current.pop("D")
    change = compare_assignments(BASE, current)
    assert change["switch_count"] == 2
    assert change["shared_count"] == 7
    assert change["switch_percent"] == 28.6
    assert change["entered"] == ["I"] and change["left"] == ["D"]
    assert {row["team"] for row in change["switched"]} == {"A", "E"}
    assert sum(row["added"] for row in change["league_changes"]) == 3
    assert sum(row["removed"] for row in change["league_changes"]) == 3


def test_league_renaming_does_not_count_as_switching():
    renamed = {team: "Süd" if league == "Nord" else "Nord" for team, league in BASE.items()}
    assert compare_assignments(BASE, renamed)["switch_count"] == 0
    renamed.update(A="Nord", E="Süd")
    assert {row["team"] for row in compare_assignments(BASE, renamed)["switched"]} == {"A", "E"}


def test_completely_new_pool_has_no_fictitious_switch_percentage():
    current = {team + " new": league for team, league in BASE.items()}
    change = compare_assignments(BASE, current)
    assert change["shared_count"] == change["switch_count"] == 0
    assert change["switch_percent"] is None
    assert len(change["entered"]) == len(change["left"]) == 8


def test_first_snapshot_is_baseline_and_report_is_read_only(tmp_path):
    first = snapshot(1, BASE, standings=None)
    report = report_for(tmp_path, [first])
    path = history_path(SOURCE, TARGET, tmp_path)
    before = path.read_bytes()
    assert report["snapshot_count"] == 1 and report["latest"] is None
    assert report["comparison_count"] == report["switch_total"] == 0
    assert "Erster gespeicherter Lauf" in render_recalculation_history(report)
    build_history_report(SOURCE, TARGET, BASE, first["id"], tmp_path)
    assert not record_snapshot(SOURCE, TARGET, first, tmp_path)
    assert path.read_bytes() == before


def test_identical_recalculations_are_zero_change_observations(tmp_path):
    changed = dict(BASE, A="Süd", E="Nord")
    report = report_for(tmp_path, [snapshot(1, BASE), snapshot(2, changed), snapshot(3, changed)])
    assert report["snapshot_count"] == 3
    assert report["comparison_count"] == 2 and report["allocation_changes"] == 1
    assert report["switch_total"] == 2 and report["latest"]["switch_count"] == 0
    assert report["latest"]["tables_changed"] is False
    assert {row["team"]: row["switch_count"] for row in report["teams"]}["A"] == 1


def test_reentry_is_separate_from_switches(tmp_path):
    middle = dict(BASE)
    middle["I"] = middle.pop("D")
    last = dict(BASE, D="Süd", E="Nord")
    report = report_for(tmp_path, [snapshot(1, BASE), snapshot(2, middle), snapshot(3, last)])
    counts = {row["team"]: row for row in report["teams"]}
    assert counts["D"]["switch_count"] == 0
    assert counts["D"]["entries"] == counts["D"]["exits"] == 1
    assert counts["D"]["appearances"] == 2
    assert counts["E"]["switch_count"] == 1


def test_table_and_settings_changes_are_not_confused_with_assignment_changes(tmp_path):
    report = report_for(tmp_path, [snapshot(1, BASE, standings=None),
                                   snapshot(2, BASE), snapshot(3, BASE, standings="table-b", settings="search-b")])
    assert report["comparisons"][0]["tables_changed"] is None
    assert report["latest"]["tables_changed"] is True
    assert report["latest"]["settings_changed"] is True
    assert report["allocation_changes"] == report["switch_total"] == 0


def test_seasons_are_separate_and_stale_outputs_are_not_misreported(tmp_path):
    report_for(tmp_path, [snapshot(1, BASE)])
    assert load_history("2027/28", "2028/29", tmp_path)["snapshots"] == []
    stale = build_history_report(SOURCE, TARGET, BASE, "different run", tmp_path)
    assert not stale["available"] and stale["reason"] == "stale"
    stale = build_history_report(SOURCE, TARGET, dict(BASE, A="Süd"), "1", tmp_path)
    assert not stale["available"]


def test_bad_history_is_preserved(tmp_path):
    path = history_path(SOURCE, TARGET, tmp_path)
    path.write_text("broken history", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        record_snapshot(SOURCE, TARGET, snapshot(1, BASE), tmp_path)
    assert path.read_text(encoding="utf-8") == "broken history"


def test_standings_fingerprint_is_captured_before_other_models(monkeypatch):
    kompass.RECALCULATION_STANDINGS.clear()
    rows = [{"team": "A", "rank": 1, "points": 20, "games": 10}]
    monkeypatch.setattr(kompass, "extract_standings_rows", lambda *args, **kwargs: rows)
    monkeypatch.setattr(kompass, "table_source_priority_for_season", lambda: ["fupa"])
    sources = {"fupa": "https://example.com/table"}
    kompass.extract_standings_rows_with_fallback(sources)
    selected = dict(kompass.RECALCULATION_STANDINGS)
    before = fingerprint(selected)
    rows[0]["points"] = 23
    kompass.extract_standings_rows_with_fallback(sources)
    assert fingerprint(selected) == before
    assert fingerprint(kompass.RECALCULATION_STANDINGS) != before
    kompass.RECALCULATION_STANDINGS.clear()


def test_archive_only_records_consistent_rank1_output(tmp_path):
    (tmp_path / "outputs/json").mkdir(parents=True)
    (tmp_path / "outputs/csv").mkdir(parents=True)
    teams = {league: [f"{league} {number}" for number in range(20)]
             for league in ("Nord", "West", "Ost", "Süd")}
    ranked = {"generated_at": "2026-10-21T12:00:00+00:00", "search_config": {},
              "solutions": [{"rank": 1, "teams_by_league": teams}]}
    (tmp_path / "outputs/json/kompass_solutions_ranked.json").write_text(json.dumps(ranked), encoding="utf-8")
    (tmp_path / "season_transitions.json").write_text(json.dumps({
        "source_season": SOURCE, "target_season": TARGET, "reform_rule": "12+4+14+2",
    }), encoding="utf-8")
    csv_path = tmp_path / "outputs/csv/kompass_regionalliga_4x20.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Liga", "Verein"])
        writer.writeheader()
        writer.writerows({"Liga": league, "Verein": team} for league, names in teams.items() for team in names)
    assert record_output_snapshot({"table": [{"team": "A", "rank": 1}]}, tmp_path)
    assert not record_output_snapshot(root=tmp_path)
    history = load_history(SOURCE, TARGET, tmp_path / "data/recalculation_history")
    assert len(history["snapshots"]) == 1
    assert history["snapshots"][0]["standings_hash"] is not None
    csv_path.write_text("Liga,Verein\nNord,Incomplete\n", encoding="utf-8")
    ranked["generated_at"] = "2026-10-22T12:00:00+00:00"
    (tmp_path / "outputs/json/kompass_solutions_ranked.json").write_text(json.dumps(ranked), encoding="utf-8")
    assert not record_output_snapshot(root=tmp_path)


def test_history_exports_and_html_include_changes(tmp_path):
    changed = dict(BASE, A="Süd", E="Nord")
    report = report_for(tmp_path, [snapshot(1, BASE), snapshot(2, changed)])
    export_history_report(report, tmp_path / "changes.json", tmp_path / "changes.csv")
    assert json.loads((tmp_path / "changes.json").read_text(encoding="utf-8"))["switch_total"] == 2
    with (tmp_path / "changes.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert sum(int(row["switch_count"]) for row in rows) == 2
    html = render_recalculation_history(report)
    assert 'id="projection-history"' in html
    assert "2 / 8 (25,0 %)" in html
    assert "Wechsel je Verein" in html and "Tabellen gleich" in html
    report["teams"][0]["team"] = "<script>untrusted</script>"
    assert "<script>untrusted</script>" not in render_recalculation_history(report)
