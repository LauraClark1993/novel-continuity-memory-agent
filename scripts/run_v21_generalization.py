from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL = PROJECT_ROOT / "skills" / "novel-continuity-memory" / "scripts" / "novel_skill.py"


def db_stats(path: Path) -> dict:
    empty = {"novels": 0, "chapters": 0, "outlines": 0, "accepted": 0}
    if not path.is_file():
        return empty
    try:
        with sqlite3.connect(path) as connection:
            return {
                "novels": connection.execute("SELECT COUNT(*) FROM novels").fetchone()[0],
                "chapters": connection.execute("SELECT COUNT(*) FROM chapters").fetchone()[0],
                "outlines": connection.execute("SELECT COUNT(*) FROM outline_chapters").fetchone()[0],
                "accepted": connection.execute("SELECT COUNT(*) FROM drafts WHERE status='accepted'").fetchone()[0],
            }
    except sqlite3.Error:
        return empty


def invoke(arguments: list[str]) -> int:
    command = [sys.executable, str(SKILL), *arguments, "--project-root", str(PROJECT_ROOT)]
    print("执行：", subprocess.list2cmdline(command), flush=True)
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


def selected_books(manifest: dict, stage: int | None) -> list[dict]:
    books = manifest["books"]
    return [book for book in books if stage is None or int(book["stage"]) == stage]


def write_progress(manifest_path: Path, books: list[dict]) -> Path:
    rows = []
    for book in books:
        stats = db_stats(Path(book["database"]))
        rows.append({**{key: book[key] for key in ("stage", "genre", "book_id", "title", "database")}, **stats})
    path = manifest_path.parent / "batch_progress.json"
    path.write_text(json.dumps({"books": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def initialize(book: dict) -> int:
    db = Path(book["database"])
    output = Path(book["output"])
    stats = db_stats(db)
    if stats["novels"] == 0:
        code = invoke(["create", "--db", str(db), "--title", book["title"], "--author", book["author"]])
        if code:
            return code
        stats = db_stats(db)
    if stats["chapters"] == 0 and stats["outlines"] == 0:
        code = invoke(["import", "--db", str(db), "--novel-id", "1", "--manuscript", book["manuscript"], "--outline", book["outline"]])
        if code:
            return code
    elif stats["chapters"] < 4 or stats["outlines"] != 10:
        print(f"数据库内容数量异常，停止以免重复导入：{db}")
        return 3
    state_file = output / "novel_1" / "v2_story_state.json"
    if not state_file.is_file():
        return invoke(["state-init", "--db", str(db), "--novel-id", "1", "--through-chapter", "4", "--output", str(output)])
    print(f"已初始化，跳过：{book['genre']} / {book['title']}")
    return 0


def run_book(book: dict, args) -> int:
    db = Path(book["database"])
    stats = db_stats(db)
    if stats["accepted"] >= 6:
        print(f"已完成，跳过：{book['genre']} / {book['title']}")
        return 0
    return invoke([
        "run-book", "--db", str(db), "--novel-id", "1", "--start", "5", "--end", "10",
        "--target-chars", str(args.target_chars),
        "--max-revisions", str(args.max_revisions), "--instruction", args.instruction,
        "--output", book["output"],
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description="V2.1 WebNovelBench隔离数据库批量初始化与断点续跑")
    parser.add_argument("command", choices=("status", "init", "run"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--stage", type=int, choices=(1, 2, 3, 4))
    parser.add_argument("--limit", type=int, help="仅调试：最多处理本阶段前N本")
    parser.add_argument("--target-chars", type=int, default=3000)
    parser.add_argument("--max-revisions", type=int, default=2)
    parser.add_argument("--instruction", default="每章第一行必须是第X章加章节名；遵守任务卡和既有事实；正文不超过6000字，不为接近目标字数额外压缩。")
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    books = selected_books(manifest, args.stage)
    if args.limit:
        books = books[: args.limit]
    if args.command == "status":
        path = write_progress(manifest_path, books)
        complete = sum(db_stats(Path(book["database"]))["accepted"] >= 6 for book in books)
        print(f"范围：{len(books)}本；完成：{complete}本；进度：{path.resolve()}")
        return 0
    if args.stage is None:
        raise SystemExit("init和run必须显式指定--stage，防止误跑全部60本")
    for index, book in enumerate(books, 1):
        if args.command == "init":
            code = initialize(book)
        else:
            stats = db_stats(Path(book["database"]))
            state_file = Path(book["output"]) / "novel_1" / "v2_story_state.json"
            if stats["chapters"] < 4 or stats["outlines"] != 10 or not state_file.is_file():
                print(f"尚未完成初始化：{book['title']}。请先运行init。")
                return 4
            code = run_book(book, args)
        write_progress(manifest_path, manifest["books"])
        if code:
            print(f"在第{index}/{len(books)}本停止；再次执行相同命令即可续跑。")
            return code
    print(f"{args.command}完成：stage {args.stage}，{len(books)}本。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
