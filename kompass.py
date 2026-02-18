"""
Kompass-Regionalliga-Reform (4 Ligen Ã  20 Teams), ohne U23/II-Teams.

Was das Script macht:
1) EnthÃ¤lt ALLE Teilnehmer der 5 Regionalligen 2025/26 direkt im Code (Wikipedia-Saisonartikel).
2) Entfernt automatisch U23/II-Teams (z.B. "II", "U23").
3) Weil danach i. d. R. < 80 Teams Ã¼brig bleiben, kann es automatisch mit Top-Teams aus
   Oberliga-Seiten (5. Liga) auf Wikipedia auffÃ¼llen, bis exakt 80 Teams erreicht sind.
4) Holt Koordinaten primÃ¤r Ã¼ber die Wikipedia-API (prop=coordinates). Falls ein Verein keine Koordinaten hat:
   optionaler Fallback per OpenStreetMap/Nominatim (geopy) â€“ deaktivierbar.
5) Clustert in 4 geografische Gruppen, erzwingt exakt 20 Teams je Liga, optimiert per lokalen Swaps.
6) Gibt die 4 Ligen (Nord/SÃ¼d/West/Ost) + Metriken aus und schreibt CSV.

Installation (empfohlen):
  pip install requests pandas numpy scikit-learn lxml
Optional (Fallback-Geocoding):
  pip install geopy

Hinweis:
- Wikipedia-Koordinaten sind meist Stadion-/Ortskoordinaten und fÃ¼r Distanzoptimierung ausreichend.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass
from io import StringIO
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from sklearn.cluster import KMeans


# -------------------------
# Konfiguration
# -------------------------
N_LEAGUES = 4
TEAMS_PER_LEAGUE = 20
TARGET_TEAM_COUNT = N_LEAGUES * TEAMS_PER_LEAGUE
ENABLE_DISTANCE_MATRIX_VARIANT = True
ENFORCE_DERBY_SAME_LEAGUE = False
DERBY_MAX_DISTANCE_KM = 50.0

EXCLUDE_U23_TEAMS = True
USE_RULE_BASED_SEASON_LOGIC = True
USE_REFORM_12_4_14_RULE = True

# Wenn nach Ausschluss der U23/II-Teams weniger als 80 Teams Ã¼brig sind:
FILL_UP_WITH_TIER5_FROM_WIKIPEDIA = True
# Wenn du ausschlieÃŸlich mit Regionalliga-Teams arbeiten willst, setze:
# FILL_UP_WITH_TIER5_FROM_WIKIPEDIA = False
#
# Wenn dann <80 Teams Ã¼brig sind, bricht das Script mit Fehlermeldung ab.

# Koordinaten: primÃ¤r Wikipedia, optional Fallback Nominatim
# auf False setzen, wenn du nur Wikipedia-Koordinaten willst
USE_NOMINATIM_FALLBACK = True
NOMINATIM_MIN_SECONDS = 1.1     # Rate limit (freundlich bleiben)

# Wikipedia-Seitentitel, falls Vereinsname nicht exakt passt
WIKI_TITLE_OVERRIDES = {
    # FuÃŸball-Seite (nicht die Turn-Seite)
    "TSG Balingen": "TSG Balingen",
    "SV Atlas Delmenhorst": "SV Atlas Delmenhorst (2012)",
}

# Wenn Nominatim bei manchen Vereinen zickt: explizite Orts-Queries
GEOCODE_QUERY_OVERRIDES = {
    "SG Barockstadt Fulda-Lehnerz": "Fulda, Germany",
    "TSV Steinbach Haiger": "Haiger, Germany",
    "SGV Freiberg": "Freiberg am Neckar, Germany",
    "SSVg Velbert": "Velbert, Germany",
    "FSV SchÃ¶ningen": "SchÃ¶ningen, Germany",
    "1. FC PhÃ¶nix LÃ¼beck": "LÃ¼beck, Germany",
    "SC Fortuna KÃ¶ln": "KÃ¶ln, Germany",
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
    "SC Fortuna KÃ¶ln": (50.92245, 6.97423),
    "SG Barockstadt Fulda Lehnerz": (50.555809, 9.680845),
    "SG Barockstadt Fulda-Lehnerz": (50.555809, 9.680845),
}


CACHE_FILE = "club_coords_cache.json"
ADDED_TEAMS_LOG_FILE = "added_teams.log"
SEASON_TRANSITIONS_FILE = "season_transitions.json"
OUT_CSV_DEFAULT = "kompass_regionalliga_4x20.csv"
OUT_CSV_MATRIX = "kompass_regionalliga_4x20_matrix.csv"
OUT_CSV_CENTROID = "kompass_regionalliga_4x20_centroid.csv"
WIKIPEDIA_API = "https://de.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "CompassRegionalligaBot/1.0 (your_email_or_github_here)"


# -------------------------
# Daten: Regionalligen 2025/26 (aus den Wikipedia-Saisonartikeln)
# -------------------------
REGIONALLIGA_2025_26: Dict[str, List[str]] = {
    "Nord": [
        "Hannover 96 II",
        "Kickers Emden",
        "SV Drochtersen/Assel",
        "Werder Bremen II",
        "1. FC PhÃ¶nix LÃ¼beck",
        "SV Meppen",
        "VfB LÃ¼beck",
        "Hamburger SV II",
        "Blau-WeiÃŸ Lohne",
        "FC St. Pauli II",
        "VfB Oldenburg",
        "Eintracht Norderstedt",
        "SC Weiche Flensburg 08",
        "SSV Jeddeloh",
        "Bremer SV",
        "HSC Hannover",
        "FSV SchÃ¶ningen",
        "Altona 93",
    ],
    "Nordost": [
        "1. FC Lokomotive Leipzig",
        "Hallescher FC",
        "FC Rot-WeiÃŸ Erfurt",
        "FSV Zwickau",
        "FC Carl Zeiss Jena",
        "Greifswalder FC",
        "Chemnitzer FC",
        "BFC Dynamo",
        "VSG Altglienicke",
        "Hertha BSC II",
        "ZFC Meuselwitz",
        "Hertha 03 Zehlendorf",
        "SV Babelsberg 03",
        "BSG Chemie Leipzig",
        "FSV 63 Luckenwalde",
        "FC Eilenburg",
        "BFC Preussen",
        "1. FC Magdeburg II",
    ],
    "West": [
        "Borussia Dortmund II",
        "FC GÃ¼tersloh",
        "Sportfreunde Lotte",
        "Rot-WeiÃŸ Oberhausen",
        "SV RÃ¶dinghausen",
        "SC Fortuna KÃ¶ln",
        "Borussia MÃ¶nchengladbach II",
        "1. FC KÃ¶ln II",
        "SC Paderborn 07 II",
        "1. FC Bocholt",
        "Fortuna DÃ¼sseldorf II",
        "SC WiedenbrÃ¼ck",
        "Wuppertaler SV",
        "FC Schalke 04 II",
        "Bonner SC",
        "SSVg Velbert",
        "Sportfreunde Siegen",
        "VfL Bochum II",
    ],
    "Bayern": [
        "SpVgg Unterhaching",
        "TSV Buchbach",
        "SpVgg Greuther FÃ¼rth II",
        "FC Bayern MÃ¼nchen II",
        "SpVgg Bayreuth",
        "WÃ¼rzburger Kickers",
        "Wacker Burghausen",
        "DJK Vilzing",
        "FV Illertissen",
        "SpVgg Ansbach 09",
        "1. FC NÃ¼rnberg II",
        "FC Augsburg II",
        "TSV Aubstadt",
        "TSV Schwaben Augsburg",
        "Viktoria Aschaffenburg",
        "SpVgg Hankofen-Hailing",
        "VfB EichstÃ¤tt",
        "FC Memmingen",
    ],
    "SÃ¼dwest": [
        "SV Sandhausen",
        "Kickers Offenbach",
        "SGV Freiberg",
        "TSV Steinbach Haiger",
        "Stuttgarter Kickers",
        "FSV Frankfurt",
        "SC Freiburg II",
        "FC 08 Homburg",
        "KSV Hessen Kassel",
        "SG Barockstadt Fulda-Lehnerz",
        "FC-Astoria Walldorf",
        "1. FSV Mainz 05 II",
        "SV Eintracht Trier",
        "Bahlinger SC",
        "SG Sonnenhof GroÃŸaspach",
        "FC Bayern Alzenau",
        "TSV Schott Mainz",
        "TSG Balingen",
    ],
}

# Oberliga-/5.-Liga-Seiten (Wikipedia), um nach Ausschluss von U23/II-Teams auf 80 Teams aufzufÃ¼llen
# (Es werden Tabellen gelesen und in Tabellenreihenfolge â€žoben nach untenâ€œ Kandidaten entnommen.)
TIER5_WIKI_URLS: List[str] = [
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Niedersachsen_2025/26",
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Schleswig-Holstein_2025/26",
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Hamburg_2025/26",
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Bremen-Liga_2025/26",
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Westfalen_2025/26",
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Niederrhein_2025/26",
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Mittelrheinliga_2025/26",
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Nordost_2025/26",
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Baden-W%C3%BCrttemberg_2025/26",
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Hessenliga_2025/26",
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Rheinland-Pfalz/Saar_2025/26",
    "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Bayernliga_2025/26",
]

TABLE_SOURCE_PRIORITY: List[str] = ["fupa", "wikipedia"]

REGIONALLIGA_TABLE_URLS: Dict[str, Dict[str, str]] = {
    "Nord": {
        "fupa": "https://www.fupa.net/league/regionalliga-nord/standing",
        "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Regionalliga_Nord_2025/26",
    },
    "Nordost": {
        "fupa": "https://www.fupa.net/league/regionalliga-nordost/standing",
        "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Regionalliga_Nordost_2025/26",
    },
    "West": {
        "fupa": "https://www.fupa.net/league/regionalliga-west/standing",
        "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Regionalliga_West_2025/26",
    },
    "Bayern": {
        "fupa": "https://www.fupa.net/league/regionalliga-bayern/standing",
        "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Regionalliga_Bayern_2025/26",
    },
    "Südwest": {
        "fupa": "https://www.fupa.net/league/regionalliga-suedwest/standing",
        "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Regionalliga_S%C3%BCdwest_2025/26",
    },
}

THIRD_LIGA_TABLE_URLS: Dict[str, str] = {
    "fupa": "https://www.fupa.net/league/3-liga/standing",
    "wikipedia": "https://de.wikipedia.org/wiki/3._Fu%C3%9Fball-Liga_2025/26",
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
    {"name": "Niedersachsen", "sources": {"fupa": "https://www.fupa.net/league/oberliga-niedersachsen/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Niedersachsen_2025/26"}},
    {"name": "Schleswig-Holstein", "sources": {"fupa": "https://www.fupa.net/league/oberliga-schleswig-holstein/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Schleswig-Holstein_2025/26"}},
    {"name": "Hamburg", "sources": {"fupa": "https://www.fupa.net/league/oberliga-hamburg/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Hamburg_2025/26"}},
    {"name": "Bremen", "sources": {"fupa": "https://www.fupa.net/league/bremen-liga/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Bremen-Liga_2025/26"}},
    {"name": "Westfalen", "sources": {"fupa": "https://www.fupa.net/league/oberliga-westfalen/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Westfalen_2025/26"}},
    {"name": "Niederrhein", "sources": {"fupa": "https://www.fupa.net/league/oberliga-niederrhein/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Niederrhein_2025/26"}},
    {"name": "Mittelrhein", "sources": {"fupa": "https://www.fupa.net/league/mittelrheinliga/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Mittelrheinliga_2025/26"}},
    {"name": "NOFV Nord", "sources": {"wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Nordost_2025/26"}, "wikipedia_table_pick": 0},
    {"name": "NOFV Süd", "sources": {"wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Nordost_2025/26"}, "wikipedia_table_pick": 1},
    {"name": "Baden-Württemberg", "sources": {"fupa": "https://www.fupa.net/league/oberliga-baden-wuerttemberg/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Baden-W%C3%BCrttemberg_2025/26"}},
    {"name": "Hessen", "sources": {"fupa": "https://www.fupa.net/league/hessenliga/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Hessenliga_2025/26"}},
    {"name": "Rheinland-Pfalz/Saar", "sources": {"fupa": "https://www.fupa.net/league/oberliga-rheinland-pfalz-saar/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Oberliga_Rheinland-Pfalz/Saar_2025/26"}},
    {"name": "Bayernliga Nord", "sources": {"fupa": "https://www.fupa.net/league/bayernliga-nord/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Bayernliga_2025/26"}, "wikipedia_table_pick": 0},
    {"name": "Bayernliga Süd", "sources": {"fupa": "https://www.fupa.net/league/bayernliga-sued/standing", "wikipedia": "https://de.wikipedia.org/wiki/Fu%C3%9Fball-Bayernliga_2025/26"}, "wikipedia_table_pick": 1},
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


def normalize_text(text: str) -> str:
    s = str(text).strip()
    s = s.replace("\xa0", " ")
    # Repariert haeufige UTF-8/Latin1-Mojibake wie "MÃ¶nchengladbach" -> "Mönchengladbach".
    if any(x in s for x in ("Ã", "Â", "â", "€", "™", "Ÿ")):
        for enc in ("cp1252", "latin1"):
            try:
                repaired = s.encode(enc).decode("utf-8")
                if repaired:
                    s = repaired
                    break
            except Exception:
                continue
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


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
    Entfernt typische Wikipedia-Tabellen-Anmerkungen wie (A), (N), (M), FuÃŸnoten etc.
    """
    s = normalize_text(name)
    # entferne KlammerzusÃ¤tze am Ende: "(A)", "(N)" usw.
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
    # entferne Hochstellungen/Footnote-Ã¤hnliche Marker
    s = re.sub(r"\[[0-9]+\]", "", s).strip()
    # entferne Tabellenstatus-Suffixe wie "L" am Ende
    s = re.sub(r"\s+[A-ZÄÖÜ]$", "", s).strip()
    # Mehrfachspaces
    s = normalize_text(s)
    s = get_override(TEAM_NAME_NORMALIZATION_OVERRIDES, s) or s
    return s


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two points.
    """
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1) * \
        math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Club:
    name: str
    lat: float
    lon: float


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
    Optionaler Geocoder-Fallback. BenÃ¶tigt geopy.
    Nutzt GEOCODE_QUERY_OVERRIDES fÃ¼r schwierige FÃ¤lle.
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
            cache[name] = (float(override_coords[0]), float(override_coords[1]))
            save_cache(CACHE_FILE, cache)
            clubs.append(Club(name=name, lat=float(override_coords[0]), lon=float(override_coords[1])))
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
            resolved_title, title_source = resolve_wikipedia_title(session, name)
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
    Gibt die Teams in Tabellenreihenfolge zurÃ¼ck.
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

        # In vielen Wikipedia-Artikeln ist die erste passende Tabelle die gewÃ¼nschte "Tabelle".
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
            points = _to_int_or_none(row.get(points_col)) if points_col else None
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

    m = re.search(r"window\.REDUX_DATA\s*=\s*(\{.*?\})\s*</script>", html, re.DOTALL)
    if not m:
        return []

    data = json.loads(m.group(1))
    standings: List[Dict] = []
    for item in data.get("dataHistory", []):
        ls = item.get("LeagueStandingPage", {})
        st = ((ls.get("total", {}) or {}).get("data", {}) or {}).get("standings", [])
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
            rows = extract_standings_rows(url, source=src, table_pick=table_pick)
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
    marked_up = [c for c in candidates if str(c.get("mark", "")).startswith("up")]
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
        round_pool = [c for c in candidates if c.get("rank") == place and c["team"] not in used]
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
            raise RuntimeError(f"Zu wenig Vertreter in {league_name}: {len(picked)} (erwartet 12)")
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
            raise RuntimeError(f"Zusatzplatz fuer {league_name} nicht vollstaendig.")
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
    lines.append(f"- RL-Vertreter (5x12): {sum(len(v) for v in rl_representatives.values())}")
    lines.append(f"- RL-Aufsteiger (Platz 1 je Staffel): {sorted(promoted_to_3liga)}")
    lines.append(f"- RL-Absteiger (ab Platz 14): {len(relegated_from_regionalliga)}")
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
        raise RuntimeError(f"Reform-Teamlogik ergibt {len(deduped)} Teams statt {target}.")
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
        _pick_rl_champions_for_promotion(rl_rows_by_league, RL_PROMOTION_SLOTS_TO_3LIGA)
    )
    relegated_from_rl = _pick_relegations_per_staffel(
        rl_rows_by_league, RL_RELEGATION_SLOTS_PER_STAFFEL, promoted_to_3
    )

    pool = set(current_rl_set)
    pool -= promoted_to_3
    pool -= relegated_from_rl

    third_rows, third_src, third_src_info = extract_standings_rows_with_fallback(THIRD_LIGA_TABLE_URLS)
    from_3liga = set(_pick_3liga_relegated(third_rows, THIRD_LIGA_RELEGATION_SLOTS))
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
            f.write("\n".join([f"{t} | {u}" for t, u in added_with_source]) + "\n")

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
    FÃ¼llt base bis target auf, mit Kandidaten aus Oberliga-Seiten (Wikipedia Tabellen).
    """
    if len(base) >= target:
        return base[:target]

    if not FILL_UP_WITH_TIER5_FROM_WIKIPEDIA:
        raise RuntimeError(
            f"Nach Filterung sind nur {len(base)} Teams vorhanden, benÃ¶tigt werden {target}. "
            f"Aktiviere FILL_UP_WITH_TIER5_FROM_WIKIPEDIA oder passe Parameter an."
        )

    have = set(base)
    added: List[str] = []
    added_with_source: List[Tuple[str, str]] = []

    for url in TIER5_WIKI_URLS:
        if len(base) + len(added) >= target:
            break
        try:
            cand = extract_table_teams_from_wikipedia(url)
        except Exception:
            continue

        for t in cand:
            t = clean_team_name(t)
            if not t or t in have:
                continue
            if EXCLUDE_U23_TEAMS and is_u23_or_reserve(t):
                continue
            have.add(t)
            added.append(t)
            added_with_source.append((t, url))
            if len(base) + len(added) >= target:
                break

    out = base + added
    if len(out) < target:
        raise RuntimeError(
            f"Konnte nur auf {len(out)} Teams auffÃ¼llen (Ziel: {target}). "
            "FÃ¼ge weitere TIER5_WIKI_URLS hinzu oder lockere Filter."
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
# Clustering + KapazitÃ¤ten erzwingen
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

        # WÃ¤hle einen Move aus einem Ã¼bervollen Cluster in einen untervollen Cluster
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
        "Balance der Cluster nicht konvergiert. ErhÃ¶he max_iter oder prÃ¼fe Daten.")


