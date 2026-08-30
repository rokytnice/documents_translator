"""
Interpretation agent: turns an old public-domain text into a modern novel,
page by page, while keeping the whole work stylistically homogeneous.

ARCHITECTURE
------------
                 +---------------------------------------+
                 |  Orchestrator (main agent)            |
                 |  holds ONLY:                          |
                 |   - style bible (constant)            |
                 |   - continuity state (glossary, ...)  |
                 |   - rolling summaries of past pages   |
                 +----------------+----------------------+
                                  | briefing (source page + context)
                                  v
                 +---------------------------------------+
                 |  Page subagent (fresh context, 1 page)|
                 |  step 1 analyse -> step 2 write       |
                 |  step 3 check   -> step 4 revise      |
                 +----------------+----------------------+
                                  | two returns
              artifact  <---------+---------> summary
   pages/page_0061.md (full prose)     ~40 words + tail + state delta
   never enters the orchestrator        the only thing kept in context

The orchestrator therefore never accumulates the prose of the pages already written.
Its context stays roughly constant no matter how long the book is, while the plot
remains traceable through the chain of summaries. The artifacts are merged into one
Markdown file (and from there into a PDF) at the end via --merge.

Homogeneity across independent subagents comes from four mechanisms:

  1. Style bible   - one versioned file, injected verbatim into every single call.
  2. Continuity    - glossary, characters and open threads carried forward and
                     rewritten after each page.
  3. Two-step pass - the subagent first ANALYSES the page (what happens, how it hooks
                     into what came before and what comes next), then WRITES from it.
  4. Drift control - style metrics of every page are compared against the running
                     baseline of the pages already written; a page that drifts is
                     sent back for a targeted revision.

Only craft principles of the historical-novel genre are emulated. No text of any
living author is reproduced; the content comes entirely from the public-domain source.
"""

import argparse
import glob
import json
import logging
import os
import re
import statistics
import sys
import time

import pdfplumber

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claude_cli import ClaudeModel, ClaudeError  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DEFAULT_MODEL = os.getenv("CLAUDE_MODEL")
STYLE_DIR = "style"
DEFAULT_STYLE = "follett_style.md"

# A page needs at least this many letters to be considered narrative content.
MIN_CONTENT_CHARS = 220
# Trailing characters of the previous page handed to the next subagent verbatim.
TAIL_CHARS = 600
# How many recent page summaries the orchestrator passes down as plot context.
SUMMARY_WINDOW = 8
# Pages used to build the style baseline before drift control kicks in.
BASELINE_WARMUP = 3
# Relative deviation from the baseline that counts as drift.
DRIFT_TOLERANCE = 0.35
# How many metrics must drift before a revision pass is triggered.
DRIFT_METRICS_REQUIRED = 2


# --------------------------------------------------------------------------- #
# Model access
# --------------------------------------------------------------------------- #

def configure_genai(model_name=None):
    """Stellt das Modell über die Claude CLI bereit."""
    try:
        return ClaudeModel(model_name or DEFAULT_MODEL)
    except ClaudeError as exc:
        logging.error("%s", exc)
        return None


"""Timestamp of the last model call, shared by every subagent in the process."""
_last_call = [0.0]


def throttle():
    """
    Hält einen Mindestabstand zwischen den Aufrufen.

    Jede Seite kostet vier Aufrufe (Analyse, Prosa, Revision, Übergabe). Die CLI
    hat kein Minutenkontingent, ein kleiner Abstand hält den Rechner aber ruhig;
    über CLAUDE_MIN_INTERVAL einstellbar.
    """
    interval = float(os.getenv("CLAUDE_MIN_INTERVAL", "0"))
    waited = time.time() - _last_call[0]
    if waited < interval:
        time.sleep(interval - waited)
    _last_call[0] = time.time()


def call_model(model, prompt, as_json=False, max_retries=4, temperature=0.7):
    """Einzelner zustandsloser Modellaufruf mit Wiederholung. None bei Fehlschlag."""
    generation_config = {"temperature": temperature}
    if as_json:
        generation_config["response_mime_type"] = "application/json"

    for attempt in range(max_retries):
        throttle()
        try:
            return model.generate_content(
                prompt, generation_config=generation_config).text
        except ClaudeError as exc:
            delay = 5 * (attempt + 1)
            logging.warning("Modellaufruf gescheitert (Versuch %d/%d): %s — warte %ds",
                            attempt + 1, max_retries, exc, delay)
            time.sleep(delay)
        except Exception as exc:  # noqa: BLE001
            logging.error("Model call failed: %s", exc)
            return None
    logging.error("Max retries exceeded.")
    return None


def parse_json(raw):
    """Parses a model answer that should be JSON, tolerating fenced code blocks."""
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            try:
                return json.loads(brace.group(0))
            except json.JSONDecodeError:
                pass
    logging.warning("Could not parse JSON answer.")
    return None


# --------------------------------------------------------------------------- #
# Source reading
# --------------------------------------------------------------------------- #

