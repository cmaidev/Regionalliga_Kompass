# Kompass-Regionalliga 4x20

Geografische Neu-Zusammensetzung von 80 Vereinen in 4 Ligen mit je 20 Teams, inklusive Karten, Distanz-Auswertung und Saisonlogik (Auf-/Abstieg).

## Stand
- Datenstand (letzter Lauf): **2026-02-18 14:08:56**
- Modus: **Reformregel 12+4+14+2** aktiv
- Derby-Regel: **deaktiviert** (`ENFORCE_DERBY_SAME_LEAGUE = False`)
- Quellen-Priorität: `FuPa` -> `Wikipedia`

## Schnellstart
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python kompass.py
python kompass_report.py
```

## Was erzeugt wird
- `kompass_regionalliga_4x20.csv`: Haupt-Ergebnis (Liga + Verein + `lat`/`lon`)
- `kompass_regionalliga_4x20_matrix.csv`: Distanzmatrix-Variante
- `kompass_regionalliga_4x20_map.html`: Karte zur Haupt-Lösung
- `kompass_regionalliga_4x20_map_matrix.html`: Karte zur Matrix-Variante
- `kompass_regionalliga_compare.html`: HTML-Vergleich beider Karten
- `kompass_away_metrics_per_club.csv`: Auswärts-Kennzahlen je Verein
- `kompass_away_metrics_per_league.csv`: Auswärts-Kennzahlen je Liga
- `kompass_longest_trips.csv`: längste Reisen
- `kompass_all_pair_distances.csv`: alle Paar-Distanzen
- `season_transitions.json`: markierte Auf-/Absteiger
- `added_teams.log`: hinzugefügte Teams inkl. Quelle
- `club_coords_cache.json`: Koordinaten-Cache

## Bedeutung von `lat` und `lon`
- `lat` = Breitengrad (Latitude)
- `lon` = Längengrad (Longitude)

Damit wird die Luftlinien-Distanz (Haversine) zwischen Vereinen berechnet.

## Aktuelle Ligasortierung (Haupt-CSV)

### Nord (20)
- 1. FC Germania Egestorf/Langreder
- 1. FC Phoenix Lübeck
- Bremer SV
- ETSV Hamburg
- FC Gütersloh
- Hamburger SV
- Hannover 96
- HSC Hannover
- Kickers Emden
- SC Paderborn 07
- SC Weiche Flensburg 08
- Sportfreunde Lotte
- SSV Jeddeloh
- SV Drochtersen/Assel
- SV Todesfelde
- SV Werder Bremen
- TSV Havelse
- TV Eiche Horn
- VfB Lübeck
- VfB Oldenburg

### West (20)
- 1. FC Bocholt
- 1. FC Köln
- Bonner SC
- Borussia Dortmund
- Borussia Mönchengladbach
- FC 08 Homburg
- FC Eddersheim
- FC Schalke 04
- FK Pirmasens
- Fortuna Düsseldorf
- FSV Frankfurt
- FSV Mainz 05
- Kickers Offenbach
- Ratingen 04/19
- Rot-Weiss Oberhausen
- SG Wattenscheid 09
- Sportfreunde Siegen
- SV Bergisch Gladbach 09
- SV Eintracht Trier
- TSV Steinbach Haiger

### Ost (20)
- 1. FC Magdeburg
- 1. FC Schweinfurt 05
- BFC Preußen
- BSV Eintracht Mahlsdorf
- Chemnitzer FC
- FC Carl Zeiss Jena
- FC Erzgebirge Aue
- FC Rot-Weiss Erfurt
- FSV 63 Luckenwalde
- FSV Zwickau
- Greifswalder FC
- Hallescher FC
- Hertha BSC
- KSV Hessen Kassel
- SG Barockstadt Fulda-Lehnerz
- SpVgg Bayreuth
- SV Babelsberg 03
- SV Tasmania Berlin
- VSG Altglienicke
- ZFC Meuselwitz

### Süd (20)
- ASV Neumarkt
- DJK Vilzing
- FC Bayern München
- FC Memmingen
- FC-Astoria Walldorf
- FV Illertissen
- SG Sonnenhof Großaspach
- SpVgg Ansbach 09
- SpVgg Greuther Fürth
- SpVgg Unterhaching
- SSV Ulm 1846
- Stuttgarter Kickers
- SV Sandhausen
- TSV Aubstadt
- TSV Buchbach
- TSV Landsberg
- VfB Eichstätt
- VfR Mannheim
- Wacker Burghausen
- Würzburger Kickers

## Aktuelle Distanz-Snapshots
- Durchschnitt Auswärtsdistanz pro Verein: **146.83 km**
- Längste Einzelreise: **1. FC Schweinfurt 05 -> Greifswalder FC (499.80 km)**
- Durchschnittliche Liga-Distanzen:
  - Nord: **134.54 km**
  - West: **124.33 km**
  - Ost: **180.27 km**
  - Süd: **148.18 km**

## HTML-Karten einbinden
Direkt im GitHub-README lässt sich eine interaktive lokale HTML-Datei nicht sauber einbetten (`iframe`/Scripts werden dort eingeschränkt).

Mögliche Wege:
- Im README auf die Datei verlinken, z. B. auf `kompass_regionalliga_4x20_map.html`.
- Für echte interaktive Ansicht: GitHub Pages aktivieren und die HTML dort hosten, dann im README den Pages-Link setzen.
- Als Ergänzung: statischen Screenshot (`.png`) im README anzeigen und zusätzlich auf die interaktive Seite verlinken.

### GitHub Pages (empfohlen)
1. In GitHub: `Settings` -> `Pages`
2. Unter `Build and deployment` bei `Source` auf `Deploy from a branch`
3. Branch `main` und Ordner `/ (root)` wählen
4. Speichern und ca. 1-2 Minuten warten
5. Danach ist die Startseite unter `https://<username>.github.io/<repo>/` erreichbar

Die Startseite liegt in `index.html` und verlinkt auf:
- `kompass_regionalliga_4x20_map.html`
- `kompass_regionalliga_4x20_map_matrix.html`
- `kompass_regionalliga_compare.html`

## Marker-Logik auf der Karte
- Liga-Zugehörigkeit: Farbe (Nord/West/Ost/Süd)
- Regionalliga-Absteiger: einheitlicher Ring
- Regionalliga-Meister (Aufsteiger in 3. Liga): einheitliches Dreieck
- 3.-Liga-Absteiger: einheitliches Quadrat (Form-only)
- Oberliga-Aufsteiger: einheitliches Pentagon (Form-only)

## Wichtige Konfigurationsschalter (`kompass.py`)
- `USE_REFORM_12_4_14_RULE`
- `USE_RULE_BASED_SEASON_LOGIC`
- `REFORM_EXTRA_STARTPLACES`
- `TABLE_SOURCE_PRIORITY`
- `ENFORCE_DERBY_SAME_LEAGUE`
- `DERBY_MAX_DISTANCE_KM`
- `ENABLE_DISTANCE_MATRIX_VARIANT`

## Hinweise
- APIs können sich ändern (Wikipedia/Wikidata/FuPa). Bei Abweichungen: Cache leeren und neu laufen lassen.
- Koordinaten werden in `club_coords_cache.json` gespeichert, damit Folgeläufe schneller und stabiler sind.
- Karten zeigen Distanz-Unterschiede zwischen Haupt- und Matrix-Variante optional mit schwarzer Umrandung (falls vorhanden).

## Credits
Dieses Projekt wurde mit Hilfe von **GPT-5.3-Codex** erstellt und weiterentwickelt.