def improve_by_swaps(clubs: List[Club], labels: np.ndarray, k: int, iters: int = 30000, seed: int = 42) -> np.ndarray:
    """
    Lokale Verbesserung: zufÃ¤llige Swaps zwischen Clustern, wenn Objective sinkt.
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
            d = haversine_km(clubs[i].lat, clubs[i].lon, clubs[j].lat, clubs[j].lon)
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
) -> np.ndarray:
    """
    Alternative Optimierung auf Distanzmatrix-Basis:
    minimiert Summe aller Intra-Liga-Paarstrecken bei festen Teamzahlen je Liga.
    """
    rng = np.random.default_rng(seed)
    labels = labels.copy()
    n = len(labels)
    members = [set(np.where(labels == c)[0].tolist()) for c in range(k)]

    def sum_to_cluster(i: int, cluster_idx: int, exclude: Optional[int] = None) -> float:
        s = 0.0
        for x in members[cluster_idx]:
            if x == exclude:
                continue
            s += float(dist_matrix[i, x])
        return s

    for _ in range(iters):
        i, j = rng.integers(0, n, size=2)
        if i == j:
            continue
        a, b = int(labels[i]), int(labels[j])
        if a == b:
            continue

        before = sum_to_cluster(i, a, exclude=i) + sum_to_cluster(j, b, exclude=j)
        after = sum_to_cluster(i, b, exclude=j) + sum_to_cluster(j, a, exclude=i)
        if after < before:
            members[a].remove(i)
            members[b].remove(j)
            members[a].add(j)
            members[b].add(i)
            labels[i], labels[j] = labels[j], labels[i]
    return labels


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
            key=lambda c: haversine_km(lat, lon, float(centroids[c, 0]), float(centroids[c, 1])),
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
    current_obj = average_away_distance_per_club(current_labels, dist_matrix, cap)

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
    Benennt Cluster als Nord/SÃ¼d/West/Ost anhand der Centroids.
    """
    centroids = compute_centroids(clubs, labels, k)
    idxs = list(range(k))

    north = int(np.argmax(centroids[:, 0]))
    south = int(np.argmin(centroids[:, 0]))

    remaining = [i for i in idxs if i not in {north, south}]
    if len(remaining) != 2:
        # Fallback: sortiere nach lon
        order = sorted(idxs, key=lambda x: centroids[x, 1])
        return {order[0]: "West", order[1]: "SÃ¼d", order[2]: "Nord", order[3]: "Ost"}

    west = remaining[0] if centroids[remaining[0],
                                     1] < centroids[remaining[1], 1] else remaining[1]
    east = remaining[1] if west == remaining[0] else remaining[0]

    return {north: "Nord", south: "SÃ¼d", west: "West", east: "Ost"}


