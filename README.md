# Motion Graphics Tools (`mgt`)

13 Hilfstools für die **Audio-First-Produktion von Motion-Graphics-Videos per Vibe Coding**.
Sie nehmen einem LLM (Claude Code, Codex, Gemini CLI …) die Routinearbeit ab: Statt jedes Mal Skripte neu zu
schreiben, ruft das LLM einen fertigen, getesteten Befehl auf. Das spart Tokens und macht Ergebnisse reproduzierbar.

Alle Tools stecken in **einer** Kommandozeile: `mgt <befehl>`. Die Ordnernamen folgen dem Master-Workflow
(`01_Referenzen` … `06_Export`).

| # | Befehl | Workflow-Phase | Was es tut |
|---|---|---|---|
| 1 | `mgt setup` | 0 | Ordner `01_Referenzen`–`06_Export`, `STATUS.md`, `lizenzen.md`, `.gitignore`, `.env.example` anlegen; Git, Node, Python, FFmpeg prüfen |
| 2 | `mgt pausen` | 3.3 + 3.4 | Lange Sprechpausen kürzen **und** Wort-Timestamps neu berechnen (`voice.mp3`, `timing.json`) |
| 3 | `mgt timetable` | 3.5 | Wort-Timestamps → `scenes.json` mit Frame-Nummern + `timetable.md` |
| 4 | `mgt sfx` | 6.2 | Whoosh, Klick, Pop, Riser (+ Impact, Ding) als lizenzfreie WAV synthetisieren |
| 5 | `mgt freistellen` | 4.2 | Hintergründe im Stapel mit `rembg` entfernen, zuschneiden, einsortieren |
| 6 | `mgt lizenz` | 4.4 + 8.3 | `lizenzen.md` pflegen, Assets ohne Nachweis und verbotene Quellen finden |
| 7 | `mgt storyboard` | 5 + 7.1 | Screenshots oder Video-Frames zu einem Storyboard-Sheet, optional mit Safe-Area-Overlay |
| 8 | `mgt finish` | 6.3 + 6.4 | Format/FPS/Codec prüfen, Musik mischen, auf **-14 LUFS / -1 dBTP** normalisieren |
| 9 | `mgt status` / `mgt report` | global + 9 | `STATUS.md` aktualisieren + Git-Checkpoint; `REPORT.md` (Kosten, Zeit pro Phase, Versionen) |
| 10 | `mgt aussprache` | 3.1 | Englische Begriffe/Abkürzungen im deutschen Sprechertext phonetisch schreiben |
| 11 | `mgt brand` | 1.2 + 7.1 | Farben und Schriften im Code gegen `02_Brand/brand.md` prüfen |
| 12 | `mgt formate` | 6.3 | 16:9 ↔ 9:16 (auch 1:1, 4:5): FFmpeg-Reframing oder Render-Schleife pro Format |
| 13 | `mgt sprache` | 7.4 | `de.json` → `en.json`-Vorlage + Prüfung, englisches Voiceover über ElevenLabs mit Timestamps, Render pro Sprache |

---

## Installation

Voraussetzungen: **Python 3.10+** und **FFmpeg** (inkl. `ffprobe`) im Terminal. `mgt setup` prüft beides.

```bash
# im Projektordner des Videos
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install "git+https://github.com/isengaarzombie-pixel/motion-graphics-tools"

# optional für Tool 5 (Freisteller, lädt beim ersten Lauf ein ~170 MB Modell):
pip install "motion-graphics-tools[freisteller] @ git+https://github.com/isengaarzombie-pixel/motion-graphics-tools"

mgt --help
```

Ohne Installation geht es auch: Repo klonen und `python -m mgtools <befehl>` im Repo-Ordner aufrufen.

---

## Anleitung für LLMs (bitte zuerst lesen)

Diese Regeln gelten, wenn du als LLM mit diesem Repo arbeitest:

1. **Arbeitsordner = Projektordner des Videos.** Alle Standardpfade (`03_Audio/…`, `05_Code/…`) sind relativ dazu.
   Rufe `mgt` immer von dort auf. Fehlt die Struktur: `mgt setup --git`.
