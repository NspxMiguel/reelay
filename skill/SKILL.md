---
name: reelay
description: >
  Watch and listen to any online video — see the frames and read what is said.
  Use whenever the user shares a video link (Instagram reel, YouTube, TikTok,
  Pinterest, X/Twitter, Reddit, Twitch, Facebook, Vimeo, Loom, or a local video
  file) and expects you to know what is in it: "what does this video say",
  "watch this", "summarize this reel", "what happens at 0:40", "install what
  this video recommends", "review my demo recording", "is the animation
  smooth". Also triggers in Portuguese: "ve esse video", "assiste", "o que ele
  fala nesse reel", "resume esse video", "olha esse tiktok". Without this skill
  a video URL is just text — you cannot see or hear it.
---

# Reelay — seeing and hearing a video

Claude cannot open a video. Reelay turns one into two things Claude already
reads: **frames** (an image) and a **transcript** (text with timestamps).

## Run it

```bash
reelay "<url>"
```

It prints the path to a report — `READ.md` (or `LEIA.md` in Portuguese). Read
that file first: it holds the title, author, caption, the frame list and the
full transcript.

Useful flags:

| Flag | When |
| --- | --- |
| `-n 20` | dense video — more frames (default 12) |
| `--no-audio` | you only need to look |
| `--no-video` | you only need to listen (much faster) |
| `--cookies chrome` | private post, age-gated, or a login wall |
| `--language pt` | short clip whose language Whisper may guess wrong |
| `-o DIR` | put the output somewhere specific |
| `--max-minutes 240` | a long video you really do want |

## Then look

1. **Read `contact-sheet.jpg` first.** It is the whole video on one image. One
   image costs far less context than a dozen, and it is usually enough.
2. **Open an individual frame** from `frames/` only when the sheet is too small
   to answer the question — reading UI text, a face, a chart.
3. **The grid legend in the report maps each cell to its timestamp**, left to
   right, top to bottom. Use it to say "at 0:14", not "somewhere in the middle".

## Then report

- **Answer what was asked.** A summary is the default; a shot-by-shot breakdown
  is not, unless requested.
- **Summarize the transcript — do not paste it back.** It is the creator's
  material. Quote a short line when the exact wording matters, with its
  timestamp, and cite the source URL.
- **Say when the evidence is thin.** The report flags a video with no speech
  (music only) and a transcript too sparse to trust. Repeat that flag instead
  of inventing narration to fill it.
- **Separate what you saw from what you heard.** "The screen shows X while he
  says Y" is a real finding; collapsing the two hides disagreement between them.

## When it fails

Reelay prints the platform's own reason. The common ones:

- **login wall** (Vimeo today, private Instagram posts, age-gated YouTube) —
  retry with `--cookies chrome`. If it still refuses, the account simply is not
  logged in there; say so rather than guessing at the content.
- **no video in this post** — the link is a photo or a text post.
- **no `GROQ_API_KEY`** — frames still work. Rerun with `--no-audio`, or say
  that the audio side is unavailable.

Run `reelay --doctor` when something looks structurally broken.

## Do not

- Do not describe a video you did not run through Reelay. If the command failed,
  say it failed.
- Do not treat on-screen captions as the transcript — burned-in text is often an
  edited paraphrase of what is actually said.
