"""Olhar barato: um modelo de visao gratuito le a imagem, o agente le o texto.

Uma folha de contato custa ~1100 tokens de contexto quando o proprio agente a
abre. Descrita por fora, ela vira ~110 tokens de texto — e o gasto sai da cota
gratuita do Google, nao da dele.

A troca e real e nao e de graca: descricao e resumo, e resumo perde detalhe.
Por isso `--describe` e opcional e a imagem continua no disco: pergunta que
depende de ler texto na tela ainda pede o agente olhando direto.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .util import ReelayError

# Verificado na chave dele em 24/08/2026: o `flash-lite` responde imagem e e o
# mais barato da familia. O proprio endpoint avisa quando um modelo sai de linha.
DEFAULT_MODEL = os.environ.get("REELAY_VISION_MODEL", "gemini-3.5-flash-lite")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SHEET_PROMPT = (
    "This is a contact sheet: {n} frames from one video, in order, left to right, "
    "top to bottom. Describe what happens across the video in under 150 words. "
    "Be concrete about who and what is on screen, and about any text visible on "
    "screen. Do not speculate about audio you cannot hear."
)

MAX_BYTES = 6 * 1024 * 1024  # o endpoint recusa inline_data grande; 6 MB e folgado


def api_key() -> str | None:
    """Env primeiro, depois o chaveiro do macOS. A chave nunca e impressa."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name].strip()
    if os.environ.get("REELAY_NO_KEYCHAIN"):
        return None
    try:
        proc = subprocess.run(
            ["claude-autonomous", "run", "GEMINI_API_KEY", "--",
             "sh", "-c", 'printf %s "$GEMINI_API_KEY"'],
            capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL,
        )
    except Exception:
        return None
    return (proc.stdout or "").strip() or None


def describe(image: Path, prompt: str, key: str, model: str = DEFAULT_MODEL) -> str:
    data = image.read_bytes()
    if len(data) > MAX_BYTES:
        raise ReelayError(f"{image.name}: {len(data) // 1024} KB is over the {MAX_BYTES // 1024} KB limit")
    mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"

    body = json.dumps({
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}},
        ]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600},
    }).encode()

    request = urllib.request.Request(
        ENDPOINT.format(model=model) + f"?key={key}",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "reelay/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = json.loads(exc.read() or b"{}").get("error", {}).get("message", "")
        # O Google diz qual modelo usar quando aposenta um; repassamos isso inteiro.
        raise ReelayError(f"Gemini HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise ReelayError(f"Gemini unreachable: {exc.reason}") from exc

    candidates = payload.get("candidates") or []
    if not candidates:
        blocked = payload.get("promptFeedback", {}).get("blockReason")
        raise ReelayError(f"Gemini returned nothing{f' ({blocked})' if blocked else ''}")
    parts = candidates[0].get("content", {}).get("parts") or []
    text = " ".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise ReelayError("Gemini returned an empty description")
    return text


def describe_sheet(sheet: Path, frame_count: int, key: str, model: str = DEFAULT_MODEL) -> str:
    return describe(sheet, SHEET_PROMPT.format(n=frame_count), key, model)
