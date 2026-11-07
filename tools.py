"""Tool, slash-command and CLI handlers for Podcast Studio."""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

from . import episodes as store
from .mix import MixError, find_ffmpeg, master
from .script import DEFAULT_VOICES, ScriptError, parse_script
from .synth import Synthesize, SynthError, list_voices, synthesize_lines

logger = logging.getLogger(__name__)
PLUGIN = "podcast"


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps({"success": True, **payload}, ensure_ascii=False)


def _error(message: str, hint: str = "") -> str:
    return json.dumps({"error": message, **({"hint": hint} if hint else {})}, ensure_ascii=False)


def _guard(fn: Callable[..., str]) -> Callable[..., str]:
    @wraps(fn)
    def wrapper(self: "PodcastTools", args: dict[str, Any], **_kwargs: Any) -> str:
        try:
            return fn(self, args or {})
        except ScriptError as exc:
            return _error(str(exc), "Fix the script and call the tool again.")
        except SynthError as exc:
            return _error(str(exc), exc.hint)
        except MixError as exc:
            return _error(str(exc), "Check that ffmpeg works, or clear the plugin's ffmpeg_path setting.")
        except Exception as exc:  # tool handlers must never raise
            logger.exception("podcast tool %s failed", fn.__name__)
            return _error(f"Unexpected Podcast Studio error: {exc}")

    return wrapper


def _data_root() -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir  # noqa: PLC0415 - Hermes runtime only
    except ImportError:
        return Path.home() / ".hermes" / "plugin-data" / PLUGIN
    return Path(plugin_data_dir(PLUGIN))


def _media_tag(path: str) -> str:
    return f"MEDIA:{path}"


