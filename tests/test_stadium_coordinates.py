import json
from pathlib import Path

import pandas as pd
import pytest

import kompass
import kompass_report
from kompass_utils import load_verified_stadiums


def test_unverified_and_wrong_season_records_are_ignored(tmp_path):
    path = tmp_path / "grounds.json"
    path.write_text(json.dumps({
        "Town centre": {"lat": 52.5, "lon": 13.4, "stadium": "Town"},
        "Old season": {"verified_season": "2025/26", "lat": 52.5, "lon": 13.4},
    }))
    assert load_verified_stadiums("2026/27", path) == {}


@pytest.mark.parametrize("change", [{"lat": float("nan")}, {"lon": 1.0}, {"venue_source_url": ""}])
def test_invalid_verified_record_fails(tmp_path, change):
    ground = dict(next(iter(load_verified_stadiums("2026/27").values())))
    ground.update(change)
    path = tmp_path / "grounds.json"
    path.write_text(json.dumps({"Club": ground}))
    with pytest.raises(ValueError):
        load_verified_stadiums("2026/27", path)


def test_clustering_ignores_old_city_and_parent_stadium_caches(tmp_path, monkeypatch):
    teams = ["Heeslinger SC", "TSV Aubstadt", "FC Bayern München II"]
    cache = tmp_path / "coords.json"
    cache.write_text(json.dumps({t: {"lat": 50.0, "lon": 8.0} for t in teams}))
    monkeypatch.setattr(kompass, "CACHE_FILE", str(cache))
    clubs = kompass.build_clubs(teams)
    grounds = load_verified_stadiums(kompass.SEASON)
    assert [(c.lat, c.lon) for c in clubs] == [(grounds[t]["lat"], grounds[t]["lon"]) for t in teams]
    assert grounds["Heeslinger SC"]["lat"] > 53
    assert grounds["TSV Aubstadt"]["lat"] > 50
    assert grounds["FC Bayern München II"]["stadium"] == "Grünwalder Stadion"


def test_unknown_club_cannot_silently_use_city_coordinate():
    with pytest.raises(RuntimeError, match="Missing verified home grounds"):
        kompass.build_clubs(["Unverified club"])


def test_report_and_overlays_use_same_ground_as_optimizer(tmp_path, monkeypatch):
    monkeypatch.setattr(kompass, "CACHE_FILE", str(tmp_path / "cache.json"))
    clubs = kompass.build_clubs(["Heeslinger SC", "FC Bayern München II"])
    df = pd.DataFrame([dict(Verein=c.name, Liga="Nord", lat=c.lat, lon=c.lon) for c in clubs])
    mapped, stats = kompass_report.resolve_map_coordinates(df)
    overlay, missing = kompass_report.resolve_overlay_coords(df, [c.name for c in clubs])
    assert stats["stadium"] == 2 and stats["fallback_club"] == 0 and not missing
    for _, row in mapped.iterrows():
        assert overlay[row["Verein"]] == (row["lat"], row["lon"])
    df.loc[0, "lat"] = 50.0
    with pytest.raises(RuntimeError, match="Stale CSV coordinates"):
        kompass_report.resolve_map_coordinates(df)


def test_all_audited_clubs_have_current_season_records():
    audit = pd.read_csv(Path(__file__).resolve().parents[1] / "data/stadium_coordinate_audit_2026_27.csv")
    grounds = load_verified_stadiums("2026/27")
    assert len(audit) == 109
    assert set(audit["team"]) <= set(grounds)
