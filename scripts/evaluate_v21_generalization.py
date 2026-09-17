from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import statistics
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUALITY_SKILL = PROJECT_ROOT / "skills" / "novel-quality-evaluator" / "scripts" / "quality_skill.py"
BASELINE_DIR = PROJECT_ROOT / "reports" / "baseline"
BASELINE_TOKEN_CSV = BASELINE_DIR / "chapter_token_metrics.csv"
BASELINE_SCORE_CSV = BASELINE_DIR / "chapter_score_comparison.csv"


def select_books(manifest: dict, stage: int) -> list[dict]:
    return [book for book in manifest["books"] if int(book["stage"]) <= stage]


def evaluation_dir(book: dict) -> Path:
    # quality_skill forwards --output to the CLI, whose evaluate-quality
    # command appends novel_<id>/quality_evaluation.
    return (
        Path(book["output"])
        / "quality_evaluation"
        / f"novel_{book.get('novel_id', 1)}"
        / "quality_evaluation"
    )


def evaluation_output_arg(book: dict) -> Path:
    return Path(book["output"]) / "quality_evaluation"


def completed_chapters(book: dict) -> int:
    folder = evaluation_dir(book) / "chapters"
    count = 0
    for ordinal in range(int(book["generation_start"]), int(book["generation_end"]) + 1):
        path = folder / f"chapter_{ordinal:03d}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            if int(value["chapter_id"]) == ordinal and 0 <= float(value["overall_score"]) <= 100:
                count += 1
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            pass
    return count


def evaluate(book: dict, model: str | None) -> int:
    command = [
        sys.executable, str(QUALITY_SKILL), "evaluate",
        "--project-root", str(PROJECT_ROOT),
        "--db", book["database"], "--novel-id", str(book.get("novel_id", 1)),
        "--reference", book["reference"], "--chapter-map", book["chapter_map"],
        "--start", str(book["generation_start"]), "--end", str(book["generation_end"]),
        "--output", str(evaluation_output_arg(book)),
    ]
    if model:
        command.extend(["--model", model])
    print(f"评分：{book['genre']} / {book['title']}", flush=True)
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


