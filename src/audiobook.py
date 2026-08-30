"""
Turns the finished interpretation into a chapter-wise audiobook using Piper TTS.

Pipeline per chapter:

    Markdown chapter  ->  speech-ready plain text  ->  sentence-bounded chunks
                      ->  piper (one WAV per chunk) ->  ffmpeg concat -> tagged MP3

Chapters come from the `## ` headings that src/interpreter.py writes during the merge,
so the audiobook is split exactly like the PDF. One MP3 per chapter, plus an M3U
playlist. Finished chapters are skipped on a rerun, so a long book can be produced in
several sessions.

Piper runs locally; no text leaves the machine in this stage.
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

PIPER = os.getenv("PIPER_BIN", os.path.expanduser("~/.local/bin/piper"))
VOICE_DIR = os.getenv("PIPER_VOICE_DIR", os.path.expanduser("~/.local/share/piper/voices"))
DEFAULT_VOICE = "de_DE-thorsten-medium"
# Piper is happiest with a few sentences at a time; this keeps memory flat on long chapters.
CHUNK_CHARS = 1200
# Pause inserted at a scene break, in seconds of silence.
SCENE_PAUSE = 1.2


# --------------------------------------------------------------------------- #
# Input handling
# --------------------------------------------------------------------------- #

def read_source(path):
    """Reads the merged interpretation. Markdown is preferred; PDF is a fallback."""
    if path.lower().endswith(".pdf"):
        import pdfplumber
        logging.info("Reading PDF: %s", path)
        with pdfplumber.open(path) as pdf:
            return "\n\n".join(page.extract_text() or "" for page in pdf.pages)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def split_chapters(text):
    """Splits the document at `## ` headings. Returns [(title, body), ...]."""
    lines = text.split("\n")
    chapters, title, body = [], None, []

    for line in lines:
        heading = re.match(r"^##\s+(.*\S)\s*$", line)
        if heading:
            if body and any(part.strip() for part in body):
                chapters.append((title or "Vorspann", "\n".join(body)))
            title, body = heading.group(1), []
            continue
        if re.match(r"^#\s+", line):  # book title, not a chapter
            continue
        body.append(line)

    if body and any(part.strip() for part in body):
        chapters.append((title or "Vorspann", "\n".join(body)))
    return chapters


def to_speech_text(markdown):
    """Strips markup and turns visual conventions into something a voice can read."""
    text = markdown
    text = re.sub(r"^\s*\*\s*\*\s*\*\s*$", "<<PAUSE>>", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*---+\s*$", "<<PAUSE>>", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`]{1,3}([^*_`]+)[*_`]{1,3}", r"\1", text)   # emphasis
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)          # links and images
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)        # quotes
    text = text.replace("…", "...").replace("–", "-").replace("—", " - ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


SENTENCE_END = re.compile(r"(?<=[.!?\"“«])\s+")


def chunk_for_tts(text, limit=CHUNK_CHARS):
    """
    Cuts a chapter into chunks at sentence boundaries.

    A `<<PAUSE>>` marker always ends a chunk so the caller can insert real silence
    at scene breaks instead of letting the voice run through them.
    """
    chunks = []
    for block in text.split("<<PAUSE>>"):
        block = block.strip()
        if not block:
            continue
        current = ""
        for sentence in SENTENCE_END.split(block):
            if current and len(current) + len(sentence) > limit:
                chunks.append(("text", current.strip()))
                current = ""
            current += sentence + " "
        if current.strip():
            chunks.append(("text", current.strip()))
        chunks.append(("pause", ""))
    if chunks and chunks[-1][0] == "pause":
        chunks.pop()
    return chunks


# --------------------------------------------------------------------------- #
# Synthesis
# --------------------------------------------------------------------------- #

def resolve_voice(voice):
    """Returns the .onnx path of the requested voice, or None if it is not installed."""
    candidate = voice if voice.endswith(".onnx") else os.path.join(VOICE_DIR, f"{voice}.onnx")
    if os.path.exists(candidate):
        return candidate
    available = sorted(name[:-5] for name in os.listdir(VOICE_DIR)
                       if name.endswith(".onnx")) if os.path.isdir(VOICE_DIR) else []
    logging.error("Voice '%s' not found. Installed: %s", voice, ", ".join(available) or "none")
    return None


def synthesise_chunk(text, model_path, output_wav, length_scale):
    """Runs piper for one chunk. Returns True on success."""
    result = subprocess.run(
        [PIPER, "--model", model_path, "--output-file", output_wav,
         "--length-scale", str(length_scale), "--sentence-silence", "0.35"],
        input=text, text=True, capture_output=True,
    )
    if result.returncode != 0 or not os.path.exists(output_wav):
        logging.error("piper failed: %s", (result.stderr or "").strip()[:400])
        return False
    return True


def silence_wav(path, seconds, reference_wav):
    """Creates a silent WAV matching the sample rate of the synthesised audio."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate", "-of", "csv=p=0", reference_wav],
        capture_output=True, text=True)
    rate = probe.stdout.strip() or "22050"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"anullsrc=r={rate}:cl=mono", "-t", str(seconds), path],
        check=True)


