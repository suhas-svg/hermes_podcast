"""Validate and normalise an episode script supplied by the model."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DEFAULT_VOICES = ("en-US-AndrewMultilingualNeural", "en-US-AvaMultilingualNeural", "en-GB-RyanNeural")
_VOICE_RE = re.compile(r"^[a-z]{2,3}-[A-Za-z]{2,4}(?:-[A-Za-z]+)?-[A-Za-z0-9]+Neural$")
_RATE_RE = re.compile(r"^[+-]\d{1,2}%$")
_PITCH_RE = re.compile(r"^[+-]\d{1,3}Hz$")
MAX_LINE_CHARS = 1500


class ScriptError(ValueError):
    """The script cannot be produced as given; the message says how to fix it."""


@dataclass(frozen=True)
class Host:
    name: str
    voice: str
    rate: str = "+0%"
    pitch: str = "+0Hz"


@dataclass(frozen=True)
class Line:
    host: Host
    text: str
    chapter: str = ""


@dataclass
class Script:
    title: str
    hosts: list[Host]
    lines: list[Line]
    description: str = ""
    chapters: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(len(line.text) for line in self.lines)


def _clean(text: Any) -> str:
    text = str(text or "")
    text = re.sub(r"[*_`#>]+", "", text)  # markdown the TTS would read aloud
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    return " ".join(text.split())


def parse_hosts(raw: Any, default_voices: list[str]) -> list[Host]:
    if not raw:
        raw = [{"name": "Alex"}, {"name": "Sam"}]
    if not isinstance(raw, list) or not 1 <= len(raw) <= 3:
        raise ScriptError("hosts must be a list of 1 to 3 hosts.")
    hosts: list[Host] = []
    for index, item in enumerate(raw):
        item = {"name": item} if isinstance(item, str) else item
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise ScriptError(f"Host {index + 1} needs a name.")
        voice = str(item.get("voice") or default_voices[index % len(default_voices)]).strip()
        rate = str(item.get("rate") or "+0%").strip()
        pitch = str(item.get("pitch") or "+0Hz").strip()
        if not _VOICE_RE.match(voice):
            raise ScriptError(f"{voice!r} is not an Edge voice name.",)
        if not _RATE_RE.match(rate) or not _PITCH_RE.match(pitch):
            raise ScriptError("rate looks like '+10%' or '-5%'; pitch looks like '+0Hz' or '-20Hz'.")
        hosts.append(Host(str(item["name"]).strip(), voice, rate, pitch))
    names = [h.name.lower() for h in hosts]
    if len(set(names)) != len(names):
        raise ScriptError("Host names must be different.")
    return hosts


def parse_script(args: dict[str, Any], *, default_voices: list[str], max_lines: int, max_chars: int) -> Script:
    title = _clean(args.get("title"))
    if not title:
        raise ScriptError("title is required.")
    hosts = parse_hosts(args.get("hosts"), default_voices)
    by_name = {h.name.lower(): h for h in hosts}
    raw_lines = args.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ScriptError("lines must be a non-empty list of {speaker, text}.")
    if len(raw_lines) > max_lines:
        raise ScriptError(f"Too many lines ({len(raw_lines)}); the limit is {max_lines}. Merge short turns.")
    lines: list[Line] = []
    chapter = ""
    chapters: list[str] = []
    for index, item in enumerate(raw_lines, start=1):
        if not isinstance(item, dict):
            raise ScriptError(f"Line {index} must be an object with speaker and text.")
        speaker = str(item.get("speaker") or "").strip().lower()
        host = by_name.get(speaker) or (hosts[0] if len(hosts) == 1 and not speaker else None)
        if host is None:
            raise ScriptError(f"Line {index}: speaker {item.get('speaker')!r} is not one of the hosts "
                              f"({', '.join(h.name for h in hosts)}).")
        text = _clean(item.get("text"))
        if not text:
            raise ScriptError(f"Line {index} has no text.")
        if len(text) > MAX_LINE_CHARS:
            raise ScriptError(f"Line {index} is {len(text)} characters; keep turns under {MAX_LINE_CHARS}.")
        new_chapter = _clean(item.get("chapter"))
        if new_chapter and new_chapter != chapter:
            chapter = new_chapter
            chapters.append(chapter)
        lines.append(Line(host, text, chapter))
    script = Script(title, hosts, lines, _clean(args.get("description")), chapters)
    if script.chars > max_chars:
        raise ScriptError(f"The script is {script.chars} characters; the limit is {max_chars}. Tighten it.")
    return script