# A unit is one work package for one subagent: a PDF page, or a chunk of an EPUB chapter.
# Each unit knows its chapter so the merged book and the audiobook can be split by chapter.
CHAPTER_PATTERN = re.compile(
    r"^\s*((?:Erster|Zweiter|Dritter|Vierter|Fünfter|Sechster|Siebenter|Siebter|Achter|Neunter|"
    r"Zehnter|Elfter|Zwölfter|Dreizehnter|Vierzehnter|Fünfzehnter|Sechzehnter|Siebzehnter|"
    r"Achtzehnter|Neunzehnter|Zwanzigster|Einundzwanzigster|Zweiundzwanzigster|"
    r"Dreiundzwanzigster|Vierundzwanzigster)\s+Gesang)", re.IGNORECASE | re.MULTILINE)

# Target size of one EPUB work package, in characters. Roughly one printed page.
UNIT_CHARS = 3500


def load_units(source_file):
    """Splits any supported source into the work packages the subagents receive."""
    if source_file.lower().endswith(".epub"):
        return load_epub_units(source_file)
    return load_pdf_units(source_file)


def load_pdf_units(pdf_file):
    """One unit per PDF page; the chapter is carried forward from the last heading seen."""
    logging.info("Opening PDF: %s", pdf_file)
    units = []
    chapter = "Ohne Kapitel"
    with pdfplumber.open(pdf_file) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = clean_ocr(page.extract_text() or "")
            heading = CHAPTER_PATTERN.search(text)
            if heading:
                chapter = normalise_chapter(heading.group(1))
            units.append({"nummer": index, "kapitel": chapter, "text": text})
    logging.info("Read %d page(s).", len(units))
    return units


def load_epub_units(epub_file):
    """
    Splits the EPUB into chapter-aware units.

    EPUB documents are far larger than a printed page, so each document is cut into
    UNIT_CHARS-sized packages at paragraph boundaries. That keeps one subagent call at
    a workable size and preserves the page-by-page rhythm the style bible is built for.
    """
    from ebooklib import epub, ITEM_DOCUMENT
    from bs4 import BeautifulSoup

    logging.info("Opening EPUB: %s", epub_file)
    book = epub.read_epub(epub_file)
    units = []
    chapter = "Ohne Kapitel"
    number = 0

    for item in book.get_items_of_type(ITEM_DOCUMENT):
        if item.get_name().lower().startswith("nav"):
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")

        # Headings carry the chapter name, so they must be read before the paragraphs.
        # Nested containers are avoided: taking <div> as well would duplicate every <p>.
        blocks = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"])
        if not blocks:
            blocks = soup.find_all("div")

        for block in blocks:
            if block.name.startswith("h"):
                match = CHAPTER_PATTERN.search(block.get_text(" ", strip=True))
                if match:
                    chapter = normalise_chapter(match.group(1))
                    break

        paragraphs = [text for text in
                      (block.get_text(" ", strip=True) for block in blocks) if text]
        document_text = "\n\n".join(paragraphs)

        if not paragraphs or is_front_matter(document_text):
            logging.info("Skipping front matter: %s", item.get_name())
            continue

        if chapter == "Ohne Kapitel":
            match = CHAPTER_PATTERN.search(document_text[:400])
            if match:
                chapter = normalise_chapter(match.group(1))

        for chunk in chunk_paragraphs(paragraphs, UNIT_CHARS):
            number += 1
            units.append({"nummer": number, "kapitel": chapter, "text": chunk})

    logging.info("Read %d unit(s) across %d chapter(s).",
                 len(units), len({unit["kapitel"] for unit in units}))
    return units


def is_front_matter(text):
    """Detects title pages and tables of contents, which must not be interpreted."""
    head = text[:1500]
    chapter_mentions = len(CHAPTER_PATTERN.findall(text)) + len(re.findall(r"\d+\.\s*Gesang", text))
    if chapter_mentions > 6:
        return True
    return bool(re.search(r"\b(Inhaltsverzeichnis|Titelseite|Impressum)\b", head))


def chunk_paragraphs(paragraphs, target):
    """Groups paragraphs into chunks of roughly `target` characters, never splitting one."""
    chunks, current, size = [], [], 0
    for paragraph in paragraphs:
        if current and size + len(paragraph) > target:
            chunks.append("\n\n".join(current))
            current, size = [], 0
        current.append(paragraph)
        size += len(paragraph)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def normalise_chapter(raw):
    """Turns a matched heading into a stable chapter label."""
    return " ".join(word.capitalize() for word in raw.split())


def clean_ocr(text):
    """Normalises Fraktur OCR artefacts so the model sees readable German."""
    if not text:
        return ""
    replacements = {
        "ſ": "s", "ﬁ": "fi", "ﬂ": "fl",
        "aͤ": "ä", "oͤ": "ö", "uͤ": "ü", "Aͤ": "Ä", "Oͤ": "Ö", "Uͤ": "Ü", "ͤ": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)      # de-hyphenate line breaks
    text = re.sub(r"^\s*V\.\s*\d+[—\-–\s]*\d*\.?\s*$", "", text, flags=re.MULTILINE)  # verse refs
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_content_page(text):
    """Filters out scan front matter, plate pages and OCR noise."""
    if not text:
        return False
    letters = sum(character.isalpha() for character in text)
    if letters < MIN_CONTENT_CHARS:
        return False
    return letters / max(len(text), 1) > 0.55


# --------------------------------------------------------------------------- #
# Orchestrator memory: continuity state + summary chain
# --------------------------------------------------------------------------- #

