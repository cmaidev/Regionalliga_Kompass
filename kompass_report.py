from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import pandas as pd
import requests
from lxml import html

from kompass_utils import ensure_parent_dir, haversine_km, load_verified_stadiums, normalize_text
from kompass_history import build_history_report, export_history_report
from kompass_weekly import export_weekly_metrics, load_weekly_projections

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
INPUT_CSV_WISH_BEST = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20_wish_best.csv")
INPUT_CSV_WISH_WORST = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20_wish_worst.csv")
INPUT_CSV_REGIONENMODELL = str(OUTPUT_CSV_DIR / "kompass_regionalliga_4x20_regionenmodell.csv")
INPUT_CSV_BAYERN_MEISTER = str(OUTPUT_CSV_DIR / "kompass_bayern_meisterrunde.csv")
INPUT_CSV_BAYERN_ABSTIEG = str(OUTPUT_CSV_DIR / "kompass_bayern_abstiegsrunde.csv")
INPUT_CSV_CURRENT_REGIONALLIGA = str(OUTPUT_CSV_DIR / "kompass_current_regionalliga_after_transitions.csv")
MAP_HTML = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map.html")
MAP_HTML_INITIAL = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_initial.html")
MAP_HTML_INITIAL_AUTO = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_initial_auto.html")
MAP_HTML_INITIAL_MANUAL = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_initial_manual.html")
MAP_HTML_RANK2 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_rank2.html")
MAP_HTML_RANK3 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_rank3.html")
MAP_HTML_RANK5 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_rank5.html")
MAP_HTML_RANK10 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_rank10.html")
MAP_HTML_WORST = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_worst.html")
MAP_HTML_WISH_BEST = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_wish_best.html")
MAP_HTML_REGIONENMODELL = str(OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_regionenmodell.html")
MAP_HTML_BAYERN_MEISTER = str(OUTPUT_HTML_DIR / "kompass_bayern_meisterrunde_map.html")
MAP_HTML_BAYERN_ABSTIEG = str(OUTPUT_HTML_DIR / "kompass_bayern_abstiegsrunde_map.html")
MAP_HTML_CURRENT_REGIONALLIGA = str(OUTPUT_HTML_DIR / "kompass_current_regionalliga_after_transitions_map.html")
MAP_COMPARE_HTML_WISH = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_wish.html")
MAP_COMPARE_HTML_RANK2 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_rank2.html")
MAP_COMPARE_HTML_INITIAL = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_initial.html")
MAP_COMPARE_HTML_INITIAL_AUTO_MANUAL = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_initial_auto_manual.html")
MAP_COMPARE_HTML_RANK3 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_rank3.html")
MAP_COMPARE_HTML_RANK5 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_rank5.html")
MAP_COMPARE_HTML_RANK10 = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_rank10.html")
MAP_COMPARE_HTML_WORST = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_worst.html")
MAP_COMPARE_HTML_REGIONENMODELL = str(OUTPUT_HTML_DIR / "kompass_regionalliga_compare_regionenmodell.html")
MAP_COMPARE_HTML_BAYERN_MEISTER = str(OUTPUT_HTML_DIR / "kompass_bayern_compare_meisterrunde.html")
MAP_COMPARE_HTML_BAYERN_SPLIT = str(OUTPUT_HTML_DIR / "kompass_bayern_compare_split.html")
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
TEAMS_PER_LEAGUE = 20

EUROPLAN_LEAGUE_IDS = {
    "Regionalliga Nord": 2900,
    "Regionalliga Nordost": 654,
    "Regionalliga West": 23,
    "Regionalliga Bayern": 640,
    "Regionalliga Suedwest": 24,
}
EUROPLAN_BASE = "https://www.europlan-online.de/"

TARGET_LEAGUE_COLORS = {
    "Nord": "#2563eb",
    "West": "#dc2626",
    "Ost": "#16a34a",
    "Sued": "#f59e0b",
    "Süd": "#f59e0b",
    "Südwest": "#f59e0b",
}

RL_ORIGIN_COLORS = {
    "Nord": "#2563eb",
    "Nordost": "#0f766e",
    "West": "#dc2626",
    "Bayern": "#8b5e34",
    "Südwest": "#f59e0b",
}


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



def load_transitions(path: str, model_name: Optional[str] = None) -> Dict:
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    if model_name:
        models = raw.get("models", {})
        if isinstance(models, dict) and isinstance(models.get(model_name), dict):
            raw = models[model_name]
        else:
            raw = {}
    out: Dict = {}
    for key in ("source_season", "target_season", "is_projection", "source_priority", "forced_regionalliga_relegations"):
        if key in raw:
            out[key] = raw[key]
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
    third_map = raw.get("relegated_from_3liga_league", {})
    if isinstance(third_map, dict):
        out["relegated_from_3liga_league"] = {
            normalize_text(k): normalize_text(v) for k, v in third_map.items()
        }
    rl_down_map = raw.get("relegated_from_regionalliga_league", {})
    if isinstance(rl_down_map, dict):
        out["relegated_from_regionalliga_league"] = {
            normalize_text(k): normalize_text(v) for k, v in rl_down_map.items()
        }
    rule_text = raw.get("reform_rule")
    if isinstance(rule_text, str) and rule_text.strip():
        out["reform_rule"] = normalize_text(rule_text)
    for group_key in ("meisterrunde_teams", "abstiegsrunde_teams"):
        groups_raw = raw.get(group_key, {})
        groups_out: Dict[str, List[Dict[str, Any]]] = {}
        if isinstance(groups_raw, dict):
            for league_name, entries in groups_raw.items():
                norm_league = normalize_text(league_name)
                if not norm_league or not isinstance(entries, list):
                    continue
                normalized_entries: List[Dict[str, Any]] = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    item: Dict[str, Any] = {}
                    for key, value in entry.items():
                        if isinstance(value, str):
                            item[key] = normalize_text(value)
                        else:
                            item[key] = value
                    if normalize_text(item.get("team", "")):
                        normalized_entries.append(item)
                if normalized_entries:
                    groups_out[norm_league] = normalized_entries
        if groups_out:
            out[group_key] = groups_out
    return out


def build_team_origin_lookup(
    groups: Dict[str, List[Dict[str, Any]]],
    fallback_to_group: bool = False,
) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for group_name, entries in groups.items():
        norm_group = normalize_text(group_name)
        if not norm_group or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            team = normalize_text(entry.get("team", ""))
            if not team:
                continue
            origin = normalize_text(entry.get("rl_league", "")) or (
                norm_group if fallback_to_group else ""
            )
            if origin:
                lookup[team] = origin
    return lookup


def resolve_map_color_mode(
    variant: str,
    transitions: Dict,
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str], str, List[Tuple[str, str]]]:
    if variant == "bayern_meisterrunde":
        origin_lookup = build_team_origin_lookup(
            transitions.get("meisterrunde_teams", {})
        )
        legend_items = [
            ("Nord", "Nord"),
            ("West", "West"),
            ("Ost", "Ost"),
            ("Südwest", "Süd / Südwest"),
        ]
        return {}, origin_lookup, TARGET_LEAGUE_COLORS, "RL-Herkunft", legend_items
    if variant == "bayern_abstiegsrunde":
        origin_lookup = build_team_origin_lookup(
            transitions.get("abstiegsrunde_teams", {}),
            fallback_to_group=True,
        )
        legend_items = [
            ("Nord", "Nord"),
            ("Nordost", "Nordost"),
            ("West", "West"),
            ("Bayern", "Bayern"),
            ("Südwest", "Südwest"),
        ]
        return origin_lookup, {}, RL_ORIGIN_COLORS, "Liga", legend_items
    if variant == "current_regionalliga":
        legend_items = [
            ("Nord", "Nord"),
            ("Nordost", "Nordost"),
            ("West", "West"),
            ("Bayern", "Bayern"),
            ("Südwest", "Südwest"),
        ]
        return {}, {}, RL_ORIGIN_COLORS, "Liga", legend_items
    legend_items = [
        ("Nord", "Nord"),
        ("West", "West"),
        ("Ost", "Ost"),
        ("Südwest", "Süd / Südwest"),
    ]
    return {}, {}, TARGET_LEAGUE_COLORS, "Liga", legend_items


def build_legend_html(
    legend_items: List[Tuple[str, str]],
    league_colors: Dict[str, str],
    legend_title: str = "Liga",
) -> str:
    league_lines = []
    for key, label in legend_items:
        color = league_colors.get(key)
        if not color:
            continue
        league_lines.append(f'<span style="color:{color};">●</span> {label}<br>')
    league_markup = "".join(league_lines)
    return f"""
    <div style="
      position: fixed;
      bottom: 20px; left: 20px; z-index: 9999;
      max-width: 260px;
      background: rgba(255,255,255,0.96);
      border: 1px solid #d9e1eb;
      border-radius: 8px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.16);
      padding: 10px 12px;
      font-size: 13px;
      line-height: 1.35;">
      <b>Farben: {legend_title}</b><br>
      {league_markup}
      <hr style="border:0;border-top:1px solid #d9e1eb;margin:8px 0;">
      <span style="color:gray;">◯</span> Absteiger RL<br>
      <span style="color:#ffd700;">▲</span> Aufsteiger in 3. Liga<br>
      <span style="color:#2f2f2f;">□</span> Absteiger aus 3. Liga (nur Form)<br>
      <span style="color:#2f2f2f;">⬟</span> Aufsteiger aus Oberliga (nur Form)<br>
      <span style="color:#111;">◯</span> Unterschied STD/MATRIX
    </div>
    """


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
    from kompass import SEASON
    return load_verified_stadiums(SEASON, path)


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
    grounds = load_stadium_overrides(STADIUM_OVERRIDES_FILE)
    rows = []
    for _, row in df.iterrows():
        team = normalize_text(row["Verein"])
        ground = grounds.get(team)
        if ground is None:
            raise RuntimeError(f"Missing verified home ground: {team}")
        if haversine_km(float(row["lat"]), float(row["lon"]), ground["lat"], ground["lon"]) > 0.001:
            raise RuntimeError(f"Stale CSV coordinates for {team}; run kompass.py before kompass_report.py.")
        rows.append(dict(row, lat=ground["lat"], lon=ground["lon"],
                         stadium=ground["stadium"], stadium_address=ground.get("address", ""),
                         coord_source=ground["source"], stadium_source_url=ground["source_url"],
                         stadium_venue_source_url=ground["venue_source_url"],
                         stadium_verified_at=ground["verified_at"],
                         coordinate_precision=ground.get("coordinate_precision", "")))
    return pd.DataFrame(rows), {"total": len(rows), "stadium": len(rows), "fallback_club": 0}


def resolve_overlay_coords(df: pd.DataFrame, teams: List[str]) -> Tuple[Dict[str, Tuple[float, float]], List[str]]:
    grounds = load_stadium_overrides(STADIUM_OVERRIDES_FILE)
    coords = {}
    missing = []
    for team in teams:
        name = normalize_text(team)
        ground = grounds.get(name)
        if ground is None:
            missing.append(name)
        else:
            coords[name] = (ground["lat"], ground["lon"])
    return coords, missing


