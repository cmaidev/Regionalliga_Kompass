# Kompass-Regionalliga 4x20

Dieses Projekt berechnet eine geografisch optimierte 4x20-Regionalliga auf Basis einer saisonalen Reformlogik. Teamdaten werden gesammelt, Koordinaten ermittelt, Vereine auf vier Ligen verteilt und die Ergebnisse als CSV, JSON sowie Kartenansichten ausgegeben.

## Projektziel
- 80 Vereine in vier Regionalligen mit je 20 Teams zusammenstellen
- Distanzen zwischen Vereinen auswerten
- Saisonuebergaenge (Auf-/Abstieg) nachvollziehbar markieren

## Kernlogik
- Standardmodus: `12+4+14+2`
- Zusammensetzung:
  - je Regionalliga Platz `2-13`
  - 4 Absteiger aus der 3. Liga
  - 14 Oberliga-Meister
  - 2 Zusatzplaetze (aktuell Bayern + Nordost)
- Reserve-/U-Teams sind im aktuellen Reformmodus erlaubt
- Quellenprioritaet: `FuPa -> Wikipedia`

## Optimierungsmodus (aktuell)
- Hauptausgabe ist die **Distanzmatrix-Optimierung (Rank 1)**.
- Die Suche nutzt eine **2-Phasen-Heuristik**:
  - Phase 1: Multi-Start (standardmaessig `2000` Runs)
  - Phase 2: Elite-Restarts auf den besten bzw. diversen Phase-1-Loesungen
- Es werden mehrere Initial-Seeds verwendet:
  - `initial_auto` (urspruenglicher KMeans-Start)
  - `initial_north_south_extreme` (20 noerdlichste + 20 suedlichste fix)
  - `initial_west_east_extreme` (20 westlichste + 20 oestlichste fix)
  - optional `initial_manual` via CSV-Override
- Zielmetrik fuer Ranking: durchschnittliche Auswaertsdistanz pro Verein.
- Fokus ist jetzt ausschliesslich Distanzmatrix (keine Centroid-Vergleichsausgabe mehr).
- Ausgabe-Ordner:
  - CSV: `outputs/csv/`
  - HTML: `outputs/html/`
  - JSON: `outputs/json/`
- Wichtige Ausgaben:
  - `outputs/csv/kompass_regionalliga_4x20.csv` (Rank 1, Hauptausgabe)
  - `outputs/csv/kompass_regionalliga_4x20_initial.csv` (Initialverteilung vor Optimierung)
  - `outputs/csv/kompass_regionalliga_4x20_initial_auto.csv` (automatisch erzeugte Initialverteilung)
  - `outputs/csv/kompass_regionalliga_4x20_initial_north_south.csv` (Initialverteilung Nord/Sued-Extrem)
  - `outputs/csv/kompass_regionalliga_4x20_initial_west_east.csv` (Initialverteilung West/Ost-Extrem)
  - `outputs/csv/kompass_regionalliga_4x20_initial_manual.csv` (manuell geladene Initialverteilung, falls gesetzt)
  - `outputs/csv/kompass_regionalliga_4x20_matrix.csv` (Rank 1, kompatibel)
  - `outputs/csv/kompass_regionalliga_4x20_matrix_rank2.csv` (Rank 2)
  - `outputs/csv/kompass_regionalliga_4x20_matrix_rank3.csv` (Rank 3)
  - `outputs/csv/kompass_regionalliga_4x20_matrix_rank5.csv` (Rank 5)
  - `outputs/csv/kompass_regionalliga_4x20_matrix_rank10.csv` (Rank 10)
  - `outputs/csv/kompass_regionalliga_4x20_matrix_worst.csv` (schlechteste gefundene Loesung)
  - `outputs/json/kompass_solutions_ranked.json` (Top-Loesungen inkl. Score/Gap)
  - `outputs/csv/kompass_solution_diff.csv` (Vereine mit unterschiedlicher Liga in Rank1/Rank2)

