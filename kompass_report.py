from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import pandas as pd
import requests
from lxml import html

from kompass_utils import ensure_parent_dir, haversine_km, normalize_text

try:
    import folium
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "folium is required for map output. Install with: pip install folium"
    ) from exc


OUTPUT_DIR = Path("outputs")
OUTPUT_CSV_DIR = OUTPUT_DIR / "csv"
OUTPUT_HTML_DIR = OUTPUT_DIR / "html"
OUTPUT_JSON_DIR = OUTPUT_DIR / "json"
PAGES_DOCS_DIR = Path("docs")
INPUT_CSV = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20.csv")
INPUT_CSV_INITIAL = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20_initial.csv")
INPUT_CSV_INITIAL_AUTO = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20_initial_auto.csv")
INPUT_CSV_INITIAL_MANUAL = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20_initial_manual.csv")
INPUT_CSV_RANK2 = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20_matrix_rank2.csv")
INPUT_CSV_RANK3 = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20_matrix_rank3.csv")
INPUT_CSV_RANK5 = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20_matrix_rank5.csv")
INPUT_CSV_RANK10 = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20_matrix_rank10.csv")
INPUT_CSV_WORST = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20_matrix_worst.csv")
MAP_HTML = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map.html")
MAP_HTML_INITIAL = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_initial.html")
MAP_HTML_INITIAL_AUTO = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_initial_auto.html")
MAP_HTML_INITIAL_MANUAL = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_initial_manual.html")
MAP_HTML_RANK2 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_rank2.html")
MAP_HTML_RANK3 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_rank3.html")
MAP_HTML_RANK5 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_rank5.html")
MAP_HTML_RANK10 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_rank10.html")
MAP_HTML_WORST = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_worst.html")
MAP_COMPARE_HTML_RANK2 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_rank2.html")
MAP_COMPARE_HTML_INITIAL = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_initial.html")
MAP_COMPARE_HTML_INITIAL_AUTO_MANUAL = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_initial_auto_manual.html")
MAP_COMPARE_HTML_RANK3 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_rank3.html")
MAP_COMPARE_HTML_RANK5 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_rank5.html")
MAP_COMPARE_HTML_RANK10 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_rank10.html")
MAP_COMPARE_HTML_WORST = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_worst.html")
INDEX_HTML = str(OUTPUT_HTML_DIR / "index.html")
CLUB_METRICS_CSV = str(OUTPUT_CSV_DIR / "kompass_away_metrics_per_club.csv")
LEAGUE_METRICS_CSV = str(OUTPUT_CSV_DIR / "kompass_away_metrics_per_league.csv")
LONGEST_TRIPS_CSV = str(OUTPUT_CSV_DIR / "kompass_longest_trips.csv")
MAP_COORDS_CSV = str(OUTPUT_CSV_DIR / "kompass_map_coordinates.csv")
STADIUM_MISSING_CSV = str(OUTPUT_CSV_DIR / "kompass_stadium_missing.csv")
STADIUM_SNAPSHOT_JSON = str(OUTPUT_JSON_DIR / "stadium_coords_snapshot.json")
SOLUTIONS_RANKED_JSON = str(OUTPUT_JSON_DIR / "kompass_solutions_ranked.json")
TRANSITIONS_JSON = "season_transitions.json"
CACHE_FILE = "club_coords_cache.json"
STADIUM_CACHE_FILE = "stadium_coords_cache.json"
STADIUM_OVERRIDES_FILE = "stadium_overrides.json"
USE_STADIUM_COORDS_FOR_MAP = True
USE_EUROPLAN_STADIUM_SOURCE = False
DISPLAY_MATRIX_RANKS = [1]

EUROPLAN_LEAGUE_IDS = {
    "Regionalliga Nord": 2900,
    "Regionalliga Nordost": 654,
    "Regionalliga West": 23,
    "Regionalliga Bayern": 640,
    "Regionalliga Suedwest": 24,
}
EUROPLAN_BASE = "https://www.europlan-online.de/"


def html_asset_name(path: str) -> str:
    return Path(path).name


def sync_pages_docs(source_dir: Path, docs_dir: Path) -> int:
    docs_dir.mkdir(parents=True, exist_ok=True)
    source_files = sorted(source_dir.glob("*.html"))
    source_names = {p.name for p in source_files}

    for docs_html in docs_dir.glob("*.html"):
        if docs_html.name not in source_names:
            docs_html.unlink()

    for src in source_files:
        shutil.copy2(src, docs_dir / src.name)

    (docs_dir / ".nojekyll").write_text("", encoding="utf-8")
    return len(source_files)



def load_transitions(path: str) -> Dict:
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    out: Dict = {}
    for k in (
        "promoted_to_3liga",
        "relegated_from_regionalliga",
        "relegated_from_3liga",
        "promoted_from_oberliga",
    ):
        out[k] = [normalize_text(x) for x in raw.get(k, [])]
    pmap = raw.get("promoted_to_3liga_league", {})
    if isinstance(pmap, dict):
        out["promoted_to_3liga_league"] = {
            normalize_text(k): normalize_text(v) for k, v in pmap.items()
        }
    return out


def load_cache_coords(path: str) -> Dict[str, Tuple[float, float]]:
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    out: Dict[str, Tuple[float, float]] = {}
    for k, v in raw.items():
        if isinstance(v, list) and len(v) == 2:
            out[normalize_text(k)] = (float(v[0]), float(v[1]))
    return out


def load_stadium_cache(path: str) -> Dict[str, Dict]:
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    out: Dict[str, Dict] = {}
    for k, v in raw.items():
        if isinstance(v, dict) and "lat" in v and "lon" in v:
            out[normalize_text(k)] = {
                "lat": float(v["lat"]),
                "lon": float(v["lon"]),
                "stadium": normalize_text(v.get("stadium", "")),
                "address": normalize_text(v.get("address", "")),
                "source": normalize_text(v.get("source", "")),
                "source_url": normalize_text(v.get("source_url", "")),
                "updated_at": normalize_text(v.get("updated_at", "")),
            }
    return out


def save_stadium_cache(path: str, cache: Dict[str, Dict]) -> None:
    payload: Dict[str, Dict] = {}
    for k, v in cache.items():
        payload[k] = {
            "lat": float(v["lat"]),
            "lon": float(v["lon"]),
            "stadium": v.get("stadium", ""),
            "address": v.get("address", ""),
            "source": v.get("source", ""),
            "source_url": v.get("source_url", ""),
            "updated_at": v.get("updated_at", ""),
        }
    ensure_parent_dir(path)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_stadium_overrides(path: str) -> Dict[str, Dict]:
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8-sig"))
    out: Dict[str, Dict] = {}
    for k, v in raw.items():
        if isinstance(v, dict) and "lat" in v and "lon" in v:
            out[normalize_text(k)] = {
                "lat": float(v["lat"]),
                "lon": float(v["lon"]),
                "stadium": normalize_text(v.get("stadium", "")),
                "address": normalize_text(v.get("address", "")),
                "source": "override",
                "source_url": normalize_text(v.get("source_url", "")),
                "updated_at": normalize_text(v.get("updated_at", "")),
            }
    return out


def _extract_q_coords(href: str) -> Optional[Tuple[float, float]]:
    m = re.search(r"[?&]q=\(?\s*([0-9.+-]+)\s*,\s*([0-9.+-]+)\s*\)?", href)
    if not m:
        return None
    try:
        return float(m.group(1)), float(m.group(2))
    except Exception:
        return None


def _extract_address_from_stadium_html(raw_html: str) -> str:
    m = re.search(
        r"Anschrift\s*</h3>\s*([^<]+?)\s*<br\s*/?>\s*([^<]+?)\s*<br\s*/?>\s*([^<]+?)\s*<br",
        raw_html,
        flags=re.IGNORECASE,
    )
    if m:
        parts = [normalize_text(x) for x in m.groups() if normalize_text(x)]
        return ", ".join(parts[:3]).strip(", ")
    return ""


