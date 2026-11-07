"""JSON Schemas for the Podcast Studio tools."""

from __future__ import annotations

from typing import Any

PRODUCE_SCHEMA: dict[str, Any] = {
    "description": (
        "Produce a real podcast episode (MP3) from a script you write: each line is spoken "
        "by its host's voice, with natural pauses, an intro chime, normalised loudness, "
        "chapter markers and a timestamped transcript. Put the returned media_tag line in "
        "your reply to attach the audio. Write the script from sources you actually read (web pages, "
        "PDFs, notes); load the podcast:audio-overview skill first for the format."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Episode title."},
            "description": {"type": "string", "description": "One or two sentences for the episode notes."},
            "hosts": {
                "type": "array",
                "description": "1-3 hosts. Omit for the default pair (Alex and Sam). voice is an Edge voice such as en-US-AndrewMultilingualNeural (see podcast_voices).",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "voice": {"type": "string"},
                        "rate": {"type": "string", "description": "e.g. +5% or -10%"},
                        "pitch": {"type": "string", "description": "e.g. +0Hz or -20Hz"},
                    },
                    "required": ["name"],
                },
            },
            "lines": {
                "type": "array",
                "description": "The conversation in order. Plain spoken text only, no markdown or stage directions. Set chapter on the first line of each section.",
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker": {"type": "string", "description": "A host name."},
                        "text": {"type": "string"},
                        "chapter": {"type": "string", "description": "Section title, set where a new section starts."},
                    },
                    "required": ["speaker", "text"],
                },
            },
        },
        "required": ["title", "lines"],
        "additionalProperties": False,
    },
}

VOICES_SCHEMA: dict[str, Any] = {
    "description": "List the voices available for podcast hosts, filtered by language/locale and gender.",
    "parameters": {
        "type": "object",
        "properties": {
            "locale": {"type": "string", "description": "Language or locale prefix, e.g. en, en-GB, es, hi-IN. Default en."},
            "gender": {"type": "string", "enum": ["Male", "Female"]},
        },
        "additionalProperties": False,
    },
}

EPISODES_SCHEMA: dict[str, Any] = {
    "description": "List podcast episodes produced so far, newest first, with audio and transcript paths. Pass `id` to re-send one episode's audio.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Episode id from a previous listing, to attach its audio again."},
            "limit": {"type": "integer", "description": "How many to list (1-50, default 10)."},
        },
        "additionalProperties": False,
    },
}
