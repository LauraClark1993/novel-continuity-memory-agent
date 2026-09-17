from novel_memory_agent.database import NovelDatabase
from novel_memory_agent.parser import parse_manuscript, parse_outline
from novel_memory_agent.story_state import StoryStateStore


def test_database_project_import_and_memory_status(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说", budget_cny=20)
    database.replace_chapters(
        novel_id,
        parse_manuscript("第一章 开端\n\n林夏把钥匙放进抽屉。"),
    )
    database.replace_outline(
        novel_id,
        parse_outline("第二章 来客\n\n周明来到旅店。"),
    )
    chapters = database.list_chapters(novel_id)
    outline = database.list_outline(novel_id)
    assert len(chapters) == 1
    assert len(outline) == 1

    memory_id = database.add_memory(
        novel_id,
        kind="item",
        subject="黄铜钥匙",
        content="黄铜钥匙位于柜台抽屉",
        source_chapter_id=chapters[0]["id"],
        status="candidate",
    )
    database.update_memory_status(memory_id, "confirmed")
    memories = database.list_memories(novel_id, statuses=("confirmed",))
    assert memories[0]["content"] == "黄铜钥匙位于柜台抽屉"


def test_usage_summary_starts_at_zero(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说")
    summary = database.usage_summary(novel_id)
    assert summary["calls"] == 0
    assert summary["cost_cny"] == 0


def test_novel_budget_can_be_updated(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说")
    database.update_novel_budget(novel_id, 300)
    assert database.get_novel(novel_id)["budget_cny"] == 300


def test_accepted_draft_cannot_be_inserted_twice(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说")
    draft_id = database.create_draft(
        novel_id,
        outline_chapter_id=None,
        title="第一章",
        author_instruction="",
        task_card={},
        context_text="",
        context_meta={},
        content="正文",
        continuity_report={},
    )
    database.accept_draft(draft_id)
    try:
        database.accept_draft(draft_id)
    except ValueError as error:
        assert "不能重复" in str(error)
    else:
        raise AssertionError("重复确认应当失败")


def test_v2_story_state_can_be_imported_and_updated(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说")
    database.replace_chapters(novel_id, parse_manuscript("第一章 开端\n\n沈知绾回到侯府。"))
    chapter_id = database.list_chapters(novel_id)[0]["id"]
    store = StoryStateStore(database)

    counts = store.import_bundle(
        novel_id,
        {
            "fixed_settings": [
                {"category": "place", "key": "库房名称", "value": "库房"}
            ],
            "characters": [
                {
                    "name": "沈知绾",
                    "location": "侯府",
                    "current_goal": "查清账目",
                    "source_chapter_id": chapter_id,
                }
            ],
            "locations": [
                {"name": "库房", "direction": "东边", "forbidden_aliases": ["东院"]}
            ],
            "chapter_end_states": [
                {"chapter_id": chapter_id, "location": "侯府", "last_action": "查看账册"}
            ],
            "open_threads": [
                {"key": "账目异常", "description": "东库账目对不上", "importance": 5}
            ],
            "foreshadowing": [
                {"key": "旧账册", "description": "旧账册暗示府内有人做手脚"}
            ],
        },
    )
    assert counts == {
        "fixed_settings": 1,
        "characters": 1,
        "locations": 1,
        "chapter_end_states": 1,
        "open_threads": 1,
        "foreshadowing": 1,
    }

    store.import_bundle(
        novel_id,
        {"characters": [{"name": "沈知绾", "location": "库房", "emotion": "警觉"}]},
    )
    state = store.export_bundle(novel_id)
    assert len(state["characters"]) == 1
    assert state["characters"][0]["state"]["location"] == "库房"
    assert state["locations"][0]["forbidden_aliases"] == ["东院"]
    assert state["fixed_settings"][0]["setting_value"] == "库房"


def test_v2_story_state_rejects_unknown_section(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说")
    store = StoryStateStore(database)
    try:
        store.import_bundle(novel_id, {"unknown": []})
    except ValueError as error:
        assert "未知状态分区" in str(error)
    else:
        raise AssertionError("未知状态分区应当失败")


def test_clone_v2_experiment_is_isolated_and_keeps_state(tmp_path) -> None:
    source_path = tmp_path / "source.db"
    database = NovelDatabase(source_path)
    novel_id = database.create_novel("测试小说")
    database.replace_chapters(
        novel_id,
        parse_manuscript(
            "第一章 开端\n\n一。\n\n第二章 发展\n\n二。\n\n第三章 未来\n\n三。"
        ),
    )
    database.replace_outline(
        novel_id,
        parse_outline(
            "第一章 开端\n\n一。\n\n第二章 发展\n\n二。\n\n第三章 未来\n\n三。"
        ),
    )
    StoryStateStore(database).import_bundle(
        novel_id,
        {"locations": [{"name": "库房", "direction": "东边"}]},
    )
    database.add_memory(
        novel_id,
        kind="event",
        subject="旧记忆",
        content="V1旧记忆",
        status="confirmed",
    )

    target_path = tmp_path / "v2.db"
    result = database.clone_v2_experiment(novel_id, target_path, through_chapter=2)
    experiment = NovelDatabase(target_path)

    assert len(database.list_chapters(novel_id)) == 3
    assert len(experiment.list_chapters(novel_id)) == 2
    assert experiment.list_memories(novel_id) == []
    assert StoryStateStore(experiment).export_bundle(novel_id)["locations"][0][
        "canonical_name"
    ] == "库房"
    assert result["target_chapters"] == 2
    assert experiment.list_outline(novel_id)[2]["status"] == "planned"


def test_location_can_be_renamed_and_old_name_forbidden(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说")
    store = StoryStateStore(database)
    store.import_bundle(
        novel_id,
        {
            "locations": [{"name": "东院", "owner": "沈砚辞", "direction": "侯府东侧"}],
            "characters": [{"name": "沈砚辞", "location": "东院"}],
        },
    )
    store.rename_location(novel_id, "东院", "凌霄院")
    state = store.export_bundle(novel_id)
    assert state["locations"][0]["canonical_name"] == "凌霄院"
    assert state["locations"][0]["forbidden_aliases"] == ["东院"]
    assert state["fixed_settings"][0]["setting_value"] == "凌霄院"
    assert state["characters"][0]["state"]["location"] == "凌霄院"
