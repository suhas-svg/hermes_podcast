"""Speech synthesis with Microsoft Edge's online voices (edge-tts), concurrent and retried."""

from __future__ import annotations

import asyncio
import random
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .script import Line

# (text, voice, rate, pitch, out_path) -> None; injectable for tests.
Synthesize = Callable[[str, str, str, str, Path], Awaitable[None]]
_VOICE_CACHE_SECONDS = 7 * 24 * 3600


class SynthError(RuntimeError):
    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


def _edge():
    try:
        import edge_tts  # noqa: PLC0415 - optional until first use
    except ImportError as exc:
        raise SynthError(
            "The edge-tts package is not installed.",
            hint="Run `hermes plugins install podcast --install-deps` or `hermes pm install`.",
        ) from exc
    return edge_tts


async def edge_synthesize(text: str, voice: str, rate: str, pitch: str, out: Path) -> None:
    edge_tts = _edge()
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, receive_timeout=60)
    await communicate.save(str(out))


def run_async(coro: Awaitable[Any]) -> Any:
    """Run a coroutine from sync code, even when the caller's thread already runs a loop."""
    result: dict[str, Any] = {}

    def target() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # re-raised in the caller's thread
            result["error"] = exc

    worker = threading.Thread(target=target, name="podcast-synth", daemon=True)
    worker.start()
    worker.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


class _Pacer:
    """Spaces request starts: the Edge service answers rapid back-to-back requests with no audio."""

    def __init__(self, gap: float) -> None:
        self.gap, self.next_start, self.lock = gap, 0.0, asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            now = time.monotonic()
            if self.next_start > now:
                await asyncio.sleep(self.next_start - now)
            self.next_start = max(now, self.next_start) + self.gap


async def _one(synth: Synthesize, line: Line, out: Path, sem: asyncio.Semaphore, pacer: _Pacer,
               attempts: int, backoff: float) -> None:
    async with sem:
        for attempt in range(1, attempts + 1):
            await pacer.wait()
            try:
                await synth(line.text, line.host.voice, line.host.rate, line.host.pitch, out)
                if out.is_file() and out.stat().st_size > 0:
                    return
                raise SynthError("the voice service returned no audio")
            except Exception as exc:
                if attempt == attempts:
                    raise SynthError(
                        f"Could not synthesize a line for {line.host.name} ({line.host.voice}): {exc}",
                        hint="Check the internet connection and that the voice exists (podcast_voices).",
                    ) from exc
                await asyncio.sleep(min(8.0, backoff * 2 ** (attempt - 1)) * random.uniform(0.75, 1.25))


async def _all(synth: Synthesize, lines: list[Line], workdir: Path, concurrency: int, attempts: int,
               gap: float, backoff: float) -> list[Path]:
    sem, pacer = asyncio.Semaphore(concurrency), _Pacer(gap)
    paths = [workdir / f"line_{i:03d}.mp3" for i in range(len(lines))]
    await asyncio.gather(*(_one(synth, line, path, sem, pacer, attempts, backoff)
                           for line, path in zip(lines, paths)))
    return paths


def synthesize_lines(lines: list[Line], workdir: Path, *, synth: Optional[Synthesize] = None,
                     concurrency: int = 3, attempts: int = 6, gap: float = 0.6,
                     backoff: float = 1.5) -> list[Path]:
    workdir.mkdir(parents=True, exist_ok=True)
    return run_async(_all(synth or edge_synthesize, lines, workdir, concurrency, attempts, gap, backoff))


async def _list_voices() -> list[dict[str, Any]]:
    return await _edge().list_voices()


def list_voices(cache: Path, *, fetch: Optional[Callable[[], Awaitable[list[dict[str, Any]]]]] = None) -> list[dict[str, Any]]:
    import json  # noqa: PLC0415

    if cache.is_file() and time.time() - cache.stat().st_mtime < _VOICE_CACHE_SECONDS:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            pass
    try:
        voices = run_async((fetch or _list_voices)())
    except SynthError:
        raise
    except Exception as exc:
        raise SynthError(f"Could not fetch the Edge voice list: {exc}",
                         hint="Check the internet connection.") from exc
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(voices), encoding="utf-8")
    return voices