def league_metrics(clubs: List[Club]) -> Dict[str, float]:
    """
    Einfache Metriken: Ã˜ Paar-Distanz innerhalb der Liga und Max-Paar-Distanz.
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


# -------------------------
# Main
# -------------------------
def main() -> None:
    # 1) Teamliste bauen
    if USE_REFORM_12_4_14_RULE:
        try:
            teams = build_reform_12_4_14_team_pool(TARGET_TEAM_COUNT)
        except Exception as exc:
            print(f"Reformregel fehlgeschlagen ({type(exc).__name__}): {exc}")
            print("Fallback auf regelbasierte Saisonlogik.")
            teams = build_rule_based_team_pool(TARGET_TEAM_COUNT)
    elif USE_RULE_BASED_SEASON_LOGIC:
        try:
            teams = build_rule_based_team_pool(TARGET_TEAM_COUNT)
        except Exception as exc:
            print(f"Regelbasierte Saisonlogik fehlgeschlagen ({type(exc).__name__}): {exc}")
            print("Fallback auf statische Regionalliga-Liste + Oberliga-Auffuellen.")
            all_rl_teams = [t for league in REGIONALLIGA_2025_26.values() for t in league]
            all_rl_teams = [clean_team_name(t) for t in all_rl_teams]
            if EXCLUDE_U23_TEAMS:
                excluded = [t for t in all_rl_teams if is_u23_or_reserve(t)]
                base = [t for t in all_rl_teams if not is_u23_or_reserve(t)]
                print(
                    f"Ausgeschlossene U/Reserve-Teams: {len(excluded)} | Beispiele: {excluded[:10]}"
                )
                assert all(not is_u23_or_reserve(t) for t in base), (
                    "Filterfehler: U/Reserve-Team in der Basisliste gefunden."
                )
            else:
                base = all_rl_teams
            base = sorted(set(base))
            teams = fill_up_to_target(base, TARGET_TEAM_COUNT)
    else:
        all_rl_teams = [t for league in REGIONALLIGA_2025_26.values() for t in league]
        all_rl_teams = [clean_team_name(t) for t in all_rl_teams]

        if EXCLUDE_U23_TEAMS:
            excluded = [t for t in all_rl_teams if is_u23_or_reserve(t)]
            base = [t for t in all_rl_teams if not is_u23_or_reserve(t)]
            print(
                f"Ausgeschlossene U/Reserve-Teams: {len(excluded)} | Beispiele: {excluded[:10]}"
            )
            assert all(not is_u23_or_reserve(t) for t in base), (
                "Filterfehler: U/Reserve-Team in der Basisliste gefunden."
            )
        else:
            base = all_rl_teams
        base = sorted(set(base))
        # 2) Auf genau 80 auffÃ¼llen (falls nÃ¶tig)
        teams = fill_up_to_target(base, TARGET_TEAM_COUNT)
    if not (USE_REFORM_12_4_14_RULE and REFORM_STRICT_QUOTA_ALLOW_RESERVES):
        assert all(not is_u23_or_reserve(t) for t in teams), (
            "Filterfehler: U/Reserve-Team nach Auffuellen gefunden."
        )

    print(f"Teams gesamt (nach Filter + ggf. AuffÃ¼llen): {len(teams)}")
    if len(teams) != TARGET_TEAM_COUNT:
        raise RuntimeError(
            f"Erwartet {TARGET_TEAM_COUNT} Teams, habe {len(teams)}.")

    # 3) Koordinaten holen
    clubs = build_clubs(teams)
    X = clubs_to_array(clubs)

    # 4) Initiales Clustering (k-means auf lat/lon; fÃ¼r Deutschland hinreichend)
    km = KMeans(n_clusters=N_LEAGUES, n_init=50, random_state=42)
    labels = km.fit_predict(X)

    # 5) KapazitÃ¤t erzwingen (20 pro Liga)
    labels = balance_clusters(clubs, labels, N_LEAGUES, TEAMS_PER_LEAGUE)

    # 6) Lokale Verbesserung
    labels = improve_by_swaps(clubs, labels, N_LEAGUES, iters=40000, seed=7)
    def export_solution(solution_labels: np.ndarray, out_csv: str, title: str) -> None:
        compass = label_compass_names(clubs, solution_labels, N_LEAGUES)
        rows = []
        leagues: Dict[str, List[Club]] = {name: [] for name in ["Nord", "SÃ¼d", "West", "Ost"]}
        for c, lab in zip(clubs, solution_labels):
            lname = compass[int(lab)]
            leagues[lname].append(c)
            rows.append({"Liga": lname, "Verein": c.name, "lat": c.lat, "lon": c.lon})

        for lname, lst in leagues.items():
            if len(lst) != TEAMS_PER_LEAGUE:
                raise RuntimeError(f"Liga {lname} hat {len(lst)} Teams statt {TEAMS_PER_LEAGUE}.")
        for lname in leagues:
            leagues[lname] = sorted(leagues[lname], key=lambda c: c.name.lower())

        print(f"\n=== Ergebnis: {title} ===")
        for lname in ["Nord", "West", "Ost", "SÃ¼d"]:
            m = league_metrics(leagues[lname])
            print(
                f"\n--- {lname} (20 Teams) | Ã˜ Paar-Distanz: {m['avg_pair_km']:.1f} km | Max: {m['max_pair_km']:.1f} km ---"
            )
            for c in leagues[lname]:
                print(f"  - {c.name}")

        df = pd.DataFrame(rows).sort_values(["Liga", "Verein"])
        df.to_csv(out_csv, index=False, encoding="utf-8")
        print(f"\nCSV geschrieben: {out_csv}")

    if ENABLE_DISTANCE_MATRIX_VARIANT:
        dist_matrix = compute_distance_matrix_km(clubs)
        if ENFORCE_DERBY_SAME_LEAGUE:
            components = build_derby_components(dist_matrix, DERBY_MAX_DISTANCE_KM)
            if any(len(c) > TEAMS_PER_LEAGUE for c in components):
                raise RuntimeError(
                    "Derby-Regel unloesbar: mindestens eine Derby-Komponente ist groesser als Liga-Kapazitaet."
                )
            initial_matrix_labels = assign_components_initial(
                clubs=clubs,
                components=components,
                centroids=km.cluster_centers_,
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
            # harte Validierung Derby-Regel
            derby_pairs = sum(len(c) * (len(c) - 1) // 2 for c in components if len(c) > 1)
            print(
                f"\nDistanzmatrix-Variante mit Derby-Regel <= {DERBY_MAX_DISTANCE_KM:.0f} km: "
                f"{len(components)} Komponenten, interne Derby-Paare={derby_pairs}"
            )
        else:
            labels_matrix = improve_by_swaps_distance_matrix(
                labels=labels,
                dist_matrix=dist_matrix,
                k=N_LEAGUES,
                iters=70000,
                seed=11,
            )

        avg_base = average_away_distance_per_club(labels, dist_matrix, TEAMS_PER_LEAGUE)
        avg_alt = average_away_distance_per_club(labels_matrix, dist_matrix, TEAMS_PER_LEAGUE)
        print(
            f"Durchschnitt Auswaertsdistanz pro Verein: {avg_base:.2f} -> {avg_alt:.2f} km"
        )
        export_solution(labels_matrix, OUT_CSV_DEFAULT, "4 Kompass-Ligen (Distanzmatrix-Optimierung, Hauptausgabe)")
        export_solution(labels_matrix, OUT_CSV_MATRIX, "4 Kompass-Ligen (Distanzmatrix-Optimierung)")
        export_solution(labels, OUT_CSV_CENTROID, "4 Kompass-Ligen (Centroid-Optimierung, Vergleich)")
    else:
        export_solution(labels, OUT_CSV_DEFAULT, "4 Kompass-Ligen (Centroid-Optimierung)")


if __name__ == "__main__":
    main()

