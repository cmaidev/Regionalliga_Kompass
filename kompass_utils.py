# -*- coding: utf-8 -*-
"""
Gemeinsame Hilfsfunktionen und Datenstrukturen fuer kompass.py und kompass_report.py.
Kein Netzwerkzugriff, keine externen Abhaengigkeiten (nur stdlib).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path


def normalize_text(text: str) -> str:
    """
    Normalisiert einen String:
    - Entfernt fuehrende/nachfolgende Whitespace
    - Ersetzt Non-Breaking Spaces durch regulaere Leerzeichen
    - Repariert UTF-8/Latin1-Mojibake (z.B. "MÃ¶nchengladbach" -> "Mönchengladbach")
    - Kollabiert Mehrfach-Whitespace
    """
    s = str(text).strip()
    s = s.replace("\xa0", " ")
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


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Orthodrome-Distanz in Kilometern zwischen zwei Punkten (WGS84)."""
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def ensure_parent_dir(path: str) -> None:
    """Erstellt das Elternverzeichnis einer Datei, falls es nicht existiert."""
    parent = Path(path).parent
    if str(parent) and str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Club:
    """Repraesentiert einen Fussballverein mit geografischen Koordinaten."""
    name: str
    lat: float
    lon: float
