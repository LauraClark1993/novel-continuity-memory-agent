from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CATEGORIES = ("东方玄幻", "都市现实", "历史古代", "言情", "悬疑科幻")
GENRE_TERMS = {
    "悬疑科幻": ("悬疑", "推理", "刑侦", "犯罪", "破案", "侦探", "诡异", "灵异", "科幻", "末世", "废土", "未来", "星际", "机甲"),
    "历史古代": ("历史", "古代", "架空", "宫廷", "权谋", "朝堂", "皇帝", "王爷", "侯府", "将军", "科举", "民国"),
    "东方玄幻": ("东方玄幻", "玄幻", "仙侠", "修真", "武侠", "武道", "宗门", "仙帝", "妖兽", "灵气", "丹帝", "神王", "天尊", "符道"),
    "都市现实": ("都市", "现实", "职场", "商战", "创业", "工业", "金融", "娱乐圈", "校园", "公司", "集团"),
    "言情": ("言情", "爱情", "婚恋", "甜宠", "王妃", "嫡女", "庶女", "娇妻", "弃妇", "前妻", "新娘", "皇后", "宠妃", "娘子"),
}
TEXT_KEYS = ("content", "text", "chapter", "chapter_content", "正文")
TITLE_KEYS = ("title", "chapter_title", "name", "章节名")
SUMMARY_KEYS = ("novel_info", "summaries", "summary", "chapter_summaries", "梗概")
CHAPTER_KEYS = ("chapters", "chapter", "texts", "contents", "novel_content", "正文")
NAME_KEYS = ("novel", "novel_name", "title", "name", "书名")
AUTHOR_KEYS = ("author", "author_name", "作者")
GENRE_KEYS = ("genre", "category", "type", "tags", "题材", "分类")


@dataclass(slots=True)
class Chapter:
    position: int
    source_label: str
    title: str
    content: str
    summary: str


@dataclass(slots=True)
class NovelSample:
    source_id: str
    title: str
    author: str
    raw_genre: str
    category: str
    chapters: list[Chapter]


def _first(record: dict[str, Any], keys: Iterable[str], default: Any = "") -> Any:
    for key in keys:
        if key in record and record[key] not in (None, "", []):
            return record[key]
    return default