def concat_to_mp3(wav_files, output_mp3, tags):
    """Concatenates the chunk WAVs and encodes one tagged MP3 for the chapter."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as listing:
        for wav in wav_files:
            listing.write(f"file '{os.path.abspath(wav)}'\n")
        listing_path = listing.name

    command = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
               "-i", listing_path, "-codec:a", "libmp3lame", "-qscale:a", "4"]
    for key, value in tags.items():
        command += ["-metadata", f"{key}={value}"]
    command.append(output_mp3)

    try:
        subprocess.run(command, check=True)
    finally:
        os.unlink(listing_path)


def duration_of(path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(probe.stdout.strip())
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def build(source, voice, output_dir, length_scale, force, only_chapter):
    if not os.path.exists(PIPER):
        logging.error("piper not found at %s (set PIPER_BIN).", PIPER)
        return 1
    if not shutil.which("ffmpeg"):
        logging.error("ffmpeg not found in PATH.")
        return 1

    model_path = resolve_voice(voice)
    if not model_path:
        return 1

    book_title = os.path.splitext(os.path.basename(source))[0].replace("_", " ")
    target_dir = output_dir or os.path.join(
        "output", os.path.splitext(os.path.basename(source))[0] + "_hoerbuch")
    os.makedirs(target_dir, exist_ok=True)

    chapters = split_chapters(read_source(source))
    if not chapters:
        logging.error("No chapters found. The source needs '## ' headings.")
        return 1
    logging.info("%d chapter(s), voice: %s", len(chapters), os.path.basename(model_path))

    manifest = []
    for index, (title, body) in enumerate(chapters, start=1):
        if only_chapter and index != only_chapter:
            continue

        slug = re.sub(r"[^A-Za-zÄÖÜäöüß0-9]+", "_", title).strip("_") or f"Kapitel_{index}"
        mp3_path = os.path.join(target_dir, f"{index:02d}_{slug}.mp3")

        if os.path.exists(mp3_path) and not force:
            logging.info("Chapter %d/%d '%s' already done, skipping.", index, len(chapters), title)
            manifest.append({"nummer": index, "titel": title, "datei": mp3_path,
                             "dauer_sekunden": round(duration_of(mp3_path), 1)})
            continue

        # The chapter title is spoken first, then the prose.
        speech_text = f"{title}.\n<<PAUSE>>\n" + to_speech_text(body)
        chunks = chunk_for_tts(speech_text)
        if not chunks:
            logging.warning("Chapter %d '%s' is empty, skipping.", index, title)
            continue

        logging.info("Chapter %d/%d '%s' — %d chunk(s).", index, len(chapters), title, len(chunks))
        work_dir = tempfile.mkdtemp(prefix="audiobook_")
        wav_files, failed = [], False
        try:
            for position, (kind, payload) in enumerate(chunks):
                wav_path = os.path.join(work_dir, f"{position:04d}.wav")
                if kind == "pause":
                    if not wav_files:
                        continue
                    silence_wav(wav_path, SCENE_PAUSE, wav_files[-1])
                elif not synthesise_chunk(payload, model_path, wav_path, length_scale):
                    failed = True
                    break
                wav_files.append(wav_path)

            if failed or not wav_files:
                logging.error("Chapter %d failed, leaving it for the next run.", index)
                continue

            concat_to_mp3(wav_files, mp3_path, {
                "title": title, "album": book_title, "artist": "Interpretation",
                "track": f"{index}/{len(chapters)}", "genre": "Audiobook",
            })
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        seconds = duration_of(mp3_path)
        logging.info("Chapter %d done: %s (%d:%02d)", index, os.path.basename(mp3_path),
                     int(seconds // 60), int(seconds % 60))
        manifest.append({"nummer": index, "titel": title, "datei": mp3_path,
                         "dauer_sekunden": round(seconds, 1)})

    write_playlist(target_dir, book_title, manifest)
    total = sum(entry["dauer_sekunden"] for entry in manifest)
    logging.info("Audiobook ready in %s — %d chapter(s), %d:%02d:%02d total.",
                 target_dir, len(manifest),
                 int(total // 3600), int(total % 3600 // 60), int(total % 60))
    return 0


def write_playlist(target_dir, book_title, manifest):
    """Writes an M3U playlist and a JSON manifest next to the MP3s."""
    manifest.sort(key=lambda entry: entry["nummer"])
    with open(os.path.join(target_dir, "hoerbuch.m3u"), "w", encoding="utf-8") as handle:
        handle.write("#EXTM3U\n")
        for entry in manifest:
            handle.write(f"#EXTINF:{int(entry['dauer_sekunden'])},{book_title} - {entry['titel']}\n")
            handle.write(os.path.basename(entry["datei"]) + "\n")
    with open(os.path.join(target_dir, "hoerbuch.json"), "w", encoding="utf-8") as handle:
        json.dump({"titel": book_title, "kapitel": manifest}, handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Chapter-wise audiobook from the finished interpretation, via Piper TTS.")
    parser.add_argument("--file", required=True,
                        help="Merged interpretation (.md preferred, .pdf possible)")
    parser.add_argument("--voice", default=DEFAULT_VOICE,
                        help=f"Piper voice in {VOICE_DIR} (default: {DEFAULT_VOICE})")
    parser.add_argument("--output", default="", help="Output directory for the MP3s")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="Piper length-scale; >1 slower, <1 faster (default: 1.0)")
    parser.add_argument("--chapter", type=int, default=0, help="Only render this chapter number")
    parser.add_argument("--force", action="store_true", help="Re-render chapters that exist")
    args = parser.parse_args()

    sys.exit(build(args.file, args.voice, args.output, args.speed, args.force, args.chapter))
