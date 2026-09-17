from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .database import NovelDatabase
from .pricing import estimate_chinese_tokens


def build_evaluation(database: NovelDatabase, novel_id: int) -> tuple[str, dict[str, Any]]:
    novel = database.get_novel(novel_id)
    if not novel:
        raise ValueError("小说项目不存在")
    chapters = database.list_chapters(novel_id)
    drafts = [row for row in database.list_drafts(novel_id) if row["status"] == "accepted"]
    drafts.sort(key=lambda row: int(row["outline_chapter_id"] or 0))
    usage = database.list_usage(novel_id)
    repaired_draft_ids = {
        int(row["draft_id"])
        for row in usage
        if row["task_type"] == "draft_repair" and row.get("draft_id") is not None
    }

    comparisons = []
    for draft in drafts:
        outline = database.get_outline_chapter(draft["outline_chapter_id"])
        ordinal = int(outline["ordinal"]) if outline else 0
        prior_text = "\n\n".join(
            chapter["content"] for chapter in chapters if int(chapter["ordinal"]) < ordinal
        )
        outline_text = (outline["raw_text"] if outline else "") or ""
        baseline_tokens = estimate_chinese_tokens(prior_text + "\n" + outline_text)
        agent_tokens = estimate_chinese_tokens(draft["context_text"])
        saved = max(0, baseline_tokens - agent_tokens)
        continuity = json.loads(draft.get("continuity_json") or "{}")
        comparisons.append(
            {
                "draft_id": int(draft["id"]),
                "chapter": ordinal,
                "title": draft["title"],
                "baseline_tokens": baseline_tokens,
                "agent_tokens": agent_tokens,
                "saved_tokens": saved,
                "saving_rate": saved / baseline_tokens if baseline_tokens else 0.0,
                "passed": bool(continuity.get("passed")),
                "complete": (
                    int(draft["id"]) in repaired_draft_ids
                    or not any(
                        isinstance(item, dict) and item.get("status") == "partial"
                        for item in continuity.get("outline_completion", [])
                    )
                ),
            }
        )

    grouped: dict[str, dict[str, float]] = defaultdict(
        lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_cny": 0.0}
    )
    for row in usage:
        item = grouped[row["task_type"]]
        item["calls"] += 1
        item["prompt_tokens"] += int(row["prompt_tokens"])
        item["completion_tokens"] += int(row["completion_tokens"])
        item["cost_cny"] += float(row["cost_cny"])

    total_baseline = sum(item["baseline_tokens"] for item in comparisons)
    total_agent = sum(item["agent_tokens"] for item in comparisons)
    total_saved = max(0, total_baseline - total_agent)
    summary = database.usage_summary(novel_id)
    metrics = {
        "novel_id": novel_id,
        "accepted_generated_chapters": len(comparisons),
        "baseline_context_tokens": total_baseline,
        "agent_context_tokens": total_agent,
        "saved_context_tokens": total_saved,
        "context_saving_rate": total_saved / total_baseline if total_baseline else 0.0,
        "continuity_pass_rate": (
            sum(item["passed"] for item in comparisons) / len(comparisons) if comparisons else 0.0
        ),
        "completion_rate": (
            sum(item["complete"] for item in comparisons) / len(comparisons) if comparisons else 0.0
        ),
        "actual_calls": int(summary["calls"]),
        "actual_prompt_tokens": int(summary["prompt_tokens"]),
        "actual_completion_tokens": int(summary["completion_tokens"]),
        "actual_cost_cny": float(summary["cost_cny"]),
    }

    lines = [
        f"# 《{novel['title']}》MVP 效果验证报告",
        "",
        "## 核心结论",
        "",
        f"- 已确认生成章节：{metrics['accepted_generated_chapters']} 章",
        f"- 上下文模拟基线：{total_baseline:,} Token",
        f"- Agent 检索上下文：{total_agent:,} Token",
        f"- 上下文节省：{total_saved:,} Token（{metrics['context_saving_rate']:.1%}）",
        f"- 一致性检查通过率：{metrics['continuity_pass_rate']:.1%}",
        f"- 大纲完整率：{metrics['completion_rate']:.1%}",
        f"- 本项目截至当前 API 估算费用：{metrics['actual_cost_cny']:.4f} 元（最终实扣以DeepSeek后台为准）",
        "",
        "> 基线定义：每次创作都发送该章之前的全部正文，再附本章大纲。"
        "本报告的上下文对比不调用模型；估算费用包含分析、失败重试、修复和记忆更新等已取得usage的调用。",
        "",
        "## 分章上下文对比",
        "",
        "| 草稿 | 章节 | 全量正文基线 | Agent上下文 | 节省率 | 一致性 | 完整性 |",
        "|---:|---|---:|---:|---:|---|---|",
    ]
    for item in comparisons:
        lines.append(
            f"| {item['draft_id']} | {item['title']} | {item['baseline_tokens']:,} | "
            f"{item['agent_tokens']:,} | {item['saving_rate']:.1%} | "
            f"{'通过' if item['passed'] else '未通过'} | {'完整' if item['complete'] else '不完整'} |"
        )
    lines.extend(
        [
            "",
            "## API 用量构成",
            "",
            "| 任务类型 | 调用次数 | 输入Token | 输出Token | 估算费用（元） |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for task_type, item in sorted(grouped.items()):
        lines.append(
            f"| {task_type} | {int(item['calls'])} | {int(item['prompt_tokens']):,} | "
            f"{int(item['completion_tokens']):,} | {item['cost_cny']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## 当前验证边界",
            "",
            "- 上下文节省率是离线体积模拟，不等同于最终账单节省率。",
            "- 一致性通过率来自模型检查，需要结合作者人工验收。",
            "- 当前样本仅覆盖连续生成章节，后续应扩大到不同题材和更长正文。",
            "",
        ]
    )
    return "\n".join(lines), metrics


def write_evaluation(
    database: NovelDatabase, novel_id: int, output_dir: Path
) -> tuple[Path, Path, dict[str, Any]]:
    report, metrics = build_evaluation(database, novel_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "mvp_evaluation.md"
    metrics_path = output_dir / "mvp_metrics.json"
    report_path.write_text(report, encoding="utf-8")
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path, metrics_path, metrics
