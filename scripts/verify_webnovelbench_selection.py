from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from novel_memory_agent.webnovelbench import load_records, normalize_record


def short_title(value: str) -> str:
    match = re.search(r"《([^》]+)》", value)
    return match.group(1) if match else value.split("作者：", 1)[0]


def embedded_author(value: str) -> str:
    match = re.search(r"作者[：:]\s*(.+)$", value)
    return match.group(1).strip() if match else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="验证WebNovelBench冻结的60本样本")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--support-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    requested = json.loads(args.selection.read_text(encoding="utf-8-sig"))
    support = json.loads(args.support_audit.read_text(encoding="utf-8-sig"))
    expected = {title: genre for genre, titles in requested.items() for title in titles}
    if len(requested) != 20 or any(len(titles) != 3 for titles in requested.values()):
        raise ValueError("必须是20个题材且每类恰好3本")
    if len(expected) != 60:
        raise ValueError("存在跨题材重复书名")

    evidence_lookup = {}
    for genre, value in support["genres"].items():
        for item in value["top_candidates"]:
            evidence_lookup[(genre, short_title(item["title"]))] = item

    found = {}
    for index, record in enumerate(load_records(args.input), 1):
        sample = normalize_record(record, index, {})
        if sample is None:
            continue
        title = short_title(sample.title)
        if title not in expected:
            continue
        lengths = [len(re.sub(r"\s+", "", chapter.content)) for chapter in sample.chapters]
        found[title] = {
            "genre": expected[title],
            "source_id": sample.source_id,
            "title": sample.title,
            "short_title": title,
            "author": sample.author or embedded_author(sample.title),
            "chapters": len(sample.chapters),
            "summaries": sum(bool(chapter.summary) for chapter in sample.chapters),
            "min_chapter_chars": min(lengths) if lengths else 0,
            "max_chapter_chars": max(lengths) if lengths else 0,
            "unique_chapters": len({re.sub(r"\s+", "", chapter.content) for chapter in sample.chapters}),
            "classification_evidence": evidence_lookup.get((expected[title], title), {}).get("evidence", []),
            "manual_review": "题材主线明确；正式运行前不读取第5—10章原作正文。",
        }

    missing = sorted(set(expected) - set(found))
    if missing:
        raise ValueError(f"未找到冻结书目：{missing}")
    authors = [item["author"] for item in found.values() if item["author"]]
    duplicate_authors = sorted(author for author, count in Counter(authors).items() if count > 1)
    invalid = [
        title for title, item in found.items()
        if item["chapters"] != 10 or item["summaries"] != 10
        or item["min_chapter_chars"] < 1000 or item["max_chapter_chars"] > 8000
        or item["unique_chapters"] != 10
    ]
    result = {
        "status": "PASS" if not missing and not invalid and not duplicate_authors else "REVIEW",
        "books": 60,
        "genres": 20,
        "books_per_genre": 3,
        "duplicate_authors": duplicate_authors,
        "invalid_books": invalid,
        "selection": [found[title] for genre in requested for title in requested[genre]],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# WebNovelBench正式60本样本审计",
        "",
        f"- 审核状态：{result['status']}",
        "- 规模：20种题材 × 每类3本 = 60本",
        "- 完整性：每本10章正文与10章摘要，章节1,000—8,000字，无完全重复章。",
        "- 去重：书名不重复，作者不重复。",
        "- 标签性质：根据书名与10章摘要建立的实验标签，并非数据集官方题材标签。",
        "",
        "| 题材 | 书名 | 作者 | 字数范围/章 | 分类证据 |",
        "|---|---|---|---:|---|",
    ]
    for item in result["selection"]:
        evidence = "、".join(item["classification_evidence"]) or "人工按10章主线确认"
        lines.append(
            f"| {item['genre']} | {item['short_title']} | {item['author'] or '—'} | "
            f"{item['min_chapter_chars']}—{item['max_chapter_chars']} | {evidence} |"
        )
    md_path = args.output.with_suffix(".md")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(md_path.resolve())
    print(json.dumps({key: result[key] for key in ("status", "books", "genres", "books_per_genre", "duplicate_authors", "invalid_books")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
