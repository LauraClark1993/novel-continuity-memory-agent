from novel_memory_agent.database import NovelDatabase
from novel_memory_agent.parser import parse_manuscript
from novel_memory_agent.retrieval import ContextRetriever


def test_retriever_prioritizes_confirmed_relevant_memory(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说", style_guide="第三人称限知视角")
    database.replace_chapters(
        novel_id,
        parse_manuscript(
            """第一章 钥匙

林夏把黄铜钥匙藏在柜台抽屉。

第二章 脚印

林夏在后门发现陌生脚印。
"""
        ),
    )
    chapters = database.list_chapters(novel_id)
    database.add_memory(
        novel_id,
        kind="item",
        subject="黄铜钥匙",
        content="钥匙位于柜台最下层抽屉",
        keywords="林夏,父亲,钥匙",
        source_chapter_id=chapters[0]["id"],
        status="confirmed",
    )
    database.add_memory(
        novel_id,
        kind="event",
        subject="无关候选",
        content="这条信息不应参与检索",
        status="candidate",
    )
    bundle = ContextRetriever(database).build_context(
        novel_id, "林夏发现父亲的黄铜钥匙", max_tokens=3000
    )
    assert "钥匙位于柜台最下层抽屉" in bundle.text
    assert "这条信息不应参与检索" not in bundle.text
    assert "第三人称限知视角" in bundle.text


def test_retriever_excludes_future_chapters_and_memories(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "test.db")
    novel_id = database.create_novel("测试小说")
    database.replace_chapters(
        novel_id,
        parse_manuscript(
            "第一章 开端\n\n第一章事实。\n\n"
            "第二章 发展\n\n第二章事实。\n\n"
            "第三章 未来\n\n第三章未来事实。"
        ),
    )
    chapters = database.list_chapters(novel_id)
    database.add_memory(
        novel_id,
        kind="event",
        subject="未来事件",
        content="第三章未来记忆",
        source_chapter_id=chapters[2]["id"],
        status="confirmed",
    )
    bundle = ContextRetriever(database).build_context(
        novel_id, "未来事件", before_ordinal=3
    )
    assert "第三章未来事实" not in bundle.text
    assert "第三章未来记忆" not in bundle.text
    assert chapters[2]["id"] not in bundle.source_chapter_ids
