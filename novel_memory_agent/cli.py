from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
from typing import Any

from .agent import BudgetExceededError, NovelAgent
from .config import Settings
from .database import NovelDatabase
from .deepseek import DeepSeekClient, DeepSeekError
from .evaluation import write_evaluation
from .pricing import estimate_cny
from .quality_evaluation import run_quality_evaluation
from .story_state import SECTIONS, StoryStateStore, empty_story_state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NovelMemory Agent CLI")
    parser.add_argument("--db", default="data/novel_memory.db", help="SQLite 数据库路径")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="创建小说项目")
    create.add_argument("title")
    create.add_argument("--author", default="")

    import_text = subparsers.add_parser("import", help="导入正文和大纲")
    import_text.add_argument("novel_id", type=int)
    import_text.add_argument("--manuscript", type=Path)
    import_text.add_argument("--outline", type=Path)

    subparsers.add_parser("list", help="列出小说项目")

    test_api = subparsers.add_parser("test-api", help="安全测试真实 DeepSeek API 连接")
    test_api.add_argument("--model", default=None, help="默认使用配置中的 Flash 模型")
    test_api.add_argument(
        "--visible-input",
        action="store_true",
        help="在终端中显示输入内容，仅用于隐藏输入无法粘贴时",
    )

    analyze = subparsers.add_parser("analyze", help="分析一个正文章节并提取候选记忆")
    analyze.add_argument("novel_id", type=int)
    analyze.add_argument("--chapter", type=int, required=True, help="正文章节序号")

    memories = subparsers.add_parser("memories", help="列出小说记忆")
    memories.add_argument("novel_id", type=int)
    memories.add_argument(
        "--status",
        choices=["candidate", "confirmed", "rejected"],
        default="candidate",
    )

    memory_status = subparsers.add_parser("memory-status", help="确认或废弃一条记忆")
    memory_status.add_argument("memory_id", type=int)
    memory_status.add_argument("status", choices=["confirmed", "rejected"])

    review_memories = subparsers.add_parser(
        "review-memories", help="在PowerShell中逐条审核候选记忆"
    )
    review_memories.add_argument("novel_id", type=int)

    preview = subparsers.add_parser("preview", help="预览下一章最小充分上下文")
    preview.add_argument("novel_id", type=int)
    preview.add_argument("--outline", type=int, required=True, help="大纲章节序号")
    preview.add_argument("--instruction", default="")
    preview.add_argument("--output", type=Path, default=Path("outputs"))

    generate = subparsers.add_parser("generate", help="生成章节并执行一致性检查")
    generate.add_argument("novel_id", type=int)
    generate.add_argument("--outline", type=int, required=True, help="大纲章节序号")
    generate.add_argument("--instruction", default="")
    generate.add_argument("--target-chars", type=int, default=None)
    generate.add_argument("--output", type=Path, default=Path("outputs"))

    regenerate = subparsers.add_parser("regenerate", help="重新生成并覆盖一个未确认草稿")
    regenerate.add_argument("draft_id", type=int)
    regenerate.add_argument("--instruction", default="")
    regenerate.add_argument("--target-chars", type=int, default=None)
    regenerate.add_argument("--output", type=Path, default=Path("outputs"))

    accept = subparsers.add_parser("accept", help="确认草稿并提取增量候选记忆")
    accept.add_argument("draft_id", type=int)
    accept.add_argument("--file", type=Path, help="先用指定UTF-8文件替换草稿正文")
    accept_v2 = subparsers.add_parser("accept-v2", help="确认已通过审核的V2保留草稿并更新状态")
    accept_v2.add_argument("draft_id", type=int)

    repair = subparsers.add_parser("repair-truncated", help="补全被Token上限截断的已确认章节")
    repair.add_argument("draft_id", type=int)
    repair.add_argument("--extra-chars", type=int, default=1200)
    repair.add_argument("--output", type=Path, default=Path("outputs"))

    drafts = subparsers.add_parser("drafts", help="列出历史草稿")
    drafts.add_argument("novel_id", type=int)

    usage = subparsers.add_parser("usage", help="查看Token和费用汇总")
    usage.add_argument("novel_id", type=int)

    evaluate = subparsers.add_parser("evaluate", help="生成MVP成本与上下文效果报告（不调用API）")
    evaluate.add_argument("novel_id", type=int)
    evaluate.add_argument("--output", type=Path, default=Path("outputs"))

    quality_evaluate = subparsers.add_parser(
        "evaluate-quality", help="调用独立裁判生成逐章质量、证据和漏检报告"
    )
    quality_evaluate.add_argument("novel_id", type=int)
    quality_evaluate.add_argument("--reference", type=Path, help="可选：含原作对应章节的正文文件")
    quality_evaluate.add_argument(
        "--chapter-map", type=Path, help="可选：实验章到原作章与参考文件位置的JSON映射"
    )
    quality_evaluate.add_argument("--start", type=int)
    quality_evaluate.add_argument("--end", type=int)
    quality_evaluate.add_argument("--model", default=None)
    quality_evaluate.add_argument("--output", type=Path, default=Path("outputs"))

    state_template = subparsers.add_parser("state-template", help="生成V2故事状态JSON模板")
    state_template.add_argument("--output", type=Path, default=Path("story_state.json"))

    state_import = subparsers.add_parser("state-import", help="导入或更新V2故事状态")
    state_import.add_argument("novel_id", type=int)
    state_import.add_argument("--file", type=Path, required=True, help="UTF-8 JSON状态文件")

    state_show = subparsers.add_parser("state-show", help="查看V2结构化故事状态")
    state_show.add_argument("novel_id", type=int)
    state_show.add_argument("--section", choices=("all", *SECTIONS), default="all")
    state_show.add_argument("--output", type=Path, help="可选：另存为UTF-8 JSON文件")

    state_init = subparsers.add_parser("state-init", help="调用DeepSeek初始化V2故事状态")
    state_init.add_argument("novel_id", type=int)
    state_init.add_argument(
        "--through-chapter", type=int, help="只读取该序号及以前的正文；默认读取全部现有正文"
    )
    state_init.add_argument("--model", default=None)
    state_init.add_argument("--output", type=Path, default=Path("outputs"))

    clone_v2 = subparsers.add_parser("clone-v2-db", help="建立隔离的V2实验数据库")
    clone_v2.add_argument("novel_id", type=int)
    clone_v2.add_argument("--through-chapter", type=int, required=True)
    clone_v2.add_argument("--output-db", type=Path, required=True)

    rename_location = subparsers.add_parser("state-rename-location", help="修改V2场景正式名称")
    rename_location.add_argument("novel_id", type=int)
    rename_location.add_argument("old_name")
    rename_location.add_argument("new_name")
    rename_location.add_argument("--allow-old-alias", action="store_true")

    replace_location = subparsers.add_parser(
        "state-replace-location-reference", help="迁移人物与章节状态中的旧场景名称"
    )
    replace_location.add_argument("novel_id", type=int)
    replace_location.add_argument("old_name")
    replace_location.add_argument("new_name")

    run_book = subparsers.add_parser("run-book", help="按章节顺序断点续跑整本V2小说")
    run_book.add_argument("novel_id", type=int)
    run_book.add_argument("--start", type=int, default=5)
    run_book.add_argument("--end", type=int, required=True)
    run_book.add_argument("--target-chars", type=int, default=3000)
    run_book.add_argument("--max-cost", type=float, default=200.0)
    run_book.add_argument("--max-revisions", type=int, default=2)
    run_book.add_argument("--instruction", default="")
    run_book.add_argument("--output", type=Path, default=Path("outputs_v2"))

    budget_set = subparsers.add_parser("budget-set", help="修改项目API预算停止线")
    budget_set.add_argument("novel_id", type=int)
    budget_set.add_argument("amount", type=float)
    return parser


