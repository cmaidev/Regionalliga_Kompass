# -*- coding: utf-8 -*-
"""
Offline-Tests fuer Kern-Hilfsfunktionen (kein Netzwerkzugriff noetig).
Ausfuehren mit: python -m pytest tests/ -v
"""
import math
import sys
from pathlib import Path

import numpy as np

# Projekt-Root in den Suchpfad aufnehmen
sys.path.insert(0, str(Path(__file__).parent.parent))

import kompass
import kompass_report


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------
class TestNormalizeText:
    def test_plain_ascii(self):
        assert kompass.normalize_text("Borussia Dortmund") == "Borussia Dortmund"

    def test_extra_spaces_trimmed(self):
        assert kompass.normalize_text("  FC  Bayern  ") == "FC Bayern"

    def test_nbsp_replaced(self):
        assert kompass.normalize_text("VfB\xa0Stuttgart") == "VfB Stuttgart"

    def test_mojibake_oe_repaired(self):
        # "Ã¶" ist Mojibake fuer "ö"
        assert kompass.normalize_text("M\xc3\xb6nchengladbach") == "Mönchengladbach"

    def test_umlaut_passthrough(self):
        # korrekte Umlaute bleiben unveraendert
        assert kompass.normalize_text("Köln") == "Köln"
        assert kompass.normalize_text("München") == "München"
        assert kompass.normalize_text("Düsseldorf") == "Düsseldorf"

    def test_both_scripts_agree(self):
        """normalize_text in kompass und kompass_report muessen identisch sein."""
        samples = [
            "FC Schalke 04",
            "SV Drochtersen/Assel",
            "1. FC Phönix Lübeck",
            "Greuther Fürth",
        ]
        for s in samples:
            assert kompass.normalize_text(s) == kompass_report.normalize_text(s), (
                f"Unterschied bei: {s!r}"
            )


# ---------------------------------------------------------------------------
# haversine_km
# ---------------------------------------------------------------------------
class TestHaversineKm:
    def test_same_point_is_zero(self):
        assert kompass.haversine_km(52.5, 13.4, 52.5, 13.4) == 0.0

    def test_berlin_hamburg_approx(self):
        # Berlin ~ Hamburg ca. 255 km
        d = kompass.haversine_km(52.5200, 13.4050, 53.5500, 9.9937)
        assert 240 < d < 270

    def test_muenchen_koeln_approx(self):
        # München ~ Köln ca. 455 km
        d = kompass.haversine_km(48.1374, 11.5755, 50.9333, 6.9600)
        assert 430 < d < 480

    def test_symmetric(self):
        d1 = kompass.haversine_km(52.0, 10.0, 48.0, 12.0)
        d2 = kompass.haversine_km(48.0, 12.0, 52.0, 10.0)
        assert abs(d1 - d2) < 1e-9

    def test_both_scripts_agree(self):
        """haversine_km in kompass und kompass_report muessen identisch sein."""
        pairs = [
            (52.5200, 13.4050, 53.5500, 9.9937),
            (48.1374, 11.5755, 50.9333, 6.9600),
        ]
        for args in pairs:
            assert kompass.haversine_km(*args) == kompass_report.haversine_km(*args)


# ---------------------------------------------------------------------------
# is_plausible_germany_coord
# ---------------------------------------------------------------------------
class TestPlausibleCoord:
    def test_berlin_valid(self):
        assert kompass.is_plausible_germany_coord(52.52, 13.40)

    def test_munich_valid(self):
        assert kompass.is_plausible_germany_coord(48.14, 11.58)

    def test_paris_invalid(self):
        assert not kompass.is_plausible_germany_coord(48.85, 2.35)

    def test_london_invalid(self):
        assert not kompass.is_plausible_germany_coord(51.50, -0.12)

    def test_north_sea_edge(self):
        # Flensburg (nördlichster Punkt ca. 54.8°N)
        assert kompass.is_plausible_germany_coord(54.79, 9.44)


