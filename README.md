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
- Das gilt auch für Oberliga-Meister und Drittliga-Absteiger; ein Reserve-Meister wird nicht zugunsten des nächsten Erstteams übersprungen.
- Quellenpriorität: `FuPa -> Wikipedia`
- Drittliga-Absteiger werden für die Referenzkarte geografisch zugeordnet. Bestehende Zuordnungs-Overrides bleiben erhalten:
  - `TSV Havelse -> Nord`
  - `FC Erzgebirge Aue -> Nordost`
  - `SSV Ulm 1846 -> Südwest`
  - `1. FC Schweinfurt 05 -> Bayern`
- Sonderfall für die Quellsaison 2025/26 (Reform 2026/27): `Fortuna Düsseldorf II` wird trotz Tabellenplatz als Regionalliga-Absteiger behandelt. Dieser Override gilt nicht für die Quellsaison 2026/27.
- Auch der alte Namensalias `Fortuna Düsseldorf -> Fortuna Düsseldorf II` gilt nur für 2025/26. In 2026/27 bleibt die erste Mannschaft als Drittliga-Team erhalten; FuPa-Reservebezeichnungen werden anhand des Mannschaftslevels ergänzt.
- Neue Spielstätten 2026/27: SGV Heilbronn-Freiberg im [Frankenstadion Heilbronn](https://www.heilbronn.de/kommunikation/pressemitteilungen/details/artikel/ins-frankenstadion.html), Kaiserslautern II im [Fritz-Walter-Stadion](https://fck.de/fussball/u21/). Club- und Stadion-Overrides verwenden die Koordinaten der jeweiligen Wikipedia-Stadionartikel.

## Stadionkoordinaten
- Clustering, Distanzmetriken, CSVs, Karten und Übergangsmarker verwenden dieselben geprüften Heimspielstätten aus `stadium_overrides.json` für die Quellsaison. Ungeprüfte Stadt-/Club-Caches und alte Overrides gelten nicht als Stadionnachweis.
- Stand 14.10.2026 sind alle 109 angezeigten Vereine der Quellsaison 2026/27 geprüft. Der [Koordinaten-Audit](data/stadium_coordinate_audit_2026_27.csv) enthält alte und neue Punkte, Verschiebung, Quellen und Sonderfälle. 42 Punkte wurden um mehr als 500 Meter korrigiert.
- Am 21.10.2026 wurden Saisonnachweise für SV Meppen ([Hänsch-Arena](https://www.fupa.net/club/sv-meppen)), SC Fortuna Köln ([Südstadion](https://www.fupa.net/club/sc-fortuna-koeln)) und SSV Jahn Regensburg ([Jahnstadion Regensburg](https://www.fupa.net/club/ssv-jahn-regensburg)) ergänzt, damit auch diese Drittliga-Abstiegskandidaten verarbeitet werden können. Der alte Fortuna-Punkt wurde auf die Wikipedia-Stadionkoordinaten korrigiert.
- Zusätzlich sind die aktuellen Oberliga-Aufstiegskandidaten Eintracht Braunschweig II (B-Platz/Rheingoldarena), FC Wegberg-Beeck (Waldstadion Beeck), BSV Eintracht Mahlsdorf (Am Rosenhag) und ZFC Meuselwitz (bluechip-Arena) für 2026/27 geprüft; die Quellen stehen in den jeweiligen Overrides.
- Heimspielstätten: FuPa → Wikipedia; widersprüchliche Angaben und temporäre Einzelspielorte werden mit Vereins-/Verbandsseiten abgeglichen. Reserve-Teams werden separat geprüft und nicht automatisch dem Stadion der ersten Mannschaft zugeordnet.
- Koordinaten: direkte Stadionpunkte aus Wikipedia/Wikidata zuerst; bei fehlenden Punkten veröffentlichte Vereinskoordinaten oder Nominatim/OpenStreetMap als Fallback. Straßen, Gebäude, Tennisanlagen und Ortsmittelpunkte werden nicht als Fußballstadion akzeptiert. `coordinate_precision` unterscheidet Stadion-/Spielfeldpunkte von Punkten innerhalb einer größeren Sportanlage.
- Verwendet wird die aktuelle reguläre Heimspielstätte, keine noch unbestätigte Spielstätte nach einem möglichen Aufstieg. Sonderfälle stehen im jeweiligen Datensatz, etwa Havelse (zusätzlich zugelassenes Eilenriedestadion), Cham und Eichstätt (Einzelspiele an anderen Orten).
- Fehlende Saisonprüfung stoppt `kompass.py` mit einer Vereinsliste. Ein Report mit veralteten CSV-Koordinaten verlangt einen erneuten Lauf von `kompass.py`. Für historische oder neue Saisons müssen die entsprechenden Heimspielstätten zuerst geprüft werden; nicht aktuelle Override-Einträge bleiben erhalten.

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
  - Erzwungene RL-Absteiger werden auch hier übersprungen; fehlende Makroplätze werden mit dem nächsten Oberliga-Kandidaten derselben Makroregion aufgefüllt.
  - Projektannahme für stabile Folgejahre: `4` Direktaufsteiger in die 3. Liga, RL-Abstieg `West=3`, `Südwest=3`, `Nord/Nordost/Bayern-Block=8`.
- `Bayern-Vorrunden-Split`:
  - Jede der 5 bestehenden Regionalligen spielt eine gemeinsame Vorrunde.
  - Nach der Hinrunde teilt sich die Tabelle: Top-8 jeder RL (5×8 = 40 Teams) bilden **4 geografisch optimierte Meisterrunden-Staffeln à 10 Teams** und spielen dort Aufstiegsplätze zur 3. Liga aus.
  - Die übrigen Teams bleiben in ihrer bisherigen RL und spielen dort eine Abstiegsrunde (Ligagröße je Staffel variiert).
  - Hinweis: Die durchschnittliche Auswärtsdistanz der Meisterrunde ist nicht direkt mit dem 4x20-Modell vergleichbar (9 statt 19 Gegner pro Liga).

## Optimierung

### Stabilität zwischen Neuberechnungen
- Jeder erfolgreiche vollständige Lauf von `kompass.py` speichert die beste gefundene Kompass-Aufteilung (Rank 1) in `data/recalculation_history/<Quellsaison>_to_<Reformsaison>.json`. Ein vorhandener, konsistenter Ergebnisstand wird beim ersten Lauf als Ausgangsstand übernommen. Die Dateien müssen für Vergleiche über mehrere Wochen erhalten bleiben.
- Im HTML-Report stehen diese persönlichen Läufe unter **Modelle & Details → Archiv einzelner Berechnungsläufe**. Die Hauptkennzahlen zur Stabilität stammen aus dem festen Sonntagsverlauf. Im Laufarchiv zählt ein Staffelwechsel nur bei Vereinen, die in beiden aufeinanderfolgenden Läufen im Pool sind; die Prozentzahl bezieht sich auf diese gemeinsamen Vereine. Staffel-Zugänge/-Abgänge enthalten sowohl Wechsel als auch Pool-Ein-/Austritte.
- Staffeln werden für jeden Vergleich anhand der größten Mitgliederüberschneidung einander zugeordnet. Ein bloßer Tausch der Kompassnamen zählt nicht als Wechsel. „Veränderte Aufteilungen“ zählt Vergleiche mit mindestens einem Wechsel oder einer Änderung des Pools, keine vollständig ausgetauschten Staffeln.
- Ein Fingerabdruck der eingelesenen Tabellen unterscheidet geänderte Tabellen von einer erneuten Optimierung bei gleichem Tabellenstand. Änderungen an Regeln oder Suchparametern werden zusätzlich markiert; Wechsel sind kein alleiniger Nachweis für einen Einfluss der Tabellen. Beim übernommenen Ausgangsstand ist der frühere Tabellenstand unbekannt.
- Wiederholtes Erzeugen des Reports fügt keine Läufe hinzu. Ein identisches Ergebnis eines neuen Berechnungslaufs bleibt als Vergleich mit null Wechseln sichtbar; frühere Wochen werden nicht rückwirkend erfunden. Ein nicht zur aktuellen Ausgabe passender Verlauf wird nicht als aktueller Vergleich angezeigt.
- Zusätzlich: `outputs/json/recalculation_changes.json` und `outputs/csv/kompass_recalculation_changes_per_club.csv`. Der erste gespeicherte Lauf ist nur der Ausgangsstand; Wechselstatistiken beginnen mit dem zweiten Lauf.

### Wöchentliche Rekonstruktion

- `python kompass.py` aktualisiert für die laufende Quellsaison automatisch den Sonntagsverlauf. Danach erzeugt `python kompass_report.py` die HTML-Ausgabe und `docs/`. Ein Lauf am Mittwoch, 21.10.2026, verwendet für den Wochenvergleich Sonntag, 18.10.2026; ein aktueller Sonntag wird erst nach Tagesende aufgenommen. Auch mehrere verpasste Sonntage werden nachgeholt, ohne dass an diesen Tagen ein Lauf stattgefunden haben muss.
- `python kompass_weekly.py` kann den Wochenverlauf separat aktualisieren. Die datierten FuPa-Ergebnisse aller 20 Quellligen werden automatisch neu geladen, sobald der Cache den letzten abgeschlossenen Sonntag noch nicht vollständig abdeckt. Deckt er den Sonntag ab, bleibt ein erneuter Lauf in derselben Woche bei diesen Eingaben. `--refresh` lädt unabhängig davon erneut und übernimmt auch nachträgliche Wertungen. Jede geladene Ergebnismenge wird gegen die aktuellen FuPa-Tabellen geprüft. `--through YYYY-MM-DD` begrenzt den Verlauf, `--prepare-only` prüft Tabellen, Auswahlgrenzen und fehlende Stadien ohne Optimierung.
- Gemeinsamer Stichtag ist Sonntag, 23:59 Uhr in `Europe/Berlin`. Die erste Woche beginnt, sobald **alle 20 Ligen mindestens ein abgeschlossenes Spiel** haben. Ein noch laufender Sonntag wird ausgelassen. Für 2026/27 beginnt der Verlauf am 30.08.2026; Mittelrhein startete als letzte Liga am 28.08.2026. Gezählt wird das tatsächliche Spieldatum, nicht der angesetzte Spieltag; verschobene Spiele fließen erst nach Austragung ein.
- Das sind Rekonstruktionen mit **heutigem zertifizierten Spielwertungs- und Punktabzugsstand**, keine archivierten damaligen Veröffentlichungen. Nachträgliche Sportgerichtswertungen und Punktabzüge können frühere Wochen verändern. Zwischentabellen werden nach Punkten, Tordifferenz und erzielten Toren sortiert und gegen die veröffentlichte aktuelle Reihenfolge geprüft. Vollständig gleiche Werte werden alphabetisch geordnet und markiert; Gleichstände über einer Auswahlgrenze werden sichtbar ausgewiesen.
- Die 80er-Auswahl verwendet dieselbe Reformregel `12+4+14+2`. Nur die geografische Referenzzuordnung der Drittliga-Absteiger zu bisherigen Regionalligen wird beim Vorbereiten ausgelassen; sie beeinflusst die Auswahl nicht. Historische Eingaben dürfen nicht auf heutige Tabellen zurückfallen. Zusätzliche saisonverifizierte Spielstätten für die früheren Wochen stehen in `stadium_overrides.json`.
- Jede Woche erhält standardmäßig dieselben 50 Startläufe mit festen Seeds, kanonisch sortierten Vereinen und anschließender Elite-Suche (4 Eliten, je 2 Neustarts). Das Wochenprofil nutzt 500/3000/2000 Iterationen für Zentroid-/Matrix-/Komponentensuche und 500/5000/3000 in Phase 2, ohne LNS oder CP-SAT. `--runs` ändert das Budget für alle Wochen gemeinsam. Das Ergebnis ist die beste gefundene Lösung dieses Profils, ohne Optimalitätsgarantie; die Live-Berechnung kann mit größerem Budget anders ausfallen. Identische Pools mit identischen Koordinaten und Suchparametern verwenden dieselbe gespeicherte Lösung.
- `data/weekly_results_<Saison>.json` bewahrt datierte Ergebnisse und Quellen; `data/weekly_projections/<Quellsaison>_to_<Reformsaison>.json` bewahrt Tabellen, Aufteilungen und Wechselverlauf. Bereits berechnete Sonntagslösungen werden bei identischen Eingaben und Suchparametern aus diesem dauerhaften Archiv wiederverwendet, auch wenn der temporäre Cache in `outputs/` fehlt. Diese Dateien getrennt vom Archiv tatsächlich ausgeführter Live-Neuberechnungen erhalten. Wochenwechsel vergleichen Staffeln nach maximaler Mitgliederüberschneidung; Pool-Eintritte und -Austritte werden separat gezählt.
- Der HTML-Report gliedert sich in **Übersicht**, **Wochenverlauf** und **Modelle & Details**. Die Übersicht zeigt Live-Karte und Vereinssuche. Der Wochenverlauf zeigt die Stabilität, anklickbare Wochenbalken, Wochenkarten, Quelltabellen, die 80er-Zuordnung und Wechsel je Verein. Seine Kennzahlen basieren unabhängig vom persönlichen Ausführungstag auf Sonntagsständen. Exporte: `outputs/csv/kompass_weekly_changes.csv`, `outputs/csv/kompass_weekly_changes_per_club.csv` und `outputs/json/kompass_weekly_changes.json`. Die erste Woche bildet den Ausgangsstand und hat noch keinen Wechselwert.

### Wunschlisten-Optimierung
- Standardmäßig deaktiviert (`KOMPASS_WISH_SA_ENABLED=0`) und nicht im Report angeboten.
- Die reine Summe erfüllter Top-19-Wünsche ignoriert die Entfernung zu den übrigen Gegnern. Im Lauf für 2026/27 brachte die Variante nur 13 zusätzliche Wünsche, erhöhte aber die längste Reise von rund 500 auf 780 km und verlegte Freiburg II, Oberachern und Mechtersheim in die Ost-Staffel.
- Acht Neustarts mit Reisegrenzen aus der Matrix-Lösung und ein 120-Sekunden-Solverlauf fanden keine bessere zulässige Coverage. Das ist keine Optimalitätsgarantie.
- Bei experimenteller Aktivierung mit `KOMPASS_WISH_SA_ENABLED=1` werden nur Ergebnisse exportiert und angezeigt, die mehr Wünsche erfüllen und weder die längste Reise noch den höchsten Vereinsdurchschnitt der Matrix-Lösung überschreiten. Alte oder verworfene Wunschlisten-Karten werden aus dem Report und `docs/` entfernt.

### Metriken
- **Durchschnittliche Auswärtsreise (km)**: Für jeden Club der Durchschnitt der Entfernungen zu allen 19 Ligagegnern, dann Mittelwert über alle 80 Clubs. Die intuitive Kennzahl — z.B. "ein Club fährt im Schnitt 141 km pro Auswärtsfahrt".
- **Intra-Pair-Summe (km)**: Summe aller paarweisen Distanzen innerhalb jeder Liga (4 x 190 = 760 Paare). Das ist die Zielfunktion, die der Optimierer minimiert. Zusammenhang: `Ø Auswärtsreise = Intra-Pair-Summe / 760`.

### 3-Phasen-Heuristik

**Phase 1 — Multi-Start-Suche** (Standard: 500 Runs)
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
- `data/regionalliga_2026_27.json` — RL-Teilnehmerliste 2026/27 aus FuPa, einschließlich Reserve-Teamnummern; die historische Liste 2025/26 bleibt erhalten
- `season_transitions.json` — Auf-/Abstiegsmarker, inkl. modellbezogener Transition-Daten
- `tests/test_utils.py` — Offline-Tests für Hilfsfunktionen, Saison- und Quellenlogik

## Ausgaben
### CSV (`outputs/csv/`)
- `kompass_regionalliga_4x20.csv` — Rank 1 (Hauptausgabe)
- `kompass_current_regionalliga_after_transitions.csv` — bisherige 5 Regionalligen nach Auf-/Abstieg als Referenzkarte
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
- `kompass_current_regionalliga_after_transitions_map.html` — bisherige 5 Regionalligen nach Auf-/Abstieg
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
- `KOMPASS_SEASON` is the source season (Default `2026/27`); current tables build a provisional 2027/28 reform pool. Promotion/relegation markers are model projections, not confirmed season results. The report and `season_transitions.json` record both seasons and the projection status.
- FuPa remains the preferred source for the active season. Its configured standing URLs do not select historical seasons, so historical runs use the season-specific Wikipedia tables instead; this prevents mixed-season pools after a season rollover.
- FuPa team levels are preserved as `II`/`III` suffixes, and tables with a different season in their team slugs are rejected before falling back to Wikipedia.
- Wikipedia/Wikidata coordinate requests use a contact URL in the User-Agent, paced requests, and retries for HTTP 429/503 that respect `Retry-After`, following the [Wikimedia rate-limit guidance](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits).

### Phase 1
- `KOMPASS_MULTI_START_RUNS` (Default `500`)
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
- `KOMPASS_CPSAT_ENABLED` (Default `1`, deaktivieren mit `0`; wird ohne installiertes `ortools` übersprungen)
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