class PodcastTools:
    def __init__(self, ctx: Any, *, synth: Optional[Synthesize] = None,
                 data_root: Optional[Callable[[], Path]] = None, voice_fetch: Any = None,
                 pacing: Optional[dict[str, float]] = None) -> None:
        self.ctx = ctx
        self._synth = synth
        self._pacing = pacing or {}
        self._root = data_root or _data_root
        self._voice_fetch = voice_fetch

    def _get(self, key: str, default: Any) -> Any:
        try:
            value = self.ctx.get_config(key, default)
        except Exception:
            return default
        return default if value in (None, "") else value

    def _int(self, key: str, default: int, low: int, high: int) -> int:
        try:
            return max(low, min(high, int(self._get(key, default))))
        except (TypeError, ValueError):
            return default

    # ---------- tools ----------

    @_guard
    def produce(self, args: dict[str, Any]) -> str:
        voices = [str(self._get("host_a_voice", DEFAULT_VOICES[0])), str(self._get("host_b_voice", DEFAULT_VOICES[1])),
                  DEFAULT_VOICES[2]]
        script = parse_script(args, default_voices=voices,
                              max_lines=self._int("max_lines", 160, 1, 400),
                              max_chars=self._int("max_chars", 24000, 200, 100000))
        started = time.monotonic()
        folder = store.new_episode_dir(self._root(), script.title)
        try:
            clips = synthesize_lines(script.lines, folder / "clips", synth=self._synth,
                                     concurrency=self._int("concurrency", 3, 1, 8), **self._pacing)
            ffmpeg = find_ffmpeg(str(self._get("ffmpeg_path", "")))
            episode = master(script, clips, folder / "episode.mp3", ffmpeg=ffmpeg,
                             pause=self._int("pause_ms", 350, 0, 2000) / 1000,
                             chime=bool(self._get("intro_chime", True)))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        shutil.rmtree(folder / "clips", ignore_errors=True)
        store.write_transcript(script, episode, folder / "transcript.md")
        meta = store.save_meta(script, episode, folder)
        payload = {
            "episode_id": folder.name,
            "title": script.title,
            "duration": meta["duration_text"],
            "hosts": meta["hosts"],
            "lines": meta["lines"],
            "chapters": meta["chapters"],
            "audio": meta["audio"],
            "transcript": meta["transcript"],
            "mastered": episode.mastered,
            "render_seconds": round(time.monotonic() - started, 1),
            "media_tag": _media_tag(meta["audio"]),
            "deliver": "Include the media_tag line exactly, on its own line, in your reply so the audio is attached.",
        }
        if not episode.mastered:
            payload["note"] = "ffmpeg was not found, so the episode has no intro chime, pauses, loudness pass or embedded chapters."
        return _ok(payload)

    @_guard
    def voices(self, args: dict[str, Any]) -> str:
        locale = str(args.get("locale") or "en").strip().lower()
        gender = str(args.get("gender") or "").strip().lower()
        rows = []
        for v in list_voices(self._root() / "voices.json", fetch=self._voice_fetch):
            if not str(v.get("Locale", "")).lower().startswith(locale):
                continue
            if gender and str(v.get("Gender", "")).lower() != gender:
                continue
            tags = v.get("VoiceTag") or {}
            rows.append({"voice": v.get("ShortName"), "locale": v.get("Locale"), "gender": v.get("Gender"),
                         "personality": ", ".join(tags.get("VoicePersonalities") or [])})
        return _ok({"locale": locale, "count": len(rows), "voices": rows[:60],
                    "defaults": [self._get("host_a_voice", DEFAULT_VOICES[0]), self._get("host_b_voice", DEFAULT_VOICES[1])]})

    @_guard
    def list(self, args: dict[str, Any]) -> str:
        wanted = str(args.get("id") or "").strip()
        try:
            limit = max(1, min(50, int(args.get("limit", 10))))
        except (TypeError, ValueError):
            limit = 10
        rows = store.list_episodes(self._root(), limit=500 if wanted else limit)
        if wanted:
            match = next((r for r in rows if r["id"] == wanted), None)
            if not match:
                return _error(f"No episode with id {wanted!r}.", "Call podcast_episodes without id to list them.")
            return _ok({"episode": match, "media_tag": _media_tag(match["audio"]),
                        "deliver": "Include the media_tag line exactly, on its own line, in your reply."})
        return _ok({"count": len(rows), "episodes": rows,
                    "folder": str(self._root() / "episodes")})

    # ---------- /podcast ----------

    def slash(self, raw_args: str, **_kwargs: Any) -> str:
        try:
            parts = shlex.split(raw_args or "")
        except ValueError as exc:
            return f"Could not parse /podcast arguments: {exc}"
        command = parts[0].lower() if parts else "list"
        try:
            if command == "list":
                return self._text_list()
            if command == "voices":
                return self._text_voices(parts[1] if len(parts) > 1 else "en")
            if command == "doctor":
                return self._text_doctor()
        except (SynthError, MixError) as exc:
            return f"Podcast Studio error: {exc}"
        return ("Usage: /podcast [list|voices [locale]|doctor]\n"
                "Ask Hermes to turn an article, PDF or your notes into an episode.")

    def _text_list(self) -> str:
        rows = store.list_episodes(self._root(), limit=10)
        if not rows:
            return "No episodes yet. Try: \"Make a 3-minute podcast about <a link or topic>.\""
        lines = ["Recent episodes:"]
        lines += [f"  {r['created']}  {r['duration_text']}  {r['title']}\n    {r['audio']}" for r in rows]
        return "\n".join(lines)

    def _text_voices(self, locale: str) -> str:
        data = json.loads(self.voices({"locale": locale}))
        if data.get("error"):
            return f"Podcast Studio error: {data['error']}"
        return "\n".join([f"{data['count']} voices for {locale}:"] +
                         [f"  {v['voice']}  ({v['gender']}{', ' + v['personality'] if v['personality'] else ''})"
                          for v in data["voices"][:25]])

    def _text_doctor(self) -> str:
        ffmpeg = find_ffmpeg(str(self._get("ffmpeg_path", "")))
        try:
            import edge_tts  # noqa: F401, PLC0415
            edge = "installed"
        except ImportError:
            edge = "MISSING (run `hermes pm install`)"
        return (f"edge-tts: {edge}\n"
                f"ffmpeg:   {ffmpeg or 'not found (episodes are joined without chime, pauses or chapters)'}\n"
                f"episodes: {self._root() / 'episodes'}")

    # ---------- hermes podcast ----------

    def cli(self, args: Any) -> int:
        command = getattr(args, "podcast_command", None) or "list"
        if command == "play":
            rows = store.list_episodes(self._root(), limit=50)
            ref = getattr(args, "episode", None)
            match = rows[0] if rows and not ref else next((r for r in rows if ref and ref in r["id"]), None)
            if not match:
                print("No matching episode. Run `hermes podcast list`.")
                return 1
            print(f"Playing {match['title']} ({match['duration_text']})")
            _open(match["audio"])
            return 0
        text = {"list": self._text_list, "doctor": self._text_doctor}.get(command)
        if text is None and command == "voices":
            print(self._text_voices(getattr(args, "locale", "en") or "en"))
            return 0
        if text is None:
            print("Usage: hermes podcast <list|play [ID]|voices [LOCALE]|doctor>")
            return 2
        print(text())
        return 0


def _open(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - opens the user's own episode in their default player
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _setup_cli(subparser: Any) -> None:
    subs = subparser.add_subparsers(dest="podcast_command")
    subs.add_parser("list", help="List recent episodes")
    play = subs.add_parser("play", help="Open an episode in your default audio player")
    play.add_argument("episode", nargs="?", help="Episode id (or part of it); newest if omitted")
    voices = subs.add_parser("voices", help="List host voices for a locale")
    voices.add_argument("locale", nargs="?", default="en")
    subs.add_parser("doctor", help="Check edge-tts and ffmpeg")
