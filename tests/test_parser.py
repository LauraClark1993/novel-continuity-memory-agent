from novel_memory_agent.parser import parse_manuscript, parse_outline


def test_parse_manuscript_with_chinese_headings() -> None:
    text = """第一章 雨夜

林夏关上了门。

第二章 脚印

她发现一串脚印。
"""
    chapters = parse_manuscript(text)
    assert len(chapters) == 2
    assert chapters[0].title == "第一章 雨夜"
    assert "关上了门" in chapters[0].content
    assert chapters[1].ordinal == 2


def test_parse_manuscript_falls_back_to_chunks() -> None:
    text = "甲" * 9000
    chapters = parse_manuscript(text, fallback_chunk_chars=4000)
    assert len(chapters) == 3
    assert chapters[0].title == "片段 1"


def test_parse_outline_extracts_core_event() -> None:
    text = """第一章 开端
林夏发现钥匙。

第二章 来客
核心事件：周明在雨夜来到旅店。
"""
    outline = parse_outline(text)
    assert len(outline) == 2
    assert outline[0].core_event == "林夏发现钥匙。"
    assert outline[1].core_event == "周明在雨夜来到旅店。"


def test_markdown_heading_is_recognized_without_fake_preface() -> None:
    text = """# 小说标题

## 第一章 开端

林夏发现钥匙。
"""
    chapters = parse_manuscript(text)
    assert len(chapters) == 1
    assert chapters[0].title == "第一章 开端"


def test_bold_markdown_outline_headings() -> None:
    text = """**十二、章节规划**

**第一章 灯下旧账**

沈知绾深夜核对租账。

**第二章 曲水春宴**

王承裕借宴席试探沈家。
"""
    outline = parse_outline(text)
    assert len(outline) == 2
    assert outline[0].title == "第一章 灯下旧账"
    assert outline[1].core_event == "王承裕借宴席试探沈家。"
