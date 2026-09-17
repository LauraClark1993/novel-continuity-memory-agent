from __future__ import annotations

import json
from typing import Any

from .database import NovelDatabase, utc_now


SECTIONS = (
    "fixed_settings",
    "characters",
    "locations",
    "chapter_end_states",
    "open_threads",
    "foreshadowing",
)


def empty_story_state() -> dict[str, list[dict[str, Any]]]:
    return {section: [] for section in SECTIONS}


def _required(item: dict[str, Any], key: str) -> str:
    value = str(item.get(key, "")).strip()
    if not value:
        raise ValueError(f"状态字段 {key} 不能为空")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _replace_exact(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, list):
        return [_replace_exact(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_exact(item, old, new) for key, item in value.items()}
    return value


class StoryStateStore:
    def __init__(self, database: NovelDatabase) -> None:
        self.database = database

    def import_bundle(self, novel_id: int, bundle: dict[str, Any]) -> dict[str, int]:
        if not self.database.get_novel(novel_id):
            raise ValueError("小说不存在")
        unknown = set(bundle) - set(SECTIONS)
        if unknown:
            raise ValueError(f"未知状态分区：{', '.join(sorted(unknown))}")
        chapter_ids = {int(row["id"]) for row in self.database.list_chapters(novel_id)}
        chapter_fields = {
            "fixed_settings": ("source_chapter_id",),
            "characters": ("source_chapter_id",),
            "locations": ("source_chapter_id",),
            "chapter_end_states": ("chapter_id",),
            "open_threads": ("first_chapter_id", "last_chapter_id"),
            "foreshadowing": ("first_chapter_id",),
        }
        for section, fields in chapter_fields.items():
            for item in bundle.get(section, []):
                for field in fields:
                    value = item.get(field)
                    if value is not None and int(value) not in chapter_ids:
                        raise ValueError(f"{section}.{field}={value} 不属于当前小说")
        counts = {section: 0 for section in SECTIONS}
        now = utc_now()
        with self.database.connect() as connection:
            for item in bundle.get("fixed_settings", []):
                connection.execute(
                    """
                    INSERT INTO fixed_settings
                        (novel_id, category, setting_key, setting_value, evidence,
                         source_chapter_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(novel_id, category, setting_key) DO UPDATE SET
                        setting_value = excluded.setting_value,
                        evidence = excluded.evidence,
                        source_chapter_id = excluded.source_chapter_id,
                        version = fixed_settings.version + 1,
                        updated_at = excluded.updated_at
                    """,
                    (
                        novel_id,
                        str(item.get("category", "general")).strip(),
                        _required(item, "key"),
                        _required(item, "value"),
                        str(item.get("evidence", "")).strip(),
                        item.get("source_chapter_id"),
                        now,
                        now,
                    ),
                )
                counts["fixed_settings"] += 1

            for item in bundle.get("characters", []):
                name = _required(item, "name")
                state = {
                    key: value
                    for key, value in item.items()
                    if key not in {"name", "evidence", "source_chapter_id"}
                }
                connection.execute(
                    """
                    INSERT INTO character_states
                        (novel_id, character_name, state_json, evidence,
                         source_chapter_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(novel_id, character_name) DO UPDATE SET
                        state_json = excluded.state_json,
                        evidence = excluded.evidence,
                        source_chapter_id = excluded.source_chapter_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        novel_id,
                        name,
                        _json(state),
                        str(item.get("evidence", "")).strip(),
                        item.get("source_chapter_id"),
                        now,
                        now,
                    ),
                )
                counts["characters"] += 1

            for item in bundle.get("locations", []):
                connection.execute(
                    """
                    INSERT INTO locations
                        (novel_id, canonical_name, aliases_json, forbidden_aliases_json,
                         location_type, owner, direction, adjacent_json, purpose, evidence,
                         source_chapter_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(novel_id, canonical_name) DO UPDATE SET
                        aliases_json = excluded.aliases_json,
                        forbidden_aliases_json = excluded.forbidden_aliases_json,
                        location_type = excluded.location_type, owner = excluded.owner,
                        direction = excluded.direction, adjacent_json = excluded.adjacent_json,
                        purpose = excluded.purpose, evidence = excluded.evidence,
                        source_chapter_id = excluded.source_chapter_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        novel_id,
                        _required(item, "name"),
                        _json(item.get("aliases", [])),
                        _json(item.get("forbidden_aliases", [])),
                        str(item.get("type", "")).strip(),
                        str(item.get("owner", "")).strip(),
                        str(item.get("direction", "")).strip(),
                        _json(item.get("adjacent", [])),
                        str(item.get("purpose", "")).strip(),
                        str(item.get("evidence", "")).strip(),
                        item.get("source_chapter_id"),
                        now,
                        now,
                    ),
                )
                counts["locations"] += 1

            for item in bundle.get("chapter_end_states", []):
                chapter_id = int(item.get("chapter_id", 0))
                if chapter_id <= 0:
                    raise ValueError("chapter_end_states[].chapter_id 必须是正整数")
                state = {
                    key: value
                    for key, value in item.items()
                    if key not in {"chapter_id", "evidence"}
                }
                connection.execute(
                    """
                    INSERT INTO chapter_end_states
                        (novel_id, chapter_id, state_json, evidence, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(novel_id, chapter_id) DO UPDATE SET
                        state_json = excluded.state_json, evidence = excluded.evidence,
                        updated_at = excluded.updated_at
                    """,
                    (
                        novel_id,
                        chapter_id,
                        _json(state),
                        str(item.get("evidence", "")).strip(),
                        now,
                        now,
                    ),
                )
                counts["chapter_end_states"] += 1

            for item in bundle.get("open_threads", []):
                connection.execute(
                    """
                    INSERT INTO open_threads
                        (novel_id, thread_key, thread_type, description, importance,
                         first_chapter_id, last_chapter_id, expected_stage, status,
                         evidence, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(novel_id, thread_key) DO UPDATE SET
                        thread_type = excluded.thread_type, description = excluded.description,
                        importance = excluded.importance,
                        first_chapter_id = excluded.first_chapter_id,
                        last_chapter_id = excluded.last_chapter_id,
                        expected_stage = excluded.expected_stage, status = excluded.status,
                        evidence = excluded.evidence, updated_at = excluded.updated_at
                    """,
                    (
                        novel_id,
                        _required(item, "key"),
                        str(item.get("type", "conflict")).strip(),
                        _required(item, "description"),
                        max(1, min(5, int(item.get("importance", 3)))),
                        item.get("first_chapter_id"),
                        item.get("last_chapter_id"),
                        str(item.get("expected_stage", "")).strip(),
                        str(item.get("status", "open")).strip(),
                        str(item.get("evidence", "")).strip(),
                        now,
                        now,
                    ),
                )
                counts["open_threads"] += 1

            for item in bundle.get("foreshadowing", []):
                connection.execute(
                    """
                    INSERT INTO foreshadowing
                        (novel_id, clue_key, description, first_chapter_id,
                         allowed_resolution_stage, forbidden_before, status, evidence,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(novel_id, clue_key) DO UPDATE SET
                        description = excluded.description,
                        first_chapter_id = excluded.first_chapter_id,
                        allowed_resolution_stage = excluded.allowed_resolution_stage,
                        forbidden_before = excluded.forbidden_before,
                        status = excluded.status, evidence = excluded.evidence,
                        updated_at = excluded.updated_at
                    """,
                    (
                        novel_id,
                        _required(item, "key"),
                        _required(item, "description"),
                        item.get("first_chapter_id"),
                        str(item.get("allowed_resolution_stage", "")).strip(),
                        str(item.get("forbidden_before", "")).strip(),
                        str(item.get("status", "planted")).strip(),
                        str(item.get("evidence", "")).strip(),
                        now,
                        now,
                    ),
                )
                counts["foreshadowing"] += 1
        return counts

    def export_bundle(self, novel_id: int) -> dict[str, list[dict[str, Any]]]:
        queries = {
            "fixed_settings": "SELECT * FROM fixed_settings WHERE novel_id = ? ORDER BY category, setting_key",
            "characters": "SELECT * FROM character_states WHERE novel_id = ? ORDER BY character_name",
            "locations": "SELECT * FROM locations WHERE novel_id = ? ORDER BY canonical_name",
            "chapter_end_states": "SELECT * FROM chapter_end_states WHERE novel_id = ? ORDER BY chapter_id",
            "open_threads": "SELECT * FROM open_threads WHERE novel_id = ? ORDER BY importance DESC, thread_key",
            "foreshadowing": "SELECT * FROM foreshadowing WHERE novel_id = ? ORDER BY clue_key",
        }
        result: dict[str, list[dict[str, Any]]] = {}
        with self.database.connect() as connection:
            for section, query in queries.items():
                rows = [dict(row) for row in connection.execute(query, (novel_id,)).fetchall()]
                for row in rows:
                    for key in tuple(row):
                        if key.endswith("_json"):
                            row[key[:-5]] = json.loads(row.pop(key) or "null")
                result[section] = rows
        return result

    def rename_location(
        self, novel_id: int, old_name: str, new_name: str, *, forbid_old: bool = True
    ) -> None:
        old_name = old_name.strip()
        new_name = new_name.strip()
        if not old_name or not new_name:
            raise ValueError("旧名称和新名称不能为空")
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM locations WHERE novel_id = ? AND canonical_name = ?",
                (novel_id, old_name),
            ).fetchone()
            if not row:
                raise ValueError(f"找不到场景：{old_name}")
            collision = connection.execute(
                "SELECT 1 FROM locations WHERE novel_id = ? AND canonical_name = ?",
                (novel_id, new_name),
            ).fetchone()
            if collision:
                raise ValueError(f"新场景名称已经存在：{new_name}")
            aliases = json.loads(row["aliases_json"] or "[]")
            forbidden = json.loads(row["forbidden_aliases_json"] or "[]")
            target = forbidden if forbid_old else aliases
            if old_name not in target:
                target.append(old_name)
            connection.execute(
                """
                UPDATE locations
                SET canonical_name = ?, aliases_json = ?, forbidden_aliases_json = ?,
                    updated_at = ?
                WHERE novel_id = ? AND canonical_name = ?
                """,
                (new_name, _json(aliases), _json(forbidden), utc_now(), novel_id, old_name),
            )
            connection.execute(
                """
                INSERT INTO fixed_settings
                    (novel_id, category, setting_key, setting_value, evidence,
                     created_at, updated_at)
                VALUES (?, 'naming', ?, ?, '作者确认的V2场景命名规范', ?, ?)
                ON CONFLICT(novel_id, category, setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    evidence = excluded.evidence,
                    version = fixed_settings.version + 1,
                    updated_at = excluded.updated_at
                """,
                (novel_id, f"场景正式名称:{old_name}", new_name, utc_now(), utc_now()),
            )
        self.replace_location_references(novel_id, old_name, new_name)

    def replace_location_references(self, novel_id: int, old_name: str, new_name: str) -> int:
        """Replace exact old location values inside structured current/end state JSON."""
        changed = 0
        with self.database.connect() as connection:
            for table in ("character_states", "chapter_end_states"):
                rows = connection.execute(
                    f"SELECT id, state_json FROM {table} WHERE novel_id = ?", (novel_id,)
                ).fetchall()
                for row in rows:
                    current = json.loads(row["state_json"] or "{}")
                    updated = _replace_exact(current, old_name, new_name)
                    if updated != current:
                        connection.execute(
                            f"UPDATE {table} SET state_json = ?, updated_at = ? WHERE id = ?",
                            (_json(updated), utc_now(), row["id"]),
                        )
                        changed += 1
            cursor = connection.execute(
                """
                UPDATE fixed_settings SET setting_value = ?, version = version + 1,
                    updated_at = ?
                WHERE novel_id = ? AND setting_value = ?
                """,
                (new_name, utc_now(), novel_id, old_name),
            )
            changed += cursor.rowcount
        return changed
