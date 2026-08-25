"""Baixar o video, tirar o audio e escolher os quadros que valem a pena olhar."""

from __future__ import annotations

import json
import math
import re
import os
import tempfile
from pathlib import Path

from .i18n import t
from .util import ReelayError, ensure_dir, run, say, timestamp, which

# Fontes que existem em macOS/Linux — so pra carimbar o tempo na folha de contato.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]

SHEET_CELL_H = 320      # altura da celula; a largura segue o formato do video
SHEET_MAX_COLS = 4


def _font() -> str | None:
    return next((f for f in FONT_CANDIDATES if Path(f).exists()), None)


# Sinais de que o site quer sessao logada, e nao que o video sumiu.
LOGIN_SIGNS = ("logged-in", "log in", "login", "cookies", "sign in",
               "private", "age-restricted", "age restricted", "rate-limit")


def _explain(proc, url: str) -> ReelayError:
    """Devolver o motivo do yt-dlp, nao um 'falhou' generico.

    A causa quase sempre e especifica — parede de login da Vimeo, tweet sem
    video, post apagado — e o usuario so consegue agir se souber qual e.
    """
    lines = [ln.strip() for ln in (proc.stderr or proc.stdout or "").splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.startswith("ERROR:")] or lines[-2:]
    reason = " ".join(errors)[:400] or "unknown error"
    platform = url.split("//")[-1].split("/")[0].replace("www.", "") or "the site"
    message = t("err_download", platform=platform, reason=reason)
    if any(sign in reason.lower() for sign in LOGIN_SIGNS):
        message += "\n  " + t("hint_cookies")
    return ReelayError(message)


_TIKTOK_ID = re.compile(r"tiktok\.com/@[^/]+/(?:video|photo)/(\d+)")


def tiktok_embed(url: str) -> str | None:
    """Rota alternativa do TikTok.

    O extrator normal do yt-dlp esta quebrado no TikTok ("universal data for
    rehydration"), mas o player embutido continua entregando o arquivo. Quando o
    caminho normal falha, tentamos este antes de desistir.
    """
    match = _TIKTOK_ID.search(url)
    return f"https://www.tiktok.com/embed/v2/{match.group(1)}" if match else None


def local_source(target: str) -> Path | None:
    """Arquivo no disco em vez de URL. Devolve o caminho, ou None se for URL."""
    if target.startswith("file://"):
        from urllib.parse import unquote, urlparse
        target = unquote(urlparse(target).path)
    elif "://" in target:
        return None
    path = Path(target).expanduser()
    return path if path.is_file() else None


def local_metadata(path: Path) -> dict:
    """Metadado de arquivo local: o que o ffprobe sabe, e nada inventado."""
    proc = run(["ffprobe", "-v", "error", "-show_entries",
                "format=duration:format_tags=title,artist", "-of", "json", str(path)],
               check=False)
    tags, duration = {}, None
    try:
        fmt = json.loads(proc.stdout or "{}").get("format", {})
        tags = fmt.get("tags") or {}
        duration = float(fmt.get("duration")) if fmt.get("duration") else None
    except Exception:
        pass
    return {
        "title": tags.get("title") or path.stem,
        "uploader": tags.get("artist"),
        "extractor_key": "local file",
        "duration": duration,
        "webpage_url": str(path),
    }


def probe_metadata(url: str, cookies: str | None, quiet: bool) -> dict:
    """So os metadados — nao baixa midia nenhuma."""
    say(t("fetching"), quiet=quiet)
    cmd = ["yt-dlp", "--skip-download", "--dump-single-json", "--no-warnings"]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    cmd.append(url)
    proc = run(cmd, check=False)
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        # O embed do TikTok baixa, mas nao traz metadado: seguimos com o minimo
        # em vez de recusar um video que da pra ver e ouvir.
        if tiktok_embed(url):
            return {"title": url.rstrip("/").rsplit("/", 1)[-1], "extractor_key": "TikTok",
                    "uploader": url.split("@")[-1].split("/")[0] if "@" in url else None,
                    "webpage_url": url}
        raise _explain(proc, url)
    data = json.loads(proc.stdout)
    # Playlist: pegamos a primeira entrada, que e o que o usuario quase sempre quis.
    if data.get("_type") == "playlist" and data.get("entries"):
        data = data["entries"][0]
    return data