def fetch_europlan_stadium_index(session: requests.Session) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for _, league_id in EUROPLAN_LEAGUE_IDS.items():
        url = f"{EUROPLAN_BASE}index.php?s=liga&id={league_id}"
        r = session.get(url, timeout=25)
        r.raise_for_status()
        doc = html.fromstring(r.text)
        rows = doc.xpath("//tr[.//a[contains(@href,'stadion-')]]")
        for row in rows:
            team = normalize_text(" ".join(row.xpath("./td[2]//span[1]//text()")))
            if not team:
                continue
            stadium = normalize_text(" ".join(row.xpath(".//a[contains(@href,'stadion-')][1]//text()")))
            rel_links = row.xpath(".//a[contains(@href,'stadion-')][1]/@href")
            if not rel_links:
                continue
            stadium_url = urljoin(EUROPLAN_BASE, rel_links[0])
            try:
                sr = session.get(stadium_url, timeout=25)
                sr.raise_for_status()
            except Exception:
                continue
            sdoc = html.fromstring(sr.text)
            map_links = sdoc.xpath(
                "//a[contains(@href,'maps.google') or contains(@href,'google.de/maps')]/@href"
            )
            coords = _extract_q_coords(map_links[0]) if map_links else None
            if not coords:
                continue
            out[team] = {
                "lat": coords[0],
                "lon": coords[1],
                "stadium": stadium,
                "address": _extract_address_from_stadium_html(sr.text),
                "source": "europlan",
                "source_url": stadium_url,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
    return out


def _wikidata_get_entity(session: requests.Session, qid: str) -> Dict:
    params = {
        "action": "wbgetentities",
        "format": "json",
        "ids": qid,
        "props": "claims|labels",
    }
    r = session.get("https://www.wikidata.org/w/api.php", params=params, timeout=25)
    r.raise_for_status()
    return r.json().get("entities", {}).get(qid, {})


def _wikidata_entity_label(entity: Dict) -> str:
    labels = entity.get("labels", {})
    for lang in ("de", "en"):
        val = labels.get(lang, {}).get("value")
        if val:
            return normalize_text(val)
    return ""


def _wiki_get_page_wikitext(session: requests.Session, title: str) -> Optional[str]:
    params = {
        "action": "query",
        "format": "json",
        "prop": "revisions",
        "titles": title,
        "redirects": "1",
        "rvprop": "content",
        "rvslots": "main",
    }
    r = session.get("https://de.wikipedia.org/w/api.php", params=params, timeout=25)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    revs = page.get("revisions", [])
    if not revs:
        return None
    return revs[0].get("slots", {}).get("main", {}).get("*")


def _extract_wikilink_target(value: str) -> Optional[str]:
    m = re.search(r"\[\[([^\]|#]+)", value)
    if m:
        return normalize_text(m.group(1))
    return None


def _extract_stadium_name_from_wikitext(wikitext: str) -> Optional[str]:
    keys = [
        "stadion",
        "spielstätte",
        "spielstaette",
        "heimspielstätte",
        "heimspielstaette",
        "ground",
    ]
    for key in keys:
        m = re.search(rf"^\|\s*{key}\s*=\s*(.+)$", wikitext, flags=re.IGNORECASE | re.MULTILINE)
        if not m:
            continue
        raw = m.group(1).strip()
        raw = re.split(r"<ref|<!--|<br\s*/?>", raw, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        linked = _extract_wikilink_target(raw)
        if linked:
            return linked
        clean = re.sub(r"\{\{[^{}]*\}\}", "", raw).strip()
        clean = re.sub(r"\[[^\]]+\]", "", clean).strip()
        clean = re.sub(r"\s+", " ", clean).strip()
        if clean:
            return normalize_text(clean)
    return None


def resolve_stadium_from_wikipedia_infobox(session: requests.Session, team: str) -> Optional[Dict]:
    try:
        import kompass
    except Exception:
        return None

    try:
        club_title, _ = kompass.resolve_wikipedia_title(session, team)
        wikitext = _wiki_get_page_wikitext(session, club_title)
    except Exception:
        return None
    if not wikitext:
        return None

    stadium_hint = _extract_stadium_name_from_wikitext(wikitext)
    if not stadium_hint:
        return None

    try:
        stadium_title, _ = kompass.resolve_wikipedia_title(session, stadium_hint)
        coords, stage = kompass.wiki_get_coords_with_stage(session, stadium_title)
    except Exception:
        return None
    if not coords:
        return None

    return {
        "lat": float(coords[0]),
        "lon": float(coords[1]),
        "stadium": normalize_text(stadium_title),
        "address": "",
        "source": f"wikipedia.infobox.{club_title}->{stadium_title}.{stage}",
        "source_url": f"https://de.wikipedia.org/wiki/{stadium_title.replace(' ', '_')}",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _wiki_get_page_links(session: requests.Session, title: str) -> List[str]:
    params = {
        "action": "parse",
        "format": "json",
        "page": title,
        "prop": "links",
        "redirects": "1",
    }
    r = session.get("https://de.wikipedia.org/w/api.php", params=params, timeout=25)
    r.raise_for_status()
    links = r.json().get("parse", {}).get("links", [])
    out: List[str] = []
    for lk in links:
        name = normalize_text(lk.get("*", ""))
        if name:
            out.append(name)
    return out


def resolve_stadium_from_wikipedia_links(session: requests.Session, team: str) -> Optional[Dict]:
    try:
        import kompass
    except Exception:
        return None

    try:
        club_title, _ = kompass.resolve_wikipedia_title(session, team)
        links = _wiki_get_page_links(session, club_title)
    except Exception:
        return None

    patterns = (r"\bstadion\b", r"\barena\b", r"\bsportpark\b", r"\bkampfbahn\b")
    candidates = [
        l for l in links if any(re.search(p, l, flags=re.IGNORECASE) for p in patterns)
    ]
    for cand in candidates[:20]:
        try:
            stadium_title, _ = kompass.resolve_wikipedia_title(session, cand)
            coords, stage = kompass.wiki_get_coords_with_stage(session, stadium_title)
        except Exception:
            continue
        if not coords:
            continue
        return {
            "lat": float(coords[0]),
            "lon": float(coords[1]),
            "stadium": normalize_text(stadium_title),
            "address": "",
            "source": f"wikipedia.links.{club_title}->{stadium_title}.{stage}",
            "source_url": f"https://de.wikipedia.org/wiki/{stadium_title.replace(' ', '_')}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    return None


def resolve_stadium_from_wikidata(session: requests.Session, team: str) -> Optional[Dict]:
    try:
        import kompass
    except Exception:
        return None

    try:
        title, _ = kompass.resolve_wikipedia_title(session, team)
        qid = kompass._wiki_get_wikidata_qid(session, title)
    except Exception:
        return None
    if not qid:
        return None

    try:
        club_entity = _wikidata_get_entity(session, qid)
    except Exception:
        return None
    claims = club_entity.get("claims", {})
    venue_qids = kompass._extract_entity_ids(claims, "P115")
    for venue_qid in venue_qids:
        try:
            venue_entity = _wikidata_get_entity(session, venue_qid)
        except Exception:
            continue
        v_claims = venue_entity.get("claims", {})
        coords = kompass._extract_p625_from_claims(v_claims)
        if not coords:
            continue
        if not kompass.is_plausible_germany_coord(coords[0], coords[1]):
            continue
        return {
            "lat": float(coords[0]),
            "lon": float(coords[1]),
            "stadium": _wikidata_entity_label(venue_entity),
            "address": "",
            "source": f"wikidata.P115.{qid}->{venue_qid}.P625",
            "source_url": f"https://www.wikidata.org/wiki/{venue_qid}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    return None


def resolve_map_coordinates(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, int]]:
    if not USE_STADIUM_COORDS_FOR_MAP:
        return df.copy(), {"total": len(df), "stadium": 0, "fallback_club": len(df)}

    cache = load_stadium_cache(STADIUM_CACHE_FILE)
    overrides = load_stadium_overrides(STADIUM_OVERRIDES_FILE)
    session = requests.Session()
    session.headers.update({"User-Agent": "KompassRegionalliga/1.0"})

    europlan_index: Dict[str, Dict] = {}
    if USE_EUROPLAN_STADIUM_SOURCE:
        try:
            europlan_index = fetch_europlan_stadium_index(session)
        except Exception:
            europlan_index = {}

    stadium_hits = 0
    rows: List[Dict] = []
    for _, row in df.iterrows():
        team = normalize_text(row["Verein"])
        coord = None
        if team in overrides:
            coord = overrides[team]
        elif team in cache:
            coord = cache[team]
        else:
            wiki = resolve_stadium_from_wikipedia_infobox(session, team)
            if wiki:
                coord = wiki
                cache[team] = wiki
            else:
                wiki_links = resolve_stadium_from_wikipedia_links(session, team)
                if wiki_links:
                    coord = wiki_links
                    cache[team] = wiki_links
                else:
                    wd = resolve_stadium_from_wikidata(session, team)
                    if wd:
                        coord = wd
                        cache[team] = wd
                    elif team in europlan_index:
                        coord = europlan_index[team]
                        cache[team] = coord

        out_row = dict(row)
        if coord:
            out_row["lat"] = float(coord["lat"])
            out_row["lon"] = float(coord["lon"])
            out_row["stadium"] = coord.get("stadium", "")
            out_row["stadium_address"] = coord.get("address", "")
            out_row["coord_source"] = coord.get("source", "")
            stadium_hits += 1
        else:
            out_row["stadium"] = ""
            out_row["stadium_address"] = ""
            out_row["coord_source"] = "club_fallback"
        rows.append(out_row)

    save_stadium_cache(STADIUM_CACHE_FILE, cache)
    out_df = pd.DataFrame(rows)
    return out_df, {
        "total": len(out_df),
        "stadium": stadium_hits,
        "fallback_club": len(out_df) - stadium_hits,
        "europlan_index_size": len(europlan_index),
    }


def resolve_overlay_coords(df: pd.DataFrame, teams: List[str]) -> Tuple[Dict[str, Tuple[float, float]], List[str]]:
    coords: Dict[str, Tuple[float, float]] = {}
    missing: List[str] = []
    by_csv = {
        normalize_text(row["Verein"]): (float(row["lat"]), float(row["lon"]))
        for _, row in df.iterrows()
    }
    by_cache = load_cache_coords(CACHE_FILE)

    # Fuer Transition-Overlays zuerst aktiv ueber kompass aufloesen
    # (beruecksichtigt harte Club-Overrides und aktualisiert Cache).
    try:
        import kompass
        for team in teams:
            t = normalize_text(team)
            if t in by_csv:
                continue
            try:
                clubs = kompass.build_clubs([t])
                if clubs:
                    coords[t] = (float(clubs[0].lat), float(clubs[0].lon))
            except Exception:
                continue
    except Exception:
        pass

    for team in teams:
        t = normalize_text(team)
        if t in coords:
            continue
        if t in by_csv:
            coords[t] = by_csv[t]
        elif t in by_cache:
            coords[t] = by_cache[t]
        else:
            missing.append(t)

    unresolved = [t for t in teams if normalize_text(t) not in coords]
    return coords, unresolved


def build_map(
    df: pd.DataFrame,
    out_html: str,
    transitions: Dict,
    changed_teams: Optional[Dict[str, Tuple[str, str]]] = None,
    variant: str = "std",
    changed_left_label: str = "STD",
    changed_right_label: str = "MATRIX",
) -> List[str]:
    league_colors = {
        "Nord": "blue",
        "West": "red",
        "Ost": "green",
        "Sued": "orange",
        "Süd": "orange",
    }
    center_lat = float(df["lat"].mean())
    center_lon = float(df["lon"].mean())
    m = folium.Map(location=[center_lat, center_lon], zoom_start=6, tiles=None)
    folium.TileLayer(
        tiles="https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        name="OpenStreetMap DE",
    ).add_to(m)
    by_csv_liga = {
        normalize_text(row["Verein"]): normalize_text(row["Liga"])
        for _, row in df.iterrows()
    }

    for _, row in df.iterrows():
        liga = normalize_text(row["Liga"])
        color = league_colors.get(liga, "gray")
        stadium = normalize_text(row.get("stadium", ""))
        source = normalize_text(row.get("coord_source", "club"))
        popup = f"{row['Verein']} ({liga})"
        if stadium:
            popup += f"<br>Stadion: {stadium}<br>Quelle: {source}"
        folium.CircleMarker(
            location=[float(row["lat"]), float(row["lon"])],
            radius=6,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.8,
            popup=popup,
            tooltip=f"{row['Verein']} | {liga}",
        ).add_to(m)

    # Unterschiede zwischen Standard- und Matrix-Lösung sichtbar markieren.
    if changed_teams:
        for _, row in df.iterrows():
            team = normalize_text(row["Verein"])
            if team not in changed_teams:
                continue
            lat, lon = float(row["lat"]), float(row["lon"])
            liga_left, liga_right = changed_teams[team]
            folium.CircleMarker(
                location=[lat, lon],
                radius=12,
                color="#111111",
                weight=3,
                fill=False,
                tooltip=(
                    f"{team} | Unterschied {changed_left_label}:{liga_left}"
                    f" -> {changed_right_label}:{liga_right}"
                ),
                popup=(
                    f"{team} ({changed_left_label}: {liga_left} | "
                    f"{changed_right_label}: {liga_right})"
                ),
            ).add_to(m)

    overlay_teams = sorted(
        set(
            transitions.get("promoted_to_3liga", [])
            + transitions.get("relegated_from_regionalliga", [])
            + transitions.get("relegated_from_3liga", [])
            + transitions.get("promoted_from_oberliga", [])
        )
    )
    overlay_coords, unresolved = resolve_overlay_coords(df, overlay_teams)

    for team in transitions.get("relegated_from_regionalliga", []):
        t = normalize_text(team)
        if t not in overlay_coords:
            continue
        lat, lon = overlay_coords[t]
        folium.CircleMarker(
            location=[lat, lon],
            radius=10,
            color="gray",
            fill=False,
            weight=3,
            tooltip=f"{t} | Absteiger Regionalliga",
            popup=f"{t} (Absteiger Regionalliga)",
        ).add_to(m)

    for team in transitions.get("promoted_to_3liga", []):
        t = normalize_text(team)
        if t not in overlay_coords:
            continue
        lat, lon = overlay_coords[t]
        folium.RegularPolygonMarker(
            location=[lat, lon],
            number_of_sides=3,
            radius=11,
            color="#b8860b",
            fill_color="#ffd700",
            fill_opacity=0.9,
            tooltip=f"{t} | Aufsteiger in 3. Liga",
            popup=f"{t} (Aufsteiger in 3. Liga)",
        ).add_to(m)

    for team in transitions.get("relegated_from_3liga", []):
        t = normalize_text(team)
        if t not in overlay_coords:
            continue
        lat, lon = overlay_coords[t]
        folium.RegularPolygonMarker(
            location=[lat, lon],
            number_of_sides=4,
            radius=10,
            color="#2f2f2f",
            fill_color="#ffffff",
            fill_opacity=0.0,
            tooltip=f"{t} | Absteiger aus 3. Liga",
            popup=f"{t} (Absteiger aus 3. Liga)",
        ).add_to(m)

    for team in transitions.get("promoted_from_oberliga", []):
        t = normalize_text(team)
        if t not in overlay_coords:
            continue
        lat, lon = overlay_coords[t]
        folium.RegularPolygonMarker(
            location=[lat, lon],
            number_of_sides=5,
            radius=14,
            color="#2f2f2f",
            weight=3,
            fill_color="#ffffff",
            fill_opacity=0.0,
            tooltip=f"{t} | Aufsteiger aus Oberliga",
            popup=f"{t} (Aufsteiger aus Oberliga)",
        ).add_to(m)

    legend_html = """
    <div style="
      position: fixed;
      bottom: 20px; left: 20px; z-index: 9999;
      background: white; border: 1px solid #333; padding: 10px; font-size: 14px;">
      <b>Liga</b><br>
      <span style="color:blue;">●</span> Nord<br>
      <span style="color:red;">●</span> West<br>
      <span style="color:green;">●</span> Ost<br>
      <span style="color:orange;">●</span> Sued<br>
      <span style="color:gray;">◯</span> Absteiger RL<br>
      <span style="color:#ffd700;">▲</span> Aufsteiger in 3. Liga<br>
      <span style="color:#2f2f2f;">□</span> Absteiger aus 3. Liga (nur Form)<br>
      <span style="color:#2f2f2f;">⬟</span> Aufsteiger aus Oberliga (nur Form)<br>
      <span style="color:#111;">◯</span> Unterschied STD/MATRIX
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    ensure_parent_dir(out_html)
    m.save(out_html)
    return unresolved


def compute_metrics(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    clubs_rows: List[Dict] = []
    league_rows: List[Dict] = []
    trips_rows: List[Dict] = []

    for liga, g in df.groupby("Liga", sort=True):
        records = g.to_dict("records")
        n = len(records)
        all_away_distances: List[float] = []
        undirected_pairs: List[Tuple[str, str, float]] = []

        for i in range(n):
            club_i = records[i]
            dists_i: List[float] = []
            for j in range(n):
                if i == j:
                    continue
                club_j = records[j]
                d = haversine_km(
                    float(club_i["lat"]),
                    float(club_i["lon"]),
                    float(club_j["lat"]),
                    float(club_j["lon"]),
                )
                dists_i.append(d)
                all_away_distances.append(d)
                trips_rows.append(
                    {
                        "Liga": liga,
                        "Von": club_i["Verein"],
                        "Nach": club_j["Verein"],
                        "Distanz_km": round(d, 2),
                    }
                )

            clubs_rows.append(
                {
                    "Liga": liga,
                    "Verein": club_i["Verein"],
                    "Auswaerts_spiele": n - 1,
                    "Durchschnitt_Auswaerts_km": round(sum(dists_i) / len(dists_i), 2),
                    "Saison_Auswaerts_km": round(sum(dists_i), 2),
                    "Laengste_Einzelreise_km": round(max(dists_i), 2),
                }
            )

        for i in range(n):
            for j in range(i + 1, n):
                d = haversine_km(
                    float(records[i]["lat"]),
                    float(records[i]["lon"]),
                    float(records[j]["lat"]),
                    float(records[j]["lon"]),
                )
                undirected_pairs.append((records[i]["Verein"], records[j]["Verein"], d))

        league_avg = sum(all_away_distances) / len(all_away_distances) if all_away_distances else 0.0
        longest = max(undirected_pairs, key=lambda x: x[2]) if undirected_pairs else ("", "", 0.0)
        league_rows.append(
            {
                "Liga": liga,
                "Teams": n,
                "Durchschnitt_Auswaertsreise_km": round(league_avg, 2),
                "Laengste_Reise_Von": longest[0],
                "Laengste_Reise_Nach": longest[1],
                "Laengste_Reise_km": round(longest[2], 2),
            }
        )

    club_df = pd.DataFrame(clubs_rows).sort_values(["Liga", "Verein"])
    league_df = pd.DataFrame(league_rows).sort_values("Liga")
    trips_df = pd.DataFrame(trips_rows).sort_values("Distanz_km", ascending=False)
    return club_df, league_df, trips_df


def print_summary(club_df: pd.DataFrame, league_df: pd.DataFrame, trips_df: pd.DataFrame) -> None:
    max_season_row = club_df.loc[club_df["Saison_Auswaerts_km"].idxmax()]
    max_trip = trips_df.iloc[0]

    print("lat/lon sind geografische Koordinaten in Dezimalgrad:")
    print("lat = Breitengrad, lon = Laengengrad")
    print()
    print("Max Distanz pro Saison (Auswaerts-Summe eines Vereins):")
    print(
        f"- {max_season_row['Verein']} ({max_season_row['Liga']}): "
        f"{max_season_row['Saison_Auswaerts_km']:.2f} km"
    )
    print()
    print("Durchschnittliche Distanz pro Liga (Auswaertsfahrten):")
    for _, row in league_df.iterrows():
        print(f"- {row['Liga']}: {row['Durchschnitt_Auswaertsreise_km']:.2f} km")
    print()
    print("Laengste Einzelreise (gesamt):")
    print(
        f"- {max_trip['Von']} -> {max_trip['Nach']} ({max_trip['Liga']}): "
        f"{max_trip['Distanz_km']:.2f} km"
    )
    print()
    print("Laengste Reisen je Liga:")
    for _, row in league_df.iterrows():
        print(
            f"- {row['Liga']}: {row['Laengste_Reise_Von']} -> {row['Laengste_Reise_Nach']} "
            f"({row['Laengste_Reise_km']:.2f} km)"
        )


def load_ranked_solutions(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def rank_csv_path(rank: int) -> str:
    mapping = {
        1: INPUT_CSV,
        2: INPUT_CSV_RANK2,
        3: INPUT_CSV_RANK3,
        5: INPUT_CSV_RANK5,
        10: INPUT_CSV_RANK10,
    }
    return mapping.get(
        int(rank),
        str(OUTPUT_CSV_DIR / f"kompass_regionalliga_4x20_matrix_rank{int(rank)}.csv"),
    )


def rank_map_path(rank: int) -> str:
    mapping = {
        1: MAP_HTML,
        2: MAP_HTML_RANK2,
        3: MAP_HTML_RANK3,
        5: MAP_HTML_RANK5,
        10: MAP_HTML_RANK10,
    }
    return mapping.get(
        int(rank),
        str(OUTPUT_HTML_DIR / f"kompass_regionalliga_4x20_map_rank{int(rank)}.html"),
    )


def rank_compare_path(rank: int) -> str:
    mapping = {
        2: MAP_COMPARE_HTML_RANK2,
        3: MAP_COMPARE_HTML_RANK3,
        5: MAP_COMPARE_HTML_RANK5,
        10: MAP_COMPARE_HTML_RANK10,
    }
    return mapping.get(
        int(rank),
        str(OUTPUT_HTML_DIR / f"kompass_regionalliga_compare_rank{int(rank)}.html"),
    )


def compute_changed_teams(df_left: pd.DataFrame, df_right: pd.DataFrame) -> Dict[str, Tuple[str, str]]:
    left_map = {
        normalize_text(r["Verein"]): normalize_text(r["Liga"])
        for _, r in df_left.iterrows()
    }
    right_map = {
        normalize_text(r["Verein"]): normalize_text(r["Liga"])
        for _, r in df_right.iterrows()
    }
    changed: Dict[str, Tuple[str, str]] = {}
    for team, liga_left in left_map.items():
        liga_right = right_map.get(team)
        if liga_right is not None and liga_right != liga_left:
            changed[team] = (liga_left, liga_right)
    return changed


def write_stadium_snapshot(df_map: pd.DataFrame, out_json: str) -> None:
    cache = load_stadium_cache(STADIUM_CACHE_FILE)
    overrides = load_stadium_overrides(STADIUM_OVERRIDES_FILE)

    teams: List[Dict[str, Any]] = []
    for _, row in df_map.sort_values(["Liga", "Verein"]).iterrows():
        team = normalize_text(row["Verein"])
        source_from_row = normalize_text(row.get("coord_source", ""))
        source_data = overrides.get(team) or cache.get(team) or {}
        stadium = normalize_text(row.get("stadium", "")) or normalize_text(source_data.get("stadium", ""))
        address = normalize_text(row.get("stadium_address", "")) or normalize_text(source_data.get("address", ""))
        source = source_from_row or normalize_text(source_data.get("source", ""))
        teams.append(
            {
                "liga": normalize_text(row.get("Liga", "")),
                "verein": team,
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "stadium": stadium,
                "address": address,
                "source": source,
                "source_url": normalize_text(source_data.get("source_url", "")),
                "updated_at": normalize_text(source_data.get("updated_at", "")),
            }
        )

    fallback_count = sum(1 for t in teams if t["source"] == "club_fallback")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(teams),
        "stadium_hits": len(teams) - fallback_count,
        "fallback_club": fallback_count,
        "teams": teams,
    }
    ensure_parent_dir(out_json)
    Path(out_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_variant_payload(
    variant_id: str,
    title: str,
    map_html: str,
    df: pd.DataFrame,
    club_df: pd.DataFrame,
    league_df: pd.DataFrame,
    trips_df: pd.DataFrame,
    rank_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    clubs_by_league: Dict[str, List[str]] = {}
    for liga, group in df.groupby("Liga", sort=True):
        clubs_by_league[normalize_text(liga)] = sorted(
            [normalize_text(v) for v in group["Verein"].tolist()],
            key=lambda x: x.lower(),
        )

    leagues: List[Dict[str, Any]] = []
    for _, row in league_df.iterrows():
        leagues.append(
            {
                "liga": normalize_text(row["Liga"]),
                "avg_km": float(row["Durchschnitt_Auswaertsreise_km"]),
                "longest_route": (
                    f"{normalize_text(row['Laengste_Reise_Von'])} -> "
                    f"{normalize_text(row['Laengste_Reise_Nach'])}"
                ),
                "longest_km": float(row["Laengste_Reise_km"]),
            }
        )

    top_trips: List[Dict[str, Any]] = []
    for idx, (_, row) in enumerate(trips_df.head(5).iterrows(), start=1):
        top_trips.append(
            {
                "index": idx,
                "route": f"{normalize_text(row['Von'])} -> {normalize_text(row['Nach'])}",
                "km": float(row["Distanz_km"]),
            }
        )

    out: Dict[str, Any] = {
        "id": variant_id,
        "title": title,
        "map_html": map_html,
        "overall_avg_km": float(club_df["Durchschnitt_Auswaerts_km"].mean()),
        "leagues": leagues,
        "top_trips": top_trips,
        "clubs_by_league": clubs_by_league,
    }
    if rank_info:
        out["rank"] = int(rank_info.get("rank", 0))
        out["rank_label"] = normalize_text(rank_info.get("rank_label", ""))
        out["score_avg_away_km"] = float(rank_info.get("score_avg_away_km", 0.0))
        out["gap_to_best_km"] = float(rank_info.get("gap_to_best_km", 0.0))
    return out


def create_index_html(page_data: Dict[str, Any], out_html: str) -> None:
    payload = json.dumps(page_data, ensure_ascii=False)
    html = """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kompass-Regionalliga 4x20</title>
  <style>
    :root {
      --bg: #f6f7fb;
      --card: #ffffff;
      --text: #1c2530;
      --muted: #536375;
      --accent: #005ecb;
      --border: #d9e1eb;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Tahoma, Arial, sans-serif;
      background: radial-gradient(circle at 10% 0%, #e9f2ff 0%, var(--bg) 38%);
      color: var(--text);
      line-height: 1.45;
    }
    main {
      max-width: 1200px;
      margin: 0 auto;
      padding: 24px 16px 36px;
    }
    h1, h2, h3 {
      margin: 0 0 10px;
      line-height: 1.2;
    }
    h1 { font-size: clamp(1.7rem, 3.2vw, 2.2rem); }
    h2 { margin-top: 22px; font-size: 1.25rem; }
    p { margin: 0 0 14px; color: var(--muted); }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
      margin-bottom: 14px;
    }
    .map-frame {
      width: 100%;
      min-height: 70vh;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: #fff;
    }
    .switch {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 10px;
    }
    .switch button {
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text);
      border-radius: 999px;
      padding: 6px 12px;
      cursor: pointer;
      font-size: 0.92rem;
    }
    .switch button.active {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }
    .meta {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
    }
    .meta div {
      background: #fff;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      color: var(--muted);
    }
    .meta strong {
      display: block;
      color: var(--text);
      margin-bottom: 4px;
    }
    .selection ul {
      margin: 0;
      padding-left: 18px;
    }
    .selection li {
      margin-bottom: 4px;
      color: var(--muted);
    }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 12px;
    }
    .clubs-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }
    .league-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.94rem;
    }
    .league-table th,
    .league-table td {
      border-bottom: 1px solid var(--border);
      padding: 6px 4px;
      text-align: left;
      color: var(--muted);
      vertical-align: top;
    }
    .league-table th {
      color: var(--text);
      font-weight: 600;
    }
    .league-table td:first-child,
    .league-table th:first-child {
      width: 34px;
    }
    .repo-link { margin-top: 8px; font-size: 0.95rem; }
    .compare-links a {
      display: inline-block;
      margin-right: 10px;
      margin-bottom: 6px;
    }
    .note {
      margin-top: 18px;
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: #fff;
      color: var(--muted);
      font-size: 0.95rem;
    }
    a {
      color: var(--accent);
      text-decoration: none;
    }
    a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <main>
    <h1>Kompass-Regionalliga 4x20</h1>
    <p id="subtitle"></p>
    <p class="repo-link"><a id="repo-link" href="#" hidden>Zum GitHub-Repository</a></p>

    <section class="card">
      <h2>Karte</h2>
      <div class="switch" id="variant-switch"></div>
      <p id="variant-note"></p>
      <p>Direktlink: <a id="map-link" href="#">Karte öffnen</a></p>
      <iframe id="map-frame" class="map-frame" src="" title="Kompass-Regionalliga Karte"></iframe>
    </section>

    <section>
      <h2>Datenstand</h2>
      <div class="meta" id="meta-grid"></div>
    </section>

    <section class="selection">
      <h2>Wie die Auswahl erfolgt</h2>
      <ul>
        <li>Je Regionalliga werden die Tabellenplätze 2-13 übernommen.</li>
        <li>Hinzu kommen 4 Absteiger aus der 3. Liga.</li>
        <li>Hinzu kommen 14 Oberliga-Meister.</li>
        <li>2 Zusatzplätze gehen aktuell an Bayern und Nordost.</li>
        <li>Reserve-/U-Teams sind im aktuellen Reformmodus erlaubt.</li>
      </ul>
    </section>

    <section>
      <h2>Optimierung</h2>
      <div class="meta" id="search-grid"></div>
    </section>

    <section class="card">
      <h2>Einfach Erklärt</h2>
      <p id="simple-explanation"></p>
    </section>

    <section>
      <h2>Statistiken</h2>
      <div class="stats-grid">
        <div class="card">
          <h3>Gesamt</h3>
          <table class="league-table" id="overall-table"></table>
        </div>
        <div class="card">
          <h3>Pro Liga</h3>
          <table class="league-table" id="league-table"></table>
        </div>
        <div class="card">
          <h3>Top 5 längste Reisen (gesamt)</h3>
          <table class="league-table" id="trip-table"></table>
        </div>
      </div>
    </section>

    <section>
      <h2>Vereinsliste</h2>
      <div class="clubs-grid" id="clubs-grid"></div>
    </section>

    <section class="card">
      <h2>Vergleichsseiten</h2>
      <div class="compare-links" id="compare-links"></div>
    </section>

    <p class="note">
      Dieses Projekt wurde mit Hilfe von <strong>GPT-5.3-Codex</strong> erstellt und weiterentwickelt.
    </p>
  </main>

  <script>
    const PAGE_DATA = __PAGE_DATA__;

    function esc(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function fmtKm(value) {
      const num = Number(value);
      if (!Number.isFinite(num)) return "-";
      return num.toFixed(2) + " km";
    }

    function renderCards(containerId, cards) {
      const el = document.getElementById(containerId);
      if (!el) return;
      el.innerHTML = (cards || [])
        .map(card => `<div><strong>${esc(card.label)}</strong>${esc(card.value)}</div>`)
        .join("");
    }

    function renderCompareLinks(links) {
      const el = document.getElementById("compare-links");
      if (!el) return;
      if (!links || links.length === 0) {
        el.textContent = "Keine Vergleichsseite verfügbar.";
        return;
      }
      el.innerHTML = links
        .map(link => `<a href="${esc(link.href)}">${esc(link.label)}</a>`)
        .join("");
    }

    const variants = PAGE_DATA.variants || [];
    let activeId = variants.length ? variants[0].id : "";

    function findVariant(id) {
      return variants.find(v => v.id === id) || variants[0];
    }

    function renderVariant(variant) {
      if (!variant) return;
      const mapFrame = document.getElementById("map-frame");
      const mapLink = document.getElementById("map-link");
      const note = document.getElementById("variant-note");
      mapFrame.src = variant.map_html;
      mapLink.href = variant.map_html;

      const rankBits = [];
      if (variant.rank_label) rankBits.push(variant.rank_label);
      if (Number.isFinite(Number(variant.score_avg_away_km))) {
        rankBits.push("Score: " + fmtKm(variant.score_avg_away_km));
      }
      if (Number.isFinite(Number(variant.gap_to_best_km))) {
        rankBits.push("Gap zu Rank 1: " + fmtKm(variant.gap_to_best_km));
      }
      note.textContent = rankBits.join(" | ");

      const overall = document.getElementById("overall-table");
      overall.innerHTML = [
        "<tbody>",
        "<tr><th>Kennzahl</th><th>Wert</th></tr>",
        `<tr><td>Durchschnitt pro Team</td><td>${esc(fmtKm(variant.overall_avg_km))}</td></tr>`,
        "</tbody>"
      ].join("");

      const leagues = variant.leagues || [];
      const leagueRows = leagues.map(l => (
        `<tr><td>${esc(l.liga)}</td><td>${esc(fmtKm(l.avg_km))}</td>` +
        `<td>${esc(l.longest_route)} (${esc(fmtKm(l.longest_km))})</td></tr>`
      )).join("");
      document.getElementById("league-table").innerHTML = [
        "<thead><tr><th>Liga</th><th>Ø Distanz</th><th>Längste Reise</th></tr></thead>",
        `<tbody>${leagueRows}</tbody>`
      ].join("");

      const trips = variant.top_trips || [];
      const tripRows = trips.map(t => (
        `<tr><td>${esc(t.index)}</td><td>${esc(t.route)}</td><td>${esc(fmtKm(t.km))}</td></tr>`
      )).join("");
      document.getElementById("trip-table").innerHTML = [
        "<thead><tr><th>#</th><th>Route</th><th>Distanz</th></tr></thead>",
        `<tbody>${tripRows}</tbody>`
      ].join("");

      const clubsByLeague = variant.clubs_by_league || {};
      const leaguesOrdered = Object.keys(clubsByLeague).sort();
      document.getElementById("clubs-grid").innerHTML = leaguesOrdered.map(liga => {
        const clubs = clubsByLeague[liga] || [];
        const rows = clubs.map((team, idx) => `<tr><td>${idx + 1}</td><td>${esc(team)}</td></tr>`).join("");
        return [
          '<div class="card">',
          `<h3>${esc(liga)}</h3>`,
          '<table class="league-table">',
          '<thead><tr><th>#</th><th>Verein</th></tr></thead>',
          `<tbody>${rows}</tbody>`,
          '</table>',
          '</div>',
        ].join("");
      }).join("");
    }

    function renderSwitch() {
      const el = document.getElementById("variant-switch");
      if (!el) return;
      el.innerHTML = variants.map(v => (
        `<button class="${v.id === activeId ? "active" : ""}" data-variant="${esc(v.id)}">${esc(v.title)}</button>`
      )).join("");
      el.querySelectorAll("button[data-variant]").forEach(btn => {
        btn.addEventListener("click", function () {
          activeId = this.getAttribute("data-variant") || "";
          renderSwitch();
          renderVariant(findVariant(activeId));
        });
      });
    }

    (function bootstrap() {
      const subtitle = document.getElementById("subtitle");
      if (subtitle) subtitle.textContent = PAGE_DATA.subtitle || "";
      const simpleExplanation = document.getElementById("simple-explanation");
      if (simpleExplanation) simpleExplanation.textContent = PAGE_DATA.simple_explanation || "";
      renderCards("meta-grid", PAGE_DATA.meta_cards || []);
      renderCards("search-grid", PAGE_DATA.search_cards || []);
      renderCompareLinks(PAGE_DATA.compare_links || []);
      renderSwitch();
      renderVariant(findVariant(activeId));

      const link = document.getElementById("repo-link");
      const host = window.location.hostname;
      if (!link || !host.endsWith("github.io")) return;
      const user = host.replace(".github.io", "");
      const repo = window.location.pathname.split("/").filter(Boolean)[0];
      if (!user || !repo) return;
      link.href = "https://github.com/" + user + "/" + repo;
      link.hidden = false;
    })();
  </script>
</body>
</html>"""
    ensure_parent_dir(out_html)
    Path(out_html).write_text(html.replace("__PAGE_DATA__", payload), encoding="utf-8")


def create_compare_html(
    left_map: str,
    right_map: str,
    out_html: str,
    left_title: str = "Hauptkarte",
    right_title: str = "Vergleich",
) -> None:
    html = f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Kompass Vergleich</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; height: 100vh; }}
    .pane {{ display: flex; flex-direction: column; min-width: 0; }}
    .head {{ padding: 8px 10px; background: #f1f3f5; border-bottom: 1px solid #ccc; font-weight: 600; }}
    iframe {{ border: 0; width: 100%; height: 100%; }}
  </style>
</head>
<body>
  <div class="grid">
    <div class="pane">
      <div class="head">{left_title}</div>
      <iframe src="{left_map}"></iframe>
    </div>
    <div class="pane">
      <div class="head">{right_title}</div>
      <iframe src="{right_map}"></iframe>
    </div>
  </div>
</body>
</html>"""
    ensure_parent_dir(out_html)
    Path(out_html).write_text(html, encoding="utf-8")


def main() -> None:
    OUTPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON_DIR.mkdir(parents=True, exist_ok=True)

    def load_solution_csv(path: Path) -> pd.DataFrame:
        data = pd.read_csv(path)
        for col in ("Liga", "Verein"):
            data[col] = data[col].map(normalize_text)
        data["lat"] = pd.to_numeric(data["lat"], errors="raise")
        data["lon"] = pd.to_numeric(data["lon"], errors="raise")
        return data

    in_path = Path(INPUT_CSV)
    if not in_path.exists():
        raise FileNotFoundError(f"CSV not found: {INPUT_CSV}")
    df_rank1 = load_solution_csv(in_path)

    transitions = load_transitions(TRANSITIONS_JSON)
    ranked_payload = load_ranked_solutions(SOLUTIONS_RANKED_JSON)
    ranked_entries_raw = ranked_payload.get("solutions", [])
    ranked_entries = ranked_entries_raw if isinstance(ranked_entries_raw, list) else []
    rank_meta: Dict[int, Dict[str, Any]] = {}
    for entry in ranked_entries:
        if not isinstance(entry, dict):
            continue
        try:
            rank_no = int(entry.get("rank", 0))
        except Exception:
            continue
        if rank_no > 0:
            rank_meta[rank_no] = entry
    best_score = rank_meta.get(1, {}).get("score_avg_away_km")

    rank_data: Dict[int, Dict[str, Any]] = {}
    for rank in DISPLAY_MATRIX_RANKS:
        csv_path = Path(rank_csv_path(rank))
        if not csv_path.exists():
            continue
        df_rank = load_solution_csv(csv_path)
        rank_data[rank] = {"df": df_rank, "csv": str(csv_path)}

    if 1 not in rank_data:
        rank_data[1] = {"df": df_rank1, "csv": INPUT_CSV}

    worst_data: Optional[Dict[str, Any]] = None
    worst_csv_path = Path(INPUT_CSV_WORST)
    if worst_csv_path.exists():
        try:
            df_worst = load_solution_csv(worst_csv_path)
            worst_data = {"df": df_worst, "csv": str(worst_csv_path)}
        except Exception:
            worst_data = None
    initial_data: Optional[Dict[str, Any]] = None
    initial_csv_path = Path(INPUT_CSV_INITIAL)
    if initial_csv_path.exists():
        try:
            df_initial = load_solution_csv(initial_csv_path)
            initial_data = {"df": df_initial, "csv": str(initial_csv_path)}
        except Exception:
            initial_data = None
    initial_auto_data: Optional[Dict[str, Any]] = None
    initial_auto_csv_path = Path(INPUT_CSV_INITIAL_AUTO)
    if initial_auto_csv_path.exists():
        try:
            df_initial_auto = load_solution_csv(initial_auto_csv_path)
            initial_auto_data = {"df": df_initial_auto, "csv": str(initial_auto_csv_path)}
        except Exception:
            initial_auto_data = None
    initial_manual_data: Optional[Dict[str, Any]] = None
    initial_manual_csv_path = Path(INPUT_CSV_INITIAL_MANUAL)
    if initial_manual_csv_path.exists():
        try:
            df_initial_manual = load_solution_csv(initial_manual_csv_path)
            initial_manual_data = {"df": df_initial_manual, "csv": str(initial_manual_csv_path)}
        except Exception:
            initial_manual_data = None

    df_map_rank1, map_coord_stats = resolve_map_coordinates(rank_data[1]["df"])
    changed_vs_rank2 = (
        compute_changed_teams(rank_data[1]["df"], rank_data[2]["df"])
        if 2 in rank_data
        else {}
    )
    unresolved_overlay = build_map(
        df_map_rank1,
        MAP_HTML,
        transitions,
        changed_teams=changed_vs_rank2 if changed_vs_rank2 else None,
        variant="matrix",
        changed_left_label="RANK1",
        changed_right_label="RANK2",
    )
    df_map_rank1.to_csv(MAP_COORDS_CSV, index=False, encoding="utf-8")
    missing_df = df_map_rank1[df_map_rank1["coord_source"] == "club_fallback"][["Liga", "Verein"]].copy()
    missing_df.to_csv(STADIUM_MISSING_CSV, index=False, encoding="utf-8")
    write_stadium_snapshot(df_map_rank1, STADIUM_SNAPSHOT_JSON)

    club_df, league_df, trips_df = compute_metrics(rank_data[1]["df"])
    club_df.to_csv(CLUB_METRICS_CSV, index=False, encoding="utf-8")
    league_df.to_csv(LEAGUE_METRICS_CSV, index=False, encoding="utf-8")
    trips_df.head(100).to_csv(LONGEST_TRIPS_CSV, index=False, encoding="utf-8")
    print_summary(club_df, league_df, trips_df)

    variants: List[Dict[str, Any]] = []
    compare_links: List[Dict[str, str]] = []
    initial_score: Optional[float] = None

    for rank in DISPLAY_MATRIX_RANKS:
        if rank not in rank_data:
            continue
        df_rank = rank_data[rank]["df"]
        map_path = rank_map_path(rank)
        if rank == 1:
            df_rank_map = df_map_rank1
        else:
            df_rank_map, _ = resolve_map_coordinates(df_rank)
            changed_vs_rank1 = compute_changed_teams(rank_data[1]["df"], df_rank)
            build_map(
                df_rank_map,
                map_path,
                transitions,
                changed_teams=changed_vs_rank1 if changed_vs_rank1 else None,
                variant=f"matrix_rank{rank}",
                changed_left_label="RANK1",
                changed_right_label=f"RANK{rank}",
            )
            compare_path = rank_compare_path(rank)
            create_compare_html(
                html_asset_name(MAP_HTML),
                html_asset_name(map_path),
                compare_path,
                left_title="Distanzmatrix-Optimierung (Rank 1)",
                right_title=f"Distanzmatrix-Optimierung (Rank {rank})",
            )
            compare_links.append({"href": html_asset_name(compare_path), "label": f"Rank 1 vs Rank {rank}"})
            print(f"Karte (Rank-{rank}-Vergleich): {map_path}")
            print(f"Kartenvergleich: {compare_path}")
            print(f"Sichtbare Unterschiede Rank1/Rank{rank}: {len(changed_vs_rank1)}")

        club_df_rank, league_df_rank, trips_df_rank = compute_metrics(df_rank)
        meta = rank_meta.get(rank, {})
        variants.append(
            build_variant_payload(
                f"rank{rank}",
                f"Rank {rank} (Matrix)",
                html_asset_name(map_path),
                df_rank,
                club_df_rank,
                league_df_rank,
                trips_df_rank,
                rank_info={
                    "rank": rank,
                    "rank_label": f"Rank {rank} (Distanzmatrix)",
                    "score_avg_away_km": meta.get("score_avg_away_km", club_df_rank["Durchschnitt_Auswaerts_km"].mean()),
                    "gap_to_best_km": meta.get("gap_to_best_km", 0.0),
                },
            )
        )

    if initial_data is not None:
        changed_initial_vs_rank1 = compute_changed_teams(initial_data["df"], rank_data[1]["df"])
        df_initial_map, _ = resolve_map_coordinates(initial_data["df"])
        build_map(
            df_initial_map,
            MAP_HTML_INITIAL,
            transitions,
            changed_teams=changed_initial_vs_rank1 if changed_initial_vs_rank1 else None,
            variant="initial",
            changed_left_label="INITIAL",
            changed_right_label="RANK1",
        )
        create_compare_html(
            html_asset_name(MAP_HTML_INITIAL),
            html_asset_name(MAP_HTML),
            MAP_COMPARE_HTML_INITIAL,
            left_title="Initialverteilung",
            right_title="Distanzmatrix-Optimierung (Rank 1)",
        )
        compare_links.append({"href": html_asset_name(MAP_COMPARE_HTML_INITIAL), "label": "Initial vs Rank 1"})
        print(f"Karte (Initial): {MAP_HTML_INITIAL}")
        print(f"Kartenvergleich: {MAP_COMPARE_HTML_INITIAL}")
        print(f"Sichtbare Unterschiede Initial/Rank1: {len(changed_initial_vs_rank1)}")

        club_df_initial, league_df_initial, trips_df_initial = compute_metrics(initial_data["df"])
        initial_score = float(club_df_initial["Durchschnitt_Auswaerts_km"].mean())
        variants.append(
            build_variant_payload(
                "initial",
                "Initialverteilung",
                html_asset_name(MAP_HTML_INITIAL),
                initial_data["df"],
                club_df_initial,
                league_df_initial,
                trips_df_initial,
                rank_info={
                    "rank": 0,
                    "rank_label": "Initialverteilung",
                    "score_avg_away_km": initial_score,
                    "gap_to_best_km": (
                        float(initial_score) - float(best_score)
                        if best_score is not None
                        else 0.0
                    ),
                },
            )
        )

    if initial_auto_data is not None and initial_manual_data is not None:
        changed_auto_manual = compute_changed_teams(initial_auto_data["df"], initial_manual_data["df"])
        df_initial_auto_map, _ = resolve_map_coordinates(initial_auto_data["df"])
        build_map(
            df_initial_auto_map,
            MAP_HTML_INITIAL_AUTO,
            transitions,
            changed_teams=None,
            variant="initial_auto",
        )
        df_initial_manual_map, _ = resolve_map_coordinates(initial_manual_data["df"])
        build_map(
            df_initial_manual_map,
            MAP_HTML_INITIAL_MANUAL,
            transitions,
            changed_teams=changed_auto_manual if changed_auto_manual else None,
            variant="initial_manual",
            changed_left_label="INITIAL_AUTO",
            changed_right_label="INITIAL_MANUAL",
        )
        create_compare_html(
            html_asset_name(MAP_HTML_INITIAL_AUTO),
            html_asset_name(MAP_HTML_INITIAL_MANUAL),
            MAP_COMPARE_HTML_INITIAL_AUTO_MANUAL,
            left_title="Initialverteilung (Auto)",
            right_title="Initialverteilung (Manuell)",
        )
        compare_links.append(
            {
                "href": html_asset_name(MAP_COMPARE_HTML_INITIAL_AUTO_MANUAL),
                "label": "Initial Auto vs Initial Manuell",
            }
        )
        print(f"Kartenvergleich: {MAP_COMPARE_HTML_INITIAL_AUTO_MANUAL}")
        print(f"Sichtbare Unterschiede Initial-Auto/Initial-Manuell: {len(changed_auto_manual)}")

    if worst_data is not None:
        changed_vs_rank1 = compute_changed_teams(rank_data[1]["df"], worst_data["df"])
        df_worst_map, _ = resolve_map_coordinates(worst_data["df"])
        build_map(
            df_worst_map,
            MAP_HTML_WORST,
            transitions,
            changed_teams=changed_vs_rank1 if changed_vs_rank1 else None,
            variant="matrix_worst",
            changed_left_label="RANK1",
            changed_right_label="WORST",
        )
        create_compare_html(
            html_asset_name(MAP_HTML),
            html_asset_name(MAP_HTML_WORST),
            MAP_COMPARE_HTML_WORST,
            left_title="Distanzmatrix-Optimierung (Rank 1)",
            right_title="Distanzmatrix-Optimierung (Worst found)",
        )
        compare_links.append({"href": html_asset_name(MAP_COMPARE_HTML_WORST), "label": "Rank 1 vs Worst found"})
        print(f"Karte (Worst-Vergleich): {MAP_HTML_WORST}")
        print(f"Kartenvergleich: {MAP_COMPARE_HTML_WORST}")
        print(f"Sichtbare Unterschiede Rank1/Worst: {len(changed_vs_rank1)}")

        club_df_worst, league_df_worst, trips_df_worst = compute_metrics(worst_data["df"])
        worst_meta = ranked_payload.get("worst_found", {})
        variants.append(
            build_variant_payload(
                "worst",
                "Worst found (Matrix)",
                html_asset_name(MAP_HTML_WORST),
                worst_data["df"],
                club_df_worst,
                league_df_worst,
                trips_df_worst,
                rank_info={
                    "rank": int(worst_meta.get("rank", 0)) if worst_meta else 0,
                    "rank_label": (
                        f"Worst found (Rank {int(worst_meta.get('rank', 0))})"
                        if worst_meta and worst_meta.get("rank") is not None
                        else "Worst found"
                    ),
                    "score_avg_away_km": worst_meta.get(
                        "score_avg_away_km",
                        club_df_worst["Durchschnitt_Auswaerts_km"].mean(),
                    ),
                    "gap_to_best_km": (
                        float(worst_meta.get("score_avg_away_km", 0.0)) - float(best_score)
                        if (worst_meta and worst_meta.get("score_avg_away_km") is not None and best_score is not None)
                        else 0.0
                    ),
                },
            )
        )

    if transitions:
        print()
        print(
            f"Overlay-Marker: RL-Absteiger={len(transitions.get('relegated_from_regionalliga', []))}, "
            f"Aufsteiger 3. Liga={len(transitions.get('promoted_to_3liga', []))}, "
            f"Absteiger 3. Liga={len(transitions.get('relegated_from_3liga', []))}, "
            f"Aufsteiger Oberliga={len(transitions.get('promoted_from_oberliga', []))}"
        )
    if unresolved_overlay:
        print(f"Ohne Koordinate (Overlay ausgelassen): {sorted(set(unresolved_overlay))}")

    requested_runs = ranked_payload.get("requested_runs")
    unique_solutions = ranked_payload.get("unique_solutions")
    second_score = rank_meta.get(2, {}).get("score_avg_away_km")
    worst_score = None
    if isinstance(ranked_payload.get("worst_found"), dict):
        worst_score = ranked_payload["worst_found"].get("score_avg_away_km")
    worst_rank = None
    if isinstance(ranked_payload.get("worst_found"), dict):
        worst_rank = ranked_payload["worst_found"].get("rank")
    gap_text = "-"
    try:
        if best_score is not None and second_score is not None:
            gap_text = f"{float(second_score) - float(best_score):.2f} km"
    except Exception:
        gap_text = "-"

    page_data = {
        "subtitle": "Interaktive Umschaltung zwischen Initialverteilung, Rank 1 und Worst found.",
        "simple_explanation": (
            "Wir starten mit einer ersten sinnvollen Teamverteilung (Initialverteilung). "
            "Danach verbessert die Distanzmatrix-Optimierung diese Verteilung in vielen Schritten "
            "und sucht die beste gefundene Lösung (Rank 1). "
            "Zusätzlich zeigen wir die schlechteste gefundene Lösung (Worst found), "
            "damit der Unterschied sichtbar bleibt."
        ),
        "meta_cards": [
            {"label": "Letzter Lauf", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            {"label": "Modus", "value": "Reformregel 12+4+14+2"},
            {"label": "Derby-Regel", "value": "Deaktiviert (ENFORCE_DERBY_SAME_LEAGUE = False)"},
            {"label": "Quellen-Priorität", "value": "FuPa -> Wikipedia"},
        ],
        "search_cards": [
            {"label": "Multi-Start Läufe", "value": str(requested_runs) if requested_runs is not None else "-"},
            {"label": "Eindeutige Lösungen", "value": str(unique_solutions) if unique_solutions is not None else "-"},
            {"label": "Rank-1 Score", "value": f"{float(best_score):.2f} km" if best_score is not None else "-"},
            {"label": "Initial-Score", "value": f"{float(initial_score):.2f} km" if initial_score is not None else "-"},
            {"label": "Gap Rank2-Rank1", "value": gap_text},
            {"label": "Verfügbare Ranks", "value": ", ".join(str(r) for r in sorted(rank_data.keys()))},
            {
                "label": "Worst found",
                "value": (
                    f"Rank {int(worst_rank)} ({float(worst_score):.2f} km)"
                    if worst_rank is not None and worst_score is not None
                    else "-"
                ),
            },
            {
                "label": "Stadionkoordinaten",
                "value": (
                    f"{map_coord_stats['stadium']}/{map_coord_stats['total']} Stadion, "
                    f"{map_coord_stats['fallback_club']} Club-Fallback"
                ),
            },
        ],
        "variants": variants,
        "compare_links": compare_links,
    }
    create_index_html(page_data, INDEX_HTML)
    docs_count = sync_pages_docs(OUTPUT_HTML_DIR, PAGES_DOCS_DIR)

    print()
    print(f"Karte: {MAP_HTML}")
    print(
        "Kartenkoordinaten: "
        f"{map_coord_stats['stadium']}/{map_coord_stats['total']} Stadion-Koordinaten, "
        f"{map_coord_stats['fallback_club']} Club-Fallbacks, "
        f"Europlan-Index={map_coord_stats.get('europlan_index_size', 0)}"
    )
    print(f"Map-Koordinaten (Debug): {MAP_COORDS_CSV}")
    print(f"Stadion-Snapshot: {STADIUM_SNAPSHOT_JSON}")
    print(f"Fehlende Stadiondaten: {STADIUM_MISSING_CSV}")
    print(f"Pro Verein: {CLUB_METRICS_CSV}")
    print(f"Pro Liga: {LEAGUE_METRICS_CSV}")
    print(f"Laengste Reisen (Top 100): {LONGEST_TRIPS_CSV}")
    print(f"Index: {INDEX_HTML}")
    print(f"GitHub Pages (/docs): {PAGES_DOCS_DIR} ({docs_count} HTML-Dateien)")


if __name__ == "__main__":
    main()
