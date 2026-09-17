from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from .database import NovelDatabase
from .models import ContextBundle
from .pricing import estimate_chinese_tokens
from .story_state import StoryStateStore


STOPWORDS = {
    "这一章",
    "本章",
    "故事",
    "小说",
    "发生",
    "一个",
    "一些",
    "然后",
    "以及",
    "需要",
    "进行",
    "继续",
}


def extract_terms(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", text)
    terms: list[str] = []
    for word in words:
        if word in STOPWORDS:
            continue
        terms.append(word.lower())
        if re.fullmatch(r"[\u4e00-\u9fff]{4,8}", word):
            terms.extend(word[index : index + 2] for index in range(len(word) - 1))
    return list(dict.fromkeys(terms))


def _score_text(text: str, terms: list[str]) -> float:
    lowered = text.lower()
    counts = Counter(term for term in terms if term and term in lowered)
    return sum((1.0 + min(lowered.count(term), 3) * 0.2) * count for term, count in counts.items())


class ContextRetriever:
    def __init__(self, database: NovelDatabase) -> None:
        self.database = database
        self.story_states = StoryStateStore(database)

    def build_context(
        self,
        novel_id: int,
        query: str,
        *,
        before_ordinal: int | None = None,
        max_tokens: int = 18_000,
        recent_chapters: int = 2,
        max_memories: int = 24,
        max_historical_chapters: int = 6,
    ) -> ContextBundle:
        novel = self.database.get_novel(novel_id)
        if not novel:
            raise ValueError("小说项目不存在")
        chapters = self.database.list_chapters(novel_id)
        if before_ordinal is not None:
            chapters = [
                chapter for chapter in chapters if int(chapter["ordinal"]) < before_ordinal
            ]
        memories = self.database.list_memories(novel_id, statuses=("confirmed",))
        if before_ordinal is not None:
            memories = [
                memory
                for memory in memories
                if memory.get("source_chapter_ordinal") is None
                or int(memory["source_chapter_ordinal"]) < before_ordinal
            ]
        terms = extract_terms(query)
        location_replacements = self._location_replacements(novel_id)

        recent = chapters[-recent_chapters:] if recent_chapters else []
        recent_ids = {chapter["id"] for chapter in recent}

        scored_memories = []
        for memory in memories:
            searchable = " ".join(
                [memory["subject"], memory["content"], memory["keywords"], memory["evidence"]]
            )
            score = _score_text(searchable, terms)
            if memory["pinned"]:
                score += 100
            scored_memories.append((score, memory))
        selected_memories = [
            item for score, item in sorted(scored_memories, key=lambda pair: pair[0], reverse=True)
            if score > 0 or item["pinned"]
        ][:max_memories]

        scored_chapters = []
        for chapter in chapters:
            if chapter["id"] in recent_ids:
                continue
            searchable = f"{chapter['title']}\n{chapter['summary']}\n{chapter['content']}"
            score = _score_text(searchable, terms)
            if score > 0:
                scored_chapters.append((score, chapter))
        selected_history = [
            item for _, item in sorted(scored_chapters, key=lambda pair: pair[0], reverse=True)
        ][:max_historical_chapters]

        sections: dict[str, str] = {}
        if novel["style_guide"]:
            sections["固定创作规则"] = novel["style_guide"]
        sections.update(self._build_story_state_sections(novel_id, terms))
        if selected_memories:
            lines = []
            for memory in selected_memories:
                source = memory.get("source_chapter_title") or memory["source_type"]
                lines.append(
                    f"- [{memory['kind']}] {memory['subject']}：{memory['content']}（来源：{source}）"
                )
            sections["已确认的相关记忆"] = "\n".join(lines)
        if recent:
            blocks = []
            for chapter in recent:
                content = self._replace_location_names(
                    chapter["content"][-2500:], location_replacements
                )
                summary = self._replace_location_names(
                    chapter["summary"] or "暂无摘要", location_replacements
                )
                blocks.append(f"### {chapter['title']}\n摘要：{summary}\n章节结尾：{content}")
            sections["最近章节"] = "\n\n".join(blocks)
        if selected_history:
            blocks = []
            for chapter in selected_history:
                excerpt = self._replace_location_names(
                    chapter["content"][:1800], location_replacements
                )
                summary = self._replace_location_names(
                    chapter["summary"] or "暂无摘要", location_replacements
                )
                blocks.append(f"### {chapter['title']}\n摘要：{summary}\n相关原文：{excerpt}")
            sections["历史相关章节"] = "\n\n".join(blocks)

        context = self._fit_sections(sections, max_tokens=max_tokens)
        return ContextBundle(
            text=context,
            source_chapter_ids=[chapter["id"] for chapter in selected_history + recent],
            memory_ids=[memory["id"] for memory in selected_memories],
            estimated_tokens=estimate_chinese_tokens(context),
            sections=sections,
        )

    def _build_story_state_sections(
        self, novel_id: int, terms: list[str]
    ) -> dict[str, str]:
        state = self.story_states.export_bundle(novel_id)
        sections: dict[str, str] = {}

        settings = state["fixed_settings"]
        if settings:
            sections["V2固定设定"] = "\n".join(
                f"- [{row['category']}] {row['setting_key']}：{row['setting_value']}"
                for row in settings[:40]
            )

        characters = self._relevant_rows(
            state["characters"], terms, fields=("character_name", "state"), limit=16
        )
        if characters:
            sections["V2人物当前状态"] = "\n".join(
                f"- {row['character_name']}：{json.dumps(row['state'], ensure_ascii=False)}"
                for row in characters
            )

        locations = self._relevant_rows(
            state["locations"],
            terms,
            fields=("canonical_name", "owner", "direction", "purpose"),
            limit=20,
        )
        if locations:
            sections["V2场景地图"] = "\n".join(
                "- "
                + row["canonical_name"]
                + f"｜方位：{row['direction'] or '未定'}｜归属：{row['owner'] or '未定'}"
                + f"｜别称：{','.join(row['aliases']) or '无'}"
                + f"｜禁用别称：{','.join(row['forbidden_aliases']) or '无'}"
                for row in locations
            )

        endings = state["chapter_end_states"]
        if endings:
            latest = endings[-1]
            sections["V2上一章精确末态"] = json.dumps(latest["state"], ensure_ascii=False)

        open_threads = [row for row in state["open_threads"] if row["status"] == "open"]
        if open_threads:
            sections["V2未解决事项"] = "\n".join(
                f"- [重要度{row['importance']}] {row['description']}｜预计：{row['expected_stage'] or '未定'}"
                for row in open_threads[:20]
            )

        clues = [row for row in state["foreshadowing"] if row["status"] != "resolved"]
        if clues:
            sections["V2伏笔边界"] = "\n".join(
                f"- {row['description']}｜允许回收：{row['allowed_resolution_stage'] or '未定'}"
                f"｜禁止提前：{row['forbidden_before'] or '未定'}"
                for row in clues[:20]
            )
        return sections

    def _location_replacements(self, novel_id: int) -> dict[str, str]:
        state = self.story_states.export_bundle(novel_id)
        replacements: dict[str, str] = {}
        for row in state["locations"]:
            for old_name in row["forbidden_aliases"]:
                if old_name:
                    replacements[str(old_name)] = str(row["canonical_name"])
        return replacements

    @staticmethod
    def _replace_location_names(text: str, replacements: dict[str, str]) -> str:
        for old_name in sorted(replacements, key=len, reverse=True):
            text = text.replace(old_name, replacements[old_name])
        return text

    @staticmethod
    def _relevant_rows(
        rows: list[dict[str, Any]],
        terms: list[str],
        *,
        fields: tuple[str, ...],
        limit: int,
    ) -> list[dict[str, Any]]:
        if len(rows) <= limit:
            return rows
        scored = []
        for row in rows:
            text = " ".join(str(row.get(field, "")) for field in fields)
            scored.append((_score_text(text, terms), row))
        return [row for _, row in sorted(scored, key=lambda pair: pair[0], reverse=True)[:limit]]

    @staticmethod
    def _fit_sections(sections: dict[str, str], *, max_tokens: int) -> str:
        parts: list[str] = []
        for title, body in sections.items():
            candidate = "\n\n".join([*parts, f"## {title}\n{body}"])
            if estimate_chinese_tokens(candidate) <= max_tokens:
                parts.append(f"## {title}\n{body}")
                continue
            remaining_tokens = max_tokens - estimate_chinese_tokens("\n\n".join(parts))
            if remaining_tokens <= 200:
                break
            approx_chars = int(remaining_tokens / 0.6)
            parts.append(f"## {title}\n{body[:approx_chars]}\n[因上下文预算截断]")
            break
        return "\n\n".join(parts)