## Karten und Koordinaten
- `kompass_report.py` erstellt:
  - `outputs/html/kompass_regionalliga_4x20_map.html` (Rank 1)
  - `outputs/html/kompass_regionalliga_4x20_map_initial.html` (Initialverteilung, falls vorhanden)
  - `outputs/html/kompass_regionalliga_compare_initial_auto_manual.html` (Vergleich Auto-Initial vs Manuell-Initial, falls vorhanden)
  - `outputs/html/kompass_regionalliga_4x20_map_rank2.html` (Rank 2, falls vorhanden)
  - `outputs/html/kompass_regionalliga_4x20_map_rank3.html` (Rank 3, falls vorhanden)
  - `outputs/html/kompass_regionalliga_4x20_map_rank5.html` (Rank 5, falls vorhanden)
  - `outputs/html/kompass_regionalliga_4x20_map_rank10.html` (Rank 10, falls vorhanden)
  - `outputs/html/kompass_regionalliga_4x20_map_worst.html` (Worst found, falls vorhanden)
  - `outputs/html/kompass_regionalliga_compare_worst.html` (Vergleich Rank 1 vs Worst found)
  - `outputs/html/kompass_regionalliga_compare_initial.html` (Vergleich Initial vs Rank 1)
  - `outputs/html/index.html` mit Schaltern fuer Initial / Rank 1 / Worst found
  - `outputs/json/stadium_coords_snapshot.json` als Stadion-Koordinaten-Snapshot

## Wichtige Dateien
- `kompass.py`: Datenbeschaffung, Saisonlogik, Optimierung, CSV/JSON-Export
- `kompass_report.py`: Karten, Distanzmetriken, `outputs/html/index.html`, Stadion-Snapshot
- `data/regionalliga_2025_26.json`: statische RL-Teilnehmerliste 2025/26 (Basisdaten)
- `season_transitions.json`: Marker- und Uebergabedaten

## Konfigurierbare Optimierungsparameter (optional)
- `KOMPASS_MULTI_START_RUNS` (Default `2000`)
- `KOMPASS_MULTI_START_KMEANS_N_INIT` (Default `5`)
- `KOMPASS_MULTI_START_CENTROID_ITERS` (Default `2000`)
- `KOMPASS_MULTI_START_MATRIX_ITERS` (Default `9000`)
- `KOMPASS_MULTI_START_COMPONENT_ITERS` (Default `7000`, nur mit Derby-Regel)
- `KOMPASS_MULTI_START_BASE_SEED` (Default `1000`)
- `KOMPASS_MULTI_START_SHAKE_SWAP_FRACTION` (Default `0.02`)
- `KOMPASS_MATRIX_ACCEPT_EQUAL_PROB` (Default `0.02`)
- `KOMPASS_MATRIX_ANNEAL_START_TEMP_KM` (Default `60.0`)
- `KOMPASS_MATRIX_ANNEAL_END_TEMP_KM` (Default `1.0`)
- `KOMPASS_MATRIX_MOVE_2_PROB` (Default `0.80`, Gewicht fuer 2er-Tausch)
- `KOMPASS_MATRIX_MOVE_3_PROB` (Default `0.15`, Gewicht fuer 3er-Tausch)
- `KOMPASS_MATRIX_MOVE_4_PROB` (Default `0.05`, Gewicht fuer 4er-Tausch)
- `KOMPASS_MATRIX_STAGNATION_SHAKE_ITERS` (Default `2500`, danach Diversifikations-Shake)
- `KOMPASS_MATRIX_STAGNATION_SHAKE_FRACTION` (Default `0.02`, Anteil Teams pro Shake)
- `KOMPASS_PHASE2_ELITE_COUNT` (Default `8`)
- `KOMPASS_PHASE2_ELITE_SELECTION_MODE` (Default `diverse`; `diverse` oder `score`)
- `KOMPASS_PHASE2_DIVERSE_POOL_MULTIPLIER` (Default `6`, Poolgroesse fuer diverse Elite-Auswahl)
- `KOMPASS_PHASE2_DIVERSE_MAX_SCORE_GAP_KM` (Default `4.0`, max. Score-Abstand zum Besten im diversen Pool)
- `KOMPASS_PHASE2_RESTARTS_PER_ELITE` (Default `5`)
- `KOMPASS_PHASE2_BASE_SEED` (Default `100000`)
- `KOMPASS_PHASE2_CENTROID_ITERS` (Default `1500`)
- `KOMPASS_PHASE2_MATRIX_ITERS` (Default `15000`)
- `KOMPASS_PHASE2_COMPONENT_ITERS` (Default `12000`, nur mit Derby-Regel)
- `KOMPASS_PHASE2_SHAKE_SWAP_FRACTION` (Default `0.08`)
- `KOMPASS_PHASE2_ACCEPT_EQUAL_PROB` (Default `0.05`)
- `KOMPASS_PHASE2_ANNEAL_START_TEMP_KM` (Default `120.0`)
- `KOMPASS_PHASE2_ANNEAL_END_TEMP_KM` (Default `2.0`)
- `KOMPASS_PHASE2_MOVE_2_PROB` (Default wie Phase 1)
- `KOMPASS_PHASE2_MOVE_3_PROB` (Default wie Phase 1)
- `KOMPASS_PHASE2_MOVE_4_PROB` (Default wie Phase 1)
- `KOMPASS_PHASE2_STAGNATION_SHAKE_ITERS` (Default halb so hoch wie Phase 1)
- `KOMPASS_PHASE2_STAGNATION_SHAKE_FRACTION` (Default hoeher als Phase 1)
- `KOMPASS_INITIAL_CSV_OVERRIDE` (optionaler Pfad zu einer manuellen Initial-CSV mit Spalten `Liga`,`Verein`)

