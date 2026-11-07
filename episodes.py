"""Episode storage: <data dir>/episodes/<date>-<slug>/{episode.mp3, transcript.md, episode.json}."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .mix import Episode
from .script import Script


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:48].strip("-") or "episode"


def new_episode_dir(root: Path, title: str) -> Path:
    base = root / "episodes" / f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(title)}"
    path, n = base, 2
    while path.exists():
        path, n = base.with_name(f"{base.name}-{n}"), n + 1
    path.mkdir(parents=True)
    return path


def clock(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def write_transcript(script: Script, episode: Episode, path: Path) -> None:
    rows = [f"# {script.title}", ""]
    if script.description:
        rows += [script.description, ""]
    rows += ["Hosts: " + ", ".join(f"{h.name} ({h.voice})" for h in script.hosts), ""]
    chapter = None
    for timed in episode.timeline:
        line = script.lines[timed.index]
        if line.chapter and line.chapter != chapter:
            chapter = line.chapter
            rows += ["", f"## {chapter}  [{clock(timed.start)}]", ""]
        rows.append(f"**[{clock(timed.start)}] {line.host.name}:** {line.text}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def save_meta(script: Script, episode: Episode, folder: Path) -> dict[str, Any]:
    chapters, seen = [], ""
    for timed in episode.timeline:
        name = script.lines[timed.index].chapter
        if name and name != seen:
            chapters.append({"title": name, "start": clock(timed.start)})
            seen = name
    meta = {
        "title": script.title,
        "description": script.description,
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "duration": round(episode.duration, 1),
        "duration_text": clock(episode.duration),
        "hosts": [{"name": h.name, "voice": h.voice} for h in script.hosts],
        "lines": len(script.lines),
        "chapters": chapters,
        "mastered": episode.mastered,
        "audio": str(episode.path),
        "transcript": str(folder / "transcript.md"),
    }
    (folder / "episode.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def list_episodes(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    folder = root / "episodes"
    if not folder.is_dir():
        return []
    rows = []
    for child in sorted(folder.iterdir(), reverse=True):
        meta_file = child / "episode.json"
        if meta_file.is_file() and (child / "episode.mp3").is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except ValueError:
                continue
            rows.append({"id": child.name, **{k: meta.get(k) for k in
                         ("title", "created", "duration_text", "audio", "transcript", "chapters")}})
        if len(rows) >= limit:
            break
    return rows