def usage(path: Path) -> dict:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0),
                      COALESCE(SUM(completion_tokens),0)
               FROM usage_logs"""
        ).fetchone()
    return {"api_calls": row[0], "prompt_tokens": row[1], "completion_tokens": row[2]}


PRODUCTION_TASKS = {
    "task_card", "task_card_json_retry", "draft_generation", "continuity_check",
    "continuity_check_json_retry", "v2_state_update", "v2_state_update_json_retry",
}


def production_cycles(path: Path) -> list[dict]:
    """Group production usage by each accepted draft's actual acceptance time.

    A failed/malformed state-update call is still logged, so treating every
    v2_state_update row as a chapter boundary can shift later chapters. Draft
    updated_at is the authoritative successful-acceptance boundary.
    """
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        calls = connection.execute(
            "SELECT * FROM usage_logs ORDER BY id"
        ).fetchall()
        drafts = connection.execute(
            """SELECT d.updated_at
               FROM drafts d JOIN outline_chapters o ON o.id=d.outline_chapter_id
               WHERE d.status='accepted' ORDER BY o.ordinal"""
        ).fetchall()
    production = [row for row in calls if row["task_type"] in PRODUCTION_TASKS]
    cycles, used_ids = [], set()
    for draft in drafts:
        current = [
            row for row in production
            if row["id"] not in used_ids and row["created_at"] <= draft["updated_at"]
        ]
        used_ids.update(row["id"] for row in current)
        cycles.append({
            "prompt_tokens": sum(int(row["prompt_tokens"]) for row in current),
            "completion_tokens": sum(int(row["completion_tokens"]) for row in current),
            "cache_hit_tokens": sum(int(row["cache_hit_tokens"]) for row in current),
            "api_calls": len(current),
            "rewrite_calls": max(0, sum(row["task_type"] == "draft_generation" for row in current) - 1),
        })
    return cycles


def slope(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    xs = list(range(len(values)))
    x_mean, y_mean = statistics.mean(xs), statistics.mean(values)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values)) / denominator


def quartiles(values: list[float]) -> tuple[float, float]:
    cuts = statistics.quantiles(values, n=4, method="inclusive")
    return cuts[0], cuts[2]


def write_trend_chart(relative: list[dict], output: Path, stage: int) -> Path | None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    xs = [row["relative_chapter"] for row in relative]
    position_labels = [f"续写{i}\n(本地第{x}章)" for i, x in enumerate(xs, 1)]
    medians = [row["token_median"] for row in relative]
    q1 = [row["token_q1"] for row in relative]
    q3 = [row["token_q3"] for row in relative]
    scores = [row["score_mean"] for row in relative]
    score_std = [row["score_std"] for row in relative]
    sample_books = relative[0]["books"] if relative else 0
    fig, axes = plt.subplots(2, 1, figsize=(10, 8))
    fig.subplots_adjust(left=0.10, right=0.97, top=0.94, bottom=0.12, hspace=0.42)
    axes[0].plot(xs, medians, marker="o", color="#2563eb", linewidth=2, label="完整生产周期Token中位数")
    axes[0].fill_between(xs, q1, q3, color="#93c5fd", alpha=0.4, label="第25—75百分位区间")
    genres = stage * 5
    axes[0].set(
        title=f"Stage {stage}（累计{genres}题材）续写位置生产Token趋势",
        xlabel="续写位置（括号内为本地章节编号）", ylabel="Token（含任务卡、生成、审核与状态更新）",
    )
    axes[0].set_xticks(xs, position_labels)
    axes[0].grid(alpha=0.25); axes[0].legend()
    axes[1].errorbar(
        xs, scores, yerr=score_std, marker="o", color="#059669", capsize=4,
        label=f"{sample_books}本同位置章节平均分（误差棒±1标准差）",
    )
    axes[1].set(
        title=f"Stage {stage}（累计{genres}题材）续写位置实验效果总分",
        xlabel="续写位置（括号内为本地章节编号）", ylabel="实验效果总分（0–100）", ylim=(70, 100),
    )
    axes[1].set_xticks(xs, position_labels)
    axes[1].grid(alpha=0.25); axes[1].legend()
    fig.text(
        0.5, 0.025,
        "实验效果总分＝10项V2.0一致性指标与1项原作剧情功能匹配分的等权平均",
        ha="center", fontsize=9, color="#475569",
    )
    path = output / "stage_trends.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def write_retrieval_comparison(chapter_rows: list[dict], output: Path, stage: int) -> tuple[Path, Path] | None:
    """Compare generalized chapters 5—10 with the retrieval baseline on matched metrics."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    with BASELINE_TOKEN_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        token_rows = [
            row for row in csv.DictReader(handle)
            if row["group"] == "检索上下文组" and 5 <= int(row["chapter"]) <= 10
        ]
    with BASELINE_SCORE_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        score_rows = [
            row for row in csv.DictReader(handle)
            if 5 <= int(row["chapter"]) <= 10
        ]

    xs = list(range(5, 11))
    positions = [f"续写{i}\n(本地第{x}章)" for i, x in enumerate(xs, 1)]
    generalized = []
    comparison_rows = []
    for ordinal in xs:
        subset = [row for row in chapter_rows if int(row["relative_chapter"]) == ordinal]
        input_tokens = [float(row["prompt_tokens"]) for row in subset if row["prompt_tokens"] is not None]
        scores = [float(row["consistency_score"]) for row in subset]
        q1, q3 = quartiles(input_tokens)
        generalized.append({
            "chapter": ordinal,
            "token_median": statistics.median(input_tokens), "token_q1": q1, "token_q3": q3,
            "score_mean": statistics.mean(scores), "score_std": statistics.pstdev(scores),
        })

    baseline_tokens = {int(row["chapter"]): float(row["input_tokens"]) for row in token_rows}
    baseline_scores = {int(row["chapter"]): float(row["retrieval_score"]) for row in score_rows}
    for row in generalized:
        chapter = row["chapter"]
        comparison_rows.append({
            "relative_chapter": chapter,
            "continuation_position": chapter - 4,
            "stage4_books": len([x for x in chapter_rows if int(x["relative_chapter"]) == chapter]),
            "stage4_input_token_median": round(row["token_median"], 3),
            "stage4_input_token_q1": round(row["token_q1"], 3),
            "stage4_input_token_q3": round(row["token_q3"], 3),
            "retrieval_baseline_input_tokens": baseline_tokens[chapter],
            "stage4_v20_score_mean": round(row["score_mean"], 3),
            "stage4_v20_score_std": round(row["score_std"], 3),
            "retrieval_baseline_v20_score": baseline_scores[chapter],
        })

    detail_path = output / "stage_vs_retrieval_comparison.csv"
    with detail_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison_rows[0]))
        writer.writeheader(); writer.writerows(comparison_rows)

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    medians = [row["token_median"] for row in generalized]
    q1s = [row["token_q1"] for row in generalized]
    q3s = [row["token_q3"] for row in generalized]
    generalized_scores = [row["score_mean"] for row in generalized]
    generalized_std = [row["score_std"] for row in generalized]

    fig, axes = plt.subplots(2, 1, figsize=(11, 9))
    fig.subplots_adjust(left=0.10, right=0.97, top=0.94, bottom=0.13, hspace=0.43)
    axes[0].plot(xs, medians, marker="o", linewidth=2.2, color="#2563eb", label="Stage 4：60本输入Token中位数")
    axes[0].fill_between(xs, q1s, q3s, color="#93c5fd", alpha=0.38, label="Stage 4：第25—75百分位区间")
    axes[0].plot(xs, [baseline_tokens[x] for x in xs], marker="s", linewidth=2.0, color="#dc2626", label="检索上下文基准：单书输入Token")
    axes[0].set(title="Stage 4 与检索上下文基准：每章输入Token对比", xlabel="续写位置（括号内为本地章节编号）", ylabel="输入Token")
    axes[0].set_xticks(xs, positions); axes[0].grid(alpha=0.25); axes[0].legend()

    axes[1].errorbar(xs, generalized_scores, yerr=generalized_std, marker="o", linewidth=2.2,
                     capsize=4, color="#059669", label="Stage 4：60本V2.0十项均分（误差棒±1标准差）")
    axes[1].plot(xs, [baseline_scores[x] for x in xs], marker="s", linewidth=2.0,
                 color="#7c3aed", label="检索上下文基准：单书V2.0十项评分")
    axes[1].set(title="Stage 4 与检索上下文基准：每章V2.0一致性评分对比", xlabel="续写位置（括号内为本地章节编号）", ylabel="V2.0十项一致性评分（0—100）", ylim=(70, 100))
    axes[1].set_xticks(xs, positions); axes[1].grid(alpha=0.25); axes[1].legend()
    fig.text(0.5, 0.025, "蓝/绿：Stage 4跨60本统计；红/紫：检索上下文单书基准。Token仅比较输入Token，评分仅比较V2.0十项一致性分。", ha="center", fontsize=9, color="#475569")
    chart_path = output / "stage_vs_retrieval_comparison.png"
    fig.savefig(chart_path, dpi=180)
    plt.close(fig)
    return chart_path, detail_path


