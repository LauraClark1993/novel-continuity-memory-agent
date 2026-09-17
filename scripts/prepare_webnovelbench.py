from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from novel_memory_agent.webnovelbench import inspect_dataset, prepare_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="准备WebNovelBench泛化实验数据")
    parser.add_argument("command", choices=("inspect", "prepare"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("datasets/webnovelbench_experiment"))
    parser.add_argument("--genre-map", type=Path, help="可选：书名到五类题材的JSON映射")
    parser.add_argument("--per-category", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260907)
    parser.add_argument("--min-chars", type=int, default=1000)
    parser.add_argument("--max-chars", type=int, default=8000)
    args = parser.parse_args()
    if not args.input.exists():
        raise SystemExit(f"输入不存在：{args.input}")
    overrides = {}
    if args.genre_map:
        overrides = json.loads(args.genre_map.read_text(encoding="utf-8-sig"))
    if args.command == "inspect":
        result = inspect_dataset(args.input, overrides)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    result = prepare_dataset(
        args.input,
        args.output,
        per_category=args.per_category,
        seed=args.seed,
        min_chars=args.min_chars,
        max_chars=args.max_chars,
        overrides=overrides,
    )
    print(f"已准备{result['selected_books']}本，待生成{result['generated_target_chapters']}章。")
    print(f"实验清单：{(args.output / 'experiment_manifest.json').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