def download(url: str, dest: Path, cookies: str | None, quiet: bool) -> Path:
    say(t("downloading"), quiet=quiet)
    out = dest / "source.%(ext)s"
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        # Preferimos mp4 pra nao depender de remux, mas aceitamos o que vier.
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "-o", str(out),
    ]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    cmd.append(url)
    proc = run(cmd, check=False)
    files = sorted(dest.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)

    if (proc.returncode != 0 or not files) and (embed := tiktok_embed(url)):
        proc = run(cmd[:-1] + ["--playlist-items", "1", embed], check=False)
        files = sorted(dest.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)

    if proc.returncode != 0 or not files:
        raise _explain(proc, url)
    return files[0]


def has_audio(video: Path) -> bool:
    proc = run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_type", "-of", "csv=p=0", str(video)],
        check=False,
    )
    return "audio" in (proc.stdout or "")


def duration_of(video: Path) -> float:
    proc = run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        check=False,
    )
    try:
        return float((proc.stdout or "0").strip())
    except ValueError:
        return 0.0


def extract_audio(video: Path, dest: Path, quiet: bool) -> Path:
    """Mono 16 kHz — e o que o Whisper quer, e o menor arquivo possivel."""
    say(t("extracting_audio"), quiet=quiet)
    out = dest / "audio.mp3"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(out)])
    return out


def _scene_times(video: Path, threshold: float) -> list[float]:
    """Momentos em que a imagem muda de verdade — corte, virada de cena, slide novo."""
    escaped = str(video).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    proc = run(
        ["ffprobe", "-v", "error", "-f", "lavfi",
         "-i", f"movie='{escaped}',select=gt(scene\\,{threshold})",
         "-show_entries", "frame=pts_time", "-of", "csv=p=0"],
        check=False,
    )
    times = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip().rstrip(",")
        try:
            times.append(float(line))
        except ValueError:
            continue
    return times


def pick_times(video: Path, duration: float, count: int, threshold: float) -> list[float]:
    """Cenas primeiro; o que faltar, completa em intervalo regular.

    Só cena deixa buraco em video parado (uma pessoa falando na frente da camera);
    só intervalo regular perde o corte rapido. Os dois juntos cobrem os dois casos.
    """
    if duration <= 0:
        return [0.0]
    gap = max(duration / (count * 3), 0.6)  # nao aceitar dois quadros quase iguais

    chosen: list[float] = []

    def offer(candidates: list[float]) -> None:
        for value in candidates:
            if len(chosen) >= count:
                return
            if 0 <= value <= duration and all(abs(value - c) >= gap for c in chosen):
                chosen.append(value)

    offer(_scene_times(video, threshold))
    # Intervalo regular, com meio passo de recuo pra nao cair em transicao/tela preta.
    step = duration / count
    offer([min(duration - 0.05, step * (i + 0.5)) for i in range(count)])
    return sorted(chosen) or [duration / 2]


def extract_frames(video: Path, dest: Path, times: list[float], width: int, quiet: bool) -> list[dict]:
    say(t("extracting_frames"), quiet=quiet)
    folder = ensure_dir(dest / "frames")
    frames = []
    for index, when in enumerate(times):
        name = f"{index:03d}_{timestamp(when).replace(':', 'm')}.jpg"
        out = folder / name
        proc = run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{when:.3f}", "-i", str(video),
             "-frames:v", "1", "-q:v", "3",
             "-vf", f"scale='min({width},iw)':-2", str(out)],
            check=False,
        )
        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            frames.append({"index": index, "time": when, "label": timestamp(when), "path": out})
    say(t("frames_done", n=len(frames)), quiet=quiet)
    return frames