2. **Erst `mgt <befehl> -h` lesen**, wenn du dir bei Optionen unsicher bist. Die Hilfe ist kurz und aktuell.
3. **Exit-Codes:** `0` = ok, `1` = Prüfung fand Probleme (z. B. Brand-Verstoß, fehlende Lizenz, Lautheit daneben),
   `2` = Fehler (Datei fehlt, FFmpeg fehlt, API-Key fehlt). Fehlermeldungen beginnen mit `FEHLER:` und sagen, was zu tun ist.
4. **API-Keys nur in `.env`** im Projektordner (`ELEVENLABS_API_KEY=…`). Nie in Code, Commits oder Chat ausgeben.
5. **Reihenfolge im Audio-First-Workflow:** Skript → `aussprache` → TTS mit Timestamps (`sprache tts`) →
   `pausen` → `timetable` → Animation bauen → `sfx` → Render → `finish` → `formate` → `lizenz pruefen` → `report`.
   Nach jedem fertigen Schritt: `mgt status … --commit "Phase X: …"`.
6. **Übersetzen machst du selbst.** `mgt sprache vorlage` legt `en.json` mit `TODO: <deutscher Text>` an. Ersetze jedes
   TODO durch die Übersetzung und kontrolliere mit `mgt sprache pruefen` (Platzhalter wie `{name}` müssen erhalten bleiben).
7. **Prüf-Tools nicht übergehen:** Bei Exit-Code `1` die gemeldeten Stellen korrigieren und erneut prüfen, statt weiterzumachen.

### Typischer Ablauf als Befehlsfolge

```bash
mgt setup --git                                              # Phase 0
mgt aussprache 03_Audio/skript.txt                           # -> 03_Audio/skript_sprecher.txt
mgt sprache tts --sprache de --text 03_Audio/skript_sprecher.txt --modell eleven_multilingual_v2
mgt pausen 03_Audio/de/voice_raw.mp3 --timing 03_Audio/de/timing_raw.json \
          --aus 03_Audio/voice.mp3 --timing-aus 03_Audio/timing.json
mgt timetable --audio 03_Audio/voice.mp3 --szenen 03_Audio/szenen.json
mgt status --phase "Phase 3" --erledigt "Audio + Timetable" --naechster "Freigabe Skript" --commit "Phase 3: Audio"
mgt sfx alle
mgt brand
mgt storyboard 05_Code/storyboard --safe-area 16:9
mgt finish 05_Code/out/render.mp4
mgt formate umwandeln 06_Export/final.mp4 --formate 9:16
mgt lizenz pruefen
mgt report --tokens "ca. 900k" --kosten "4,20 €"
```

---

## Die Tools im Detail

### 1 · `mgt setup [ordner] [--git] [--streng]`
Legt `01_Referenzen`, `02_Brand`, `03_Audio`, `04_Assets`, `05_Code` (mit `tools/` und `i18n/de.json`), `06_Export`,
`STATUS.md`, `lizenzen.md`, `.gitignore` (inkl. `.env`, `.venv/`, `node_modules/`, `06_Export/`) und `.env.example` an.
**Überschreibt nie** vorhandene Dateien. Der Basis-Check zeigt Versionen von git, node (≥ 18), npm, python, ffmpeg,
ffprobe und bei Fehlen den passenden Installationsbefehl (winget / brew / apt). `--streng` → Exit 1, wenn etwas fehlt.

### 2 · `mgt pausen <audio> --timing <timing_raw.json>`
Kürzt Pausen länger als `--max-pause` (Standard 0,4 s) auf `--ziel` (Standard 0,25 s), mit kurzer Blende gegen Knackser.
Schreibt `03_Audio/voice.mp3`, `03_Audio/timing.json` (Wörter mit neuen Zeiten) und `03_Audio/schnittliste.json`
und nennt 3 Wörter zur Stichprobe.

* Pausen werden aus den **Wort-Lücken** im Timing erkannt; ohne Timing oder mit `--aus-audio` per Stille-Erkennung (`--schwelle-db`).
* `--raender-behalten` lässt Stille am Anfang/Ende stehen.
* `--nur-timing --timing X --schnittliste-ein Y` rechnet ein weiteres Timing mit einer vorhandenen Schnittliste um.

