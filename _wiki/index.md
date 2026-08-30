# universal_text_translator — Projekt-Wiki

_Zuletzt aktualisiert: 

## Übersicht

Dieses Wiki dokumentiert die Architektur, Konfiguration und operativen Details des Projekts.

## Inhaltsverzeichnis

- architecture.md — Aufbau & technische Struktur
- operations.md — Betrieb & Workflows
- troubleshooting.md — Häufige Fehler & Lösungen

---

_Wiki-Vorlage erstellt: 

## SRT-Untertitel übersetzen (2026-08-23)

`src/srt_cues.py` trennt Cue-Texte vom Timing: `export` schreibt je Cue eine Zeile
`<nr>|<text>` (interne Umbrüche als ⏎), `merge` baut die Ziel-SRT aus den
**Original-Timecodes** plus übersetzten Zeilen und bricht ab, wenn Zeilen fehlen.
Damit können Timecodes und Blocknummern gar nicht erst verrutschen.

`src/srt_translator.py` übersetzt SRT direkt über die Gemini-API (Batches
nummerierter Zeilen, Retry mit Batch-Halbierung).

**Gotcha:** Der Gemini-Free-Tier erlaubt nur **20 Requests pro Modell und Tag**
(`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). Für Massenübersetzungen
reicht das nicht — nach ~1 Datei ist Schluss. Das Skript bricht bei erschöpftem
Kontingent jetzt ab, statt stundenlang zu warten oder unübersetzte englische
Zeilen durchzureichen.

**Prüfung:** `_work/milos_srt/check_srt.py` vergleicht Cue-Anzahl, Blocknummern
und Timecodes gegen das Original und meldet leere Untertitel.

`src/srt_to_docx.py` baut aus den `-de.srt` ein Buch als DOCX: Nummern, Timecodes
und reine Ton-/Musikhinweise fallen weg, die Fragmente werden zu Absätzen
zusammengefügt (neuer Absatz je Sprecherwechsel bzw. nach ~450 Zeichen am
Satzende), Kapitelüberschriften kommen aus einer Titel-Tabelle im Skript.

**Umgestellt 2026-08-25:** `src/srt_translator.py` ruft nicht mehr die Gemini-API,
sondern die Claude Code CLI (`claude -p --output-format text`, Prompt über stdin).
Damit entfällt die Tagesgrenze des Gemini-Free-Tiers. Batchgröße auf 40 Cues
gesenkt; schlägt ein einzelner Cue mehrfach fehl, bricht der Lauf ab, statt
englischen Text durchzureichen.

## Modellanbieter: Claude CLI (Standard) oder Gemini

`src/llm.py` ist die Auswahlschicht. Beide Anbieter bieten dieselbe Aufrufform
`model.generate_content(prompt).text`, sodass die Module nichts vom Anbieter
wissen müssen:

- `src/claude_cli.py` — `claude -p --output-format text`, Prompt über stdin.
  Kein API-Key, kein Tageskontingent.
- `src/gemini_api.py` — Gemini-API. Das SDK wird erst beim Erzeugen des Modells
  importiert, muss also nur installiert sein, wenn man den Pfad nutzt.

Reihenfolge der Auswahl: `--provider` → `LLM_PROVIDER` → `claude`.

    python src/translator.py --file buch.pdf                    # Claude CLI
    python src/translator.py --file buch.pdf --provider gemini   # Gemini
    LLM_PROVIDER=gemini python src/interpreter.py --file buch.pdf

Modellname je Anbieter über `--model`, sonst `CLAUDE_MODEL` bzw. `GEMINI_LLM`.

**Gotcha:** Das Gemini-Tageskontingent (Free-Tier, 20 Anfragen pro Modell und
Tag) meldet sich als 429 mit `PerDay` im Text. `gemini_api.py` wirft dann sofort
`QuotaExhausted`, statt zu warten — Warten hilft bis Mitternacht Pacific nicht.
