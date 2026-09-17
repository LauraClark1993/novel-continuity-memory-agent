from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent import NovelAgent
from .deepseek import DeepSeekError, parse_json_response
from .parser import parse_manuscript
from .prompts import EXPERIMENT_EVALUATION_SYSTEM, EXPERIMENT_EVALUATION_USER

SCORE_KEYS = (
    "factual_consistency", "character_consistency", "state_consistency",
    "spatial_consistency", "temporal_consistency", "chapter_transition",
    "cross_chapter_causality", "foreshadowing_consistency", "outline_boundary",
    "narrative_pacing",
)
SCORE_LABELS = {
    "factual_consistency": "事实一致", "character_consistency": "人物一致",
    "state_consistency": "状态一致", "spatial_consistency": "空间一致",
    "temporal_consistency": "时间一致", "chapter_transition": "首尾衔接",
    "cross_chapter_causality": "跨章因果", "foreshadowing_consistency": "伏笔一致",
    "outline_boundary": "大纲边界", "narrative_pacing": "叙事节奏",
}


def _validate_result(
    value: dict[str, Any], *, chapter: int, has_reference: bool = True
) -> dict[str, Any]:
    scores = value.get("scores")
    if not isinstance(scores, dict):
        raise DeepSeekError(f"第{chapter}章实验评分缺少scores对象")
    normalized = {}
    for key in SCORE_KEYS:
        try:
            score = float(scores[key])
        except (KeyError, TypeError, ValueError) as error:
            raise DeepSeekError(f"第{chapter}章缺少有效评分：{key}") from error
        if not 0 <= score <= 100:
            raise DeepSeekError(f"第{chapter}章评分越界：{key}={score}")
        normalized[key] = score
    # The model occasionally invents a reference score even when the caller did
    # not supply original text.  Only retain this metric when a real reference
    # chapter was included in the request.
    reference_score = value.get("reference_plot_function_score") if has_reference else None
    if reference_score is not None:
        try:
            reference_score = float(reference_score)
        except (TypeError, ValueError) as error:
            raise DeepSeekError(f"第{chapter}章原作剧情功能分无效") from error
        if not 0 <= reference_score <= 100:
            raise DeepSeekError(f"第{chapter}章原作剧情功能分越界：{reference_score}")
    consistency_score = round(sum(normalized.values()) / len(SCORE_KEYS), 3)
    experiment_effect_score = (
        round((sum(normalized.values()) + reference_score) / (len(SCORE_KEYS) + 1), 3)
        if reference_score is not None else None
    )
    return {
        "scores": normalized,
        "overall_score": consistency_score,
        "reference_plot_function_score": reference_score,
        "experiment_effect_score": experiment_effect_score,
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    dimensions = {key: round(sum(item["scores"][key] for item in results) / count, 3) if count else 0.0 for key in SCORE_KEYS}
    reference_scores = [item["reference_plot_function_score"] for item in results if item.get("reference_plot_function_score") is not None]
    effect_scores = [item["experiment_effect_score"] for item in results if item.get("experiment_effect_score") is not None]
    return {
        "evaluated_chapters": count,
        "overall_score": round(sum(item["overall_score"] for item in results) / count, 3) if count else 0.0,
        "dimension_means": dimensions,
        "reference_compared_chapters": len(reference_scores),
        "reference_plot_function_score": round(sum(reference_scores) / len(reference_scores), 3) if reference_scores else None,
        "experiment_effect_score": round(sum(effect_scores) / len(effect_scores), 3) if effect_scores else None,
    }


def _report(novel_title: str, results: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    display_title = novel_title if novel_title.startswith("《") else f"《{novel_title}》"
    lines = [f"# {display_title}量化评分报告", "", "> 沿用V2.0评分口径，仅记录分数，不给出通过/失败结论，不提供修改建议，也不触发正文重写。", "", "## 整体分数", "", f"- 已评分章节：{summary['evaluated_chapters']}章", f"- AI一致性综合得分：{summary['overall_score']:.2f}/100"]
    if summary["experiment_effect_score"] is not None:
        lines.append(f"- 实验效果总分（含原作剧情功能）：{summary['experiment_effect_score']:.2f}/100")
    if summary["reference_plot_function_score"] is not None:
        lines.append(f"- 原作剧情功能匹配分：{summary['reference_plot_function_score']:.2f}/100")
    lines.extend(["", "| 指标 | 均分 |", "|---|---:|"])
    for key in SCORE_KEYS:
        lines.append(f"| {SCORE_LABELS[key]} | {summary['dimension_means'][key]:.2f} |")
    lines.extend(["", "## 分章数据", "", "| 章节 | V2.0一致性综合分 | 实验效果总分 | " + " | ".join(SCORE_LABELS[key] for key in SCORE_KEYS) + " | 原作剧情功能 |", "|---:|---:|---:|" + "---:|" * (len(SCORE_KEYS) + 1)])
    for item in results:
        scores = item["scores"]
        reference = item.get("reference_plot_function_score")
        values = " | ".join(f"{scores[key]:.2f}" for key in SCORE_KEYS)
        reference_display = f"{reference:.2f}" if reference is not None else "—"
        effect_display = f"{item['experiment_effect_score']:.2f}" if item.get("experiment_effect_score") is not None else "—"
        lines.append(f"| {item['chapter_id']} | {item['overall_score']:.2f} | {effect_display} | {values} | {reference_display} |")
    return "\n".join(lines) + "\n"


def run_quality_evaluation(agent: NovelAgent, novel_id: int, output_dir: Path, *, reference_path: Path | None = None, chapter_map_path: Path | None = None, start: int | None = None, end: int | None = None, model: str | None = None) -> tuple[Path, Path, dict[str, Any]]:
    novel = agent.database.get_novel(novel_id)
    if not novel:
        raise ValueError("小说项目不存在")
    reference_chapters = parse_manuscript(reference_path.read_text(encoding="utf-8-sig")) if reference_path else []
    chapter_map = json.loads(chapter_map_path.read_text(encoding="utf-8-sig")) if chapter_map_path else {}
    if not isinstance(chapter_map, dict):
        raise ValueError("章节映射文件最外层必须是JSON对象")
    drafts = []
    for draft in agent.database.list_drafts(novel_id):
        if draft["status"] != "accepted" or draft.get("outline_chapter_id") is None:
            continue
        outline = agent.database.get_outline_chapter(int(draft["outline_chapter_id"]))
        if not outline:
            continue
        ordinal = int(outline["ordinal"])
        if (start is None or ordinal >= start) and (end is None or ordinal <= end):
            drafts.append((ordinal, draft))
    drafts.sort(key=lambda item: item[0])
    if not drafts:
        raise ValueError("指定范围内没有已确认的生成草稿")
    chapter_dir = output_dir / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for ordinal, draft in drafts:
        chapter_path = chapter_dir / f"chapter_{ordinal:03d}.json"
        if chapter_path.is_file():
            try:
                cached = json.loads(chapter_path.read_text(encoding="utf-8-sig"))
                if (
                    int(cached.get("chapter_id", -1)) == ordinal
                    and int(cached.get("draft_id", -1)) == int(draft["id"])
                ):
                    cached = _validate_result(
                        cached,
                        chapter=ordinal,
                        has_reference=cached.get("reference_plot_function_score") is not None,
                    ) | {
                        "book_id": novel_id,
                        "chapter_id": ordinal,
                        "draft_id": int(draft["id"]),
                    }
                    results.append(cached)
                    continue
            except (OSError, ValueError, TypeError, KeyError, DeepSeekError, json.JSONDecodeError):
                pass
        mapping = chapter_map.get(str(ordinal), {})
        mapping = {"reference_index": mapping} if isinstance(mapping, int) else mapping
        mapping = mapping if isinstance(mapping, dict) else {}
        reference_index = int(mapping.get("reference_index", ordinal))
        reference_item = reference_chapters[reference_index - 1] if 1 <= reference_index <= len(reference_chapters) else None
        reference_text = f"{reference_item.title}\n\n{reference_item.content}" if reference_item else "未提供"
        response = agent._call(novel_id, "experiment_quality_scoring", [{"role": "system", "content": EXPERIMENT_EVALUATION_SYSTEM}, {"role": "user", "content": EXPERIMENT_EVALUATION_USER.format(chapter_ordinal=ordinal, task_card=draft.get("task_card_json") or "{}", context=draft.get("context_text", ""), candidate=draft.get("content", ""), reference=reference_text)}], model=model, max_tokens=800, json_mode=True, draft_id=int(draft["id"]))
        if response.finish_reason == "length":
            raise DeepSeekError(f"第{ordinal}章评分JSON被截断")
        result = _validate_result(
            parse_json_response(response.content),
            chapter=ordinal,
            has_reference=reference_item is not None,
        )
        result.update({"book_id": novel_id, "chapter_id": ordinal, "draft_id": int(draft["id"])})
        chapter_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
    summary = summarize_results(results)
    summary.update({"novel_id": novel_id, "novel_title": novel["title"]})
    summary_path, report_path = output_dir / "book_summary.json", output_dir / "quality_evaluation.md"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_report(novel["title"], results, summary), encoding="utf-8")
    return report_path, summary_path, summary