Unterstützte Timing-Formate (automatisch erkannt):
```jsonc
{"words": [{"word": "Hallo", "start": 0.12, "end": 0.48}, ...]}            // eigenes Format / Ausgabe
{"alignment": {"characters": [...], "character_start_times_seconds": [...],
               "character_end_times_seconds": [...]}}                     // ElevenLabs "with timestamps"
{"words": [{"text": "Hallo", "start": 0.1, "end": 0.4, "type": "word"}]}   // ElevenLabs Scribe
```

### 3 · `mgt timetable [timing.json] [--fps 30] [--szenen def.json] [--audio voice.mp3]`
Erzeugt `05_Code/scenes.json` und `03_Audio/timetable.md`. Ohne `--szenen` wird jeder Satz eine Szene.
Mit `--audio` wird die Gesamtlänge exakt aus dem Audio übernommen. Szenen sind lückenlos (`endFrame` = nächster `startFrame`).

Szenendefinition (optional), Start per Phrase aus dem Sprechertext oder per Wortindex; weitere Felder werden durchgereicht:
```json
[
  {"id": "hook",  "start": "Heute bauen wir", "aktion": "Titel fliegt ein", "kamera": "Push-in", "sfx": "whoosh"},
  {"id": "teil1", "start": "Der erste Schritt"},
  {"id": "outro", "start_wort": 57}
]
```
Ausgabe (gekürzt):
```json
{"fps": 30, "dauer_sekunden": 42.1, "dauer_frames": 1263,
 "szenen": [{"id": "hook", "text": "Heute bauen wir …", "start": 0.0, "end": 3.2,
             "startFrame": 0, "endFrame": 96, "durationInFrames": 96, "aktion": "Titel fliegt ein",
             "words": [{"word": "Heute", "start": 0.0, "end": 0.3, "frame": 0, "endFrame": 9, "relFrame": 0}]}]}
```
In **Remotion** z. B.: jede Szene als `<Sequence from={s.startFrame} durationInFrames={s.durationInFrames}>`,
Wort-Animationen über `relFrame`. In **HyperFrames**/reinem HTML: Zeiten in Sekunden (`start`, `end`) nutzen.

### 4 · `mgt sfx <typ> [--dauer s] [--tonhoehe f] [--varianten n] [--seed n]`
Typen: `whoosh`, `klick`, `pop`, `riser`, `impact`, `ding` oder `alle`. Stereo-WAV, 44,1 kHz, Spitze -1 dBFS,
Ziel `03_Audio/sfx/`. Selbst synthetisiert, also **keine Lizenzfragen**. `--seed` macht Ergebnisse reproduzierbar,
`--varianten 3` erzeugt leicht unterschiedliche Versionen gegen Wiederholungseffekt.

### 5 · `mgt freistellen [eingang] [--sortieren] [--zuschneiden] [--modell u2net]`
Standard: `04_Assets/roh` → `04_Assets/freigestellt` (PNG mit Alpha). `--sortieren` legt nach Präfix ab
(`char_bob.png` → `freigestellt/char/`), `--zuschneiden` entfernt transparente Ränder (`--rand` px Abstand).
Vorhandene Ergebnisse werden übersprungen (`--neu` erzwingt). `--originale <ordner>` verschiebt die Quellen nach Erfolg.
Braucht `rembg` (siehe Installation). Andere Modelle: `isnet-general-use`, `birefnet-general` …

### 6 · `mgt lizenz add|liste|pruefen`
```bash
mgt lizenz add 04_Assets/foto.jpg --quelle https://… --urheber "Name" --lizenz "CC BY 4.0" --notiz "Namensnennung im Abspann"
mgt lizenz add 04_Assets/logo.svg --lizenz eigen
mgt lizenz pruefen            # Exit 1, wenn Dateien in 04_Assets/ oder 03_Audio/musik/ keinen Eintrag haben
```
Lehnt Pinterest, Google-Bildersuche, Savee, Fiverr, Upwork als Quelle ab (nur Referenz!) und warnt bei Archive.org,
Pixabay, Pexels, Unsplash, die Lizenz pro Objekt zu prüfen. Ohne Lizenzangabe kein Eintrag.

