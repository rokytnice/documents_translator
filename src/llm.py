"""Auswahl des Modellanbieters — Claude CLI als Standard, Gemini optional.

Beide Anbieter bieten dieselbe Aufrufform:

    model = llm.get_model()                 # Claude CLI (Standard)
    model = llm.get_model(provider="gemini")
    text = model.generate_content(prompt).text

Reihenfolge, in der der Anbieter bestimmt wird:
1. Argument `provider` (etwa aus `--provider` auf der Kommandozeile)
2. Umgebungsvariable LLM_PROVIDER
3. "claude"
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claude_cli import ClaudeError, ClaudeModel  # noqa: E402

PROVIDERS = ("claude", "gemini")
DEFAULT_PROVIDER = "claude"


class ProviderError(RuntimeError):
    """Anbieter unbekannt oder nicht einsatzbereit."""


def resolve(provider=None):
    """Ermittelt den Anbieternamen aus Argument, Umgebung oder Standard."""
    name = (provider or os.getenv("LLM_PROVIDER") or DEFAULT_PROVIDER).lower()
    if name not in PROVIDERS:
        raise ProviderError(
            f"Unbekannter Anbieter {name!r}. Erlaubt: {', '.join(PROVIDERS)}."
        )
    return name


def get_model(model_name=None, provider=None, **kwargs):
    """Liefert ein Modellobjekt des gewählten Anbieters."""
    name = resolve(provider)
    if name == "gemini":
        from gemini_api import GeminiError, GeminiModel  # lazy: SDK optional
        try:
            return GeminiModel(model_name, **kwargs)
        except GeminiError as exc:
            raise ProviderError(f"Gemini nicht einsatzbereit: {exc}") from exc
    try:
        return ClaudeModel(model_name, **kwargs)
    except ClaudeError as exc:
        raise ProviderError(f"Claude CLI nicht einsatzbereit: {exc}") from exc


def model_or_none(model_name=None, provider=None, **kwargs):
    """Wie get_model, gibt aber None zurück und protokolliert den Fehler."""
    try:
        return get_model(model_name, provider, **kwargs)
    except ProviderError as exc:
        logging.error("%s", exc)
        return None


def add_provider_argument(parser):
    """Hängt --provider an einen argparse-Parser."""
    parser.add_argument(
        "--provider", choices=PROVIDERS, default=None,
        help=f"Modellanbieter (Standard: {DEFAULT_PROVIDER}, "
             f"sonst über LLM_PROVIDER)",
    )
    return parser


def transient_errors():
    """Fehlerklassen beider Anbieter, bei denen ein neuer Versuch sinnvoll ist."""
    errors = [ClaudeError]
    try:
        from gemini_api import GeminiError
        errors.append(GeminiError)
    except ImportError:
        pass
    return tuple(errors)
