"""Reconstruct Sunday projections from dated results of all 20 input leagues."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager, redirect_stdout
import csv
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import requests

from kompass_history import fingerprint, summarize_snapshots
from kompass_utils import load_verified_stadiums


BERLIN = ZoneInfo("Europe/Berlin")
WEEKLY_DIR = Path("data/weekly_projections")
VALUATION_NOTE = (
    "Rekonstruktion aus datierten Ergebnissen mit heutigem Spielwertungs- und Punktabzugsstand; "
    "spätere Sportgerichtsentscheidungen können von den damals veröffentlichten Tabellen abweichen."
)


def competition_specs():
    import kompass

    specs = [{"name": name, "sources": sources, "table_pick": 0, "kind": "regionalliga"}
             for name, sources in kompass.REGIONALLIGA_TABLE_URLS.items()]
    specs.append({"name": "3. Liga", "sources": kompass.THIRD_LIGA_TABLE_URLS,
                  "table_pick": 0, "kind": "third_liga"})
    specs.extend(dict(comp, table_pick=comp.get("wikipedia_table_pick", 0), kind="oberliga")
                 for comp in kompass.OBERLIGA_MASTER_COMPETITIONS)
    return specs


def fupa_team_name(team):
    import kompass

    name = kompass.clean_team_name(team["name"]["full"])
    suffix = {"2": "II", "3": "III"}.get(str(team.get("level")))
    if suffix and not re.search(r"\b(?:II|III)$", name):
        name = re.sub(rf"\s+(?:U(?:19|21|23)|{team['level']})$", "", name, flags=re.I)
        name = kompass.clean_team_name(f"{name} {suffix}")
    return name


def normalize_league(raw, spec):
    rows = raw["table"]["standings"]
    names = {row["team"]["id"]: fupa_team_name(row["team"]) for row in rows}
    if len(set(names.values())) != len(rows):
        raise ValueError(f"Duplicate roster in {spec['name']}")
    matches = []
    seen = set()
    for match in raw["matches"]:
        if match["id"] in seen:
            raise ValueError(f"Duplicate match in {spec['name']}: {match['id']}")
        seen.add(match["id"])
        if (match.get("category") != "league" or match.get("section") != "POST"
                or match.get("homeGoal") is None or match.get("awayGoal") is None):
            continue
        if any(flag in (match.get("flags") or []) for flag in ("cancelled", "aborted")):
            raise ValueError(f"Unresolved completed match: {match['slug']}")
        matches.append({
            "id": match["id"], "kickoff": match["kickoff"],
            "home": names[match["homeTeam"]["id"]], "away": names[match["awayTeam"]["id"]],
            "home_goals": match["homeGoal"], "away_goals": match["awayGoal"],
            "awarded": "verdict" in (match.get("flags") or []),
        })
    league = {
        "name": spec["name"], "kind": spec["kind"], "sources": spec["sources"],
        "table_key": json.dumps([spec["sources"], spec["table_pick"]], sort_keys=True),
        "source_url": spec["sources"]["fupa"], "second_sort": raw["table"]["secondSort"],
        "teams": [{"team": names[row["team"]["id"]], "level": row["team"].get("level"),
                   "penalty_points": row.get("penaltyPoints") or 0,
                   "published": {key: row[key] for key in (
                       "rank", "matches", "points", "ownGoals", "againstGoals")}}
                  for row in rows],
        "matches": sorted(matches, key=lambda match: (match["kickoff"], match["id"])),
    }
    if league["second_sort"] not in ("goal_diff", "direct_comparison"):
        raise ValueError(f"Unsupported table ordering in {league['name']}: {league['second_sort']}")
    if any(row["team"].get("flags") for row in rows):
        raise ValueError(f"Special team status needs review: {league['name']}")
    validate_current_totals(league)
    return league


def fetch_league(spec, season, through, session):
    response = session.get(spec["sources"]["fupa"], timeout=30)
    response.raise_for_status()
    match = re.search(r"window\.REDUX_DATA\s*=\s*(\{.*?\})\s*</script>", response.text, re.S)
    if not match:
        raise ValueError(f"No FuPa table for {spec['name']}")
    payload = json.loads(match.group(1))
    record = next(item for item in payload["dataHistory"] if item.get("LeagueStandingPage"))
    league = record["LeaguePage"]
    if league["season"]["slug"] != season.replace("/", "-"):
        raise ValueError(f"Wrong source season for {spec['name']}")
    matches = []
    url = f"https://api.fupa.net/v1/competitions/{league['slug']}/seasons/{league['season']['slug']}/matches"
    for offset in range(0, 2000, 100):
        response = session.get(url, params={"to": through.isoformat(), "sort": "desc",
                                            "limit": 100, "offset": offset}, timeout=30)
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            raise ValueError(f"Unexpected results feed for {spec['name']}")
        matches.extend(page)
        if len(page) < 100:
            break
    else:
        raise ValueError(f"Incomplete result pagination for {spec['name']}")
    return normalize_league({"table": record["LeagueStandingPage"]["total"]["data"], "matches": matches}, spec)


def aggregate(teams, matches):
    rows = {team: {"team": team, "games": 0, "points": 0, "goals_for": 0, "goals_against": 0}
            for team in teams}
    for match in matches:
        for team, scored, conceded in (
            (match["home"], match["home_goals"], match["away_goals"]),
            (match["away"], match["away_goals"], match["home_goals"]),
        ):
            row = rows[team]
            row["games"] += 1
            row["points"] += 3 if scored > conceded else 1 if scored == conceded else 0
            row["goals_for"] += scored
            row["goals_against"] += conceded
    return rows


def validate_current_totals(league):
    stats = aggregate([team["team"] for team in league["teams"]], league["matches"])
    for team in league["teams"]:
        actual, published = stats[team["team"]], team["published"]
        values = [actual["games"], actual["points"] - team["penalty_points"],
                  actual["goals_for"], actual["goals_against"]]
        expected = [published[key] for key in ("matches", "points", "ownGoals", "againstGoals")]
        if values != expected:
            raise ValueError(f"Results do not reproduce the published table: {league['name']} / {team['team']}: {values} != {expected}")
    rebuilt = reconstruct_table(league, date.max)
    expected_order = sorted(league["teams"], key=lambda team: team["published"]["rank"])
    for actual, expected in zip(rebuilt, expected_order):
        if actual["team"] != expected["team"] and expected["team"] not in actual["ranking_tie"]:
            raise ValueError(f"Interim table order needs review: {league['name']} / {actual['team']}")


def reconstruct_table(league, cutoff):
    boundary = datetime.combine(cutoff, time.max, tzinfo=BERLIN)
    matches = [match for match in league["matches"] if datetime.fromisoformat(match["kickoff"]) <= boundary]
    rows = aggregate([team["team"] for team in league["teams"]], matches)
    for team in league["teams"]:
        row = rows[team["team"]]
        row["points"] -= team["penalty_points"]
        row["fupa_team_level"] = team["level"]
        row["ppg"] = row["points"] / row["games"] if row["games"] else None
        row["goal_difference"] = row["goals_for"] - row["goals_against"]
    groups = defaultdict(list)
    for row in rows.values():
        groups[row["points"]].append(row)
    ordered = []
    for points in sorted(groups, reverse=True):
        tied = groups[points]
        def sort_key(row):
            return (-row["goal_difference"], -row["goals_for"])
        tied.sort(key=lambda row: (sort_key(row), row["team"].casefold()))
        for row in tied:
            row["ranking_tie"] = [other["team"] for other in tied
                                  if other is not row and sort_key(other) == sort_key(row)]
        ordered.extend(tied)
    for rank, row in enumerate(ordered, 1):
        row["rank"] = rank
        row["mark"] = "down" if league["kind"] == "third_liga" and rank > len(ordered) - 4 else None
    return ordered


def latest_completed_sunday(through, today=None):
    today = today or datetime.now(BERLIN).date()
    cutoff = through - timedelta(days=(through.weekday() + 1) % 7)
    return cutoff - timedelta(days=7) if through == today and through.weekday() == 6 else cutoff


def weekly_cutoffs(leagues, through, today=None):
    if len(leagues) != 20 or len({league["name"] for league in leagues}) != 20:
        raise ValueError("Weekly reconstruction requires all 20 input leagues")
    openings = {league["name"]: min(datetime.fromisoformat(match["kickoff"]).astimezone(BERLIN).date()
                                    for match in league["matches"]) for league in leagues if league["matches"]}
    if len(openings) != 20:
        return [], openings
    latest = max(openings.values())
    first = latest + timedelta(days=(6 - latest.weekday()) % 7)
    last = latest_completed_sunday(through, today)
    return [first + timedelta(days=offset) for offset in range(0, (last - first).days + 1, 7)], openings


@contextmanager
def historical_inputs(tables, work_dir):
    import kompass

    work_dir.mkdir(parents=True, exist_ok=True)
    settings = {"TABLE_SNAPSHOT_OVERRIDE": tables,
                "RECALCULATION_STANDINGS": {},
                "SEASON_TRANSITIONS_FILE": str(work_dir / "season_transitions.json"),
                "ADDED_TEAMS_LOG_FILE": str(work_dir / "added_teams.log"),
                "CACHE_FILE": str(work_dir / "club_coords_cache.json")}
    previous = {name: getattr(kompass, name) for name in settings}
    try:
        for name, value in settings.items():
            setattr(kompass, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(kompass, name, value)


def prepare_weeks(dataset, through, work_dir):
    import kompass

    dates, openings = weekly_cutoffs(dataset["leagues"], through, datetime.now(BERLIN).date())
    weeks = []
    for cutoff in dates:
        tables = {league["table_key"]: reconstruct_table(league, cutoff) for league in dataset["leagues"]}
        week_dir = work_dir / cutoff.isoformat()
        week_dir.mkdir(parents=True, exist_ok=True)
        with historical_inputs(tables, week_dir), (week_dir / "selection.log").open("w", encoding="utf-8") as log, redirect_stdout(log):
            teams = kompass.build_reform_12_4_14_team_pool(80, include_reference_assignments=False)
        source_tables = [{"name": league["name"], "source_url": league["source_url"],
                          "rows": tables[league["table_key"]]} for league in dataset["leagues"]]
        selected = set(teams)
        selection_ties = []
        for table in source_tables:
            seen = set()
            for row in table["rows"]:
                group = tuple(sorted([row["team"], *row["ranking_tie"]]))
                if group not in seen and len({team in selected for team in group}) > 1:
                    selection_ties.append({"league": table["name"], "teams": list(group)})
                seen.add(group)
        weeks.append({"as_of": cutoff.isoformat(), "teams": teams, "tables": source_tables,
                      "selection_ties": selection_ties,
                      "transitions": json.loads((week_dir / "season_transitions.json").read_text(encoding="utf-8"))})
    return weeks, {name: value.isoformat() for name, value in openings.items()}


@contextmanager
def weekly_search_profile(runs):
    import kompass

    settings = {
        "MULTI_START_RUNS": runs, "MULTI_START_BASE_SEED": 1000,
        "MULTI_START_KMEANS_N_INIT": 3, "MULTI_START_CENTROID_SWAP_ITERS": 500,
        "MULTI_START_MATRIX_SWAP_ITERS": 3000, "MULTI_START_COMPONENT_SWAP_ITERS": 2000,
        "PHASE2_ELITE_COUNT": 4, "PHASE2_RESTARTS_PER_ELITE": 2, "PHASE2_BASE_SEED": 100000,
        "PHASE2_CENTROID_SWAP_ITERS": 500, "PHASE2_MATRIX_SWAP_ITERS": 5000,
        "PHASE2_COMPONENT_SWAP_ITERS": 3000,
    }
    previous = {name: getattr(kompass, name) for name in settings}
    try:
        for name, value in settings.items():
            setattr(kompass, name, value)
        yield settings
    finally:
        for name, value in previous.items():
            setattr(kompass, name, value)


def build_weekly_projections(dataset, weeks, openings, work_dir, runs):
    import kompass

    target_year = int(kompass.SEASON.split("/")[0]) + 1
    target_season = f"{target_year}/{str(target_year + 1)[-2:]}"
    grounds = load_verified_stadiums(kompass.SEASON)
    prior = load_weekly_projections(kompass.SEASON, target_season)
    previous_weeks = {week["as_of"]: week for week in prior.get("snapshots", [])}
    snapshots = []
    solutions = {}
    rules = {"reform_rule": "12+4+14+2", "extra_startplaces": kompass.REFORM_EXTRA_STARTPLACES,
             "forced_regionalliga_relegations": kompass.FORCED_REGIONALLIGA_RELEGATIONS}
    with weekly_search_profile(runs) as profile:
        search_profile = kompass.build_ranked_solutions_payload([], [], requested_runs_override=runs)["search_config"]
        for index, week in enumerate(weeks, 1):
            week_dir = work_dir / week["as_of"]
            inputs = {table["name"]: table["rows"] for table in week["tables"]}
            ground_points = {team: [grounds[team]["lat"], grounds[team]["lon"]] for team in week["teams"]}
            solution_key = fingerprint({"profile_version": 2, "profile": profile,
                                        "search_config": search_profile, "points": ground_points, "rules": rules})
            saved_path = week_dir / "projection.json"
            saved = json.loads(saved_path.read_text(encoding="utf-8")) if saved_path.exists() else {}
            previous = previous_weeks.get(week["as_of"], {})
            if saved.get("solution_key") == solution_key:
                solution = saved
            elif solution_key in solutions:
                solution = solutions[solution_key]
            elif previous.get("id") == f"weekly:{week['as_of']}:{solution_key[:12]}":
                solution = {"solution_key": solution_key, "assignments": previous["assignments"],
                            "score_avg_away_km": previous["score_avg_away_km"], "search_config": prior["search_profile"],
                            "calculated_at": previous["calculated_at"]}
            else:
                with (week_dir / "optimization.log").open("w", encoding="utf-8") as log, redirect_stdout(log), historical_inputs({}, week_dir):
                    clubs = kompass.build_clubs(sorted(week["teams"]))
                    positions = kompass.clubs_to_array(clubs)
                    distances = kompass.compute_distance_matrix_km(clubs)
                    seeds = [(mode, kompass.build_extreme_initial_labels(clubs, mode))
                             for mode in ("north_south", "west_east")]
                    ranked = kompass.run_multi_start_search(clubs, positions, distances,
                                                            runs_override=runs, extra_initial_seeds=seeds)
                    best = ranked[0]
                    search_config = kompass.build_ranked_solutions_payload(clubs, ranked,
                                                                          requested_runs_override=runs)["search_config"]
                    assignments = kompass.labels_to_named_leagues(clubs, best["labels_matrix"], 4)
                    solution = {"solution_key": solution_key, "assignments": assignments,
                                "score_avg_away_km": round(float(best["matrix_avg_away_km"]), 4),
                                "search_config": search_config, "calculated_at": datetime.now(timezone.utc).isoformat()}
                saved_path.write_text(json.dumps(solution, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            solutions[solution_key] = solution
            if (set(solution["assignments"]) != set(week["teams"])
                    or sorted(Counter(solution["assignments"].values()).values()) != [20, 20, 20, 20]):
                raise ValueError(f"Invalid weekly allocation: {week['as_of']}")
            as_of = date.fromisoformat(week["as_of"])
            snapshots.append({
                **week, "kind": "reconstructed", "id": f"weekly:{week['as_of']}:{solution_key[:12]}",
                "captured_at": datetime.combine(as_of, time.max, tzinfo=BERLIN).astimezone(timezone.utc).isoformat(),
                "calculated_at": solution.get("calculated_at") or previous.get("calculated_at") or datetime.now(timezone.utc).isoformat(),
                "assignments": solution["assignments"], "score_avg_away_km": solution["score_avg_away_km"],
                "standings_hash": fingerprint(inputs), "search_config_hash": fingerprint(solution["search_config"]),
                "rules_hash": fingerprint(rules),
            })
            print(f"Weekly projection {index}/{len(weeks)}: {week['as_of']}, {solution['score_avg_away_km']:.2f} km", flush=True)
    summary = summarize_snapshots(snapshots, snapshots[-1]["assignments"], kompass.SEASON, target_season)
    payload = {"schema_version": 1, "source_season": kompass.SEASON, "target_season": target_season,
               "generated_at": datetime.now(timezone.utc).isoformat(), "result_source_retrieved_at": dataset["retrieved_at"],
               "start_policy": "all_20_leagues_started", "cutoff_timezone": "Europe/Berlin",
               "valuation_note": VALUATION_NOTE, "league_openings": openings,
               "search_profile": solution["search_config"], "snapshots": snapshots, "summary": summary}
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    path = WEEKLY_DIR / f"{kompass.SEASON_SLUG}_to_{target_season.replace('/', '_')}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    print(f"Weekly history: {path}", flush=True)
    return payload


def load_weekly_projections(source_season, target_season):
    name = f"{source_season}_to_{target_season}".replace("/", "_")
    path = WEEKLY_DIR / f"{name}.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (payload.get("schema_version") != 1 or payload.get("source_season") != source_season
            or payload.get("target_season") != target_season):
        raise ValueError(f"Invalid weekly history: {path}")
    return payload


def export_weekly_metrics(payload, output_dir=Path("outputs")):
    output_dir = Path(output_dir)
    summary = payload["summary"]
    rows = []
    for index, snapshot in enumerate(payload["snapshots"]):
        change = summary["comparisons"][index - 1] if index else {}
        rows.append({"as_of": snapshot["as_of"], "shared_count": change.get("shared_count", ""),
                     "switch_count": change.get("switch_count", ""), "switch_percent": change.get("switch_percent", ""),
                     "entered": len(change["entered"]) if change else "", "left": len(change["left"]) if change else "",
                     "avg_away_km": snapshot["score_avg_away_km"], "selection_ties": len(snapshot["selection_ties"])})
    for filename, data, columns in (
        ("kompass_weekly_changes.csv", rows, ["as_of", "shared_count", "switch_count", "switch_percent", "entered", "left", "avg_away_km", "selection_ties"]),
        ("kompass_weekly_changes_per_club.csv", summary["teams"], ["team", "switch_count", "appearances", "entries", "exits", "current_league"]),
    ):
        path = output_dir / "csv" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(data)
    path = output_dir / "json/kompass_weekly_changes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"source_season": payload["source_season"], "target_season": payload["target_season"],
                               "valuation_note": payload["valuation_note"], "weeks": rows, "summary": summary},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_weekly_history(through=None, refresh=False, runs=50, prepare_only=False):
    import kompass

    today = datetime.now(BERLIN).date()
    through = through or today
    if runs < 1 or through > today:
        raise ValueError("Use a positive search budget and a cutoff no later than today")
    cache_path = Path(f"data/weekly_results_{kompass.SEASON_SLUG}.json")
    specs = competition_specs()
    dataset = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    cutoff = latest_completed_sunday(through, today)
    boundary = datetime.combine(cutoff, time.max, tzinfo=BERLIN)
    cache_covers_week = bool(dataset) and datetime.fromisoformat(dataset["retrieved_at"]) > boundary
    if refresh or not cache_covers_week:
        session = requests.Session()
        session.headers["User-Agent"] = kompass.USER_AGENT
        leagues = []
        for spec in specs:
            leagues.append(fetch_league(spec, kompass.SEASON, today, session))
            print(f"Validated results: {spec['name']}", flush=True)
        dataset = {"schema_version": 1, "source_season": kompass.SEASON,
                   "retrieved_at": datetime.now(timezone.utc).isoformat(), "leagues": leagues,
                   "valuation_note": VALUATION_NOTE}
        cache_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if dataset["source_season"] != kompass.SEASON:
        raise ValueError("Weekly results belong to another source season")
    for league in dataset["leagues"]:
        validate_current_totals(league)
    work_dir = Path("outputs/weekly_reconstruction") / kompass.SEASON_SLUG
    weeks, openings = prepare_weeks(dataset, through, work_dir)
    if not weeks:
        print("Noch kein abgeschlossener Sonntag nach dem Start aller 20 Ligen.", flush=True)
        return {}
    grounds = load_verified_stadiums(kompass.SEASON)
    missing = sorted({team for week in weeks for team in week["teams"]} - set(grounds))
    print(json.dumps({"first_week": weeks[0]["as_of"], "last_week": weeks[-1]["as_of"],
                      "week_count": len(weeks), "missing_grounds": missing}, ensure_ascii=True), flush=True)
    (work_dir / "prepared_weeks.json").write_text(json.dumps({"openings": openings, "weeks": weeks}, ensure_ascii=False, indent=2), encoding="utf-8")
    if prepare_only:
        return {}
    if missing:
        raise RuntimeError("Missing verified home grounds for weekly projections: " + ", ".join(missing))
    return build_weekly_projections(dataset, weeks, openings, work_dir, runs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Download current certified results again")
    parser.add_argument("--through", type=date.fromisoformat, default=datetime.now(BERLIN).date())
    parser.add_argument("--prepare-only", action="store_true", help="Validate tables and list missing grounds before optimization")
    parser.add_argument("--runs", type=int, default=50, help="Same number of search starts for every weekly projection")
    args = parser.parse_args()
    update_weekly_history(args.through, args.refresh, args.runs, args.prepare_only)


if __name__ == "__main__":
    main()