### 7 · `mgt storyboard [ordner] [--safe-area shorts|16:9]`
Fügt alle Bilder aus `05_Code/storyboard/` zu `storyboard.png` zusammen (Spalten, Nummern, Bildunterschriften aus
`--szenen scenes.json`). Mit `--video final.mp4 --szenen scenes.json` werden pro Szene Frames aus dem Video geholt
(für die Selbstkritik in Phase 7). `--safe-area shorts` markiert rot, wo YouTube-/TikTok-UI liegt (unten 20 %, rechts 13 %).

### 8 · `mgt finish <render.mp4> [--format 16:9|9:16] [--fps 30] [--musik datei --musik-pegel -18]`
Prüft Auflösung, FPS, H.264, yuv420p und Tonspur, misst die Lautheit und normalisiert **zweistufig** (loudnorm mit
Messwerten, linear) auf -14 LUFS / True Peak -1 dBTP. Video wird kopiert, nur bei falschem Codec/Pixelformat neu kodiert.
Ergebnis: `06_Export/final.mp4` und eine Nachmessung. `--nur-pruefen` misst nur.

### 9 · `mgt status …` und `mgt report …`
```bash
mgt status --phase "Phase 4: Assets" --erledigt "Icons als SVG" "Charakter freigestellt" \
           --naechster "Storyboard-Frames erzeugen" --frage "Musik ja/nein?" --version "remotion: 4.0.300" \
           --commit "Phase 4: Assets fertig"
mgt status --frage-erledigt "Musik"     # Frage entfernen
mgt status --zeigen
mgt report --tokens "1,1 Mio." --kosten "5,10 €" --credits "Higgsfield: 40"
```
`report` schreibt `REPORT.md` mit Kosten, ElevenLabs-Zeichen (aus `03_Audio/credits_log.json`, schreibt Tool 13 automatisch),
geschätzter Zeit pro Phase (aus Commit-Zeiten mit Präfix `Phase X:`), Tool- und npm-Paketversionen, Export-Kennzahlen.
Ein vorhandener Abschnitt „Learnings“ bleibt beim Neuerzeugen erhalten.

### 10 · `mgt aussprache <skript.txt|de.json> [--abkuerzungen en|de|behalten]`
Schreibt `<name>_sprecher.txt` (Original bleibt für Text-Overlays unverändert). Beispiel:
„mit Claude Code und der ElevenLabs API“ → „mit Klohd Koud und der Illewen Läbs Äi Pie Ai“.
Eingebautes Wörterbuch für gängige Tech-/Motion-Begriffe; unbekannte Abkürzungen werden englisch buchstabiert
(deutsche wie KI, EU, ZDF deutsch). Groß geschriebene deutsche Wörter zur Betonung (KEIN, NUR …) bleiben.
Eigene Einträge in `02_Brand/aussprache.json` (wird automatisch geladen):
```json
{"begriffe": {"Kinetic Typography": "Kinettick Taipografie"}, "abkuerzungen": {"MG": "Emm Dschie"}}
```
Tipp für ElevenLabs v3/v4: Alternativ kann ein Aussprache-Wörterbuch direkt in ElevenLabs gepflegt werden.

### 11 · `mgt brand [--brand 02_Brand/brand.md] [--code 05_Code] [--toleranz 6] [--streng]`
Liest alle Hex-Farben aus `brand.md` (Zeilen mit „kein/nicht/verboten“ oder Abschnitt „Verbote“ → verbotene Farben)
und Schriften (Zeilen wie `Headline: Space Grotesk`, `Fließtext: Inter` oder `` `Font` `` im Abschnitt Typografie).
Prüft im Code Hex, `rgb()`, `hsl()`, benannte Farben (`orange` …), `font-family`/`fontFamily`, `@remotion/google-fonts/X`
und Google-Fonts-Links. Ignoriert `node_modules`, `out`, `dist`, `build`. Weiß/Schwarz sind erlaubt (außer `--streng`).
Ausgabe mit `datei:zeile`, Exit 1 bei Verstößen, `--json` für maschinenlesbar.