EMPTY_CONTINUITY = {
    "glossar": {},          # source spelling -> frozen German form
    "figuren": {},          # name -> short profile, kept stable across the work
    "orte": {},             # place -> short description
    "offene_faeden": [],    # unresolved plot threads the coming pages must honour
    "aktuelle_szene": {"ort": "", "zeit": "", "perspektivfigur": ""},
    "letzte_saetze": "",    # verbatim tail of the last written page (handover anchor)
    "seiten_geschrieben": 0,
}


class Continuity:
    """Structured part of the orchestrator's memory. Persisted next to the artifacts."""

    def __init__(self, path):
        self.path = path
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                self.data = json.load(handle)
            logging.info("Continuity loaded: %d pages, %d names in glossary.",
                         self.data.get("seiten_geschrieben", 0),
                         len(self.data.get("glossar", {})))
        else:
            self.data = json.loads(json.dumps(EMPTY_CONTINUITY))

    def save(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2)

    def merge(self, update):
        """Merges a subagent's state delta. Existing glossary entries are never overwritten."""
        if not isinstance(update, dict):
            return
        for source_name, german in (update.get("glossar") or {}).items():
            self.data["glossar"].setdefault(source_name, german)
        for name, profile in (update.get("figuren") or {}).items():
            self.data["figuren"][name] = profile
        for place, description in (update.get("orte") or {}).items():
            self.data["orte"][place] = description
        if isinstance(update.get("offene_faeden"), list):
            self.data["offene_faeden"] = update["offene_faeden"][:12]
        if isinstance(update.get("aktuelle_szene"), dict):
            self.data["aktuelle_szene"] = update["aktuelle_szene"]

    def as_prompt_block(self):
        """Compact rendering for the briefing; long lists are truncated to stay cheap."""
        glossary = self.data.get("glossar", {})
        glossary_lines = [f"  {source} -> {german}"
                          for source, german in list(glossary.items())[:80]]
        figures = [f"  {name}: {profile}"
                   for name, profile in list(self.data.get("figuren", {}).items())[:25]]
        places = [f"  {place}: {desc}"
                  for place, desc in list(self.data.get("orte", {}).items())[:15]]
        threads = [f"  - {thread}" for thread in self.data.get("offene_faeden", [])]
        scene = self.data.get("aktuelle_szene", {})
        return (
            "VERBINDLICHES GLOSSAR (Schreibweisen sind eingefroren):\n"
            + ("\n".join(glossary_lines) or "  (noch leer)")
            + "\n\nFIGUREN:\n" + ("\n".join(figures) or "  (noch keine)")
            + "\n\nORTE:\n" + ("\n".join(places) or "  (noch keine)")
            + "\n\nOFFENE HANDLUNGSFÄDEN:\n" + ("\n".join(threads) or "  (keine)")
            + f"\n\nAKTUELLE SZENE: Ort={scene.get('ort') or '?'}, "
              f"Zeit={scene.get('zeit') or '?'}, Perspektive={scene.get('perspektivfigur') or '?'}"
        )


class SummaryChain:
    """
    The narrative memory of the orchestrator: one short summary per finished page.

    This is what replaces holding the prose in context. It is append-only, persisted
    as JSONL, and only the last SUMMARY_WINDOW entries plus a compressed digest of
    everything older are passed down to the next subagent.
    """

    def __init__(self, path):
        self.path = path
        self.entries = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                self.entries = [json.loads(line) for line in handle if line.strip()]
            logging.info("Summary chain loaded: %d page(s).", len(self.entries))

    def add(self, page_number, summary, artifact, chapter=""):
        entry = {"seite": page_number, "kapitel": chapter,
                 "zusammenfassung": summary, "artefakt": artifact}
        self.entries.append(entry)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def as_prompt_block(self):
        if not self.entries:
            return "(noch nichts geschrieben — dies ist der Anfang des Werks)"
        recent = self.entries[-SUMMARY_WINDOW:]
        older = self.entries[:-SUMMARY_WINDOW]
        block = ""
        if older:
            block += (f"Davor bereits erzählt ({len(older)} Seiten, Seiten "
                      f"{older[0]['seite']}–{older[-1]['seite']}): "
                      + " ".join(entry["zusammenfassung"] for entry in older[-25:]) + "\n\n")
        block += "Unmittelbar davor:\n" + "\n".join(
            f"  Seite {entry['seite']}: {entry['zusammenfassung']}" for entry in recent)
        return block


# --------------------------------------------------------------------------- #
# Style metrics and drift control
# --------------------------------------------------------------------------- #

SENTENCE_SPLIT = re.compile(r"[.!?…]+[\s\"»«]")


def style_metrics(text):
    """Numeric fingerprint of a page. Used to detect stylistic drift objectively."""
    sentences = [part.strip() for part in SENTENCE_SPLIT.split(text) if part.strip()]
    words = re.findall(r"[A-Za-zÄÖÜäöüß]+", text)
    paragraphs = [block for block in text.split("\n\n") if block.strip()]
    lengths = [len(re.findall(r"[A-Za-zÄÖÜäöüß]+", sentence)) for sentence in sentences] or [0]
    dialogue_chars = sum(len(match) for match in re.findall(r"[„»\"][^„»\"]{2,}[“«\"]", text))
    return {
        "satzlaenge": round(statistics.mean(lengths), 2),
        "satzlaenge_streuung": round(statistics.pstdev(lengths), 2) if len(lengths) > 1 else 0.0,
        "absatzlaenge": round(len(sentences) / max(len(paragraphs), 1), 2),
        "dialoganteil": round(dialogue_chars / max(len(text), 1), 3),
        "wortlaenge": round(sum(len(word) for word in words) / max(len(words), 1), 2),
        "kommadichte": round(text.count(",") / max(len(sentences), 1), 2),
    }


