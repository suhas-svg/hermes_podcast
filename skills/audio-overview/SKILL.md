---
name: audio-overview
description: "Turn articles, PDFs, papers, notes or the news into a two-host podcast episode (MP3) with Podcast Studio."
version: 1.0.0
author: suhas-svg
license: MIT
metadata:
  hermes:
    tags: [podcast, audio, tts, summary, briefing]
---

# Audio overview workflow

Use this skill when the user asks for a podcast, audio overview, audio summary,
"something I can listen to", or a spoken briefing about a source or topic.

## 1. Read first, then write

- Read the real sources before writing a word: fetch the URL, open the PDF, read
  the notes, search the web or the user's Zotero library. Never script from memory.
- Pick out the 3-6 ideas that matter, the concrete numbers, names and examples,
  and anything surprising or contested.

## 2. Write the script

Two hosts by default: **Alex** (explains, carries the structure) and **Sam**
(curious, asks the questions a listener would, pushes back). Omit `hosts` to get
them with their default voices.

- **Length:** about 150 spoken words per minute. A 3-minute episode is ~450
  words, roughly 20-30 lines. Default to 3-5 minutes unless asked.
- **Shape:** a cold-open hook line, a short intro naming the source, 2-4 chapters
  (set `chapter` on the first line of each), and a takeaway close.
- **Sound like people talking:** short sentences, contractions, real reactions
  ("Wait, really?", "Right, and that's the part..."). Hosts interrupt and build on
  each other; keep most lines under 40 words. No monologues.
- **Spoken text only:** no markdown, bullet points, URLs, emoji, or stage
  directions like *(laughs)*. Write numbers the way they are said ("about two
  thirds", "twenty twenty-four").
- **Stay truthful:** every fact must come from the sources. Say where a claim comes
  from when it matters ("the paper reports...", "according to Reuters...").

## 3. Produce and deliver

1. Call `podcast_produce` with `title`, a one-sentence `description` and `lines`.
2. If it returns an error, fix exactly what it names and call it again.
3. Reply with a 2-3 bullet summary, the duration and chapters, and the returned
   `media_tag` line exactly, on its own line, so the MP3 is attached.

## Options

- Other languages: call `podcast_voices` with a locale (`es`, `fr-FR`, `hi-IN`),
  then pass `hosts` with those voices and write the script in that language.
- One narrator ("read this to me"): pass a single host.
- To send an earlier episode again: `podcast_episodes` with its `id`.
