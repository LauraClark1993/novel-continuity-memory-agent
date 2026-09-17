from __future__ import annotations

import re

from .models import OutlineChapter, ParsedChapter


CHAPTER_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?(?P<title>第[0-9零〇一二三四五六七八九十百千万两]+[章节卷回篇]\s*[^\n*]{0,60}"
    r"|Chapter\s+\d+[^\n*]{0,60})(?:\*\*)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

OUTLINE_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?(?P<title>第[0-9零〇一二三四五六七八九十百千万两]+[章节卷回篇]\s*[^\n*]{0,60}"
    r"|Chapter\s+\d+[^\n*]{0,60})(?:\*\*)?\s*(?:[:：-]\s*(?P<inline>.*))?$",
    re.IGNORECASE,
)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _split_by_length(text: str, max_chars: int) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for paragraph in paragraphs:
        if current and current_size + len(paragraph) + 2 > max_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_size = 0
        if len(paragraph) > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_size = 0
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start : start + max_chars])
            continue
        current.append(paragraph)
        current_size += len(paragraph) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks or ([text] if text else [])


def parse_manuscript(text: str, *, fallback_chunk_chars: int = 8000) -> list[ParsedChapter]:
    text = normalize_text(text)
    if not text:
        return []

    matches = list(CHAPTER_HEADING.finditer(text))
    if not matches:
        return [
            ParsedChapter(ordinal=index, title=f"片段 {index}", content=chunk)
            for index, chunk in enumerate(_split_by_length(text, fallback_chunk_chars), start=1)
        ]

    chapters: list[ParsedChapter] = []
    preface = text[: matches[0].start()].strip()
    heading_only_preface = bool(re.fullmatch(r"#{1,6}\s+[^\n]+", preface))
    if preface and not heading_only_preface:
        chapters.append(ParsedChapter(ordinal=1, title="序章/前言", content=preface))

    for match_index, match in enumerate(matches):
        start = match.end()
        end = matches[match_index + 1].start() if match_index + 1 < len(matches) else len(text)
        title = match.group("title").strip()
        content = text[start:end].strip()
        chapters.append(ParsedChapter(ordinal=len(chapters) + 1, title=title, content=content))
    return chapters


def parse_outline(text: str) -> list[OutlineChapter]:
    text = normalize_text(text)
    if not text:
        return []
    lines = text.splitlines()
    chapters: list[OutlineChapter] = []
    current_title = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if not current_title:
            return
        raw = "\n".join(line for line in current_lines if line.strip()).strip()
        core_event = _first_meaningful_line(raw)
        chapters.append(
            OutlineChapter(
                ordinal=len(chapters) + 1,
                title=current_title,
                core_event=core_event,
                raw_text=raw,
            )
        )
        current_title = ""
        current_lines = []

    for line in lines:
        match = OUTLINE_HEADING.match(line)
        if match:
            flush()
            current_title = match.group("title").strip()
            inline = (match.group("inline") or "").strip()
            current_lines = [inline] if inline else []
        elif current_title:
            current_lines.append(line)
    flush()

    if chapters:
        return chapters

    # Accept a lightweight list when headings do not follow “第X章”.
    entries = [item.strip(" -\t") for item in lines if item.strip()]
    return [
        OutlineChapter(
            ordinal=index,
            title=f"第 {index} 章",
            core_event=entry,
            raw_text=entry,
        )
        for index, entry in enumerate(entries, start=1)
    ]


def _first_meaningful_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = re.sub(
            r"^(核心事件|本章内容|剧情|概要|概括|一句话)\s*[:：]\s*", "", line.strip()
        )
        if cleaned:
            return cleaned
    return ""