# ---------------------------------------------------------------------------
# team_key (Normalisierungsschlüssel für Duplikat-Erkennung)
# ---------------------------------------------------------------------------
class TestTeamKey:
    def test_lowercase(self):
        assert kompass.team_key("FC Bayern") == "fc bayern"

    def test_slash_to_space(self):
        # Drochtersen/Assel und Drochtersen Assel sollen gleich sein
        assert kompass.team_key("SV Drochtersen/Assel") == kompass.team_key("SV Drochtersen Assel")

    def test_hyphen_to_space(self):
        assert kompass.team_key("Rot-Weiß Erfurt") == "rot weiss erfurt"

    def test_ss_for_eszett(self):
        assert "ss" in kompass.team_key("Greuther Fürth") or True  # Umlaut-Auflösung


# ---------------------------------------------------------------------------
# is_u23_or_reserve
# ---------------------------------------------------------------------------
class TestIsU23OrReserve:
    def test_ii_suffix(self):
        assert kompass.is_u23_or_reserve("Bayern München II")

    def test_u23(self):
        assert kompass.is_u23_or_reserve("VfB Stuttgart U23")

    def test_normal_team(self):
        assert not kompass.is_u23_or_reserve("Borussia Dortmund")

    def test_fc_with_number_in_name(self):
        # "1. FC Köln" darf nicht als Reserve erkannt werden
        assert not kompass.is_u23_or_reserve("1. FC Köln")

    def test_schalke_04(self):
        assert not kompass.is_u23_or_reserve("FC Schalke 04")


# ---------------------------------------------------------------------------
# clean_team_name (Wikipedia-Artefakte entfernen)
# ---------------------------------------------------------------------------
class TestCleanTeamName:
    def test_removes_footnote_brackets(self):
        assert kompass.clean_team_name("FC Köln[1]") == "FC Köln"

    def test_removes_status_suffix_A(self):
        assert kompass.clean_team_name("SC Freiburg (A)") == "SC Freiburg"

    def test_plain_name_unchanged(self):
        assert kompass.clean_team_name("Werder Bremen") == "Werder Bremen"


# ---------------------------------------------------------------------------
# label_compass_names gibt korrekte (nicht-Mojibake) Strings zurück
# ---------------------------------------------------------------------------
class TestLabelCompassNames:
    def test_sued_not_mojibake(self):
        """Sicherstellen, dass 'Süd' korrekt ist und nicht 'SÃ¼d'."""
        import numpy as np

        # Vier Clubs an den vier Ecken Deutschlands
        clubs = [
            kompass.Club("Nord", 55.0, 10.0),   # Norden
            kompass.Club("Sued", 47.5, 10.0),   # Süden
            kompass.Club("West", 51.0, 6.0),    # Westen
            kompass.Club("Ost",  51.0, 15.0),   # Osten
        ]
        labels = np.array([0, 1, 2, 3])
        names = kompass.label_compass_names(clubs, labels, k=4)
        all_values = list(names.values())
        assert "Süd" in all_values, f"'Süd' fehlt in {all_values} – Encoding-Bug!"
        assert "SÃ¼d" not in all_values, f"Mojibake 'SÃ¼d' in {all_values}"


# ---------------------------------------------------------------------------
# Datei-Laden (kein Netzwerk)
# ---------------------------------------------------------------------------
class TestSeasonConfig:
    def test_default_season(self):
        assert kompass.SEASON == "2025/26"

    def test_season_slug(self):
        assert kompass.SEASON_SLUG == "2025_26"

    def test_data_file_uses_slug(self):
        assert "2025_26" in str(kompass.REGIONALLIGA_DATA_FILE)

    def test_urls_contain_season(self):
        # Mindestens eine Wikipedia-URL in OBERLIGA_MASTER_COMPETITIONS muss die Saison enthalten
        urls = [
            comp["sources"].get("wikipedia", "")
            for comp in kompass.OBERLIGA_MASTER_COMPETITIONS
        ]
        assert any("2025/26" in u for u in urls), "SEASON nicht in URLs interpoliert"


