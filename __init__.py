"""Podcast Studio: turn anything Hermes reads into a mastered two-host podcast episode."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .schemas import EPISODES_SCHEMA, PRODUCE_SCHEMA, VOICES_SCHEMA
from .tools import PodcastTools, _setup_cli

logger = logging.getLogger(__name__)

_TOOLS = (
    ("podcast_produce", PRODUCE_SCHEMA, "produce", "Render a podcast script to a mastered MP3 episode."),
    ("podcast_voices", VOICES_SCHEMA, "voices", "List voices available for podcast hosts."),
    ("podcast_episodes", EPISODES_SCHEMA, "list", "List or re-send produced podcast episodes."),
)

_DELIVER = {
    "name": "deliver", "type": "enum", "label": "Where to deliver?", "default": "origin",
    "options": ("origin", "local", "telegram", "discord", "email"), "strict": False,
    "help": "origin = the chat you set this up from; local = save only",
}


def register(ctx: Any) -> None:
    """Register the tools, /podcast, `hermes podcast`, the skill and the daily-briefing blueprint."""
    tools = PodcastTools(ctx)
    for name, schema, method, description in _TOOLS:
        ctx.register_tool(name=name, toolset="podcast", schema=schema,
                          handler=getattr(tools, method), description=description)

    ctx.register_command("podcast", handler=tools.slash, description="Podcast Studio episodes and voices",
                         args_hint="[list|voices LOCALE|doctor]")
    ctx.register_cli_command(name="podcast", help="Podcast Studio episodes, playback and voices",
                             setup_fn=_setup_cli, handler_fn=tools.cli)

    skills_dir = Path(__file__).parent / "skills"
    for child in sorted(skills_dir.iterdir()) if skills_dir.is_dir() else ():
        if (child / "SKILL.md").is_file():
            ctx.register_skill(child.name, child / "SKILL.md")

    ctx.register_automation_blueprint(
        "daily-briefing",
        title="Daily podcast briefing",
        description="Every morning, a short two-host audio episode about the news on topics you choose.",
        category="daily",
        schedule_template="{minute} {hour} * * *",
        prompt_template=(
            "Load the podcast:audio-overview skill. Search the web for the most important news from the "
            "last 24 hours about: {topics}. Read at least three sources. Write a two-host episode of about "
            "{minutes} minutes that covers the stories and why they matter, naming the source of each fact. "
            "Produce it with podcast_produce and reply with a 3-bullet summary plus the media_tag line."
        ),
        slots=[
            {"name": "time", "type": "time", "label": "What time?", "default": "07:30",
             "help": "24h local time, e.g. 07:30"},
            {"name": "topics", "type": "text", "label": "Which topics?",
             "default": "AI research, open-source software"},
            {"name": "minutes", "type": "enum", "label": "How long?", "default": "4",
             "options": ("2", "4", "6", "8")},
            _DELIVER,
        ],
        skills=("podcast:audio-overview",),
        tags=("daily", "briefing", "audio", "podcast"),
    )
    logger.debug("podcast: registered %d tools, /podcast, hermes podcast, skill and blueprint", len(_TOOLS))