DRIFT_LABELS = {
    "satzlaenge": "durchschnittliche Satzlänge",
    "satzlaenge_streuung": "Rhythmuswechsel (Streuung der Satzlängen)",
    "absatzlaenge": "Sätze pro Absatz",
    "dialoganteil": "Dialoganteil",
    "wortlaenge": "durchschnittliche Wortlänge",
    "kommadichte": "Kommas pro Satz",
}


class StyleBaseline:
    """Running average of the metrics of all pages written so far."""

    def __init__(self, path):
        self.path = path
        self.history = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                self.history = json.load(handle)

    def add(self, metrics):
        self.history.append(metrics)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self.history[-200:], handle, ensure_ascii=False, indent=2)

    def mean(self):
        if not self.history:
            return {}
        return {
            key: round(statistics.mean([entry[key] for entry in self.history if key in entry]), 3)
            for key in self.history[0]
        }

    def drift(self, metrics):
        """Returns human-readable deviations that exceed the tolerance."""
        if len(self.history) < BASELINE_WARMUP:
            return []
        baseline = self.mean()
        findings = []
        for key, value in metrics.items():
            reference = baseline.get(key)
            if not reference:
                continue
            deviation = (value - reference) / reference
            if abs(deviation) > DRIFT_TOLERANCE:
                direction = "zu hoch" if deviation > 0 else "zu niedrig"
                findings.append(
                    f"{DRIFT_LABELS.get(key, key)}: {value} gegenüber {reference} im bisherigen "
                    f"Werk ({direction}, {deviation:+.0%})"
                )
        return findings


# --------------------------------------------------------------------------- #
# Deterministic checks that do not need the model
# --------------------------------------------------------------------------- #

def load_forbidden_terms(style_text):
    """Reads the negative list out of the style bible (backtick-quoted terms)."""
    section = style_text.split("Negativliste")[-1]
    return [term.lower() for term in re.findall(r"`([^`]+)`", section)]


def hard_violations(text, forbidden, glossary):
    """Findings the subagent must fix: banned wording, meta talk, glossary breaches."""
    findings = []
    lowered = text.lower()
    for term in forbidden:
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            findings.append(f"Verbotene Wendung aus der Negativliste verwendet: „{term}“")
    for marker in ("hier die moderne", "in dieser szene", "zusammenfassend",
                   "als ki", "der text beschreibt", "moderne interpretation:"):
        if marker in lowered:
            findings.append(f"Meta-Kommentar im Fließtext: „{marker}“")
    if re.search(r"^\s*(Seite|Page)\s+\d+", text, re.MULTILINE):
        findings.append("Seitenüberschrift im Fließtext — der Text muss fortlaufend sein.")
    for source_name, german in glossary.items():
        if source_name.lower() != german.lower() and re.search(
            rf"\b{re.escape(source_name)}\b", text
        ):
            findings.append(
                f"Glossarverstoß: „{source_name}“ statt der festgelegten Form „{german}“")
    return findings


# --------------------------------------------------------------------------- #
# Briefing and prompts
# --------------------------------------------------------------------------- #

ROLE = (
    "Du bist der Autor eines modernen historischen Romans. Du arbeitest eine gemeinfreie "
    "Vorlage Seite für Seite in ein einziges, durchgehendes Werk um. Alle Seiten müssen klingen, "
    "als hätte sie derselbe Autor an einem Stück geschrieben.\n\n"
    "Du ahmst die handwerklichen Prinzipien des modernen historischen Erzählromans nach, wie sie "
    "in der Stilbibel beschrieben sind. Du übernimmst niemals Formulierungen, Figuren oder "
    "Handlungselemente aus Romanen lebender Autoren. Der gesamte Inhalt stammt aus der Vorlage."
)


class Briefing:
    """
    Everything the orchestrator hands down for one page.

    This is the whole interface between orchestrator and subagent. The subagent gets no
    other memory, which is exactly why the style bible and the continuity state have to
    carry the consistency.
    """

    def __init__(self, page_number, page_text, next_preview, style, continuity, summaries,
                 chapter="", chapter_start=False):
        self.page_number = page_number
        self.page_text = page_text
        self.next_preview = next_preview
        self.style = style
        self.continuity = continuity
        self.summaries = summaries
        self.chapter = chapter
        self.chapter_start = chapter_start

    def context_block(self):
        position = (f"Dies ist die ERSTE Seite von „{self.chapter}“. Eröffne das Kapitel, "
                    "ohne den Titel zu nennen und ohne das Vorige zusammenzufassen."
                    if self.chapter_start
                    else f"Laufende Seite innerhalb von „{self.chapter}“.")
        return f"""=== EINORDNUNG ===
{position}

=== STILBIBEL (bindend) ===
{self.style}

=== HANDLUNGSVERLAUF BISHER (Zusammenfassungen der fertigen Seiten) ===
{self.summaries.as_prompt_block()}

=== GEDÄCHTNIS DES WERKS ===
{self.continuity.as_prompt_block()}

=== LETZTE SÄTZE DER VORSEITE (wörtlich, daran musst du anknüpfen) ===
{self.continuity.data.get("letzte_saetze") or "(dies ist der Anfang des Werks)"}"""