_DRAWTEXT: bool | None = None


def _has_drawtext() -> bool:
    """Nem todo ffmpeg traz drawtext — o do Homebrew hoje vem sem freetype."""
    global _DRAWTEXT
    if _DRAWTEXT is None:
        proc = run(["ffmpeg", "-hide_banner", "-filters"], check=False)
        _DRAWTEXT = " drawtext " in (proc.stdout or "")
    return _DRAWTEXT


def _frame_size(path: Path) -> tuple[int, int]:
    proc = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
               check=False)
    try:
        width, height = (proc.stdout or "").strip().split("x")[:2]
        return int(width), int(height)
    except Exception:
        return 16, 9


def _cell_size(sample: Path) -> tuple[int, int]:
    """A celula segue o formato do video.

    Enfiar um Reel 9:16 numa celula deitada gastava 70% da folha em tarja preta —
    e a imagem que sobrava era estreita demais pra ler texto na tela.
    """
    width, height = _frame_size(sample)
    aspect = (width / height) if height else 16 / 9
    cell_h = SHEET_CELL_H
    cell_w = int(round(cell_h * aspect / 2)) * 2
    cell_w = max(120, min(cell_w, 640))
    return cell_w, cell_h


def grid_shape(count: int) -> tuple[int, int]:
    cols = min(SHEET_MAX_COLS, max(1, math.ceil(math.sqrt(count))))
    return cols, math.ceil(count / cols)


def contact_sheet(frames: list[dict], dest: Path, quiet: bool) -> Path | None:
    """O video inteiro numa imagem so.

    Ler uma folha custa muito menos contexto que abrir doze imagens. O tempo de
    cada celula e carimbado quando o ffmpeg tem drawtext; quando nao tem, a
    legenda da grade vai no relatorio, que e o que o agente le de qualquer jeito.
    """
    if not frames:
        return None
    cell_w, cell_h = _cell_size(frames[0]["path"])
    cols, rows = grid_shape(len(frames))
    stamp = _has_drawtext()
    font = _font() if stamp else None

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        base = (
            f"scale={cell_w}:{cell_h}:force_original_aspect_ratio=decrease,"
            f"pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:black"
        )
        for position, frame in enumerate(frames):
            chain = base
            if font:
                # Dois-pontos e aspas separam opcoes dentro de um filtro do ffmpeg:
                # sem escapar, um rotulo como "0:02" derruba o grafo inteiro.
                label = frame["label"].replace("\\", "\\\\").replace(":", "\\:").replace("'", "")
                chain += (
                    f",drawtext=fontfile='{font}':text='{label}':x=8:y=8:fontsize=24:"
                    "fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=6"
                )
            out = tmpdir / f"{position:03d}.jpg"
            proc = run(["ffmpeg", "-y", "-v", "error", "-i", str(frame["path"]),
                        "-vf", chain, str(out)], check=False)
            if proc.returncode != 0 or not out.exists():
                # Perder o carimbo e aceitavel; perder a folha inteira nao e.
                run(["ffmpeg", "-y", "-v", "error", "-i", str(frame["path"]),
                     "-vf", base, str(out)], check=False)

        if not any(tmpdir.glob("*.jpg")):
            return None
        # Completa a ultima linha com preto: o tile recusa grade incompleta.
        for filler in range(len(frames), cols * rows):
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", f"color=c=black:s={cell_w}x{cell_h}", "-frames:v", "1",
                 str(tmpdir / f"{filler:03d}.jpg")], check=False)

        out = dest / "contact-sheet.jpg"
        proc = run(["ffmpeg", "-y", "-v", "error", "-framerate", "1",
                    "-i", str(tmpdir / "%03d.jpg"),
                    "-vf", f"tile={cols}x{rows}", "-frames:v", "1", "-q:v", "3", str(out)],
                   check=False)
        if proc.returncode != 0 or not out.exists():
            return None
    say(t("sheet_done", path=out), quiet=quiet)
    return out
