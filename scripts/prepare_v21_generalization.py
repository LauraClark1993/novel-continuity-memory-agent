from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from novel_memory_agent.webnovelbench import load_records, normalize_record, validate_sample, write_sample


def short_title(value: str) -> str:
    match = re.search(r"《([^》]+)》", value)
    return match.group(1) if match else value.split("作者：", 1)[0]


def embedded_author(value: str) -> str:
    match = re.search(r"作者[：:]\s*(.+)$", value)
    return match.group(1).strip() if match else ""


def safe_name(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", value).strip().rstrip(".")


def main() -> int:
    parser = argparse.ArgumentParser(description="准备V2.1正式泛化实验的60本隔离样本")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--stages", type=Path, required=True)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--database-root", type=Path, required=True)
    args = parser.parse_args()

    selected = json.loads(args.selection.read_text(encoding="utf-8-sig"))
    stage_data = json.loads(args.stages.read_text(encoding="utf-8-sig"))
    stage_by_genre = {
        genre: stage["stage"]
        for stage in stage_data["stages"]
        for genre in stage["new_genres"]
    }
    order = [genre for stage in stage_data["stages"] for genre in stage["new_genres"]]
    wanted = {title: genre for genre, titles in selected.items() for title in titles}

    samples = {}
    for index, record in enumerate(load_records(args.input), 1):
        sample = normalize_record(record, index, {})
        if sample is None:
            continue
        title = short_title(sample.title)
        if title in wanted:
            sample.category = wanted[title]
            sample.author = sample.author or embedded_author(sample.title)
            reasons = validate_sample(sample, min_chars=1000, max_chars=8000)
            if reasons:
                raise ValueError(f"{title}不再满足冻结条件：{reasons}")
            samples[title] = sample
    missing = sorted(set(wanted) - set(samples))
    if missing:
        raise ValueError(f"原始数据缺少冻结样本：{missing}")

    args.sample_root.mkdir(parents=True, exist_ok=True)
    args.database_root.mkdir(parents=True, exist_ok=True)
    manifest = []
    number = 0
    for genre in order:
        for title in selected[genre]:
            number += 1
            sample = samples[title]
            metadata = write_sample(sample, args.sample_root, number)
            book_id = metadata["book_id"]
            book_root = args.sample_root / genre / book_id
            db_path = args.database_root / f"stage_{stage_by_genre[genre]:02d}" / safe_name(genre) / f"{book_id}_{safe_name(title)}.db"
            output_root = book_root / "outputs"
            manifest.append(
                {
                    "stage": stage_by_genre[genre],
                    "genre": genre,
                    "book_id": book_id,
                    "title": title,
                    "author": sample.author,
                    "database": str(db_path.resolve()),
                    "book_root": str(book_root.resolve()),
                    "manuscript": str((book_root / "agent_input" / "initial_4_chapters.md").resolve()),
                    "outline": str((book_root / "agent_input" / "local_outline.md").resolve()),
                    "reference": str((book_root / "evaluation_only" / "reference_chapters.md").resolve()),
                    "chapter_map": str((book_root / "evaluation_only" / "chapter_map.json").resolve()),
                    "output": str(output_root.resolve()),
                    "novel_id": 1,
                    "generation_start": 5,
                    "generation_end": 10,
                    "status": "prepared",
                }
            )
    output_manifest = args.sample_root / "experiment_manifest.json"
    output_manifest.write_text(
        json.dumps(
            {
                "dataset": "Oedon42/webnovelbench",
                "design": "20 genres x 3 books x 6 generated chapters",
                "database_isolation": "one SQLite database per book",
                "database_root": str(args.database_root.resolve()),
                "books": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(output_manifest.resolve())
    print(f"已准备{len(manifest)}本；数据库目录：{args.database_root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
