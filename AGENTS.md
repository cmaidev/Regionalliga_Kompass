# AGENTS.md

## Projektzweck
Dieses Repo berechnet eine saisonale 4x20-Kompass-Regionalliga, erzeugt CSV + Karten- und Distanzauswertungen.

## Arbeitsprinzipien
- Änderungen klein und nachvollziehbar halten.
- Keine stillen Regeländerungen: bei Logikänderungen immer README mitziehen.
- Datenquellen bevorzugt in dieser Reihenfolge nutzen: `FuPa -> Wikipedia`.
- Bei Koordinaten zuerst Wikipedia/Wikidata, Nominatim nur als Fallback.

## Kernregeln (aktueller Modus)
- Standard ist die Reformlogik `12+4+14+2`.
- Zusammensetzung:
  - je Regionalliga Platz `2-13`
  - 4 Absteiger aus 3. Liga
  - 14 Oberliga-Meister
  - 2 Zusatzplätze (aktuell Bayern + Nordost)
- Reserve-/U-Teams sind im aktuellen Reformmodus erlaubt.

## Dateien mit zentraler Logik
- `kompass.py`: Datenbeschaffung, Saisonlogik, Clustering, CSV
- `kompass_report.py`: Karte + Distanzmetriken
- `season_transitions.json`: Marker-/Übergabedaten für Report

## Nach jeder Logikänderung
1. `python kompass.py`
2. `python kompass_report.py`
3. Kurzcheck:
   - CSV vorhanden
   - Karte vorhanden
   - `season_transitions.json` aktualisiert

## Nicht tun
- Keine destruktiven Git-Befehle.
- Keine Entfernung vorhandener Overrides ohne Ersatz.
- Keine unkommentierte Änderung an Quellenpriorität.