def _find_by_ordinal(rows: list[dict[str, Any]], ordinal: int, label: str) -> dict[str, Any]:
    row = next((item for item in rows if int(item["ordinal"]) == ordinal), None)
    if not row:
        available = ", ".join(str(item["ordinal"]) for item in rows) or "无"
        raise SystemExit(f"找不到{label}序号 {ordinal}。可用序号：{available}")
    return row


def _write_generation_files(output_root: Path, novel_id: int, result: Any) -> Path:
    run_dir = output_root / f"novel_{novel_id}" / f"draft_{result.draft_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "draft.md").write_text(result.draft, encoding="utf-8")
    (run_dir / "context.md").write_text(result.context_bundle.text, encoding="utf-8")
    (run_dir / "task_card.json").write_text(
        json.dumps(result.task_card, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "continuity.json").write_text(
        json.dumps(result.continuity_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return run_dir


def _revision_instruction(base: str, report: dict[str, Any]) -> str:
    feedback = []
    length_failed = False
    # Medium-risk notes are diagnostic only and often explicitly say that no
    # change is required. Feeding them back into a rewrite distracts the model
    # from actual missing events and can create new inconsistencies.
    for item in report.get("high_risk", []):
        if isinstance(item, dict):
            if "篇幅不在允许范围" in str(item.get("issue", "")):
                length_failed = True
            feedback.append(f"高风险：{item.get('issue', '')}；修改要求：{item.get('suggestion', '')}")
    for item in report.get("outline_completion", []):
        if isinstance(item, dict) and item.get("status") != "done":
            status = item.get("status", "partial")
            priority = "必须补写" if status == "missing" else "必须完整落实"
            feedback.append(f"{priority}：{item.get('requirement', '')}")
    joined = "\n".join(f"- {item}" for item in feedback if item)
    length_rule = ""
    if length_failed:
        length_rule = (
            "\n本次重写以约3000字为目标，只需确保完整正文不超过6000字。"
            "保留任务卡事件、关键因果和结尾钩子；不要调用额外压缩流程，"
            "也不得用新增情节填充篇幅。"
        )
    return (
        f"{base}\n上一版未通过AI审核，必须完整重写并修复以下问题：\n{joined}"
        "\n按故事发生顺序逐项完成上述要求；missing项优先，partial项必须补成完整事件。"
        "所有要求完成并到达任务卡end_state之前不得结束正文。"
        f"{length_rule}"
    ).strip()


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env(args.db)
    database = NovelDatabase(settings.database_path)
    agent = NovelAgent(database, settings)
    state_store = StoryStateStore(database)

    if args.command == "create":
        novel_id = database.create_novel(args.title, author=args.author)
        print(json.dumps({"novel_id": novel_id}, ensure_ascii=False))
    elif args.command == "list":
        print(json.dumps(database.list_novels(), ensure_ascii=False, indent=2))
    elif args.command == "import":
        result = {}
        if args.manuscript:
            result["chapters"] = agent.import_manuscript(
                args.novel_id, args.manuscript.read_text(encoding="utf-8")
            )
        if args.outline:
            result["outline_chapters"] = agent.import_outline(
                args.novel_id, args.outline.read_text(encoding="utf-8")
            )
        print(json.dumps(result, ensure_ascii=False))
    elif args.command == "test-api":
        if not settings.api_key:
            if args.visible_input:
                print("警告：本次输入会显示在屏幕上。请勿截图，测试结束后执行 Clear-Host。")
                settings.api_key = input("请输入 DeepSeek API Key: ").strip()
            else:
                settings.api_key = getpass.getpass(
                    "请输入 DeepSeek API Key（输入不会显示）: "
                ).strip()
        if not settings.api_key:
            raise SystemExit("未输入 API Key，测试已取消。")
        try:
            response = DeepSeekClient(settings).test_connection(model=args.model)
        except DeepSeekError as error:
            raise SystemExit(f"连接失败：{error}") from error
        cost_cny = estimate_cny(
            response.model,
            response.usage,
            exchange_rate=settings.exchange_rate_cny_per_usd,
            period=settings.pricing_period,
        )
        print("\nDeepSeek API 连接成功")
        print(f"模型：{response.model}")
        print(f"回复：{response.content}")
        print(f"输入 Token：{response.usage.prompt_tokens}")
        print(f"输出 Token：{response.usage.completion_tokens}")
        print(f"本次估算费用：{cost_cny:.6f} 元")
    elif args.command == "analyze":
        chapter = _find_by_ordinal(
            database.list_chapters(args.novel_id), args.chapter, "正文章节"
        )
        result = agent.analyze_chapter(args.novel_id, chapter["id"])
        print(f"章节分析完成：{chapter['title']}")
        print(f"摘要：{result['summary']}")
        print(f"新增候选记忆：{result['memory_count']} 条")
        print(f"下一步：python -m novel_memory_agent.cli memories {args.novel_id}")
    elif args.command == "memories":
        rows = database.list_memories(args.novel_id, statuses=(args.status,))
        if not rows:
            print(f"没有状态为 {args.status} 的记忆。")
        for row in rows:
            source = row.get("source_chapter_title") or row["source_type"]
            print(
                f"#{row['id']} [{row['kind']}] {row['subject']}\n"
                f"  {row['content']}\n  来源：{source}｜置信度：{row['confidence']:.2f}\n"
            )
    elif args.command == "memory-status":
        database.update_memory_status(args.memory_id, args.status)
        print(f"记忆 #{args.memory_id} 已更新为 {args.status}。")
    elif args.command == "review-memories":
        rows = database.list_memories(args.novel_id, statuses=("candidate",))
        if not rows:
            print("没有待审核的候选记忆。")
        confirmed = 0
        rejected = 0
        skipped = 0
        for index, row in enumerate(rows, start=1):
            source = row.get("source_chapter_title") or row["source_type"]
            print("\n" + "=" * 72)
            print(f"进度 {index}/{len(rows)}｜记忆 #{row['id']}｜类型 {row['kind']}")
            print(f"主体：{row['subject']}")
            print(f"内容：{row['content']}")
            print(f"来源：{source}｜置信度：{row['confidence']:.2f}")
            if row["evidence"]:
                print(f"证据：{row['evidence']}")
            while True:
                choice = input("[y]确认  [n]废弃  [s]跳过  [q]保存进度并退出：").strip().lower()
                if choice in {"y", "yes"}:
                    database.update_memory_status(row["id"], "confirmed")
                    confirmed += 1
                    break
                if choice in {"n", "no"}:
                    database.update_memory_status(row["id"], "rejected")
                    rejected += 1
                    break
                if choice in {"s", "skip", ""}:
                    skipped += 1
                    break
                if choice in {"q", "quit"}:
                    print(
                        f"\n本次审核：确认 {confirmed}｜废弃 {rejected}｜跳过 {skipped}。"
                    )
                    return
                print("请输入 y、n、s 或 q。")
        print(f"\n审核完成：确认 {confirmed}｜废弃 {rejected}｜跳过 {skipped}。")
    elif args.command == "preview":
        outline = _find_by_ordinal(
            database.list_outline(args.novel_id), args.outline, "大纲章节"
        )
        bundle = agent.preview_context(args.novel_id, outline["id"], args.instruction)
        output = args.output / f"novel_{args.novel_id}" / f"outline_{args.outline}_context.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(bundle.text, encoding="utf-8")
        print(f"上下文预览已生成：{output.resolve()}")
        print(f"估算 Token：{bundle.estimated_tokens}")
        print(f"引用章节：{len(bundle.source_chapter_ids)}｜引用记忆：{len(bundle.memory_ids)}")
    elif args.command in {"generate", "regenerate"}:
        if args.command == "generate":
            novel_id = args.novel_id
            outline = _find_by_ordinal(
                database.list_outline(novel_id), args.outline, "大纲章节"
            )
            replace_draft_id = None
        else:
            existing = database.get_draft(args.draft_id)
            if not existing:
                raise SystemExit("草稿不存在")
            if existing["status"] != "draft":
                raise SystemExit("只能覆盖尚未确认的草稿")
            novel_id = int(existing["novel_id"])
            outline = database.get_outline_chapter(existing["outline_chapter_id"])
            if not outline:
                raise SystemExit("草稿对应的大纲章节不存在")
            replace_draft_id = args.draft_id
        result = agent.generate_chapter(
            novel_id,
            outline["id"],
            instruction=args.instruction,
            target_chars=args.target_chars,
            replace_draft_id=replace_draft_id,
        )
        output_dir = _write_generation_files(args.output, novel_id, result)
        if replace_draft_id is not None:
            print(f"旧草稿 #{replace_draft_id} 已被重新生成结果覆盖。")
        print(f"章节草稿已生成：{(output_dir / 'draft.md').resolve()}")
        print(f"章节任务卡：{(output_dir / 'task_card.json').resolve()}")
        print(f"一致性报告：{(output_dir / 'continuity.json').resolve()}")
        print(f"上下文包：{(output_dir / 'context.md').resolve()}")
        print(f"草稿编号：{result.draft_id}")
        print(
            "一致性结论："
            + ("通过" if result.continuity_report.get("passed") else "存在高风险冲突")
        )
        print(
            f"确认命令：python -m novel_memory_agent.cli accept {result.draft_id} "
            f"--file \"{(output_dir / 'draft.md').resolve()}\""
        )
    elif args.command == "accept":
        if args.file:
            if not args.file.exists():
                raise SystemExit(f"草稿文件不存在：{args.file}")
            database.update_draft_content(
                args.draft_id, args.file.read_text(encoding="utf-8")
            )
        result = agent.accept_and_extract_memories(args.draft_id)
        print(f"草稿已写入正式正文，章节数据库编号：{result['chapter_id']}")
        print(f"新增候选记忆：{result['candidate_memories']} 条")
    elif args.command == "accept-v2":
        result = agent.accept_v2_draft(args.draft_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "repair-truncated":
        draft = database.get_draft(args.draft_id)
        if not draft:
            raise SystemExit("草稿不存在")
        repaired = agent.repair_truncated_draft(args.draft_id, extra_chars=args.extra_chars)
        output = args.output / f"novel_{draft['novel_id']}" / f"draft_{args.draft_id}" / "draft.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(repaired, encoding="utf-8")
        print(f"截断章节已补全并同步到正式正文：{output.resolve()}")
        print("下一步：重新生成受影响的后一章；旧草稿不要确认。")
    elif args.command == "drafts":
        rows = database.list_drafts(args.novel_id)
        if not rows:
            print("暂无草稿。")
        for row in rows:
            print(f"#{row['id']} [{row['status']}] {row['title']}｜{row['created_at']}")
    elif args.command == "usage":
        summary = database.usage_summary(args.novel_id)
        print(f"API 调用：{summary['calls']}")
        print(f"输入 Token：{summary['prompt_tokens']}")
        print(f"缓存命中 Token：{summary['cache_hit_tokens']}")
        print(f"输出 Token：{summary['completion_tokens']}")
        print(f"累计估算费用：{float(summary['cost_cny']):.6f} 元（最终实扣以DeepSeek后台为准）")
    elif args.command == "evaluate":
        output_dir = args.output / f"novel_{args.novel_id}" / "evaluation"
        report_path, metrics_path, metrics = write_evaluation(
            database, args.novel_id, output_dir
        )
        print(f"MVP验证报告：{report_path.resolve()}")
        print(f"结构化指标：{metrics_path.resolve()}")
        print(f"上下文节省率：{metrics['context_saving_rate']:.1%}")
        print(f"累计估算费用：{metrics['actual_cost_cny']:.4f} 元（最终实扣以DeepSeek后台为准）")
    elif args.command == "evaluate-quality":
        output_dir = args.output / f"novel_{args.novel_id}" / "quality_evaluation"
        report_path, summary_path, summary = run_quality_evaluation(
            agent,
            args.novel_id,
            output_dir,
            reference_path=args.reference,
            chapter_map_path=args.chapter_map,
            start=args.start,
            end=args.end,
            model=args.model,
        )
        print(f"独立质量报告：{report_path.resolve()}")
        print(f"结构化汇总：{summary_path.resolve()}")
        print(f"V2.0十项综合得分：{summary['overall_score']:.2f}/100")
        if summary["reference_plot_function_score"] is not None:
            print(f"原作剧情功能匹配分：{summary['reference_plot_function_score']:.2f}/100")
        if summary["experiment_effect_score"] is not None:
            print(f"实验效果总分（含原作剧情功能）：{summary['experiment_effect_score']:.2f}/100")
    elif args.command == "state-template":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(empty_story_state(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"V2故事状态模板：{args.output.resolve()}")
    elif args.command == "state-import":
        if not args.file.exists():
            raise SystemExit(f"状态文件不存在：{args.file}")
        try:
            bundle = json.loads(args.file.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as error:
            raise SystemExit(f"状态文件不是有效JSON：第{error.lineno}行第{error.colno}列") from error
        if not isinstance(bundle, dict):
            raise SystemExit("状态文件最外层必须是JSON对象")
        try:
            counts = state_store.import_bundle(args.novel_id, bundle)
        except (ValueError, TypeError) as error:
            raise SystemExit(f"状态导入失败：{error}") from error
        print("V2故事状态已写入：")
        for section, count in counts.items():
            print(f"  {section}: {count}")
    elif args.command == "state-show":
        bundle = state_store.export_bundle(args.novel_id)
        data: Any = bundle if args.section == "all" else bundle[args.section]
        rendered = json.dumps(data, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
            print(f"V2故事状态已导出：{args.output.resolve()}")
        else:
            print(rendered)
    elif args.command == "state-init":
        try:
            result = agent.initialize_story_state(
                args.novel_id,
                through_chapter=args.through_chapter,
                model=args.model,
            )
        except (DeepSeekError, ValueError) as error:
            raise SystemExit(f"V2故事状态初始化失败：{error}") from error
        output = args.output / f"novel_{args.novel_id}" / "v2_story_state.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result["state"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"V2故事状态初始化完成：读取 {result['chapter_count']} 章")
        for section, count in result["counts"].items():
            print(f"  {section}: {count}")
        print(f"状态文件：{output.resolve()}")
        print(f"查看命令：python -m novel_memory_agent.cli state-show {args.novel_id}")
    elif args.command == "clone-v2-db":
        try:
            result = database.clone_v2_experiment(
                args.novel_id,
                args.output_db,
                through_chapter=args.through_chapter,
            )
        except (ValueError, FileExistsError) as error:
            raise SystemExit(f"V2实验数据库创建失败：{error}") from error
        print(f"V2实验数据库：{result['target_path']}")
        print(f"正文：源库 {result['source_chapters']} 章 → 实验库 {result['target_chapters']} 章")
        print(f"完整剧本大纲：{result['outline_chapters']} 章")
        print(f"V1记忆：{result['memories']} 条｜历史API调用：{result['usage_calls']} 次")
        print("V2状态：")
        for section, count in result["state_counts"].items():
            print(f"  {section}: {count}")
    elif args.command == "state-rename-location":
        try:
            state_store.rename_location(
                args.novel_id,
                args.old_name,
                args.new_name,
                forbid_old=not args.allow_old_alias,
            )
        except ValueError as error:
            raise SystemExit(f"场景改名失败：{error}") from error
        print(f"场景已改名：{args.old_name} → {args.new_name}")
    elif args.command == "state-replace-location-reference":
        changed = state_store.replace_location_references(
            args.novel_id, args.old_name, args.new_name
        )
        print(f"场景引用迁移完成：{args.old_name} → {args.new_name}｜更新 {changed} 条状态")
    elif args.command == "run-book":
        if args.start <= 0 or args.end < args.start:
            raise SystemExit("章节范围无效")
        progress_path = args.output / f"novel_{args.novel_id}" / "book_progress.json"
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        for ordinal in range(args.start, args.end + 1):
            existing = next(
                (row for row in database.list_chapters(args.novel_id) if int(row["ordinal"]) == ordinal),
                None,
            )
            if existing:
                end_state_ids = {
                    int(item["chapter_id"])
                    for item in agent.story_states.export_bundle(args.novel_id)["chapter_end_states"]
                }
                if int(existing["id"]) not in end_state_ids:
                    outline = _find_by_ordinal(database.list_outline(args.novel_id), ordinal, "大纲章节")
                    accepted_draft = next(
                        (
                            row for row in database.list_drafts(args.novel_id)
                            if row["status"] == "accepted"
                            and row["outline_chapter_id"] == outline["id"]
                        ),
                        None,
                    )
                    if not accepted_draft:
                        raise SystemExit(f"第{ordinal}章已存在但缺少V2状态，且找不到对应已接收草稿。")
                    print(f"第{ordinal}章正文已存在但V2状态缺失，自动修复草稿 #{accepted_draft['id']}。")
                    try:
                        agent.accept_v2_draft(int(accepted_draft["id"]))
                    except (DeepSeekError, ValueError, BudgetExceededError) as error:
                        raise SystemExit(f"第{ordinal}章V2状态自动修复失败，进度已保留：{error}") from error
                print(f"第{ordinal}章已存在，跳过。")
                continue
            spent = float(database.usage_summary(args.novel_id)["cost_cny"])
            if spent >= args.max_cost:
                raise SystemExit(f"累计估算费用 {spent:.4f} 元已达到上限，停在第{ordinal}章之前。")
            outline = _find_by_ordinal(database.list_outline(args.novel_id), ordinal, "大纲章节")
            candidates = [
                row
                for row in database.list_drafts(args.novel_id)
                if row["status"] == "draft" and row["outline_chapter_id"] == outline["id"]
            ]
            draft = candidates[0] if candidates else None
            if not draft:
                try:
                    result = agent.generate_chapter(
                        args.novel_id,
                        outline["id"],
                        instruction=args.instruction,
                        target_chars=args.target_chars,
                    )
                except (DeepSeekError, BudgetExceededError) as error:
                    raise SystemExit(f"第{ordinal}章生成失败，进度已保留：{error}") from error
                _write_generation_files(args.output, args.novel_id, result)
                draft = database.get_draft(result.draft_id)
            continuity = json.loads(draft.get("continuity_json") or "{}")
            revisions = 0
            while not continuity.get("passed", False) and revisions < args.max_revisions:
                revisions += 1
                print(f"第{ordinal}章AI审核未通过，自动重写 {revisions}/{args.max_revisions}。")
                try:
                    result = agent.generate_chapter(
                        args.novel_id,
                        outline["id"],
                        instruction=_revision_instruction(args.instruction, continuity),
                        target_chars=args.target_chars,
                        replace_draft_id=int(draft["id"]),
                    )
                except (DeepSeekError, BudgetExceededError) as error:
                    raise SystemExit(f"第{ordinal}章自动重写失败，进度已保留：{error}") from error
                _write_generation_files(args.output, args.novel_id, result)
                draft = database.get_draft(result.draft_id)
                continuity = json.loads(draft.get("continuity_json") or "{}")
            if not continuity.get("passed", False):
                raise SystemExit(
                    f"第{ordinal}章连续{args.max_revisions}次重写仍未通过，草稿 #{draft['id']} 已保留。"
                )
            draft_id = int(draft["id"])
            print(f"第{ordinal}章草稿 #{draft_id} AI审核通过。")
            try:
                accepted = agent.accept_v2_draft(draft_id)
            except (DeepSeekError, ValueError, BudgetExceededError) as error:
                raise SystemExit(f"第{ordinal}章状态更新或写入失败，进度已保留：{error}") from error
            spent = float(database.usage_summary(args.novel_id)["cost_cny"])
            progress = {
                "novel_id": args.novel_id,
                "completed_through": ordinal,
                "target_end": args.end,
                "last_draft_id": draft_id,
                "last_chapter_id": accepted["chapter_id"],
            }
            progress_path.write_text(
                json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"第{ordinal}章完成。")
        print(f"整书任务完成到第{args.end}章。进度：{progress_path.resolve()}")
    elif args.command == "budget-set":
        try:
            database.update_novel_budget(args.novel_id, args.amount)
        except ValueError as error:
            raise SystemExit(f"预算修改失败：{error}") from error
        print(f"项目 #{args.novel_id} 预算停止线已调整为 {args.amount:.2f} 元。")


if __name__ == "__main__":
    main()
