"""Persist successful Rank-1 projections and compare consecutive recalculations."""

from collections import Counter
import csv
import hashlib
from itertools import permutations
import json
from pathlib import Path
import re

from kompass_utils import normalize_text


HISTORY_DIR = Path("data/recalculation_history")


def fingerprint(value):
    if value is None:
        return None
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def history_path(source_season, target_season, history_dir=HISTORY_DIR):
    if not all(re.fullmatch(r"\d{4}/\d{2}", season) for season in (source_season, target_season)):
        raise ValueError("Invalid history season")
    name = f"{source_season}_to_{target_season}".replace("/", "_")
    return Path(history_dir) / f"{name}.json"


def load_history(source_season, target_season, history_dir=HISTORY_DIR):
    path = history_path(source_season, target_season, history_dir)
    if not path.exists():
        return {"schema_version": 1, "source_season": source_season,
                "target_season": target_season, "snapshots": []}
    history = json.loads(path.read_text(encoding="utf-8"))
    if (history.get("schema_version") != 1
            or history.get("source_season") != source_season
            or history.get("target_season") != target_season
            or not isinstance(history.get("snapshots"), list)):
        raise ValueError(f"Invalid recalculation history: {path}")
    return history


def record_snapshot(source_season, target_season, snapshot, history_dir=HISTORY_DIR):
    history = load_history(source_season, target_season, history_dir)
    for existing in history["snapshots"]:
        if existing["id"] == snapshot["id"]:
            if existing["assignments"] != snapshot["assignments"]:
                raise ValueError("A saved recalculation cannot change its assignments")
            return False
    history["snapshots"].append(snapshot)
    path = history_path(source_season, target_season, history_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return True


def record_output_snapshot(standings=None, root=Path(".")):
    root = Path(root)
    ranked_path = root / "outputs/json/kompass_solutions_ranked.json"
    transitions_path = root / "season_transitions.json"
    csv_path = root / "outputs/csv/kompass_regionalliga_4x20.csv"
    if not all(path.exists() for path in (ranked_path, transitions_path, csv_path)):
        return False
    ranked = json.loads(ranked_path.read_text(encoding="utf-8"))
    transitions = json.loads(transitions_path.read_text(encoding="utf-8"))
    best = next((entry for entry in ranked.get("solutions", []) if entry.get("rank") == 1), None)
    if not best or not ranked.get("generated_at"):
        return False
    assignments = {}
    for league, teams in best["teams_by_league"].items():
        for team in teams:
            name = normalize_text(team)
            if name in assignments:
                raise ValueError(f"Duplicate team in Rank-1 snapshot: {name}")
            assignments[name] = normalize_text(league)
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    csv_assignments = {normalize_text(row["Verein"]): normalize_text(row["Liga"]) for row in rows}
    if (len(rows) != 80 or len(assignments) != 80 or csv_assignments != assignments
            or sorted(Counter(assignments.values()).values()) != [20, 20, 20, 20]):
        return False
    source_season = transitions.get("source_season")
    target_season = transitions.get("target_season")
    if not source_season or not target_season:
        return False
    snapshot = {
        "id": ranked["generated_at"],
        "captured_at": ranked["generated_at"],
        "assignments": dict(sorted(assignments.items())),
        "standings_hash": fingerprint(standings) if standings else None,
        "search_config_hash": fingerprint(ranked.get("search_config")),
        "rules_hash": fingerprint({key: transitions.get(key) for key in (
            "reform_rule", "extra_startplaces", "forced_regionalliga_relegations")}),
    }
    return record_snapshot(source_season, target_season, snapshot, root / HISTORY_DIR)


def compare_assignments(previous, current):
    old_leagues = sorted(set(previous.values()))
    new_leagues = sorted(set(current.values()))
    if len(old_leagues) != len(new_leagues):
        raise ValueError("Cannot compare allocations with different league counts")
    shared = set(previous) & set(current)
    mappings = [dict(zip(new_leagues, order)) for order in permutations(old_leagues)]
    mapping = max(mappings, key=lambda candidate: (
        sum(previous[team] == candidate[current[team]] for team in shared),
        sum(new == old for new, old in candidate.items()),
    ))
    switched = [
        {"team": team, "from_league": previous[team], "to_league": current[team],
         "to_previous_league": mapping[current[team]]}
        for team in sorted(shared)
        if previous[team] != mapping[current[team]]
    ]
    league_changes = []
    for league in new_leagues:
        before = {team for team, old in previous.items() if old == mapping[league]}
        after = {team for team, new in current.items() if new == league}
        league_changes.append({"league": league, "previous_league": mapping[league],
                               "added": len(after - before), "removed": len(before - after)})
    return {
        "shared_count": len(shared), "switch_count": len(switched),
        "switch_percent": round(100 * len(switched) / len(shared), 1) if shared else None,
        "switched": switched, "entered": sorted(set(current) - set(previous)),
        "left": sorted(set(previous) - set(current)), "league_changes": league_changes,
    }


def build_history_report(source_season, target_season, current_assignments, run_id,
                         history_dir=HISTORY_DIR):
    empty = {"available": False, "source_season": source_season, "target_season": target_season}
    snapshots = load_history(source_season, target_season, history_dir)["snapshots"]
    if not snapshots:
        return dict(empty, reason="not_started")
    if snapshots[-1]["id"] != run_id or snapshots[-1]["assignments"] != current_assignments:
        return dict(empty, reason="stale")
    return summarize_snapshots(snapshots, current_assignments, source_season, target_season)


def summarize_snapshots(snapshots, current_assignments, source_season, target_season):
    teams = {}
    comparisons = []
    for index, snapshot in enumerate(snapshots):
        for team, league in snapshot["assignments"].items():
            counts = teams.setdefault(team, {"team": team, "switch_count": 0,
                                            "appearances": 0, "entries": 0, "exits": 0})
            counts["appearances"] += 1
        if index == 0:
            continue
        previous = snapshots[index - 1]
        change = compare_assignments(previous["assignments"], snapshot["assignments"])
        old_hash, new_hash = previous.get("standings_hash"), snapshot.get("standings_hash")
        change.update({
            "captured_at": snapshot["captured_at"], "previous_at": previous["captured_at"],
            "tables_changed": old_hash != new_hash if old_hash and new_hash else None,
            "settings_changed": any(previous.get(key) != snapshot.get(key)
                                    for key in ("search_config_hash", "rules_hash")),
        })
        comparisons.append(change)
        for switch in change["switched"]:
            teams[switch["team"]]["switch_count"] += 1
        for team in change["entered"]:
            teams[team]["entries"] += 1
        for team in change["left"]:
            teams[team]["exits"] += 1
    for team, counts in teams.items():
        counts["current_league"] = current_assignments.get(team, "–")
    return {
        "available": True, "source_season": source_season, "target_season": target_season,
        "snapshot_count": len(snapshots), "baseline_at": snapshots[0]["captured_at"],
        "comparison_count": len(comparisons),
        "allocation_changes": sum(bool(c["switch_count"] or c["entered"] or c["left"]) for c in comparisons),
        "switch_total": sum(c["switch_count"] for c in comparisons),
        "latest": comparisons[-1] if comparisons else None,
        "comparisons": comparisons,
        "teams": sorted(teams.values(), key=lambda counts: (-counts["switch_count"], counts["team"])),
    }


def export_history_report(report, json_path, csv_path):
    json_path, csv_path = Path(json_path), Path(csv_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["team", "switch_count", "appearances",
                                                    "entries", "exits", "current_league"])
        writer.writeheader()
        writer.writerows(report.get("teams", []))
