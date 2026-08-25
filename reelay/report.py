"""O arquivo que o agente le. Tudo que o Reelay descobriu, numa pagina so."""

from __future__ import annotations

import json
from pathlib import Path

from .i18n import LANG, t
from .util import human_duration, timestamp


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def write(dest: Path, *, url: str, meta: dict, frames: list[dict],
          sheet: Path | None, transcript: dict | None,
          described: tuple[str, str] | None = None) -> Path:
    title = meta.get("title") or "?"
    author = meta.get("uploader") or meta.get("channel") or meta.get("uploader_id") or "?"
    platform = meta.get("extractor_key") or meta.get("extractor") or "?"
    seconds = meta.get("duration")
    description = (meta.get("description") or "").strip()

    lines = [
        f"# {title}",
        "",
        f'- **{t("url")}:** {url}',
        f'- **{t("platform")}:** {platform}',
        f'- **{t("author")}:** {author}',
        f'- **{t("duration")}:** {human_duration(seconds)}',
        "",
    ]

    if description:
        lines += [f'## {t("described")}', "", description, ""]

    lines += [f'## {t("frames")}', "", t("sheet_hint"), ""]
    if sheet and frames:
        from .media import grid_shape
        cols, rows = grid_shape(len(frames))
        lines += [f"- `{_relative(sheet, dest)}`", "", t("sheet_map", cols=cols, rows=rows), ""]
        # Sem drawtext o tempo nao esta carimbado na imagem; a grade abaixo e o
        # unico jeito de o agente dizer "aos 0:14" em vez de "no meio do video".
        for row in range(rows):
            cells = frames[row * cols:(row + 1) * cols]
            if cells:
                lines.append("  " + " | ".join(f'{f["label"]}' for f in cells))
        lines.append("")
    for frame in frames:
        lines.append(f'- `{_relative(frame["path"], dest)}` — {frame["label"]}')
    lines.append("")

    if described:
        text, model = described
        lines += [f'## {t("seen")}', "", f'_{t("seen_note", model=model)}_', "", text, ""]

    lines += [f'## {t("transcript")}', ""]
    if transcript and transcript.get("no_speech"):
        lines += [t("no_speech"), ""]
    elif transcript and transcript.get("segments"):
        if transcript.get("gaps"):
            gaps = transcript["gaps"]
            when = ", ".join(timestamp(g["from"]) for g in gaps)
            lines += [f'> {t("gaps", n=len(gaps), times=when)}', ""]
        if transcript.get("low_confidence"):
            lines += [f'> {t("low_confidence")}', ""]
        lines += [f'_{transcript["source"]}_', "", "```"]
        lines += [f'[{timestamp(s["start"])}] {s["text"]}'
                  for s in transcript["segments"] if s["text"]]
        lines += ["```", ""]
    elif transcript and transcript.get("text"):
        lines += [f'_{transcript["source"]}_', "", transcript["text"], ""]
    else:
        lines += [t("no_transcript"), ""]

    name = "LEIA.md" if LANG == "pt" else "READ.md"
    out = dest / name
    out.write_text("\n".join(lines))

    # Versao de maquina, pra quem quiser encadear o Reelay com outra coisa.
    (dest / "reelay.json").write_text(json.dumps({
        "url": url,
        "title": title,
        "author": author,
        "platform": platform,
        "duration": seconds,
        "description": description,
        "report": str(out),
        "contact_sheet": str(sheet) if sheet else None,
        "frames": [{"time": f["time"], "label": f["label"], "path": str(f["path"])} for f in frames],
        "transcript": transcript or None,
        "described": {"text": described[0], "model": described[1]} if described else None,
    }, indent=2, ensure_ascii=False))
    return out
