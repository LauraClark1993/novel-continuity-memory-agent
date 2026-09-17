from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParsedChapter:
    ordinal: int
    title: str
    content: str


@dataclass(slots=True)
class OutlineChapter:
    ordinal: int
    title: str
    core_event: str
    raw_text: str = ""


@dataclass(slots=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0


@dataclass(slots=True)
class LLMResponse:
    content: str
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    reasoning_content: str = ""
    finish_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ContextBundle:
    text: str
    source_chapter_ids: list[int]
    memory_ids: list[int]
    estimated_tokens: int
    sections: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AgentRunResult:
    task_card: dict[str, Any]
    context_bundle: ContextBundle
    draft: str
    continuity_report: dict[str, Any]
    draft_id: int
