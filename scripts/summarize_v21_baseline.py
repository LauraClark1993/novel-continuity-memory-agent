from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


LABELS = {
    "retrieval": "检索上下文组",
    "full_context": "整书上下文组",
}


def linear_slope(xs: list[float], ys: list[float]) -> float:
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator


def load_costs(path: Path) -> dict[str, list[dict[str, float]]]:
    groups: dict[str, list[dict[str, float]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            groups[raw["group"]].append(
                {
                    "chapter": int(raw["chapter"]),
                    "calls": int(raw["calls"]),
                    "input_tokens": int(raw["input_tokens"]),
                    "output_tokens": int(raw["output_tokens"]),
                    "actual_allocated_cost": float(raw["actual_allocated_cost"]),
                }
            )
    return groups


def load_scores(path: Path) -> list[dict[str, float]]:
    rows = []
    for file_path in sorted((path / "chapters").glob("chapter_*.json")):
        value = json.loads(file_path.read_text(encoding="utf-8"))
        rows.append(
            {"chapter": int(value["chapter_id"]), "score": float(value["overall_score"])}
        )
    return rows


def group_metrics(cost_rows: list[dict[str, float]], score_rows: list[dict[str, float]]) -> dict:
    cost_rows.sort(key=lambda row: row["chapter"])
    score_rows.sort(key=lambda row: row["chapter"])
    if [row["chapter"] for row in cost_rows] != list(range(5, 66)):
        raise ValueError("成本数据章节范围不是5—65章")
    if [row["chapter"] for row in score_rows] != list(range(5, 66)):
        raise ValueError("评分数据章节范围不是5—65章")

    chapters = [float(row["chapter"]) for row in cost_rows]
    inputs = [row["input_tokens"] for row in cost_rows]
    costs = [row["actual_allocated_cost"] for row in cost_rows]
    scores = [row["score"] for row in score_rows]
    late_scores = [row["score"] for row in score_rows if row["chapter"] >= 46]
    early_scores = [row["score"] for row in score_rows if row["chapter"] <= 24]

    return {
        "chapters": len(cost_rows),
        "api_calls": sum(row["calls"] for row in cost_rows),
        "input_tokens": sum(inputs),
        "output_tokens": sum(row["output_tokens"] for row in cost_rows),
        "total_tokens": sum(row["input_tokens"] + row["output_tokens"] for row in cost_rows),
        "backend_actual_cost_yuan": round(sum(costs), 4),
        "actual_cost_per_chapter_yuan": round(statistics.fmean(costs), 4),
        "input_token_slope_per_chapter": round(linear_slope(chapters, inputs), 3),
        "allocated_cost_slope_yuan_per_chapter": round(linear_slope(chapters, costs), 6),
        "score_mean": round(statistics.fmean(scores), 3),
        "score_min": round(min(scores), 3),
        "score_max": round(max(scores), 3),
        "score_population_std": round(statistics.pstdev(scores), 3),
        "late_score_mean_ch46_65": round(statistics.fmean(late_scores), 3),
        "late_score_population_std_ch46_65": round(statistics.pstdev(late_scores), 3),
        "early_score_mean_ch5_24": round(statistics.fmean(early_scores), 3),
        "early_to_late_score_change": round(
            statistics.fmean(late_scores) - statistics.fmean(early_scores), 3
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="汇总V2.1两组基准实验指标")
    parser.add_argument("--cost-csv", type=Path, required=True)
    parser.add_argument("--retrieval-evaluation-dir", type=Path, required=True)
    parser.add_argument("--full-context-evaluation-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    costs = load_costs(args.cost_csv)
    groups = {
        "retrieval": group_metrics(
            costs["检索上下文组"], load_scores(args.retrieval_evaluation_dir)
        ),
        "full_context": group_metrics(
            costs["整书上下文组"], load_scores(args.full_context_evaluation_dir)
        ),
    }
    retrieval = groups["retrieval"]
    full = groups["full_context"]
    comparison = {
        "full_context_cost_multiple": round(
            full["backend_actual_cost_yuan"] / retrieval["backend_actual_cost_yuan"], 3
        ),
        "full_context_extra_cost_yuan": round(
            full["backend_actual_cost_yuan"] - retrieval["backend_actual_cost_yuan"], 4
        ),
        "full_context_extra_cost_per_chapter_yuan": round(
            full["actual_cost_per_chapter_yuan"] - retrieval["actual_cost_per_chapter_yuan"], 4
        ),
        "input_token_slope_gap_per_chapter": round(
            full["input_token_slope_per_chapter"] - retrieval["input_token_slope_per_chapter"], 3
        ),
        "allocated_cost_slope_gap_yuan_per_chapter": round(
            full["allocated_cost_slope_yuan_per_chapter"]
            - retrieval["allocated_cost_slope_yuan_per_chapter"],
            6,
        ),
        "retrieval_score_advantage": round(
            retrieval["score_mean"] - full["score_mean"], 3
        ),
        "retrieval_std_reduction": round(
            full["score_population_std"] - retrieval["score_population_std"], 3
        ),
        "retrieval_late_std_reduction": round(
            full["late_score_population_std_ch46_65"]
            - retrieval["late_score_population_std_ch46_65"],
            3,
        ),
    }
    result = {
        "measurement_notes": {
            "token": "逐章API usage精确值，包含生成、审核与重试调用。",
            "cost": "总费用采用DeepSeek后台实际金额；逐章费用按API调用估算占比分摊，因此逐章费用斜率为估算值。",
            "late_stage": "后期稳定性定义为第46—65章V2.0十项综合分的总体标准差。",
        },
        "groups": groups,
        "comparison": comparison,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
