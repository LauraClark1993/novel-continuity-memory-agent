from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def load_cost_rows(path: Path) -> dict[str, list[dict[str, float]]]:
    groups: dict[str, list[dict[str, float]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            groups[row["group"]].append(
                {
                    "chapter": int(row["chapter"]),
                    "input_tokens": int(row["input_tokens"]),
                }
            )
    for values in groups.values():
        values.sort(key=lambda item: item["chapter"])
    return groups


def configure_chinese_font(plt) -> None:
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS", "DejaVu Sans"
    ]
    plt.rcParams["axes.unicode_minus"] = False


def token_chart(groups: dict[str, list[dict[str, float]]], output: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    configure_chinese_font(plt)
    colors = {"检索上下文组": "#2563EB", "整书上下文组": "#DC2626"}
    fig, ax = plt.subplots(figsize=(13, 7), dpi=160)
    for group in ("检索上下文组", "整书上下文组"):
        rows = groups.get(group, [])
        if not rows:
            raise ValueError(f"缺少数据：{group}")
        ax.plot(
            [row["chapter"] for row in rows],
            [row["input_tokens"] for row in rows],
            label=group,
            color=colors[group],
            linewidth=1.8,
            alpha=0.9,
        )
    ax.set_title("整书上下文组与检索上下文组：逐章输入 Token 对比", fontsize=16, pad=16)
    ax.set_xlabel("章节")
    ax.set_ylabel("每章输入 Token（含生成、审核、重试等调用）")
    ax.set_xlim(5, 65)
    ax.set_xticks(range(5, 66, 5))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1000:.0f}K"))
    ax.grid(True, alpha=0.22)
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def load_score_rows(chapter_dir: Path) -> list[dict[str, float]]:
    rows = []
    for path in sorted(chapter_dir.glob("chapter_*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "chapter": int(value["chapter_id"]),
                "overall_score": float(value["overall_score"]),
            }
        )
    rows.sort(key=lambda item: item["chapter"])
    return rows


def score_chart(groups: dict[str, list[dict[str, float]]], output: Path) -> None:
    import matplotlib.pyplot as plt

    configure_chinese_font(plt)
    colors = {"检索上下文组": "#2563EB", "整书上下文组": "#DC2626"}
    fig, ax = plt.subplots(figsize=(13, 7), dpi=160)
    for group in ("检索上下文组", "整书上下文组"):
        rows = groups.get(group, [])
        if len(rows) != 61:
            raise ValueError(f"{group}评分数据应为61章，实际为{len(rows)}章")
        ax.plot(
            [row["chapter"] for row in rows],
            [row["overall_score"] for row in rows],
            label=group,
            color=colors[group],
            linewidth=1.8,
            alpha=0.9,
        )
    ax.set_title("整书上下文组与检索上下文组：逐章V2.0评分对比", fontsize=16, pad=16)
    ax.set_xlabel("章节")
    ax.set_ylabel("V2.0十项综合得分（0—100）")
    ax.set_xlim(5, 65)
    ax.set_xticks(range(5, 66, 5))
    ax.set_ylim(70, 100)
    ax.grid(True, alpha=0.22)
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def write_score_csv(groups: dict[str, list[dict[str, float]]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    by_group = {
        group: {int(row["chapter"]): row["overall_score"] for row in rows}
        for group, rows in groups.items()
    }
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["chapter", "retrieval_score", "full_context_score"])
        for chapter in range(5, 66):
            writer.writerow(
                [chapter, by_group["检索上下文组"][chapter], by_group["整书上下文组"][chapter]]
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="生成V2.1两组基准实验图表")
    parser.add_argument("--cost-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--retrieval-evaluation-dir", type=Path)
    parser.add_argument("--full-context-evaluation-dir", type=Path)
    args = parser.parse_args()
    token_output = args.output_dir / "chapter_input_token_comparison.png"
    token_chart(load_cost_rows(args.cost_csv), token_output)
    print(token_output.resolve())
    if args.retrieval_evaluation_dir and args.full_context_evaluation_dir:
        score_groups = {
            "检索上下文组": load_score_rows(args.retrieval_evaluation_dir / "chapters"),
            "整书上下文组": load_score_rows(args.full_context_evaluation_dir / "chapters"),
        }
        score_output = args.output_dir / "chapter_score_comparison.png"
        score_csv = args.output_dir / "chapter_score_comparison.csv"
        score_chart(score_groups, score_output)
        write_score_csv(score_groups, score_csv)
        print(score_output.resolve())
        print(score_csv.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
