# Podcast Studio for Hermes

Turn anything Hermes can read (an article, a PDF, a paper, your notes, today's
news) into a real two-host podcast episode you can listen to: natural neural
voices, pauses between speakers, an intro chime, loudness mastering, chapter
markers and a timestamped transcript, all in one MP3.

```
You: Read https://en.wikipedia.org/wiki/Rayleigh_scattering and make me a
     1-minute two-host podcast episode about it.
Hermes: Done: 1-minute episode with Alex and Sam, mastered MP3.
        - Chapters: Why the sky is blue (00:02), Tiny molecules, huge
          effect (00:15), Beyond the sky (00:41)
        MEDIA:.../episodes/20261107-140110-why-the-sky-is-blue/episode.mp3
```

On Telegram, Discord and other messaging platforms the episode arrives as an
audio file you can play right in the chat.

## What it adds

| Surface | What you get |
| --- | --- |
| Tools | `podcast_produce`, `podcast_voices`, `podcast_episodes` |
| Skill | `podcast:audio-overview`: how to read sources and write a script that sounds like two people talking |
| Automation blueprint | `podcast:daily-briefing`: a morning news episode on topics you choose, delivered to your chat |
| Slash command | `/podcast list`, `/podcast voices LOCALE`, `/podcast doctor` |
| CLI | `hermes podcast list`, `hermes podcast play [ID]`, `hermes podcast voices [LOCALE]`, `hermes podcast doctor` |

| Tool | Does |
| --- | --- |
| `podcast_produce` | Takes a script (title, 1-3 hosts, lines with optional chapters), synthesizes every line in its host's voice, then masters the episode: speaker-aware pauses (shorter for the same speaker, longer between chapters), an intro chime, EBU R128 loudness normalisation to -16 LUFS (the podcast standard), ID3 tags and embedded chapter markers. Writes `episode.mp3`, `transcript.md` and `episode.json`. |
| `podcast_voices` | Lists the 300+ available voices by locale and gender, with their personality tags, so episodes can be in Spanish, Hindi, Japanese and more. |
| `podcast_episodes` | Lists past episodes, or re-sends one by id. |

A prompt alone can't do this. The model writes the script, but the plugin turns
it into produced audio: parallel synthesis with throttle-aware pacing and
retries, sample-accurate assembly, mastering and chapters, and a library of
episodes you can replay.

## Requirements

- Hermes Agent 0.22.5 or newer.
- An internet connection (voices are synthesized online, see Privacy).
- **ffmpeg** for mastering. Hermes ships one; otherwise any ffmpeg on `PATH`
  works, or set `ffmpeg_path`. Without ffmpeg the plugin still delivers an
  episode, but joins the clips without chime, pauses, loudness pass or chapters.
- Python dependency: [`edge-tts`](https://github.com/rany2/edge-tts) (installed
  by Hermes with the plugin).

## Install

```bash
hermes plugins install suhas-svg/hermes_podcast --enable
```

Once the plugin is in the curated catalog:

```bash
hermes plugins install podcast --enable
```

Then check the setup:

```bash
hermes podcast doctor
```

## Try it

- "Make a 3-minute podcast about this article: <link>"
- "Turn this PDF into an audio overview I can listen to on my walk."
- "Read my notes in notes.md as a single-narrator episode."
- "Haz un episodio de dos minutos en español sobre <tema>."
- With the Zotero Research plugin: "Make a podcast episode about the papers in
  my Zotero collection on diffusion models."
- Schedule `podcast:daily-briefing` with `/blueprint` for a news episode every
  morning.

## Settings

Set under `plugins.entries.podcast.settings` in `config.yaml`, for example
`hermes config set plugins.entries.podcast.settings.pause_ms 450`.

| Key | Default | Meaning |
| --- | --- | --- |
| `host_a_voice` | `en-US-AndrewMultilingualNeural` | Voice of the first default host (Alex) |
| `host_b_voice` | `en-US-AvaMultilingualNeural` | Voice of the second default host (Sam) |
| `pause_ms` | `350` | Pause between speakers, in milliseconds |
| `intro_chime` | `true` | Play a chime at the start of each episode |
| `max_lines` | `160` | Most lines one episode may have |
| `max_chars` | `24000` | Most spoken characters (about 25 minutes) |
| `concurrency` | `3` | Lines synthesized in parallel |
| `ffmpeg_path` | empty | ffmpeg to use; empty means find it on `PATH` |

Episodes are stored in the plugin's data folder
(`<HERMES_HOME>/plugin-data/podcast/episodes/`), one folder per episode.

## Privacy

The spoken text of each script line is sent to Microsoft's online neural
text-to-speech service (the one behind Microsoft Edge's Read Aloud) through the
open-source `edge-tts` library. No account or API key is used. Don't produce
episodes from text you are not willing to send to Microsoft. Nothing else leaves
your machine; episodes, transcripts and the cached voice list stay local.

## Development

```bash
python -m pip install pytest edge-tts
python -m pytest -q
```

Tests inject a fake synthesizer, so they run offline. The mastering test needs
ffmpeg and ffprobe on `PATH` and is skipped without them.

## License

MIT
