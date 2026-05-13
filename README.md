# Kompass-Regionalliga 4x20

Dieses Projekt berechnet eine geografisch optimierte 4x20-Regionalliga auf Basis einer saisonalen Reformlogik. Teamdaten werden gesammelt, Koordinaten ermittelt, Vereine auf vier Ligen verteilt und die Ergebnisse als CSV, JSON sowie Kartenansichten ausgegeben.

## Projektziel
- 80 Vereine in vier Regionalligen mit je 20 Teams zusammenstellen
- Auswärtsdistanzen zwischen Vereinen minimieren
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

## Vergleichsmodelle
- `Kompassmodell` bleibt das Standardmodell des Repos.
- `Regionenmodell` wird zusätzlich als feste Vergleichsvariante exportiert.
- Projektannahmen für das Regionenmodell:
  - `West` und `Südwest` bleiben als eigene 20er-Staffeln erhalten.
  - `Nord`, `Nordost` und `Bayern` bilden zunächst einen gemeinsamen 40er-Block.
  - Der 40er-Block wird anschließend geografisch balanciert in `Nord` und `Ost` geteilt.
  - Oberliga-Meister werden zuerst ihrer Makroregion zugeordnet:
    - `West`: Westfalen, Niederrhein, Mittelrhein
    - `Südwest`: Baden-Württemberg, Hessen, Rheinland-Pfalz/Saar
    - `Nord/Nordost/Bayern`: Niedersachsen, Schleswig-Holstein, Hamburg, Bremen, NOFV Nord, NOFV Süd, Bayernliga Nord, Bayernliga Süd
  - Projektannahme für stabile Folgejahre: `4` Direktaufsteiger in die 3. Liga, RL-Abstieg `West=3`, `Südwest=3`, `Nord/Nordost/Bayern-Block=8`.
- `Bayern-Vorrunden-Split`:
  - Jede der 5 bestehenden Regionalligen spielt eine gemeinsame Vorrunde.
  - Nach der Hinrunde teilt sich die Tabelle: Top-8 jeder RL (5×8 = 40 Teams) bilden **4 geografisch optimierte Meisterrunden-Staffeln à 10 Teams** und spielen dort Aufstiegsplätze zur 3. Liga aus.
  - Die übrigen Teams bleiben in ihrer bisherigen RL und spielen dort eine Abstiegsrunde (Ligagröße je Staffel variiert).
  - Hinweis: Die durchschnittliche Auswärtsdistanz der Meisterrunde ist nicht direkt mit dem 4x20-Modell vergleichbar (9 statt 19 Gegner pro Liga).

## Optimierung

### Metriken
- **Durchschnittliche Auswärtsreise (km)**: Für jeden Club der Durchschnitt der Entfernungen zu allen 19 Ligagegnern, dann Mittelwert über alle 80 Clubs. Die intuitive Kennzahl — z.B. "ein Club fährt im Schnitt 141 km pro Auswärtsfahrt".
- **Intra-Pair-Summe (km)**: Summe aller paarweisen Distanzen innerhalb jeder Liga (4 x 190 = 760 Paare). Das ist die Zielfunktion, die der Optimierer minimiert. Zusammenhang: `Ø Auswärtsreise = Intra-Pair-Summe / 760`.

### 3-Phasen-Heuristik

**Phase 1 — Multi-Start-Suche** (Standard: 2000 Runs)
- KMeans-Initialisierung + Simulated Annealing mit 2er/3er/4er-Tausch
- Stagnation-Shake zur Diversifikation

**Phase 2 — Elite-Restarts**
- Die besten/diversesten Phase-1-Lösungen werden intensiv nachoptimiert
- Höhere Anneal-Temperatur und mehr Iterationen

**Phase 3 — LNS (Large Neighborhood Search)**
- Ruin & Recreate: 35% der Zuordnungen zerstören, greedy via Centroid-Distanz reparieren
- Greedy Descent über 200 Iterationen
- Konfigurierbar via `KOMPASS_LNS_ITERATIONS`, `KOMPASS_LNS_DESTROY_FRACTION`
- Deaktivierbar: `KOMPASS_LNS_ENABLED=0`

### Diverse Initialisierungen
Neben KMeans werden 10 verschiedene Start-Seeds verwendet, um lokale Optima zu vermeiden:
- `initial_auto` — KMeans-Start
- `initial_north_south_extreme` / `initial_west_east_extreme` — extreme geografische Splits
- `initial_lat_stripes` / `initial_lon_stripes` — Streifen nach Breiten-/Längengrad
- `initial_diag_nw_se` / `initial_diag_ne_sw` — diagonale Streifen
- `initial_random_1..3` — zufällige balancierte Partitionen

**Phase 4 — CP-SAT Solver** (optional, `KOMPASS_CPSAT_ENABLED=1`)
- Exakter Solver via Google OR-Tools (`pip install ortools`)
- Nutzt die beste Heuristik-Lösung als Warm-Start
- CP-SAT setzt intern SAT, LP und LNS parallel ein
- Für n=80 in 120s: Ergebnis ~0.3% über Heuristik
- Zeitlimit konfigurierbar via `KOMPASS_CPSAT_TIME_LIMIT` (Default 120s)

## Dateistruktur
- `kompass.py` — Datenbeschaffung, Saisonlogik, Optimierung, CSV/JSON-Export
- `kompass_report.py` — Karten (Folium), Distanzmetriken, `index.html`, GitHub-Pages-Sync
- `kompass_utils.py` — Shared Utilities (normalize_text, haversine_km, Club-Klasse)
- `data/regionalliga_2025_26.json` — statische RL-Teilnehmerliste 2025/26
- `season_transitions.json` — Auf-/Abstiegsmarker, inkl. modellbezogener Transition-Daten
- `tests/test_utils.py` — 42 Offline-Tests