def analysis_prompt(briefing):
    return f"""{ROLE}

{briefing.context_block()}

=== VORLAGE, SEITE {briefing.page_number} (zu interpretieren) ===
{briefing.page_text}

=== AUSBLICK: ROHTEXT DER FOLGESEITE (nur zur Orientierung, NICHT interpretieren) ===
{briefing.next_preview or "(keine Folgeseite)"}

AUFGABE — SCHRITT 1 VON 2: Analysiere, bevor du schreibst.

Bestimme:
1. Was passiert auf dieser Seite tatsächlich? Ereignisse in der Reihenfolge der Handlung.
2. Wer nimmt wahr? Wähle genau eine Perspektivfigur für diese Seite.
3. Wo und wann spielt es? Anschluss an die aktuelle Szene oder Wechsel?
4. Was will die Perspektivfigur, und was steht dem im Weg?
5. Welche sinnlichen Details (Geruch, Geräusch, Temperatur, körperliche Arbeit) trägt die
   Vorlage her oder legt sie nahe?
6. Wo referiert die Vorlage, wo du in Szene oder Dialog auflösen solltest?
7. Welche Wiederholungen, Formeln oder Kataloge musst du verdichten oder durch eine
   Figurenwahrnehmung filtern?
8. Wie schließt der erste Satz nahtlos an die Vorseite an?
9. Worauf muss der letzte Satz hinauslaufen, damit die Folgeseite bruchlos weitergeht?
10. Welche offenen Fäden aus dem Gedächtnis berührt diese Seite?

Beachte: Die Vorlage ist ein OCR-Scan. Verlesene Wörter erkennst du am Kontext und
korrigierst sie stillschweigend. Übernimm niemals unverständliche Zeichenfolgen.

Antworte ausschließlich als JSON:
{{
  "perspektivfigur": "",
  "ort": "",
  "zeit": "",
  "szenenwechsel": true/false,
  "ereignisse": [""],
  "begehren": "",
  "hindernis": "",
  "sinnliche_details": [""],
  "in_szene_aufloesen": [""],
  "verdichten": [""],
  "anschluss_vorne": "",
  "ziel_am_seitenende": "",
  "beruehrte_faeden": [""],
  "ocr_korrekturen": [""],
  "risiken": ["Wo könnte der Stil kippen?"]
}}"""


def prose_prompt(briefing, analysis):
    return f"""{ROLE}

{briefing.context_block()}

=== DEINE EIGENE ANALYSE DIESER SEITE (Schritt 1) ===
{json.dumps(analysis, ensure_ascii=False, indent=2)}

=== VORLAGE, SEITE {briefing.page_number} ===
{briefing.page_text}

AUFGABE — SCHRITT 2 VON 2: Schreibe die moderne Interpretation dieser Seite.

Regeln:
- Setze deine Analyse um. Halte dich in jedem Punkt an die Stilbibel.
- Erzähle in Szenen. Übersetze die Vorlage NICHT Vers für Vers und referiere sie nicht nach.
  Was in der Vorlage als Rede markiert ist, wird bei dir zu wörtlicher Rede.
- Der erste Satz knüpft direkt an die letzten Sätze der Vorseite an, ohne sie zu wiederholen.
- Der Schluss läuft auf „{analysis.get('ziel_am_seitenende', '')}“ hinaus und lässt etwas offen.
- Halte dich an das Glossar. Erfinde keine Ereignisse, streiche keine.
- Länge: 0,8 bis 1,6 mal die Vorlage.
- Gib ausschließlich den Fließtext aus. Keine Überschrift, keine Seitenzahl, keine Anmerkung,
  keine Einleitung, kein Nachwort. Kein Wort über diese Aufgabe."""


def revision_prompt(briefing, prose, findings):
    return f"""{ROLE}

=== STILBIBEL (bindend) ===
{briefing.style}

=== DEIN ENTWURF ===
{prose}

=== BEANSTANDUNGEN AUS DER QUALITÄTSPRÜFUNG ===
{chr(10).join('- ' + finding for finding in findings)}

AUFGABE: Überarbeite den Entwurf so, dass jede Beanstandung behoben ist und er sich nahtlos in
den Stil des Gesamtwerks einfügt. Inhalt, Ereignisse und Reihenfolge bleiben unverändert.
Gib ausschließlich den überarbeiteten Fließtext aus, ohne Kommentar."""


