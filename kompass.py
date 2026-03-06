"""
Kompass-Regionalliga-Reform (4 x 20 Teams), aktueller Modus.

Was das Script macht:
1) Baut den Saison-Pool ueber die Reformlogik 12+4+14+2:
   - je Regionalliga Platz 2-13
   - 4 Absteiger aus der 3. Liga
   - 14 Oberliga-Meister
   - 2 Zusatzplaetze (aktuell Bayern + Nordost)
2) Reserve-/U-Teams sind im Reformmodus erlaubt.
3) Holt Team-Koordinaten primaer ueber FuPa, dann Wikipedia
   (mit Cache/Overrides und optionalem Nominatim-Fallback).
4) Optimiert die 4 Ligen mit Multi-Start + Distanzmatrix
   (Rank 1 ist Hauptausgabe).
5) Exportiert mehrere Ranks (1, 2, 3, 5, 10), die schlechteste
   gefundene Loesung ("worst") sowie Ranking-Metadaten als JSON.
6) Schreibt Ergebnisse in:
   - outputs/csv
   - outputs/json

Hinweis:
- Karten, Kennzahlen und index.html werden von kompass_report.py erzeugt
  (Ausgabe nach outputs/html, outputs/csv, outputs/json).
"""

from __future__ import annotations

import json
import itertools
import os
import re
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from sklearn.cluster import KMeans

from kompass_utils import Club, ensure_parent_dir, haversine_km, normalize_text


# -------------------------
# Konfiguration
# -------------------------

# Saison (Format "JJJJ/JJ") – einzige Stelle, die bei Saisonwechsel angepasst werden muss.
SEASON: str = os.getenv("KOMPASS_SEASON", "2025/26")
SEASON_SLUG: str = SEASON.replace("/", "_")  # "2025_26" (fuer Dateinamen)

N_LEAGUES = 4
TEAMS_PER_LEAGUE = 20
TARGET_TEAM_COUNT = N_LEAGUES * TEAMS_PER_LEAGUE
ENFORCE_DERBY_SAME_LEAGUE = False
DERBY_MAX_DISTANCE_KM = 50.0

EXCLUDE_U23_TEAMS = False
USE_RULE_BASED_SEASON_LOGIC = True
USE_REFORM_12_4_14_RULE = True

# Wenn nach Ausschluss der U23/II-Teams weniger als 80 Teams übrig sind:
FILL_UP_WITH_TIER5_FROM_WIKIPEDIA = True
# Wenn du ausschließlich mit Regionalliga-Teams arbeiten willst, setze:
# FILL_UP_WITH_TIER5_FROM_WIKIPEDIA = False
#
# Wenn dann <80 Teams übrig sind, bricht das Script mit Fehlermeldung ab.

# Koordinaten: primär Wikipedia, optional Fallback Nominatim
# auf False setzen, wenn du nur Wikipedia-Koordinaten willst
USE_NOMINATIM_FALLBACK = True
NOMINATIM_MIN_SECONDS = 1.1     # Rate limit (freundlich bleiben)

# Wikipedia-Seitentitel, falls Vereinsname nicht exakt passt
WIKI_TITLE_OVERRIDES = {
    # Fußball-Seite (nicht die Turn-Seite)
    "TSG Balingen": "TSG Balingen",
    "SV Atlas Delmenhorst": "SV Atlas Delmenhorst (2012)",
}

# Wenn Nominatim bei manchen Vereinen zickt: explizite Orts-Queries
GEOCODE_QUERY_OVERRIDES = {
    "SG Barockstadt Fulda-Lehnerz": "Fulda, Germany",
    "TSV Steinbach Haiger": "Haiger, Germany",
    "SGV Freiberg": "Freiberg am Neckar, Germany",
    "SSVg Velbert": "Velbert, Germany",
    "FSV Schöningen": "Schöningen, Germany",
    "1. FC Phönix Lübeck": "Lübeck, Germany",
    "SC Fortuna Köln": "Köln, Germany",
}

TEAM_NAME_NORMALIZATION_OVERRIDES = {
    "1. FC Germania Egestorf-Langreder": "1. FC Germania Egestorf/Langreder",
    "BSV Kickers Emden": "Kickers Emden",
    "RW Oberhausen": "Rot-Weiß Oberhausen",
    "SV Eintracht Trier 05": "SV Eintracht Trier",
    "SpVgg Ansbach": "SpVgg Ansbach 09",
    "FC Würzburger Kickers": "Würzburger Kickers",
    "SV Wacker Burghausen": "Wacker Burghausen",
    "SV Stuttgarter Kickers": "Stuttgarter Kickers",
    "SSV Ulm 1846 Fußball": "SSV Ulm 1846",
    "SG Barockstadt Fulda Lehnerz": "SG Barockstadt Fulda-Lehnerz",
}

# Harte Koordinaten-Overrides fuer nachweislich fehlerhafte Treffer.
CLUB_COORD_OVERRIDES: Dict[str, Tuple[float, float]] = {
    # Homburg (Saarland)
    "FC 08 Homburg": (49.316666666667, 7.3333333333333),
    # SC Fortuna Köln (Köln-Südstadion)
    "SC Fortuna Köln": (50.92245, 6.97423),
    "SG Barockstadt Fulda Lehnerz": (50.555809, 9.680845),
    "SG Barockstadt Fulda-Lehnerz": (50.555809, 9.680845),
}


CACHE_FILE = "club_coords_cache.json"
ADDED_TEAMS_LOG_FILE = "added_teams.log"
SEASON_TRANSITIONS_FILE = "season_transitions.json"
OUTPUT_DIR = "outputs"
OUTPUT_CSV_DIR = os.path.join(OUTPUT_DIR, "csv")
OUTPUT_JSON_DIR = os.path.join(OUTPUT_DIR, "json")
OUT_CSV_DEFAULT = os.path.join(OUTPUT_CSV_DIR, "kompass_regionalliga_4x20.csv")
OUT_CSV_INITIAL = os.path.join(
    OUTPUT_CSV_DIR, "kompass_regionalliga_4x20_initial.csv")
OUT_CSV_INITIAL_AUTO = os.path.join(
    OUTPUT_CSV_DIR, "kompass_regionalliga_4x20_initial_auto.csv")
OUT_CSV_INITIAL_MANUAL = os.path.join(
    OUTPUT_CSV_DIR, "kompass_regionalliga_4x20_initial_manual.csv")
OUT_CSV_INITIAL_NORTH_SOUTH = os.path.join(
    OUTPUT_CSV_DIR, "kompass_regionalliga_4x20_initial_north_south.csv")
OUT_CSV_INITIAL_WEST_EAST = os.path.join(
    OUTPUT_CSV_DIR, "kompass_regionalliga_4x20_initial_west_east.csv")
OUT_CSV_MATRIX = os.path.join(
    OUTPUT_CSV_DIR, "kompass_regionalliga_4x20_matrix.csv")
OUT_CSV_MATRIX_RANK2 = os.path.join(
    OUTPUT_CSV_DIR, "kompass_regionalliga_4x20_matrix_rank2.csv")
OUT_CSV_MATRIX_RANK3 = os.path.join(
    OUTPUT_CSV_DIR, "kompass_regionalliga_4x20_matrix_rank3.csv")
OUT_CSV_MATRIX_RANK5 = os.path.join(
    OUTPUT_CSV_DIR, "kompass_regionalliga_4x20_matrix_rank5.csv")
OUT_CSV_MATRIX_RANK10 = os.path.join(
    OUTPUT_CSV_DIR, "kompass_regionalliga_4x20_matrix_rank10.csv")
OUT_CSV_MATRIX_WORST = os.path.join(
    OUTPUT_CSV_DIR, "kompass_regionalliga_4x20_matrix_worst.csv")
OUT_SOLUTIONS_RANKED_JSON = os.path.join(
    OUTPUT_JSON_DIR, "kompass_solutions_ranked.json")
OUT_SOLUTION_DIFF_CSV = os.path.join(
    OUTPUT_CSV_DIR, "kompass_solution_diff.csv")
WIKIPEDIA_API = "https://de.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "CompassRegionalligaBot/1.0 (your_email_or_github_here)"

# Multi-Start: viele eingeschraenkte lokale Durchlaeufe fuer robustere "best-of"-Suche.
ENABLE_MULTI_START_SEARCH = True
MULTI_START_RUNS = int(os.getenv("KOMPASS_MULTI_START_RUNS", "2000"))
MULTI_START_BASE_SEED = int(os.getenv("KOMPASS_MULTI_START_BASE_SEED", "1000"))
MULTI_START_KMEANS_N_INIT = int(
    os.getenv("KOMPASS_MULTI_START_KMEANS_N_INIT", "5"))
MULTI_START_CENTROID_SWAP_ITERS = int(
    os.getenv("KOMPASS_MULTI_START_CENTROID_ITERS", "2000"))
MULTI_START_MATRIX_SWAP_ITERS = int(
    os.getenv("KOMPASS_MULTI_START_MATRIX_ITERS", "9000"))
MULTI_START_COMPONENT_SWAP_ITERS = int(
    os.getenv("KOMPASS_MULTI_START_COMPONENT_ITERS", "7000"))
TOP_SOLUTIONS_TO_EXPORT = int(os.getenv("KOMPASS_TOP_SOLUTIONS", "10"))
DISPLAY_MATRIX_RANKS: List[int] = [1, 2, 3, 5, 10]
MULTI_START_SHAKE_SWAP_FRACTION = float(
    os.getenv("KOMPASS_MULTI_START_SHAKE_SWAP_FRACTION", "0.02"))
MATRIX_ACCEPT_EQUAL_PROB = float(
    os.getenv("KOMPASS_MATRIX_ACCEPT_EQUAL_PROB", "0.02"))
MATRIX_ANNEAL_START_TEMP_KM = float(
    os.getenv("KOMPASS_MATRIX_ANNEAL_START_TEMP_KM", "60.0"))
MATRIX_ANNEAL_END_TEMP_KM = float(
    os.getenv("KOMPASS_MATRIX_ANNEAL_END_TEMP_KM", "1.0"))
MATRIX_MOVE_2_PROB = float(os.getenv("KOMPASS_MATRIX_MOVE_2_PROB", "0.80"))
MATRIX_MOVE_3_PROB = float(os.getenv("KOMPASS_MATRIX_MOVE_3_PROB", "0.15"))
MATRIX_MOVE_4_PROB = float(os.getenv("KOMPASS_MATRIX_MOVE_4_PROB", "0.05"))
MATRIX_STAGNATION_SHAKE_ITERS = int(
    os.getenv("KOMPASS_MATRIX_STAGNATION_SHAKE_ITERS", "2500"))
MATRIX_STAGNATION_SHAKE_FRACTION = float(
    os.getenv("KOMPASS_MATRIX_STAGNATION_SHAKE_FRACTION", "0.02"))
PHASE2_ELITE_COUNT = int(os.getenv("KOMPASS_PHASE2_ELITE_COUNT", "8"))
PHASE2_ELITE_SELECTION_MODE = os.getenv(
    "KOMPASS_PHASE2_ELITE_SELECTION_MODE", "diverse"
).strip().lower()
PHASE2_DIVERSE_POOL_MULTIPLIER = int(
    os.getenv("KOMPASS_PHASE2_DIVERSE_POOL_MULTIPLIER", "6"))
PHASE2_DIVERSE_MAX_SCORE_GAP_KM = float(
    os.getenv("KOMPASS_PHASE2_DIVERSE_MAX_SCORE_GAP_KM", "4.0"))
PHASE2_RESTARTS_PER_ELITE = int(
    os.getenv("KOMPASS_PHASE2_RESTARTS_PER_ELITE", "5"))
PHASE2_BASE_SEED = int(os.getenv("KOMPASS_PHASE2_BASE_SEED", "100000"))
PHASE2_CENTROID_SWAP_ITERS = int(
    os.getenv("KOMPASS_PHASE2_CENTROID_ITERS", "1500"))
PHASE2_MATRIX_SWAP_ITERS = int(
    os.getenv("KOMPASS_PHASE2_MATRIX_ITERS", "15000"))
PHASE2_COMPONENT_SWAP_ITERS = int(
    os.getenv("KOMPASS_PHASE2_COMPONENT_ITERS", "12000"))
PHASE2_SHAKE_SWAP_FRACTION = float(
    os.getenv("KOMPASS_PHASE2_SHAKE_SWAP_FRACTION", "0.08"))
PHASE2_MATRIX_ACCEPT_EQUAL_PROB = float(
    os.getenv("KOMPASS_PHASE2_ACCEPT_EQUAL_PROB", "0.05"))
PHASE2_MATRIX_ANNEAL_START_TEMP_KM = float(
    os.getenv("KOMPASS_PHASE2_ANNEAL_START_TEMP_KM", "120.0"))
PHASE2_MATRIX_ANNEAL_END_TEMP_KM = float(
    os.getenv("KOMPASS_PHASE2_ANNEAL_END_TEMP_KM", "2.0"))
PHASE2_MATRIX_MOVE_2_PROB = float(
    os.getenv("KOMPASS_PHASE2_MOVE_2_PROB", str(MATRIX_MOVE_2_PROB)))
PHASE2_MATRIX_MOVE_3_PROB = float(
    os.getenv("KOMPASS_PHASE2_MOVE_3_PROB", str(MATRIX_MOVE_3_PROB)))
PHASE2_MATRIX_MOVE_4_PROB = float(
    os.getenv("KOMPASS_PHASE2_MOVE_4_PROB", str(MATRIX_MOVE_4_PROB)))