## Ausgaben
### CSV (`outputs/csv/`)
- `kompass_regionalliga_4x20.csv` — Rank 1 (Hauptausgabe)
- `kompass_regionalliga_4x20_regionenmodell.csv` — feste Regionenmodell-Variante
- `kompass_bayern_meisterrunde.csv` — Bayern-Vorrunden-Split: Meisterrunde (4×10, geografisch optimiert)
- `kompass_bayern_abstiegsrunde.csv` — Bayern-Vorrunden-Split: Abstiegsrunde (5 RL, variable Größe)
- `kompass_regionalliga_4x20_matrix_rank2.csv` bis `_rank10.csv` — weitere Top-Lösungen
- `kompass_regionalliga_4x20_matrix_worst.csv` — schlechteste Lösung
- `kompass_regionalliga_4x20_initial*.csv` — verschiedene Initialverteilungen
- `kompass_solution_diff.csv` — Unterschiede zwischen Rank 1 und Rank 2
- `kompass_away_metrics_per_club.csv` / `_per_league.csv` — Distanzmetriken
- `kompass_longest_trips.csv` — längste Einzelreisen

### JSON (`outputs/json/`)
- `kompass_solutions_ranked.json` — Top-Lösungen mit Score, Gap und Teamlisten
- `stadium_coords_snapshot.json` — Stadion-Koordinaten-Snapshot

### HTML (`outputs/html/`)
- `index.html` — Übersichtsseite mit Kartenschalten
- `kompass_regionalliga_4x20_map.html` — Rank 1 Karte
- `kompass_regionalliga_4x20_map_regionenmodell.html` — Regionenmodell-Karte
- `kompass_bayern_meisterrunde_map.html` — Bayern-Vorrunden-Split: Meisterrunde
- `kompass_bayern_abstiegsrunde_map.html` — Bayern-Vorrunden-Split: Abstiegsrunde
- `kompass_regionalliga_4x20_map_initial.html` — Initialverteilung
- `kompass_regionalliga_4x20_map_worst.html` — schlechteste Lösung
- Vergleichskarten (u.a. Rank 1 vs Regionenmodell, Initial vs Rank 1, Rank 1 vs Worst)

## Schnellstart
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python kompass.py
python kompass_report.py
```

## Tests
```bash
python -m pytest tests/ -v
```

## Konfiguration (Umgebungsvariablen)

### Saison
- `KOMPASS_SEASON` (Default `2025/26`)

### Phase 1
- `KOMPASS_MULTI_START_RUNS` (Default `2000`)
- `KOMPASS_MULTI_START_KMEANS_N_INIT` (Default `5`)
- `KOMPASS_MULTI_START_CENTROID_ITERS` (Default `2000`)
- `KOMPASS_MULTI_START_MATRIX_ITERS` (Default `9000`)
- `KOMPASS_MULTI_START_COMPONENT_ITERS` (Default `7000`)
- `KOMPASS_MULTI_START_BASE_SEED` (Default `1000`)
- `KOMPASS_MULTI_START_SHAKE_SWAP_FRACTION` (Default `0.02`)
- `KOMPASS_MATRIX_ANNEAL_START_TEMP_KM` (Default `60.0`)
- `KOMPASS_MATRIX_ANNEAL_END_TEMP_KM` (Default `1.0`)
- `KOMPASS_MATRIX_MOVE_2_PROB` / `_3_PROB` / `_4_PROB` (Default `0.80` / `0.15` / `0.05`)
- `KOMPASS_MATRIX_STAGNATION_SHAKE_ITERS` (Default `2500`)

### Phase 2
- `KOMPASS_PHASE2_ELITE_COUNT` (Default `8`)
- `KOMPASS_PHASE2_ELITE_SELECTION_MODE` (Default `diverse`)
- `KOMPASS_PHASE2_RESTARTS_PER_ELITE` (Default `5`)
- `KOMPASS_PHASE2_BASE_SEED` (Default `100000`)
- `KOMPASS_PHASE2_MATRIX_ITERS` (Default `15000`)
- `KOMPASS_PHASE2_ANNEAL_START_TEMP_KM` (Default `120.0`)

### Phase 3 (LNS)
- `KOMPASS_LNS_ENABLED` (Default `1`, deaktivieren mit `0`)
- `KOMPASS_LNS_ITERATIONS` (Default `200`)
- `KOMPASS_LNS_DESTROY_FRACTION` (Default `0.35`)

### Phase 4 (CP-SAT, optional)
- `KOMPASS_CPSAT_ENABLED` (Default `0`, aktivieren mit `1`)
- `KOMPASS_CPSAT_TIME_LIMIT` (Default `120`, in Sekunden)

### Sonstiges
- `KOMPASS_INITIAL_CSV_OVERRIDE` — Pfad zu manueller Initial-CSV

## Empfohlener Workflow
```powershell
# Standard (ca. 10-15 Min)
python kompass.py
python kompass_report.py

# Breite Suche (aggressiv)
$env:KOMPASS_MULTI_START_RUNS="10000"
$env:KOMPASS_PHASE2_ELITE_COUNT="16"
$env:KOMPASS_PHASE2_RESTARTS_PER_ELITE="12"
python kompass.py
python kompass_report.py
```

## GitHub Pages
Die Ausgabe wird aus `docs/` bereitgestellt (Repository-Settings: Branch `main`, Folder `/docs`).

`python kompass_report.py` synchronisiert automatisch `outputs/html/` nach `docs/` (inkl. `.nojekyll`).

Nach jedem Lauf die geänderten `docs/*.html` committen.

https://cmaidev.github.io/Regionalliga_Kompass/