def combined_prompt(briefing):
    """
    Economy mode: analysis, prose and handover in one JSON answer.

    The field order is the point. A model generates JSON sequentially, so it has to
    commit to the analysis before it writes a single sentence of prose, and it writes
    the summary only after the prose exists. That preserves the look-then-interpret
    order of the two-step mode at a quarter of the API calls.
    """
    return f"""{ROLE}

{briefing.context_block()}

=== VORLAGE, SEITE {briefing.page_number} (zu interpretieren) ===
{briefing.page_text}

=== AUSBLICK: ROHTEXT DER FOLGESEITE (nur zur Orientierung, NICHT interpretieren) ===
{briefing.next_preview or "(keine Folgeseite)"}

AUFGABE: Arbeite in dieser Reihenfolge und gib alles als ein JSON-Objekt aus.

SCHRITT 1 — Analysiere die Seite, bevor du schreibst:
  Was geschieht tatsächlich? Wer nimmt wahr (genau eine Perspektivfigur)? Wo und wann?
  Was will die Figur, was steht dem im Weg? Welche sinnlichen Details trägt die Vorlage her?
  Was ist Referat und muss in Szene oder Dialog aufgelöst werden? Was ist Formel oder
  Katalog und muss verdichtet werden? Wie schließt der erste Satz an die Vorseite an?
  Worauf muss der letzte Satz hinauslaufen, damit die Folgeseite bruchlos weitergeht?

SCHRITT 2 — Schreibe die moderne Interpretation ins Feld "text":
  - Setze deine Analyse um, halte dich in jedem Punkt an die Stilbibel.
  - Erzähle in Szenen. Übersetze NICHT Vers für Vers und referiere die Vorlage nicht nach.
    Was in der Vorlage Rede ist, wird bei dir wörtliche Rede.
  - Der erste Satz knüpft direkt an die letzten Sätze der Vorseite an, ohne sie zu wiederholen.
  - Der Schluss lässt etwas offen. Halte dich an das Glossar.
  - Erfinde keine Ereignisse, streiche keine. Länge: 0,8 bis 1,6 mal die Vorlage.
  - Reiner Fließtext mit Absätzen. Keine Überschrift, keine Seitenzahl, keine Anmerkung.
  - Die Vorlage ist ein Scan: verlesene Wörter erkennst du am Kontext und korrigierst sie.

SCHRITT 3 — Übergib an den Hauptagenten. Er behält deinen Fließtext NICHT, sondern nur die
Zusammenfassung. Sie muss alles enthalten, was die nächste Seite zum Anschluss braucht.

Antworte ausschließlich als JSON in genau dieser Reihenfolge:
{{
  "perspektivfigur": "", "ort": "", "zeit": "", "szenenwechsel": true/false,
  "ereignisse": [""], "begehren": "", "hindernis": "",
  "in_szene_aufloesen": [""], "verdichten": [""],
  "anschluss_vorne": "", "ziel_am_seitenende": "",
  "text": "der vollständige Fließtext der Seite",
  "zusammenfassung": "1 bis 2 Sätze Handlung, Figuren beim Namen, Ergebnis der Szene",
  "glossar": {{}}, "figuren": {{}}, "orte": {{}}, "offene_faeden": [],
  "aktuelle_szene": {{"ort": "", "zeit": "", "perspektivfigur": ""}}
}}"""


def handover_prompt(briefing, prose, analysis):
    """Asks the subagent for its context return: summary plus state delta."""
    return f"""Du hast soeben eine Seite des Romans geschrieben. Übergib jetzt an den Hauptagenten.

Der Hauptagent behält deinen Fließtext NICHT. Er sieht künftig nur noch deine Zusammenfassung.
Sie muss deshalb alles enthalten, was die nächste Seite braucht, um bruchlos anzuschließen.

=== BISHERIGES GEDÄCHTNIS ===
{briefing.continuity.as_prompt_block()}

=== DEINE ANALYSE ===
{json.dumps(analysis, ensure_ascii=False)}

=== DEIN TEXT ===
{prose}

AUFGABE:
- zusammenfassung: 1 bis 2 Sätze, was auf dieser Seite geschieht. Handlung, keine Stilnotiz.
  Nenne handelnde Figuren beim Namen und das Ergebnis der Szene.
- glossar: nur NEUE Eigennamen dieser Seite, als "Schreibweise der Vorlage": "festgelegte Form".
- figuren: neue oder veränderte Figuren, je ein kurzer Satz (Rolle, Merkmal, Verhältnis).
- orte: neue Schauplätze, je ein kurzer Satz.
- offene_faeden: alle unerledigten Handlungsfäden des Werks, erledigte streichen, max. 12.
- aktuelle_szene: Stand am ENDE dieser Seite.

Antworte ausschließlich als JSON:
{{"zusammenfassung": "", "glossar": {{}}, "figuren": {{}}, "orte": {{}},
 "offene_faeden": [], "aktuelle_szene": {{"ort": "", "zeit": "", "perspektivfigur": ""}}}}"""


# --------------------------------------------------------------------------- #
# The page subagent
# --------------------------------------------------------------------------- #

class PageResult:
    """The two returns of a subagent: the artifact on disk, the summary for the context."""

    def __init__(self, artifact_path, summary, state_delta, tail, metrics, findings, analysis):
        self.artifact_path = artifact_path
        self.summary = summary
        self.state_delta = state_delta
        self.tail = tail
        self.metrics = metrics
        self.findings = findings
        self.analysis = analysis


