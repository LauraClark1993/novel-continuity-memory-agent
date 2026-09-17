from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs_v2" / "整书上下文对照组" / "dataset" / "raw" / "替他守侯府十年，他只当我是下人.md"
DRAFT_ROOT = ROOT / "outputs_v2" / "novel_1"
OUTPUT_DIR = ROOT / "outputs_v2" / "检索上下文组合订本"
OUTPUT = OUTPUT_DIR / "替他守侯府十年，他只当我是下人_V2检索上下文组_全65章.md"

HEADING_RE = re.compile(r"(?m)^#\s+(第[一二三四]章[^\r\n]*)\s*$")


def chinese_number(value: int) -> str:
    digits = "零一二三四五六七八九"
    if value < 10:
        return digits[value]
    tens, ones = divmod(value, 10)
    prefix = "十" if tens == 1 else digits[tens] + "十"
    return prefix if ones == 0 else prefix + digits[ones]


def source_chapters() -> list[str]:
    text = SOURCE.read_text(encoding="utf-8-sig").strip()
    matches = list(HEADING_RE.finditer(text))
    if len(matches) != 4:
        raise RuntimeError(f"前四章源文件应有4个章节标题，实际找到{len(matches)}个")

    chapters: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chapter = text[match.start():end].strip()
        chapter = re.sub(r"^#\s+", "", chapter, count=1)
        chapters.append(chapter)
    return chapters


def generated_chapters() -> list[str]:
    chapters: list[str] = []
    for chapter_number in range(5, 66):
        draft_id = chapter_number + 1
        path = DRAFT_ROOT / f"draft_{draft_id}" / "draft.md"
        if not path.exists():
            raise FileNotFoundError(f"缺少第{chapter_number}章正文：{path}")
        text = path.read_text(encoding="utf-8-sig").strip()
        first_line = text.splitlines()[0].strip().lstrip("#").strip()
        valid_prefixes = (f"第{chapter_number}章", f"第{chinese_number(chapter_number)}章")
        if not first_line.startswith(valid_prefixes):
            raise RuntimeError(
                f"章节标题异常：期望第{chapter_number}章，实际为 {first_line!r}（{path}）"
            )
        text = re.sub(r"^#+\s*", "", text, count=1)
        chapters.append(text)
    return chapters


def main() -> None:
    chapters = source_chapters() + generated_chapters()
    if len(chapters) != 65:
        raise RuntimeError(f"合并结果应为65章，实际为{len(chapters)}章")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    content = "# 替他守侯府十年，他只当我是下人\n\n" + "\n\n---\n\n".join(chapters) + "\n"
    OUTPUT.write_text(content, encoding="utf-8")

    chars = len(re.sub(r"\s+", "", content))
    print(f"合并完成：{OUTPUT}")
    print(f"章节数：{len(chapters)}")
    print(f"非空白字符数：{chars}")


if __name__ == "__main__":
    main()