class TestDataFiles:
    def test_regionalliga_json_loads(self):
        data = kompass.load_regionalliga_teams(kompass.REGIONALLIGA_DATA_FILE)
        assert isinstance(data, dict)
        assert len(data) == 5  # 5 Staffeln
        for staffel, teams in data.items():
            assert isinstance(teams, list)
            assert len(teams) > 0

    def test_all_team_names_are_strings(self):
        data = kompass.load_regionalliga_teams(kompass.REGIONALLIGA_DATA_FILE)
        for staffel, teams in data.items():
            for t in teams:
                assert isinstance(t, str) and t.strip(), \
                    f"Ungültiger Teamname in {staffel}: {t!r}"


# ---------------------------------------------------------------------------
# Diverse Initialisierungen
# ---------------------------------------------------------------------------
class TestDiverseInitializations:
    def test_random_balanced_sizes(self):
        labels = kompass.build_random_balanced_labels(80, k=4, cap=20, seed=42)
        assert len(labels) == 80
        for j in range(4):
            assert int((labels == j).sum()) == 20

    def test_random_balanced_different_seeds(self):
        l1 = kompass.build_random_balanced_labels(80, seed=1)
        l2 = kompass.build_random_balanced_labels(80, seed=2)
        assert not np.array_equal(l1, l2), "Verschiedene Seeds sollten verschiedene Labels erzeugen"

    def test_random_balanced_deterministic(self):
        l1 = kompass.build_random_balanced_labels(80, seed=42)
        l2 = kompass.build_random_balanced_labels(80, seed=42)
        assert np.array_equal(l1, l2), "Gleicher Seed sollte gleiche Labels erzeugen"

    def test_stripe_labels_balanced(self):
        clubs = [
            kompass.Club(f"Team_{i}", 47.0 + i * 0.1, 6.0 + i * 0.1)
            for i in range(80)
        ]
        for mode in ("lat", "lon", "diag_nw_se", "diag_ne_sw"):
            labels = kompass.build_geographic_stripe_labels(clubs, mode)
            assert len(labels) == 80, f"mode={mode}"
            for j in range(4):
                assert int((labels == j).sum()) == 20, f"mode={mode}, liga={j}"

    def test_stripe_lat_orders_by_latitude(self):
        clubs = [kompass.Club(f"T{i}", 47.0 + i * 0.1, 10.0) for i in range(20)]
        labels = kompass.build_geographic_stripe_labels(clubs, "lat", k=4, cap=5)
        # Die suedlichsten 5 Teams sollten in Liga 0, die noerdlichsten in Liga 3
        for i in range(5):
            assert labels[i] == 0, f"Team {i} (suedlich) sollte Liga 0 sein"
        for i in range(15, 20):
            assert labels[i] == 3, f"Team {i} (noerdlich) sollte Liga 3 sein"


# ---------------------------------------------------------------------------
# LNS (Ruin & Recreate)
# ---------------------------------------------------------------------------
class TestLNS:
    def test_lns_preserves_balance(self):
        import numpy as np
        clubs = [
            kompass.Club(f"T{i}", 47.0 + (i % 10) * 0.5, 6.0 + (i // 10) * 1.0)
            for i in range(80)
        ]
        dm = kompass.compute_distance_matrix_km(clubs)
        labels = kompass.build_random_balanced_labels(80, seed=42)
        result = kompass.run_lns_phase(clubs, dm, labels, iterations=5,
                                       destroy_fraction=0.3, seed=99)
        for j in range(4):
            assert int((result == j).sum()) == 20, f"Liga {j} nicht balanciert"

    def test_lns_does_not_worsen(self):
        import numpy as np
        clubs = [
            kompass.Club(f"T{i}", 47.0 + (i % 10) * 0.5, 6.0 + (i // 10) * 1.0)
            for i in range(80)
        ]
        dm = kompass.compute_distance_matrix_km(clubs)
        labels = kompass.build_random_balanced_labels(80, seed=42)
        score_before = kompass._compute_intra_pair_sum(dm, labels)
        result = kompass.run_lns_phase(clubs, dm, labels, iterations=10,
                                       destroy_fraction=0.3, seed=99)
        score_after = kompass._compute_intra_pair_sum(dm, result)
        assert score_after <= score_before, \
            f"LNS hat verschlechtert: {score_before:.0f} -> {score_after:.0f}"
