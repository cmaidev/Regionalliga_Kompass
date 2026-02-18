from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import pandas as pd
import requests
from lxml import html

try:
    import folium
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "folium is required for map output. Install with: pip install folium"
    ) from exc


INPUT_CSV = "kompass_regionalliga_4x20.csv"
INPUT_CSV_MATRIX = "kompass_regionalliga_4x20_matrix.csv"
MAP_HTML = "kompass_regionalliga_4x20_map.html"
MAP_HTML_MATRIX = "kompass_regionalliga_4x20_map_matrix.html"
MAP_COMPARE_HTML = "kompass_regionalliga_compare.html"
CLUB_METRICS_CSV = "kompass_away_metrics_per_club.csv"
LEAGUE_METRICS_CSV = "kompass_away_metrics_per_league.csv"
LONGEST_TRIPS_CSV = "kompass_longest_trips.csv"
MAP_COORDS_CSV = "kompass_map_coordinates.csv"
STADIUM_MISSING_CSV = "kompass_stadium_missing.csv"
TRANSITIONS_JSON = "season_transitions.json"
CACHE_FILE = "club_coords_cache.json"
STADIUM_CACHE_FILE = "stadium_coords_cache.json"
STADIUM_OVERRIDES_FILE = "stadium_overrides.json"
USE_STADIUM_COORDS_FOR_MAP = True
USE_EUROPLAN_STADIUM_SOURCE = False

EUROPLAN_LEAGUE_IDS = {
    "Regionalliga Nord": 2900,
    "Regionalliga Nordost": 654,
    "Regionalliga West": 23,
    "Regionalliga Bayern": 640,
    "Regionalliga Suedwest": 24,
}
EUROPLAN_BASE = "https://www.europlan-online.de/"


def normalize_text(text: str) -> str:
    s = str(text).strip()
    if any(x in s for x in ("Ã", "Â", "â", "€", "™", "Ÿ")):
        for enc in ("cp1252", "latin1"):
            try:
                s = s.encode(enc).decode("utf-8")
                break
            except Exception:
                continue
    return " ".join(s.split())


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


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
    m = folium.Map(location=[center_lat, center_lon], zoom_start=6, tiles="CartoDB positron")
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

    # Unterschiede zwischen Standard- und Matrix-Loesung sichtbar markieren.
    if changed_teams:
        for _, row in df.iterrows():
            team = normalize_text(row["Verein"])
            if team not in changed_teams:
                continue
            lat, lon = float(row["lat"]), float(row["lon"])
            liga_std, liga_matrix = changed_teams[team]
            folium.CircleMarker(
                location=[lat, lon],
                radius=12,
                color="#111111",
                weight=3,
                fill=False,
                tooltip=f"{team} | Unterschied STD:{liga_std} -> MATRIX:{liga_matrix}",
                popup=f"{team} (STD: {liga_std} | MATRIX: {liga_matrix})",
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


def create_compare_html(left_map: str, right_map: str, out_html: str) -> None:
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
      <div class="head">Centroid-Optimierung</div>
      <iframe src="{left_map}"></iframe>
    </div>
    <div class="pane">
      <div class="head">Distanzmatrix-Optimierung</div>
      <iframe src="{right_map}"></iframe>
    </div>
  </div>
</body>
</html>"""
    Path(out_html).write_text(html, encoding="utf-8")


def main() -> None:
    in_path = Path(INPUT_CSV)
    if not in_path.exists():
        raise FileNotFoundError(f"CSV not found: {INPUT_CSV}")

    df = pd.read_csv(in_path)
    for col in ("Liga", "Verein"):
        df[col] = df[col].map(normalize_text)
    df["lat"] = pd.to_numeric(df["lat"], errors="raise")
    df["lon"] = pd.to_numeric(df["lon"], errors="raise")

    transitions = load_transitions(TRANSITIONS_JSON)

    changed: Dict[str, Tuple[str, str]] = {}
    in_alt = Path(INPUT_CSV_MATRIX)
    if in_alt.exists():
        tmp_alt = pd.read_csv(in_alt)
        for col in ("Liga", "Verein"):
            tmp_alt[col] = tmp_alt[col].map(normalize_text)
        std_map = {normalize_text(r["Verein"]): normalize_text(r["Liga"]) for _, r in df.iterrows()}
        alt_map = {normalize_text(r["Verein"]): normalize_text(r["Liga"]) for _, r in tmp_alt.iterrows()}
        for team, liga_std in std_map.items():
            liga_alt = alt_map.get(team)
            if liga_alt is not None and liga_alt != liga_std:
                changed[team] = (liga_std, liga_alt)

    df_map, map_coord_stats = resolve_map_coordinates(df)
    unresolved_overlay = build_map(
        df_map, MAP_HTML, transitions, changed_teams=changed, variant="std"
    )
    df_map.to_csv(MAP_COORDS_CSV, index=False, encoding="utf-8")
    missing_df = df_map[df_map["coord_source"] == "club_fallback"][["Liga", "Verein"]].copy()
    missing_df.to_csv(STADIUM_MISSING_CSV, index=False, encoding="utf-8")
    club_df, league_df, trips_df = compute_metrics(df)
    club_df.to_csv(CLUB_METRICS_CSV, index=False, encoding="utf-8")
    league_df.to_csv(LEAGUE_METRICS_CSV, index=False, encoding="utf-8")
    trips_df.head(100).to_csv(LONGEST_TRIPS_CSV, index=False, encoding="utf-8")
    print_summary(club_df, league_df, trips_df)
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
    print()
    print(f"Karte: {MAP_HTML}")
    print(
        "Kartenkoordinaten: "
        f"{map_coord_stats['stadium']}/{map_coord_stats['total']} Stadion-Koordinaten, "
        f"{map_coord_stats['fallback_club']} Club-Fallbacks, "
        f"Europlan-Index={map_coord_stats.get('europlan_index_size', 0)}"
    )
    print(f"Map-Koordinaten (Debug): {MAP_COORDS_CSV}")
    print(f"Fehlende Stadiondaten: {STADIUM_MISSING_CSV}")
    print(f"Pro Verein: {CLUB_METRICS_CSV}")
    print(f"Pro Liga: {LEAGUE_METRICS_CSV}")
    print(f"Laengste Reisen (Top 100): {LONGEST_TRIPS_CSV}")

    # Optionale zweite Karte aus Distanzmatrix-CSV + Vergleichs-HTML
    if in_alt.exists():
        df_alt = pd.read_csv(in_alt)
        for col in ("Liga", "Verein"):
            df_alt[col] = df_alt[col].map(normalize_text)
        df_alt["lat"] = pd.to_numeric(df_alt["lat"], errors="raise")
        df_alt["lon"] = pd.to_numeric(df_alt["lon"], errors="raise")
        df_alt_map, _ = resolve_map_coordinates(df_alt)
        build_map(df_alt_map, MAP_HTML_MATRIX, transitions, changed_teams=changed, variant="matrix")
        create_compare_html(MAP_HTML, MAP_HTML_MATRIX, MAP_COMPARE_HTML)
        print(f"Karte (Distanzmatrix): {MAP_HTML_MATRIX}")
        print(f"Kartenvergleich: {MAP_COMPARE_HTML}")
        print(f"Sichtbare Unterschiede markiert: {len(changed)}")


if __name__ == "__main__":
    main()
