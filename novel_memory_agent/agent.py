from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .database import NovelDatabase
from .deepseek import DeepSeekClient, DeepSeekError, parse_json_response
from .models import AgentRunResult, LLMResponse
from .parser import parse_manuscript, parse_outline
from .pricing import estimate_chinese_tokens, estimate_cny
from .prompts import (
    CONTINUITY_SYSTEM,
    CONTINUITY_USER,
    DRAFT_SYSTEM,
    DRAFT_USER,
    MEMORY_SYSTEM,
    MEMORY_USER,
    STORY_STATE_SYSTEM,
    STORY_STATE_USER,
    TASK_CARD_SYSTEM,
    TASK_CARD_USER,
    UPDATE_MEMORY_SYSTEM,
    UPDATE_MEMORY_USER,
    V2_STATE_UPDATE_SYSTEM,
    V2_STATE_UPDATE_USER,
)
from .retrieval import ContextRetriever
from .story_state import SECTIONS, StoryStateStore


class BudgetExceededError(RuntimeError):
    pass


class NovelAgent:
    def __init__(
        self,
        database: NovelDatabase,
        settings: Settings,
        client: DeepSeekClient | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client = client or DeepSeekClient(settings)
        self.retriever = ContextRetriever(database)
        self.story_states = StoryStateStore(database)

    def import_manuscript(self, novel_id: int, text: str) -> int:
        chapters = parse_manuscript(text)
        if not chapters:
            raise ValueError("正文为空或无法解析")
        self.database.replace_source_document(
            novel_id, kind="manuscript", title="小说正文原稿", content=text
        )
        self.database.replace_chapters(novel_id, chapters)
        return len(chapters)

    def import_outline(self, novel_id: int, text: str) -> int:
        chapters = parse_outline(text)
        if not chapters:
            raise ValueError("大纲为空或无法解析")
        self.database.replace_source_document(
            novel_id, kind="story_bible", title="完整剧本与故事设定", content=text
        )
        self.database.replace_outline(novel_id, chapters)
        return len(chapters)

    def analyze_chapter(self, novel_id: int, chapter_id: int) -> dict[str, Any]:
        chapter = next(
            (item for item in self.database.list_chapters(novel_id) if item["id"] == chapter_id),
            None,
        )
        if not chapter:
            raise ValueError("章节不存在")
        response = self._call(
            novel_id,
            "memory_extract",
            [
                {"role": "system", "content": MEMORY_SYSTEM},
                {
                    "role": "user",
                    "content": MEMORY_USER.format(
                        title=chapter["title"], content=chapter["content"]
                    ),
                },
            ],
            max_tokens=3500,
            json_mode=True,
        )
        result = parse_json_response(response.content)
        self.database.update_chapter_summary(chapter_id, str(result.get("summary", "")))
        created = 0
        for memory in result.get("memories", []):
            if not isinstance(memory, dict) or not memory.get("content"):
                continue
            keywords = memory.get("keywords", [])
            if isinstance(keywords, list):
                keywords = ",".join(str(item) for item in keywords)
            self.database.add_memory(
                novel_id,
                kind=str(memory.get("kind", "event")),
                subject=str(memory.get("subject", chapter["title"])),
                content=str(memory["content"]),
                keywords=str(keywords),
                source_type="ai_candidate",
                source_chapter_id=chapter_id,
                evidence=str(memory.get("evidence", ""))[:500],
                confidence=float(memory.get("confidence", 0.5)),
                status="candidate",
            )
            created += 1
        return {"summary": result.get("summary", ""), "memory_count": created}

    def initialize_story_state(
        self,
        novel_id: int,
        *,
        through_chapter: int | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Extract and persist the six V2 state sections in one controlled AI call."""
        novel = self.database.get_novel(novel_id)
        if not novel:
            raise ValueError("小说项目不存在")
        chapters = self.database.list_chapters(novel_id)
        if through_chapter is not None:
            chapters = [row for row in chapters if int(row["ordinal"]) <= through_chapter]
        if not chapters:
            raise ValueError("没有可用于初始化的正文章节")
        manuscript = "\n\n".join(
            f"## [数据库章节ID={row['id']}] {row['title']}\n{row['content']}" for row in chapters
        )
        source = self.database.get_source_document(novel_id, "story_bible")
        if source:
            story_bible = source["content"]
        else:
            outline = self.database.list_outline(novel_id)
            story_bible = "\n\n".join(
                f"## {row['title']}\n{row['core_event']}\n{row['raw_text']}" for row in outline
            )
        state_messages = [
            {"role": "system", "content": STORY_STATE_SYSTEM},
            {
                "role": "user",
                "content": STORY_STATE_USER.format(
                    manuscript=manuscript,
                    story_bible=story_bible or "未提供",
                ),
            },
        ]
        response = self._call(
            novel_id,
            "story_state_init",
            state_messages,
            model=model,
            max_tokens=12000,
            json_mode=True,
        )
        parsed = None
        if response.finish_reason != "length":
            try:
                parsed = parse_json_response(response.content)
            except DeepSeekError:
                pass
        if parsed is None:
            response = self._call(
                novel_id,
                "story_state_init_json_retry",
                state_messages
                + [
                    {
                        "role": "user",
                        "content": (
                            "上一次初始化结果无效或过长。请根据同一材料重新提取最小充分状态，"
                            "严格遵守各数组数量、列表长度和60字字段上限。只返回一个完整JSON对象，"
                            "不要Markdown代码块、解释、剧情复述或重复事实。"
                        ),
                    }
                ],
                model=model,
                max_tokens=12000,
                json_mode=True,
            )
            if response.finish_reason == "length":
                raise DeepSeekError("V2故事状态初始化重试JSON仍被输出上限截断，数据库导入进度已保留")
            parsed = parse_json_response(response.content)
        bundle: dict[str, list[dict[str, Any]]] = {}
        for section in SECTIONS:
            value = parsed.get(section, [])
            if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                raise DeepSeekError(f"故事状态分区 {section} 必须是对象数组")
            bundle[section] = value
        self._normalize_optional_story_state_chapter_ids(novel_id, bundle)
        counts = self.story_states.import_bundle(novel_id, bundle)
        return {
            "through_chapter": max(int(row["ordinal"]) for row in chapters),
            "chapter_count": len(chapters),
            "counts": counts,
            "state": bundle,
        }

    def _normalize_optional_story_state_chapter_ids(
        self, novel_id: int, bundle: dict[str, list[dict[str, Any]]]
    ) -> None:
        """Remove future-outline IDs mistakenly returned as existing chapter IDs."""
        valid_ids = {int(row["id"]) for row in self.database.list_chapters(novel_id)}
        # chapter_end_states may only describe imported manuscript chapters.
        # A model can see the full outline and occasionally emits a planned future
        # chapter here; keeping it would contaminate the current story state.
        bundle["chapter_end_states"] = [
            item
            for item in bundle["chapter_end_states"]
            if item.get("chapter_id") is not None
            and int(item["chapter_id"]) in valid_ids
        ]
        optional_fields = {
            "fixed_settings": ("source_chapter_id",),
            "characters": ("source_chapter_id",),
            "locations": ("source_chapter_id",),
            "open_threads": ("first_chapter_id", "last_chapter_id"),
            "foreshadowing": ("first_chapter_id",),
        }
        for section, fields in optional_fields.items():
            for item in bundle[section]:
                for field in fields:
                    value = item.get(field)
                    if value is not None and int(value) not in valid_ids:
                        item[field] = None

    def preview_context(
        self,
        novel_id: int,
        outline_chapter_id: int,
        instruction: str = "",
    ):
        outline = self.database.get_outline_chapter(outline_chapter_id)
        if not outline or outline["novel_id"] != novel_id:
            raise ValueError("大纲章节不存在")
        query = "\n".join(
            [outline["title"], outline["core_event"], outline["raw_text"], instruction]
        )
        bundle = self.retriever.build_context(
            novel_id,
            query,
            before_ordinal=int(outline["ordinal"]),
            max_tokens=self.settings.max_context_tokens,
        )
        rolling = self._build_three_chapter_window(novel_id, int(outline["ordinal"]))
        if rolling:
            section = f"## V2三章滚动剧情窗\n{rolling}"
            bundle.text = f"{bundle.text}\n\n{section}".strip()
            bundle.sections["V2三章滚动剧情窗"] = rolling
            bundle.estimated_tokens = estimate_chinese_tokens(bundle.text)
        return bundle

    def _build_three_chapter_window(self, novel_id: int, ordinal: int) -> str:
        outline = {int(row["ordinal"]): row for row in self.database.list_outline(novel_id)}
        labels = ((ordinal - 1, "上一章：必须承接其后果"), (ordinal, "本章：只推进本章任务"), (ordinal + 1, "下一章：只能保留接口，禁止提前发生"))
        lines = []
        for number, label in labels:
            row = outline.get(number)
            if not row:
                continue
            event = row["core_event"] or row["raw_text"] or "未提供核心事件"
            lines.append(f"- {label}\n  {row['title']}：{event}")
        lines.append("- 跨章原则：重点矛盾允许跨2至3章铺垫、升级和产生后果，不得机械地在一章内全部解决。")
        return "\n".join(lines)

    def generate_chapter(
        self,
        novel_id: int,
        outline_chapter_id: int,
        *,
        instruction: str = "",
        target_chars: int | None = None,
        model: str | None = None,
        replace_draft_id: int | None = None,
    ) -> AgentRunResult:
        novel = self.database.get_novel(novel_id)
        outline = self.database.get_outline_chapter(outline_chapter_id)
        if not novel or not outline or outline["novel_id"] != novel_id:
            raise ValueError("小说或大纲章节不存在")
        target = int(target_chars or novel["target_chapter_chars"])
        context = self.preview_context(novel_id, outline_chapter_id, instruction)

        task_messages = [
            {"role": "system", "content": TASK_CARD_SYSTEM},
            {
                "role": "user",
                "content": TASK_CARD_USER.format(
                    title=outline["title"],
                    core_event=outline["core_event"],
                    outline_raw=outline["raw_text"],
                    instruction=instruction or "无额外要求",
                    target_chars=target,
                    context=context.text,
                ),
            },
        ]
        task_response = self._call(
            novel_id,
            "task_card",
            task_messages,
            model=model,
            max_tokens=5000,
            json_mode=True,
        )
        task_card = None
        if task_response.finish_reason != "length":
            try:
                task_card = parse_json_response(task_response.content)
            except DeepSeekError:
                pass
        if task_card is None:
            task_response = self._call(
                novel_id,
                "task_card_json_retry",
                task_messages
                + [
                    {
                        "role": "user",
                        "content": (
                            "上一次任务卡无效或过长。请重新输出最小充分任务卡，严格遵守条目数量"
                            "和100字字段上限，只返回一个完整JSON对象，不要解释或Markdown。"
                        ),
                    }
                ],
                model=model,
                max_tokens=5000,
                json_mode=True,
            )
            if task_response.finish_reason == "length":
                raise DeepSeekError("章节任务卡JSON重试仍被输出上限截断")
            task_card = parse_json_response(task_response.content)
        # The database outline title is the canonical heading.  WebNovelBench
        # experiments intentionally prefix the local experiment ordinal while
        # retaining the source chapter number (for example, "第8章 第118章 ...").
        # Models sometimes shorten it back to the source title in task-card
        # JSON, which made the reviewer report a false title mismatch.
        task_card["title"] = outline["title"]
        clarifications = task_card.get("clarification_required") or []
        if clarifications:
            raise DeepSeekError("章节存在会改变主线的缺失信息：" + "；".join(clarifications))

        task_json = json.dumps(task_card, ensure_ascii=False, indent=2)
        draft_response = self._call(
            novel_id,
            "draft_generation",
            [
                {"role": "system", "content": DRAFT_SYSTEM},
                {
                    "role": "user",
                    "content": DRAFT_USER.format(
                        task_card=task_json,
                        context=context.text,
                        instruction=instruction or "无额外要求",
                        target_chars=target,
                    ),
                },
            ],
            model=model,
            # Prioritize a complete chapter. Length is audited after generation;
            # we deliberately avoid an extra LLM compression call to control cost.
            # Leave enough transport headroom for Chinese text and punctuation.
            # The separate 6,000-character audit remains the actual content
            # limit; this token ceiling should not cut off an otherwise valid
            # chapter before that audit can run.
            max_tokens=max(8000, int(target * 1.8)),
            thinking=False,
        )

        draft_content = self._ensure_chapter_heading(draft_response.content, outline["title"])
        if draft_response.finish_reason == "length" or self._looks_truncated(draft_content):
            raise DeepSeekError(
                "章节生成被输出上限截断，已阻止保存和确认。请缩短目标字数或重试；"
                "程序不会再把半句话写入正式正文。"
            )

        continuity_messages = [
            {"role": "system", "content": CONTINUITY_SYSTEM},
            {
                "role": "user",
                "content": CONTINUITY_USER.format(
                    task_card=task_json,
                    context=context.text,
                    draft=draft_content,
                ),
            },
        ]
        continuity_response = self._call(
            novel_id,
            "continuity_check",
            continuity_messages,
            model=model,
            max_tokens=2500,
            json_mode=True,
        )
        try:
            continuity = parse_json_response(continuity_response.content)
        except DeepSeekError:
            # Keep the already generated chapter in memory and retry only the
            # inexpensive structured audit. This avoids paying to regenerate
            # the chapter merely because the reviewer emitted malformed JSON.
            continuity_response = self._call(
                novel_id,
                "continuity_check_json_retry",
                continuity_messages
                + [
                    {
                        "role": "user",
                        "content": (
                            "上一次审核结果不是有效JSON。请重新审核同一正文，严格只返回一个"
                            "完整JSON对象，不要Markdown代码块或解释。"
                        ),
                    }
                ],
                model=model,
                max_tokens=2500,
                json_mode=True,
            )
            continuity = parse_json_response(continuity_response.content)
        missing = any(
            item.get("status") == "missing"
            for item in continuity.get("outline_completion", [])
            if isinstance(item, dict)
        )
        if missing:
            continuity.setdefault("high_risk", []).append(
                {
                    "issue": "大纲核心要求缺失",
                    "suggestion": "补全标记为 missing 的核心剧情后再确认。",
                }
            )
        actual_chars = len(re.sub(r"\s+", "", draft_content))
        if actual_chars < 2100 or actual_chars > 6000:
            continuity.setdefault("high_risk", []).append(
                {
                    "issue": f"章节篇幅不在允许范围：{actual_chars}字",
                    "suggestion": "完整重写并将正文控制在2100至6000字内；无需为了接近目标字数额外压缩。",
                }
            )
        # Medium/low-risk observations are recorded for analysis but do not
        # trigger costly rewrites.  Only explicit high-risk failures enforce a
        # rewrite, matching CONTINUITY_USER and the experiment quality floor.
        continuity["passed"] = not bool(continuity.get("high_risk"))
        draft_data = {
            "outline_chapter_id": outline_chapter_id,
            "title": outline["title"],
            "author_instruction": instruction,
            "task_card": task_card,
            "context_text": context.text,
            "context_meta": {
                "chapter_ids": context.source_chapter_ids,
                "memory_ids": context.memory_ids,
                "estimated_tokens": context.estimated_tokens,
            },
            "content": draft_content,
            "continuity_report": continuity,
        }
        if replace_draft_id is None:
            draft_id = self.database.create_draft(novel_id, **draft_data)
        else:
            self.database.replace_draft(replace_draft_id, novel_id=novel_id, **draft_data)
            draft_id = replace_draft_id
        return AgentRunResult(
            task_card=task_card,
            context_bundle=context,
            draft=draft_content,
            continuity_report=continuity,
            draft_id=draft_id,
        )

    @staticmethod
    def _looks_truncated(text: str) -> bool:
        stripped = text.rstrip()
        if not stripped:
            return True
        return stripped[-1] not in "。！？…’”）】」』.!?"

    @staticmethod
    def _ensure_chapter_heading(text: str, title: str) -> str:
        """Normalize every generated draft to an explicit chapter heading."""
        lines = text.strip().splitlines()
        if not lines:
            return title
        first = lines[0].strip().lstrip("#").strip()
        if first == title:
            lines[0] = title
        elif re.match(r"^第[一二三四五六七八九十百零〇两0-9]+章(?:\s|$)", first):
            lines[0] = title
        else:
            lines.insert(0, title)
        while len(lines) > 1 and not lines[1].strip():
            lines.pop(1)
        if len(lines) > 1:
            lines.insert(1, "")
        return "\n".join(lines).strip()

    def repair_truncated_draft(self, draft_id: int, *, extra_chars: int = 1200) -> str:
        draft = self.database.get_draft(draft_id)
        if not draft:
            raise ValueError("草稿不存在")
        tail = draft["content"][-1800:]
        response = self._call(
            draft["novel_id"],
            "draft_repair",
            [
                {
                    "role": "system",
                    "content": (
                        "你是小说断章修复器。只输出从断点处直接接续的正文，不要重复已有文字，"
                        "不要解释，不要写下一章剧情。必须补完断句并完成本章任务卡中尚未完成的事件。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"章节任务卡：\n{draft['task_card_json']}\n\n"
                        f"已有正文末尾：\n{tail}\n\n"
                        f"请从最后一个未完成句子的断点直接续写，约 {extra_chars} 字。"
                    ),
                },
            ],
            max_tokens=max(2500, int(extra_chars * 1.5)),
            thinking=False,
            draft_id=draft_id,
        )
        if response.finish_reason == "length" or self._looks_truncated(response.content):
            raise DeepSeekError("修复文本仍被截断，未写入数据库，请重试并减少 --extra-chars。")
        repaired = draft["content"].rstrip() + response.content
        self.database.repair_draft_and_chapter(draft_id, repaired)
        return repaired

    def accept_and_extract_memories(self, draft_id: int) -> dict[str, Any]:
        draft = self.database.get_draft(draft_id)
        if not draft:
            raise ValueError("草稿不存在")
        continuity = json.loads(draft.get("continuity_json") or "{}")
        if not continuity.get("passed", False):
            raise ValueError("一致性或完整性检查未通过，不能确认该草稿")
        if self._looks_truncated(draft["content"]):
            raise ValueError("草稿疑似在句中截断，不能确认；请先修复或重新生成")
        response = self._call(
            draft["novel_id"],
            "memory_update",
            [
                {"role": "system", "content": UPDATE_MEMORY_SYSTEM},
                {
                    "role": "user",
                    "content": UPDATE_MEMORY_USER.format(
                        title=draft["title"],
                        context=draft["context_text"],
                        draft=draft["content"],
                    ),
                },
            ],
            max_tokens=3500,
            json_mode=True,
            draft_id=draft_id,
        )
        result = parse_json_response(response.content)
        chapter_id = self.database.accept_draft(draft_id)
        self.database.update_chapter_summary(chapter_id, str(result.get("summary", "")))
        count = 0
        for memory in result.get("memories", []):
            if not isinstance(memory, dict) or not memory.get("content"):
                continue
            keywords = memory.get("keywords", [])
            if isinstance(keywords, list):
                keywords = ",".join(str(item) for item in keywords)
            self.database.add_memory(
                draft["novel_id"],
                kind=str(memory.get("kind", "event")),
                subject=str(memory.get("subject", draft["title"])),
                content=str(memory["content"]),
                keywords=str(keywords),
                source_type="ai_candidate",
                source_chapter_id=chapter_id,
                evidence=str(memory.get("evidence", ""))[:500],
                confidence=float(memory.get("confidence", 0.5)),
                status="candidate",
            )
            count += 1
        return {"chapter_id": chapter_id, "candidate_memories": count}

    def accept_v2_draft(self, draft_id: int) -> dict[str, Any]:
        """Accept an AI-approved draft and advance all V2 state before the next chapter."""
        draft = self.database.get_draft(draft_id)
        if not draft or draft["status"] not in {"draft", "accepted"}:
            raise ValueError("草稿不存在或状态不支持V2接收/修复")
        continuity = json.loads(draft.get("continuity_json") or "{}")
        if not continuity.get("passed", False):
            raise ValueError("AI一致性审核未通过，批处理已停止")
        if self._looks_truncated(draft["content"]):
            raise ValueError("草稿疑似截断，批处理已停止")
        outline = self.database.get_outline_chapter(draft["outline_chapter_id"])
        if not outline:
            raise ValueError("草稿缺少对应大纲")
        chapters = self.database.list_chapters(draft["novel_id"])
        existing_chapter = next(
            (row for row in chapters if int(row["ordinal"]) == int(outline["ordinal"])),
            None,
        )
        if draft["status"] == "accepted":
            if not existing_chapter:
                raise ValueError("草稿已接收但找不到对应正式章节")
            chapter_id = int(existing_chapter["id"])
            existing_end_ids = {
                int(item["chapter_id"])
                for item in self.story_states.export_bundle(draft["novel_id"])["chapter_end_states"]
            }
            if chapter_id in existing_end_ids:
                raise ValueError("草稿和V2章节末状态均已写入，无需重复接收")
        else:
            next_ordinal = max((int(row["ordinal"]) for row in chapters), default=0) + 1
            if next_ordinal != int(outline["ordinal"]):
                raise ValueError(
                    f"章节顺序错误：数据库下一章应为{next_ordinal}，草稿对应第{outline['ordinal']}章"
                )
        next_outline = next(
            (
                row
                for row in self.database.list_outline(draft["novel_id"])
                if int(row["ordinal"]) == int(outline["ordinal"]) + 1
            ),
            None,
        )
        next_boundary = (
            f"{next_outline['title']}：{next_outline['core_event']}" if next_outline else "全书结束"
        )
        state_messages = [
            {"role": "system", "content": V2_STATE_UPDATE_SYSTEM},
            {
                "role": "user",
                "content": V2_STATE_UPDATE_USER.format(
                    context=draft["context_text"],
                    draft=draft["content"],
                    next_outline=next_boundary,
                ),
            },
        ]
        response = self._call(
            draft["novel_id"],
            "v2_state_update",
            state_messages,
            max_tokens=8000,
            json_mode=True,
            draft_id=draft_id,
        )
        if response.finish_reason == "length":
            raise DeepSeekError("V2状态更新JSON被输出上限截断，草稿与进度已保留")
        try:
            parsed = parse_json_response(response.content)
        except DeepSeekError:
            # Repair the small malformed response itself instead of sending the
            # full chapter/context through state extraction again. This is both
            # cheaper and less likely to produce a second semantic variation.
            response = self._call(
                draft["novel_id"],
                "v2_state_update_json_retry",
                [
                    {
                        "role": "system",
                        "content": (
                            "你是JSON语法修复器。只修复输入中的JSON语法、引号、转义、逗号和括号；"
                            "不得增删或改写事实。只输出一个合法JSON对象，不要解释或Markdown。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": "修复以下V2状态JSON：\n\n" + response.content,
                    },
                ],
                max_tokens=6000,
                json_mode=True,
                draft_id=draft_id,
            )
            if response.finish_reason == "length":
                raise DeepSeekError("V2状态更新重试JSON仍被输出上限截断，草稿与进度已保留")
            parsed = parse_json_response(response.content)
        bundle: dict[str, list[dict[str, Any]]] = {}
        for section in SECTIONS:
            value = parsed.get(section, [])
            if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                raise DeepSeekError(f"V2状态更新分区 {section} 必须是对象数组")
            bundle[section] = value
        bundle = self._drop_invalid_state_items(bundle)
        if draft["status"] == "draft":
            chapter_id = self.database.accept_draft(draft_id)
        for item in bundle["chapter_end_states"]:
            item["chapter_id"] = chapter_id
        for item in bundle["characters"]:
            item.setdefault("source_chapter_id", chapter_id)
        for item in bundle["locations"]:
            item.setdefault("source_chapter_id", chapter_id)
        for item in bundle["open_threads"]:
            item["last_chapter_id"] = chapter_id
            item.setdefault("first_chapter_id", chapter_id)
        for item in bundle["foreshadowing"]:
            item.setdefault("first_chapter_id", chapter_id)
        self._normalize_optional_story_state_chapter_ids(draft["novel_id"], bundle)
        counts = self.story_states.import_bundle(draft["novel_id"], bundle)
        return {"chapter_id": chapter_id, "ordinal": int(outline["ordinal"]), "counts": counts}

    @staticmethod
    def _drop_invalid_state_items(
        bundle: dict[str, list[dict[str, Any]]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Drop optional malformed model items before database validation."""
        required = {
            "fixed_settings": ("key", "value"),
            "characters": ("name",),
            "locations": ("name",),
            "chapter_end_states": ("chapter_id",),
            "open_threads": ("key", "description"),
            "foreshadowing": ("key", "description"),
        }
        cleaned: dict[str, list[dict[str, Any]]] = {}
        for section in SECTIONS:
            cleaned[section] = [
                item for item in bundle.get(section, [])
                if all(str(item.get(key, "")).strip() for key in required[section])
            ]
        return cleaned

    def _call(
        self,
        novel_id: int,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int,
        thinking: bool = False,
        json_mode: bool = False,
        draft_id: int | None = None,
    ) -> LLMResponse:
        self._ensure_budget(novel_id)
        request_started_at = datetime.now(UTC)
        response = self.client.complete(
            messages,
            model=model,
            max_tokens=max_tokens,
            thinking=thinking,
            json_mode=json_mode,
        )
        cost = estimate_cny(
            response.model,
            response.usage,
            exchange_rate=self.settings.exchange_rate_cny_per_usd,
            period=self.settings.pricing_period,
            at_utc=request_started_at,
        )
        self.database.log_usage(
            novel_id=novel_id,
            draft_id=draft_id,
            task_type=task_type,
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens,
            cache_hit_tokens=response.usage.cache_hit_tokens,
            cache_miss_tokens=response.usage.cache_miss_tokens,
            completion_tokens=response.usage.completion_tokens,
            cost_cny=cost,
        )
        return response

    def _ensure_budget(self, novel_id: int) -> None:
        novel = self.database.get_novel(novel_id)
        if not novel:
            raise ValueError("小说项目不存在")
        spent = float(self.database.usage_summary(novel_id)["cost_cny"])
        stop = min(float(novel["budget_cny"]), self.settings.budget_stop_cny)
        if spent >= stop:
            raise BudgetExceededError(
                f"项目累计费用约 {spent:.2f} 元，已达到预算停止线 {stop:.2f} 元。"
            )