Empfohlenes Format in `brand.md`:
```markdown
## Farben
- Primär: #0F172A
- Akzent: #22D3EE
- Kein Standard-Orange (#FFA500)
## Typografie
- Headline: Space Grotesk
- Fließtext: Inter
```

### 12 · `mgt formate umwandeln|render`
```bash
mgt formate umwandeln 06_Export/final.mp4 --formate 9:16 1:1 --modus blur   # blur | crop (--fokus-x 0.3) | pad
mgt formate render --formate 16:9 9:16 --arbeitsordner 05_Code \
    --befehl "npx remotion render Main out/video_{name}.mp4 --width={breite} --height={hoehe}"
```
`umwandeln` ist der schnelle Weg (H.264, Ton unverändert). Für Szenen mit viel Text ist **neu rendern** besser:
`render` führt deinen Render-Befehl pro Format aus (`{format}`, `{name}` = `9x16`, `{breite}`, `{hoehe}`; `--probe` zeigt nur).

### 13 · `mgt sprache vorlage|pruefen|tts|pipeline|render`
```bash
mgt sprache vorlage --von de --nach en      # 05_Code/i18n/en.json mit "TODO: <deutsch>" anlegen (vorhandenes bleibt)
#   -> LLM übersetzt alle TODOs
mgt sprache pruefen --von de --nach en      # fehlende Schlüssel, TODOs, leere Texte, Platzhalter, Längenwarnung
mgt sprache tts --sprache en --text 03_Audio/skript_en.txt          # -> 03_Audio/en/voice_raw.mp3 + timing_raw.json
mgt sprache pipeline --sprache en --text 03_Audio/skript_en.txt     # tts + pausen + timetable in einem Rutsch
mgt sprache render --sprachen de en --arbeitsordner 05_Code \
    --befehl "npx remotion render Main out/video_{lang}.mp4 --props=./scenes_{lang}.json"
```
* Nutzt den ElevenLabs-Endpoint **Text-to-Speech „with timestamps“** (zeichengenaue Zeiten). Lange Texte werden an
  Satzgrenzen geteilt (`--max-zeichen`, Standard 4500), mit `previous_text`/`next_text` für gleichmäßige Betonung
  verbunden und die Zeiten korrekt versetzt. Wiederholt bei 429/5xx automatisch.
* `.env`: `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` oder sprachspezifisch `ELEVENLABS_VOICE_ID_EN`; alternativ `--stimme`.
* Modell per `--modell` (Standard `eleven_multilingual_v2`; z. B. `eleven_v3`, `eleven_flash_v2_5`). `language_code`
  wird nur an Modelle geschickt, die ihn laut API akzeptieren (Flash/Turbo v2.5).
* Verbrauchte Zeichen landen in `03_Audio/credits_log.json` (für `mgt report`).
* Platzhalter im Render-Befehl: `{lang}`, `{timing}`, `{szenen}`, `{audio}`.

---

## Entwicklung & Tests

```bash
pip install -e ".[dev]"
pytest              # 83 Tests; Video/Audio-Tests brauchen FFmpeg, ElevenLabs wird gemockt (kein Key nötig)
```
Getestet mit Python 3.13, FFmpeg 6.1, rembg 2.0.87, Pillow 12, NumPy 2.5 (Linux). Pfade und Befehle sind
plattformunabhängig (Windows, macOS, Linux).

## Hinweise

* Die Tools ersetzen keine Rechtsberatung: `mgt lizenz` hilft beim Dokumentieren, die Prüfung der Lizenz bleibt bei dir.
* Remotion ist nur für Einzelpersonen und Firmen bis 3 Personen kostenlos; ab 4 Personen ist eine Company License nötig.
* YouTube monetarisiert keine reinen Template-Wiederholungen („Inauthentic content“). Jedes Video braucht eigenen Mehrwert.

Lizenz: MIT (siehe `LICENSE`).
