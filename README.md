# Reelay

**Let an AI agent see and hear any online video.**

An agent cannot open a video. Reelay turns one into the two things an agent
already reads: a **contact sheet** of frames, and a **timestamped transcript**.
Both land in one folder with a report file to point the agent at.

```bash
reelay "https://www.instagram.com/reel/XXXXXXXXX/"
# → /Users/you/.reelay/instagram-XXXXXXXXX/READ.md
```

Anything [yt-dlp](https://github.com/yt-dlp/yt-dlp) supports works — YouTube,
Instagram, TikTok, Pinterest, X/Twitter, Reddit, Facebook, Twitch, Loom, Vimeo,
and roughly 1700 more sites. A path to a local video file works too, and is
never deleted:

```bash
reelay ~/Movies/demo.mov -n 20
```

## Install

```bash
git clone https://github.com/NspxMiguel/reelay.git && cd reelay && ./install.sh
```

Requires `python3`, `yt-dlp` and `ffmpeg` (`brew install python yt-dlp ffmpeg`).
`install.sh` links the `reelay` command into `~/.local/bin` and drops the Claude
Code skill into `~/.claude/skills/reelay/`.

Check the setup:

```bash
reelay --doctor
```

## How it works

| Step | What happens |
| --- | --- |
| **Metadata** | title, author, platform, duration and caption, before anything is downloaded |
| **Listen** | real subtitles when the platform has them; otherwise Whisper (`whisper-large-v3` on Groq) |
| **See** | frames chosen by scene change, topped up at even intervals so a static shot is still covered |
| **Contact sheet** | every frame tiled into one image, sized to the video's own aspect ratio |
| **Report** | `READ.md` — metadata, caption, frame grid with timestamps, full transcript |

The video file is deleted when it is done. Pass `--keep-video` to keep it.

### Why a contact sheet

Reading twelve separate images costs an agent roughly twelve times the context
of reading one. The sheet is almost always enough to answer the question, and
individual frames stay on disk for the moments that need a closer look.

### Transcript honesty

Whisper invents phrases like *"Thanks for watching!"* over music or silence, and
it reports high confidence while doing it — so its own confidence scores cannot
filter this out. Reelay drops a transcript made entirely of those known
phantom phrases and marks the video as having no speech. A transcript that
covers very little of the running time is flagged as weak evidence rather than
presented as fact.

## Options

| Flag | Default | What it does |
| --- | --- | --- |
| `-n, --frames` | `12` | how many frames to extract |
| `--width` | `1024` | max frame width in pixels |
| `--scene-threshold` | `0.25` | scene-change sensitivity, 0–1 |
| `--transcript` | `auto` | `auto`, `whisper`, `subs`, `none` |
| `--language` | — | spoken-language hint for Whisper, e.g. `pt` |
| `--no-audio` / `--no-video` | — | skip one half entirely |
| `--cookies BROWSER` | — | `chrome`, `safari`, `firefox` — for login walls |
| `--max-minutes` | `180` | refuse anything longer |
| `--keep-video` / `--keep-audio` | — | keep the intermediate files |
| `--describe` | — | have a free vision model summarise the contact sheet |
| `--look IMAGE` | — | describe any image — no video involved (images only; a video path is redirected to the normal pipeline) |
| `--vision-model` | `gemini-3.5-flash-lite` | model used by `--describe` and `--look` |
| `--json` | — | print `reelay.json` to stdout |
| `-o, --out` | `~/.reelay/<video>` | output directory |

## The cheap-eyes layer

Frames cost an agent context. Measured on a 59-second reel with 9 frames:

| What the agent reads | Tokens |
| --- | ---: |
| the 9 frames, one image at a time | ~6200 |
| the contact sheet — one image | ~690 |
| `--describe` — the sheet, summarised into text | ~230 |

```bash
reelay "<url>" --describe
```

A free vision model reads the sheet and writes what it saw into the report, so
the agent reads text instead of an image. The description is a summary and
loses detail, so it is opt-in and the frames stay on disk — a question that
turns on small on-screen text still wants the agent looking directly.

The same eyes work on anything, which is the more useful half:

```bash
reelay --look screenshot.png -p "Which button is disabled, and why might it be?"
reelay --look chart.jpg     -p "Read the axis labels and the peak value."
```

That path never touches a video. It is a general "look at this and tell me"
for any project — a UI screenshot, a chart, a scanned page, a simulator capture.

## Transcription key

Whisper runs on Groq. Reelay reads `GROQ_API_KEY` from the environment, and
falls back to the macOS keychain via `claude-autonomous run` when that is
installed. Without a key, frames still work and Reelay falls back to
auto-captions where the platform offers them.

`--describe` and `--look` use Gemini's free tier and read `GEMINI_API_KEY` the
same way. Both keys are optional and independent: no Groq key costs you the
audio, no Gemini key costs you the description, and neither costs you the
frames. `reelay --doctor` reports which of them it can see.

## Language

Interface text is available in English and Portuguese. The system language
decides the default:

```bash
reelay --lang pt          # save the choice
REELAY_LANG=en reelay …   # override once
```

## Known limits

- **Vimeo requires a logged-in session.** `--cookies chrome` works if that
  browser is signed in; otherwise Vimeo refuses.
- **TikTok's main extractor is broken upstream.** Reelay falls back to TikTok's
  embed player automatically, which downloads the video but returns no title or
  duration.
- Audio longer than 8 minutes is transcribed in chunks. A chunk that fails after
  three retries is skipped rather than losing the whole transcript, and the
  report says which part of the timeline is missing.
- Timestamps are burned into the contact sheet only when `ffmpeg` was built with
  `drawtext`. Homebrew's current build is not, so the grid legend in the report
  carries the times instead.

## License

MIT
