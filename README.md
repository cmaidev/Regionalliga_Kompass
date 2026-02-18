# Kompass-Regionalliga 4x20

Dieses Projekt berechnet eine geografisch optimierte 4x20-Regionalliga auf Basis einer saisonalen Reformlogik. Teamdaten werden gesammelt, Koordinaten ermittelt, Vereine auf vier Ligen verteilt und die Ergebnisse als CSV sowie Kartenansichten ausgegeben.

## Projektziel
- 80 Vereine in vier Regionalligen mit je 20 Teams zusammenstellen
- Distanzen zwischen Vereinen auswerten
- Saisonübergänge (Auf-/Abstieg) nachvollziehbar markieren

## Kernlogik
- Standardmodus: `12+4+14+2`
- Zusammensetzung:
  - je Regionalliga Platz `2-13`
  - 4 Absteiger aus der 3. Liga
  - 14 Oberliga-Meister
  - 2 Zusatzplätze (aktuell Bayern + Nordost)
- Reserve-/U-Teams sind im aktuellen Reformmodus erlaubt
- Quellenpriorität: `FuPa -> Wikipedia`

## Optimierungsmodus (aktuell)
- Hauptausgabe ist die **Distanzmatrix-Optimierung**.
- `kompass_regionalliga_4x20.csv` enthält die Hauptlösung (Distanzmatrix).
- `kompass_regionalliga_4x20_matrix.csv` enthält ebenfalls die Distanzmatrix-Lösung (Kompatibilität).
- `kompass_regionalliga_4x20_centroid.csv` enthält die Centroid-Lösung als Vergleich.

## Wichtige Dateien
- `kompass.py`: Datenbeschaffung, Saisonlogik, Clustering, CSV-Export
- `kompass_report.py`: Karten und Distanzmetriken
- `season_transitions.json`: Marker- und Übergabedaten
- `index.html`: GitHub-Pages-Startseite mit Hauptkarte und Vereinsübersicht

## Schnellstart
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python kompass.py
python kompass_report.py
```

## GitHub Pages
`https://cmaidev.github.io/Regionalliga_Kompass/`

## Credits
Dieses Projekt wurde mit Hilfe von **GPT-5.3-Codex** erstellt und weiterentwickelt.
