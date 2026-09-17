import json

from novel_memory_agent.agent import NovelAgent
from novel_memory_agent.config import Settings
from novel_memory_agent.database import NovelDatabase
from novel_memory_agent.models import LLMResponse, LLMUsage
from novel_memory_agent.parser import parse_manuscript, parse_outline


class FakeClient:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = iter(outputs)

    def complete(self, messages, **kwargs) -> LLMResponse:
        del messages, kwargs
        return LLMResponse(
            content=next(self.outputs),
            model="deepseek-v4-flash",
            usage=LLMUsage(
                prompt_tokens=1000,
                cache_miss_tokens=1000,
                completion_tokens=500,
            ),
        )


class ConnectionFakeClient(FakeClient):
    def test_connection(self, **kwargs) -> LLMResponse:
        del kwargs
        return LLMResponse(
            content="连接成功",
            model="deepseek-v4-flash",
            usage=LLMUsage(prompt_tokens=10, cache_miss_tokens=10, completion_tokens=3),
        )


def test_full_generation_flow_without_network(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说", style_guide="第三人称限知视角")
    settings = Settings(database_path=tmp_path / "test.db")
    task_card = {
        "title": "第二章 来客",
        "core_event": "周明来到旅店",
        "story_start": "林夏正在关门",
        "must_happen": ["周明出现"],
        "must_not_happen": ["揭示真实身份"],
        "characters": [{"name": "林夏", "state": "警惕", "goal": "确认来客身份"}],
        "continuity_constraints": ["钥匙仍在抽屉"],
        "relevant_foreshadowing": [],
        "scene_plan": ["来客敲门", "双方试探"],
        "end_state": "林夏产生怀疑",
        "assumptions": [],
        "clarification_required": [],
    }
    continuity = {
        "passed": True,
        "high_risk": [],
        "medium_risk": [],
        "low_risk": [],
        "outline_completion": [{"requirement": "周明出现", "status": "done"}],
        "summary": "未发现明确冲突",
    }
    memory_update = {
        "summary": "周明在雨夜来到旅店。",
        "memories": [
            {
                "kind": "event",
                "subject": "周明到访",
                "content": "周明在雨夜来到旅店",
                "keywords": ["周明", "旅店"],
                "evidence": "门外站着周明。",
                "confidence": 0.95,
            }
        ],
    }
    generated_text = "门外站着周明。" * 300
    client = FakeClient(
        [json.dumps(task_card, ensure_ascii=False), generated_text, json.dumps(continuity), json.dumps(memory_update, ensure_ascii=False)]
    )
    agent = NovelAgent(database, settings, client=client)
    agent.import_manuscript(novel_id, "第一章 钥匙\n\n林夏把钥匙放进抽屉。")
    agent.import_outline(novel_id, "第二章 来客\n\n周明在雨夜来到旅店。")
    outline_id = database.list_outline(novel_id)[0]["id"]

    result = agent.generate_chapter(novel_id, outline_id)
    assert result.task_card["title"] == "第二章 来客"
    assert result.continuity_report["passed"] is True
    assert result.draft == f"第二章 来客\n\n{generated_text}"
    assert database.usage_summary(novel_id)["calls"] == 3

    accepted = agent.accept_and_extract_memories(result.draft_id)
    assert accepted["candidate_memories"] == 1
    assert len(database.list_chapters(novel_id)) == 2
    candidates = database.list_memories(novel_id, statuses=("candidate",))
    assert candidates[0]["subject"] == "周明到访"


def test_chapter_heading_is_added_or_normalized() -> None:
    assert NovelAgent._ensure_chapter_heading("正文开始。", "第五章 东库失钥") == (
        "第五章 东库失钥\n\n正文开始。"
    )
    assert NovelAgent._ensure_chapter_heading("# 第五章 旧标题\n正文。", "第五章 东库失钥") == (
        "第五章 东库失钥\n\n正文。"
    )


def test_accept_v2_draft_updates_state_without_v1_memory(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说")
    settings = Settings(database_path=tmp_path / "test.db")
    database.replace_chapters(novel_id, parse_manuscript("第一章 开端\n\n林夏关门。"))
    database.replace_outline(
        novel_id,
        parse_outline("第一章 开端\n\n林夏关门。\n\n第二章 来客\n\n周明敲门。"),
    )
    outline = database.list_outline(novel_id)[1]
    draft_id = database.create_draft(
        novel_id,
        outline_chapter_id=outline["id"],
        title=outline["title"],
        author_instruction="",
        task_card={},
        context_text="历史上下文",
        context_meta={},
        content="第二章 来客\n\n周明敲响了门。",
        continuity_report={"passed": True},
    )
    update = {
        "fixed_settings": [],
        "characters": [{"name": "林夏", "location": "旅店", "emotion": "警惕"}],
        "locations": [],
        "chapter_end_states": [{"chapter_id": 0, "location": "旅店", "last_action": "开门"}],
        "open_threads": [{"key": "来客身份", "description": "周明身份不明"}],
        "foreshadowing": [],
    }
    agent = NovelAgent(
        database,
        settings,
        client=FakeClient([json.dumps(update, ensure_ascii=False)]),
    )
    result = agent.accept_v2_draft(draft_id)
    assert result["ordinal"] == 2
    assert len(database.list_chapters(novel_id)) == 2
    assert database.list_memories(novel_id) == []
    state = agent.story_states.export_bundle(novel_id)
    assert state["chapter_end_states"][-1]["state"]["location"] == "旅店"


def test_initialize_story_state_without_network(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说")
    settings = Settings(database_path=tmp_path / "test.db")
    agent = NovelAgent(database, settings, client=FakeClient([]))
    agent.import_manuscript(novel_id, "第一章 回府\n\n沈知绾回到侯府库房。")
    agent.import_outline(novel_id, "第二章 查账\n\n沈知绾准备核查旧账。")
    chapter_id = database.list_chapters(novel_id)[0]["id"]
    state = {
        "fixed_settings": [
            {"category": "place", "key": "库房名称", "value": "库房"}
        ],
        "characters": [
            {"name": "沈知绾", "location": "库房", "source_chapter_id": chapter_id}
        ],
        "locations": [{"name": "库房", "direction": "东边"}],
        "chapter_end_states": [
            {"chapter_id": chapter_id, "location": "库房", "last_action": "查看账册"},
            {"chapter_id": 999, "location": "未来地点", "last_action": "未来事件"},
        ],
        "open_threads": [{"key": "旧账", "description": "旧账仍未核清"}],
        "foreshadowing": [
            {
                "key": "账册",
                "description": "账册存在异常",
                "first_chapter_id": 12,
                "allowed_resolution_stage": "第十二章以后",
            }
        ],
    }
    agent.client = FakeClient([json.dumps(state, ensure_ascii=False)])

    result = agent.initialize_story_state(novel_id, through_chapter=1)

    assert result["chapter_count"] == 1
    assert result["counts"]["characters"] == 1
    assert database.usage_summary(novel_id)["calls"] == 1
    saved_state = agent.story_states.export_bundle(novel_id)
    assert saved_state["foreshadowing"][0]["first_chapter_id"] is None
    assert saved_state["foreshadowing"][0]["allowed_resolution_stage"] == "第十二章以后"
    assert len(saved_state["chapter_end_states"]) == 1
    assert saved_state["chapter_end_states"][0]["chapter_id"] == chapter_id
    context = agent.preview_context(novel_id, database.list_outline(novel_id)[0]["id"])
    assert "V2人物当前状态" in context.text
    assert "V2上一章精确末态" in context.text
    assert "旧账仍未核清" in context.text
    assert "V2三章滚动剧情窗" in context.text
    assert "跨章原则" in context.text