def _clean(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("data", "novels", "items", "records"):
        if isinstance(value.get(key), list):
            return [item for item in value[key] if isinstance(item, dict)]
    result = []
    for key, item in value.items():
        if isinstance(item, dict):
            copied = dict(item)
            copied.setdefault("novel", key)
            result.append(copied)
        elif isinstance(item, list):
            result.append({"novel": key, "chapters": item})
    return result


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        records = []
        for file in sorted(path.rglob("*.json")):
            records.extend(load_records(file))
        return records
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return _records(value)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def _chapter(value: Any, position: int, summary: str) -> Chapter | None:
    if isinstance(value, str):
        content = _clean(value)
        first_line = content.splitlines()[0] if content else ""
        title = first_line if re.match(r"^第.+[章节回篇]", first_line) else f"实验第{position}章"
    elif isinstance(value, dict):
        content = _clean(_first(value, TEXT_KEYS))
        title = _clean(_first(value, TITLE_KEYS, f"实验第{position}章"))
    else:
        return None
    if not content:
        return None
    match = re.search(r"第\s*([0-9]+)\s*[章节回篇]", title + "\n" + content[:100])
    source_label = match.group(1) if match else title
    return Chapter(position, source_label, title, content, _clean(summary))


def map_genre(raw: str, title: str, overrides: dict[str, str], evidence: str = "") -> str:
    if title in overrides:
        category = overrides[title]
        return category if category in CATEGORIES else ""
    # WebNovelBench当前发布文件没有题材字段。泛化实验只接受书名中的
    # 高置信度标签；不能用正文里偶然出现的“未来”“爱人”等词推断整书题材。
    # 同时截掉“作者：”部分，避免作者笔名触发错误分类。
    title_match = re.search(r"《([^》]+)》", title)
    work_title = title_match.group(1) if title_match else title.split("作者：", 1)[0]
    primary = f"{raw}\n{work_title}".lower()
    scores: dict[str, int] = {}
    for category, terms in GENRE_TERMS.items():
        scores[category] = sum(
            primary.count(term.lower()) * max(2, len(term))
            for term in terms
        )
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else ""


def normalize_record(record: dict[str, Any], index: int, overrides: dict[str, str]) -> NovelSample | None:
    title = _clean(_first(record, NAME_KEYS, f"novel_{index:04d}"))
    author = _clean(_first(record, AUTHOR_KEYS))
    raw_genre_value = _first(record, GENRE_KEYS)
    raw_genre = "、".join(map(str, raw_genre_value)) if isinstance(raw_genre_value, list) else _clean(raw_genre_value)
    chapter_values = _as_list(_first(record, CHAPTER_KEYS))
    summary_values = _as_list(_first(record, SUMMARY_KEYS))
    evidence_parts = [str(value) for value in summary_values[:10]]
    evidence_parts.extend(str(value)[:1500] for value in chapter_values[:10])
    evidence = "\n".join(evidence_parts)
    chapters = []
    for position, value in enumerate(chapter_values[:10], start=1):
        summary = summary_values[position - 1] if position <= len(summary_values) else ""
        if isinstance(summary, dict):
            summary = _first(summary, ("summary", "info", "content", "text"), json.dumps(summary, ensure_ascii=False))
        chapter = _chapter(value, position, str(summary))
        if chapter:
            chapters.append(chapter)
    source_id = _clean(_first(record, ("request_id", "id", "novel_id"), title))
    return NovelSample(
        source_id,
        title,
        author,
        raw_genre,
        map_genre(raw_genre, title, overrides, evidence),
        chapters,
    )


def validate_sample(sample: NovelSample, *, min_chars: int, max_chars: int) -> list[str]:
    reasons = []
    if len(sample.chapters) != 10:
        reasons.append(f"正文数量不是10：{len(sample.chapters)}")
    if any(not chapter.summary for chapter in sample.chapters):
        reasons.append("至少一章缺少梗概")
    lengths = [len(re.sub(r"\s+", "", chapter.content)) for chapter in sample.chapters]
    if lengths and min(lengths) < min_chars:
        reasons.append(f"存在短于{min_chars}字的章节")
    if lengths and max(lengths) > max_chars:
        reasons.append(f"存在长于{max_chars}字的章节")
    normalized = [re.sub(r"\s+", "", chapter.content) for chapter in sample.chapters]
    if len(set(normalized)) != len(normalized):
        reasons.append("存在完全重复章节")
    if not sample.category:
        reasons.append("题材无法映射")
    return reasons


def inspect_dataset(input_path: Path, overrides: dict[str, str] | None = None) -> dict[str, Any]:
    records = load_records(input_path)
    samples = [normalize_record(record, index, overrides or {}) for index, record in enumerate(records, 1)]
    valid_samples = [sample for sample in samples if sample]
    category_counts = {category: 0 for category in CATEGORIES}
    for sample in valid_samples:
        if sample.category:
            category_counts[sample.category] += 1
    return {
        "records": len(records),
        "with_10_chapters": sum(len(sample.chapters) == 10 for sample in valid_samples),
        "with_10_summaries": sum(
            len(sample.chapters) == 10 and all(chapter.summary for chapter in sample.chapters)
            for sample in valid_samples
        ),
        "unmapped_genres": sum(not sample.category for sample in valid_samples),
        "category_counts": category_counts,
        "sample_keys": sorted(records[0].keys()) if records else [],
    }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chapter_markdown(chapters: list[Chapter]) -> str:
    blocks = []
    for chapter in chapters:
        lines = chapter.content.splitlines()
        # 数据集正文首行通常已经是原书章节标题。实验文件必须只保留一个
        # 可解析的“第X章”边界，否则基础Agent会把一章拆成两章。
        if lines and lines[0].strip() == chapter.title.strip():
            body = "\n".join(lines[1:]).lstrip()
        else:
            body = chapter.content
        display_title = re.sub(r"^第.+?[章节回篇]\s*", "", chapter.title).strip()
        if not display_title:
            display_title = "未命名"
        blocks.append(f"第{chapter.position}章 {display_title}\n\n{body}")
    return "\n\n".join(blocks) + "\n"


def _outline_markdown(sample: NovelSample) -> str:
    lines = [f"# 《{sample.title}》连续10章局部剧本", ""]
    for chapter in sample.chapters:
        lines.extend([f"第{chapter.position}章 {chapter.title}", "", chapter.summary, ""])
    return "\n".join(lines)


def write_sample(sample: NovelSample, root: Path, number: int) -> dict[str, Any]:
    book_id = f"book_{number:03d}"
    book_root = root / sample.category / book_id
    agent_dir = book_root / "agent_input"
    eval_dir = book_root / "evaluation_only"
    agent_dir.mkdir(parents=True, exist_ok=True)
    eval_dir.mkdir(parents=True, exist_ok=True)
    initial = _chapter_markdown(sample.chapters[:4])
    outline = _outline_markdown(sample)
    reference = _chapter_markdown(sample.chapters[4:])
    (agent_dir / "initial_4_chapters.md").write_text(initial, encoding="utf-8")
    (agent_dir / "local_outline.md").write_text(outline, encoding="utf-8")
    (eval_dir / "reference_chapters.md").write_text(reference, encoding="utf-8")
    chapter_map = {
        str(chapter.position): {
            "reference_index": chapter.position - 4,
            "source_chapter": chapter.source_label,
        }
        for chapter in sample.chapters[4:]
    }
    (eval_dir / "chapter_map.json").write_text(
        json.dumps(chapter_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metadata = {
        "book_id": book_id,
        "source_id": sample.source_id,
        "title": sample.title,
        "author": sample.author,
        "raw_genre": sample.raw_genre,
        "category": sample.category,
        "license": "CC BY-NC-SA 4.0",
        "intended_use": "non-commercial evaluation",
    }
    (book_root / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "book_id": book_id,
        "split": {"agent_visible": [1, 2, 3, 4], "generation_targets": [5, 6, 7, 8, 9, 10],
                  "evaluation_only": [5, 6, 7, 8, 9, 10]},
        "leakage_rule": "evaluation_only目录不得导入Agent数据库、任务卡、检索上下文或故事状态",
        "hashes": {"initial_4_chapters": _sha(initial), "local_outline": _sha(outline),
                   "reference_chapters": _sha(reference)},
        "source_chapters": [chapter.source_label for chapter in sample.chapters],
    }
    (book_root / "split_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def prepare_dataset(
    input_path: Path,
    output_root: Path,
    *,
    per_category: int = 10,
    seed: int = 20260907,
    min_chars: int = 1000,
    max_chars: int = 8000,
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    records = load_records(input_path)
    rejected = []
    pools = {category: [] for category in CATEGORIES}
    for index, record in enumerate(records, 1):
        sample = normalize_record(record, index, overrides or {})
        if not sample:
            continue
        reasons = validate_sample(sample, min_chars=min_chars, max_chars=max_chars)
        if reasons:
            rejected.append({"title": sample.title, "reasons": reasons})
        else:
            pools[sample.category].append(sample)
    rng = random.Random(seed)
    selected = []
    used_authors = set()
    for category in CATEGORIES:
        pool = sorted(pools[category], key=lambda item: (item.title, item.source_id))
        rng.shuffle(pool)
        unique = [item for item in pool if not item.author or item.author not in used_authors]
        fallback = [item for item in pool if item not in unique]
        chosen = (unique + fallback)[:per_category]
        if len(chosen) < per_category:
            raise ValueError(f"{category}合格样本不足：需要{per_category}，只有{len(chosen)}")
        for item in chosen:
            if item.author:
                used_authors.add(item.author)
            selected.append(item)
    output_root.mkdir(parents=True, exist_ok=True)
    metadata = [write_sample(sample, output_root, index) for index, sample in enumerate(selected, 1)]
    manifest = {
        "dataset": "Oedon42/webnovelbench",
        "seed": seed,
        "per_category": per_category,
        "selected_books": len(metadata),
        "generated_target_chapters": len(metadata) * 6,
        "categories": {category: sum(item["category"] == category for item in metadata) for category in CATEGORIES},
        "selection": metadata,
        "rejected_count": len(rejected),
    }
    (output_root / "experiment_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_root / "rejected_samples.json").write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
