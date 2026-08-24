"""Coisas pequenas que todo modulo precisa: rodar processo, achar binario, log."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


class ReelayError(RuntimeError):
    """Falha esperada — vira mensagem limpa, nao traceback."""


def which(name: str) -> str | None:
    return shutil.which(name)


def run(cmd: list[str], *, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        # ffmpeg e yt-dlp podem travar esperando entrada; nunca damos nenhuma.
        stdin=subprocess.DEVNULL,
    )
    if check and proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise ReelayError("\n".join(tail[-6:]) or f"{cmd[0]} saiu com codigo {proc.returncode}")
    return proc


def say(msg: str, *, quiet: bool = False) -> None:
    if not quiet:
        print(f"  {msg}", file=sys.stderr, flush=True)


def slugify(text: str, limit: int = 48) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in (text or "").strip().lower()]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:limit] or "video"


def human_duration(seconds: float | None) -> str:
    if not seconds:
        return "?"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