def build_map(
    df: pd.DataFrame,
    out_html: str,
    transitions: Dict,
    changed_teams: Optional[Dict[str, Tuple[str, str]]] = None,
    variant: str = "std",
    changed_left_label: str = "STD",
    changed_right_label: str = "MATRIX",
    as_of_note: str = "",
) -> List[str]:
    team_color_lookup, team_info_lookup, league_colors, info_label, legend_items = resolve_map_color_mode(
        variant, transitions
    )
    center_lat = float(df["lat"].mean())
    center_lon = float(df["lon"].mean())
    m = folium.Map(location=[center_lat, center_lon], zoom_start=6, tiles=None)
    if as_of_note:
        m.get_root().html.add_child(folium.Element(
            '<div style="position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:1000;'
            'max-width:70%;padding:8px 12px;background:white;border:1px solid #ccc;border-radius:6px;'
            f'font:13px sans-serif;text-align:center;">{escape(as_of_note)}</div>'
        ))
    folium.TileLayer(
        tiles="https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        name="OpenStreetMap DE",
    ).add_to(m)
    for _, row in df.iterrows():
        team = normalize_text(row["Verein"])
        liga = normalize_text(row["Liga"])
        color_key = team_color_lookup.get(team, liga)
        color = league_colors.get(color_key, "gray")
        info_value = team_info_lookup.get(team, "")
        stadium = normalize_text(row.get("stadium", ""))
        popup = f"{row['Verein']} ({liga})"
        if info_value and info_value != liga:
            popup += f"<br>{info_label}: {info_value}"
        if stadium:
            popup += f"<br>Stadion: {escape(stadium)}"
            for field, label in (("stadium_venue_source_url", "Heimspielstätte"), ("stadium_source_url", "Koordinaten")):
                if row.get(field):
                    popup += f'<br><a href="{escape(str(row[field]), quote=True)}" target="_blank" rel="noopener">Quelle: {label}</a>'
            if row.get("coordinate_precision") == "ground_complex":
                popup += "<br>Punkt innerhalb der Sportanlage"
            if row.get("stadium_verified_at"):
                popup += f'<br>Geprüft: {escape(str(row["stadium_verified_at"]))}'
        folium.CircleMarker(
            location=[float(row["lat"]), float(row["lon"])],
            radius=6,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.8,
            popup=popup,
            tooltip=(
                f"{row['Verein']} | {liga}"
                if not info_value or info_value == liga
                else f"{row['Verein']} | {liga} | {info_label}: {info_value}"
            ),
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

    third_liga_assignment = transitions.get("relegated_from_3liga_league", {})
    for team in transitions.get("relegated_from_3liga", []):
        t = normalize_text(team)
        if t not in overlay_coords:
            continue
        lat, lon = overlay_coords[t]
        assigned_league = normalize_text(third_liga_assignment.get(t, ""))
        suffix = f" -> RL {assigned_league}" if assigned_league else ""
        folium.RegularPolygonMarker(
            location=[lat, lon],
            number_of_sides=4,
            radius=10,
            color="#2f2f2f",
            fill_color="#ffffff",
            fill_opacity=0.0,
            tooltip=f"{t} | Absteiger aus 3. Liga{suffix}",
            popup=f"{t} (Absteiger aus 3. Liga{suffix})",
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

    legend_html = build_legend_html(legend_items, league_colors, info_label)
    m.get_root().html.add_child(folium.Element(legend_html))
    ensure_parent_dir(out_html)
    m.save(out_html)
    map_path = Path(out_html)
    map_path.write_text("\n".join(line.rstrip() for line in map_path.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    return unresolved


def compute_metrics(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    clubs_rows: List[Dict] = []
    league_rows: List[Dict] = []
    trips_rows: List[Dict] = []

    for liga, g in df.groupby("Liga", sort=True):
        records = g.to_dict("records")
        n = len(records)
        all_away_distances: List[float] = []
        longest_von, longest_nach, longest_d = "", "", 0.0

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
                if i < j:
                    trips_rows.append(
                        {
                            "Liga": liga,
                            "Von": club_i["Verein"],
                            "Nach": club_j["Verein"],
                            "Distanz_km": round(d, 2),
                        }
                    )
                    if d > longest_d:
                        longest_von, longest_nach, longest_d = club_i["Verein"], club_j["Verein"], d

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

        league_avg = sum(all_away_distances) / len(all_away_distances) if all_away_distances else 0.0
        league_rows.append(
            {
                "Liga": liga,
                "Teams": n,
                "Durchschnitt_Auswaertsreise_km": round(league_avg, 2),
                "Laengste_Reise_Von": longest_von,
                "Laengste_Reise_Nach": longest_nach,
                "Laengste_Reise_km": round(longest_d, 2),
            }
        )

    club_df = pd.DataFrame(clubs_rows).sort_values(["Liga", "Verein"])
    league_df = pd.DataFrame(league_rows).sort_values("Liga")
    trips_df = pd.DataFrame(trips_rows).sort_values("Distanz_km", ascending=False)

    # Cross-Liga: kürzeste Paare aus verschiedenen Ligen
    all_records = df.to_dict("records")
    m = len(all_records)
    cross_rows: List[Dict] = []
    for i in range(m):
        for j in range(i + 1, m):
            if all_records[i]["Liga"] == all_records[j]["Liga"]:
                continue
            d = haversine_km(
                float(all_records[i]["lat"]),
                float(all_records[i]["lon"]),
                float(all_records[j]["lat"]),
                float(all_records[j]["lon"]),
            )
            cross_rows.append(
                {
                    "Liga_A": all_records[i]["Liga"],
                    "Liga_B": all_records[j]["Liga"],
                    "Von": all_records[i]["Verein"],
                    "Nach": all_records[j]["Verein"],
                    "Distanz_km": round(d, 2),
                }
            )
    cross_trips_df = pd.DataFrame(cross_rows).sort_values("Distanz_km", ascending=True) if cross_rows else pd.DataFrame(columns=["Liga_A", "Liga_B", "Von", "Nach", "Distanz_km"])

    return club_df, league_df, trips_df, cross_trips_df


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
    overrides = load_stadium_overrides(STADIUM_OVERRIDES_FILE)

    teams: List[Dict[str, Any]] = []
    for _, row in df_map.sort_values(["Liga", "Verein"]).iterrows():
        team = normalize_text(row["Verein"])
        source_from_row = normalize_text(row.get("coord_source", ""))
        source_data = overrides.get(team) or {}
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
                "venue_source_url": source_data.get("venue_source_url", ""),
                "verified_season": source_data.get("verified_season", ""),
                "verified_at": source_data.get("verified_at", ""),
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
    cross_trips_df: pd.DataFrame,
    rank_info: Optional[Dict[str, Any]] = None,
    show_club_list: bool = True,
    note: str = "",
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
                "route": f"{normalize_text(row['Von'])} \u2194 {normalize_text(row['Nach'])}",
                "km": float(row["Distanz_km"]),
            }
        )

    top_close_cross_trips: List[Dict[str, Any]] = []
    for idx, (_, row) in enumerate(cross_trips_df.head(5).iterrows(), start=1):
        top_close_cross_trips.append(
            {
                "index": idx,
                "route": f"{normalize_text(row['Von'])} \u2194 {normalize_text(row['Nach'])}",
                "liga_a": normalize_text(row["Liga_A"]),
                "liga_b": normalize_text(row["Liga_B"]),
                "km": float(row["Distanz_km"]),
            }
        )

    club_lookup: Dict[str, Dict[str, Any]] = {}
    for _, row in club_df.iterrows():
        team = normalize_text(row["Verein"])
        club_lookup[team] = {
            "liga": normalize_text(row["Liga"]),
            "avg_km": float(row["Durchschnitt_Auswaerts_km"]),
            "season_km": float(row["Saison_Auswaerts_km"]),
            "longest_km": float(row["Laengste_Einzelreise_km"]),
            "longest_opponent": "",
        }

    for _, row in trips_df.iterrows():
        team_a = normalize_text(row["Von"])
        team_b = normalize_text(row["Nach"])
        km = float(row["Distanz_km"])
        if team_a in club_lookup and not club_lookup[team_a]["longest_opponent"]:
            club_lookup[team_a]["longest_opponent"] = team_b
            club_lookup[team_a]["longest_km"] = km
        if team_b in club_lookup and not club_lookup[team_b]["longest_opponent"]:
            club_lookup[team_b]["longest_opponent"] = team_a
            club_lookup[team_b]["longest_km"] = km

    closest_cross_by_club: Dict[str, Dict[str, Any]] = {}
    for _, row in cross_trips_df.iterrows():
        team_a = normalize_text(row["Von"])
        team_b = normalize_text(row["Nach"])
        item_a = {
            "opponent": team_b,
            "own_liga": normalize_text(row["Liga_A"]),
            "opponent_liga": normalize_text(row["Liga_B"]),
            "km": float(row["Distanz_km"]),
        }
        item_b = {
            "opponent": team_a,
            "own_liga": normalize_text(row["Liga_B"]),
            "opponent_liga": normalize_text(row["Liga_A"]),
            "km": float(row["Distanz_km"]),
        }
        closest_cross_by_club.setdefault(team_a, item_a)
        closest_cross_by_club.setdefault(team_b, item_b)

    out: Dict[str, Any] = {
        "id": variant_id,
        "title": title,
        "map_html": map_html,
        "overall_avg_km": float(club_df["Durchschnitt_Auswaerts_km"].mean()),
        "team_count": int(len(df)),
        "league_count": int(df["Liga"].nunique()),
        "longest_trip_route": top_trips[0]["route"] if top_trips else "",
        "longest_trip_km": float(top_trips[0]["km"]) if top_trips else 0.0,
        "leagues": leagues,
        "top_trips": top_trips,
        "top_close_cross_trips": top_close_cross_trips,
        "club_lookup": club_lookup,
        "closest_cross_by_club": closest_cross_by_club,
        "clubs_by_league": clubs_by_league,
        "show_club_list": bool(show_club_list),
        "note": normalize_text(note),
    }
    if rank_info:
        out["rank"] = int(rank_info.get("rank", 0))
        out["rank_label"] = normalize_text(rank_info.get("rank_label", ""))
        out["score_avg_away_km"] = float(rank_info.get("score_avg_away_km", 0.0))
        out["gap_to_best_km"] = float(rank_info.get("gap_to_best_km", 0.0))
    return out


def _variant_by_id(variants: List[Dict[str, Any]], variant_id: str) -> Optional[Dict[str, Any]]:
    for variant in variants:
        if variant.get("id") == variant_id:
            return variant
    return None


def _short_variant_label(variant: Dict[str, Any]) -> str:
    mapping = {
        "rank1": "Matrix",
        "wish_best": "Wunschliste",
        "regionenmodell": "Regionenmodell",
        "current_regionalliga": "Aktuelle RL",
        "bayern_meisterrunde": "Bayern Meister",
        "bayern_abstiegsrunde": "Bayern Abstieg",
        "worst": "Worst-Case",
    }
    return mapping.get(str(variant.get("id", "")), normalize_text(variant.get("title", "")))


def _format_metric_km(value: Any) -> str:
    try:
        return f"{float(value):.2f} km"
    except Exception:
        return "-"


def _assignment_lookup(variant: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    groups = variant.get("clubs_by_league", {})
    if not isinstance(groups, dict):
        return out
    for league_name, teams in groups.items():
        if not isinstance(teams, list):
            continue
        for team in teams:
            out[normalize_text(team)] = normalize_text(league_name)
    return out


def _changed_assignments_count(left: Dict[str, Any], right: Dict[str, Any]) -> int:
    left_lookup = _assignment_lookup(left)
    right_lookup = _assignment_lookup(right)
    common = set(left_lookup) & set(right_lookup)
    return sum(1 for team in common if left_lookup[team] != right_lookup[team])


def build_model_cards(variants: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    rank1 = _variant_by_id(variants, "rank1")
    wish = _variant_by_id(variants, "wish_best")
    region = _variant_by_id(variants, "regionenmodell")
    current_rl = _variant_by_id(variants, "current_regionalliga")
    bayern_meister = _variant_by_id(variants, "bayern_meisterrunde")

    cards: List[Dict[str, str]] = []
    if rank1:
        cards.append(
            {
                "title": "Matrix",
                "target_variant": "rank1",
                "avg_label": _format_metric_km(rank1.get("overall_avg_km")),
                "longest_label": _format_metric_km(rank1.get("longest_trip_km")),
                "best_for": "kürzeste 4x20-Distanzen",
            }
        )
    if wish:
        cards.append(
            {
                "title": "Wunschliste",
                "target_variant": "wish_best",
                "avg_label": _format_metric_km(wish.get("overall_avg_km")),
                "longest_label": _format_metric_km(wish.get("longest_trip_km")),
                "best_for": "möglichst viele Nähe-Duelle",
            }
        )
    if region:
        cards.append(
            {
                "title": "Regionenmodell",
                "target_variant": "regionenmodell",
                "avg_label": _format_metric_km(region.get("overall_avg_km")),
                "longest_label": _format_metric_km(region.get("longest_trip_km")),
                "best_for": "stabile Regionalstruktur",
            }
        )
    if current_rl:
        cards.append(
            {
                "title": "Aktuelle RL",
                "target_variant": "current_regionalliga",
                "avg_label": _format_metric_km(current_rl.get("overall_avg_km")),
                "longest_label": _format_metric_km(current_rl.get("longest_trip_km")),
                "best_for": "5 Staffeln nach Auf-/Abstieg",
            }
        )
    if bayern_meister:
        cards.append(
            {
                "title": "Bayern-Modell",
                "target_variant": "bayern_meisterrunde",
                "avg_label": _format_metric_km(bayern_meister.get("overall_avg_km")),
                "longest_label": _format_metric_km(bayern_meister.get("longest_trip_km")),
                "best_for": "Meisterrunde nach Vorrunden-Split",
            }
        )
    return cards


def build_chart_groups(rank1_df: pd.DataFrame, variants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chart_variant_ids = [
        "rank1",
        "wish_best",
        "regionenmodell",
        "bayern_meisterrunde",
    ]
    chart_variants = [
        v for vid in chart_variant_ids for v in [_variant_by_id(variants, vid)] if v is not None
    ]

    avg_items = [
        {
            "label": _short_variant_label(v),
            "value": float(v.get("overall_avg_km", 0.0)),
            "detail": _format_metric_km(v.get("overall_avg_km")),
            "target_variant": str(v.get("id", "")),
        }
        for v in chart_variants
    ]
    longest_items = [
        {
            "label": _short_variant_label(v),
            "value": float(v.get("longest_trip_km", 0.0)),
            "detail": _format_metric_km(v.get("longest_trip_km")),
            "target_variant": str(v.get("id", "")),
        }
        for v in chart_variants
    ]

    coverage_items = build_wish_coverage_items(rank1_df, variants)
    return [
        {"title": "Ø Auswärts-km", "unit": "km", "items": avg_items},
        {"title": "Längste Reise", "unit": "km", "items": longest_items},
        {"title": "Anteil der 19 nächsten Gegner", "unit": "%", "items": coverage_items},
    ]


def build_wish_coverage_items(rank1_df: pd.DataFrame, variants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records = []
    for row in rank1_df.to_dict("records"):
        records.append(
            {
                "team": normalize_text(row["Verein"]),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
            }
        )
    base_teams = {r["team"] for r in records}
    if not records:
        return []

    wish_table: Dict[str, List[str]] = {}
    for a in records:
        distances = []
        for b in records:
            if a["team"] == b["team"]:
                continue
            d = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            distances.append((d, b["team"]))
        distances.sort(key=lambda item: item[0])
        wish_table[a["team"]] = [team for _, team in distances[: TEAMS_PER_LEAGUE - 1]]

    max_score = len(base_teams) * (TEAMS_PER_LEAGUE - 1)
    items: List[Dict[str, Any]] = []
    for variant in variants:
        if variant.get("id") in {"current_regionalliga", "bayern_abstiegsrunde", "worst"}:
            continue
        assignment = _assignment_lookup(variant)
        if set(assignment) != base_teams:
            continue
        score = 0
        for team, wishes in wish_table.items():
            league = assignment.get(team)
            score += sum(1 for wish in wishes if assignment.get(wish) == league)
        pct = (score / max_score * 100.0) if max_score else 0.0
        items.append(
            {
                "label": _short_variant_label(variant),
                "value": pct,
                "detail": f"{score}/{max_score}",
                "target_variant": str(variant.get("id", "")),
            }
        )
    return items


def build_key_takeaways(variants: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    rank1 = _variant_by_id(variants, "rank1")
    wish = _variant_by_id(variants, "wish_best")
    region = _variant_by_id(variants, "regionenmodell")
    current_rl = _variant_by_id(variants, "current_regionalliga")
    bayern_meister = _variant_by_id(variants, "bayern_meisterrunde")
    bayern_abstieg = _variant_by_id(variants, "bayern_abstiegsrunde")
    worst = _variant_by_id(variants, "worst")

    if rank1 and wish:
        changed = _changed_assignments_count(rank1, wish)
        if changed == 0:
            out.append("Matrix und Wunschlisten-Optimierung liefern aktuell dieselbe 4x20-Aufteilung.")
        else:
            out.append(f"Wunschlisten-Optimierung verschiebt {changed} Teams gegenüber der Matrix-Lösung.")
    if rank1 and region:
        diff = float(region.get("overall_avg_km", 0.0)) - float(rank1.get("overall_avg_km", 0.0))
        out.append(f"Das Regionenmodell ist strukturell stabiler, liegt aber bei Ø {diff:+.2f} km gegenüber Matrix.")
    if bayern_meister:
        out.append("Das Bayern-Modell bleibt oben als Meisterrunde sichtbar; die Abstiegsrunde ist wegen variabler Ligagrößen ein Benchmark.")
    if current_rl:
        out.append("Die aktuelle RL-Karte zeigt die 5 Herkunftsstaffeln des Reform-Pools nach Auf-/Abstieg inklusive 3.-Liga-Zuordnung.")
    if worst and rank1:
        diff = float(worst.get("overall_avg_km", 0.0)) - float(rank1.get("overall_avg_km", 0.0))
        out.append(f"Benchmark: Der Worst-Case liegt bei Ø {diff:+.2f} km gegenüber Matrix.")
    if bayern_abstieg:
        out.append("Benchmark: Die Bayern-Abstiegsrunde zeigt die Wege innerhalb der bisherigen Regionalligen nach dem Split.")
    return out


def render_recalculation_history(report: Dict[str, Any]) -> str:
    title = '<section class="card" id="projection-history"><h2>Archiv einzelner Berechnungsläufe</h2>'
    if not report.get("available"):
        message = (
            "Für die angezeigte Lösung liegt noch kein passender Verlauf vor."
            if report.get("reason") == "stale" else
            "Der erste erfolgreiche Berechnungslauf legt den Ausgangsstand für den Verlauf an."
        )
        return title + f"<p>{message} Ab dem nächsten Lauf werden Änderungen verglichen.</p></section>"

    def timestamp(value):
        return f'<time class="history-time" datetime="{escape(value)}">{escape(value)}</time>'

    def table(headers, rows, date_column=False):
        head = "".join(f"<th>{escape(header)}</th>" for header in headers)
        body = "".join(
            "<tr>" + "".join(
                f"<td>{timestamp(str(value)) if date_column and index == 0 else escape(str(value))}</td>"
                for index, value in enumerate(row)
            ) + "</tr>" for row in rows
        )
        return f'<div class="history-scroll"><table class="league-table history-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'

    intro = (
        f'<p>Kompassmodell (Rank 1), Quellsaison {escape(report["source_season"])} → '
        f'Reform {escape(report["target_season"])}. Aufzeichnung seit {timestamp(report["baseline_at"])}.</p>'
    )
    latest = report.get("latest")
    if latest is None:
        return title + intro + (
            "<p>Erster gespeicherter Lauf: Ausgangsstand festgehalten. "
            "Wechsel lassen sich ab der nächsten erfolgreichen Neuberechnung zählen; frühere Wochen sind nicht erfasst.</p></section>"
        )
    percent = str(latest["switch_percent"]).replace(".", ",") if latest["switch_percent"] is not None else "–"
    cards = [
        ("Gespeicherte Läufe", report["snapshot_count"]),
        ("Wechsel seit letztem Lauf", f'{latest["switch_count"]} / {latest["shared_count"]} ({percent} %)'),
        ("Wechsel insgesamt", report["switch_total"]),
        ("Veränderte Aufteilungen", f'{report["allocation_changes"]} / {report["comparison_count"]} Vergleiche'),
    ]
    summary = '<div class="meta">' + "".join(
        f"<div><strong>{escape(label)}</strong>{escape(str(value))}</div>" for label, value in cards
    ) + "</div>"
    latest_text = (
        f'<p>Letzter Vergleich: {timestamp(latest["previous_at"])} → {timestamp(latest["captured_at"])}. '
        f'Unverändert zugeordnet: {latest["shared_count"] - latest["switch_count"]}; '
        f'neu im Pool: {len(latest["entered"])}; aus dem Pool: {len(latest["left"])}.</p>'
    )
    notes = (
        "<p>Wechsel zählen nur für Vereine, die in beiden Läufen im Pool stehen. "
        "Staffeln werden nach größter Mitgliederüberschneidung zugeordnet; reine Umbenennungen zählen nicht als Wechsel. "
        "Auch bei gleichen Tabellen kann eine andere gefundene Optimierung die Aufteilung ändern.</p>"
    )
    moves = table(["Verein", "Vorher", "Nachher"], [
        [row["team"], row["from_league"], row["to_league"] + (
            f' (zuvor {row["to_previous_league"]})' if row["to_league"] != row["to_previous_league"] else ""
        )] for row in latest["switched"]
    ]) if latest["switched"] else "<p>Keine Staffelwechsel im letzten Vergleich.</p>"
    for key, label in (("entered", "Neu im Pool"), ("left", "Aus dem Pool")):
        if latest[key]:
            moves += f'<p><strong>{label}:</strong> {escape(", ".join(latest[key]))}</p>'
    leagues = table(["Staffel", "Vergleichsstaffel zuvor", "Zugänge", "Abgänge"], [
        [row["league"], row["previous_league"], row["added"], row["removed"]]
        for row in latest["league_changes"]
    ])
    comparison_rows = []
    for row in reversed(report["comparisons"]):
        status = {True: "Tabellen geändert", False: "Tabellen gleich", None: "Tabellenstand unbekannt"}[row["tables_changed"]]
        if row["settings_changed"]:
            status += "; Einstellungen geändert"
        comparison_rows.append([row["captured_at"], status, row["shared_count"], row["switch_count"],
                                len(row["entered"]), len(row["left"])])
    comparisons = table(["Berechnung", "Datenvergleich", "Gemeinsame Vereine", "Wechsel", "Neu", "Raus"],
                        comparison_rows, date_column=True)
    teams = table(["Verein", "Staffel aktuell", "Wechsel", "Läufe im Pool", "Pool-Eintritte", "Pool-Austritte"], [
        [row["team"], row["current_league"], row["switch_count"], row["appearances"], row["entries"], row["exits"]]
        for row in report["teams"]
    ])
    details = "".join(f'<details><summary>{label}</summary>{content}</details>' for label, content in (
        ("Änderungen beim letzten Lauf", moves + leagues),
        ("Verlauf der Neuberechnungen", comparisons), ("Wechsel je Verein", teams),
    ))
    return title + intro + summary + latest_text + notes + details + "</section>"


def render_weekly_history(payload: Dict[str, Any]) -> str:
    if not payload:
        return ('<section class="card" id="weekly-history"><h2>Stabilität der Prognose</h2>'
                '<p>Sobald alle 20 Quellligen gestartet sind, beginnt der Vergleich abgeschlossener Sonntage. '
                'Der nächste reguläre Berechnungslauf holt fehlende Wochen nach.</p></section>')
    snapshots, summary = payload["snapshots"], payload["summary"]
    dates = [snapshot["as_of"] for snapshot in snapshots]
    latest = summary["latest"]
    stable = f'{100 - latest["switch_percent"]:.1f} %'.replace(".", ",") if latest and latest["switch_percent"] is not None else "–"
    metrics = render_stat_cards([
        ("Zuordnung beibehalten", stable, "der Vereine in beiden Wochen"),
        ("Staffelwechsel", latest["switch_count"] if latest else "–", f'von {latest["shared_count"]} gemeinsamen Vereinen' if latest else "Erste Woche ist der Ausgangsstand"),
        ("Neu im Pool", len(latest["entered"]) if latest else "–", "gegenüber dem vorherigen Sonntag"),
        ("Wochenstände", len(snapshots), f'seit {format_week_date(dates[0])}'),
    ])
    rows = []
    chart = []
    maximum = max([change["switch_count"] for change in summary["comparisons"]] + [1])
    for index, snapshot in enumerate(snapshots):
        change = summary["comparisons"][index - 1] if index else None
        values = ([change["switch_count"], len(change["entered"]), len(change["left"])] if change else ["–", "–", "–"])
        cells = "".join(f"<td>{value}</td>" for value in values)
        rows.append(f'<tr><td><button type="button" class="weekly-date" data-week="{escape(snapshot["as_of"])}">'
                    f'{format_week_date(snapshot["as_of"])}</button></td>{cells}<td>{snapshot["score_avg_away_km"]:.2f} km</td></tr>')
        count = change["switch_count"] if change else 0
        title = f'{format_week_date(snapshot["as_of"])}: {count} Staffelwechsel' if change else "Ausgangsstand"
        chart.append(f'<button type="button" class="week-bar" data-week="{snapshot["as_of"]}" '
                     f'aria-label="{title}" title="{title}"><strong>{count if change else "–"}</strong>'
                     f'<span class="week-bar-track"><span style="height:{max(3, count / maximum * 100):.1f}%"></span></span>'
                     f'<span>{format_week_date(snapshot["as_of"])[:5]}</span></button>')
    options = "".join(f'<option value="{value}"{" selected" if value == dates[-1] else ""}>Sonntag, {format_week_date(value)}</option>' for value in dates)
    leagues = "".join(f'<option value="{escape(table["name"])}">{escape(table["name"])}</option>' for table in snapshots[0]["tables"])
    team_rows = "".join(f'<tr><td>{escape(row["team"])}</td><td>{row["switch_count"]}</td>'
                        f'<td>{row["entries"]}</td><td>{row["exits"]}</td></tr>' for row in summary["teams"])
    return (
        '<section id="weekly-history"><div class="section-heading"><div><p class="eyebrow">WOCHENVERGLEICH</p>'
        '<h2>Stabilität der Prognose</h2></div>'
        f'<span class="status-pill">Bis Sonntag, {format_week_date(dates[-1])}</span></div>'
        '<p class="section-intro">Verglichen werden rekonstruierte Tabellenstände abgeschlossener Sonntage, jeweils 23:59 Uhr in Berlin. '
        'Fehlende Wochen werden beim nächsten Lauf nachgeholt – auch wenn du erst unter der Woche startest.</p>'
        + metrics + '<div class="card"><div class="section-heading"><div><h3>Staffelwechsel im Verlauf</h3>'
        '<p>Ein Klick auf eine Woche öffnet ihren Stand.</p></div>'
        f'<span class="status-pill">{summary["switch_total"]} Wechsel insgesamt</span></div>'
        '<div class="weekly-chart" aria-label="Staffelwechsel pro Woche">' + "".join(chart) + '</div>'
        '<p class="caption">Gezählt werden Vereine, die in beiden Wochen im Pool sind. Neue und ausgeschiedene Vereine zählen separat.</p>'
        '<details><summary>Alle Wochen als Tabelle</summary><div class="history-scroll"><table class="league-table history-table"><thead><tr><th>Sonntag</th>'
        '<th>Staffelwechsel</th><th>Neu im Pool</th><th>Aus dem Pool</th><th>Ø Auswärtsfahrt</th></tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody></table></div></details></div>'
        '<section class="card" id="weekly-explorer"><div class="weekly-controls">'
        '<button type="button" class="step-button" id="weekly-prev" aria-label="Vorheriger Sonntag">Zurück</button>'
        '<label>Wochenstand <select id="weekly-date">' + options + '</select></label>'
        '<button type="button" class="step-button" id="weekly-next" aria-label="Nächster Sonntag">Weiter</button></div>'
        '<p id="weekly-description" aria-live="polite"></p>'
        '<div class="switch" aria-label="Ansicht der Woche"><button type="button" data-week-panel="map" class="active">Karte</button>'
        '<button type="button" data-week-panel="source">Quelltabellen</button>'
        '<button type="button" data-week-panel="assignment">80-Team-Zuordnung</button></div>'
        '<div data-week-content="map"><p><a id="weekly-map-link" href="#" target="_blank" rel="noopener">Wochenkarte öffnen</a></p>'
        '<iframe id="weekly-map" class="map-frame" src="" loading="lazy" title="Rekonstruierte Wochenkarte"></iframe></div>'
        '<div data-week-content="source" hidden><div class="weekly-controls"><label>Quellliga <select id="weekly-league">' + leagues + '</select></label>'
        '<a id="weekly-source-link" href="#" target="_blank" rel="noopener">FuPa-Ergebnisquelle</a></div>'
        '<div class="history-scroll table-window"><table class="league-table history-table" id="weekly-source-table"></table></div></div>'
        '<div data-week-content="assignment" hidden><div class="history-scroll table-window"><table class="league-table history-table" id="weekly-assignment-table"></table></div></div>'
        '<div class="weekly-changes" id="weekly-changes"></div></section>'
        '<details class="details-section"><summary>Wechsel je Verein über alle Wochen</summary><div class="details-body history-scroll"><table class="league-table history-table">'
        '<thead><tr><th>Verein</th><th>Staffelwechsel</th><th>Pool-Eintritte</th><th>Pool-Austritte</th></tr></thead><tbody>'
        + team_rows + '</tbody></table></div></details>'
        '<details class="details-section"><summary>Datengrundlage und Vergleichsmethode</summary><div class="details-body">'
        f'<p>Beginn am {format_week_date(dates[0])}, nachdem alle 20 Quellligen mindestens ein Spiel abgeschlossen hatten. '
        f'Einheitliches Suchprofil: {payload["search_profile"]["phase1_runs"]} Startläufe je Woche mit gleichen Startwerten.</p>'
        f'<p>{escape(payload["valuation_note"])}</p>'
        '<p>Staffeln werden nach größter Mitgliederüberschneidung verglichen. Vollständig gleiche Tabellenwerte '
        'werden alphabetisch geordnet und markiert. Die Live-Projektion kann ein anderes Suchbudget verwenden.</p>'
        '</div></details></section>'
    )


def format_week_date(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%d.%m.%Y")


def render_stat_cards(cards) -> str:
    return '<div class="summary-grid">' + "".join(
        f'<div class="summary-card"><span>{escape(str(label))}</span><strong>{escape(str(value))}</strong>'
        f'<small>{escape(str(note))}</small></div>' for label, value, note in cards
    ) + '</div>'


def render_overview(page_data: Dict[str, Any]) -> str:
    variant = next((value for value in page_data.get("variants", []) if value["id"] == "rank1"), {})
    weekly = page_data.get("weekly_history", {})
    latest = weekly.get("summary", {}).get("latest")
    date_label = format_week_date(weekly["snapshots"][-1]["as_of"]) if weekly else "Noch kein Wochenstand"
    cards = render_stat_cards([
        ("Reformmodell", "4 × 20", "Vier Staffeln mit je 20 Vereinen"),
        ("Ø Auswärtsfahrt", f'{variant["overall_avg_km"]:.1f} km'.replace(".", ",") if variant else "–", "Beste gefundene Live-Aufteilung"),
        ("Letzter Wochenwechsel", f'{latest["switch_count"]} / {latest["shared_count"]}' if latest else "–", "Staffelwechsel / gemeinsame Vereine"),
        ("Wochenvergleich bis", date_label, "Berechneter Sonntagsstand"),
    ])
    return cards + ('<div class="weekly-callout"><div><strong>Wie stabil bleibt die Aufteilung?</strong>'
                    '<p>Der Wochenverlauf vergleicht feste Sonntagsstände. Dein Ausführungstag spielt dafür keine Rolle.</p></div>'
                    '<a class="button-link" href="#weekly">Wochenverlauf ansehen</a></div>')


def create_index_html(page_data: Dict[str, Any], out_html: str) -> None:
    payload = json.dumps(page_data, ensure_ascii=False).replace("<", "\\u003c")
    html = """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kompass-Regionalliga 4x20</title>
  <style>
    :root {
      --bg: #f3f5f4;
      --card: #ffffff;
      --text: #182e30;
      --muted: #526667;
      --accent: #146454;
      --border: #dce5e1;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Tahoma, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
    }
    main {
      max-width: 1280px;
      margin: 0 auto;
      padding: 40px 28px 36px;
    }
    h1, h2, h3 {
      margin: 0 0 10px;
      line-height: 1.2;
    }
    h1 { font-size: clamp(2rem, 4vw, 3.2rem); letter-spacing: -0.045em; }
    h2 { font-size: 1.45rem; letter-spacing: -0.025em; }
    h3 { font-size: 1.05rem; }
    p { margin: 0 0 14px; color: var(--muted); }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 24px;
      margin-bottom: 20px;
      box-shadow: 0 3px 16px #182e3004;
    }
    .score-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    .score-card,
    .model-item,
    .chart-row {
      font: inherit;
      color: inherit;
    }
    .score-card {
      width: 100%;
      text-align: left;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      background: #fff;
      cursor: pointer;
    }
    .score-card.active,
    .model-item.active {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px #14645418;
    }
    .score-card h3 {
      font-size: 1rem;
      margin-bottom: 8px;
    }
    .score-card .best-for {
      min-height: 2.6em;
      margin-bottom: 10px;
    }
    .metric-row {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      border-top: 1px solid var(--border);
      padding-top: 7px;
      margin-top: 7px;
      color: var(--muted);
      font-size: 0.9rem;
    }
    .metric-row strong {
      color: var(--text);
      text-align: right;
    }
    .map-frame {
      width: 100%;
      height: 65vh;
      min-height: 440px;
      max-height: 760px;
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
    .switch-label {
      align-self: center;
      color: var(--muted);
      font-size: 0.86rem;
      margin-left: 4px;
    }
    .switch button.benchmark {
      color: var(--muted);
      border-style: dashed;
    }
    .switch button.benchmark.active {
      color: #fff;
      border-style: solid;
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
    .model-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .model-item {
      width: 100%;
      text-align: left;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      background: #fff;
      cursor: pointer;
    }
    .model-item h3 {
      margin-bottom: 8px;
      font-size: 1rem;
    }
    .model-item p:last-child {
      margin-bottom: 0;
    }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr));
      gap: 12px;
    }
    .chart-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
      gap: 12px;
    }
    .chart-row {
      width: 100%;
      display: grid;
      grid-template-columns: 104px 1fr 74px;
      gap: 8px;
      align-items: center;
      border: 0;
      background: transparent;
      padding: 5px 0;
      text-align: left;
      cursor: pointer;
      color: var(--muted);
    }
    .chart-row.active {
      color: var(--text);
      font-weight: 600;
    }
    .bar-track {
      height: 9px;
      border-radius: 999px;
      background: #e7edf5;
      overflow: hidden;
    }
    .bar-fill {
      height: 100%;
      border-radius: inherit;
      background: var(--accent);
    }
    .takeaways ul {
      margin: 0;
      padding-left: 18px;
    }
    .takeaways li {
      margin-bottom: 6px;
      color: var(--muted);
    }
    .club-search {
      display: grid;
      grid-template-columns: minmax(220px, 360px) 1fr;
      gap: 12px;
      align-items: start;
    }
    .club-search input {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      font: inherit;
      color: var(--text);
      background: #fff;
    }
    .club-result {
      color: var(--muted);
    }
    .club-result h3 {
      color: var(--text);
      margin-bottom: 6px;
    }
    .club-result table {
      margin-top: 8px;
    }
    .clubs-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
      gap: 12px;
    }
    .details-section {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      margin-top: 14px;
    }
    .details-section > summary {
      cursor: pointer;
      padding: 14px;
      font-weight: 600;
      color: var(--text);
    }
    .details-section[open] > summary {
      border-bottom: 1px solid var(--border);
    }
    .details-body {
      padding: 0 14px 14px;
    }
    .details-body h2 {
      margin-top: 18px;
    }
    .league-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.94rem;
    }
    .league-table th,
    .league-table td {
      border-bottom: 1px solid var(--border);
      padding: 10px 12px;
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
    .history-scroll { overflow-x: auto; margin: 10px 0 16px; }
    .history-table td:first-child,
    .history-table th:first-child { width: auto; min-width: 170px; }
    #projection-history details { margin-top: 12px; }
    #projection-history summary { cursor: pointer; font-weight: 600; }
    #projection-history .meta { margin-bottom: 14px; }
    #weekly-history details { margin-top: 12px; }
    #weekly-history summary { cursor: pointer; font-weight: 600; }
    #weekly-history .meta { margin-bottom: 14px; }
    .weekly-controls { display: flex; flex-wrap: wrap; gap: 18px; margin: 14px 0; }
    .weekly-controls select { display: block; padding: 9px 12px; font: inherit; max-width: 100%; border: 1px solid var(--border); border-radius: 9px; background: white; color: var(--text); }
    .weekly-date { border: 0; background: none; color: var(--accent); cursor: pointer; font: inherit; padding: 0; }
    .weekly-picked { background: #edf5f1; }
    [hidden] { display: none !important; }
    html { scroll-behavior: smooth; scroll-padding-top: 88px; }
    button, input, select, a { -webkit-tap-highlight-color: transparent; }
    button:focus-visible, input:focus-visible, select:focus-visible, a:focus-visible, summary:focus-visible {
      outline: 3px solid #d28c40; outline-offset: 3px;
    }
    button { touch-action: manipulation; }
    .page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 28px; margin-bottom: 28px; }
    .page-header #subtitle { max-width: 680px; margin: 12px 0 0; }
    .eyebrow { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.14em; color: var(--accent); margin-bottom: 10px; }
    .season-badge { border-left: 3px solid var(--accent); padding: 8px 0 8px 18px; white-space: nowrap; }
    .season-badge strong { display: block; font-size: 1.15rem; }
    .season-badge small { color: var(--muted); }
    .page-nav { position: sticky; top: 10px; z-index: 1001; display: flex; gap: 5px; width: fit-content; max-width: 100%; margin: 0 0 28px; padding: 5px; border: 1px solid var(--border); border-radius: 12px; background: #fffffff5; box-shadow: 0 5px 20px #182e3008; }
    .page-nav a { padding: 9px 20px; border-radius: 8px; color: var(--muted); font-weight: 600; font-size: 0.9rem; white-space: nowrap; }
    .page-nav a[aria-current="page"] { background: var(--text); color: white; }
    .page-nav a:hover { text-decoration: none; background: #eaf0ed; }
    .page-nav a[aria-current="page"]:hover { background: var(--text); }
    .section-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 18px; }
    .section-heading h2, .section-heading h3, .section-heading p { margin-bottom: 0; }
    .section-heading .eyebrow { margin-bottom: 6px; }
    .section-intro { max-width: 800px; margin-bottom: 24px; }
    .status-pill { display: inline-block; border-radius: 7px; padding: 5px 10px; background: #e8f1ed; color: var(--accent); font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
    .summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 22px; }
    .summary-card { display: flex; flex-direction: column; gap: 9px; background: white; border: 1px solid var(--border); border-radius: 14px; padding: 21px; }
    .summary-card > span { color: var(--muted); font-size: 0.82rem; font-weight: 600; }
    .summary-card > strong { font-size: clamp(1.4rem, 2.4vw, 2rem); line-height: 1.2; letter-spacing: -0.04em; font-variant-numeric: tabular-nums; }
    .summary-card > small { color: var(--muted); font-size: 0.76rem; margin-top: auto; }
    .weekly-callout { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 20px 24px; background: #e8f0ec; border-radius: 14px; margin-bottom: 28px; }
    .weekly-callout p { margin: 3px 0 0; font-size: 0.88rem; }
    .button-link, .step-button { display: inline-block; padding: 9px 14px; border: 1px solid var(--border); border-radius: 9px; background: white; color: var(--accent); font: inherit; font-weight: 600; cursor: pointer; white-space: nowrap; }
    .button-link:hover, .step-button:hover { background: #f4f8f5; text-decoration: none; }
    .step-button:disabled { opacity: 0.4; cursor: default; }
    .caption { font-size: 0.82rem; margin-top: 12px; }
    .weekly-chart { display: flex; align-items: stretch; gap: 8px; overflow-x: auto; padding: 12px 0; }
    .week-bar { flex: 1 0 62px; display: flex; flex-direction: column; align-items: center; gap: 8px; border: 1px solid transparent; border-radius: 10px; padding: 8px; background: transparent; color: var(--muted); font: inherit; font-size: 0.78rem; cursor: pointer; }
    .week-bar strong { font-size: 1rem; color: var(--text); }
    .week-bar:hover, .week-bar[aria-pressed="true"] { border-color: var(--border); background: #eff5f1; }
    .week-bar-track { height: 110px; width: 28px; display: flex; align-items: end; border-radius: 6px; background: #edf2ef; }
    .week-bar-track > span { width: 100%; border-radius: 5px; background: #70a695; min-height: 3px; }
    .week-bar[aria-pressed="true"] .week-bar-track > span { background: var(--accent); }
    .weekly-controls { align-items: end; gap: 12px; }
    .weekly-controls label { color: var(--muted); font-size: 0.8rem; font-weight: 600; min-width: 0; }
    #weekly-source-table td:first-child, #weekly-source-table th:first-child { min-width: 48px; width: 48px; }
    #weekly-source-table td:nth-child(2) { min-width: 180px; }
    .table-window { max-height: 560px; }
    .table-window thead th { position: sticky; top: 0; background: #f4f7f5; z-index: 1; }
    .weekly-changes { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 22px; }
    .change-list { background: #f5f8f6; border-radius: 10px; padding: 16px; font-size: 0.85rem; }
    .change-list ul { margin: 8px 0 0; padding-left: 17px; color: var(--muted); }
    .change-list small { display: block; color: var(--muted); }
    .details-section { margin-bottom: 20px; }
    .details-section > summary { padding: 18px 22px; }
    .details-body { padding: 16px 22px 22px; }
    details summary { cursor: pointer; font-weight: 600; }
    .model-intro { margin-bottom: 22px; }
    .map-heading a { font-size: 0.86rem; white-space: nowrap; }
    .note { background: transparent; border: 0; padding: 12px 0 0; font-size: 0.76rem; }
    @media (max-width: 980px) { .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 720px) {
      main { padding: 24px 14px; }
      .card { padding: 18px; }
      .page-header { display: block; }
      .season-badge { margin-top: 20px; }
      .page-nav { width: 100%; justify-content: stretch; top: 4px; }
      .page-nav a { flex: 1; min-width: 0; white-space: normal; text-align: center; padding: 9px 8px; font-size: 0.8rem; }
      .summary-card { padding: 16px; }
      .weekly-callout { align-items: flex-start; flex-direction: column; }
      .section-heading { flex-wrap: wrap; }
      .weekly-changes { grid-template-columns: 1fr; }
      .weekly-controls select { font-size: 0.9rem; }
      .week-bar { flex-basis: 54px; padding: 6px; }
      .map-frame { height: 58vh; min-height: 380px; }
    }
    @media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
    .repo-link { margin-top: 8px; font-size: 0.95rem; }
    .note {
      margin-top: 18px;
      padding: 12px 0 0;
      border: 0;
      border-radius: 10px;
      background: transparent;
      color: var(--muted);
      font-size: 0.76rem;
    }
    a {
      color: var(--accent);
      text-decoration: none;
    }
    a:hover { text-decoration: underline; }
    @media (max-width: 980px) {
      .score-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    @media (max-width: 720px) {
      .score-grid,
      .model-grid {
        grid-template-columns: 1fr;
      }
      .club-search {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main>
    <header class="page-header"><div>
      <p class="eyebrow">4 STAFFELN · 80 VEREINE</p>
      <h1>Regionalliga-Kompass</h1>
      <p id="subtitle"></p>
    </div><div class="season-badge">__SEASON_BADGE__</div></header>
    <nav class="page-nav" aria-label="Bereiche">
      <a href="#overview" data-view-link="overview" aria-current="page">Übersicht</a>
      <a href="#weekly" data-view-link="weekly">Wochenverlauf</a>
      <a href="#models" data-view-link="models">Modelle &amp; Details</a>
    </nav>
    <noscript><p>Bitte JavaScript aktivieren, um Karten und Tabellen auszuwählen.</p></noscript>
    <section id="overview" data-view-panel aria-label="Übersicht">
    __OVERVIEW__
    <section class="card" id="map-section">
      <div class="section-heading map-heading"><div><p class="eyebrow">AKTUELLE LIVE-PROJEKTION</p>
      <h2>Die Aufteilung auf der Karte</h2></div><a id="map-link" href="#" target="_blank" rel="noopener">Karte separat öffnen</a></div>
      <div class="switch" id="variant-switch"></div>
      <p id="variant-note"></p>
      <iframe id="map-frame" class="map-frame" src="" title="Kompass-Regionalliga Karte"></iframe>
    </section>

    <section class="card">
      <h2>Vereinssuche</h2>
      <div class="club-search">
        <div>
          <label for="club-search-input" class="eyebrow">VEREIN FINDEN</label>
          <input id="club-search-input" list="club-options" type="search" placeholder="Zum Beispiel: SV Meppen">
          <datalist id="club-options"></datalist>
        </div>
        <div class="club-result" id="club-result">Verein eingeben, um Modellzuordnung und Wege zu sehen.</div>
      </div>
    </section>

    <details class="details-section" id="clubs-section">
      <summary>Alle Vereine nach Staffel</summary>
      <div class="details-body"><div class="clubs-grid" id="clubs-grid"></div></div>
    </details>
    </section>

    <section id="weekly" data-view-panel aria-label="Wochenverlauf" hidden>
      __WEEKLY_HISTORY__
    </section>

    <section id="models" data-view-panel aria-label="Modelle und Details" hidden>
    <div class="model-intro"><p class="eyebrow">ALTERNATIVEN VERGLEICHEN</p><h2>Modelle &amp; Details</h2>
      <p>Wähle ein Modell, um seine Karte zu öffnen. Datengrundlage und Suchparameter stehen weiter unten.</p></div>
    <section class="card">
      <h2>Modellvergleich</h2>
      <div class="score-grid" id="model-score-grid"></div>
    </section>
    <section class="card">
      <h2>So funktionieren die Modelle</h2>
      <div class="model-grid" id="model-explanations"></div>
    </section>
    <section class="card takeaways">
      <h2>Was die Ergebnisse zeigen</h2>
      <ul id="takeaways-list"></ul>
    </section>
    <details class="details-section">
      <summary>Daten, Regeln und Analyse</summary>
      <div class="details-body">
        <section>
          <h2>Datenstand</h2>
          <div class="meta" id="meta-grid"></div>
        </section>

        <section class="selection">
          <h2>Wie die Auswahl erfolgt</h2>
          <ul>
            <li>Je Regionalliga werden 12 Teams ab Platz 2 übernommen; erzwungene Absteiger werden übersprungen.</li>
            <li>Hinzu kommen 4 Absteiger aus der 3. Liga.</li>
            <li>Hinzu kommen 14 Oberliga-Meister.</li>
            <li>2 Zusatzplätze gehen aktuell an Bayern und Nordost.</li>
            <li id="forced-relegations" hidden></li>
            <li>Reserve-/U-Teams sind im aktuellen Reformmodus erlaubt.</li>
          </ul>
        </section>

        <section>
          <h2>Optimierung</h2>
          <div class="meta" id="search-grid"></div>
        </section>

        <section>
          <h2>Mini-Charts</h2>
          <div class="chart-grid" id="mini-chart-grid"></div>
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
            <div class="card">
              <h3>Top 5 kürzeste verpasste Duelle (verschiedene Ligen)</h3>
              <table class="league-table" id="cross-trip-table"></table>
            </div>
          </div>
        </section>
      </div>
    </details>

    <details class="details-section">
      <summary>Archiv einzelner Berechnungsläufe</summary>
      <div class="details-body"><p>Dieses Archiv dokumentiert persönliche Neuberechnungen. Die Stabilitätskennzahlen im Wochenverlauf beziehen sich auf feste Sonntagsstände.</p>
        __RECALCULATION_HISTORY__
      </div>
    </details>
    </section>

    <p class="repo-link"><a id="repo-link" href="#" hidden>Zum GitHub-Repository</a></p>
    <p class="note">
      Dieses Projekt wurde mit Hilfe von <strong>GPT-5.3-Codex</strong> erstellt und weiterentwickelt.
    </p>
  </main>

  <script>
    const PAGE_DATA = __PAGE_DATA__;

    function showView(id) {
      const name = ["overview", "weekly", "models"].includes(id) ? id : "overview";
      document.querySelectorAll("[data-view-panel]").forEach(panel => { panel.hidden = panel.id !== name; });
      document.querySelectorAll("[data-view-link]").forEach(link => {
        if (link.dataset.viewLink === name) link.setAttribute("aria-current", "page");
        else link.removeAttribute("aria-current");
      });
    }

    function setupViews() {
      const update = () => {
        showView(window.location.hash.slice(1));
        window.scrollTo(0, 0);
      };
      window.addEventListener("hashchange", update);
      update();
    }

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

    function renderModelExplanations(items) {
      const el = document.getElementById("model-explanations");
      if (!el) return;
      el.innerHTML = (items || []).map(item => [
        `<button type="button" class="model-item${item.target_variant === activeId ? " active" : ""}" data-variant="${esc(item.target_variant || "")}">`,
        `<h3>${esc(item.title)}</h3>`,
        `<p>${esc(item.text)}</p>`,
        '</button>',
      ].join("")).join("");
      el.querySelectorAll("[data-variant]").forEach(btn => {
        btn.addEventListener("click", function () {
          navigateToVariant(this.getAttribute("data-variant") || "", true);
        });
      });
    }

    function renderModelCards(cards) {
      const el = document.getElementById("model-score-grid");
      if (!el) return;
      el.innerHTML = (cards || []).map(card => [
        `<button type="button" class="score-card${card.target_variant === activeId ? " active" : ""}" data-variant="${esc(card.target_variant || "")}">`,
        `<h3>${esc(card.title)}</h3>`,
        `<p class="best-for">${esc(card.best_for)}</p>`,
        '<div class="metric-row"><span>Ø Auswärts-km</span>',
        `<strong>${esc(card.avg_label)}</strong></div>`,
        '<div class="metric-row"><span>Längste Reise</span>',
        `<strong>${esc(card.longest_label)}</strong></div>`,
        '</button>',
      ].join("")).join("");
      el.querySelectorAll("[data-variant]").forEach(btn => {
        btn.addEventListener("click", function () {
          navigateToVariant(this.getAttribute("data-variant") || "", true);
        });
      });
    }

    function renderTakeaways(items) {
      const el = document.getElementById("takeaways-list");
      if (!el) return;
      el.innerHTML = (items || []).map(item => `<li>${esc(item)}</li>`).join("");
    }

    function renderCharts(groups) {
      const el = document.getElementById("mini-chart-grid");
      if (!el) return;
      el.innerHTML = (groups || []).map((group, groupIndex) => {
        const items = group.items || [];
        const maxValue = Math.max(1, ...items.map(item => Number(item.value) || 0));
        const rows = items.map(item => {
          const value = Number(item.value) || 0;
          const width = Math.max(2, Math.min(100, value / maxValue * 100));
          return [
            `<button type="button" class="chart-row${item.target_variant === activeId ? " active" : ""}" data-variant="${esc(item.target_variant || "")}">`,
            `<span>${esc(item.label)}</span>`,
            '<span class="bar-track">',
            `<span class="bar-fill" style="width:${width.toFixed(2)}%"></span>`,
            '</span>',
            `<span>${esc(item.detail)}</span>`,
            '</button>',
          ].join("");
        }).join("");
        return [
          '<div class="card">',
          `<h3>${esc(group.title)}</h3>`,
          `<div id="chart-${groupIndex}">${rows}</div>`,
          '</div>',
        ].join("");
      }).join("");
      el.querySelectorAll("[data-variant]").forEach(btn => {
        btn.addEventListener("click", function () {
          navigateToVariant(this.getAttribute("data-variant") || "", true);
        });
      });
    }

    const variants = PAGE_DATA.variants || [];
    let activeId = variants.length ? variants[0].id : "";

    function findVariant(id) {
      return variants.find(v => v.id === id) || variants[0];
    }

    function comparisonText(variant) {
      if (!variant) return "";
      if (variant.id === "rank1") return "Referenzmodell";
      if (variant.id === "current_regionalliga") return "nicht direkt vergleichbar: 5 Herkunftsstaffeln mit variabler Größe";
      if (variant.id === "bayern_meisterrunde") return "nicht direkt vergleichbar: 9 Gegner statt 19";
      if (variant.id === "bayern_abstiegsrunde") return "Benchmark: variable Ligagrößen nach dem Split";
      if (variant.id === "worst") return "Benchmark: maximale gefundene Distanz";
      const gap = Number(variant.gap_to_best_km);
      if (!Number.isFinite(gap)) return "";
      if (Math.abs(gap) < 0.005) return "wie Matrix";
      return (gap > 0 ? "+" : "") + gap.toFixed(2) + " km vs Matrix";
    }

    function navigateToVariant(id, scrollToMap) {
      if (!id || !findVariant(id)) return;
      showView("overview");
      window.history.replaceState(null, "", "#overview");
      activeId = id;
      renderSwitch();
      renderModelCards(PAGE_DATA.model_cards || []);
      renderModelExplanations(PAGE_DATA.model_explanations || []);
      renderCharts(PAGE_DATA.chart_groups || []);
      renderVariant(findVariant(activeId));
      if (scrollToMap) {
        const mapSection = document.getElementById("map-section");
        if (mapSection) mapSection.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    function renderVariant(variant) {
      if (!variant) return;
      const mapFrame = document.getElementById("map-frame");
      const mapLink = document.getElementById("map-link");
      const note = document.getElementById("variant-note");
      mapFrame.src = variant.map_html;
      mapLink.href = variant.map_html;

      const rankBits = [];
      const comparison = comparisonText(variant);
      if (comparison) {
        rankBits.push(comparison);
      }
      if (variant.note) {
        rankBits.push(String(variant.note));
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
        "<thead><tr><th>#</th><th>Begegnung</th><th>Distanz</th></tr></thead>",
        `<tbody>${tripRows}</tbody>`
      ].join("");

      const crossTrips = variant.top_close_cross_trips || [];
      const crossTripRows = crossTrips.map(t => (
        `<tr><td>${esc(t.index)}</td><td>${esc(t.route)}</td>` +
        `<td>${esc(t.liga_a)} / ${esc(t.liga_b)}</td><td>${esc(fmtKm(t.km))}</td></tr>`
      )).join("");
      document.getElementById("cross-trip-table").innerHTML = [
        "<thead><tr><th>#</th><th>Begegnung</th><th>Ligen</th><th>Distanz</th></tr></thead>",
        `<tbody>${crossTripRows}</tbody>`
      ].join("");

      const clubsByLeague = variant.clubs_by_league || {};
      const leaguesOrdered = Object.keys(clubsByLeague).sort();
      const clubsSection = document.getElementById("clubs-section");
      if (clubsSection) {
        clubsSection.hidden = variant.show_club_list === false;
      }
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
      renderClubSearch();
    }

    function allClubNames() {
      const names = new Set();
      variants.forEach(variant => {
        Object.keys(variant.club_lookup || {}).forEach(name => names.add(name));
      });
      return Array.from(names).sort((a, b) => a.localeCompare(b, "de"));
    }

    function setupClubSearch() {
      const input = document.getElementById("club-search-input");
      const options = document.getElementById("club-options");
      if (options) {
        options.innerHTML = allClubNames().map(name => `<option value="${esc(name)}"></option>`).join("");
      }
      if (!input) return;
      input.addEventListener("input", function () {
        renderClubSearch();
      });
    }

    function findClubName(query) {
      const q = String(query || "").trim().toLowerCase();
      if (!q) return "";
      const names = allClubNames();
      return (
        names.find(name => name.toLowerCase() === q) ||
        names.find(name => name.toLowerCase().startsWith(q)) ||
        names.find(name => name.toLowerCase().includes(q)) ||
        ""
      );
    }

    function leagueForTeam(variant, team) {
      const info = (variant.club_lookup || {})[team];
      return info ? info.liga : "nicht dabei";
    }

    function renderClubSearch() {
      const input = document.getElementById("club-search-input");
      const result = document.getElementById("club-result");
      if (!input || !result) return;
      const team = findClubName(input.value);
      if (!team) {
        result.textContent = "Verein eingeben, um Modellzuordnung und Wege zu sehen.";
        return;
      }
      const activeVariant = findVariant(activeId);
      const info = (activeVariant.club_lookup || {})[team];
      const missed = (activeVariant.closest_cross_by_club || {})[team];
      const assignments = variants
        .filter(variant => ["rank1", "wish_best", "regionenmodell", "current_regionalliga", "bayern_meisterrunde"].includes(variant.id))
        .map(variant => (
          `<tr><td>${esc(variant.title)}</td><td>${esc(leagueForTeam(variant, team))}</td></tr>`
        ))
        .join("");

      const activeRows = info ? [
        `<tr><td>Aktive Karte</td><td>${esc(activeVariant.title)}</td></tr>`,
        `<tr><td>Liga</td><td>${esc(info.liga)}</td></tr>`,
        `<tr><td>Ø Auswärtsfahrt</td><td>${esc(fmtKm(info.avg_km))}</td></tr>`,
        `<tr><td>Längste Auswärtsfahrt</td><td>${esc(info.longest_opponent || "-")} (${esc(fmtKm(info.longest_km))})</td></tr>`,
      ].join("") : `<tr><td>Aktive Karte</td><td>${esc(activeVariant.title)}: nicht dabei</td></tr>`;

      const missedText = missed
        ? `${esc(missed.opponent)} (${esc(missed.own_liga)} / ${esc(missed.opponent_liga)}, ${esc(fmtKm(missed.km))})`
        : "-";

      result.innerHTML = [
        `<h3>${esc(team)}</h3>`,
        '<table class="league-table">',
        '<tbody>',
        activeRows,
        `<tr><td>Nächstes verpasstes Duell</td><td>${missedText}</td></tr>`,
        '</tbody>',
        '</table>',
        '<table class="league-table">',
        '<thead><tr><th>Modell</th><th>Zuordnung</th></tr></thead>',
        `<tbody>${assignments}</tbody>`,
        '</table>',
      ].join("");
    }

    function renderSwitch() {
      const el = document.getElementById("variant-switch");
      if (!el) return;
      const benchmarkIds = new Set(["bayern_abstiegsrunde", "worst"]);
      const primary = variants.filter(v => !benchmarkIds.has(v.id));
      const benchmarks = variants.filter(v => benchmarkIds.has(v.id));
      const buttonHtml = (v, extraClass) => (
        `<button class="${extraClass || ""}${v.id === activeId ? " active" : ""}" data-variant="${esc(v.id)}">${esc(v.title)}</button>`
      );
      el.innerHTML = [
        primary.map(v => buttonHtml(v, "")).join(""),
        benchmarks.length ? '<span class="switch-label">Benchmark</span>' : "",
        benchmarks.map(v => buttonHtml(v, "benchmark")).join(""),
      ].join("");
      el.querySelectorAll("button[data-variant]").forEach(btn => {
        btn.addEventListener("click", function () {
          navigateToVariant(this.getAttribute("data-variant") || "", false);
        });
      });
    }

    function setupWeeklyHistory() {
      const history = PAGE_DATA.weekly_history;
      const dateSelect = document.getElementById("weekly-date");
      const leagueSelect = document.getElementById("weekly-league");
      if (!history || !dateSelect || !leagueSelect) return;
      const previousButton = document.getElementById("weekly-prev");
      const nextButton = document.getElementById("weekly-next");
      const dateLabel = value => value.split("-").reverse().join(".");
      const table = (headers, rows) => '<thead><tr>' + headers.map(h => `<th>${esc(h)}</th>`).join("") +
        '</tr></thead><tbody>' + rows.map(row => '<tr>' + row.map(value => `<td>${esc(value)}</td>`).join("") + '</tr>').join("") + '</tbody>';
      function render() {
        const index = history.snapshots.findIndex(week => week.as_of === dateSelect.value);
        const week = history.snapshots[index];
        if (!week) return;
        const source = week.tables.find(league => league.name === leagueSelect.value) || week.tables[0];
        const change = index > 0 ? history.summary.comparisons[index - 1] : null;
        const selected = new Set(week.teams);
        document.getElementById("weekly-description").textContent = `Sonntag, ${dateLabel(week.as_of)}, 23:59 Uhr. ` +
          (change ? `Vergleich mit ${dateLabel(history.snapshots[index - 1].as_of)}: ${change.switch_count} Staffelwechsel bei ${change.shared_count} gemeinsamen Vereinen.` : "Erster Wochenstand – Ausgangspunkt für den Vergleich.") +
          (week.selection_ties.length ? " Gleichstand an einer Auswahlgrenze; alphabetische Zuordnung verwendet." : "");
        previousButton.disabled = index === 0;
        nextButton.disabled = index === history.snapshots.length - 1;
        document.querySelectorAll("button[data-week]").forEach(button => {
          button.setAttribute("aria-pressed", String(button.dataset.week === week.as_of));
        });
        document.getElementById("weekly-map-link").href = week.map_href;
        document.getElementById("weekly-source-link").href = source.source_url;
        const frame = document.getElementById("weekly-map");
        if (frame.getAttribute("src") !== week.map_href) frame.src = week.map_href;
        document.getElementById("weekly-source-table").innerHTML = table(
          ["Platz", "Verein", "Spiele", "Tore", "Diff.", "Punkte", "Im Pool", "Gleichstand"],
          source.rows.map(row => [row.rank, row.team, row.games, `${row.goals_for}:${row.goals_against}`,
            row.goal_difference, row.points, selected.has(row.team) ? "Ja" : "", row.ranking_tie.length ? "Ja" : ""]));
        document.getElementById("weekly-assignment-table").innerHTML = table(["Verein", "Staffel"],
          Object.entries(week.assignments).sort((a, b) => a[0].localeCompare(b[0], "de")).map(([team, league]) => [team, league]));
        const list = (title, items, empty) => '<div class="change-list"><h3>' + esc(title) + '</h3>' +
          (items.length ? '<ul>' + items.map(value => '<li>' + esc(value) + '</li>').join("") + '</ul>' : '<small>' + esc(empty) + '</small>') + '</div>';
        document.getElementById("weekly-changes").innerHTML = change ?
          list(`${change.switch_count} Staffelwechsel`, change.switched.map(row => `${row.team}: ${row.from_league} → ${row.to_league}`), "Keine Staffelwechsel.") +
          list(`${change.entered.length} neu im Pool`, change.entered, "Keine neuen Vereine.") +
          list(`${change.left.length} aus dem Pool`, change.left, "Keine ausgeschiedenen Vereine.") :
          '<p class="caption">Der Ausgangsstand hat noch keinen Wochenvergleich.</p>';
      }
      dateSelect.addEventListener("change", render);
      leagueSelect.addEventListener("change", render);
      document.querySelectorAll("button[data-week]").forEach(button => button.addEventListener("click", () => {
        dateSelect.value = button.dataset.week;
        render();
        document.getElementById("weekly-explorer").scrollIntoView({behavior: "smooth", block: "start"});
      }));
      previousButton.addEventListener("click", () => {
        const index = history.snapshots.findIndex(week => week.as_of === dateSelect.value);
        if (index > 0) { dateSelect.value = history.snapshots[index - 1].as_of; render(); }
      });
      nextButton.addEventListener("click", () => {
        const index = history.snapshots.findIndex(week => week.as_of === dateSelect.value);
        if (index < history.snapshots.length - 1) { dateSelect.value = history.snapshots[index + 1].as_of; render(); }
      });
      document.querySelectorAll("[data-week-panel]").forEach(button => button.addEventListener("click", () => {
        document.querySelectorAll("[data-week-content]").forEach(panel => { panel.hidden = panel.dataset.weekContent !== button.dataset.weekPanel; });
        document.querySelectorAll("[data-week-panel]").forEach(item => {
          const selected = item === button;
          item.classList.toggle("active", selected);
          item.setAttribute("aria-pressed", String(selected));
        });
      }));
      render();
    }

    (function bootstrap() {
      setupViews();
      setupWeeklyHistory();
      document.querySelectorAll(".history-time").forEach(el => {
        const date = new Date(el.dateTime);
        if (Number.isFinite(date.getTime())) {
          el.textContent = date.toLocaleString("de-DE", { timeZone: "Europe/Berlin", dateStyle: "short", timeStyle: "short" });
        }
      });
      const subtitle = document.getElementById("subtitle");
      if (subtitle) subtitle.textContent = PAGE_DATA.subtitle || "";
      const forcedRelegations = document.getElementById("forced-relegations");
      if (forcedRelegations && PAGE_DATA.forced_relegations_note) {
        forcedRelegations.textContent = PAGE_DATA.forced_relegations_note;
        forcedRelegations.hidden = false;
      }
      const simpleExplanation = document.getElementById("simple-explanation");
      if (simpleExplanation) simpleExplanation.textContent = PAGE_DATA.simple_explanation || "";
      renderModelCards(PAGE_DATA.model_cards || []);
      renderModelExplanations(PAGE_DATA.model_explanations || []);
      renderTakeaways(PAGE_DATA.takeaways || []);
      renderCards("meta-grid", PAGE_DATA.meta_cards || []);
      renderCards("search-grid", PAGE_DATA.search_cards || []);
      renderCharts(PAGE_DATA.chart_groups || []);
      setupClubSearch();
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
    html = html.replace("__OVERVIEW__", render_overview(page_data))
    html = html.replace("__SEASON_BADGE__", f'<small>Reformsaison</small><strong>{escape(page_data.get("target_season", "–"))}</strong>'
                        f'<small>Quellsaison {escape(page_data.get("source_season", "–"))}</small>')
    html = html.replace("__RECALCULATION_HISTORY__", render_recalculation_history(page_data.get("recalculation_history", {})))
    html = html.replace("__WEEKLY_HISTORY__", render_weekly_history(page_data.get("weekly_history", {})))
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
    (OUTPUT_HTML_DIR / "kompass_regionalliga_4x20_map_wish_worst.html").unlink(missing_ok=True)

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
    regionenmodell_transitions = load_transitions(TRANSITIONS_JSON, model_name="regionenmodell")
    bayern_transitions = load_transitions(TRANSITIONS_JSON, model_name="bayern_vorrunden_split")
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
    worst_csv_path = Path(INPUT_CSV_WISH_WORST)
    if worst_csv_path.exists():
        try:
            df_worst = load_solution_csv(worst_csv_path)
            worst_data = {"df": df_worst, "csv": str(worst_csv_path)}
        except Exception:
            worst_data = None
    wish_best_data: Optional[Dict[str, Any]] = None
    from kompass import (
        WISH_SA_ENABLED, Club, build_wish_table, compute_distance_matrix_km,
        wish_solution_is_acceptable,
    )
    wish_best_csv_path = Path(INPUT_CSV_WISH_BEST)
    if WISH_SA_ENABLED and wish_best_csv_path.exists():
        try:
            df_wish_best = load_solution_csv(wish_best_csv_path)
            if set(df_wish_best["Verein"]) == set(df_rank1["Verein"]):
                df_wish_best = df_wish_best.set_index("Verein").loc[df_rank1["Verein"]].reset_index()
                clubs = [Club(row.Verein, row.lat, row.lon) for row in df_rank1.itertuples()]
                distances = compute_distance_matrix_km(clubs)
                if wish_solution_is_acceptable(
                    pd.factorize(df_wish_best["Liga"])[0],
                    pd.factorize(df_rank1["Liga"])[0],
                    distances, build_wish_table(distances),
                ):
                    wish_best_data = {"df": df_wish_best, "csv": str(wish_best_csv_path)}
        except Exception:
            wish_best_data = None
    if wish_best_data is None:
        for path in (MAP_HTML_WISH_BEST, MAP_COMPARE_HTML_WISH):
            Path(path).unlink(missing_ok=True)
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
    regionenmodell_data: Optional[Dict[str, Any]] = None
    regionenmodell_csv_path = Path(INPUT_CSV_REGIONENMODELL)
    if regionenmodell_csv_path.exists():
        try:
            df_regionenmodell = load_solution_csv(regionenmodell_csv_path)
            regionenmodell_data = {"df": df_regionenmodell, "csv": str(regionenmodell_csv_path)}
        except Exception:
            regionenmodell_data = None
    bayern_meister_data: Optional[Dict[str, Any]] = None
    bayern_meister_csv_path = Path(INPUT_CSV_BAYERN_MEISTER)
    if bayern_meister_csv_path.exists():
        try:
            df_bayern_meister = load_solution_csv(bayern_meister_csv_path)
            bayern_meister_data = {"df": df_bayern_meister, "csv": str(bayern_meister_csv_path)}
        except Exception:
            bayern_meister_data = None
    bayern_abstieg_data: Optional[Dict[str, Any]] = None
    bayern_abstieg_csv_path = Path(INPUT_CSV_BAYERN_ABSTIEG)
    if bayern_abstieg_csv_path.exists():
        try:
            df_bayern_abstieg = load_solution_csv(bayern_abstieg_csv_path)
            bayern_abstieg_data = {"df": df_bayern_abstieg, "csv": str(bayern_abstieg_csv_path)}
        except Exception:
            bayern_abstieg_data = None
    current_regionalliga_data: Optional[Dict[str, Any]] = None
    current_regionalliga_csv_path = Path(INPUT_CSV_CURRENT_REGIONALLIGA)
    if current_regionalliga_csv_path.exists():
        try:
            df_current_regionalliga = load_solution_csv(current_regionalliga_csv_path)
            current_regionalliga_data = {
                "df": df_current_regionalliga,
                "csv": str(current_regionalliga_csv_path),
            }
        except Exception:
            current_regionalliga_data = None

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

    club_df, league_df, trips_df, _ = compute_metrics(rank_data[1]["df"])
    club_df.to_csv(CLUB_METRICS_CSV, index=False, encoding="utf-8")
    league_df.to_csv(LEAGUE_METRICS_CSV, index=False, encoding="utf-8")
    trips_df.head(100).to_csv(LONGEST_TRIPS_CSV, index=False, encoding="utf-8")
    print_summary(club_df, league_df, trips_df)

    variants: List[Dict[str, Any]] = []
    compare_links: List[Dict[str, str]] = []

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

        club_df_rank, league_df_rank, trips_df_rank, cross_trips_df_rank = compute_metrics(df_rank)
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
                cross_trips_df_rank,
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
        print(f"Karte (Initial): {MAP_HTML_INITIAL}")
        print(f"Kartenvergleich: {MAP_COMPARE_HTML_INITIAL}")
        print(f"Sichtbare Unterschiede Initial/Rank1: {len(changed_initial_vs_rank1)}")

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
        print(f"Kartenvergleich: {MAP_COMPARE_HTML_INITIAL_AUTO_MANUAL}")
        print(f"Sichtbare Unterschiede Initial-Auto/Initial-Manuell: {len(changed_auto_manual)}")

    current_regionalliga_score: Optional[float] = None
    if current_regionalliga_data is not None:
        df_current_regionalliga_map, _ = resolve_map_coordinates(current_regionalliga_data["df"])
        build_map(
            df_current_regionalliga_map,
            MAP_HTML_CURRENT_REGIONALLIGA,
            transitions,
            changed_teams=None,
            variant="current_regionalliga",
        )
        club_df_crl, league_df_crl, trips_df_crl, cross_trips_df_crl = compute_metrics(
            current_regionalliga_data["df"]
        )
        current_regionalliga_score = float(club_df_crl["Durchschnitt_Auswaerts_km"].mean())
        variants.append(
            build_variant_payload(
                "current_regionalliga",
                "Aktuelle Regionalligen nach Auf-/Abstieg",
                html_asset_name(MAP_HTML_CURRENT_REGIONALLIGA),
                current_regionalliga_data["df"],
                club_df_crl,
                league_df_crl,
                trips_df_crl,
                cross_trips_df_crl,
                rank_info={
                    "rank": 0,
                    "rank_label": "Aktuelle Regionalligen",
                    "score_avg_away_km": current_regionalliga_score,
                    "gap_to_best_km": 0.0,
                },
                show_club_list=False,
                note="5 bisherige Regionalligen als Herkunfts-/Zielstaffeln des 80er-Reform-Pools nach Auf-/Abstieg.",
            )
        )
        print(f"Karte (Aktuelle Regionalligen): {MAP_HTML_CURRENT_REGIONALLIGA}")

    if regionenmodell_data is not None:
        changed_regionenmodell = compute_changed_teams(rank_data[1]["df"], regionenmodell_data["df"])
        df_regionenmodell_map, _ = resolve_map_coordinates(regionenmodell_data["df"])
        build_map(
            df_regionenmodell_map,
            MAP_HTML_REGIONENMODELL,
            regionenmodell_transitions or transitions,
            changed_teams=changed_regionenmodell if changed_regionenmodell else None,
            variant="regionenmodell",
            changed_left_label="RANK1",
            changed_right_label="REGIONEN",
        )
        create_compare_html(
            html_asset_name(MAP_HTML),
            html_asset_name(MAP_HTML_REGIONENMODELL),
            MAP_COMPARE_HTML_REGIONENMODELL,
            left_title="Distanzmatrix-Optimierung (Rank 1)",
            right_title="Regionenmodell",
        )
        compare_links.append({"href": html_asset_name(MAP_COMPARE_HTML_REGIONENMODELL), "label": "Rank 1 vs Regionenmodell"})
        club_df_rm, league_df_rm, trips_df_rm, cross_trips_df_rm = compute_metrics(regionenmodell_data["df"])
        regionenmodell_score = float(club_df_rm["Durchschnitt_Auswaerts_km"].mean())
        variants.append(
            build_variant_payload(
                "regionenmodell",
                "Regionenmodell",
                html_asset_name(MAP_HTML_REGIONENMODELL),
                regionenmodell_data["df"],
                club_df_rm,
                league_df_rm,
                trips_df_rm,
                cross_trips_df_rm,
                rank_info={
                    "rank": 0,
                    "rank_label": "Regionenmodell",
                    "score_avg_away_km": regionenmodell_score,
                    "gap_to_best_km": regionenmodell_score - float(best_score) if best_score is not None else 0.0,
                },
                show_club_list=False,
                note="West/Suedwest fix, 4 Direktaufsteiger, RL-Abstieg 3/3/8",
            )
        )
        print(f"Karte (Regionenmodell): {MAP_HTML_REGIONENMODELL}")
        print(f"Kartenvergleich: {MAP_COMPARE_HTML_REGIONENMODELL}")
        print(f"Sichtbare Unterschiede Rank1/Regionenmodell: {len(changed_regionenmodell)}")

    bayern_meister_score: Optional[float] = None
    if bayern_meister_data is not None:
        df_bayern_meister_map, _ = resolve_map_coordinates(bayern_meister_data["df"])
        build_map(
            df_bayern_meister_map,
            MAP_HTML_BAYERN_MEISTER,
            bayern_transitions or transitions,
            changed_teams=None,
            variant="bayern_meisterrunde",
        )
        create_compare_html(
            html_asset_name(MAP_HTML),
            html_asset_name(MAP_HTML_BAYERN_MEISTER),
            MAP_COMPARE_HTML_BAYERN_MEISTER,
            left_title="Distanzmatrix-Optimierung (Rank 1, 4x20)",
            right_title="Bayern-Meisterrunde (4x10)",
        )
        compare_links.append({"href": html_asset_name(MAP_COMPARE_HTML_BAYERN_MEISTER), "label": "Rank 1 vs Bayern-Meisterrunde"})
        club_df_fm, league_df_fm, trips_df_fm, cross_trips_df_fm = compute_metrics(bayern_meister_data["df"])
        bayern_meister_score = float(club_df_fm["Durchschnitt_Auswaerts_km"].mean())
        variants.append(
            build_variant_payload(
                "bayern_meisterrunde",
                "Bayern-Vorrunden-Split (Meisterrunde, 4x10)",
                html_asset_name(MAP_HTML_BAYERN_MEISTER),
                bayern_meister_data["df"],
                club_df_fm,
                league_df_fm,
                trips_df_fm,
                cross_trips_df_fm,
                rank_info={
                    "rank": 0,
                    "rank_label": "Bayern-Meisterrunde",
                    "score_avg_away_km": bayern_meister_score,
                    "gap_to_best_km": 0.0,
                },
                show_club_list=False,
                note=(
                    "Farben zeigen die 4 Meisterrunden-Staffeln; RL-Herkunft steht in Tooltip/Popup. "
                    "Nur Top-8 je RL (40 Teams) in 4 Staffeln a 10 – "
                    "Ø-Auswärts-Metrik nicht direkt mit 20er-Ligen vergleichbar (9 statt 19 Gegner)."
                ),
            )
        )
        print(f"Karte (Bayern-Meisterrunde): {MAP_HTML_BAYERN_MEISTER}")
        print(f"Kartenvergleich: {MAP_COMPARE_HTML_BAYERN_MEISTER}")

    bayern_abstieg_score: Optional[float] = None
    if bayern_abstieg_data is not None:
        df_bayern_abstieg_map, _ = resolve_map_coordinates(bayern_abstieg_data["df"])
        build_map(
            df_bayern_abstieg_map,
            MAP_HTML_BAYERN_ABSTIEG,
            bayern_transitions or transitions,
            changed_teams=None,
            variant="bayern_abstiegsrunde",
        )
        club_df_fa, league_df_fa, trips_df_fa, cross_trips_df_fa = compute_metrics(bayern_abstieg_data["df"])
        bayern_abstieg_score = float(club_df_fa["Durchschnitt_Auswaerts_km"].mean())
        variants.append(
            build_variant_payload(
                "bayern_abstiegsrunde",
                "Bayern-Abstiegsrunde (Benchmark)",
                html_asset_name(MAP_HTML_BAYERN_ABSTIEG),
                bayern_abstieg_data["df"],
                club_df_fa,
                league_df_fa,
                trips_df_fa,
                cross_trips_df_fa,
                rank_info={
                    "rank": 0,
                    "rank_label": "Bayern-Abstiegsrunde",
                    "score_avg_away_km": bayern_abstieg_score,
                    "gap_to_best_km": 0.0,
                },
                show_club_list=False,
                note=(
                    "Farben zeigen die bisherigen RL-Staffeln; untere Teams jeder RL bleiben in ihrer bisherigen Staffel – "
                    "Ligagrößen variieren, Vergleich mit 4x20 nur eingeschränkt aussagekräftig."
                ),
            )
        )
        print(f"Karte (Bayern-Abstiegsrunde): {MAP_HTML_BAYERN_ABSTIEG}")

    if bayern_meister_data is not None and bayern_abstieg_data is not None:
        create_compare_html(
            html_asset_name(MAP_HTML_BAYERN_MEISTER),
            html_asset_name(MAP_HTML_BAYERN_ABSTIEG),
            MAP_COMPARE_HTML_BAYERN_SPLIT,
            left_title="Bayern-Meisterrunde (4x10)",
            right_title="Bayern-Abstiegsrunde (5 RL)",
        )
        compare_links.append({"href": html_asset_name(MAP_COMPARE_HTML_BAYERN_SPLIT), "label": "Bayern: Meisterrunde vs Abstiegsrunde"})
        print(f"Kartenvergleich Bayern-Split: {MAP_COMPARE_HTML_BAYERN_SPLIT}")

    if wish_best_data is not None:
        changed_wish_best = compute_changed_teams(rank_data[1]["df"], wish_best_data["df"])
        df_wish_best_map, _ = resolve_map_coordinates(wish_best_data["df"])
        build_map(
            df_wish_best_map,
            MAP_HTML_WISH_BEST,
            transitions,
            changed_teams=changed_wish_best if changed_wish_best else None,
            variant="wish_best",
            changed_left_label="RANK1",
            changed_right_label="WISH-BEST",
        )
        create_compare_html(
            html_asset_name(MAP_HTML),
            html_asset_name(MAP_HTML_WISH_BEST),
            MAP_COMPARE_HTML_WISH,
            left_title="Distanzmatrix-Optimierung (Rank 1)",
            right_title="Wunschlisten-Optimierung (Beste Coverage)",
        )
        compare_links.append({"href": html_asset_name(MAP_COMPARE_HTML_WISH), "label": "Rank 1 vs Wunschlisten-Best"})
        club_df_wb, league_df_wb, trips_df_wb, cross_trips_df_wb = compute_metrics(wish_best_data["df"])
        wish_best_score_computed = float(club_df_wb["Durchschnitt_Auswaerts_km"].mean())
        variants.append(
            build_variant_payload(
                "wish_best",
                "Wunschlisten-Optimierung (Beste Coverage)",
                html_asset_name(MAP_HTML_WISH_BEST),
                wish_best_data["df"],
                club_df_wb,
                league_df_wb,
                trips_df_wb,
                cross_trips_df_wb,
                rank_info={
                    "rank": 0,
                    "rank_label": "Wunschlisten-Best",
                    "score_avg_away_km": wish_best_score_computed,
                    "gap_to_best_km": wish_best_score_computed - float(best_score) if best_score is not None else 0.0,
                },
            )
        )
        print(f"Karte (Wunschlisten-Beste): {MAP_HTML_WISH_BEST}")
        print(f"Kartenvergleich: {MAP_COMPARE_HTML_WISH}")
        print(f"Sichtbare Unterschiede Rank1/Wish-Best: {len(changed_wish_best)}")

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
            right_title="Worst-Case-Optimierung (Maximale Distanz)",
        )
        compare_links.append({"href": html_asset_name(MAP_COMPARE_HTML_WORST), "label": "Rank 1 vs Worst-Case"})
        print(f"Karte (Worst-Case): {MAP_HTML_WORST}")
        print(f"Kartenvergleich: {MAP_COMPARE_HTML_WORST}")
        print(f"Sichtbare Unterschiede Rank1/Worst: {len(changed_vs_rank1)}")

        club_df_worst, league_df_worst, trips_df_worst, cross_trips_df_worst = compute_metrics(worst_data["df"])
        worst_score_computed = float(club_df_worst["Durchschnitt_Auswaerts_km"].mean())
        variants.append(
            build_variant_payload(
                "worst",
                "Worst-Case-Optimierung (Maximale Distanz)",
                html_asset_name(MAP_HTML_WORST),
                worst_data["df"],
                club_df_worst,
                league_df_worst,
                trips_df_worst,
                cross_trips_df_worst,
                rank_info={
                    "rank": 0,
                    "rank_label": "Worst-Case",
                    "score_avg_away_km": worst_score_computed,
                    "gap_to_best_km": (
                        worst_score_computed - float(best_score)
                        if best_score is not None
                        else 0.0
                    ),
                },
                show_club_list=False,
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
    worst_score = worst_score_computed if worst_data is not None else None
    if wish_best_data is None:
        wish_best_score_computed = None
    if current_regionalliga_data is None:
        current_regionalliga_score = None
    if regionenmodell_data is None:
        regionenmodell_score = None
    if bayern_meister_data is None:
        bayern_meister_score = None
    if bayern_abstieg_data is None:
        bayern_abstieg_score = None
    gap_text = "-"
    try:
        if best_score is not None and second_score is not None:
            gap_text = f"{float(second_score) - float(best_score):.2f} km"
    except Exception:
        gap_text = "-"

    source_season = transitions.get("source_season", "-")
    target_season = transitions.get("target_season", "-")
    history_report = build_history_report(
        source_season, target_season,
        dict(zip(df_rank1["Verein"], df_rank1["Liga"])), ranked_payload.get("generated_at"),
    ) if source_season != "-" and target_season != "-" else {"available": False}
    export_history_report(history_report, OUTPUT_JSON_DIR / "recalculation_changes.json",
                          OUTPUT_CSV_DIR / "kompass_recalculation_changes_per_club.csv")
    weekly_history = load_weekly_projections(source_season, target_season) if source_season != "-" and target_season != "-" else {}
    if weekly_history:
        grounds = load_verified_stadiums(source_season)
        for index, week in enumerate(weekly_history["snapshots"]):
            frame = pd.DataFrame([{"Verein": team, "Liga": league,
                                   "lat": grounds[team]["lat"], "lon": grounds[team]["lon"]}
                                  for team, league in week["assignments"].items()])
            mapped, _ = resolve_map_coordinates(frame)
            filename = f'kompass_weekly_{week["as_of"].replace("-", "_")}.html'
            comparison = weekly_history["summary"]["comparisons"][index - 1] if index else {}
            changes = {row["team"]: (row["from_league"], row["to_league"])
                       for row in comparison.get("switched", [])}
            unresolved = build_map(mapped, str(OUTPUT_HTML_DIR / filename), week.get("transitions", {}),
                                   changed_teams=changes, variant="matrix", changed_left_label="Vorwoche",
                                   changed_right_label=week["as_of"],
                                   as_of_note=f'Rekonstruierte Projektion zum {week["as_of"]} – heutiger Spielwertungsstand')
            if unresolved:
                raise RuntimeError("Missing weekly map coordinates: " + ", ".join(unresolved))
            week["map_href"] = filename
        export_weekly_metrics(weekly_history)
    season_note = f"Quellsaison {source_season} → Reform {target_season}."
    if transitions.get("is_projection"):
        season_note += " Vorläufige Projektion aus laufenden Tabellen; Auf-/Abstiege sind Modellannahmen."
    forced_teams = [
        team for teams in transitions.get("forced_regionalliga_relegations", {}).values()
        for team in teams
    ]
    page_data = {
        "source_season": source_season,
        "target_season": target_season,
        "recalculation_history": history_report,
        "weekly_history": weekly_history,
        "subtitle": "Geografisch optimierte Staffeln, kurze Auswärtswege und ein fester Wochenvergleich. "
        + ("Vorläufige Projektion aus den laufenden Tabellen." if transitions.get("is_projection") else season_note),
        "forced_relegations_note": (
            f"Sonderfälle der Quellsaison {source_season}: {', '.join(forced_teams)} werden als Regionalliga-Absteiger behandelt."
            if forced_teams else ""
        ),
        "simple_explanation": (
            "Die Distanzmatrix-Optimierung sucht die Aufteilung mit den kürzesten Auswärtsfahrten (Rank 1). "
            "Die aktuelle RL-Karte zeigt, welcher bisherigen Regionalliga die Teams nach Auf-/Abstieg zugeordnet sind. "
            "Das Regionenmodell hält West und Südwest stabil und teilt den Block aus Nord, Nordost und Bayern "
            "in zwei 20er-Staffeln. "
            "Der Bayern-Vorrunden-Split teilt jede der 5 bestehenden "
            "Regionalligen nach der Hinrunde: Top-8 je Liga (40 Teams) bilden 4 geografisch optimierte "
            "Meisterrunden-Staffeln à 10. Die Abstiegsrunde bleibt als Benchmark im Karten-Switch. "
            "Der Worst-Case bleibt als Benchmark für die schlechtestmögliche Aufteilung verfügbar."
        ),
        "model_explanations": [
            {
                "title": "Matrix-Methode",
                "target_variant": "rank1",
                "text": (
                    "Alle Vereinsstandorte werden paarweise in einer Distanzmatrix verglichen. Ausgehend von "
                    "Startverteilungen tauscht der Optimierer wiederholt 2, 3 oder 4 Vereine zwischen Staffeln "
                    "und behält bessere Lösungen. Rank 1 ist die beste gefundene 4x20-Aufteilung."
                ),
            },
            {
                "title": "Wunschlisten-Optimierung",
                "target_variant": "wish_best",
                "text": (
                    "Für jeden Verein wird eine Wunschliste der 19 geografisch nächsten Nachbarn gebaut. "
                    "Optimiert wird nicht direkt die Gesamtdistanz, sondern wie viele dieser Wunschgegner "
                    "in derselben 20er-Staffel landen. Die längste Reise und der höchste Vereinsdurchschnitt "
                    "dürfen die Matrix-Lösung nicht überschreiten."
                ),
            },
            {
                "title": "Aktuelle Regionalligen",
                "target_variant": "current_regionalliga",
                "text": (
                    "Diese Karte gruppiert den 80er-Reform-Pool nach den bisherigen fünf Regionalligen. "
                    "Absteiger aus der 3. Liga werden ihrer Ziel-Regionalliga zugeordnet. "
                    "Sonderfälle gelten nur für die jeweilige Quellsaison."
                ),
            },
            {
                "title": "Regionenmodell",
                "target_variant": "regionenmodell",
                "text": (
                    "West und Südwest bleiben als eigene 20er-Staffeln erhalten. Nord, Nordost und Bayern "
                    "bilden einen gemeinsamen 40er-Block, der geografisch in Nord und Ost geteilt wird. "
                    "Oberliga-Meister werden ihrer Makroregion zugeordnet; für Folgejahre gilt die Annahme "
                    "4 Direktaufsteiger, RL-Abstieg West=3, Südwest=3 und Nord/Nordost/Bayern-Block=8."
                ),
            },
            {
                "title": "Bayern-Modell",
                "target_variant": "bayern_meisterrunde",
                "text": (
                    "Die fünf bestehenden Regionalligen spielen zunächst in ihrer bisherigen Struktur. Nach der "
                    "Hinrunde gehen die Top-8 jeder Liga in eine 40-Team-Meisterrunde, die in vier geografische "
                    "10er-Staffeln geteilt wird. Die Abstiegsrunde wird separat als Benchmark angezeigt, weil "
                    "ihre Ligagrößen variieren und sie nicht sauber mit 4x20 vergleichbar ist."
                ),
            },
        ],
        "model_cards": build_model_cards(variants),
        "chart_groups": build_chart_groups(rank_data[1]["df"], variants),
        "takeaways": build_key_takeaways(variants),
        "meta_cards": [
            {"label": "Letzter Lauf", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            {"label": "Quellsaison", "value": source_season},
            {"label": "Reformsaison", "value": target_season},
            {"label": "Modus", "value": "Reformregel 12+4+14+2"},
            {"label": "Derby-Regel", "value": "Deaktiviert (ENFORCE_DERBY_SAME_LEAGUE = False)"},
            {"label": "Quellen-Priorität", "value": " -> ".join(transitions.get("source_priority", ["fupa", "wikipedia"]))},
        ],
        "search_cards": [
            {"label": "Multi-Start Läufe", "value": str(requested_runs) if requested_runs is not None else "-"},
            {"label": "Eindeutige Lösungen", "value": str(unique_solutions) if unique_solutions is not None else "-"},
            {"label": "Rank-1 Score", "value": f"{float(best_score):.2f} km" if best_score is not None else "-"},
            {"label": "Gap Rank2-Rank1", "value": gap_text},
            {"label": "Verfügbare Ranks", "value": ", ".join(str(r) for r in sorted(rank_data.keys()))},
            {
                "label": "Regionenmodell",
                "value": f"{regionenmodell_score:.2f} km" if regionenmodell_score is not None else "-",
            },
            {
                "label": "Aktuelle Regionalligen",
                "value": f"{current_regionalliga_score:.2f} km" if current_regionalliga_score is not None else "-",
            },
            {
                "label": "Bayern-Meisterrunde (4x10)",
                "value": f"{bayern_meister_score:.2f} km" if bayern_meister_score is not None else "-",
            },
            {
                "label": "Benchmark: Bayern-Abstiegsrunde",
                "value": f"{bayern_abstieg_score:.2f} km" if bayern_abstieg_score is not None else "-",
            },
            {
                "label": "Wunschlisten-Best",
                "value": f"{wish_best_score_computed:.2f} km" if wish_best_score_computed is not None else "-",
            },
            {
                "label": "Worst-Case",
                "value": f"{float(worst_score):.2f} km" if worst_score is not None else "-",
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
    }
    variant_ids = {variant["id"] for variant in variants}
    page_data["model_explanations"] = [
        explanation for explanation in page_data["model_explanations"]
        if explanation["target_variant"] in variant_ids
    ]
    if wish_best_data is None:
        page_data["search_cards"] = [
            card for card in page_data["search_cards"]
            if card["label"] != "Wunschlisten-Best"
        ]
    create_index_html(page_data, INDEX_HTML)
    docs_count = sync_pages_docs(OUTPUT_HTML_DIR, PAGES_DOCS_DIR)

    print()
    print(f"Karte: {MAP_HTML}")
    print(
        "Kartenkoordinaten: "
        f"{map_coord_stats['stadium']}/{map_coord_stats['total']} Stadion-Koordinaten, "
        f"{map_coord_stats['fallback_club']} Club-Fallbacks"
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
