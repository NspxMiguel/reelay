"""Idioma da interface.

Regra do projeto: nada de texto de tela escrito direto no codigo. A escolha
segue, nesta ordem: REELAY_LANG -> config salva -> idioma do sistema -> ingles.
"""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path

CONFIG = Path(os.environ.get("REELAY_HOME", Path.home() / ".reelay")) / "config.json"

STRINGS = {
    "en": {
        "checking": "Checking dependencies",
        "dep_ok": "{name}: {version}",
        "dep_missing": "{name}: NOT FOUND — {fix}",
        "doctor_ok": "Everything Reelay needs is present.",
        "doctor_fail": "{n} dependency problem(s). Fix them and run `reelay doctor` again.",
        "fetching": "Fetching video metadata",
        "downloading": "Downloading video",
        "too_long": "Video is {mins:.0f} min, over the {limit} min limit. Pass --max-minutes to raise it.",
        "extracting_audio": "Extracting audio",
        "extracting_frames": "Extracting frames",
        "frames_done": "{n} frames written",
        "sheet_done": "Contact sheet: {path}",
        "transcribing": "Transcribing audio ({chunks} chunk(s))",
        "transcribe_skipped": "Transcription skipped ({why})",
        "no_key": "no GROQ_API_KEY found — set it, or pass --no-audio",
        "no_audio_track": "this video has no audio track",
        "done": "Done in {secs:.0f}s — {path}",
        "read_this": "Point Claude at this file:",
        "title": "Title",
        "author": "Author",
        "duration": "Duration",
        "platform": "Platform",
        "url": "URL",
        "described": "Caption / description",
        "transcript": "Transcript",
        "frames": "Frames",
        "sheet_hint": "Read the contact sheet first — it is the whole video on one image. Open individual frames only when you need a closer look.",
        "sheet_map": "Contact sheet layout: {cols} columns x {rows} rows, left to right, top to bottom.",
        "no_transcript": "No transcript (silent video or audio disabled).",
        "no_speech": "No speech in this video — the audio is music or ambient only. Whatever it says happens on screen, not in words.",
        "low_confidence": "Sparse transcript: it covers very little of the running time, so treat it as weak evidence.",
        "err_download": "{platform} refused the download:\n  {reason}",
        "hint_cookies": "That looks like a login wall. Retry with --cookies chrome (or safari/firefox).",
        "err_generic": "Reelay failed: {msg}",
        "lang_saved": "Interface language set to {lang}.",
    },
    "pt": {
        "checking": "Conferindo dependencias",
        "dep_ok": "{name}: {version}",
        "dep_missing": "{name}: NAO ENCONTRADO — {fix}",
        "doctor_ok": "Tudo que o Reelay precisa esta instalado.",
        "doctor_fail": "{n} dependencia(s) com problema. Resolva e rode `reelay doctor` de novo.",
        "fetching": "Buscando dados do video",
        "downloading": "Baixando o video",
        "too_long": "O video tem {mins:.0f} min, acima do limite de {limit} min. Use --max-minutes para aumentar.",
        "extracting_audio": "Extraindo o audio",
        "extracting_frames": "Extraindo os quadros",
        "frames_done": "{n} quadros gravados",
        "sheet_done": "Folha de contato: {path}",
        "transcribing": "Transcrevendo o audio ({chunks} pedaco(s))",
        "transcribe_skipped": "Transcricao pulada ({why})",
        "no_key": "nenhuma GROQ_API_KEY encontrada — configure, ou passe --no-audio",
        "no_audio_track": "este video nao tem faixa de audio",
        "done": "Pronto em {secs:.0f}s — {path}",
        "read_this": "Aponte o Claude para este arquivo:",
        "title": "Titulo",
        "author": "Autor",
        "duration": "Duracao",
        "platform": "Plataforma",
        "url": "URL",
        "described": "Legenda / descricao",
        "transcript": "Transcricao",
        "frames": "Quadros",
        "sheet_hint": "Leia a folha de contato primeiro — ela e o video inteiro numa imagem so. Abra quadro individual so quando precisar olhar de perto.",
        "sheet_map": "Disposicao da folha: {cols} colunas x {rows} linhas, da esquerda para a direita, de cima para baixo.",
        "no_transcript": "Sem transcricao (video mudo ou audio desligado).",
        "no_speech": "Nao ha fala neste video — o audio e so musica ou ambiente. O que ele diz acontece na tela, nao em palavras.",
        "low_confidence": "Transcricao esparsa: cobre muito pouco do tempo do video, entao vale como prova fraca.",
        "err_download": "{platform} recusou o download:\n  {reason}",
        "hint_cookies": "Isso parece parede de login. Tente de novo com --cookies chrome (ou safari/firefox).",
        "err_generic": "O Reelay falhou: {msg}",
        "lang_saved": "Idioma da interface definido para {lang}.",
    },
}


def _from_config() -> str | None:
    try:
        return json.loads(CONFIG.read_text()).get("lang")
    except Exception:
        return None


def _from_system() -> str | None:
    try:
        tag = locale.getlocale()[0] or os.environ.get("LANG") or ""
    except Exception:
        tag = os.environ.get("LANG") or ""
    return "pt" if tag.lower().startswith("pt") else None


def resolve() -> str:
    for candidate in (os.environ.get("REELAY_LANG"), _from_config(), _from_system()):
        if candidate and candidate[:2] in STRINGS:
            return candidate[:2]
    return "en"


def save(lang: str) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    try:
        data = json.loads(CONFIG.read_text())
    except Exception:
        pass
    data["lang"] = lang
    CONFIG.write_text(json.dumps(data, indent=2))


LANG = resolve()


def t(key: str, **kw) -> str:
    text = STRINGS.get(LANG, STRINGS["en"]).get(key) or STRINGS["en"][key]
    return text.format(**kw) if kw else text
