"""Linha de comando do Reelay."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__, i18n, media, report, transcribe, vision
from .i18n import t
from .util import ReelayError, ensure_dir, run, say, slugify, which

HOME = Path(os.environ.get("REELAY_HOME", Path.home() / ".reelay"))

DEPENDENCIES = [
    ("yt-dlp", ["yt-dlp", "--version"], "brew install yt-dlp"),
    ("ffmpeg", ["ffmpeg", "-version"], "brew install ffmpeg"),
    ("ffprobe", ["ffprobe", "-version"], "brew install ffmpeg"),
]


def doctor(quiet: bool = False) -> int:
    say(t("checking"), quiet=quiet)
    problems = 0
    for name, probe, fix in DEPENDENCIES:
        if not which(name):
            print(t("dep_missing", name=name, fix=fix))
            problems += 1
            continue
        proc = run(probe, check=False)
        version = (proc.stdout or proc.stderr or "").strip().splitlines()[0][:60]
        print(t("dep_ok", name=name, version=version))

    key = transcribe.groq_key()
    if key:
        print(t("dep_ok", name="GROQ_API_KEY", version=f"{key[:4]}… ({len(key)} chars)"))
    else:
        print(t("dep_missing", name="GROQ_API_KEY",
                fix="export GROQ_API_KEY=… (--no-audio works without it)"))

    seeing = vision.api_key()
    if seeing:
        print(t("dep_ok", name="GEMINI_API_KEY", version=f"{seeing[:4]}… ({len(seeing)} chars)"))
    else:
        print(t("dep_missing", name="GEMINI_API_KEY",
                fix="export GEMINI_API_KEY=… (only --describe and --look need it)"))

    print(t("doctor_ok") if not problems else t("doctor_fail", n=problems))
    return 1 if problems else 0


def watch(args: argparse.Namespace) -> int:
    started = time.time()
    quiet = args.quiet

    # Arquivo local pula download e legenda: nao ha site para pedir nem para recusar.
    source = media.local_source(args.url)
    meta = media.local_metadata(source) if source else media.probe_metadata(args.url, args.cookies, quiet)
    seconds = meta.get("duration") or 0
    if seconds and seconds > args.max_minutes * 60:
        raise ReelayError(t("too_long", mins=seconds / 60, limit=args.max_minutes))

    dest = Path(args.out).expanduser() if args.out else HOME / slugify(
        f'{meta.get("extractor") or "video"}-{meta.get("id") or meta.get("title") or "x"}')
    ensure_dir(dest)

    # Ordem de preferencia da legenda: o que o usuario pediu, o idioma que o
    # proprio video declara, o idioma da interface, e ingles como ultimo recurso.
    prefer = [args.language, meta.get("language"), i18n.LANG, "en"]

    transcript = None
    # Legenda escrita por gente e a melhor prova que existe — tentamos antes de baixar.
    if source is None and not args.no_audio and args.transcript in ("auto", "subs"):
        transcript = transcribe.with_subtitles(args.url, dest, args.cookies, True, prefer)
        if not transcript and args.transcript == "subs":
            transcript = transcribe.with_subtitles(args.url, dest, args.cookies, False, prefer)

    video = source or media.download(args.url, dest, args.cookies, quiet)
    duration = seconds or media.duration_of(video)
    # Instagram nao declara duracao no metadado; a medida do arquivo e a real.
    meta["duration"] = duration or None

    frames: list[dict] = []
    sheet = None
    if not args.no_video and args.frames > 0:
        times = media.pick_times(video, duration, args.frames, args.scene_threshold)
        frames = media.extract_frames(video, dest, times, args.width, quiet)
        sheet = media.contact_sheet(frames, dest, quiet)

    if transcript is None and not args.no_audio and args.transcript in ("auto", "whisper"):
        if not media.has_audio(video):
            say(t("transcribe_skipped", why=t("no_audio_track")), quiet=quiet)
        else:
            key = transcribe.groq_key()
            if not key:
                say(t("transcribe_skipped", why=t("no_key")), quiet=quiet)
                # Sem chave, legenda automatica ainda e melhor que silencio.
                transcript = transcribe.with_subtitles(args.url, dest, args.cookies, False, prefer)
            else:
                audio = media.extract_audio(video, dest, quiet)
                transcript = transcribe.with_whisper(audio, duration, key, args.language, quiet)
                if not args.keep_audio:
                    audio.unlink(missing_ok=True)

    # `source` e arquivo DELE: apagar aqui seria destruir o original. So removemos
    # o que o proprio Reelay baixou.
    if not args.keep_video and source is None:
        video.unlink(missing_ok=True)

    # Um modelo de visao gratuito le a folha e escreve o que viu. O agente passa a
    # ler ~110 tokens de texto em vez de ~1100 tokens de imagem, e o gasto sai da
    # cota do Google em vez da dele.
    described = None
    if args.describe and sheet:
        key = vision.api_key()
        if not key:
            say(t("describe_skipped", why=t("no_vision_key")), quiet=quiet)
        else:
            say(t("describing", model=args.vision_model), quiet=quiet)
            try:
                text = vision.describe_sheet(sheet, len(frames), key, args.vision_model)
                described = (text, args.vision_model)
            except ReelayError as exc:
                # Descricao e extra: perder ela nao pode custar o resto do trabalho.
                say(t("describe_skipped", why=str(exc)), quiet=quiet)

    path = report.write(dest, url=args.url, meta=meta, frames=frames,
                        sheet=sheet, transcript=transcript, described=described)

    if args.json:
        print((dest / "reelay.json").read_text())
    else:
        say(t("done", secs=time.time() - started, path=dest), quiet=quiet)
        print(t("read_this"))
        print(path)
    return 0


def look(args: argparse.Namespace) -> int:
    """Olhar uma imagem qualquer — util fora de video: print de tela, PDF, grafico."""
    image = Path(args.look).expanduser()
    if not image.exists():
        raise ReelayError(f"{image} does not exist")

    # O Gemini aceita video inline e descreve — mas isso manda o arquivo inteiro
    # em base64 por um resultado pior que o pipeline normal, que ja escolhe os
    # quadros e transcreve. Redirecionar custa menos que a surpresa.
    import mimetypes
    kind = mimetypes.guess_type(image.name)[0] or ""
    if kind.startswith("video/"):
        raise ReelayError(f"{image.name} is a video — run `reelay \"{image}\"` instead, "
                          "which picks the frames and transcribes the audio.")
    if not kind.startswith("image/"):
        raise ReelayError(f"{image.name} is not an image ({kind or 'unknown type'}).")
    key = vision.api_key()
    if not key:
        raise ReelayError(t("describe_skipped", why=t("no_vision_key")))
    prompt = args.prompt or "Describe this image concretely, including any text visible in it."
    print(vision.describe(image, prompt, key, args.vision_model))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reelay",
        description="Let an AI agent see and hear any online video.",
    )
    parser.add_argument("url", nargs="?", help="video URL (YouTube, Instagram, TikTok, Pinterest, X…)")
    parser.add_argument("--version", action="version", version=f"reelay {__version__}")
    parser.add_argument("--doctor", action="store_true", help="check dependencies and exit")
    parser.add_argument("--lang", choices=sorted(i18n.STRINGS), help="set interface language and exit")
    parser.add_argument("--look", metavar="IMAGE",
                        help="describe any image with a free vision model and exit — no video involved")
    parser.add_argument("-p", "--prompt", help="question to ask about the image (with --look)")

    parser.add_argument("-o", "--out", help="output directory (default: ~/.reelay/<video>)")
    parser.add_argument("-n", "--frames", type=int, default=12, help="how many frames to extract (default: 12)")
    parser.add_argument("--width", type=int, default=1024, help="max frame width in px (default: 1024)")
    parser.add_argument("--scene-threshold", type=float, default=0.25,
                        help="scene-change sensitivity, 0-1 (default: 0.25)")
    parser.add_argument("--transcript", choices=["auto", "whisper", "subs", "none"], default="auto",
                        help="transcript source (default: auto — real subtitles, else Whisper)")
    parser.add_argument("--language", help="spoken-language hint for Whisper, e.g. pt")
    parser.add_argument("--no-audio", action="store_true", help="skip listening entirely")
    parser.add_argument("--no-video", action="store_true", help="skip frames entirely")
    parser.add_argument("--cookies", metavar="BROWSER",
                        help="read cookies from a browser (chrome, safari, firefox…) for private posts")
    parser.add_argument("--max-minutes", type=float, default=180, help="refuse videos longer than this")
    parser.add_argument("--keep-video", action="store_true", help="keep the downloaded video file")
    parser.add_argument("--keep-audio", action="store_true", help="keep the extracted audio file")
    parser.add_argument("--describe", action="store_true",
                        help="have a free vision model describe the contact sheet, so the agent reads text instead of an image")
    parser.add_argument("--vision-model", default=vision.DEFAULT_MODEL,
                        help=f"vision model for --describe and --look (default: {vision.DEFAULT_MODEL})")
    parser.add_argument("--json", action="store_true", help="print reelay.json to stdout")
    parser.add_argument("-q", "--quiet", action="store_true", help="no progress output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.lang:
        i18n.save(args.lang)
        print(i18n.STRINGS[args.lang]["lang_saved"].format(lang=args.lang))
        return 0
    if args.doctor:
        return doctor(args.quiet)
    if args.look:
        try:
            return look(args)
        except ReelayError as exc:
            print(t("err_generic", msg=exc), file=sys.stderr)
            return 1
    if not args.url:
        parser.print_help()
        return 2
    if args.transcript == "none":
        args.no_audio = True

    try:
        return watch(args)
    except ReelayError as exc:
        print(t("err_generic", msg=exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
