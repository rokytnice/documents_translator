"""Modellzugriff über die Claude Code CLI statt über eine Web-API.

`ClaudeModel` ahmt die Aufrufform des früheren Gemini-SDKs nach
(`model.generate_content(prompt).text`), damit die bestehenden Module ohne
Umbau weiterlaufen. Der Prompt geht über stdin an `claude -p`, die Antwort
kommt als reiner Text zurück.
"""

import logging
import os
import shutil
import subprocess
import time

CLI = os.getenv("CLAUDE_CLI", "claude")
DEFAULT_TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT", "900"))


class ClaudeError(RuntimeError):
    """Die CLI hat mit einem Fehler geantwortet."""


class Response:
    """Minimaler Ersatz für das Antwortobjekt des alten SDKs."""

    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return f"Response({self.text[:60]!r}…)"


def available():
    """Liegt die CLI im PATH?"""
    return shutil.which(CLI) is not None


class ClaudeModel:
    """Ruft `claude -p` auf; kompatibel zu model.generate_content(prompt)."""

    def __init__(self, model_name=None, timeout=DEFAULT_TIMEOUT, retries=3):
        self.model_name = model_name or os.getenv("CLAUDE_MODEL")
        self.timeout = timeout
        self.retries = retries
        if not available():
            raise ClaudeError(
                f"Claude CLI '{CLI}' nicht gefunden. Installieren oder "
                f"CLAUDE_CLI auf den Pfad setzen."
            )
        logging.info("Modell über Claude CLI%s",
                     f" ({self.model_name})" if self.model_name else "")

    def _command(self):
        cmd = [CLI, "-p", "--output-format", "text"]
        if self.model_name:
            cmd += ["--model", self.model_name]
        return cmd

    def generate_content(self, prompt, generation_config=None):
        """generation_config wird angenommen, aber nur für JSON-Ausgabe genutzt."""
        if generation_config and generation_config.get(
                "response_mime_type") == "application/json":
            prompt = (
                f"{prompt}\n\nAntworte ausschließlich mit gültigem JSON, "
                "ohne Markdown-Codeblock und ohne Vor- oder Nachtext."
            )

        last = None
        for attempt in range(1, self.retries + 1):
            try:
                proc = subprocess.run(
                    self._command(), input=prompt,
                    capture_output=True, text=True, timeout=self.timeout,
                )
            except subprocess.TimeoutExpired:
                last = f"Zeitüberschreitung nach {self.timeout}s"
                logging.warning("Claude CLI: %s (Versuch %d/%d)",
                                last, attempt, self.retries)
                continue
            if proc.returncode == 0 and proc.stdout.strip():
                return Response(proc.stdout.strip())
            last = (proc.stderr or proc.stdout).strip()[:200] or \
                f"Exit {proc.returncode}, leere Antwort"
            logging.warning("Claude CLI: %s (Versuch %d/%d)",
                            last, attempt, self.retries)
            time.sleep(3 * attempt)
        raise ClaudeError(f"Claude CLI nach {self.retries} Versuchen: {last}")


def ask(prompt, **kwargs):
    """Einzelaufruf ohne eigenes Modellobjekt."""
    return ClaudeModel(**kwargs).generate_content(prompt).text
