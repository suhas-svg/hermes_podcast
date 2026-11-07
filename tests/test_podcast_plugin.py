"""Behaviour tests for Podcast Studio.

Speech synthesis is injected (a fake that writes audio files), so the tests run offline.
Tests that master real audio need ffmpeg on PATH and are skipped without it.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load_plugin():
    name = "podcast_plugin_under_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PLUGIN = _load_plugin()
tools_mod = sys.modules["podcast_plugin_under_test.tools"]
script_mod = sys.modules["podcast_plugin_under_test.script"]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe not on PATH")


class FakeCtx:
    def __init__(self, config=None):
        self.config = config or {}
        self.tools, self.commands, self.cli, self.skills, self.blueprints = {}, {}, {}, {}, {}

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_tool(self, name, toolset, schema, handler, description=""):
        self.tools[name] = (toolset, schema, handler)

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = handler

    def register_cli_command(self, name, help, setup_fn, handler_fn):
        self.cli[name] = (setup_fn, handler_fn)

    def register_skill(self, name, path):
        self.skills[name] = Path(path)

    def register_automation_blueprint(self, key, **fields):
        self.blueprints[key] = fields


class FakeSynth:
    """Records calls; writes a real tone with ffmpeg when asked, else placeholder MP3 bytes."""

    def __init__(self, *, tone=False, fail_first=0, always_fail=False):
        self.calls, self.tone, self.fail_first, self.always_fail = [], tone, fail_first, always_fail

    async def __call__(self, text, voice, rate, pitch, out):
        self.calls.append((text, voice, rate, pitch))
        if self.always_fail or len(self.calls) <= self.fail_first:
            raise ConnectionError("voice service unavailable")
        if self.tone:
            seconds = 0.5 + len(text) / 100
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"sine=frequency=440:duration={seconds}", "-ar", "24000", "-ac", "1",
                            "-b:a", "48k", str(out)], check=True)
        else:
            out.write_bytes(b"\xff\xf3" + b"\x00" * 6000)  # ~1 s at edge-tts' 48 kbps


NO_PACING = {"gap": 0.0, "backoff": 0.0}


def _tools(tmp_path, synth=None, **config):
    return tools_mod.PodcastTools(FakeCtx(config), synth=synth or FakeSynth(),
                                  data_root=lambda: tmp_path, voice_fetch=None, pacing=NO_PACING)


SCRIPT = {
    "title": "Attention Is All You Need",
    "description": "Why transformers replaced recurrence.",
    "lines": [
        {"speaker": "Alex", "text": "Today: the **paper** that started it all.", "chapter": "Intro"},
        {"speaker": "Sam", "text": "The transformer one? Okay, walk me through it."},
        {"speaker": "Alex", "text": "It drops recurrence entirely.", "chapter": "The idea"},
        {"speaker": "Alex", "text": "Every token looks at every other token at once."},
        {"speaker": "Sam", "text": "So that's why it trains so fast on GPUs."},
    ],
}


def _produce(tools, args=None):
    return json.loads(tools.produce(args or SCRIPT))


# ---------- script validation ----------

@pytest.mark.parametrize("change, message", [
    ({"lines": [{"speaker": "Jordan", "text": "hi"}]}, "not one of the hosts"),
    ({"hosts": [{"name": "A", "voice": "robot"}]}, "not an Edge voice"),
    ({"hosts": [{"name": "A"}, {"name": "a"}]}, "must be different"),
    ({"lines": [{"speaker": "Alex", "text": "  **  "}]}, "has no text"),
    ({"title": ""}, "title is required"),
])
def test_bad_scripts_return_fixable_errors_without_synthesizing(tmp_path, change, message):
    synth = FakeSynth()
    result = _produce(_tools(tmp_path, synth), {**SCRIPT, **change})
    assert message in result["error"]
    assert result["hint"]
    assert synth.calls == []
    assert not (tmp_path / "episodes").exists() or not any((tmp_path / "episodes").iterdir())


def test_line_and_character_limits_come_from_config(tmp_path):
    many = {**SCRIPT, "lines": SCRIPT["lines"] * 3}
    assert "limit is 10" in _produce(_tools(tmp_path, max_lines=10), many)["error"]
    assert "limit is 200" in _produce(_tools(tmp_path, max_chars=200), many)["error"]


def test_markdown_is_stripped_and_chapters_carry_forward():
    script = script_mod.parse_script(SCRIPT, default_voices=list(script_mod.DEFAULT_VOICES),
                                     max_lines=50, max_chars=5000)
    assert script.lines[0].text == "Today: the paper that started it all."
    assert [line.chapter for line in script.lines] == ["Intro", "Intro", "The idea", "The idea", "The idea"]
    assert script.chapters == ["Intro", "The idea"]
    assert [h.name for h in script.hosts] == ["Alex", "Sam"]


# ---------- production ----------

def test_produce_without_ffmpeg_still_delivers_an_episode(tmp_path):
    synth = FakeSynth()
    result = _produce(_tools(tmp_path, synth, ffmpeg_path="no-such-ffmpeg-binary"))
    assert result["success"] and result["mastered"] is False and "note" in result
    audio = Path(result["audio"])
    assert audio.is_file() and audio.stat().st_size == 5 * 6002
    assert result["media_tag"] == f"MEDIA:{audio}"
    assert not (audio.parent / "clips").exists()
    voices = {call[0]: call[1] for call in synth.calls}
    assert voices["It drops recurrence entirely."] == "en-US-AndrewMultilingualNeural"
    assert voices["So that's why it trains so fast on GPUs."] == "en-US-AvaMultilingualNeural"
    meta = json.loads((audio.parent / "episode.json").read_text(encoding="utf-8"))
    assert meta["lines"] == 5 and [c["title"] for c in meta["chapters"]] == ["Intro", "The idea"]


def test_configured_host_voices_are_used(tmp_path):
    synth = FakeSynth()
    _produce(_tools(tmp_path, synth, ffmpeg_path="no-such-ffmpeg-binary", host_b_voice="en-GB-SoniaNeural"))
    assert {c[1] for c in synth.calls} == {"en-US-AndrewMultilingualNeural", "en-GB-SoniaNeural"}


def test_transient_voice_failures_are_retried(tmp_path):
    synth = FakeSynth(fail_first=1)
    result = _produce(_tools(tmp_path, synth, ffmpeg_path="no-such-ffmpeg-binary", concurrency=1))
    assert result["success"]
    assert len(synth.calls) == 6


def test_requests_are_spaced_so_the_voice_service_does_not_throttle(tmp_path):
    starts = []

    class Timing(FakeSynth):
        async def __call__(self, *args):
            starts.append(time.monotonic())
            await super().__call__(*args)

    tools = tools_mod.PodcastTools(FakeCtx({"ffmpeg_path": "no-such-ffmpeg-binary", "concurrency": 3}),
                                   synth=Timing(), data_root=lambda: tmp_path, pacing={"gap": 0.1})
    assert json.loads(tools.produce(SCRIPT))["success"]
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert len(starts) == 5 and min(gaps) >= 0.09


def test_a_line_that_keeps_failing_aborts_cleanly(tmp_path):
    result = _produce(_tools(tmp_path, FakeSynth(always_fail=True), ffmpeg_path="no-such-ffmpeg-binary"))
    assert "Could not synthesize" in result["error"] and "internet" in result["hint"]
    assert list((tmp_path / "episodes").iterdir()) == []


def test_produce_works_when_called_inside_a_running_event_loop(tmp_path):
    tools = _tools(tmp_path, ffmpeg_path="no-such-ffmpeg-binary")

    async def inside_loop():
        return json.loads(tools.produce(SCRIPT))

    assert asyncio.run(inside_loop())["success"]


@needs_ffmpeg
def test_mastered_episode_has_pauses_chime_chapters_and_tags(tmp_path):
    result = _produce(_tools(tmp_path, FakeSynth(tone=True)))
    assert result["success"] and result["mastered"] is True
    audio = Path(result["audio"])
    probe = json.loads(subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_chapters", "-show_streams",
         str(audio)], capture_output=True, text=True, check=True).stdout)
    stream = probe["streams"][0]
    assert stream["codec_name"] == "mp3" and stream["sample_rate"] == "44100"
    assert [c["tags"]["title"] for c in probe["chapters"]] == ["Intro", "The idea"]
    assert probe["format"]["tags"]["title"] == "Attention Is All You Need"
    speech = sum(0.5 + len(line["text"].replace("**", "")) / 100 for line in SCRIPT["lines"])
    duration = float(probe["format"]["duration"])
    assert speech + 2.0 < duration < speech + 5.0  # chime + pauses + tail
    assert not (audio.parent / "work").exists()
    transcript = (audio.parent / "transcript.md").read_text(encoding="utf-8")
    assert "## The idea  [00:" in transcript and "**[00:02] Alex:**" in transcript  # after the 1.85 s chime


# ---------- voices and episodes ----------

VOICES = [
    {"ShortName": "en-US-AvaMultilingualNeural", "Locale": "en-US", "Gender": "Female",
     "VoiceTag": {"VoicePersonalities": ["Expressive", "Caring"]}},
    {"ShortName": "en-GB-RyanNeural", "Locale": "en-GB", "Gender": "Male", "VoiceTag": {}},
    {"ShortName": "es-ES-AlvaroNeural", "Locale": "es-ES", "Gender": "Male"},
]


def test_voices_filter_and_cache(tmp_path):
    fetches = []

    async def fetch():
        fetches.append(1)
        return VOICES

    tools = tools_mod.PodcastTools(FakeCtx(), data_root=lambda: tmp_path, voice_fetch=fetch)
    english = json.loads(tools.voices({"locale": "en"}))
    assert [v["voice"] for v in english["voices"]] == ["en-US-AvaMultilingualNeural", "en-GB-RyanNeural"]
    assert english["voices"][0]["personality"] == "Expressive, Caring"
    male = json.loads(tools.voices({"locale": "en", "gender": "Male"}))
    assert [v["voice"] for v in male["voices"]] == ["en-GB-RyanNeural"]
    assert json.loads(tools.voices({"locale": "es"}))["count"] == 1
    assert fetches == [1]


def test_voice_list_failure_is_reported(tmp_path):
    async def fetch():
        raise OSError("offline")

    tools = tools_mod.PodcastTools(FakeCtx(), data_root=lambda: tmp_path, voice_fetch=fetch)
    assert "offline" in json.loads(tools.voices({}))["error"]


def test_episodes_list_and_resend(tmp_path):
    tools = _tools(tmp_path, ffmpeg_path="no-such-ffmpeg-binary")
    first = _produce(tools)
    second = _produce(tools, {**SCRIPT, "title": "Second one"})
    listing = json.loads(tools.list({}))
    assert [e["title"] for e in listing["episodes"]] == ["Second one", "Attention Is All You Need"]
    again = json.loads(tools.list({"id": first["episode_id"]}))
    assert again["media_tag"] == first["media_tag"]
    assert "No episode" in json.loads(tools.list({"id": "nope"}))["error"]
    assert second["episode_id"] != first["episode_id"]


def test_slash_and_cli(tmp_path, capsys):
    tools = _tools(tmp_path, ffmpeg_path="no-such-ffmpeg-binary")
    assert "No episodes yet" in tools.slash("")
    _produce(tools)
    assert "Attention Is All You Need" in tools.slash("list")
    assert "Usage: /podcast" in tools.slash("bogus")
    assert "edge-tts:" in tools.slash("doctor")

    parser = argparse.ArgumentParser()
    tools_mod._setup_cli(parser)
    assert tools.cli(parser.parse_args(["list"])) == 0
    assert "Attention Is All You Need" in capsys.readouterr().out
    assert tools.cli(parser.parse_args(["play", "zzz-no-match"])) == 1


# ---------- registration ----------

def test_register_wires_tools_command_cli_skill_and_blueprint():
    ctx = FakeCtx()
    PLUGIN.register(ctx)
    assert set(ctx.tools) == {"podcast_produce", "podcast_voices", "podcast_episodes"}
    assert all(toolset == "podcast" for toolset, _, _ in ctx.tools.values())
    assert "podcast" in ctx.commands and "podcast" in ctx.cli
    assert ctx.skills["audio-overview"].is_file()
    blueprint = ctx.blueprints["daily-briefing"]
    assert blueprint["skills"] == ("podcast:audio-overview",)
    slot_names = {slot["name"] for slot in blueprint["slots"]}
    assert {"topics", "minutes", "time"} <= slot_names

    manifest = (PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8")
    for name in ctx.tools:
        assert f"- {name}" in manifest


def test_blueprint_is_accepted_by_hermes_when_available():
    blueprint_plugins = pytest.importorskip("cron.blueprint_plugins")
    ctx = FakeCtx()
    PLUGIN.register(ctx)
    built = blueprint_plugins.build_plugin_blueprint("podcast", "daily-briefing", **ctx.blueprints["daily-briefing"])
    assert built.key == "podcast:daily-briefing"
