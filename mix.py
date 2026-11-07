"""Assemble synthesized lines into one episode: pauses, intro chime, loudness, chapters, tags."""

from __future__ import annotations

import shutil
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .script import Script

RATE = 24000
_EDGE_MP3_BYTES_PER_SECOND = 48000 / 8  # edge-tts audio-24khz-48kbitrate-mono-mp3
_CHIME = ("aevalsrc=exprs='0.32*sin(2*PI*659.25*t)*exp(-3.2*t)+0.24*sin(2*PI*987.77*t)*exp(-2.6*t)"
          "+0.16*sin(2*PI*1318.5*t)*exp(-2.2*t)':s=24000:d=1.6")


class MixError(RuntimeError):
    pass


@dataclass
class Timed:
    index: int
    start: float
    end: float


@dataclass
class Episode:
    path: Path
    duration: float
    timeline: list[Timed]
    mastered: bool  # False when ffmpeg was unavailable and clips were joined as-is


def find_ffmpeg(configured: str = "") -> Optional[str]:
    if configured:
        return configured if Path(configured).is_file() else shutil.which(configured)
    return shutil.which("ffmpeg")


def _run(argv: list[str]) -> None:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise MixError(f"ffmpeg failed: {proc.stderr.strip()[-400:]}")


def _to_wav(ffmpeg: str, src: Path, dst: Path) -> None:
    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
          "-ac", "1", "-ar", str(RATE), "-sample_fmt", "s16", str(dst)])


def _frames(seconds: float) -> bytes:
    return b"\x00\x00" * int(RATE * seconds)


def _pause_after(script: Script, i: int, pause: float) -> float:
    if i + 1 >= len(script.lines):
        return 0.0
    here, nxt = script.lines[i], script.lines[i + 1]
    if nxt.chapter != here.chapter:
        return pause * 2.6
    return pause if nxt.host != here.host else pause * 0.5


def _metadata(script: Script, timeline: list[Timed], total: float, path: Path) -> None:
    def esc(text: str) -> str:
        return "".join("\\" + c if c in "=;#\\\n" else c for c in text)

    rows = [";FFMETADATA1", f"title={esc(script.title)}", "artist=Hermes Podcast Studio",
            "genre=Podcast", f"comment={esc(script.description)}"]
    starts: list[tuple[float, str]] = []
    seen = ""
    for timed in timeline:
        chapter = script.lines[timed.index].chapter
        if chapter and chapter != seen:
            starts.append((timed.start, chapter))
            seen = chapter
    for n, (start, title) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else total
        rows += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(start * 1000)}",
                 f"END={int(end * 1000)}", f"title={esc(title)}"]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def master(script: Script, clips: list[Path], out: Path, *, ffmpeg: Optional[str],
           pause: float = 0.35, chime: bool = True, bitrate: str = "128k") -> Episode:
    if not ffmpeg:
        return _join_raw(clips, out)
    work = out.parent / "work"
    work.mkdir(exist_ok=True)
    wavs = [work / f"{c.stem}.wav" for c in clips]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda pair: _to_wav(ffmpeg, *pair), zip(clips, wavs)))
    timeline: list[Timed] = []
    joined = work / "joined.wav"
    with wave.open(str(joined), "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(RATE)
        cursor = 0.0
        if chime:
            chime_wav = work / "chime.wav"
            _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", _CHIME,
                  "-ac", "1", "-ar", str(RATE), "-sample_fmt", "s16", str(chime_wav)])
            cursor += _append(dst, chime_wav) + _pad(dst, 0.25)
        for i, wav in enumerate(wavs):
            start = cursor
            cursor += _append(dst, wav)
            timeline.append(Timed(i, start, cursor))
            cursor += _pad(dst, _pause_after(script, i, pause))
        cursor += _pad(dst, 0.6)
    meta = work / "chapters.txt"
    _metadata(script, timeline, cursor, meta)
    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-i", str(meta),
          "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
          "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100",
          "-c:a", "libmp3lame", "-b:a", bitrate, "-id3v2_version", "3", str(out)])
    shutil.rmtree(work, ignore_errors=True)
    return Episode(out, cursor, timeline, True)


def _append(dst: wave.Wave_write, wav: Path) -> float:
    with wave.open(str(wav), "rb") as src:
        if src.getframerate() != RATE or src.getnchannels() != 1:
            raise MixError(f"unexpected audio format in {wav.name}")
        frames = src.readframes(src.getnframes())
    dst.writeframes(frames)
    return len(frames) / 2 / RATE


def _pad(dst: wave.Wave_write, seconds: float) -> float:
    if seconds > 0:
        dst.writeframes(_frames(seconds))
    return seconds


def _join_raw(clips: list[Path], out: Path) -> Episode:
    """No ffmpeg: MP3 is frame-based, so clips from one encoder concatenate cleanly."""
    timeline, cursor = [], 0.0
    with out.open("wb") as dst:
        for i, clip in enumerate(clips):
            data = clip.read_bytes()
            dst.write(data)
            length = len(data) / _EDGE_MP3_BYTES_PER_SECOND
            timeline.append(Timed(i, cursor, cursor + length))
            cursor += length
    return Episode(out, cursor, timeline, False)