class PageSubagent:
    """
    Processes exactly one page in its own context and returns artifact + summary.

    It never sees the prose of earlier pages, only the briefing. Everything it produces
    beyond the summary stays on disk.
    """

    def __init__(self, model, pages_dir, forbidden, baseline, max_revisions=1, economy=False):
        self.model = model
        self.pages_dir = pages_dir
        self.forbidden = forbidden
        self.baseline = baseline
        self.max_revisions = max_revisions
        self.economy = economy

    def run(self, briefing):
        page_number = briefing.page_number
        handover = None

        if self.economy:
            # One call: analysis, prose and handover in a single JSON answer.
            combined = parse_json(call_model(
                self.model, combined_prompt(briefing), as_json=True, temperature=0.75))
            if not combined or not combined.get("text"):
                logging.error("Page %d: combined call returned no text.", page_number)
                return None
            analysis = {key: value for key, value in combined.items()
                        if key not in ("text", "zusammenfassung", "glossar", "figuren",
                                       "orte", "offene_faeden", "aktuelle_szene")}
            prose = strip_meta(combined["text"])
            handover = combined
        else:
            # Step 1 - look at the page and decide how to reinterpret it.
            analysis = parse_json(call_model(
                self.model, analysis_prompt(briefing), as_json=True, temperature=0.4)) or {}
            if not analysis:
                logging.warning("Page %d: analysis failed, writing without it.", page_number)

            # Step 2 - write the prose from that analysis.
            prose = call_model(self.model, prose_prompt(briefing, analysis), temperature=0.8)
            if not prose:
                return None
            prose = strip_meta(prose)

        # Step 3 - check against hard rules and against the style of the pages so far.
        findings = []
        for _ in range(self.max_revisions + 1):
            metrics = style_metrics(prose)
            findings = hard_violations(prose, self.forbidden,
                                       briefing.continuity.data["glossar"])
            # A single outlier metric is normal variation; only a broader shift counts as drift.
            drift = self.baseline.drift(metrics)
            if len(drift) >= DRIFT_METRICS_REQUIRED:
                findings += drift
            if not findings:
                break
            logging.info("Page %d: %d finding(s), revising.", page_number, len(findings))
            revised = call_model(self.model, revision_prompt(briefing, prose, findings),
                                 temperature=0.6)
            if not revised:
                break
            prose = strip_meta(revised)

        # Return 1 - the artifact. Written to disk, never handed back into the context.
        artifact_path = os.path.join(self.pages_dir, f"page_{page_number:04d}.md")
        with open(artifact_path, "w", encoding="utf-8") as handle:
            handle.write(prose.strip() + "\n")

        # Return 2 - the context return: summary plus state delta. In economy mode the
        # subagent already produced it as part of the same answer.
        if handover is None:
            handover = parse_json(call_model(
                self.model, handover_prompt(briefing, prose, analysis),
                as_json=True, temperature=0.2)) or {}
        summary = handover.get("zusammenfassung") or f"(Seite {page_number} ohne Zusammenfassung)"

        return PageResult(
            artifact_path=artifact_path,
            summary=summary,
            state_delta=handover,
            tail=prose[-TAIL_CHARS:].strip(),
            metrics=style_metrics(prose),
            findings=findings,
            analysis=analysis,
        )


def strip_meta(text):
    """Removes leftover headings or framing sentences the model sometimes adds."""
    text = text.strip()
    text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text)
    text = re.sub(r"^(Seite|Page)\s+\d+\s*:?\s*\n+", "", text)
    text = re.sub(r"^(Hier ist|Hier die|Moderne Interpretation)[^\n]*\n+", "", text, flags=re.I)
    return text.strip()


# --------------------------------------------------------------------------- #
# Workspace layout
# --------------------------------------------------------------------------- #

class Workspace:
    """All paths of one interpretation run."""

    def __init__(self, source_file, output_dir):
        self.base = os.path.splitext(os.path.basename(source_file))[0]
        self.root = os.path.join(output_dir, f"{self.base}_interpretation")
        self.pages = os.path.join(self.root, "pages")
        self.continuity = os.path.join(self.root, "continuity.json")
        self.summaries = os.path.join(self.root, "summaries.jsonl")
        self.baseline = os.path.join(self.root, "style_baseline.json")
        self.analyses = os.path.join(self.root, "analyses.jsonl")
        self.progress = os.path.join(self.root, "progress.json")
        self.merged = os.path.join(output_dir, f"{self.base}_interpretation.md")

    def prepare(self):
        os.makedirs(self.pages, exist_ok=True)

    def reset(self):
        import shutil
        if os.path.isdir(self.root):
            shutil.rmtree(self.root)
        if os.path.exists(self.merged):
            os.remove(self.merged)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #

