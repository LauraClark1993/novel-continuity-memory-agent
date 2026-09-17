from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def find_project_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "novel_memory_agent").is_dir():
            return candidate
    raise SystemExit("找不到NovelMemory Agent项目根目录，请使用 --project-root 指定。")


def resolve_root(value: Path | None) -> Path:
    root = value.resolve() if value else find_project_root(Path.cwd().resolve())
    if not (root / "novel_memory_agent").is_dir():
        raise SystemExit(f"不是有效的NovelMemory Agent项目：{root}")
    return root


def resolve_path(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def doctor(root: Path, db_arg: Path, novel_id: int | None) -> int:
    db = resolve_path(root, db_arg)
    print(f"项目：{root}")
    print(f"数据库：{db}")
    print(f"DeepSeek API Key：{'已配置' if os.getenv('DEEPSEEK_API_KEY') else '未配置'}")
    if not db.exists():
        print("数据库：不存在")
        return 2
    print(f"数据库：存在（{db.stat().st_size} bytes）")
    if novel_id is None:
        return 0
    try:
        with sqlite3.connect(db) as connection:
            row = connection.execute("SELECT title FROM novels WHERE id = ?", (novel_id,)).fetchone()
            if not row:
                print(f"小说ID {novel_id}：不存在")
                return 3
            chapter_count = connection.execute(
                "SELECT COUNT(*) FROM chapters WHERE novel_id = ?", (novel_id,)
            ).fetchone()[0]
            print(f"小说ID {novel_id}：{row[0]}")
            print(f"已确认章节：{chapter_count}")
    except sqlite3.Error as error:
        print(f"数据库结构检查失败：{error}")
        return 4
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--novel-id", type=int, required=True)


def run_cli(root: Path, db: Path, arguments: list[str]) -> int:
    command = [sys.executable, "-m", "novel_memory_agent.cli", "--db", str(db), *arguments]
    print("调用基础Agent：", subprocess.list2cmdline(command))
    return subprocess.run(command, cwd=root, check=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Novel Continuity Memory Skill adapter")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("doctor", help="检查项目、数据库、小说和API配置")
    check.add_argument("--project-root", type=Path)
    check.add_argument("--db", type=Path, required=True)
    check.add_argument("--novel-id", type=int)

    create = sub.add_parser("create", help="在独立数据库中新建小说")
    create.add_argument("--project-root", type=Path)
    create.add_argument("--db", type=Path, required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--author", default="")

    import_data = sub.add_parser("import", help="导入前置正文和完整大纲")
    add_common(import_data)
    import_data.add_argument("--manuscript", type=Path, required=True)
    import_data.add_argument("--outline", type=Path, required=True)

    state = sub.add_parser("state-init", help="初始化结构化故事状态")
    add_common(state)
    state.add_argument("--through-chapter", type=int, required=True)
    state.add_argument("--output", type=Path, default=Path("outputs_v2"))

    show = sub.add_parser("state-show", help="查看结构化故事状态")
    add_common(show)
    show.add_argument("--section", default="all")
    show.add_argument("--output", type=Path)

    preview = sub.add_parser("preview", help="预览当前章节的最小充分上下文")
    add_common(preview)
    preview.add_argument("--outline", type=int, required=True)
    preview.add_argument("--instruction", default="")
    preview.add_argument("--output", type=Path, default=Path("outputs_v2"))

    run = sub.add_parser("run-book", help="按章生成并支持断点续跑")
    add_common(run)
    run.add_argument("--start", type=int, default=5)
    run.add_argument("--end", type=int, required=True)
    run.add_argument("--target-chars", type=int, default=3000)
    run.add_argument("--max-cost", type=float, required=True)
    run.add_argument("--max-revisions", type=int, default=2)
    run.add_argument("--instruction", default="")
    run.add_argument("--output", type=Path, default=Path("outputs_v2"))

    usage = sub.add_parser("usage", help="查看Token和估算费用")
    add_common(usage)
    evaluate = sub.add_parser("evaluate", help="生成不调用API的评测报告")
    add_common(evaluate)
    evaluate.add_argument("--output", type=Path, default=Path("outputs_v2"))
    quality = sub.add_parser("evaluate-quality", help="调用独立裁判生成证据化质量报告")
    add_common(quality)
    quality.add_argument("--reference", type=Path)
    quality.add_argument("--chapter-map", type=Path)
    quality.add_argument("--start", type=int)
    quality.add_argument("--end", type=int)
    quality.add_argument("--model")
    quality.add_argument("--output", type=Path, default=Path("outputs_v2"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = resolve_root(args.project_root)
    if args.command == "doctor":
        return doctor(root, args.db, args.novel_id)
    db = resolve_path(root, args.db)
    if args.command == "create":
        db.parent.mkdir(parents=True, exist_ok=True)
        return run_cli(root, db, ["create", args.title, "--author", args.author])
    if not db.exists():
        raise SystemExit(f"数据库不存在：{db}")
    if args.command == "import":
        manuscript = resolve_path(root, args.manuscript)
        outline = resolve_path(root, args.outline)
        for label, path in (("正文", manuscript), ("大纲", outline)):
            if not path.is_file():
                raise SystemExit(f"{label}文件不存在：{path}")
        return run_cli(root, db, ["import", str(args.novel_id), "--manuscript",
                                  str(manuscript), "--outline", str(outline)])
    if args.command == "state-init":
        return run_cli(root, db, ["state-init", str(args.novel_id), "--through-chapter",
                                  str(args.through_chapter), "--output", str(args.output)])
    if args.command == "state-show":
        arguments = ["state-show", str(args.novel_id), "--section", args.section]
        if args.output:
            arguments.extend(["--output", str(args.output)])
        return run_cli(root, db, arguments)
    if args.command == "preview":
        return run_cli(root, db, ["preview", str(args.novel_id), "--outline",
                                  str(args.outline), "--instruction", args.instruction,
                                  "--output", str(args.output)])
    if args.command == "run-book":
        return run_cli(root, db, ["run-book", str(args.novel_id), "--start", str(args.start),
                                  "--end", str(args.end), "--target-chars", str(args.target_chars),
                                  "--max-cost", str(args.max_cost), "--max-revisions",
                                  str(args.max_revisions), "--output", str(args.output),
                                  "--instruction", args.instruction])
    if args.command == "usage":
        return run_cli(root, db, ["usage", str(args.novel_id)])
    if args.command == "evaluate":
        return run_cli(root, db, ["evaluate", str(args.novel_id), "--output", str(args.output)])
    if args.command == "evaluate-quality":
        arguments = ["evaluate-quality", str(args.novel_id), "--output", str(args.output)]
        if args.reference:
            arguments.extend(["--reference", str(resolve_path(root, args.reference))])
        if args.chapter_map:
            arguments.extend(["--chapter-map", str(resolve_path(root, args.chapter_map))])
        if args.start is not None:
            arguments.extend(["--start", str(args.start)])
        if args.end is not None:
            arguments.extend(["--end", str(args.end)])
        if args.model:
            arguments.extend(["--model", args.model])
        return run_cli(root, db, arguments)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
