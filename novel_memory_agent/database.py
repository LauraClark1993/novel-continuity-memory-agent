from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class NovelDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS novels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    author TEXT NOT NULL DEFAULT '',
                    genre TEXT NOT NULL DEFAULT '',
                    style_guide TEXT NOT NULL DEFAULT '',
                    target_chapter_chars INTEGER NOT NULL DEFAULT 3000,
                    budget_cny REAL NOT NULL DEFAULT 150,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'confirmed',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(novel_id, ordinal)
                );

                CREATE TABLE IF NOT EXISTS outline_chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    core_event TEXT NOT NULL DEFAULT '',
                    raw_text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'planned',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(novel_id, ordinal)
                );

                CREATE TABLE IF NOT EXISTS source_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(novel_id, kind)
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    content TEXT NOT NULL,
                    keywords TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT 'ai_candidate',
                    source_chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
                    evidence TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                    outline_chapter_id INTEGER REFERENCES outline_chapters(id) ON DELETE SET NULL,
                    title TEXT NOT NULL,
                    author_instruction TEXT NOT NULL DEFAULT '',
                    task_card_json TEXT NOT NULL DEFAULT '{}',
                    context_text TEXT NOT NULL DEFAULT '',
                    context_meta_json TEXT NOT NULL DEFAULT '{}',
                    content TEXT NOT NULL DEFAULT '',
                    continuity_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS usage_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER REFERENCES novels(id) ON DELETE CASCADE,
                    draft_id INTEGER REFERENCES drafts(id) ON DELETE SET NULL,
                    task_type TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_cny REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fixed_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                    category TEXT NOT NULL,
                    setting_key TEXT NOT NULL,
                    setting_value TEXT NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '',
                    source_chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(novel_id, category, setting_key)
                );

                CREATE TABLE IF NOT EXISTS character_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                    character_name TEXT NOT NULL,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    evidence TEXT NOT NULL DEFAULT '',
                    source_chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(novel_id, character_name)
                );

                CREATE TABLE IF NOT EXISTS locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                    canonical_name TEXT NOT NULL,
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    forbidden_aliases_json TEXT NOT NULL DEFAULT '[]',
                    location_type TEXT NOT NULL DEFAULT '',
                    owner TEXT NOT NULL DEFAULT '',
                    direction TEXT NOT NULL DEFAULT '',
                    adjacent_json TEXT NOT NULL DEFAULT '[]',
                    purpose TEXT NOT NULL DEFAULT '',
                    evidence TEXT NOT NULL DEFAULT '',
                    source_chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(novel_id, canonical_name)
                );

                CREATE TABLE IF NOT EXISTS chapter_end_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                    chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    evidence TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(novel_id, chapter_id)
                );

                CREATE TABLE IF NOT EXISTS open_threads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                    thread_key TEXT NOT NULL,
                    thread_type TEXT NOT NULL DEFAULT 'conflict',
                    description TEXT NOT NULL,
                    importance INTEGER NOT NULL DEFAULT 3,
                    first_chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
                    last_chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
                    expected_stage TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    evidence TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(novel_id, thread_key)
                );

                CREATE TABLE IF NOT EXISTS foreshadowing (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                    clue_key TEXT NOT NULL,
                    description TEXT NOT NULL,
                    first_chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
                    allowed_resolution_stage TEXT NOT NULL DEFAULT '',
                    forbidden_before TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'planted',
                    evidence TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(novel_id, clue_key)
                );

                CREATE INDEX IF NOT EXISTS idx_chapters_novel_ordinal
                    ON chapters(novel_id, ordinal);
                CREATE INDEX IF NOT EXISTS idx_outline_novel_ordinal
                    ON outline_chapters(novel_id, ordinal);
                CREATE INDEX IF NOT EXISTS idx_memories_novel_status_kind
                    ON memories(novel_id, status, kind);
                CREATE INDEX IF NOT EXISTS idx_usage_novel
                    ON usage_logs(novel_id);
                CREATE INDEX IF NOT EXISTS idx_character_states_novel
                    ON character_states(novel_id);
                CREATE INDEX IF NOT EXISTS idx_locations_novel
                    ON locations(novel_id);
                CREATE INDEX IF NOT EXISTS idx_open_threads_novel_status
                    ON open_threads(novel_id, status);
                CREATE INDEX IF NOT EXISTS idx_foreshadowing_novel_status
                    ON foreshadowing(novel_id, status);
                """
            )

    def create_novel(
        self,
        title: str,
        *,
        author: str = "",
        genre: str = "",
        style_guide: str = "",
        target_chapter_chars: int = 3000,
        budget_cny: float = 150.0,
    ) -> int:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO novels
                    (title, author, genre, style_guide, target_chapter_chars,
                     budget_cny, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title.strip(),
                    author.strip(),
                    genre.strip(),
                    style_guide.strip(),
                    int(target_chapter_chars),
                    float(budget_cny),
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def list_novels(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM novels ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def get_novel(self, novel_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM novels WHERE id = ?", (novel_id,)).fetchone()
        return dict(row) if row else None

    def update_novel_budget(self, novel_id: int, budget_cny: float) -> None:
        if budget_cny <= 0:
            raise ValueError("预算必须大于0元")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE novels SET budget_cny = ?, updated_at = ? WHERE id = ?",
                (float(budget_cny), utc_now(), novel_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("小说项目不存在")

    def clone_v2_experiment(
        self,
        novel_id: int,
        target_path: str | Path,
        *,
        through_chapter: int,
    ) -> dict[str, Any]:
        """Create an isolated V2 database without mutating the source database."""
        if through_chapter <= 0:
            raise ValueError("through_chapter 必须是正整数")
        if not self.get_novel(novel_id):
            raise ValueError("小说项目不存在")
        target = Path(target_path)
        if target.resolve() == self.path.resolve():
            raise ValueError("V2实验数据库不能覆盖源数据库")
        if target.exists():
            raise FileExistsError(f"目标数据库已经存在：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)

        source_connection = sqlite3.connect(self.path)
        target_connection = sqlite3.connect(target)
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
            source_connection.close()

        experiment = NovelDatabase(target)
        with experiment.connect() as connection:
            connection.execute("DELETE FROM novels WHERE id <> ?", (novel_id,))
            connection.execute("DELETE FROM usage_logs WHERE novel_id = ?", (novel_id,))
            connection.execute("DELETE FROM drafts WHERE novel_id = ?", (novel_id,))
            connection.execute("DELETE FROM memories WHERE novel_id = ?", (novel_id,))
            connection.execute(
                "DELETE FROM chapters WHERE novel_id = ? AND ordinal > ?",
                (novel_id, through_chapter),
            )
            connection.execute(
                "UPDATE outline_chapters SET status = CASE WHEN ordinal <= ? "
                "THEN 'written' ELSE 'planned' END, updated_at = ? WHERE novel_id = ?",
                (through_chapter, utc_now(), novel_id),
            )
            connection.execute(
                "UPDATE novels SET title = title || '（V2实验）', updated_at = ? WHERE id = ?",
                (utc_now(), novel_id),
            )

        source_chapters = len(self.list_chapters(novel_id))
        target_chapters = len(experiment.list_chapters(novel_id))
        state_counts: dict[str, int] = {}
        with experiment.connect() as connection:
            for table in (
                "fixed_settings",
                "character_states",
                "locations",
                "chapter_end_states",
                "open_threads",
                "foreshadowing",
            ):
                state_counts[table] = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE novel_id = ?", (novel_id,)
                    ).fetchone()[0]
                )
        return {
            "source_chapters": source_chapters,
            "target_chapters": target_chapters,
            "outline_chapters": len(experiment.list_outline(novel_id)),
            "memories": len(experiment.list_memories(novel_id)),
            "usage_calls": int(experiment.usage_summary(novel_id)["calls"]),
            "state_counts": state_counts,
            "target_path": str(target.resolve()),
        }

    def replace_chapters(self, novel_id: int, chapters: list[Any]) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("DELETE FROM chapters WHERE novel_id = ?", (novel_id,))
            connection.executemany(
                """
                INSERT INTO chapters
                    (novel_id, ordinal, title, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (novel_id, chapter.ordinal, chapter.title, chapter.content, now, now)
                    for chapter in chapters
                ],
            )
            connection.execute(
                "UPDATE novels SET updated_at = ? WHERE id = ?", (now, novel_id)
            )

    def replace_source_document(
        self, novel_id: int, *, kind: str, title: str, content: str
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_documents
                    (novel_id, kind, title, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(novel_id, kind) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (novel_id, kind, title.strip(), content, now, now),
            )

    def get_source_document(self, novel_id: int, kind: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_documents WHERE novel_id = ? AND kind = ?",
                (novel_id, kind),
            ).fetchone()
        return dict(row) if row else None

    def replace_outline(self, novel_id: int, chapters: list[Any]) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("DELETE FROM outline_chapters WHERE novel_id = ?", (novel_id,))
            connection.executemany(
                """
                INSERT INTO outline_chapters
                    (novel_id, ordinal, title, core_event, raw_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        novel_id,
                        chapter.ordinal,
                        chapter.title,
                        chapter.core_event,
                        chapter.raw_text,
                        now,
                        now,
                    )
                    for chapter in chapters
                ],
            )
            connection.execute(
                "UPDATE novels SET updated_at = ? WHERE id = ?", (now, novel_id)
            )

    def list_chapters(self, novel_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chapters WHERE novel_id = ? ORDER BY ordinal", (novel_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def list_outline(self, novel_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM outline_chapters WHERE novel_id = ? ORDER BY ordinal",
                (novel_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_outline_chapter(self, outline_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM outline_chapters WHERE id = ?", (outline_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_chapter_summary(self, chapter_id: int, summary: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE chapters SET summary = ?, updated_at = ? WHERE id = ?",
                (summary.strip(), utc_now(), chapter_id),
            )

    def add_memory(
        self,
        novel_id: int,
        *,
        kind: str,
        subject: str,
        content: str,
        keywords: str = "",
        source_type: str = "ai_candidate",
        source_chapter_id: int | None = None,
        evidence: str = "",
        confidence: float = 0.5,
        status: str = "candidate",
        pinned: bool = False,
    ) -> int:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memories
                    (novel_id, kind, subject, content, keywords, source_type,
                     source_chapter_id, evidence, confidence, status, pinned,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    kind.strip(),
                    subject.strip(),
                    content.strip(),
                    keywords.strip(),
                    source_type,
                    source_chapter_id,
                    evidence.strip(),
                    max(0.0, min(1.0, float(confidence))),
                    status,
                    int(pinned),
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def list_memories(
        self,
        novel_id: int,
        *,
        statuses: tuple[str, ...] = ("confirmed", "candidate"),
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in statuses)
        query = f"""
            SELECT m.*, c.title AS source_chapter_title, c.ordinal AS source_chapter_ordinal
            FROM memories m
            LEFT JOIN chapters c ON c.id = m.source_chapter_id
            WHERE m.novel_id = ? AND m.status IN ({placeholders})
            ORDER BY m.pinned DESC, m.updated_at DESC
        """
        with self.connect() as connection:
            rows = connection.execute(query, (novel_id, *statuses)).fetchall()
        return [dict(row) for row in rows]

    def update_memory_status(self, memory_id: int, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE memories SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), memory_id),
            )

    def create_draft(
        self,
        novel_id: int,
        *,
        outline_chapter_id: int | None,
        title: str,
        author_instruction: str,
        task_card: dict[str, Any],
        context_text: str,
        context_meta: dict[str, Any],
        content: str,
        continuity_report: dict[str, Any],
    ) -> int:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO drafts
                    (novel_id, outline_chapter_id, title, author_instruction,
                     task_card_json, context_text, context_meta_json, content,
                     continuity_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    outline_chapter_id,
                    title,
                    author_instruction,
                    json.dumps(task_card, ensure_ascii=False),
                    context_text,
                    json.dumps(context_meta, ensure_ascii=False),
                    content,
                    json.dumps(continuity_report, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def get_draft(self, draft_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        return dict(row) if row else None

    def replace_draft(
        self,
        draft_id: int,
        *,
        novel_id: int,
        outline_chapter_id: int | None,
        title: str,
        author_instruction: str,
        task_card: dict[str, Any],
        context_text: str,
        context_meta: dict[str, Any],
        content: str,
        continuity_report: dict[str, Any],
    ) -> None:
        """Replace every generated artifact of an unaccepted draft."""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE drafts
                SET outline_chapter_id = ?, title = ?, author_instruction = ?,
                    task_card_json = ?, context_text = ?, context_meta_json = ?,
                    content = ?, continuity_json = ?, updated_at = ?
                WHERE id = ? AND novel_id = ? AND status = 'draft'
                """,
                (
                    outline_chapter_id,
                    title,
                    author_instruction,
                    json.dumps(task_card, ensure_ascii=False),
                    context_text,
                    json.dumps(context_meta, ensure_ascii=False),
                    content,
                    json.dumps(continuity_report, ensure_ascii=False),
                    utc_now(),
                    draft_id,
                    novel_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("草稿不存在、小说不匹配或已经确认，不能覆盖")

    def list_drafts(self, novel_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM drafts WHERE novel_id = ? ORDER BY created_at DESC",
                (novel_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_draft_content(self, draft_id: int, content: str) -> None:
        if not content.strip():
            raise ValueError("草稿正文不能为空")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE drafts SET content = ?, updated_at = ? WHERE id = ? AND status = 'draft'",
                (content.strip(), utc_now(), draft_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("草稿不存在或已经确认")

    def repair_draft_and_chapter(self, draft_id: int, content: str) -> None:
        """Repair an accepted draft and its matching official chapter atomically."""
        draft = self.get_draft(draft_id)
        if not draft or draft["status"] != "accepted":
            raise ValueError("只能修复已经确认的草稿")
        with self.connect() as connection:
            outline = connection.execute(
                "SELECT ordinal FROM outline_chapters WHERE id = ?",
                (draft["outline_chapter_id"],),
            ).fetchone()
            if not outline:
                raise ValueError("无法确定草稿对应的正式章节")
            now = utc_now()
            cursor = connection.execute(
                "UPDATE chapters SET content = ?, updated_at = ? WHERE novel_id = ? AND ordinal = ?",
                (content.strip(), now, draft["novel_id"], int(outline[0])),
            )
            if cursor.rowcount != 1:
                raise ValueError("找不到草稿对应的正式章节")
            connection.execute(
                "UPDATE drafts SET content = ?, updated_at = ? WHERE id = ?",
                (content.strip(), now, draft_id),
            )

    def accept_draft(self, draft_id: int) -> int:
        draft = self.get_draft(draft_id)
        if not draft:
            raise ValueError("草稿不存在")
        if draft["status"] != "draft":
            raise ValueError("草稿已经确认，不能重复写入正文")
        now = utc_now()
        with self.connect() as connection:
            max_ordinal = connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) FROM chapters WHERE novel_id = ?",
                (draft["novel_id"],),
            ).fetchone()[0]
            cursor = connection.execute(
                """
                INSERT INTO chapters
                    (novel_id, ordinal, title, content, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'confirmed', ?, ?)
                """,
                (
                    draft["novel_id"],
                    int(max_ordinal) + 1,
                    draft["title"],
                    draft["content"],
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE drafts SET status = 'accepted', updated_at = ? WHERE id = ?",
                (now, draft_id),
            )
            if draft["outline_chapter_id"]:
                connection.execute(
                    "UPDATE outline_chapters SET status = 'written', updated_at = ? WHERE id = ?",
                    (now, draft["outline_chapter_id"]),
                )
            return int(cursor.lastrowid)

    def log_usage(
        self,
        *,
        novel_id: int | None,
        draft_id: int | None,
        task_type: str,
        model: str,
        prompt_tokens: int,
        cache_hit_tokens: int,
        cache_miss_tokens: int,
        completion_tokens: int,
        cost_cny: float,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO usage_logs
                    (novel_id, draft_id, task_type, model, prompt_tokens,
                     cache_hit_tokens, cache_miss_tokens, completion_tokens,
                     cost_cny, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    draft_id,
                    task_type,
                    model,
                    prompt_tokens,
                    cache_hit_tokens,
                    cache_miss_tokens,
                    completion_tokens,
                    cost_cny,
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def usage_summary(self, novel_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS calls,
                       COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                       COALESCE(SUM(cache_hit_tokens), 0) AS cache_hit_tokens,
                       COALESCE(SUM(cache_miss_tokens), 0) AS cache_miss_tokens,
                       COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                       COALESCE(SUM(cost_cny), 0) AS cost_cny
                FROM usage_logs WHERE novel_id = ?
                """,
                (novel_id,),
            ).fetchone()
        return dict(row)

    def list_usage(self, novel_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM usage_logs WHERE novel_id = ? ORDER BY created_at DESC",
                (novel_id,),
            ).fetchall()
        return [dict(row) for row in rows]
