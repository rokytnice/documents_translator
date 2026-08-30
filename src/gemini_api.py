"""Optionaler Modellzugriff über die Gemini-API.

Gleiche Aufrufform wie src/claude_cli.py (`model.generate_content(prompt).text`),
damit beide Anbieter austauschbar sind. Das SDK wird erst beim Erzeugen des
Modells importiert — ohne `--provider gemini` muss es nicht installiert sein.

Achtung: Der Free-Tier erlaubt nur 20 Anfragen pro Modell und Tag. Für größere
Läufe ist die Claude CLI der Standard.
"""

import logging
import os
import re
import time

DEFAULT_MODEL = os.getenv("GEMINI_LLM", "gemini-2.5-flash")


class GeminiError(RuntimeError):
    """Die Gemini-API hat mit einem Fehler geantwortet."""


class QuotaExhausted(GeminiError):
    """Tages- oder Minutenkontingent erschöpft."""


class Response:
    """Minimaler Ersatz für das Antwortobjekt des SDKs."""

    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return f"Response({self.text[:60]!r}…)"


class GeminiModel:
    """Ruft die Gemini-API auf; kompatibel zu model.generate_content(prompt)."""

    def __init__(self, model_name=None, retries=3, api_key=None):
        try:
            from google.generativeai import GenerativeModel, configure
        except ImportError as exc:  # pragma: no cover - hängt an der Installation
            raise GeminiError(
                "google-generativeai ist nicht installiert. "
                "`pip install google-generativeai` oder ohne --provider gemini "
                "arbeiten."
            ) from exc

        key = api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise GeminiError("GEMINI_API_KEY fehlt.")

        configure(api_key=key)
        self.model_name = model_name or DEFAULT_MODEL
        self.retries = retries
        self._model = GenerativeModel(self.model_name)
        logging.info("Modell über Gemini-API (%s)", self.model_name)

    def generate_content(self, prompt, generation_config=None):
        config = dict(generation_config or {})
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self._model.generate_content(
                    prompt, generation_config=config or None)
                return Response(response.text)
            except Exception as exc:  # noqa: BLE001 - das SDK wirft vielerlei
                message = str(exc)
                quota = "429" in message or "quota" in message.lower()
                last = message[:200]
                if not quota:
                    raise GeminiError(last) from exc
                delay = 60
                match = re.search(r"retry in (\d+\.?\d*)", message.lower())
                if match:
                    delay = int(float(match.group(1))) + 5
                if "PerDay" in message or "per day" in message.lower():
                    # Tageskontingent: warten hilft nicht mehr.
                    raise QuotaExhausted(
                        "Gemini-Tageskontingent erschöpft (Free-Tier: 20 Anfragen "
                        "pro Modell und Tag). Ohne --provider gemini läuft es "
                        "über die Claude CLI weiter."
                    ) from exc
                logging.warning("Gemini-Ratelimit (Versuch %d/%d), warte %ds",
                                attempt, self.retries, delay)
                time.sleep(delay)
        raise QuotaExhausted(f"Gemini nach {self.retries} Versuchen: {last}")


def ask(prompt, **kwargs):
    """Einzelaufruf ohne eigenes Modellobjekt."""
    return GeminiModel(**kwargs).generate_content(prompt).text