## Empfohlener Heuristik-Workflow
```powershell
$env:KOMPASS_MULTI_START_RUNS="2000"
$env:KOMPASS_PHASE2_ELITE_COUNT="8"
$env:KOMPASS_PHASE2_RESTARTS_PER_ELITE="5"
python kompass.py
python kompass_report.py
```

## Breite Suche (aggressiv)
```powershell
$env:KOMPASS_MULTI_START_RUNS="10000"
$env:KOMPASS_PHASE2_ELITE_COUNT="16"
$env:KOMPASS_PHASE2_RESTARTS_PER_ELITE="12"
$env:KOMPASS_MULTI_START_SHAKE_SWAP_FRACTION="0.05"
$env:KOMPASS_PHASE2_SHAKE_SWAP_FRACTION="0.12"
$env:KOMPASS_MATRIX_MOVE_2_PROB="0.65"
$env:KOMPASS_MATRIX_MOVE_3_PROB="0.25"
$env:KOMPASS_MATRIX_MOVE_4_PROB="0.10"
$env:KOMPASS_MATRIX_STAGNATION_SHAKE_ITERS="1800"
$env:KOMPASS_MATRIX_STAGNATION_SHAKE_FRACTION="0.04"
$env:KOMPASS_PHASE2_MOVE_2_PROB="0.55"
$env:KOMPASS_PHASE2_MOVE_3_PROB="0.30"
$env:KOMPASS_PHASE2_MOVE_4_PROB="0.15"
$env:KOMPASS_PHASE2_STAGNATION_SHAKE_ITERS="1200"
$env:KOMPASS_PHASE2_STAGNATION_SHAKE_FRACTION="0.08"
python kompass.py
python kompass_report.py
```

## Schnellstart
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python kompass.py
python kompass_report.py
```

## GitHub Pages
https://cmaidev.github.io/Regionalliga_Kompass/

## Credits
Dieses Projekt wurde mit Hilfe von **GPT-5.3-Codex** erstellt und weiterentwickelt.