def write_final_generalization_view(chapter_rows: list[dict], output: Path) -> tuple[Path, Path, Path] | None:
    """Create the final, simple Stage 4 view from all 60 books and 360 chapters."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    summary_rows = []
    for ordinal in range(5, 11):
        subset = [row for row in chapter_rows if int(row["relative_chapter"]) == ordinal]
        input_tokens = [float(row["prompt_tokens"]) for row in subset if row["prompt_tokens"] is not None]
        scores = [float(row["consistency_score"]) for row in subset]
        q1, q3 = quartiles(input_tokens)
        summary_rows.append({
            "continuation_position": ordinal - 4,
            "local_chapter": ordinal,
            "sample_chapters": len(subset),
            "input_token_median": round(statistics.median(input_tokens), 3),
            "input_token_q1": round(q1, 3),
            "input_token_q3": round(q3, 3),
            "v20_score_mean": round(statistics.mean(scores), 3),
            "v20_score_std": round(statistics.pstdev(scores), 3),
        })

    csv_path = output / "generalization_summary.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader(); writer.writerows(summary_rows)

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    xs = [row["continuation_position"] for row in summary_rows]
    labels = [f"续写{row['continuation_position']}\n(本地第{row['local_chapter']}章)" for row in summary_rows]

    token_medians = [row["input_token_median"] for row in summary_rows]
    token_q1 = [row["input_token_q1"] for row in summary_rows]
    token_q3 = [row["input_token_q3"] for row in summary_rows]
    fig, ax = plt.subplots(figsize=(11, 6.4))
    fig.subplots_adjust(left=0.10, right=0.97, top=0.88, bottom=0.20)
    ax.plot(xs, token_medians, marker="o", markersize=7, linewidth=2.4,
            color="#2563eb", label="60本同位置章节输入Token中位数")
    ax.fill_between(xs, token_q1, token_q3, color="#93c5fd", alpha=0.42,
                    label="第25—75百分位区间")
    for x, value in zip(xs, token_medians):
        ax.annotate(f"{value:,.0f}", (x, value), xytext=(0, 9),
                    textcoords="offset points", ha="center", fontsize=9, color="#1e3a8a")
    ax.set_title("20种题材60本小说：逐章输入Token趋势", fontsize=16, pad=14)
    ax.set_xlabel("续写位置（括号内为本地章节编号）")
    ax.set_ylabel("输入Token中位数")
    ax.set_xticks(xs, labels)
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left")
    final_change = (token_medians[-1] / token_medians[-2] - 1) * 100
    ax.text(0.99, 0.04, f"续写5→6变化：{final_change:+.2f}%\n末段基本稳定",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=10,
            bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#94a3b8"})
    fig.text(0.5, 0.035, "每个位置包含60章，共360章；Token为完整生产周期的输入Token，不含独立评分调用。",
             ha="center", fontsize=9, color="#475569")
    token_path = output / "generalization_token_trend.png"
    fig.savefig(token_path, dpi=180)
    plt.close(fig)

    score_means = [row["v20_score_mean"] for row in summary_rows]
    score_std = [row["v20_score_std"] for row in summary_rows]
    early_mean = statistics.mean(score_means[:3])
    late_mean = statistics.mean(score_means[3:])
    fig, ax = plt.subplots(figsize=(11, 6.4))
    fig.subplots_adjust(left=0.10, right=0.97, top=0.88, bottom=0.20)
    ax.errorbar(xs, score_means, yerr=score_std, marker="o", markersize=7,
                linewidth=2.4, capsize=5, color="#059669",
                label="60本同位置章节V2.0十项平均分（误差棒±1标准差）")
    for x, value in zip(xs, score_means):
        ax.annotate(f"{value:.2f}", (x, value), xytext=(0, 9),
                    textcoords="offset points", ha="center", fontsize=9, color="#065f46")
    ax.set_title("20种题材60本小说：逐章V2.0一致性评分", fontsize=16, pad=14)
    ax.set_xlabel("续写位置（括号内为本地章节编号）")
    ax.set_ylabel("V2.0十项一致性评分（0—100）")
    ax.set_xticks(xs, labels)
    ax.set_ylim(70, 100)
    ax.grid(alpha=0.25)
    ax.legend(loc="lower left")
    ax.text(0.99, 0.04,
            f"前3章均分：{early_mean:.2f}\n后3章均分：{late_mean:.2f}\n后期变化：{late_mean - early_mean:+.2f}",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=10,
            bbox={"boxstyle": "round,pad=0.40", "facecolor": "white", "edgecolor": "#94a3b8"})
    fig.text(0.5, 0.035, "每个位置包含60章，共360章；评分为V2.0十项一致性指标的等权平均。",
             ha="center", fontsize=9, color="#475569")
    score_path = output / "generalization_score_trend.png"
    fig.savefig(score_path, dpi=180)
    plt.close(fig)
    return token_path, score_path, csv_path


def summarize(books: list[dict], output: Path) -> tuple[Path, Path]:
    rows, chapter_rows = [], []
    for book in books:
        chapter_dir = evaluation_dir(book) / "chapters"
        chapter_scores = []
        cycles = production_cycles(Path(book["database"]))
        for ordinal in range(int(book["generation_start"]), int(book["generation_end"]) + 1):
            path = chapter_dir / f"chapter_{ordinal:03d}.json"
            if not path.is_file():
                continue
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            effect_score = float(value.get("experiment_effect_score") or value["overall_score"])
            chapter_scores.append(effect_score)
            cycle_index = ordinal - int(book["generation_start"])
            cycle = cycles[cycle_index] if cycle_index < len(cycles) else {}
            chapter_rows.append({
                "stage": book["stage"], "genre": book["genre"], "book_id": book["book_id"],
                "title": book["title"], "relative_chapter": ordinal,
                "prompt_tokens": cycle.get("prompt_tokens"),
                "completion_tokens": cycle.get("completion_tokens"),
                "total_tokens": (cycle.get("prompt_tokens", 0) + cycle.get("completion_tokens", 0)) if cycle else None,
                "cache_hit_tokens": cycle.get("cache_hit_tokens"),
                "production_api_calls": cycle.get("api_calls"), "rewrite_calls": cycle.get("rewrite_calls"),
                "consistency_score": float(value["overall_score"]),
                "reference_plot_function_score": value.get("reference_plot_function_score"),
                "experiment_effect_score": effect_score,
            })
        stats = usage(Path(book["database"]))
        rows.append({
            "stage": book["stage"], "genre": book["genre"], "book_id": book["book_id"],
            "title": book["title"], "scored_chapters": len(chapter_scores),
            "score_mean": round(statistics.mean(chapter_scores), 3) if chapter_scores else None,
            "score_min": round(min(chapter_scores), 3) if chapter_scores else None,
            "score_std": round(statistics.pstdev(chapter_scores), 3) if len(chapter_scores) > 1 else 0.0 if chapter_scores else None,
            **stats,
        })
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "book_metrics.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader(); writer.writerows(rows)
    chapter_csv = output / "chapter_metrics.csv"
    with chapter_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(chapter_rows[0]) if chapter_rows else [])
        if chapter_rows:
            writer.writeheader(); writer.writerows(chapter_rows)
    all_scores = [row["experiment_effect_score"] for row in chapter_rows]
    relative = []
    for ordinal in range(5, 11):
        subset = [row for row in chapter_rows if row["relative_chapter"] == ordinal]
        token_values = [float(row["total_tokens"]) for row in subset if row["total_tokens"] is not None]
        score_values = [float(row["experiment_effect_score"]) for row in subset]
        q1, q3 = quartiles(token_values) if len(token_values) >= 2 else (None, None)
        relative.append({
            "relative_chapter": ordinal, "books": len(subset),
            "token_median": round(statistics.median(token_values), 3) if token_values else None,
            "token_q1": round(q1, 3) if q1 is not None else None,
            "token_q3": round(q3, 3) if q3 is not None else None,
            "score_mean": round(statistics.mean(score_values), 3) if score_values else None,
            "score_std": round(statistics.pstdev(score_values), 3) if len(score_values) > 1 else None,
        })
    token_medians = [row["token_median"] for row in relative if row["token_median"] is not None]
    early_scores = [row["experiment_effect_score"] for row in chapter_rows if row["relative_chapter"] <= 7]
    late_scores = [row["experiment_effect_score"] for row in chapter_rows if row["relative_chapter"] >= 8]
    summary = {
        "books": len(books), "expected_chapters": len(books) * 6,
        "scored_chapters": len(all_scores),
        "score_mean": round(statistics.mean(all_scores), 3) if all_scores else None,
        "score_min": round(min(all_scores), 3) if all_scores else None,
        "score_std": round(statistics.pstdev(all_scores), 3) if len(all_scores) > 1 else None,
        "early_score_mean_ch5_7": round(statistics.mean(early_scores), 3) if early_scores else None,
        "early_score_std_ch5_7": round(statistics.pstdev(early_scores), 3) if len(early_scores) > 1 else None,
        "late_score_mean_ch8_10": round(statistics.mean(late_scores), 3) if late_scores else None,
        "late_score_std_ch8_10": round(statistics.pstdev(late_scores), 3) if len(late_scores) > 1 else None,
        "late_minus_early_score": round(statistics.mean(late_scores) - statistics.mean(early_scores), 3) if late_scores and early_scores else None,
        "token_median_slope_per_chapter": round(slope(token_medians), 3) if len(token_medians) > 1 else None,
        "relative_chapter_metrics": relative,
        "prompt_tokens": sum(row["prompt_tokens"] for row in rows),
        "completion_tokens": sum(row["completion_tokens"] for row in rows),
    }
    json_path = output / "stage_summary.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    stage = max((int(book["stage"]) for book in books), default=0)
    write_trend_chart(relative, output, stage)
    write_retrieval_comparison(chapter_rows, output, stage)
    if stage == 4 and len(books) == 60:
        write_final_generalization_view(chapter_rows, output)
    return csv_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="V2.1泛化实验跨书评分与汇总（支持章节级断点续跑）")
    parser.add_argument("command", choices=("status", "evaluate", "summarize"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--stage", type=int, choices=(1, 2, 3, 4), required=True)
    parser.add_argument("--model")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8-sig"))
    books = select_books(manifest, args.stage)
    if args.limit:
        books = books[:args.limit]
    if args.command == "status":
        done = sum(completed_chapters(book) for book in books)
        print(f"范围：{len(books)}本；已评分：{done}/{len(books) * 6}章")
        return 0
    if args.command == "evaluate":
        for index, book in enumerate(books, 1):
            if completed_chapters(book) == 6:
                print(f"已评分，跳过：{book['genre']} / {book['title']}")
                continue
            code = evaluate(book, args.model)
            if code:
                print(f"在第{index}/{len(books)}本停止；再次运行相同命令将从缺失章节续评。")
                return code
        print(f"评分完成：累计Stage {args.stage}，{len(books)}本。")
        return 0
    output = args.manifest.resolve().parent / "evaluation_summary" / f"stage_{args.stage:02d}"
    csv_path, json_path = summarize(books, output)
    print(f"逐书汇总：{csv_path}\n阶段汇总：{json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
