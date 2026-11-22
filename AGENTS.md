# Hinweise für KI-Agenten (Claude Code, Codex, Gemini CLI …)

Dieses Repo stellt die Kommandozeile `mgt` mit 13 Hilfstools für Motion-Graphics-Projekte bereit.
Die vollständige Anleitung steht in `README.md`, Abschnitt **„Anleitung für LLMs“**.

Kurzfassung:
- Installieren: `pip install "git+https://github.com/isengaarzombie-pixel/motion-graphics-tools"` (in einer `.venv`).
- Immer im Projektordner des Videos arbeiten (`01_Referenzen` … `06_Export`). Fehlt er: `mgt setup --git`.
- Bei Unsicherheit `mgt <befehl> -h` lesen statt raten.
- Exit-Codes: 0 ok · 1 Prüfung fand Probleme (beheben, erneut prüfen) · 2 Fehler (Meldung nach `FEHLER:` befolgen).
- API-Keys nur in `.env`, nie committen oder ausgeben.
- Übersetzungen macht der Agent selbst: `mgt sprache vorlage` → TODOs ersetzen → `mgt sprache pruefen`.
- Nach jedem Arbeitsschritt: `mgt status --erledigt "…" --naechster "…" --commit "Phase X: …"`.

Am Code dieses Repos arbeiten: `pip install -e ".[dev]"` und `pytest` (braucht FFmpeg). Neue Tools als Modul in
`mgtools/` mit `register(sub)` anlegen und in `mgtools/cli.py` unter `MODULES` eintragen.
