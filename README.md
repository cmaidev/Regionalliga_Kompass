# Kompass-Regionalliga 4x20

Geografische Neu-Zusammensetzung von 80 Vereinen in 4 Ligen mit je 20 Teams, inklusive Karten, Distanz-Auswertung und Saisonlogik (Auf-/Abstieg).

## Stand
- Datenstand (letzter Lauf): **2026-02-18 14:08:56**
- Modus: **Reformregel 12+4+14+2** aktiv
- Derby-Regel: **deaktiviert** (`ENFORCE_DERBY_SAME_LEAGUE = False`)
- Quellen-Prioritaet: `FuPa` -> `Wikipedia`

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
- `kompass_regionalliga_4x20_map.html`: Karte zur Haupt-Loesung
- `kompass_regionalliga_4x20_map_matrix.html`: Karte zur Matrix-Variante
- `kompass_regionalliga_compare.html`: HTML-Vergleich beider Karten
- `kompass_away_metrics_per_club.csv`: Auswaerts-Kennzahlen je Verein
- `kompass_away_metrics_per_league.csv`: Auswaerts-Kennzahlen je Liga
- `kompass_longest_trips.csv`: laengste Reisen
- `kompass_all_pair_distances.csv`: alle Paar-Distanzen
- `season_transitions.json`: markierte Auf-/Absteiger
- `added_teams.log`: hinzugefuegte Teams inkl. Quelle
- `club_coords_cache.json`: Koordinaten-Cache

## Bedeutung von `lat` und `lon`
- `lat` = Breitengrad (Latitude)
- `lon` = Laengengrad (Longitude)

Damit wird die Luftlinien-Distanz (Haversine) zwischen Vereinen berechnet.

## Aktuelle Ligasortierung (Haupt-CSV)

### Nord (20)
1. 1. FC Germania Egestorf/Langreder
2. 1. FC Phoenix Luebeck
3. Bremer SV
4. ETSV Hamburg
5. FC Guetersloh
6. Hamburger SV
7. Hannover 96
8. HSC Hannover
9. Kickers Emden
10. SC Paderborn 07
11. SC Weiche Flensburg 08
12. Sportfreunde Lotte
13. SSV Jeddeloh
14. SV Drochtersen/Assel
15. SV Todesfelde
16. SV Werder Bremen
17. TSV Havelse
18. TV Eiche Horn
19. VfB Luebeck
20. VfB Oldenburg

### West (20)
1. 1. FC Bocholt
2. 1. FC Koeln
3. Bonner SC
4. Borussia Dortmund
5. Borussia Moenchengladbach
6. FC 08 Homburg
7. FC Eddersheim
8. FC Schalke 04
9. FK Pirmasens
10. Fortuna Duesseldorf
11. FSV Frankfurt
12. FSV Mainz 05
13. Kickers Offenbach
14. Ratingen 04/19
15. Rot-Weiss Oberhausen
16. SG Wattenscheid 09
17. Sportfreunde Siegen
18. SV Bergisch Gladbach 09
19. SV Eintracht Trier
20. TSV Steinbach Haiger

### Ost (20)
1. 1. FC Magdeburg
2. 1. FC Schweinfurt 05
3. BFC Preussen
4. BSV Eintracht Mahlsdorf
5. Chemnitzer FC
6. FC Carl Zeiss Jena
7. FC Erzgebirge Aue
8. FC Rot-Weiss Erfurt
9. FSV 63 Luckenwalde
10. FSV Zwickau
11. Greifswalder FC
12. Hallescher FC
13. Hertha BSC
14. KSV Hessen Kassel
15. SG Barockstadt Fulda-Lehnerz
16. SpVgg Bayreuth
17. SV Babelsberg 03
18. SV Tasmania Berlin
19. VSG Altglienicke
20. ZFC Meuselwitz

### Sued (20)
1. ASV Neumarkt
2. DJK Vilzing
3. FC Bayern Muenchen
4. FC Memmingen
5. FC-Astoria Walldorf
6. FV Illertissen
7. SG Sonnenhof Grossaspach
8. SpVgg Ansbach 09
9. SpVgg Greuther Fuerth
10. SpVgg Unterhaching
11. SSV Ulm 1846
12. Stuttgarter Kickers
13. SV Sandhausen
14. TSV Aubstadt
15. TSV Buchbach
16. TSV Landsberg
17. VfB Eichstaett
18. VfR Mannheim
19. Wacker Burghausen
20. Wuerzburger Kickers

## Aktuelle Distanz-Snapshots
- Durchschnitt Auswaertsdistanz pro Verein: **146.83 km**
- Laengste Einzelreise: **1. FC Schweinfurt 05 -> Greifswalder FC (499.80 km)**
- Durchschnittliche Liga-Distanzen:
  - Nord: **134.54 km**
  - West: **124.33 km**
  - Ost: **180.27 km**
  - Sued: **148.18 km**

## Marker-Logik auf der Karte
- Liga-Zugehoerigkeit: Farbe (Nord/West/Ost/Sued)
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
- APIs koennen sich aendern (Wikipedia/Wikidata/FuPa). Bei Abweichungen: Cache leeren und neu laufen lassen.
- Koordinaten werden in `club_coords_cache.json` gespeichert, damit Folgelaeufe schneller und stabiler sind.
- Karten zeigen Distanz-Unterschiede zwischen Haupt- und Matrix-Variante optional mit schwarzer Umrandung (falls vorhanden).