def orchestrate(source_file, style_file, page_range, output_dir, model_name, force,
                merge_only, economy=False):
    workspace = Workspace(source_file, output_dir)
    if force:
        workspace.reset()
        logging.info("--force: previous run removed.")
    workspace.prepare()

    if merge_only:
        return merge_artifacts(workspace)

    with open(os.path.join(STYLE_DIR, style_file), "r", encoding="utf-8") as handle:
        style_text = handle.read()

    model = configure_genai(model_name)
    if not model:
        return 1

    units = load_units(source_file)
    by_number = {unit["nummer"]: unit for unit in units}
    start, end = page_range
    end = min(end or len(units), len(units))

    # A run interrupted mid-write can leave a truncated progress file; the artifacts on
    # disk are the real source of truth, so fall back to them instead of failing.
    last_done = 0
    if os.path.exists(workspace.progress):
        try:
            with open(workspace.progress, "r", encoding="utf-8") as handle:
                last_done = json.load(handle).get("last_page", 0)
        except (json.JSONDecodeError, OSError):
            logging.warning("Progress file unreadable, recovering from the artifacts.")
            existing = sorted(glob.glob(os.path.join(workspace.pages, "page_*.md")))
            last_done = int(re.search(r"page_(\d+)", existing[-1]).group(1)) if existing else 0
        if last_done:
            logging.info("Resuming after page %d.", last_done)
    start = max(start, last_done + 1)

    continuity = Continuity(workspace.continuity)
    summaries = SummaryChain(workspace.summaries)
    baseline = StyleBaseline(workspace.baseline)
    subagent = PageSubagent(model, workspace.pages, load_forbidden_terms(style_text),
                            baseline, economy=economy)

    written = 0
    for page_number in range(start, end + 1):
        unit = by_number.get(page_number, {})
        page_text = unit.get("text", "")
        if not is_content_page(page_text):
            logging.info("Page %d skipped (no narrative content).", page_number)
            continue

        next_preview = ""
        for lookahead in range(page_number + 1, min(page_number + 4, len(units) + 1)):
            candidate = by_number.get(lookahead, {}).get("text", "")
            if is_content_page(candidate):
                next_preview = candidate[:1200]
                break

        chapter = unit.get("kapitel", "")
        previous_chapter = by_number.get(page_number - 1, {}).get("kapitel")
        chapter_start = chapter != previous_chapter

        logging.info("Page %d/%d (%s) — dispatching subagent.", page_number, end, chapter)
        result = subagent.run(Briefing(page_number, page_text, next_preview,
                                       style_text, continuity, summaries,
                                       chapter=chapter, chapter_start=chapter_start))
        if not result:
            logging.error("Page %d failed, stopping so the work stays consistent.", page_number)
            break

        # The orchestrator keeps only the summary and the state delta — never the prose.
        summaries.add(page_number, result.summary, result.artifact_path, chapter)
        continuity.merge(result.state_delta)
        continuity.data["letzte_saetze"] = result.tail
        continuity.data["seiten_geschrieben"] += 1
        continuity.save()
        baseline.add(result.metrics)

        with open(workspace.analyses, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"seite": page_number, "analyse": result.analysis,
                                     "beanstandungen": result.findings,
                                     "metriken": result.metrics}, ensure_ascii=False) + "\n")
        with open(workspace.progress, "w", encoding="utf-8") as handle:
            json.dump({"last_page": page_number, "total_pages": len(units),
                       "style": style_file, "model": model_name or DEFAULT_MODEL},
                      handle, indent=2)

        logging.info("Page %d done -> %s | %s", page_number,
                     os.path.basename(result.artifact_path), result.summary)
        written += 1

    logging.info("%d page(s) interpreted.", written)
    return merge_artifacts(workspace)


def merge_artifacts(workspace):
    """
    Assembles the page artifacts into one Markdown file for the PDF conversion.

    Chapter headings come from the summary chain, not from the prose: the subagents are
    told never to write a heading, so the structure is added here, once, consistently.
    The same headings later become the chapters of the audiobook.
    """
    artifacts = sorted(glob.glob(os.path.join(workspace.pages, "page_*.md")))
    if not artifacts:
        logging.warning("No artifacts to merge.")
        return 1

    chapters = {}
    if os.path.exists(workspace.summaries):
        with open(workspace.summaries, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    entry = json.loads(line)
                    chapters[entry["seite"]] = entry.get("kapitel", "")

    written_chapter = None
    with open(workspace.merged, "w", encoding="utf-8") as target:
        target.write(f"# {workspace.base.replace('_', ' ')}\n\n")
        target.write("_Moderne Interpretation einer gemeinfreien Vorlage._\n\n")
        for artifact in artifacts:
            page_number = int(re.search(r"page_(\d+)", artifact).group(1))
            chapter = chapters.get(page_number, "")
            if chapter and chapter != written_chapter:
                target.write(f"\n## {chapter}\n\n")
                written_chapter = chapter
            with open(artifact, "r", encoding="utf-8") as handle:
                target.write(handle.read().strip() + "\n\n")

    logging.info("Merged %d artifact(s) -> %s", len(artifacts), workspace.merged)
    logging.info("PDF:   ./convert_pdf_from_md.sh %s", workspace.merged)
    logging.info("Audio: ./make_audiobook.sh --file %s", workspace.merged)
    return 0


def parse_range(value):
    if not value:
        return 1, None
    if "-" in value:
        start, end = value.split("-", 1)
        return int(start), int(end)
    return int(value), int(value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Interpret a historical public-domain text as a modern novel, "
                    "page by page via subagents, in one consistent voice.")
    parser.add_argument("--file", required=True, help="Source PDF in books/")
    parser.add_argument("--style", default=DEFAULT_STYLE, help=f"Style bible in {STYLE_DIR}/")
    parser.add_argument("--range", default="", help='Page range, e.g. "40-120" or "57"')
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument("--model", default=None, help="Override the Claude model (z. B. claude-sonnet-5)")
    parser.add_argument("--force", action="store_true", help="Discard a previous run and restart")
    parser.add_argument("--merge", action="store_true",
                        help="Only merge existing page artifacts into the final Markdown")
    parser.add_argument("--economy", action="store_true",
                        help="One API call per page instead of four (for tight quotas)")
    args = parser.parse_args()

    sys.exit(orchestrate(args.file, args.style, parse_range(args.range),
                         args.output, args.model, args.force, args.merge, args.economy))