PHASE2_MATRIX_STAGNATION_SHAKE_ITERS = int(
    os.getenv(
        "KOMPASS_PHASE2_STAGNATION_SHAKE_ITERS",
        str(max(1, MATRIX_STAGNATION_SHAKE_ITERS // 2)),
    )
)
PHASE2_MATRIX_STAGNATION_SHAKE_FRACTION = float(
    os.getenv(
        "KOMPASS_PHASE2_STAGNATION_SHAKE_FRACTION",
        str(max(0.03, MATRIX_STAGNATION_SHAKE_FRACTION * 1.8)),
    )
)
EXPORT_INITIAL_ONLY = os.getenv("KOMPASS_EXPORT_INITIAL_ONLY", "0").lower() in {
    "1", "true", "yes"
}
INITIAL_CSV_OVERRIDE = os.getenv("KOMPASS_INITIAL_CSV_OVERRIDE", "").strip()



# -------------------------
# Daten: Regionalligen 2025/26 (aus den Wikipedia-Saisonartikeln)
# -------------------------
REGIONALLIGA_DATA_FILE = Path(f"data/regionalliga_{SEASON_SLUG}.json")


def load_regionalliga_teams(path: Path) -> Dict[str, List[str]]:
    if not path.exists():
        raise FileNotFoundError(
            f"Regionalliga-Daten fehlen: {path}. "
            "Bitte Datei anlegen/committen."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Regionalliga-Daten unlesbar ({path}): {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(
            f"Regionalliga-Daten muessen ein Objekt sein: {path}")

    out: Dict[str, List[str]] = {}
    for league, teams in raw.items():
        if not isinstance(league, str):
            raise RuntimeError(f"Ungueltiger Liga-Key in {path}: {league!r}")
        if not isinstance(teams, list) or not all(isinstance(t, str) for t in teams):
            raise RuntimeError(
                f"Ungueltige Teamliste fuer Liga '{league}' in {path}")
        out[league] = [t.strip() for t in teams if t.strip()]
    return out


REGIONALLIGA_TEAMS: Dict[str, List[str]
                           ] = load_regionalliga_teams(REGIONALLIGA_DATA_FILE)

# Oberliga-/5.-Liga-Seiten (Wikipedia), um nach Ausschluss von U23/II-Teams auf 80 Teams aufzufüllen
# (Es werden Tabellen gelesen und in Tabellenreihenfolge "oben nach unten" Kandidaten entnommen.)
TIER5_WIKI_URLS: List[str] = [
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Niedersachsen_{SEASON}",
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Schleswig-Holstein_{SEASON}",
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Hamburg_{SEASON}",
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Bremen-Liga_{SEASON}",
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Westfalen_{SEASON}",
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Niederrhein_{SEASON}",
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Mittelrheinliga_{SEASON}",
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Nordost_{SEASON}",
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Baden-W%C3%BCrttemberg_{SEASON}",
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Hessenliga_{SEASON}",
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Rheinland-Pfalz/Saar_{SEASON}",
    f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Bayernliga_{SEASON}",
]

TABLE_SOURCE_PRIORITY: List[str] = ["fupa", "wikipedia"]

REGIONALLIGA_TABLE_URLS: Dict[str, Dict[str, str]] = {
    "Nord": {
        "fupa": "https://www.fupa.net/league/regionalliga-nord/standing",
        "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Regionalliga_Nord_{SEASON}",
    },
    "Nordost": {
        "fupa": "https://www.fupa.net/league/regionalliga-nordost/standing",
        "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Regionalliga_Nordost_{SEASON}",
    },
    "West": {
        "fupa": "https://www.fupa.net/league/regionalliga-west/standing",
        "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Regionalliga_West_{SEASON}",
    },
    "Bayern": {
        "fupa": "https://www.fupa.net/league/regionalliga-bayern/standing",
        "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Regionalliga_Bayern_{SEASON}",
    },
    "Südwest": {
        "fupa": "https://www.fupa.net/league/regionalliga-suedwest/standing",
        "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Regionalliga_S%C3%BCdwest_{SEASON}",
    },
}

THIRD_LIGA_TABLE_URLS: Dict[str, str] = {
    "fupa": "https://www.fupa.net/league/3-liga/standing",
    "wikipedia": f"https://de.wikipedia.org/wiki/3._Fu%C3%9Fball-Liga_{SEASON}",
}

TIER5_TABLE_URLS: Dict[str, List[str]] = {
    "fupa": [
        "https://www.fupa.net/league/oberliga-niedersachsen/standing",
        "https://www.fupa.net/league/oberliga-schleswig-holstein/standing",
        "https://www.fupa.net/league/oberliga-hamburg/standing",
        "https://www.fupa.net/league/bremen-liga/standing",
        "https://www.fupa.net/league/oberliga-westfalen/standing",
        "https://www.fupa.net/league/oberliga-niederrhein/standing",
        "https://www.fupa.net/league/mittelrheinliga/standing",
        # NOFV-Oberliga URLs sind auf FuPa nicht stabil auffindbar -> Wikipedia-Fallback bleibt wichtig.
        "https://www.fupa.net/league/oberliga-baden-wuerttemberg/standing",
        "https://www.fupa.net/league/hessenliga/standing",
        "https://www.fupa.net/league/oberliga-rheinland-pfalz-saar/standing",
        "https://www.fupa.net/league/bayernliga-nord/standing",
        "https://www.fupa.net/league/bayernliga-sued/standing",
    ],
    "wikipedia": TIER5_WIKI_URLS,
}

OBERLIGA_MASTER_COMPETITIONS: List[Dict] = [
    {"name": "Niedersachsen", "sources": {"fupa": "https://www.fupa.net/league/oberliga-niedersachsen/standing",
                                          "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Niedersachsen_2025/26"}},
    {"name": "Schleswig-Holstein", "sources": {"fupa": "https://www.fupa.net/league/oberliga-schleswig-holstein/standing",
                                               "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Schleswig-Holstein_2025/26"}},
    {"name": "Hamburg", "sources": {"fupa": "https://www.fupa.net/league/oberliga-hamburg/standing",
                                    "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Hamburg_2025/26"}},
    {"name": "Bremen", "sources": {"fupa": "https://www.fupa.net/league/bremen-liga/standing",
                                   "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Bremen-Liga_2025/26"}},
    {"name": "Westfalen", "sources": {"fupa": "https://www.fupa.net/league/oberliga-westfalen/standing",
                                      "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Westfalen_2025/26"}},
    {"name": "Niederrhein", "sources": {"fupa": "https://www.fupa.net/league/oberliga-niederrhein/standing",
                                        "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Niederrhein_2025/26"}},
    {"name": "Mittelrhein", "sources": {"fupa": "https://www.fupa.net/league/mittelrheinliga/standing",
                                        "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Mittelrheinliga_2025/26"}},
    {"name": "NOFV Nord", "sources": {
        "fupa": "https://www.fupa.net/league/nofv-oberliga-nord/standing",
        "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Nordost_2025/26"}, "wikipedia_table_pick": 0},
    {"name": "NOFV Süd", "sources": {
        "fupa": "https://www.fupa.net/league/nofv-oberliga-sued/standing",
        "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Nordost_2025/26"}, "wikipedia_table_pick": 1},
    {"name": "Baden-Württemberg", "sources": {"fupa": "https://www.fupa.net/league/oberliga-baden-wuerttemberg/standing",
                                              "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Baden-W%C3%BCrttemberg_2025/26"}},
    {"name": "Hessen", "sources": {"fupa": "https://www.fupa.net/league/hessenliga/standing",
                                   "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Hessenliga_2025/26"}},
    {"name": "Rheinland-Pfalz/Saar", "sources": {"fupa": "https://www.fupa.net/league/oberliga-rheinland-pfalz-saar/standing",
                                                 "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Rheinland-Pfalz/Saar_2025/26"}},
    {"name": "Bayernliga Nord", "sources": {"fupa": "https://www.fupa.net/league/bayernliga-nord/standing",
                                            "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Bayernliga_2025/26"}, "wikipedia_table_pick": 0},
    {"name": "Bayernliga Süd", "sources": {"fupa": "https://www.fupa.net/league/bayernliga-sued/standing",
                                           "wikipedia": f"https://de.wikipedia.org/wiki/Fu%C3%9Fball-Bayernliga_2025/26"}, "wikipedia_table_pick": 1},
]

# Modellannahmen fuer die Saisonlogik
RL_PROMOTION_SLOTS_TO_3LIGA = 4
RL_RELEGATION_SLOTS_PER_STAFFEL = 2
THIRD_LIGA_RELEGATION_SLOTS = 4

# Reformregel:
# 12 je bisheriger Regionalliga-Staffel (5*12=60) + 4 Absteiger 3. Liga + 14 Oberliga-Meister + 2 Zusatzplaetze.
REFORM_RL_BASE_SLOTS = 12
REFORM_3LIGA_RELEGATED_SLOTS = 4
REFORM_OBERLIGA_MASTER_SLOTS = 14
REFORM_EXTRA_STARTPLACES = {"Bayern": 1, "Nordost": 1}
REFORM_STRICT_QUOTA_ALLOW_RESERVES = True


# -------------------------
# Helfer
# -------------------------
U23_PATTERN = re.compile(
    r"(?:\bU[\s-]?(?:19|21|23)\b|\bII\b|\bIII\b|\s(?:2|3)\s*$)",
    re.IGNORECASE,
)


def is_u23_or_reserve(team_name: str) -> bool:
    return bool(U23_PATTERN.search(team_name))


def build_static_regionalliga_base_pool() -> List[str]:
    all_rl_teams = [clean_team_name(
        t) for league in REGIONALLIGA_TEAMS.values() for t in league]
    if EXCLUDE_U23_TEAMS:
        excluded = [t for t in all_rl_teams if is_u23_or_reserve(t)]
        base = [t for t in all_rl_teams if not is_u23_or_reserve(t)]
        print(
            f"Ausgeschlossene U/Reserve-Teams: {len(excluded)} | Beispiele: {excluded[:10]}")
        assert all(not is_u23_or_reserve(t) for t in base), (
            "Filterfehler: U/Reserve-Team in der Basisliste gefunden."
        )
    else:
        base = all_rl_teams
    return sorted(set(base))


def get_override(mapping: Dict[str, str], name: str) -> Optional[str]:
    norm_name = normalize_text(name)
    for k, v in mapping.items():
        if normalize_text(k) == norm_name:
            return normalize_text(v)
    return None


def get_coord_override(mapping: Dict[str, Tuple[float, float]], name: str) -> Optional[Tuple[float, float]]:
    norm_name = normalize_text(name)
    for k, v in mapping.items():
        if normalize_text(k) == norm_name:
            return float(v[0]), float(v[1])
    return None


def team_key(name: str) -> str:
    s = normalize_text(name).lower()
    s = s.replace("ß", "ss")
    s = re.sub(r"[-/]", " ", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_plausible_germany_coord(lat: float, lon: float) -> bool:
    return 46.0 <= float(lat) <= 56.5 and 5.0 <= float(lon) <= 16.5


def clean_team_name(name: str) -> str:
    """
    Entfernt typische Wikipedia-Tabellen-Anmerkungen wie (A), (N), (M), Fußnoten etc.
    """
    s = normalize_text(name)
    # entferne Klammerzusätze am Ende: "(A)", "(N)" usw.
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
    # entferne Hochstellungen/Footnote-ähnliche Marker
    s = re.sub(r"\[[0-9]+\]", "", s).strip()
    # entferne Tabellenstatus-Suffixe wie "L" am Ende
    s = re.sub(r"\s+[A-ZÄÖÜ]$", "", s).strip()
    # Mehrfachspaces
    s = normalize_text(s)
    s = get_override(TEAM_NAME_NORMALIZATION_OVERRIDES, s) or s
    return s



# -------------------------
# Wikipedia Koordinaten
# -------------------------
def load_cache(path: str) -> Dict[str, Tuple[float, float]]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: Dict[str, Tuple[float, float]] = {}
    for k, v in raw.items():
        if isinstance(v, list) and len(v) == 2:
            out[k] = (float(v[0]), float(v[1]))
    return out


def save_cache(path: str, cache: Dict[str, Tuple[float, float]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: [v[0], v[1]] for k, v in cache.items()},
                  f, ensure_ascii=False, indent=2)


def resolve_wikipedia_title(session: requests.Session, name: str) -> Tuple[str, str]:
    """
    Liefert einen aufloesbaren Wikipedia-Titel.
    Reihenfolge: Override -> direkter Titelcheck -> Suche (Top-Treffer).
    """
    norm_name = normalize_text(name)
    override = get_override(WIKI_TITLE_OVERRIDES, norm_name)
    candidate = override if override else norm_name
    source = "override" if override else "direct"

    params = {
        "action": "query",
        "format": "json",
        "titles": candidate,
        "redirects": "1",
    }
    r = session.get(WIKIPEDIA_API, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    pages = data.get("query", {}).get("pages", {})
    if pages:
        page = next(iter(pages.values()))
        if "missing" not in page:
            return page.get("title", candidate), source

    search_params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": norm_name,
        "srlimit": "1",
    }
    sr = session.get(WIKIPEDIA_API, params=search_params, timeout=20)
    sr.raise_for_status()
    sdata = sr.json()
    hits = sdata.get("query", {}).get("search", [])
    if hits:
        return hits[0].get("title", candidate), "search"
    return candidate, "unresolved"


def _wiki_get_coords_from_page(session: requests.Session, title: str) -> Optional[Tuple[float, float]]:
    params = {
        "action": "query",
        "format": "json",
        "prop": "coordinates",
        "titles": title,
        "redirects": "1",
        "colimit": "1",
    }
    r = session.get(WIKIPEDIA_API, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    coords = page.get("coordinates")
    if not coords:
        return None
    c0 = coords[0]
    return float(c0["lat"]), float(c0["lon"])


def _wiki_get_wikidata_qid(session: requests.Session, title: str) -> Optional[str]:
    params = {
        "action": "query",
        "format": "json",
        "prop": "pageprops",
        "ppprop": "wikibase_item",
        "titles": title,
        "redirects": "1",
    }
    r = session.get(WIKIPEDIA_API, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    return page.get("pageprops", {}).get("wikibase_item")


def _wikidata_get_claims(session: requests.Session, qid: str) -> Dict:
    params = {
        "action": "wbgetentities",
        "format": "json",
        "ids": qid,
        "props": "claims",
    }
    r = session.get(WIKIDATA_API, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    entity = data.get("entities", {}).get(qid, {})
    return entity.get("claims", {})


def _extract_p625_from_claims(claims: Dict) -> Optional[Tuple[float, float]]:
    p625_claims = claims.get("P625", [])
    if not p625_claims:
        return None
    for claim in p625_claims:
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        lat = value.get("latitude")
        lon = value.get("longitude")
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    return None


def _extract_entity_ids(claims: Dict, prop: str) -> List[str]:
    out: List[str] = []
    for claim in claims.get(prop, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        qid = value.get("id")
        if isinstance(qid, str) and qid.startswith("Q"):
            out.append(qid)
    return out


def _is_generic_location_entity(qid: str, claims: Dict) -> bool:
    # Verhindert z.B. "Deutschland (Q183)" als Standortkoordinate.
    if qid == "Q183":
        return True
    p31_ids = set(_extract_entity_ids(claims, "P31"))
    return "Q6256" in p31_ids  # country


def _wikidata_get_p625_coords(session: requests.Session, qid: str) -> Tuple[Optional[Tuple[float, float]], str]:
    claims = _wikidata_get_claims(session, qid)
    coords = _extract_p625_from_claims(claims)
    if coords is not None and is_plausible_germany_coord(coords[0], coords[1]):
        return coords, f"wikidata.P625.{qid}"

    # One-hop fallback ueber verknuepfte Standort-Properties.
    related_props = ("P159", "P131", "P276", "P740", "P115")
    seen: set[str] = set()
    for prop in related_props:
        for related_qid in _extract_entity_ids(claims, prop):
            if related_qid in seen:
                continue
            seen.add(related_qid)
            rel_claims = _wikidata_get_claims(session, related_qid)
            if _is_generic_location_entity(related_qid, rel_claims):
                continue
            rel_coords = _extract_p625_from_claims(rel_claims)
            if rel_coords is not None and is_plausible_germany_coord(rel_coords[0], rel_coords[1]):
                return rel_coords, f"wikidata.{qid}.{prop}->{related_qid}.P625"

    return None, f"wikidata.missing_p625.{qid}"


def wiki_get_coords_with_stage(session: requests.Session, title: str) -> Tuple[Optional[Tuple[float, float]], str]:
    coords = _wiki_get_coords_from_page(session, title)
    if coords is not None:
        return coords, "wikipedia.coordinates"

    qid = _wiki_get_wikidata_qid(session, title)
    if not qid:
        return None, "wikipedia.pageprops_missing_qid"

    coords, stage = _wikidata_get_p625_coords(session, qid)
    if coords is not None:
        return coords, stage
    return None, stage


def wiki_get_coords(session: requests.Session, title: str) -> Optional[Tuple[float, float]]:
    """
    Beibehaltener Entry-Point: zuerst Wikipedia, dann Wikidata P625.
    """
    coords, _ = wiki_get_coords_with_stage(session, title)
    return coords


def nominatim_fallback_geocode(name: str) -> Optional[Tuple[float, float]]:
    """
    Optionaler Geocoder-Fallback. Benötigt geopy.
    Nutzt GEOCODE_QUERY_OVERRIDES für schwierige Fälle.
    """
    try:
        from geopy.geocoders import Nominatim
        from geopy.extra.rate_limiter import RateLimiter
    except Exception:
        return None

    geolocator = Nominatim(user_agent=USER_AGENT)
    geocode = RateLimiter(geolocator.geocode,
                          min_delay_seconds=NOMINATIM_MIN_SECONDS)

    norm_name = normalize_text(name)
    queries = []
    override_query = get_override(GEOCODE_QUERY_OVERRIDES, norm_name)
    if override_query:
        queries.append(override_query)

    # Standard-Varianten
    queries += [
        norm_name,
        f"{norm_name}, Deutschland",
        f"{norm_name}, Germany",
    ]

    for q in queries:
        loc = geocode(q)
        if loc and loc.latitude and loc.longitude:
            return float(loc.latitude), float(loc.longitude)

    return None


def build_clubs(team_names: List[str]) -> List[Club]:
    """
    Mappt Teamnamen -> Koordinaten (Wikipedia API, optional Nominatim), mit Cache.
    """
    cache = load_cache(CACHE_FILE)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    clubs: List[Club] = []
    missing: List[str] = []

    for name in team_names:
        override_coords = get_coord_override(CLUB_COORD_OVERRIDES, name)
        if override_coords is not None:
            cache[name] = (float(override_coords[0]),
                           float(override_coords[1]))
            save_cache(CACHE_FILE, cache)
            clubs.append(Club(name=name, lat=float(
                override_coords[0]), lon=float(override_coords[1])))
            continue

        if name in cache:
            lat, lon = cache[name]
            if is_plausible_germany_coord(lat, lon):
                clubs.append(Club(name=name, lat=lat, lon=lon))
                continue
            del cache[name]
            save_cache(CACHE_FILE, cache)

        # Wikipedia -> Wikidata
        coords = None
        resolved_title = name
        title_source = "direct"
        stage = "init"
        try:
            resolved_title, title_source = resolve_wikipedia_title(
                session, name)
            coords, stage = wiki_get_coords_with_stage(session, resolved_title)
        except Exception as exc:
            stage = f"wiki_exception:{type(exc).__name__}"
            coords = None

        # Fallback
        if coords is None and USE_NOMINATIM_FALLBACK:
            coords = nominatim_fallback_geocode(name)
            if coords is not None:
                stage = "nominatim.fallback"
            else:
                stage = f"{stage}->nominatim_missing"

        if coords is None:
            missing.append(
                f"{name} | title={resolved_title} ({title_source}) | fail_stage={stage}"
            )
            continue

        if not is_plausible_germany_coord(coords[0], coords[1]):
            missing.append(
                f"{name} | title={resolved_title} ({title_source}) | fail_stage={stage}->out_of_germany_bbox"
            )
            continue

        cache[name] = coords
        save_cache(CACHE_FILE, cache)
        clubs.append(Club(name=name, lat=coords[0], lon=coords[1]))

        # freundlich drosseln (Wikipedia-API)
        time.sleep(0.2)

    if missing:
        raise RuntimeError(
            "Fuer diese Teams konnten keine Koordinaten ermittelt werden:\n- "
            + "\n- ".join(missing)
            + "\n\nTipp: WIKI_TITLE_OVERRIDES/GEOCODE_QUERY_OVERRIDES erweitern."
        )

    return clubs


# -------------------------
# Oberliga/5.-Liga: Tabellen aus Wikipedia ziehen
# -------------------------
def extract_table_teams_from_wikipedia(url: str) -> List[str]:
    """
    Liest Wikipedia-HTML-Tabellen und extrahiert Teamnamen aus Spalten 'Verein' oder 'Mannschaft'.
    Gibt die Teams in Tabellenreihenfolge zurück.
    """
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    dfs = pd.read_html(StringIO(resp.text))
    teams: List[str] = []

    for df in dfs:
        cols = [str(c) for c in df.columns]
        # Suche nach geeigneter Spalte
        target_col = None
        for c in cols:
            lc = c.lower()
            if lc.startswith("verein") or lc.startswith("mannschaft"):
                target_col = c
                break
        if target_col is None:
            continue

        col_vals = df[target_col].tolist()
        for v in col_vals:
            name = clean_team_name(str(v))
            # Filter offensichtliche Nicht-Vereinszeilen
            if not name or name.lower() in {"verein", "mannschaft"}:
                continue
            # Manche Tabellen haben Zeilen wie "Stand: ...", die durch read_html selten,
            # aber gelegentlich als NaN/Strings auftauchen.
            if "stand:" in name.lower():
                continue
            teams.append(name)

        # In vielen Wikipedia-Artikeln ist die erste passende Tabelle die gewünschte "Tabelle".
        # Wir nehmen sie und brechen ab.
        if teams:
            break

    return teams


def _flatten_col_name(col) -> str:
    if isinstance(col, tuple):
        parts = [str(x) for x in col if str(x) != "nan"]
        return " ".join(parts).strip()
    return str(col)


def _find_col(cols: List[str], patterns: List[str]) -> Optional[str]:
    for c in cols:
        lc = c.lower()
        if any(p in lc for p in patterns):
            return c
    return None


def _to_int_or_none(value) -> Optional[int]:
    s = clean_team_name(str(value))
    m = re.search(r"-?\d+", s)
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None


def _extract_standings_rows_wikipedia(url: str, table_pick: int = 0) -> List[Dict]:
    """
    Extrahiert Tabellenzeilen (Reihenfolge = Tabellenstand) inkl. Team/Points/Games.
    """
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    dfs = pd.read_html(StringIO(resp.text))

    table_hits = 0
    for df in dfs:
        df = df.copy()
        df.columns = [_flatten_col_name(c) for c in df.columns]
        cols = [str(c) for c in df.columns]
        team_col = _find_col(cols, ["verein", "mannschaft"])
        if not team_col:
            continue

        points_col = _find_col(cols, ["pkt", "punkte"])
        games_col = _find_col(cols, [" sp", "spiele", "sp."])

        rows: List[Dict] = []
        pos = 0
        for _, row in df.iterrows():
            team = clean_team_name(str(row.get(team_col, "")))
            if not team or team.lower() in {"verein", "mannschaft"}:
                continue
            if "stand:" in team.lower():
                continue
            pos += 1
            points = _to_int_or_none(
                row.get(points_col)) if points_col else None
            games = _to_int_or_none(row.get(games_col)) if games_col else None
            ppg = None
            if points is not None and games not in (None, 0):
                ppg = float(points) / float(games)
            rows.append(
                {
                    "rank": pos,
                    "team": team,
                    "points": points,
                    "games": games,
                    "ppg": ppg,
                }
            )
        if rows:
            if table_hits == table_pick:
                return rows
            table_hits += 1
    return []


def _extract_standings_rows_fupa(url: str) -> List[Dict]:
    """
    Extrahiert Tabellenstand aus FuPa (window.REDUX_DATA JSON).
    """
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    html = resp.text

    m = re.search(
        r"window\.REDUX_DATA\s*=\s*(\{.*?\})\s*</script>", html, re.DOTALL)
    if not m:
        return []

    data = json.loads(m.group(1))
    standings: List[Dict] = []
    for item in data.get("dataHistory", []):
        ls = item.get("LeagueStandingPage", {})
        st = ((ls.get("total", {}) or {}).get(
            "data", {}) or {}).get("standings", [])
        if st:
            standings = st
            break

    rows: List[Dict] = []
    for entry in standings:
        team_obj = entry.get("team", {})
        team_name = (
            team_obj.get("name", {}).get("full")
            or team_obj.get("name", {}).get("middle")
            or team_obj.get("name", {}).get("short")
            or ""
        )
        team = clean_team_name(team_name)
        if not team:
            continue
        points = entry.get("points")
        games = entry.get("matches")
        ppg = None
        if games not in (None, 0) and points is not None:
            ppg = float(points) / float(games)
        rows.append(
            {
                "rank": int(entry.get("rank")) if entry.get("rank") is not None else None,
                "team": team,
                "points": int(points) if points is not None else None,
                "games": int(games) if games is not None else None,
                "ppg": ppg,
                "mark": entry.get("mark"),
                "fupa_team_level": team_obj.get("level"),
                "source": "fupa",
                "source_url": url,
            }
        )
    return rows


def extract_standings_rows(url: str, source: Optional[str] = None, table_pick: int = 0) -> List[Dict]:
    source = source or ("fupa" if "fupa.net" in url else "wikipedia")
    if source == "fupa":
        try:
            rows = _extract_standings_rows_fupa(url)
            if rows:
                return rows
        except Exception:
            return []
        return []
    return _extract_standings_rows_wikipedia(url, table_pick=table_pick)


def extract_standings_rows_with_fallback(source_urls: Dict[str, str], table_pick: int = 0) -> Tuple[List[Dict], str, str]:
    errors: List[str] = []
    for src in TABLE_SOURCE_PRIORITY:
        url = source_urls.get(src)
        if not url:
            continue
        try:
            rows = extract_standings_rows(
                url, source=src, table_pick=table_pick)
            if rows:
                return rows, src, url
        except Exception as exc:
            errors.append(f"{src}:{type(exc).__name__}")
            continue
    return [], "", (";".join(errors) if errors else "no_source_rows")


def _score_tuple(row: Dict) -> Tuple[float, float, float]:
    ppg = float(row["ppg"]) if row.get("ppg") is not None else -1.0
    points = float(row["points"]) if row.get("points") is not None else -1.0
    rank_bonus = -float(row.get("rank", 999))
    return (ppg, points, rank_bonus)


def _is_filtered_out_row(row: Dict) -> bool:
    team = clean_team_name(str(row.get("team", "")))
    if not team:
        return True
    if is_u23_or_reserve(team):
        return True
    lvl = row.get("fupa_team_level")
    try:
        if lvl is not None and int(lvl) > 1:
            return True
    except Exception:
        pass
    return False


def _pick_rl_champions_for_promotion(rl_rows_by_league: Dict[str, List[Dict]], slots: int) -> List[str]:
    candidates: List[Dict] = []
    for league_name, rows in rl_rows_by_league.items():
        for r in rows:
            if _is_filtered_out_row(r):
                continue
            item = dict(r)
            item["league"] = league_name
            candidates.append(item)
            break
    candidates = sorted(candidates, key=_score_tuple, reverse=True)
    return [c["team"] for c in candidates[:slots]]


def _pick_relegations_per_staffel(rl_rows_by_league: Dict[str, List[Dict]], per_staffel: int, protected: set[str]) -> set[str]:
    rel: set[str] = set()
    for _, rows in rl_rows_by_league.items():
        marked = [
            r for r in rows
            if str(r.get("mark", "")).startswith("down") and not _is_filtered_out_row(r) and r["team"] not in protected
        ]
        for r in marked:
            rel.add(r["team"])
            if len([x for x in rel if x in [rr["team"] for rr in rows]]) >= per_staffel:
                break

        picked = 0
        for r in reversed(rows):
            t = r["team"]
            if _is_filtered_out_row(r) or t in protected or t in rel:
                continue
            rel.add(t)
            picked += 1
            already = len([x for x in rel if x in [rr["team"] for rr in rows]])
            if max(picked, already) >= per_staffel:
                break
    return rel


def _pick_3liga_relegated(rows: List[Dict], slots: int) -> List[str]:
    out: List[str] = []
    marked = [r for r in rows if str(r.get("mark", "")).startswith("down")]
    for r in marked:
        t = r["team"]
        if _is_filtered_out_row(r):
            continue
        if t not in out:
            out.append(t)
        if len(out) >= slots:
            return out
    for r in reversed(rows):
        t = r["team"]
        if _is_filtered_out_row(r):
            continue
        if t not in out:
            out.append(t)
        if len(out) >= slots:
            break
    return out


def _pick_oberliga_promotions(slots: int, exclude: set[str]) -> List[Tuple[str, str]]:
    candidates: List[Dict] = []
    exclude_keys = {team_key(x) for x in exclude}
    for src in TABLE_SOURCE_PRIORITY:
        for url in TIER5_TABLE_URLS.get(src, []):
            try:
                rows = extract_standings_rows(url, source=src)
            except Exception:
                continue
            for r in rows:
                t = clean_team_name(r["team"])
                if not t or _is_filtered_out_row(r) or team_key(t) in exclude_keys:
                    continue
                item = dict(r)
                item["team"] = t
                item["source_url"] = url
                item["source"] = src
                candidates.append(item)

    unique: Dict[str, Dict] = {}
    for c in candidates:
        t_key = team_key(c["team"])
        old = unique.get(t_key)
        if old is None or _score_tuple(c) > _score_tuple(old):
            unique[t_key] = c

    candidates = list(unique.values())

    selected: List[Dict] = []
    used: set[str] = set()
    marked_up = [c for c in candidates if str(
        c.get("mark", "")).startswith("up")]
    marked_up.sort(key=_score_tuple, reverse=True)
    for c in marked_up:
        if c["team"] in used:
            continue
        selected.append(c)
        used.add(c["team"])
        if len(selected) >= slots:
            return [(x["team"], x["source_url"]) for x in selected]

    # Erst Spitzenplaetze je Liga (Platz 1, dann 2, ...)
    for place in [1, 2, 3, 4]:
        round_pool = [c for c in candidates if c.get(
            "rank") == place and c["team"] not in used]
        round_pool.sort(key=_score_tuple, reverse=True)
        for c in round_pool:
            selected.append(c)
            used.add(c["team"])
            if len(selected) >= slots:
                return [(x["team"], x["source_url"]) for x in selected]

    # Dann Rest nach Leistung
    rest = [c for c in candidates if c["team"] not in used]
    rest.sort(key=_score_tuple, reverse=True)
    for c in rest:
        selected.append(c)
        used.add(c["team"])
        if len(selected) >= slots:
            break
    return [(x["team"], x["source_url"]) for x in selected]


def _pick_top_n_from_rows(
    rows: List[Dict],
    n: int,
    used_keys: Optional[set[str]] = None,
    allow_filtered_fallback: bool = False,
) -> List[str]:
    if used_keys is None:
        used_keys = set()
    out: List[str] = []
    for r in rows:
        if _is_filtered_out_row(r):
            continue
        t = clean_team_name(r["team"])
        k = team_key(t)
        if not t or k in used_keys:
            continue
        out.append(t)
        used_keys.add(k)
        if len(out) >= n:
            break
    if len(out) < n and allow_filtered_fallback:
        for r in rows:
            t = clean_team_name(r.get("team", ""))
            k = team_key(t)
            if not t or k in used_keys:
                continue
            out.append(t)
            used_keys.add(k)
            if len(out) >= n:
                break
    return out


def _rows_by_rank(rows: List[Dict]) -> Dict[int, Dict]:
    out: Dict[int, Dict] = {}
    for r in rows:
        rk = r.get("rank")
        if rk is None:
            continue
        try:
            out[int(rk)] = r
        except Exception:
            continue
    return out


def build_reform_12_4_14_team_pool(target: int) -> List[str]:
    rl_rows_by_league: Dict[str, List[Dict]] = {}
    rl_source_info: Dict[str, str] = {}

    for league_name, source_urls in REGIONALLIGA_TABLE_URLS.items():
        rows, src, src_info = extract_standings_rows_with_fallback(source_urls)
        if rows:
            rl_rows_by_league[normalize_text(league_name)] = rows
            rl_source_info[normalize_text(league_name)] = f"{src}:{src_info}"

    required_leagues = {"Nord", "Nordost", "West", "Bayern", "Südwest"}
    if set(rl_rows_by_league.keys()) != required_leagues:
        missing = sorted(required_leagues - set(rl_rows_by_league.keys()))
        raise RuntimeError(f"Fehlende RL-Daten fuer: {missing}")

    used_keys: set[str] = set()
    pool: List[str] = []
    promoted_to_3liga: List[str] = []
    promoted_to_3liga_league: Dict[str, str] = {}
    relegated_from_regionalliga: List[str] = []

    # 1) 12 Vertreter je Regionalliga: exakt Platz 2-13
    rl_representatives: Dict[str, List[str]] = {}
    for league_name in ["Nord", "Nordost", "West", "Bayern", "Südwest"]:
        rows = rl_rows_by_league[league_name]
        rank_map = _rows_by_rank(rows)

        # Platz 1 steigt auf
        if 1 in rank_map:
            top_team = clean_team_name(rank_map[1]["team"])
            if top_team:
                promoted_to_3liga.append(top_team)
                promoted_to_3liga_league[top_team] = league_name
                used_keys.add(team_key(top_team))

        picked: List[str] = []
        for rk in range(2, 14):
            if rk not in rank_map:
                continue
            t = clean_team_name(rank_map[rk]["team"])
            if not t:
                continue
            k = team_key(t)
            if k in used_keys:
                continue
            used_keys.add(k)
            picked.append(t)
            pool.append(t)
        if len(picked) < REFORM_RL_BASE_SLOTS:
            raise RuntimeError(
                f"Zu wenig Vertreter in {league_name}: {len(picked)} (erwartet 12)")
        rl_representatives[league_name] = picked

        # Absteiger: Rest ab Platz 14
        for rk in sorted(rank_map.keys()):
            if rk <= 13:
                continue
            t = clean_team_name(rank_map[rk]["team"])
            if t:
                relegated_from_regionalliga.append(t)

    # 2) 4 Absteiger aus 3. Liga
    third_rows, third_src, third_src_info = extract_standings_rows_with_fallback(
        THIRD_LIGA_TABLE_URLS
    )
    relegated_3liga = []
    for t in _pick_3liga_relegated(third_rows, REFORM_3LIGA_RELEGATED_SLOTS):
        k = team_key(t)
        if k in used_keys:
            continue
        used_keys.add(k)
        relegated_3liga.append(t)
        pool.append(t)
    if len(relegated_3liga) < REFORM_3LIGA_RELEGATED_SLOTS:
        raise RuntimeError("Zu wenig 3.-Liga-Absteiger gefunden.")

    # 3) 14 Oberliga-Meister (ein Meister je definierter Oberliga)
    oberliga_masters: List[Tuple[str, str, str]] = []
    for comp in OBERLIGA_MASTER_COMPETITIONS:
        table_pick = int(comp.get("wikipedia_table_pick", 0))
        rows, src, src_info = extract_standings_rows_with_fallback(
            comp["sources"], table_pick=table_pick
        )
        champ = _pick_top_n_from_rows(rows, 1, used_keys)
        if not champ:
            continue
        team = champ[0]
        pool.append(team)
        oberliga_masters.append((comp["name"], team, f"{src}:{src_info}"))
        if len(oberliga_masters) >= REFORM_OBERLIGA_MASTER_SLOTS:
            break
    if len(oberliga_masters) < REFORM_OBERLIGA_MASTER_SLOTS:
        raise RuntimeError(
            f"Nur {len(oberliga_masters)} Oberliga-Meister gefunden (erwartet {REFORM_OBERLIGA_MASTER_SLOTS})."
        )

    # 4) 2 Zusatzplaetze: Bayern + Nordost (naechster Platz nach 2-13, i.d.R. Platz 14)
    extra_picks: Dict[str, List[str]] = {}
    for league_name, slots in REFORM_EXTRA_STARTPLACES.items():
        rank_map = _rows_by_rank(rl_rows_by_league[league_name])
        extra: List[str] = []
        for rk in range(14, 25):
            if rk not in rank_map:
                continue
            t = clean_team_name(rank_map[rk]["team"])
            if not t:
                continue
            k = team_key(t)
            if k in used_keys:
                continue
            used_keys.add(k)
            extra.append(t)
            pool.append(t)
            if len(extra) >= slots:
                break
        if len(extra) < slots:
            raise RuntimeError(
                f"Zusatzplatz fuer {league_name} nicht vollstaendig.")
        extra_picks[league_name] = extra

    # final dedupe safety
    deduped: List[str] = []
    seen: set[str] = set()
    for t in pool:
        k = team_key(t)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(t)

    lines = []
    lines.append("Reformregel 12+4+14+2:")
    lines.append(f"- Quellen-Prioritaet: {TABLE_SOURCE_PRIORITY}")
    lines.append(f"- RL-Quellen: {rl_source_info}")
    lines.append(f"- 3. Liga Quelle: {third_src}:{third_src_info}")
    lines.append(
        f"- RL-Vertreter (5x12): {sum(len(v) for v in rl_representatives.values())}")
    lines.append(
        f"- RL-Aufsteiger (Platz 1 je Staffel): {sorted(promoted_to_3liga)}")
    lines.append(
        f"- RL-Absteiger (ab Platz 14): {len(relegated_from_regionalliga)}")
    lines.append(f"- 3. Liga Absteiger: {relegated_3liga}")
    lines.append(f"- Oberliga-Meister: {len(oberliga_masters)}")
    lines.append(f"- Zusatzplaetze: {extra_picks}")
    reserve_count = len([t for t in deduped if is_u23_or_reserve(t)])
    if reserve_count:
        lines.append(
            f"- Hinweis: {reserve_count} Reserve/U-Teams wegen strikter Quote enthalten."
        )
    print("\n".join(lines))

    with open(ADDED_TEAMS_LOG_FILE, "w", encoding="utf-8") as f:
        for league_name, team, src in oberliga_masters:
            f.write(f"{league_name}: {team} | {src}\n")

    transitions = {
        "promoted_to_3liga": sorted(promoted_to_3liga),
        "promoted_to_3liga_league": promoted_to_3liga_league,
        "relegated_from_regionalliga": sorted(set(relegated_from_regionalliga)),
        "relegated_from_3liga": sorted(relegated_3liga),
        "promoted_from_oberliga": [x[1] for x in oberliga_masters],
        "reform_rule": "12+4+14+2",
        "extra_startplaces": REFORM_EXTRA_STARTPLACES,
    }
    with open(SEASON_TRANSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(transitions, f, ensure_ascii=False, indent=2)

    if len(deduped) != target:
        raise RuntimeError(
            f"Reform-Teamlogik ergibt {len(deduped)} Teams statt {target}.")
    return sorted(deduped)


def build_rule_based_team_pool(target: int) -> List[str]:
    """
    Regelbasierte Saisonlogik:
    - RL-Tabellenstand analysieren
    - 4 RL-Aufsteiger in 3. Liga (beste Staffelsieger)
    - Fester RL-Abstieg je Staffel
    - 3.-Liga-Absteiger aufnehmen
    - Offene Plaetze mit Oberliga-Aufsteigern nach Tabellenstand fuellen
    """
    rl_rows_by_league: Dict[str, List[Dict]] = {}
    rl_source_info: Dict[str, str] = {}
    for league_name, source_urls in REGIONALLIGA_TABLE_URLS.items():
        rows, src, src_info = extract_standings_rows_with_fallback(source_urls)
        rows = [r for r in rows if not _is_filtered_out_row(r)]
        if rows:
            rl_rows_by_league[normalize_text(league_name)] = rows
            rl_source_info[normalize_text(league_name)] = f"{src}:{src_info}"

    if not rl_rows_by_league:
        raise RuntimeError("Keine Regionalliga-Tabellen verfuegbar.")

    current_rl_set = {
        clean_team_name(r["team"])
        for rows in rl_rows_by_league.values()
        for r in rows
        if not _is_filtered_out_row(r)
    }

    promoted_to_3 = set(
        _pick_rl_champions_for_promotion(
            rl_rows_by_league, RL_PROMOTION_SLOTS_TO_3LIGA)
    )
    relegated_from_rl = _pick_relegations_per_staffel(
        rl_rows_by_league, RL_RELEGATION_SLOTS_PER_STAFFEL, promoted_to_3
    )

    pool = set(current_rl_set)
    pool -= promoted_to_3
    pool -= relegated_from_rl

    third_rows, third_src, third_src_info = extract_standings_rows_with_fallback(
        THIRD_LIGA_TABLE_URLS)
    from_3liga = set(_pick_3liga_relegated(
        third_rows, THIRD_LIGA_RELEGATION_SLOTS))
    pool |= from_3liga

    slots = target - len(pool)
    if slots < 0:
        # Wenn uebervoll: weitere RL-Absteiger anhand Tabellenende bestimmen.
        extra = -slots
        tail_pool: List[Dict] = []
        for league_name, rows in rl_rows_by_league.items():
            for r in reversed(rows):
                t = r["team"]
                if t in promoted_to_3 or t in relegated_from_rl or t not in pool:
                    continue
                item = dict(r)
                item["league"] = league_name
                tail_pool.append(item)
        tail_pool.sort(key=lambda x: x.get("rank", 999), reverse=True)
        for x in tail_pool[:extra]:
            pool.discard(x["team"])
        slots = target - len(pool)

    added_with_source: List[Tuple[str, str]] = []
    if slots > 0:
        added_with_source = _pick_oberliga_promotions(slots, pool)
        for team, _ in added_with_source:
            pool.add(team)

    lines = []
    lines.append("Regelbasierte Saisonentscheidung:")
    lines.append(f"- Quellen-Prioritaet: {TABLE_SOURCE_PRIORITY}")
    lines.append(f"- 3. Liga Quelle: {third_src}:{third_src_info}")
    lines.append(f"- Regionalliga Quellen: {rl_source_info}")
    lines.append(f"- RL-Teams (eligible): {len(current_rl_set)}")
    lines.append(f"- Aufsteiger in 3. Liga: {sorted(promoted_to_3)}")
    lines.append(f"- RL-Absteiger gesamt: {len(relegated_from_rl)}")
    lines.append(f"- Absteiger aus 3. Liga: {sorted(from_3liga)}")
    if added_with_source:
        lines.append("- Aufsteiger aus Oberligen:")
        for team, src in added_with_source:
            lines.append(f"  * {team} | {src}")
    print("\n".join(lines))

    if added_with_source:
        with open(ADDED_TEAMS_LOG_FILE, "w", encoding="utf-8") as f:
            f.write(
                "\n".join([f"{t} | {u}" for t, u in added_with_source]) + "\n")

    transitions = {
        "promoted_to_3liga": sorted(promoted_to_3),
        "relegated_from_regionalliga": sorted(relegated_from_rl),
        "relegated_from_3liga": sorted(from_3liga),
        "promoted_from_oberliga": [t for t, _ in added_with_source],
    }
    with open(SEASON_TRANSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(transitions, f, ensure_ascii=False, indent=2)

    out = sorted(pool)
    if len(out) != target:
        raise RuntimeError(
            f"Regelbasierte Teamlogik ergibt {len(out)} Teams statt {target}."
        )
    return out


def fill_up_to_target(base: List[str], target: int) -> List[str]:
    """
    Füllt base bis target auf, mit Kandidaten aus Oberliga-Ligen (FuPa bevorzugt, Wikipedia als Fallback).
    """
    if len(base) >= target:
        return base[:target]

    if not FILL_UP_WITH_TIER5_FROM_WIKIPEDIA:
        raise RuntimeError(
            f"Nach Filterung sind nur {len(base)} Teams vorhanden, benötigt werden {target}. "
            f"Aktiviere FILL_UP_WITH_TIER5_FROM_WIKIPEDIA oder passe Parameter an."
        )

    have = set(base)
    added: List[str] = []
    added_with_source: List[Tuple[str, str]] = []

    for comp in OBERLIGA_MASTER_COMPETITIONS:
        if len(base) + len(added) >= target:
            break
        table_pick = comp.get("wikipedia_table_pick", 0)
        try:
            rows, src, url = extract_standings_rows_with_fallback(
                comp["sources"], table_pick=table_pick
            )
        except Exception:
            continue

        if not rows:
            continue

        if src == "wikipedia":
            print(
                f"  [Warnung] {comp['name']}: FuPa nicht verfügbar – "
                f"nutze Wikipedia als Fallback ({url})"
            )

        for row in rows:
            t = clean_team_name(str(row.get("team", "")))
            if not t or t in have:
                continue
            if EXCLUDE_U23_TEAMS and is_u23_or_reserve(t):
                continue
            have.add(t)
            added.append(t)
            added_with_source.append((t, f"{src}:{url}"))
            if len(base) + len(added) >= target:
                break

    out = base + added
    if len(out) < target:
        raise RuntimeError(
            f"Konnte nur auf {len(out)} Teams auffüllen (Ziel: {target}). "
            "Füge weitere Ligen zu OBERLIGA_MASTER_COMPETITIONS hinzu oder lockere Filter."
        )
    if added_with_source:
        lines = [f"{team} | {source_url}" for team, source_url in added_with_source]
        print("\nHinzugefuegte Oberliga-Teams (inkl. Quelle):")
        for line in lines:
            print(f"  - {line}")
        with open(ADDED_TEAMS_LOG_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return out[:target]


# -------------------------
# Clustering + Kapazitäten erzwingen
# -------------------------
def compute_centroids(clubs: List[Club], labels: np.ndarray, k: int) -> np.ndarray:
    centroids = np.zeros((k, 2), dtype=float)
    for i in range(k):
        pts = clubs_to_array([clubs[j]
                             for j in range(len(clubs)) if labels[j] == i])
        centroids[i] = pts.mean(axis=0)
    return centroids


def clubs_to_array(clubs: List[Club]) -> np.ndarray:
    return np.array([[c.lat, c.lon] for c in clubs], dtype=float)


def dist_to_centroid_km(club: Club, centroid_latlon: np.ndarray) -> float:
    return haversine_km(club.lat, club.lon, float(centroid_latlon[0]), float(centroid_latlon[1]))


def balance_clusters(clubs: List[Club], labels: np.ndarray, k: int, cap: int, max_iter: int = 5000) -> np.ndarray:
    """
    Erzwingt exakt 'cap' Teams pro Cluster durch Moves mit minimaler Mehrkosten-Heuristik.
    """
    labels = labels.copy()
    n = len(clubs)

    for _ in range(max_iter):
        counts = np.bincount(labels, minlength=k)
        over = [i for i in range(k) if counts[i] > cap]
        under = [i for i in range(k) if counts[i] < cap]
        if not over and not under:
            return labels

        centroids = compute_centroids(clubs, labels, k)

        # Wähle einen Move aus einem übervollen Cluster in einen untervollen Cluster
        best_move = None  # (delta_cost, idx, from_k, to_k)
        for from_k in over:
            idxs = np.where(labels == from_k)[0]
            for idx in idxs:
                c = clubs[idx]
                cost_from = dist_to_centroid_km(c, centroids[from_k])
                for to_k in under:
                    cost_to = dist_to_centroid_km(c, centroids[to_k])
                    delta = cost_to - cost_from
                    if best_move is None or delta < best_move[0]:
                        best_move = (delta, idx, from_k, to_k)

        if best_move is None:
            break

        _, idx, from_k, to_k = best_move
        labels[idx] = to_k

    raise RuntimeError(
        "Balance der Cluster nicht konvergiert. Erhöhe max_iter oder prüfe Daten.")


def improve_by_swaps(clubs: List[Club], labels: np.ndarray, k: int, iters: int = 30000, seed: int = 42) -> np.ndarray:
    """
    Lokale Verbesserung: zufällige Swaps zwischen Clustern, wenn Objective sinkt.
    Objective: Summe Distanz(Club -> Cluster-Centroid).
    """
    rng = np.random.default_rng(seed)
    labels = labels.copy()
    n = len(clubs)

    for _ in range(iters):
        centroids = compute_centroids(clubs, labels, k)

        i, j = rng.integers(0, n, size=2)
        if i == j:
            continue
        ci, cj = clubs[i], clubs[j]
        ki, kj = labels[i], labels[j]
        if ki == kj:
            continue

        before = dist_to_centroid_km(
            ci, centroids[ki]) + dist_to_centroid_km(cj, centroids[kj])
        after = dist_to_centroid_km(
            ci, centroids[kj]) + dist_to_centroid_km(cj, centroids[ki])

        if after < before:
            labels[i], labels[j] = labels[j], labels[i]

    return labels


def compute_distance_matrix_km(clubs: List[Club]) -> np.ndarray:
    n = len(clubs)
    dm = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_km(clubs[i].lat, clubs[i].lon,
                             clubs[j].lat, clubs[j].lon)
            dm[i, j] = d
            dm[j, i] = d
    return dm


def objective_intra_league_sum(labels: np.ndarray, dist_matrix: np.ndarray) -> float:
    n = len(labels)
    total = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            if labels[i] == labels[j]:
                total += float(dist_matrix[i, j])
    return total


def improve_by_swaps_distance_matrix(
    labels: np.ndarray,
    dist_matrix: np.ndarray,
    k: int,
    iters: int = 60000,
    seed: int = 42,
    accept_equal_prob: float = 0.0,
    anneal_start_temp_km: float = 0.0,
    anneal_end_temp_km: float = 0.0,
    move_2_prob: float = 0.8,
    move_3_prob: float = 0.15,
    move_4_prob: float = 0.05,
    stagnation_shake_iters: int = 0,
    stagnation_shake_fraction: float = 0.0,
) -> np.ndarray:
    """
    Alternative Optimierung auf Distanzmatrix-Basis:
    minimiert Summe aller Intra-Liga-Paarstrecken bei festen Teamzahlen je Liga.
    Unterstuetzt 2er/3er/4er-Tauschzyklen sowie optionale Diversifikations-Shakes.
    """
    rng = np.random.default_rng(seed)
    labels = labels.copy()
    if k < 2:
        return labels

    move_2_prob = max(0.0, float(move_2_prob))
    move_3_prob = max(0.0, float(move_3_prob))
    move_4_prob = max(0.0, float(move_4_prob))
    stagnation_shake_iters = max(0, int(stagnation_shake_iters))
    stagnation_shake_fraction = max(0.0, float(stagnation_shake_fraction))

    n = len(labels)
    members = [set(np.where(labels == c)[0].tolist()) for c in range(k)]

    def sum_to_cluster(i: int, cluster_idx: int, exclude: Optional[int] = None) -> float:
        s = 0.0
        for x in members[cluster_idx]:
            if x == exclude:
                continue
            s += float(dist_matrix[i, x])
        return s

    def choose_cycle_size() -> int:
        p2 = move_2_prob
        p3 = move_3_prob if k >= 3 else 0.0
        p4 = move_4_prob if k >= 4 else 0.0
        total = p2 + p3 + p4
        if total <= 0.0:
            return 2
        r = rng.random() * total
        if r < p2:
            return 2
        if r < p2 + p3:
            return 3
        return 4

    def propose_cycle_move(move_size: int) -> Optional[Tuple[List[int], List[int], List[int]]]:
        if move_size < 2 or move_size > k:
            return None
        clusters = [int(x) for x in rng.choice(k, size=move_size, replace=False)]
        nodes: List[int] = []
        for c in clusters:
            if not members[c]:
                return None
            nodes.append(int(rng.choice(tuple(members[c]))))

        # Vorwaerts- oder Rueckwaerts-Zyklus fuer mehr Diversitaet.
        if move_size == 2 or rng.random() < 0.5:
            target_clusters = [clusters[(i + 1) % move_size]
                               for i in range(move_size)]
        else:
            target_clusters = [clusters[(i - 1) % move_size]
                               for i in range(move_size)]

        source_clusters = [int(labels[idx]) for idx in nodes]
        if len(set(source_clusters)) != move_size:
            return None
        return nodes, source_clusters, target_clusters

    def cycle_delta(nodes: List[int], source_clusters: List[int], target_clusters: List[int]) -> float:
        leaving_node: Dict[int, int] = {
            source_clusters[pos]: nodes[pos] for pos in range(len(nodes))
        }
        before = 0.0
        after = 0.0
        for pos, node_idx in enumerate(nodes):
            src = source_clusters[pos]
            dst = target_clusters[pos]
            before += sum_to_cluster(node_idx, src, exclude=node_idx)
            after += sum_to_cluster(node_idx, dst,
                                    exclude=leaving_node.get(dst))
        return float(after - before)

    def apply_cycle_move(nodes: List[int], source_clusters: List[int], target_clusters: List[int]) -> None:
        for pos, node_idx in enumerate(nodes):
            members[source_clusters[pos]].remove(node_idx)
        for pos, node_idx in enumerate(nodes):
            dst = target_clusters[pos]
            members[dst].add(node_idx)
            labels[node_idx] = dst

    def random_shake(swap_count: int) -> None:
        if swap_count <= 0:
            return
        performed = 0
        tries = 0
        max_tries = max(200, swap_count * 30)
        while performed < swap_count and tries < max_tries:
            tries += 1
            i, j = rng.integers(0, n, size=2)
            if i == j:
                continue
            a, b = int(labels[i]), int(labels[j])
            if a == b:
                continue
            members[a].remove(int(i))
            members[b].remove(int(j))
            members[a].add(int(j))
            members[b].add(int(i))
            labels[i], labels[j] = labels[j], labels[i]
            performed += 1

    current_obj = objective_intra_league_sum(labels, dist_matrix)
    best_obj = float(current_obj)
    best_labels = labels.copy()
    no_improve_steps = 0

    for step in range(iters):
        move_size = choose_cycle_size()
        move = propose_cycle_move(move_size)
        if move is None:
            no_improve_steps += 1
            continue
        nodes, source_clusters, target_clusters = move
        delta = cycle_delta(nodes, source_clusters, target_clusters)

        if abs(delta) < 1e-12:
            delta = 0.0

        accept = False
        if delta < 0.0:
            accept = True
        elif delta == 0.0 and accept_equal_prob > 0.0 and rng.random() < accept_equal_prob:
            accept = True
        elif delta > 0.0 and anneal_start_temp_km > 0.0:
            if iters <= 1:
                temp = max(1e-9, anneal_end_temp_km if anneal_end_temp_km >
                           0.0 else anneal_start_temp_km)
            else:
                t = step / float(iters - 1)
                temp = anneal_start_temp_km + \
                    (anneal_end_temp_km - anneal_start_temp_km) * t
                temp = max(1e-9, temp)
            p_accept = float(np.exp(-delta / temp))
            if rng.random() < p_accept:
                accept = True

        if accept:
            apply_cycle_move(nodes, source_clusters, target_clusters)
            current_obj += delta
            if current_obj + 1e-12 < best_obj:
                best_obj = float(current_obj)
                best_labels = labels.copy()
                no_improve_steps = 0
            else:
                no_improve_steps += 1
        else:
            no_improve_steps += 1

        if stagnation_shake_iters <= 0:
            continue
        if no_improve_steps < stagnation_shake_iters:
            continue

        shake_swaps = int(round(stagnation_shake_fraction * n))
        if shake_swaps > 0:
            random_shake(shake_swaps)
            current_obj = objective_intra_league_sum(labels, dist_matrix)
            if current_obj + 1e-12 < best_obj:
                best_obj = float(current_obj)
                best_labels = labels.copy()
        no_improve_steps = 0

    return best_labels


def shake_labels_by_random_swaps(
    labels: np.ndarray,
    k: int,
    swap_count: int,
    seed: int,
) -> np.ndarray:
    """
    Kleine Diversifikationsphase: zufaellige Swaps zwischen Clustern.
    Kapazitaeten bleiben erhalten, weil nur getauscht wird.
    """
    if swap_count <= 0:
        return labels.copy()
    rng = np.random.default_rng(seed)
    out = labels.copy()
    n = len(out)
    performed = 0
    max_tries = max(100, swap_count * 20)
    tries = 0
    while performed < swap_count and tries < max_tries:
        tries += 1
        i, j = rng.integers(0, n, size=2)
        if i == j:
            continue
        a, b = int(out[i]), int(out[j])
        if a == b:
            continue
        out[i], out[j] = out[j], out[i]
        performed += 1
    return out


def build_derby_components(dist_matrix: np.ndarray, max_km: float) -> List[List[int]]:
    n = dist_matrix.shape[0]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if float(dist_matrix[i, j]) <= max_km:
                union(i, j)

    buckets: Dict[int, List[int]] = {}
    for i in range(n):
        r = find(i)
        buckets.setdefault(r, []).append(i)
    return list(buckets.values())


def assign_components_initial(
    clubs: List[Club],
    components: List[List[int]],
    centroids: np.ndarray,
    k: int,
    cap: int,
) -> np.ndarray:
    n = len(clubs)
    labels = np.full(n, -1, dtype=int)
    remaining = [cap] * k

    comp_infos = []
    for idx, members in enumerate(components):
        lat = float(np.mean([clubs[m].lat for m in members]))
        lon = float(np.mean([clubs[m].lon for m in members]))
        comp_infos.append((idx, members, lat, lon, len(members)))

    # Zuerst groessere Komponenten platzieren.
    comp_infos.sort(key=lambda x: x[4], reverse=True)
    for comp_idx, members, lat, lon, size in comp_infos:
        choices = sorted(
            range(k),
            key=lambda c: haversine_km(lat, lon, float(
                centroids[c, 0]), float(centroids[c, 1])),
        )
        picked = None
        for c in choices:
            if remaining[c] >= size:
                picked = c
                break
        if picked is None:
            raise RuntimeError(
                f"Derby-Komponente mit Größe {size} kann nicht in Liga-Kapazität eingeplant werden."
            )
        for m in members:
            labels[m] = picked
        remaining[picked] -= size

    if np.any(labels < 0):
        raise RuntimeError("Interner Fehler bei Derby-Komponenten-Zuordnung.")
    return labels


def average_away_distance_per_club(labels: np.ndarray, dist_matrix: np.ndarray, cap: int) -> float:
    n = len(labels)
    sums = np.zeros(n, dtype=float)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if labels[i] == labels[j]:
                sums[i] += float(dist_matrix[i, j])
    # jedes Team hat cap-1 Auswaertsspiele innerhalb seiner Liga
    return float(np.mean(sums / max(1, cap - 1)))


def improve_component_swaps_distance_matrix(
    labels: np.ndarray,
    components: List[List[int]],
    dist_matrix: np.ndarray,
    iters: int = 25000,
    seed: int = 42,
    cap: int = 20,
) -> np.ndarray:
    """
    Optimiert mit harten Derby-Komponenten:
    Es werden nur ganze Komponenten zwischen Ligen getauscht (gleiche Groesse).
    """
    rng = np.random.default_rng(seed)
    labels = labels.copy()

    comp_sizes = [len(c) for c in components]
    size_to_comps: Dict[int, List[int]] = {}
    for i, s in enumerate(comp_sizes):
        size_to_comps.setdefault(s, []).append(i)

    # comp -> league
    comp_league = []
    for comp in components:
        comp_league.append(int(labels[comp[0]]))

    def materialize_labels() -> np.ndarray:
        out = labels.copy()
        for ci, members in enumerate(components):
            for m in members:
                out[m] = comp_league[ci]
        return out

    current_labels = materialize_labels()
    current_obj = average_away_distance_per_club(
        current_labels, dist_matrix, cap)

    sizes = [s for s, comps in size_to_comps.items() if len(comps) >= 2]
    if not sizes:
        return current_labels

    for _ in range(iters):
        s = int(rng.choice(sizes))
        comp_idxs = size_to_comps[s]
        a, b = rng.choice(comp_idxs, size=2, replace=False)
        la, lb = comp_league[a], comp_league[b]
        if la == lb:
            continue

        comp_league[a], comp_league[b] = lb, la
        candidate = materialize_labels()
        cand_obj = average_away_distance_per_club(candidate, dist_matrix, cap)
        if cand_obj < current_obj:
            current_obj = cand_obj
            current_labels = candidate
        else:
            comp_league[a], comp_league[b] = la, lb

    return current_labels


def label_compass_names(clubs: List[Club], labels: np.ndarray, k: int) -> Dict[int, str]:
    """
    Benennt Cluster als Nord/Süd/West/Ost anhand der Centroids.
    """
    centroids = compute_centroids(clubs, labels, k)
    idxs = list(range(k))

    north = int(np.argmax(centroids[:, 0]))
    south = int(np.argmin(centroids[:, 0]))

    remaining = [i for i in idxs if i not in {north, south}]
    if len(remaining) != 2:
        # Fallback: sortiere nach lon
        order = sorted(idxs, key=lambda x: centroids[x, 1])
        return {order[0]: "West", order[1]: "Süd", order[2]: "Nord", order[3]: "Ost"}

    west = remaining[0] if centroids[remaining[0],
                                     1] < centroids[remaining[1], 1] else remaining[1]
    east = remaining[1] if west == remaining[0] else remaining[0]

    return {north: "Nord", south: "Süd", west: "West", east: "Ost"}


def league_metrics(clubs: List[Club]) -> Dict[str, float]:
    """
    Einfache Metriken: Ø Paar-Distanz innerhalb der Liga und Max-Paar-Distanz.
    """
    dists = []
    max_d = 0.0
    for i in range(len(clubs)):
        for j in range(i + 1, len(clubs)):
            d = haversine_km(clubs[i].lat, clubs[i].lon,
                             clubs[j].lat, clubs[j].lon)
            dists.append(d)
            if d > max_d:
                max_d = d
    return {
        "avg_pair_km": float(np.mean(dists)) if dists else 0.0,
        "max_pair_km": float(max_d),
    }


def preferred_league_print_order(leagues: Dict[str, List[Club]]) -> List[str]:
    preferred = ["Nord", "West", "Ost", "Sued", "Süd"]
    out = [name for name in preferred if name in leagues]
    out.extend(sorted([name for name in leagues if name not in out]))
    return out


def solution_to_dataframe(
    clubs: List[Club], labels: np.ndarray, k: int
) -> Tuple[pd.DataFrame, Dict[str, List[Club]]]:
    compass = label_compass_names(clubs, labels, k)
    leagues: Dict[str, List[Club]] = {}
    rows: List[Dict[str, Any]] = []

    for c, lab in zip(clubs, labels):
        lname = str(compass[int(lab)])
        leagues.setdefault(lname, []).append(c)
        rows.append({"Liga": lname, "Verein": c.name,
                    "lat": c.lat, "lon": c.lon})

    if len(leagues) != k:
        raise RuntimeError(f"Erwartet {k} Ligen, habe {len(leagues)}.")
    for lname, lst in leagues.items():
        if len(lst) != TEAMS_PER_LEAGUE:
            raise RuntimeError(
                f"Liga {lname} hat {len(lst)} Teams statt {TEAMS_PER_LEAGUE}.")
        leagues[lname] = sorted(
            lst, key=lambda c: normalize_text(c.name).lower())

    df = pd.DataFrame(rows).sort_values(["Liga", "Verein"])
    return df, leagues


def export_solution(clubs: List[Club], labels: np.ndarray, out_csv: str, title: str) -> pd.DataFrame:
    df, leagues = solution_to_dataframe(clubs, labels, N_LEAGUES)
    print(f"\n=== Ergebnis: {title} ===")
    for lname in preferred_league_print_order(leagues):
        m = league_metrics(leagues[lname])
        print(
            f"\n--- {lname} (20 Teams) | Ø Paar-Distanz: {m['avg_pair_km']:.1f} km | Max: {m['max_pair_km']:.1f} km ---"
        )
        for c in leagues[lname]:
            print(f"  - {c.name}")
    ensure_parent_dir(out_csv)
    df.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"\nCSV geschrieben: {out_csv}")
    return df


def labels_to_named_leagues(clubs: List[Club], labels: np.ndarray, k: int) -> Dict[str, str]:
    compass = label_compass_names(clubs, labels, k)
    out: Dict[str, str] = {}
    for c, lab in zip(clubs, labels):
        out[normalize_text(c.name)] = normalize_text(compass[int(lab)])
    return out


def solution_signature_unlabeled(clubs: List[Club], labels: np.ndarray, k: int) -> str:
    parts: List[str] = []
    for cluster_idx in range(k):
        names = sorted(
            normalize_text(clubs[i].name)
            for i in range(len(clubs))
            if int(labels[i]) == cluster_idx
        )
        parts.append("|".join(names))
    parts.sort()
    return "##".join(parts)


def write_solution_diff_csv(
    clubs: List[Club],
    rank1_labels: np.ndarray,
    rank2_labels: np.ndarray,
    out_csv: str,
) -> int:
    rank1 = labels_to_named_leagues(clubs, rank1_labels, N_LEAGUES)
    rank2 = labels_to_named_leagues(clubs, rank2_labels, N_LEAGUES)
    rows: List[Dict[str, str]] = []
    for club in sorted(clubs, key=lambda c: normalize_text(c.name).lower()):
        team = normalize_text(club.name)
        liga_rank1 = rank1.get(team, "")
        liga_rank2 = rank2.get(team, "")
        if liga_rank1 and liga_rank2 and liga_rank1 != liga_rank2:
            rows.append(
                {
                    "Verein": club.name,
                    "Liga_rank1": liga_rank1,
                    "Liga_rank2": liga_rank2,
                }
            )
    ensure_parent_dir(out_csv)
    pd.DataFrame(rows).to_csv(out_csv, index=False, encoding="utf-8")
    print(f"CSV geschrieben: {out_csv} ({len(rows)} Unterschiede)")
    return len(rows)


def matrix_rank_output_csv(rank: int) -> str:
    if rank == 1:
        return OUT_CSV_DEFAULT
    if rank == 2:
        return OUT_CSV_MATRIX_RANK2
    if rank == 3:
        return OUT_CSV_MATRIX_RANK3
    if rank == 5:
        return OUT_CSV_MATRIX_RANK5
    if rank == 10:
        return OUT_CSV_MATRIX_RANK10
    return os.path.join(OUTPUT_CSV_DIR, f"kompass_regionalliga_4x20_matrix_rank{int(rank)}.csv")


def build_extreme_initial_labels(
    clubs: List[Club], mode: str
) -> np.ndarray:
    """
    Erzeugt harte 20er-Gruppen als Initialverteilung:
    - mode='north_south': 20 noerdlichste + 20 suedlichste fix,
      Rest 40 in West/Ost via Laengengrad.
    - mode='west_east': 20 westlichste + 20 oestlichste fix,
      Rest 40 in Nord/Sued via Breitengrad.
    """
    n = len(clubs)
    if n != TARGET_TEAM_COUNT:
        raise RuntimeError(
            f"Extreme Initialverteilung erwartet {TARGET_TEAM_COUNT} Teams, erhalten: {n}"
        )

    idx_all = list(range(n))
    if mode == "north_south":
        by_lat_desc = sorted(
            idx_all, key=lambda i: (clubs[i].lat, -clubs[i].lon), reverse=True
        )
        north = set(by_lat_desc[:TEAMS_PER_LEAGUE])
        south = set(by_lat_desc[-TEAMS_PER_LEAGUE:])
        remaining = [i for i in idx_all if i not in north and i not in south]
        by_lon_asc = sorted(remaining, key=lambda i: (clubs[i].lon, -clubs[i].lat))
        west = set(by_lon_asc[:TEAMS_PER_LEAGUE])
        east = set(by_lon_asc[TEAMS_PER_LEAGUE:])
    elif mode == "west_east":
        by_lon_asc = sorted(idx_all, key=lambda i: (clubs[i].lon, -clubs[i].lat))
        west = set(by_lon_asc[:TEAMS_PER_LEAGUE])
        east = set(by_lon_asc[-TEAMS_PER_LEAGUE:])
        remaining = [i for i in idx_all if i not in west and i not in east]
        by_lat_desc = sorted(
            remaining, key=lambda i: (clubs[i].lat, -clubs[i].lon), reverse=True
        )
        north = set(by_lat_desc[:TEAMS_PER_LEAGUE])
        south = set(by_lat_desc[TEAMS_PER_LEAGUE:])
    else:
        raise RuntimeError(
            f"Unbekannter Modus fuer extreme Initialverteilung: {mode}"
        )

    labels = np.full(n, -1, dtype=int)
    for i in north:
        labels[i] = 0
    for i in west:
        labels[i] = 1
    for i in east:
        labels[i] = 2
    for i in south:
        labels[i] = 3

    if np.any(labels < 0):
        raise RuntimeError(
            f"Extreme Initialverteilung '{mode}' unvollstaendig erzeugt.")
    counts = [int(np.sum(labels == i)) for i in range(N_LEAGUES)]
    if any(c != TEAMS_PER_LEAGUE for c in counts):
        raise RuntimeError(
            f"Extreme Initialverteilung '{mode}' ungueltig (Liga-Groessen={counts})."
        )
    return labels


def build_random_balanced_labels(
    n: int, k: int = N_LEAGUES, cap: int = TEAMS_PER_LEAGUE, seed: int = 0
) -> np.ndarray:
    """Erzeugt eine komplett zufaellige, aber balancierte Partition (k Gruppen a cap)."""
    rng = np.random.default_rng(seed)
    indices = rng.permutation(n)
    labels = np.empty(n, dtype=int)
    for j in range(k):
        labels[indices[j * cap:(j + 1) * cap]] = j
    return labels


def build_geographic_stripe_labels(
    clubs: List[Club], mode: str, k: int = N_LEAGUES, cap: int = TEAMS_PER_LEAGUE
) -> np.ndarray:
    """
    Teilt Teams in k gleich grosse Streifen entlang einer geographischen Achse.
    mode: 'lat' (horizontale Streifen N->S), 'lon' (vertikale Streifen W->O),
          'diag_nw_se' (Diagonale NW->SO), 'diag_ne_sw' (Diagonale NO->SW)
    """
    n = len(clubs)
    if mode == "lat":
        keys = [c.lat for c in clubs]
    elif mode == "lon":
        keys = [c.lon for c in clubs]
    elif mode == "diag_nw_se":
        keys = [c.lat + c.lon for c in clubs]
    elif mode == "diag_ne_sw":
        keys = [c.lat - c.lon for c in clubs]
    else:
        raise ValueError(f"Unbekannter Stripe-Modus: {mode}")

    sorted_indices = sorted(range(n), key=lambda i: keys[i])
    labels = np.empty(n, dtype=int)
    for j in range(k):
        for i in sorted_indices[j * cap:(j + 1) * cap]:
            labels[i] = j
    return labels


def optimize_candidate_from_seed(
    clubs: List[Club],
    dist_matrix: np.ndarray,
    labels_start: np.ndarray,
    run_no: int,
    base_seed: int,
    origin: str,
    centroid_iters: int,
    matrix_iters: int,
    component_iters: int,
    shake_fraction: float,
    accept_equal_prob: float,
    anneal_start_temp_km: float,
    anneal_end_temp_km: float,
    move_2_prob: float,
    move_3_prob: float,
    move_4_prob: float,
    stagnation_shake_iters: int,
    stagnation_shake_fraction: float,
    derby_components: Optional[List[List[int]]] = None,
) -> Dict[str, Any]:
    labels_balanced = balance_clusters(
        clubs, labels_start.copy(), N_LEAGUES, TEAMS_PER_LEAGUE)
    if centroid_iters > 0:
        labels_centroid = improve_by_swaps(
            clubs,
            labels_balanced,
            N_LEAGUES,
            iters=centroid_iters,
            seed=base_seed + 17,
        )
    else:
        labels_centroid = labels_balanced.copy()

    shake_swaps = int(round(len(labels_centroid) * max(0.0, shake_fraction)))
    labels_seeded = shake_labels_by_random_swaps(
        labels=labels_centroid,
        k=N_LEAGUES,
        swap_count=shake_swaps,
        seed=base_seed + 23,
    )

    if ENFORCE_DERBY_SAME_LEAGUE:
        if derby_components is None:
            raise RuntimeError("Interner Fehler: derby_components fehlt.")
        centroids = compute_centroids(clubs, labels_seeded, N_LEAGUES)
        initial_matrix_labels = assign_components_initial(
            clubs=clubs,
            components=derby_components,
            centroids=centroids,
            k=N_LEAGUES,
            cap=TEAMS_PER_LEAGUE,
        )
        labels_matrix = improve_component_swaps_distance_matrix(
            labels=initial_matrix_labels,
            components=derby_components,
            dist_matrix=dist_matrix,
            iters=component_iters,
            seed=base_seed + 31,
            cap=TEAMS_PER_LEAGUE,
        )
    else:
        labels_matrix = improve_by_swaps_distance_matrix(
            labels=labels_seeded,
            dist_matrix=dist_matrix,
            k=N_LEAGUES,
            iters=matrix_iters,
            seed=base_seed + 31,
            accept_equal_prob=max(0.0, accept_equal_prob),
            anneal_start_temp_km=max(0.0, anneal_start_temp_km),
            anneal_end_temp_km=max(0.0, anneal_end_temp_km),
            move_2_prob=max(0.0, move_2_prob),
            move_3_prob=max(0.0, move_3_prob),
            move_4_prob=max(0.0, move_4_prob),
            stagnation_shake_iters=max(0, int(stagnation_shake_iters)),
            stagnation_shake_fraction=max(0.0, stagnation_shake_fraction),
        )

    centroid_avg = average_away_distance_per_club(
        labels_centroid, dist_matrix, TEAMS_PER_LEAGUE)
    matrix_avg = average_away_distance_per_club(
        labels_matrix, dist_matrix, TEAMS_PER_LEAGUE)
    matrix_intra = objective_intra_league_sum(labels_matrix, dist_matrix)
    signature = solution_signature_unlabeled(clubs, labels_matrix, N_LEAGUES)
    return {
        "run": int(run_no),
        "seed": int(base_seed),
        "origin": origin,
        "labels_centroid": labels_centroid.copy(),
        "labels_matrix": labels_matrix.copy(),
        "centroid_avg_away_km": float(centroid_avg),
        "matrix_avg_away_km": float(matrix_avg),
        "matrix_intra_km": float(matrix_intra),
        "signature": signature,
    }


def add_or_replace_candidate(
    candidates: List[Dict[str, Any]],
    by_signature: Dict[str, int],
    entry: Dict[str, Any],
) -> None:
    signature = str(entry.get("signature", ""))
    if not signature:
        return
    existing_idx = by_signature.get(signature)
    if existing_idx is None:
        by_signature[signature] = len(candidates)
        candidates.append(entry)
        return
    current = candidates[existing_idx]
    key_new = (
        float(entry.get("matrix_avg_away_km", 1e18)),
        float(entry.get("matrix_intra_km", 1e18)),
        int(entry.get("run", 10**9)),
    )
    key_old = (
        float(current.get("matrix_avg_away_km", 1e18)),
        float(current.get("matrix_intra_km", 1e18)),
        int(current.get("run", 10**9)),
    )
    if key_new < key_old:
        candidates[existing_idx] = entry


def partition_distance_with_best_relabel(
    labels_a: np.ndarray,
    labels_b: np.ndarray,
    k: int,
) -> int:
    """
    Anzahl Teams, die nach optimaler Cluster-Umbenennung unterschiedlich liegen.
    Label-invariant und damit fuer Diversitaet geeignet.
    """
    if len(labels_a) != len(labels_b):
        raise RuntimeError("Partition-Distanz: Labelvektoren ungleich lang.")
    overlap = np.zeros((k, k), dtype=int)
    for i in range(len(labels_a)):
        a = int(labels_a[i])
        b = int(labels_b[i])
        if a < 0 or a >= k or b < 0 or b >= k:
            raise RuntimeError(
                f"Partition-Distanz: ungueltige Labelwerte ({a}, {b}) bei k={k}."
            )
        overlap[a, b] += 1

    best_overlap = 0
    for perm in itertools.permutations(range(k)):
        s = 0
        for a in range(k):
            s += int(overlap[a, perm[a]])
        if s > best_overlap:
            best_overlap = s
    return int(len(labels_a) - best_overlap)


def solve_milp(
    clubs: List["Club"],
    dist_matrix: np.ndarray,
    k: int = N_LEAGUES,
    cap: int = TEAMS_PER_LEAGUE,
    time_limit_s: int = int(os.getenv("KOMPASS_MILP_TIME_LIMIT", "600")),
    mip_gap: float = float(os.getenv("KOMPASS_MILP_GAP", "0.005")),
) -> Optional[np.ndarray]:
    """
    Exakter MILP-Solver fuer die balancierte Ligaeinteilung (optional).

    Minimiert die Summe aller Intra-Liga-Paardistanzen (identisch zur
    Heuristik-Objective).  Benoetigt PuLP + CBC-Solver; wenn nicht
    installiert, wird None zurueckgegeben.

    EINSCHRAENKUNGEN (CBC mit n=80):
    - LP-Relaxation hat Lower Bound = 0 (schwache Schranke), daher kann CBC
      die Optimalitaet praktisch nie beweisen.
    - Die Root-Node-Cut-Generierung kann das Zeitlimit blockieren – CBC kann
      fuer n=80 Minuten bis Stunden benoetigen.
    - Empfehlung: Nur fuer kleine Teilmengen (n<=32) oder mit Gurobi/CPLEX
      als Solver verwenden.  Fuer n=80 liefert die Heuristik bessere
      Ergebnisse in deutlich kuerzerer Zeit.

    Aufruf (mit explizitem Zeitlimit):
        from kompass import *
        teams = select_teams_for_season(80)
        clubs = build_clubs(teams); dm = compute_distance_matrix_km(clubs)
        labels = solve_milp(clubs, dm, time_limit_s=120, mip_gap=0.05)
        if labels is not None: export_solution(clubs, labels, 'milp_result.csv', 'MILP')

    Umgebungsvariablen (werden nur ausgewertet wenn kein Argument uebergeben):
        KOMPASS_MILP_TIME_LIMIT  Zeitlimit in Sekunden (Default 600)
        KOMPASS_MILP_GAP         Optimality-Gap-Toleranz (Default 0.005 = 0.5%)
    """
    try:
        import pulp
    except ImportError:
        print("PuLP nicht installiert – MILP-Solver uebersprungen. "
              "Installieren mit: pip install pulp")
        return None

    n = len(clubs)
    if n != k * cap:
        raise ValueError(f"solve_milp: n={n} != k*cap={k*cap}")

    prob = pulp.LpProblem("Kompass_MILP", pulp.LpMinimize)

    # x[i][j] = 1 wenn Team i in Liga j
    x = [[pulp.LpVariable(f"x_{i}_{j}", cat="Binary") for j in range(k)] for i in range(n)]

    # Linearisierungsvariablen y[i][l][j] = x[i][j] * x[l][j]  (i < l)
    # Statt alle O(n^2*k) Vars zu erzeugen, nutzen wir nur die obere Dreiecksmatrix
    y: dict = {}
    for i in range(n):
        for l in range(i + 1, n):
            for j in range(k):
                y[(i, l, j)] = pulp.LpVariable(f"y_{i}_{l}_{j}", lowBound=0, upBound=1)

    # Objective: minimiere Summe aller Intra-Liga-Paardistanzen
    prob += pulp.lpSum(
        dist_matrix[i, l] * y[(i, l, j)]
        for i in range(n) for l in range(i + 1, n) for j in range(k)
    )

    # Jedes Team in genau einer Liga
    for i in range(n):
        prob += pulp.lpSum(x[i][j] for j in range(k)) == 1

    # Jede Liga hat genau `cap` Teams
    for j in range(k):
        prob += pulp.lpSum(x[i][j] for i in range(n)) == cap

    # McCormick-Linearisierung: y[i,l,j] <= x[i][j], y[i,l,j] <= x[l][j],
    # y[i,l,j] >= x[i][j] + x[l][j] - 1
    for i in range(n):
        for l in range(i + 1, n):
            for j in range(k):
                yvar = y[(i, l, j)]
                prob += yvar <= x[i][j]
                prob += yvar <= x[l][j]
                prob += yvar >= x[i][j] + x[l][j] - 1

    # threads=1 ensures CBC respects the wall-clock time limit reliably.
    # Multi-threaded CBC may not honour timeLimit correctly on some platforms.
    solver = pulp.PULP_CBC_CMD(
        timeLimit=time_limit_s,
        gapRel=mip_gap,
        msg=1,
        threads=1,
    )
    prob.solve(solver)
    print(f"MILP Status: {pulp.LpStatus[prob.status]} | "
          f"Objective: {pulp.value(prob.objective):.2f} km")

    if prob.status not in (pulp.LpStatusNotSolved, -1):
        labels = np.zeros(n, dtype=int)
        for i in range(n):
            for j in range(k):
                if pulp.value(x[i][j]) is not None and pulp.value(x[i][j]) > 0.5:
                    labels[i] = j
                    break
        return labels
    return None


def solve_cpsat(
    clubs: List["Club"],
    dist_matrix: np.ndarray,
    k: int = N_LEAGUES,
    cap: int = TEAMS_PER_LEAGUE,
    time_limit_s: int = 120,
    warm_start: Optional[np.ndarray] = None,
) -> Optional[np.ndarray]:
    """
    CP-SAT Solver fuer die balancierte Ligaeinteilung (Google OR-Tools).

    Deutlich schneller als CBC-MILP fuer dieses Problem, da CP-SAT intern
    einen Portfolio-Ansatz nutzt (SAT, LP, LNS gleichzeitig).

    Args:
        clubs: Liste der Clubs
        dist_matrix: n x n Distanzmatrix in km
        k: Anzahl Ligen
        cap: Teams pro Liga
        time_limit_s: Zeitlimit in Sekunden
        warm_start: Optionale Startloesung (Label-Array) als Hint

    Returns:
        Label-Array oder None wenn keine Loesung gefunden
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        print("OR-Tools nicht installiert – CP-SAT-Solver uebersprungen. "
              "Installieren mit: pip install ortools")
        return None

    n = len(clubs)
    if n != k * cap:
        raise ValueError(f"solve_cpsat: n={n} != k*cap={k*cap}")

    model = cp_model.CpModel()

    # x[i][j] = 1 wenn Team i in Liga j
    x = [[model.new_bool_var(f"x_{i}_{j}") for j in range(k)] for i in range(n)]

    # Jedes Team in genau einer Liga
    for i in range(n):
        model.add_exactly_one(x[i][j] for j in range(k))

    # Jede Liga hat genau cap Teams
    for j in range(k):
        model.add(sum(x[i][j] for i in range(n)) == cap)

    # Objective: minimiere Summe aller Intra-Liga-Paardistanzen
    # CP-SAT arbeitet mit Ganzzahlen -> Distanzen in Metern (int) skalieren
    SCALE = 100  # 2 Nachkommastellen der km-Distanz
    obj_terms = []
    b_vars: List[tuple] = []  # (i, l, j, b_var) fuer Warm-Start
    for i in range(n):
        for l in range(i + 1, n):
            d_scaled = int(round(dist_matrix[i, l] * SCALE))
            if d_scaled == 0:
                continue
            for j in range(k):
                # b = x[i][j] AND x[l][j]  (beide Teams in derselben Liga)
                b = model.new_bool_var(f"b_{i}_{l}_{j}")
                model.add_implication(b, x[i][j])
                model.add_implication(b, x[l][j])
                model.add_bool_or([b, x[i][j].negated(), x[l][j].negated()])
                obj_terms.append(d_scaled * b)
                b_vars.append((i, l, j, b))

    model.minimize(sum(obj_terms))

    # Warm-Start Hint (falls vorhanden)
    if warm_start is not None and len(warm_start) == n:
        for i in range(n):
            for j in range(k):
                model.add_hint(x[i][j], 1 if warm_start[i] == j else 0)
        for i, l, j, bv in b_vars:
            model.add_hint(bv, 1 if (warm_start[i] == j and warm_start[l] == j) else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = max(1, os.cpu_count() or 1)
    solver.parameters.log_search_progress = True

    print(f"CP-SAT: n={n}, k={k}, cap={cap}, time_limit={time_limit_s}s, "
          f"workers={solver.parameters.num_workers}", flush=True)

    status = solver.solve(model)

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, f"STATUS_{status}")

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        obj_km = solver.objective_value / SCALE
        print(f"CP-SAT Status: {status_name} | "
              f"Objective: {obj_km:.2f} km | "
              f"Bound: {solver.best_objective_bound / SCALE:.2f} km | "
              f"Gap: {(obj_km - solver.best_objective_bound / SCALE) / max(obj_km, 1) * 100:.1f}%")
        labels = np.zeros(n, dtype=int)
        for i in range(n):
            for j in range(k):
                if solver.value(x[i][j]):
                    labels[i] = j
                    break
        return labels

    print(f"CP-SAT Status: {status_name} – keine Loesung gefunden")
    return None


def select_phase2_elites(
    phase1_ranked: List[Dict[str, Any]],
    elite_count: int,
    k: int,
) -> Tuple[List[Dict[str, Any]], str]:
    if not phase1_ranked or elite_count <= 0:
        return [], "score"

    mode = PHASE2_ELITE_SELECTION_MODE
    if mode not in {"score", "diverse"}:
        mode = "diverse"

    elite_count = min(max(1, elite_count), len(phase1_ranked))
    if mode == "score" or elite_count == 1:
        return phase1_ranked[:elite_count], "score"

    pool_mult = max(1, int(PHASE2_DIVERSE_POOL_MULTIPLIER))
    pool_size = min(len(phase1_ranked), max(elite_count, elite_count * pool_mult))
    pool = phase1_ranked[:pool_size]

    max_gap = max(0.0, float(PHASE2_DIVERSE_MAX_SCORE_GAP_KM))
    if max_gap > 0.0 and pool:
        best_score = float(pool[0]["matrix_avg_away_km"])
        filtered = [
            e for e in pool
            if float(e["matrix_avg_away_km"]) <= best_score + max_gap
        ]
        if len(filtered) >= elite_count:
            pool = filtered

    selected: List[Dict[str, Any]] = [pool[0]]
    remaining: List[Dict[str, Any]] = pool[1:]

    while len(selected) < elite_count and remaining:
        best_idx = 0
        best_key: Optional[Tuple[int, float, int]] = None
        for idx, cand in enumerate(remaining):
            cand_labels = cand["labels_matrix"]
            min_div = min(
                partition_distance_with_best_relabel(
                    cand_labels, sel["labels_matrix"], k)
                for sel in selected
            )
            key = (
                int(min_div),  # hoechste Diversitaet zuerst
                -float(cand["matrix_avg_away_km"]),  # bei Gleichstand besserer Score
                -int(cand.get("run", 0)),  # stabiler Tie-Break
            )
            if best_key is None or key > best_key:
                best_key = key
                best_idx = idx
        selected.append(remaining.pop(best_idx))

    if len(selected) < elite_count:
        used = {str(e.get("signature", "")) for e in selected}
        for e in phase1_ranked:
            sig = str(e.get("signature", ""))
            if sig in used:
                continue
            selected.append(e)
            used.add(sig)
            if len(selected) >= elite_count:
                break

    return selected[:elite_count], "diverse"


def run_multi_start_search(
    clubs: List[Club],
    X: np.ndarray,
    dist_matrix: np.ndarray,
    seeded_labels: Optional[np.ndarray] = None,
    runs_override: Optional[int] = None,
    extra_initial_seeds: Optional[List[Tuple[str, np.ndarray]]] = None,
) -> List[Dict[str, Any]]:
    runs_count = int(runs_override) if runs_override is not None else MULTI_START_RUNS
    if runs_count <= 0:
        raise RuntimeError("MULTI_START_RUNS muss > 0 sein.")

    derby_components: Optional[List[List[int]]] = None
    if ENFORCE_DERBY_SAME_LEAGUE:
        derby_components = build_derby_components(
            dist_matrix, DERBY_MAX_DISTANCE_KM)
        if any(len(comp) > TEAMS_PER_LEAGUE for comp in derby_components):
            raise RuntimeError(
                "Derby-Regel unloesbar: mindestens eine Derby-Komponente ist groesser als Liga-Kapazitaet."
            )
        derby_pairs = sum(len(comp) * (len(comp) - 1) //
                          2 for comp in derby_components if len(comp) > 1)
        print(
            "Distanzmatrix-Variante mit Derby-Regel "
            f"<= {DERBY_MAX_DISTANCE_KM:.0f} km: {len(derby_components)} Komponenten, "
            f"interne Derby-Paare={derby_pairs}"
        )

    candidates: List[Dict[str, Any]] = []
    by_signature: Dict[str, int] = {}

    print(
        "Starte 2-Phasen-Heuristik: "
        f"phase1_runs={runs_count}, phase2_elites={PHASE2_ELITE_COUNT}, "
        f"phase2_elite_mode={PHASE2_ELITE_SELECTION_MODE}, "
        f"phase2_restarts={PHASE2_RESTARTS_PER_ELITE}, "
        f"phase1_matrix_iters={MULTI_START_MATRIX_SWAP_ITERS}, "
        f"phase2_matrix_iters={PHASE2_MATRIX_SWAP_ITERS}, "
        f"moves_phase1=(2:{MATRIX_MOVE_2_PROB:.2f},3:{MATRIX_MOVE_3_PROB:.2f},4:{MATRIX_MOVE_4_PROB:.2f}), "
        f"moves_phase2=(2:{PHASE2_MATRIX_MOVE_2_PROB:.2f},3:{PHASE2_MATRIX_MOVE_3_PROB:.2f},4:{PHASE2_MATRIX_MOVE_4_PROB:.2f})"
    )

    deterministic_seeds: List[Tuple[str, np.ndarray]] = []
    if extra_initial_seeds:
        deterministic_seeds.extend(
            [(str(name), labels.copy()) for name, labels in extra_initial_seeds]
        )
    if seeded_labels is not None:
        deterministic_seeds.append(("initial_manual", seeded_labels.copy()))

    for idx, (origin, labels_seed) in enumerate(deterministic_seeds, start=1):
        base_seed = MULTI_START_BASE_SEED - 1000 - idx
        entry = optimize_candidate_from_seed(
            clubs=clubs,
            dist_matrix=dist_matrix,
            labels_start=labels_seed,
            run_no=-idx,
            base_seed=base_seed,
            origin=origin,
            centroid_iters=MULTI_START_CENTROID_SWAP_ITERS,
            matrix_iters=MULTI_START_MATRIX_SWAP_ITERS,
            component_iters=MULTI_START_COMPONENT_SWAP_ITERS,
            shake_fraction=MULTI_START_SHAKE_SWAP_FRACTION,
            accept_equal_prob=MATRIX_ACCEPT_EQUAL_PROB,
            anneal_start_temp_km=MATRIX_ANNEAL_START_TEMP_KM,
            anneal_end_temp_km=MATRIX_ANNEAL_END_TEMP_KM,
            move_2_prob=MATRIX_MOVE_2_PROB,
            move_3_prob=MATRIX_MOVE_3_PROB,
            move_4_prob=MATRIX_MOVE_4_PROB,
            stagnation_shake_iters=MATRIX_STAGNATION_SHAKE_ITERS,
            stagnation_shake_fraction=MATRIX_STAGNATION_SHAKE_FRACTION,
            derby_components=derby_components,
        )
        add_or_replace_candidate(candidates, by_signature, entry)
        print(
            f"[Phase1-Seed] {origin} | score={entry['matrix_avg_away_km']:.2f} km | "
            f"eindeutig={len(candidates)}"
        )

    progress_step = max(1, runs_count // 10)
    for run_idx in range(runs_count):
        run_no = run_idx + 1
        base_seed = MULTI_START_BASE_SEED + run_idx

        km = KMeans(
            n_clusters=N_LEAGUES,
            n_init=MULTI_START_KMEANS_N_INIT,
            random_state=base_seed,
        )
        labels0 = km.fit_predict(X)
        entry = optimize_candidate_from_seed(
            clubs,
            dist_matrix=dist_matrix,
            labels_start=labels0,
            run_no=run_no,
            base_seed=base_seed,
            origin="phase1_random",
            centroid_iters=MULTI_START_CENTROID_SWAP_ITERS,
            matrix_iters=MULTI_START_MATRIX_SWAP_ITERS,
            component_iters=MULTI_START_COMPONENT_SWAP_ITERS,
            shake_fraction=MULTI_START_SHAKE_SWAP_FRACTION,
            accept_equal_prob=MATRIX_ACCEPT_EQUAL_PROB,
            anneal_start_temp_km=MATRIX_ANNEAL_START_TEMP_KM,
            anneal_end_temp_km=MATRIX_ANNEAL_END_TEMP_KM,
            move_2_prob=MATRIX_MOVE_2_PROB,
            move_3_prob=MATRIX_MOVE_3_PROB,
            move_4_prob=MATRIX_MOVE_4_PROB,
            stagnation_shake_iters=MATRIX_STAGNATION_SHAKE_ITERS,
            stagnation_shake_fraction=MATRIX_STAGNATION_SHAKE_FRACTION,
            derby_components=derby_components,
        )
        add_or_replace_candidate(candidates, by_signature, entry)

        if run_no == 1 or run_no % progress_step == 0 or run_no == runs_count:
            best_so_far = min(c["matrix_avg_away_km"] for c in candidates)
            print(
                f"[Phase1] Lauf {run_no}/{runs_count} | "
                f"aktuell={entry['matrix_avg_away_km']:.2f} km | best={best_so_far:.2f} km | "
                f"eindeutig={len(candidates)}"
            )

    phase1_ranked = sorted(
        candidates,
        key=lambda x: (x["matrix_avg_away_km"],
                       x["matrix_intra_km"], x["run"]),
    )
    if not phase1_ranked:
        raise RuntimeError("2-Phasen-Heuristik hat keine Kandidaten erzeugt.")

    elite_count = min(max(1, PHASE2_ELITE_COUNT), len(phase1_ranked))
    elites, elite_mode_used = select_phase2_elites(
        phase1_ranked=phase1_ranked,
        elite_count=elite_count,
        k=N_LEAGUES,
    )
    if not elites:
        raise RuntimeError("Phase-2-Eliteauswahl hat keine Kandidaten geliefert.")

    diversity_to_best: List[int] = []
    elite_ref = elites[0]["labels_matrix"]
    for e in elites:
        diversity_to_best.append(
            partition_distance_with_best_relabel(
                elite_ref, e["labels_matrix"], N_LEAGUES)
        )
    avg_div_to_best = float(
        np.mean(diversity_to_best)) if diversity_to_best else 0.0
    max_div_to_best = max(diversity_to_best) if diversity_to_best else 0
    print(
        "Phase 1 abgeschlossen: "
        f"eindeutige_loesungen={len(phase1_ranked)}, elites={elite_count}, "
        f"best={phase1_ranked[0]['matrix_avg_away_km']:.2f} km, "
        f"elite_mode={elite_mode_used}, "
        f"diversity_to_best(avg/max)={avg_div_to_best:.1f}/{max_div_to_best}"
    )

    total_phase2 = elite_count * max(0, PHASE2_RESTARTS_PER_ELITE)
    if total_phase2 > 0:
        phase2_progress = max(1, total_phase2 // 10)
        done = 0
        for elite_idx, elite in enumerate(elites, start=1):
            for restart_idx in range(PHASE2_RESTARTS_PER_ELITE):
                done += 1
                base_seed = PHASE2_BASE_SEED + elite_idx * 1000 + restart_idx
                entry = optimize_candidate_from_seed(
                    clubs=clubs,
                    dist_matrix=dist_matrix,
                    labels_start=elite["labels_matrix"],
                    run_no=runs_count + done,
                    base_seed=base_seed,
                    origin=f"phase2_elite_{elite_idx}",
                    centroid_iters=PHASE2_CENTROID_SWAP_ITERS,
                    matrix_iters=PHASE2_MATRIX_SWAP_ITERS,
                    component_iters=PHASE2_COMPONENT_SWAP_ITERS,
                    shake_fraction=PHASE2_SHAKE_SWAP_FRACTION,
                    accept_equal_prob=PHASE2_MATRIX_ACCEPT_EQUAL_PROB,
                    anneal_start_temp_km=PHASE2_MATRIX_ANNEAL_START_TEMP_KM,
                    anneal_end_temp_km=PHASE2_MATRIX_ANNEAL_END_TEMP_KM,
                    move_2_prob=PHASE2_MATRIX_MOVE_2_PROB,
                    move_3_prob=PHASE2_MATRIX_MOVE_3_PROB,
                    move_4_prob=PHASE2_MATRIX_MOVE_4_PROB,
                    stagnation_shake_iters=PHASE2_MATRIX_STAGNATION_SHAKE_ITERS,
                    stagnation_shake_fraction=PHASE2_MATRIX_STAGNATION_SHAKE_FRACTION,
                    derby_components=derby_components,
                )
                add_or_replace_candidate(candidates, by_signature, entry)
                if done == 1 or done % phase2_progress == 0 or done == total_phase2:
                    best_so_far = min(c["matrix_avg_away_km"] for c in candidates)
                    print(
                        f"[Phase2] Lauf {done}/{total_phase2} | "
                        f"aktuell={entry['matrix_avg_away_km']:.2f} km | "
                        f"best={best_so_far:.2f} km | eindeutig={len(candidates)}"
                    )

    ranked = sorted(
        candidates,
        key=lambda x: (x["matrix_avg_away_km"],
                       x["matrix_intra_km"], x["run"]),
    )
    for idx, entry in enumerate(ranked, start=1):
        entry["rank"] = idx

    best_val = ranked[0]["matrix_avg_away_km"]
    second_gap = (
        ranked[1]["matrix_avg_away_km"] - best_val
        if len(ranked) > 1
        else 0.0
    )
    print(
        "2-Phasen-Heuristik abgeschlossen: "
        f"phase1_runs={runs_count}, phase2_runs={total_phase2}, "
        f"eindeutige_loesungen={len(ranked)}, best={best_val:.2f} km, "
        f"gap(rank2-rank1)={second_gap:.2f} km"
    )
    return ranked


# -------------------------
# Phase 3: Large Neighborhood Search (Ruin & Recreate)
# -------------------------
LNS_ITERATIONS: int = int(os.getenv("KOMPASS_LNS_ITERATIONS", "200"))
LNS_DESTROY_FRACTION: float = float(os.getenv("KOMPASS_LNS_DESTROY_FRACTION", "0.35"))
LNS_ENABLED: bool = os.getenv("KOMPASS_LNS_ENABLED", "1") == "1"

# -------------------------
# Phase 4: CP-SAT (optional, benoetigt ortools)
# -------------------------
CPSAT_ENABLED: bool = os.getenv("KOMPASS_CPSAT_ENABLED", "0") == "1"
CPSAT_TIME_LIMIT: int = int(os.getenv("KOMPASS_CPSAT_TIME_LIMIT", "120"))


def _lns_ruin_and_recreate(
    clubs: List[Club],
    dist_matrix: np.ndarray,
    labels: np.ndarray,
    destroy_fraction: float,
    rng: np.random.Generator,
    k: int = N_LEAGUES,
    cap: int = TEAMS_PER_LEAGUE,
) -> np.ndarray:
    """
    Ruin & Recreate: Entferne einen Anteil der Teams aus ihren Ligen,
    dann ordne sie gierig der nächsten Liga zu (Distanz zum Liga-Schwerpunkt),
    wobei die Liga-Kapazitaet eingehalten wird.
    """
    n = len(clubs)
    n_destroy = max(2, int(round(n * destroy_fraction)))
    destroyed_indices = set(rng.choice(n, size=n_destroy, replace=False).tolist())

    new_labels = labels.copy()
    for i in destroyed_indices:
        new_labels[i] = -1

    # Liga-Schwerpunkte aus den noch zugewiesenen Teams berechnen
    centroids = np.zeros((k, 2))
    counts = np.zeros(k)
    for i in range(n):
        if new_labels[i] >= 0:
            centroids[new_labels[i]] += [clubs[i].lat, clubs[i].lon]
            counts[new_labels[i]] += 1
    for j in range(k):
        if counts[j] > 0:
            centroids[j] /= counts[j]

    # Gierig: zerstoerte Teams in zufaelliger Reihenfolge einsetzen
    remaining = list(destroyed_indices)
    rng.shuffle(remaining)
    for i in remaining:
        best_j = -1
        best_cost = float("inf")
        for j in range(k):
            if counts[j] >= cap:
                continue
            cost = haversine_km(clubs[i].lat, clubs[i].lon,
                                centroids[j][0], centroids[j][1])
            if cost < best_cost:
                best_cost = cost
                best_j = j
        if best_j < 0:
            # Alle Ligen voll -> in die naechstbeste zuweisen (sollte nicht passieren)
            best_j = int(rng.integers(0, k))
        new_labels[i] = best_j
        # Schwerpunkt aktualisieren
        old_count = counts[best_j]
        centroids[best_j] = (centroids[best_j] * old_count +
                              [clubs[i].lat, clubs[i].lon]) / (old_count + 1)
        counts[best_j] += 1

    return new_labels


def _compute_intra_pair_sum(dist_matrix: np.ndarray, labels: np.ndarray) -> float:
    """Summe aller Paar-Distanzen innerhalb derselben Liga."""
    total = 0.0
    n = len(labels)
    for i in range(n):
        for l in range(i + 1, n):
            if labels[i] == labels[l]:
                total += dist_matrix[i, l]
    return total


def run_lns_phase(
    clubs: List[Club],
    dist_matrix: np.ndarray,
    best_labels: np.ndarray,
    iterations: int = LNS_ITERATIONS,
    destroy_fraction: float = LNS_DESTROY_FRACTION,
    seed: int = 54321,
) -> np.ndarray:
    """
    Large Neighborhood Search: iterativ die beste Loesung durch Ruin & Recreate
    verbessern.  Akzeptiert nur strikt bessere Loesungen (greedy descent).
    """
    rng = np.random.default_rng(seed)
    current = best_labels.copy()
    current_score = _compute_intra_pair_sum(dist_matrix, current)
    best_score = current_score
    best_result = current.copy()
    improved_count = 0

    print(
        f"[LNS] Start: score={current_score:.2f} km, "
        f"iters={iterations}, destroy={destroy_fraction:.0%}",
        flush=True,
    )

    progress_step = max(1, iterations // 10)
    for it in range(1, iterations + 1):
        candidate = _lns_ruin_and_recreate(
            clubs, dist_matrix, current, destroy_fraction, rng
        )
        candidate_score = _compute_intra_pair_sum(dist_matrix, candidate)
        if candidate_score < current_score:
            current = candidate
            current_score = candidate_score
            if current_score < best_score:
                best_score = current_score
                best_result = current.copy()
                improved_count += 1
        if it % progress_step == 0 or it == iterations:
            print(
                f"[LNS] iter {it}/{iterations} | "
                f"current={current_score:.2f} km | best={best_score:.2f} km | "
                f"improvements={improved_count}",
                flush=True,
            )

    print(
        f"[LNS] Fertig: score {_compute_intra_pair_sum(dist_matrix, best_labels):.2f}"
        f" -> {best_score:.2f} km ({improved_count} Verbesserungen)",
        flush=True,
    )
    return best_result


def build_ranked_solutions_payload(
    clubs: List[Club],
    ranked: List[Dict[str, Any]],
    requested_runs_override: Optional[int] = None,
    search_config_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    top_ranked = ranked[: max(1, TOP_SOLUTIONS_TO_EXPORT)]
    best_value = top_ranked[0]["matrix_avg_away_km"] if top_ranked else None
    solutions: List[Dict[str, Any]] = []

    for entry in top_ranked:
        df, _ = solution_to_dataframe(clubs, entry["labels_matrix"], N_LEAGUES)
        teams_by_league: Dict[str, List[str]] = {}
        for liga, group in df.groupby("Liga", sort=True):
            teams_by_league[normalize_text(liga)] = sorted(
                [normalize_text(x) for x in group["Verein"].tolist()],
                key=lambda x: x.lower(),
            )

        rank = int(entry["rank"])
        csv_name = matrix_rank_output_csv(
            rank) if rank in DISPLAY_MATRIX_RANKS else ""

        gap = 0.0
        if best_value is not None:
            gap = float(entry["matrix_avg_away_km"] - best_value)

        solutions.append(
            {
                "rank": rank,
                "run": int(entry["run"]),
                "seed": int(entry["seed"]),
                "score_avg_away_km": round(float(entry["matrix_avg_away_km"]), 4),
                "score_intra_pair_km": round(float(entry["matrix_intra_km"]), 4),
                "centroid_avg_away_km": round(float(entry["centroid_avg_away_km"]), 4),
                "gap_to_best_km": round(gap, 4),
                "csv": csv_name,
                "teams_by_league": teams_by_league,
            }
        )
        if "origin" in entry:
            solutions[-1]["origin"] = str(entry.get("origin"))

    worst_summary: Dict[str, Any] = {}
    if ranked:
        worst = ranked[-1]
        worst_summary = {
            "rank": int(worst["rank"]),
            "score_avg_away_km": round(float(worst["matrix_avg_away_km"]), 4),
            "score_intra_pair_km": round(float(worst["matrix_intra_km"]), 4),
            "csv": OUT_CSV_MATRIX_WORST,
        }

    if search_config_override is not None:
        search_config = dict(search_config_override)
    else:
        search_config = {
            "mode": "heuristic_two_phase",
            "phase1_runs": MULTI_START_RUNS,
            "base_seed": MULTI_START_BASE_SEED,
            "kmeans_n_init": MULTI_START_KMEANS_N_INIT,
            "phase1_centroid_swap_iters": MULTI_START_CENTROID_SWAP_ITERS,
            "phase1_matrix_swap_iters": MULTI_START_MATRIX_SWAP_ITERS,
            "phase1_component_swap_iters": MULTI_START_COMPONENT_SWAP_ITERS,
            "phase1_shake_swap_fraction": MULTI_START_SHAKE_SWAP_FRACTION,
            "phase1_matrix_accept_equal_prob": MATRIX_ACCEPT_EQUAL_PROB,
            "phase1_matrix_anneal_start_temp_km": MATRIX_ANNEAL_START_TEMP_KM,
            "phase1_matrix_anneal_end_temp_km": MATRIX_ANNEAL_END_TEMP_KM,
            "phase1_move_2_prob": MATRIX_MOVE_2_PROB,
            "phase1_move_3_prob": MATRIX_MOVE_3_PROB,
            "phase1_move_4_prob": MATRIX_MOVE_4_PROB,
            "phase1_stagnation_shake_iters": MATRIX_STAGNATION_SHAKE_ITERS,
            "phase1_stagnation_shake_fraction": MATRIX_STAGNATION_SHAKE_FRACTION,
            "phase2_elite_count": PHASE2_ELITE_COUNT,
            "phase2_elite_selection_mode": PHASE2_ELITE_SELECTION_MODE,
            "phase2_diverse_pool_multiplier": PHASE2_DIVERSE_POOL_MULTIPLIER,
            "phase2_diverse_max_score_gap_km": PHASE2_DIVERSE_MAX_SCORE_GAP_KM,
            "phase2_restarts_per_elite": PHASE2_RESTARTS_PER_ELITE,
            "phase2_base_seed": PHASE2_BASE_SEED,
            "phase2_centroid_swap_iters": PHASE2_CENTROID_SWAP_ITERS,
            "phase2_matrix_swap_iters": PHASE2_MATRIX_SWAP_ITERS,
            "phase2_component_swap_iters": PHASE2_COMPONENT_SWAP_ITERS,
            "phase2_shake_swap_fraction": PHASE2_SHAKE_SWAP_FRACTION,
            "phase2_matrix_accept_equal_prob": PHASE2_MATRIX_ACCEPT_EQUAL_PROB,
            "phase2_matrix_anneal_start_temp_km": PHASE2_MATRIX_ANNEAL_START_TEMP_KM,
            "phase2_matrix_anneal_end_temp_km": PHASE2_MATRIX_ANNEAL_END_TEMP_KM,
            "phase2_move_2_prob": PHASE2_MATRIX_MOVE_2_PROB,
            "phase2_move_3_prob": PHASE2_MATRIX_MOVE_3_PROB,
            "phase2_move_4_prob": PHASE2_MATRIX_MOVE_4_PROB,
            "phase2_stagnation_shake_iters": PHASE2_MATRIX_STAGNATION_SHAKE_ITERS,
            "phase2_stagnation_shake_fraction": PHASE2_MATRIX_STAGNATION_SHAKE_FRACTION,
            "derby_rule_enabled": ENFORCE_DERBY_SAME_LEAGUE,
            "derby_max_distance_km": DERBY_MAX_DISTANCE_KM,
        }
    requested_runs = (
        int(requested_runs_override)
        if requested_runs_override is not None
        else MULTI_START_RUNS
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "objective": "average_away_distance_per_club_km",
        "requested_runs": requested_runs,
        "unique_solutions": len(ranked),
        "search_config": search_config,
        "solutions": solutions,
        "worst_found": worst_summary,
    }


def write_ranked_solutions_json(path: str, payload: Dict[str, Any]) -> None:
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"JSON geschrieben: {path}")


def export_ranked_matrix_outputs(
    clubs: List[Club],
    ranked: List[Dict[str, Any]],
    requested_runs_override: Optional[int] = None,
    search_config_override: Optional[Dict[str, Any]] = None,
) -> None:
    best = ranked[0]
    rank2 = ranked[1] if len(ranked) > 1 else None
    rank2_labels = rank2["labels_matrix"] if rank2 is not None else best["labels_matrix"]

    avg_base = float(best["centroid_avg_away_km"])
    avg_best = float(best["matrix_avg_away_km"])
    print(
        f"Durchschnitt Auswaertsdistanz pro Verein: {avg_base:.2f} -> {avg_best:.2f} km")

    ranked_by_rank = {int(e["rank"]): e for e in ranked}
    for rank in DISPLAY_MATRIX_RANKS:
        entry = ranked_by_rank.get(rank)
        if entry is None:
            print(
                f"Hinweis: Rank {rank} nicht verfuegbar (nur {len(ranked)} eindeutige Loesungen).")
            continue
        out_csv = matrix_rank_output_csv(rank)
        title = f"4 Kompass-Ligen (Distanzmatrix-Optimierung, Rank {rank})"
        if rank == 1:
            title = "4 Kompass-Ligen (Distanzmatrix-Optimierung, Hauptausgabe / Rank 1)"
        export_solution(clubs, entry["labels_matrix"], out_csv, title)

    # Kompatibilitaetsdatei fuer bisherige Matrix-Hauptausgabe.
    export_solution(
        clubs,
        best["labels_matrix"],
        OUT_CSV_MATRIX,
        "4 Kompass-Ligen (Distanzmatrix-Optimierung, Rank 1 / Kompatibilitaet)",
    )
    worst = ranked[-1]
    export_solution(
        clubs,
        worst["labels_matrix"],
        OUT_CSV_MATRIX_WORST,
        f"4 Kompass-Ligen (Distanzmatrix-Optimierung, Worst found / Rank {int(worst['rank'])})",
    )

    diff_count = write_solution_diff_csv(
        clubs,
        best["labels_matrix"],
        rank2_labels,
        OUT_SOLUTION_DIFF_CSV,
    )
    if rank2 is None:
        print("Hinweis: Nur eine eindeutige Matrix-Loesung gefunden; Rank 2 entspricht Rank 1.")
    elif diff_count == 0:
        print("Hinweis: Rank-1 und Rank-2-CSV sind identisch.")

    ranked_payload = build_ranked_solutions_payload(
        clubs,
        ranked,
        requested_runs_override=requested_runs_override,
        search_config_override=search_config_override,
    )
    write_ranked_solutions_json(OUT_SOLUTIONS_RANKED_JSON, ranked_payload)


def export_single_run_matrix_outputs(
    clubs: List[Club],
    labels_seed: np.ndarray,
    labels_matrix: np.ndarray,
    dist_matrix: np.ndarray,
) -> None:
    avg_base = average_away_distance_per_club(
        labels_seed, dist_matrix, TEAMS_PER_LEAGUE)
    avg_alt = average_away_distance_per_club(
        labels_matrix, dist_matrix, TEAMS_PER_LEAGUE)
    print(
        f"Durchschnitt Auswaertsdistanz pro Verein: {avg_base:.2f} -> {avg_alt:.2f} km")

    export_solution(clubs, labels_matrix, OUT_CSV_DEFAULT,
                    "4 Kompass-Ligen (Distanzmatrix-Optimierung, Hauptausgabe)")
    export_solution(clubs, labels_matrix, OUT_CSV_MATRIX,
                    "4 Kompass-Ligen (Distanzmatrix-Optimierung)")
    for rank in (2, 3, 5, 10):
        export_solution(
            clubs,
            labels_matrix,
            matrix_rank_output_csv(rank),
            f"4 Kompass-Ligen (Distanzmatrix-Optimierung, Rank {rank} = Rank 1 im Single-Run)",
        )
    export_solution(
        clubs,
        labels_matrix,
        OUT_CSV_MATRIX_WORST,
        "4 Kompass-Ligen (Distanzmatrix-Optimierung, Worst found = Rank 1 im Single-Run)",
    )
    write_solution_diff_csv(clubs, labels_matrix,
                            labels_matrix, OUT_SOLUTION_DIFF_CSV)
    single_payload = build_ranked_solutions_payload(
        clubs,
        [
            {
                "rank": 1,
                "run": 1,
                "seed": 42,
                "labels_centroid": labels_seed.copy(),
                "labels_matrix": labels_matrix.copy(),
                "centroid_avg_away_km": float(avg_base),
                "matrix_avg_away_km": float(avg_alt),
                "matrix_intra_km": float(objective_intra_league_sum(labels_matrix, dist_matrix)),
            }
        ],
    )
    write_ranked_solutions_json(OUT_SOLUTIONS_RANKED_JSON, single_payload)


def export_initial_distribution(
    clubs: List[Club],
    X: np.ndarray,
    use_multi_start_seed: bool,
    out_csv: str,
    title: str,
) -> np.ndarray:
    seed = MULTI_START_BASE_SEED if use_multi_start_seed else 42
    n_init = MULTI_START_KMEANS_N_INIT if use_multi_start_seed else 50
    km = KMeans(n_clusters=N_LEAGUES, n_init=n_init, random_state=seed)
    labels = km.fit_predict(X)
    labels = balance_clusters(clubs, labels, N_LEAGUES, TEAMS_PER_LEAGUE)
    export_solution(
        clubs,
        labels,
        out_csv,
        f"4 Kompass-Ligen ({title}, seed={seed}, n_init={n_init})",
    )
    return labels


def load_initial_labels_from_csv(clubs: List[Club], path: str) -> np.ndarray:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Initial-CSV nicht gefunden: {path}")
    df = pd.read_csv(p)
    required = {"Verein", "Liga"}
    if not required.issubset(set(df.columns)):
        raise RuntimeError(
            f"Initial-CSV braucht Spalten {sorted(required)}: {path}")

    team_to_league: Dict[str, str] = {}
    for _, row in df.iterrows():
        team = normalize_text(str(row["Verein"]))
        league = normalize_text(str(row["Liga"]))
        if not team or not league:
            continue
        team_to_league[team] = league

    club_names = [normalize_text(c.name) for c in clubs]
    missing = [n for n in club_names if n not in team_to_league]
    extra = [n for n in team_to_league if n not in set(club_names)]
    if missing or extra:
        raise RuntimeError(
            f"Initial-CSV passt nicht zur Teamliste. Fehlend={len(missing)}, zusaetzlich={len(extra)}"
        )

    leagues = sorted(set(team_to_league.values()), key=lambda x: x.lower())
    if len(leagues) != N_LEAGUES:
        raise RuntimeError(
            f"Initial-CSV hat {len(leagues)} Ligen, erwartet sind {N_LEAGUES}."
        )
    league_to_id = {league: idx for idx, league in enumerate(leagues)}
    labels = np.array([league_to_id[team_to_league[n]]
                      for n in club_names], dtype=int)

    counts = [int(np.sum(labels == i)) for i in range(N_LEAGUES)]
    if any(c != TEAMS_PER_LEAGUE for c in counts):
        raise RuntimeError(
            f"Initial-CSV ungueltige Groessen: {counts} (erwartet je {TEAMS_PER_LEAGUE})"
        )
    return labels


def select_teams_for_season(target_count: int) -> List[str]:
    if USE_REFORM_12_4_14_RULE:
        try:
            teams = build_reform_12_4_14_team_pool(target_count)
        except Exception as exc:
            print(f"Reformregel fehlgeschlagen ({type(exc).__name__}): {exc}")
            print("Fallback auf regelbasierte Saisonlogik.")
            teams = build_rule_based_team_pool(target_count)
    elif USE_RULE_BASED_SEASON_LOGIC:
        try:
            teams = build_rule_based_team_pool(target_count)
        except Exception as exc:
            print(
                f"Regelbasierte Saisonlogik fehlgeschlagen ({type(exc).__name__}): {exc}")
            print("Fallback auf statische Regionalliga-Liste + Oberliga-Auffuellen.")
            teams = fill_up_to_target(
                build_static_regionalliga_base_pool(), target_count)
    else:
        teams = fill_up_to_target(
            build_static_regionalliga_base_pool(), target_count)

    if not (USE_REFORM_12_4_14_RULE and REFORM_STRICT_QUOTA_ALLOW_RESERVES):
        assert all(not is_u23_or_reserve(t) for t in teams), (
            "Filterfehler: U/Reserve-Team nach Auffuellen gefunden."
        )

    print(f"Teams gesamt (nach Filter + ggf. Auffuellen): {len(teams)}")
    if len(teams) != target_count:
        raise RuntimeError(
            f"Erwartet {target_count} Teams, habe {len(teams)}.")
    return teams


# -------------------------
# Main
# -------------------------
def main() -> None:
    # 1) Teamliste bauen
    teams = select_teams_for_season(TARGET_TEAM_COUNT)

    # 2) Koordinaten holen
    clubs = build_clubs(teams)
    X = clubs_to_array(clubs)
    dist_matrix = compute_distance_matrix_km(clubs)

    # 3) Initialverteilungen erzeugen
    auto_initial_labels = export_initial_distribution(
        clubs,
        X,
        use_multi_start_seed=ENABLE_MULTI_START_SEARCH,
        out_csv=OUT_CSV_INITIAL_AUTO,
        title="Initialverteilung (Auto) vor Optimierung",
    )
    north_south_initial_labels = build_extreme_initial_labels(
        clubs, mode="north_south")
    export_solution(
        clubs,
        north_south_initial_labels,
        OUT_CSV_INITIAL_NORTH_SOUTH,
        "4 Kompass-Ligen (Initialverteilung Nord/Sued-Extrem)",
    )
    west_east_initial_labels = build_extreme_initial_labels(
        clubs, mode="west_east")
    export_solution(
        clubs,
        west_east_initial_labels,
        OUT_CSV_INITIAL_WEST_EAST,
        "4 Kompass-Ligen (Initialverteilung West/Ost-Extrem)",
    )

    initial_override_labels: Optional[np.ndarray] = None
    if INITIAL_CSV_OVERRIDE:
        initial_override_labels = load_initial_labels_from_csv(
            clubs, INITIAL_CSV_OVERRIDE)
        export_solution(
            clubs,
            initial_override_labels,
            OUT_CSV_INITIAL_MANUAL,
            f"4 Kompass-Ligen (Initialverteilung manuell geladen aus {INITIAL_CSV_OVERRIDE})",
        )
        export_solution(
            clubs,
            initial_override_labels,
            OUT_CSV_INITIAL,
            "4 Kompass-Ligen (Initialverteilung aktiv = Manuell)",
        )
    else:
        export_solution(
            clubs,
            auto_initial_labels,
            OUT_CSV_INITIAL,
            "4 Kompass-Ligen (Initialverteilung aktiv = Auto)",
        )
    if EXPORT_INITIAL_ONLY:
        print(
            f"Nur Anfangsverteilung exportiert (KOMPASS_EXPORT_INITIAL_ONLY=1): {OUT_CSV_INITIAL}"
        )
        return

    extra_initial_seeds: List[Tuple[str, np.ndarray]] = [
        ("initial_auto", auto_initial_labels),
        ("initial_north_south_extreme", north_south_initial_labels),
        ("initial_west_east_extreme", west_east_initial_labels),
        ("initial_lat_stripes", build_geographic_stripe_labels(clubs, "lat")),
        ("initial_lon_stripes", build_geographic_stripe_labels(clubs, "lon")),
        ("initial_diag_nw_se", build_geographic_stripe_labels(clubs, "diag_nw_se")),
        ("initial_diag_ne_sw", build_geographic_stripe_labels(clubs, "diag_ne_sw")),
        ("initial_random_1", build_random_balanced_labels(len(clubs), seed=7777)),
        ("initial_random_2", build_random_balanced_labels(len(clubs), seed=31415)),
        ("initial_random_3", build_random_balanced_labels(len(clubs), seed=27182)),
    ]

    if ENABLE_MULTI_START_SEARCH:
        ranked = run_multi_start_search(
            clubs,
            X,
            dist_matrix,
            seeded_labels=initial_override_labels,
            extra_initial_seeds=extra_initial_seeds,
        )
        if not ranked:
            raise RuntimeError(
                "Keine gueltige Loesung aus der Multi-Start-Suche erhalten.")
        requested_runs = MULTI_START_RUNS + len(extra_initial_seeds)
        if initial_override_labels is not None:
            requested_runs += 1
        search_config_override = {
            "mode": "heuristic_two_phase",
            "phase1_runs": MULTI_START_RUNS,
            "deterministic_seeds": [name for name, _ in extra_initial_seeds]
            + (["initial_manual"] if initial_override_labels is not None else []),
            "base_seed": MULTI_START_BASE_SEED,
            "kmeans_n_init": MULTI_START_KMEANS_N_INIT,
            "phase1_centroid_swap_iters": MULTI_START_CENTROID_SWAP_ITERS,
            "phase1_matrix_swap_iters": MULTI_START_MATRIX_SWAP_ITERS,
            "phase1_component_swap_iters": MULTI_START_COMPONENT_SWAP_ITERS,
            "phase1_shake_swap_fraction": MULTI_START_SHAKE_SWAP_FRACTION,
            "phase1_matrix_accept_equal_prob": MATRIX_ACCEPT_EQUAL_PROB,
            "phase1_matrix_anneal_start_temp_km": MATRIX_ANNEAL_START_TEMP_KM,
            "phase1_matrix_anneal_end_temp_km": MATRIX_ANNEAL_END_TEMP_KM,
            "phase1_move_2_prob": MATRIX_MOVE_2_PROB,
            "phase1_move_3_prob": MATRIX_MOVE_3_PROB,
            "phase1_move_4_prob": MATRIX_MOVE_4_PROB,
            "phase1_stagnation_shake_iters": MATRIX_STAGNATION_SHAKE_ITERS,
            "phase1_stagnation_shake_fraction": MATRIX_STAGNATION_SHAKE_FRACTION,
            "phase2_elite_count": PHASE2_ELITE_COUNT,
            "phase2_elite_selection_mode": PHASE2_ELITE_SELECTION_MODE,
            "phase2_diverse_pool_multiplier": PHASE2_DIVERSE_POOL_MULTIPLIER,
            "phase2_diverse_max_score_gap_km": PHASE2_DIVERSE_MAX_SCORE_GAP_KM,
            "phase2_restarts_per_elite": PHASE2_RESTARTS_PER_ELITE,
            "phase2_base_seed": PHASE2_BASE_SEED,
            "phase2_centroid_swap_iters": PHASE2_CENTROID_SWAP_ITERS,
            "phase2_matrix_swap_iters": PHASE2_MATRIX_SWAP_ITERS,
            "phase2_component_swap_iters": PHASE2_COMPONENT_SWAP_ITERS,
            "phase2_shake_swap_fraction": PHASE2_SHAKE_SWAP_FRACTION,
            "phase2_matrix_accept_equal_prob": PHASE2_MATRIX_ACCEPT_EQUAL_PROB,
            "phase2_matrix_anneal_start_temp_km": PHASE2_MATRIX_ANNEAL_START_TEMP_KM,
            "phase2_matrix_anneal_end_temp_km": PHASE2_MATRIX_ANNEAL_END_TEMP_KM,
            "phase2_move_2_prob": PHASE2_MATRIX_MOVE_2_PROB,
            "phase2_move_3_prob": PHASE2_MATRIX_MOVE_3_PROB,
            "phase2_move_4_prob": PHASE2_MATRIX_MOVE_4_PROB,
            "phase2_stagnation_shake_iters": PHASE2_MATRIX_STAGNATION_SHAKE_ITERS,
            "phase2_stagnation_shake_fraction": PHASE2_MATRIX_STAGNATION_SHAKE_FRACTION,
            "derby_rule_enabled": ENFORCE_DERBY_SAME_LEAGUE,
            "derby_max_distance_km": DERBY_MAX_DISTANCE_KM,
        }
        # Phase 3: LNS (Ruin & Recreate) auf der besten Loesung
        if LNS_ENABLED and ranked:
            best_entry = ranked[0]
            lns_labels = run_lns_phase(
                clubs, dist_matrix,
                best_labels=best_entry["labels_matrix"],
                iterations=LNS_ITERATIONS,
                destroy_fraction=LNS_DESTROY_FRACTION,
            )
            lns_score = _compute_intra_pair_sum(dist_matrix, lns_labels)
            old_score = best_entry["matrix_intra_km"]
            if lns_score < old_score:
                print(
                    f"[LNS] Verbesserung gefunden: {old_score:.2f} -> {lns_score:.2f} km "
                    f"({(old_score - lns_score) / old_score * 100:.2f}%)"
                )
                # LNS-Loesung als neuen Kandidaten einfuegen
                lns_entry = optimize_candidate_from_seed(
                    clubs=clubs,
                    dist_matrix=dist_matrix,
                    labels_start=lns_labels,
                    run_no=len(ranked) + 1,
                    base_seed=99999,
                    origin="lns_phase3",
                    centroid_iters=0,
                    matrix_iters=PHASE2_MATRIX_SWAP_ITERS,
                    component_iters=PHASE2_COMPONENT_SWAP_ITERS,
                    shake_fraction=0.0,
                    accept_equal_prob=PHASE2_MATRIX_ACCEPT_EQUAL_PROB,
                    anneal_start_temp_km=PHASE2_MATRIX_ANNEAL_START_TEMP_KM,
                    anneal_end_temp_km=PHASE2_MATRIX_ANNEAL_END_TEMP_KM,
                    move_2_prob=PHASE2_MATRIX_MOVE_2_PROB,
                    move_3_prob=PHASE2_MATRIX_MOVE_3_PROB,
                    move_4_prob=PHASE2_MATRIX_MOVE_4_PROB,
                    stagnation_shake_iters=PHASE2_MATRIX_STAGNATION_SHAKE_ITERS,
                    stagnation_shake_fraction=PHASE2_MATRIX_STAGNATION_SHAKE_FRACTION,
                )
                ranked.append(lns_entry)
                ranked.sort(key=lambda x: (x["matrix_avg_away_km"],
                                           x["matrix_intra_km"], x["run"]))
                for idx, entry in enumerate(ranked, start=1):
                    entry["rank"] = idx
                search_config_override["lns_iterations"] = LNS_ITERATIONS
                search_config_override["lns_destroy_fraction"] = LNS_DESTROY_FRACTION
            else:
                print(f"[LNS] Keine Verbesserung (best bleibt {old_score:.2f} km)")

        # Phase 4: CP-SAT (optional)
        if CPSAT_ENABLED and ranked:
            best_entry = ranked[0]
            print(f"\n=== Phase 4: CP-SAT Solver (time_limit={CPSAT_TIME_LIMIT}s) ===")
            cpsat_labels = solve_cpsat(
                clubs, dist_matrix,
                time_limit_s=CPSAT_TIME_LIMIT,
                warm_start=best_entry["labels_matrix"],
            )
            if cpsat_labels is not None:
                cpsat_score = _compute_intra_pair_sum(dist_matrix, cpsat_labels)
                old_score = best_entry["matrix_intra_km"]
                if cpsat_score < old_score:
                    print(
                        f"[CP-SAT] Verbesserung: {old_score:.2f} -> {cpsat_score:.2f} km "
                        f"({(old_score - cpsat_score) / old_score * 100:.2f}%)"
                    )
                    cpsat_entry = optimize_candidate_from_seed(
                        clubs=clubs,
                        dist_matrix=dist_matrix,
                        labels_start=cpsat_labels,
                        run_no=len(ranked) + 1,
                        base_seed=88888,
                        origin="cpsat_phase4",
                        centroid_iters=0,
                        matrix_iters=PHASE2_MATRIX_SWAP_ITERS,
                        component_iters=PHASE2_COMPONENT_SWAP_ITERS,
                        shake_fraction=0.0,
                        accept_equal_prob=PHASE2_MATRIX_ACCEPT_EQUAL_PROB,
                        anneal_start_temp_km=PHASE2_MATRIX_ANNEAL_START_TEMP_KM,
                        anneal_end_temp_km=PHASE2_MATRIX_ANNEAL_END_TEMP_KM,
                        move_2_prob=PHASE2_MATRIX_MOVE_2_PROB,
                        move_3_prob=PHASE2_MATRIX_MOVE_3_PROB,
                        move_4_prob=PHASE2_MATRIX_MOVE_4_PROB,
                        stagnation_shake_iters=PHASE2_MATRIX_STAGNATION_SHAKE_ITERS,
                        stagnation_shake_fraction=PHASE2_MATRIX_STAGNATION_SHAKE_FRACTION,
                    )
                    ranked.append(cpsat_entry)
                    ranked.sort(key=lambda x: (x["matrix_avg_away_km"],
                                               x["matrix_intra_km"], x["run"]))
                    for idx, entry in enumerate(ranked, start=1):
                        entry["rank"] = idx
                else:
                    print(f"[CP-SAT] Keine Verbesserung (best bleibt {old_score:.2f} km)")
                search_config_override["cpsat_time_limit_s"] = CPSAT_TIME_LIMIT

        export_ranked_matrix_outputs(
            clubs,
            ranked,
            requested_runs_override=requested_runs,
            search_config_override=search_config_override,
        )
    else:
        if initial_override_labels is not None:
            labels = initial_override_labels.copy()
        else:
            labels = auto_initial_labels.copy()
            labels = improve_by_swaps(
                clubs,
                labels,
                N_LEAGUES,
                iters=max(2000, MULTI_START_CENTROID_SWAP_ITERS),
                seed=MULTI_START_BASE_SEED + 7,
            )

        if ENFORCE_DERBY_SAME_LEAGUE:
            components = build_derby_components(
                dist_matrix, DERBY_MAX_DISTANCE_KM)
            if any(len(c) > TEAMS_PER_LEAGUE for c in components):
                raise RuntimeError(
                    "Derby-Regel unloesbar: mindestens eine Derby-Komponente ist groesser als Liga-Kapazitaet."
                )
            initial_matrix_labels = assign_components_initial(
                clubs=clubs,
                components=components,
                centroids=compute_centroids(clubs, labels, N_LEAGUES),
                k=N_LEAGUES,
                cap=TEAMS_PER_LEAGUE,
            )
            labels_matrix = improve_component_swaps_distance_matrix(
                labels=initial_matrix_labels,
                components=components,
                dist_matrix=dist_matrix,
                iters=30000,
                seed=11,
                cap=TEAMS_PER_LEAGUE,
            )
        else:
            labels_matrix = improve_by_swaps_distance_matrix(
                labels=labels,
                dist_matrix=dist_matrix,
                k=N_LEAGUES,
                iters=max(6000, MULTI_START_MATRIX_SWAP_ITERS),
                seed=MULTI_START_BASE_SEED + 11,
                accept_equal_prob=MATRIX_ACCEPT_EQUAL_PROB,
                anneal_start_temp_km=MATRIX_ANNEAL_START_TEMP_KM,
                anneal_end_temp_km=MATRIX_ANNEAL_END_TEMP_KM,
                move_2_prob=MATRIX_MOVE_2_PROB,
                move_3_prob=MATRIX_MOVE_3_PROB,
                move_4_prob=MATRIX_MOVE_4_PROB,
                stagnation_shake_iters=MATRIX_STAGNATION_SHAKE_ITERS,
                stagnation_shake_fraction=MATRIX_STAGNATION_SHAKE_FRACTION,
            )
        export_single_run_matrix_outputs(
            clubs, labels, labels_matrix, dist_matrix)


if __name__ == "__main__":
    main()
