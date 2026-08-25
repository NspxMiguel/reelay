"""Ouvir o video: legenda oficial quando existe, senao Whisper no Groq."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .i18n import t
from .util import ReelayError, run, say, timestamp

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3"
# Pedaco de 15 min derrubou a chamada com HTTP 524 (timeout do gateway) num video
# de 18,7 min: o arquivo cabia no limite de upload, mas a transcricao demorava mais
# do que o proxy aguenta. 8 min passa com folga e custa so mais uma chamada.
CHUNK_SECONDS = 480
# 5xx e 429 sao transitorios por definicao; desistir na primeira e jogar fora
# trabalho que ja foi pago.
RETRY_STATUSES = {408, 429, 500, 502, 503, 504, 520, 522, 524}
RETRIES = 3

# Frases que o Whisper inventa sozinho quando o audio e musica ou silencio. Nao
# sao erro de reconhecimento: sao o que o modelo emite quando nao ha fala nenhuma.
GHOST_PHRASES = {
    "thanks for watching", "thank you for watching", "thanks for watching!",
    "obrigado por assistir", "obrigada por assistir", "inscreva-se no canal",
    "subtitles by the amara.org community", "legendas pela comunidade amara.org",
    "amara.org", "subscribe", "bye", "you", "music", "applause",
}
# Abaixo disto o "transcrito" nao cobre o video: sinal de faixa so com musica.
GHOST_COVERAGE = 0.10
GHOST_CHARS = 80
# Zero letra ou numero no texto inteiro nao e fala, e pontuacao solta. O limite
# e 1 de proposito: com 2 ou 3 a regra descartaria 'oi', 'ok', 'hi' — fala curta
# de verdade — e perder palavra real e pior do que deixar passar um ruido.
GHOST_MIN_ALNUM = 1


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s.]", "", (text or "").strip().lower()).strip(" .")


def flag_ghosts(result: dict, duration: float) -> dict:
    """Transcricao falsa e pior que transcricao nenhuma.

    O Whisper devolve `no_speech_prob` baixo mesmo quando alucina em cima de
    musica, entao a confianca dele nao serve de filtro. O que separa os dois
    casos e a cobertura: fala de verdade ocupa o video; a frase fantasma ocupa
    dois segundos de um clipe inteiro e repete um bordao conhecido.
    """
    segments = [s for s in result.get("segments") or [] if s.get("text")]
    if not segments or duration <= 0:
        return result

    covered = sum(max(0.0, s["end"] - s["start"]) for s in segments)
    text = " ".join(s["text"] for s in segments)
    silent = {"source": result["source"], "text": "", "segments": [], "no_speech": True}

    # Sem letra nem numero nao existe fala. Em cima de um tom puro o Whisper
    # devolveu um unico "." cobrindo o video inteiro — cobertura alta, frase
    # nenhuma, e ainda assim aparecia no relatorio como se fosse transcricao.
    if sum(character.isalnum() for character in text) < GHOST_MIN_ALNUM:
        return silent

    # Transcricao inteira feita so de bordao conhecido: nao ha nada a perder ao
    # descartar, mesmo no caso raro de o video realmente so dizer isso.
    if len(text) < GHOST_CHARS and all(_normalize(s["text"]) in GHOST_PHRASES for s in segments):
        return silent

    if covered / duration < GHOST_COVERAGE and len(text) < GHOST_CHARS:
        result["low_confidence"] = True
    return result


def groq_key() -> str | None:
    """Env primeiro; depois o chaveiro do macOS, via claude-autonomous.

    A chave nunca e impressa nem gravada em disco — so entra no processo.
    """
    key = os.environ.get("GROQ_API_KEY")
    if key:
        return key.strip()
    if os.environ.get("REELAY_NO_KEYCHAIN"):
        return None
    try:
        proc = subprocess.run(
            ["claude-autonomous", "run", "GROQ_API_KEY", "--",
             "sh", "-c", 'printf %s "$GROQ_API_KEY"'],
            capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL,
        )
    except Exception:
        return None
    candidate = (proc.stdout or "").strip()
    return candidate or None


def _multipart(fields: dict[str, str], filename: str, payload: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    sep = f"--{boundary}".encode()
    parts = []
    for name, value in fields.items():
        parts += [sep, f'Content-Disposition: form-data; name="{name}"'.encode(), b"", value.encode()]
    parts += [
        sep,
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode(),
        b"Content-Type: audio/mpeg",
        b"",
        payload,
        f"--{boundary}--".encode(),
        b"",
    ]
    return b"\r\n".join(parts), f"multipart/form-data; boundary={boundary}"


def _post_chunk(path: Path, key: str, language: str | None) -> dict:
    fields = {"model": GROQ_MODEL, "response_format": "verbose_json"}
    if language:
        fields["language"] = language
    body, content_type = _multipart(fields, path.name, path.read_bytes())

    last = ""
    for attempt in range(RETRIES):
        request = urllib.request.Request(
            GROQ_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": content_type,
                # A API da Groq recusa cliente sem User-Agent com 403.
                "User-Agent": "reelay/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            last = f"Groq HTTP {exc.code}: {detail}"
            if exc.code not in RETRY_STATUSES or attempt == RETRIES - 1:
                raise ReelayError(last) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = f"Groq unreachable: {exc}"
            if attempt == RETRIES - 1:
                raise ReelayError(last) from exc
        time.sleep(2 ** attempt * 3)
    raise ReelayError(last or "Groq failed")


def _split(audio: Path, duration: float, workdir: Path) -> list[tuple[Path, float]]:
    if duration <= CHUNK_SECONDS:
        return [(audio, 0.0)]
    pieces = []
    for index in range(math.ceil(duration / CHUNK_SECONDS)):
        start = index * CHUNK_SECONDS
        out = workdir / f"chunk{index:02d}.mp3"
        run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(CHUNK_SECONDS),
             "-i", str(audio), "-c", "copy", str(out)], check=False)
        if out.exists() and out.stat().st_size > 0:
            pieces.append((out, float(start)))
    return pieces or [(audio, 0.0)]


def with_whisper(audio: Path, duration: float, key: str, language: str | None, quiet: bool) -> dict:
    workdir = audio.parent / "chunks"
    workdir.mkdir(exist_ok=True)
    pieces = _split(audio, duration, workdir)
    say(t("transcribing", chunks=len(pieces)), quiet=quiet)

    segments, text, lost = [], [], []
    for piece, offset in pieces:
        try:
            result = _post_chunk(piece, key, language)
        except ReelayError as exc:
            # Um pedaco perdido nao pode custar os outros: o que ja voltou vale, e
            # o buraco fica declarado no relatorio em vez de virar silencio.
            lost.append((offset, str(exc)))
            continue
        text.append((result.get("text") or "").strip())
        for seg in result.get("segments") or []:
            segments.append({
                "start": float(seg.get("start", 0)) + offset,
                "end": float(seg.get("end", 0)) + offset,
                "text": (seg.get("text") or "").strip(),
            })
    segments.sort(key=lambda seg: seg["start"])
    for piece, _ in pieces:
        if piece.parent == workdir:
            piece.unlink(missing_ok=True)
    if workdir.exists() and not any(workdir.iterdir()):
        workdir.rmdir()

    if lost and not segments:
        raise ReelayError(lost[0][1])
    result = {"source": f"whisper ({GROQ_MODEL})",
              "text": " ".join(t for t in text if t), "segments": segments}
    if lost:
        result["gaps"] = [{"from": offset, "why": why} for offset, why in lost]
    return flag_ghosts(result, duration)


_VTT_TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")


def _parse_vtt(raw: str) -> list[dict]:
    segments, current = [], None
    for line in raw.splitlines():
        match = _VTT_TIME.search(line)
        if match:
            h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(g) for g in match.groups())
            current = {
                "start": h1 * 3600 + m1 * 60 + s1 + ms1 / 1000,
                "end": h2 * 3600 + m2 * 60 + s2 + ms2 / 1000,
                "text": "",
            }
            continue
        if current is None:
            continue
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if not clean:
            if current["text"]:
                segments.append(current)
            current = None
        elif clean not in current["text"]:
            current["text"] = f'{current["text"]} {clean}'.strip()
    if current and current["text"]:
        segments.append(current)

    # Legenda automatica repete a linha anterior a cada bloco; tiramos a repeticao.
    deduped = []
    for seg in segments:
        if deduped and seg["text"] == deduped[-1]["text"]:
            deduped[-1]["end"] = seg["end"]
        else:
            deduped.append(seg)
    return deduped


def _lang_of(path: Path) -> str:
    """`sub.pt-BR.vtt` -> `pt-br`. O nome do arquivo e onde o yt-dlp poe o idioma."""
    parts = path.name.split(".")
    return parts[-2].lower() if len(parts) >= 3 else ""


def _rank(path: Path, prefer: list[str]) -> tuple[int, str]:
    """Menor e melhor: casamento exato, depois so o prefixo, depois o resto."""
    lang = _lang_of(path)
    for position, wanted in enumerate(prefer):
        wanted = wanted.lower()
        if lang == wanted:
            return (position * 2, path.name)
        if lang.split("-")[0] == wanted.split("-")[0]:
            return (position * 2 + 1, path.name)
    return (len(prefer) * 2, path.name)


def with_subtitles(url: str, dest: Path, cookies: str | None, manual_only: bool,
                   prefer: list[str] | None = None) -> dict | None:
    """Legenda escrita por gente vale mais que qualquer transcricao automatica.

    O idioma importa: pedir `all` e pegar o primeiro arquivo trazia a legenda
    arabe de um video em ingles, so porque `ar` vem antes de `en` no alfabeto.
    """
    prefer = [p for p in (prefer or []) if p] or ["en"]
    folder = dest / "subs"
    folder.mkdir(exist_ok=True)
    wanted = ",".join(dict.fromkeys(prefer + [f"{p.split('-')[0]}.*" for p in prefer]))
    cmd = ["yt-dlp", "--skip-download", "--no-warnings", "--write-subs",
           "--sub-format", "vtt/srt/best", "--sub-langs", wanted,
           "-o", str(folder / "sub"), url]
    if not manual_only:
        cmd.insert(4, "--write-auto-subs")
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    run(cmd, check=False)

    files = sorted(folder.glob("*.vtt")) + sorted(folder.glob("*.srt"))
    if not files:
        return None
    best = min(files, key=lambda f: _rank(f, prefer))
    segments = _parse_vtt(best.read_text(errors="replace"))
    if not segments:
        return None
    kind = "subtitles" if manual_only else "auto-captions"
    return {
        "source": f"{kind}, {_lang_of(best) or '?'} ({best.name})",
        "text": " ".join(s["text"] for s in segments),
        "segments": segments,
    }


def as_text(result: dict) -> str:
    if not result.get("segments"):
        return result.get("text", "")
    return "\n".join(f'[{timestamp(s["start"])}] {s["text"]}' for s in result["segments"] if s["text"])
