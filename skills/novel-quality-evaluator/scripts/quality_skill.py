from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def find_project_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "novel_memory_agent").is_dir():
            return candidate
    raise SystemExit("找不到NovelMemory Agent项目根目录，请使用--project-root指定。")


def resolve(root: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (root / value).resolve()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Novel Quality Evaluator Skill")
    commands = value.add_subparsers(dest="command", required=True)
    for name, help_text in (("doctor", "检查评测依赖和数据"), ("evaluate", "运行独立证据化评测")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--project-root", type=Path)
        command.add_argument("--db", type=Path, required=True)
        command.add_argument("--novel-id", type=int, required=True)
        if name == "evaluate":
            command.add_argument("--reference", type=Path)
            command.add_argument("--chapter-map", type=Path)
            command.add_argument("--start", type=int)
            command.add_argument("--end", type=int)
            command.add_argument("--model")
            command.add_argument("--output", type=Path, default=Path("outputs"))
    return value


def doctor(root: Path, db: Path, novel_id: int) -> int:
    print(f"项目：{root}")
    print(f"数据库：{db}")
    print(f"DeepSeek API Key：{'已配置' if os.getenv('DEEPSEEK_API_KEY') else '未配置'}")
    if not db.is_file():
        print("数据库不存在。")
        return 2
    with sqlite3.connect(db) as connection:
        novel = connection.execute("SELECT title FROM novels WHERE id = ?", (novel_id,)).fetchone()
        if not novel:
            print(f"小说ID {novel_id}不存在。")
            return 3
        accepted = connection.execute(
            "SELECT COUNT(*) FROM drafts WHERE novel_id = ? AND status = 'accepted'", (novel_id,)
        ).fetchone()[0]
    print(f"小说：{novel[0]}")
    print(f"可评测的已确认生成草稿：{accepted}")
    return 0 if accepted else 4


def main() -> int:
    args = parser().parse_args()
    root = args.project_root.resolve() if args.project_root else find_project_root(Path.cwd())
    db = resolve(root, args.db)
    if args.command == "doctor":
        return doctor(root, db, args.novel_id)
    command = [sys.executable, "-m", "novel_memory_agent.cli", "--db", str(db),
               "evaluate-quality", str(args.novel_id), "--output", str(resolve(root, args.output))]
    if args.reference:
        reference = resolve(root, args.reference)
        if not reference.is_file():
            raise SystemExit(f"原作参考文件不存在：{reference}")
        command.extend(["--reference", str(reference)])
    if args.chapter_map:
        chapter_map = resolve(root, args.chapter_map)
        if not chapter_map.is_file():
            raise SystemExit(f"章节映射文件不存在：{chapter_map}")
        command.extend(["--chapter-map", str(chapter_map)])
    if args.start is not None:
        command.extend(["--start", str(args.start)])
    if args.end is not None:
        command.extend(["--end", str(args.end)])
    if args.model:
        command.extend(["--model", args.model])
    print("调用独立评估器：", subprocess.list2cmdline(command))
    return subprocess.run(command, cwd=root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
