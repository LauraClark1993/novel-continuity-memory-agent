import json

from novel_memory_agent.webnovelbench import inspect_dataset, prepare_dataset


def _record(category: str, number: int) -> dict:
    return {
        "novel": f"{category}-{number}",
        "author": f"作者-{category}-{number}",
        "genre": category,
        "chapters": [f"第{100 + i}章 标题\n\n" + (f"正文{number}-{i}。" * 300) for i in range(10)],
        "novel_info": [f"第{i + 1}个连续章梗概" for i in range(10)],
    }


def test_inspect_and_prepare_dataset(tmp_path) -> None:
    records = []
    for category in ("东方玄幻", "都市", "历史", "言情", "科幻"):
        records.append(_record(category, 1))
    source = tmp_path / "data.json"
    source.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    inspected = inspect_dataset(source)
    assert inspected["records"] == 5
    assert inspected["with_10_summaries"] == 5
    output = tmp_path / "prepared"
    manifest = prepare_dataset(source, output, per_category=1, min_chars=100, max_chars=8000)
    assert manifest["selected_books"] == 5
    assert manifest["generated_target_chapters"] == 30
    maps = list(output.rglob("chapter_map.json"))
    assert len(maps) == 5
    chapter_map = json.loads(maps[0].read_text(encoding="utf-8"))
    assert chapter_map["5"]["reference_index"] == 1
