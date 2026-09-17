from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from novel_memory_agent.webnovelbench import load_records, normalize_record


# Twenty mutually exclusive target genres.  Terms are intentionally concrete:
# they provide auditable evidence from the title and ten chapter summaries rather
# than relying on an LLM or silently treating an inferred label as ground truth.
GENRES = {
    "东方玄幻": ("武魂", "斗气", "灵气", "玄气", "武道", "天尊", "神王", "圣域", "宗门", "妖兽", "丹帝"),
    "仙侠修真": ("修真", "修仙", "仙门", "飞升", "渡劫", "灵根", "金丹", "元婴", "仙界", "道祖", "炼气"),
    "武侠江湖": ("武侠", "江湖", "侠客", "掌门", "武林", "剑客", "镖局", "少林", "丐帮", "门派"),
    "奇幻异界": ("魔法", "魔兽", "法师", "精灵", "兽人", "骑士", "教廷", "异界", "龙族", "亡灵", "炼金"),
    "都市生活": ("都市", "城市", "小区", "租房", "上班", "邻居", "饭店", "医院", "警局", "大学毕业"),
    "职场商战": ("公司", "集团", "董事长", "总经理", "收购", "上市", "股权", "商业", "创业", "投资", "谈判"),
    "校园青春": ("校园", "高中", "大学", "同学", "班主任", "宿舍", "高考", "校花", "学生会", "教室"),
    "娱乐明星": ("娱乐圈", "明星", "演员", "导演", "经纪人", "剧组", "电影", "演唱会", "粉丝", "综艺"),
    "历史争霸": ("争霸", "诸侯", "起兵", "征伐", "统一天下", "夺取城池", "王朝", "天下大乱", "割据", "称帝"),
    "架空历史": ("穿越", "重生古代", "架空", "朝代", "古代", "县令", "科举", "状元", "知府", "巡抚"),
    "宫廷权谋": ("皇帝", "皇后", "太后", "皇子", "朝堂", "宫廷", "后宫", "奏折", "丞相", "夺嫡", "权谋"),
    "古代言情": ("王妃", "侯府", "嫡女", "庶女", "世子", "郡主", "公主", "娘子", "婚约", "将军府"),
    "现代言情": ("男朋友", "女朋友", "恋爱", "暗恋", "告白", "约会", "前男友", "前女友", "相亲", "爱情"),
    "婚恋豪门": ("豪门", "总裁", "离婚", "结婚", "婚姻", "丈夫", "妻子", "未婚妻", "新娘", "婆婆"),
    "悬疑推理": ("悬疑", "推理", "侦探", "案件", "凶手", "线索", "调查真相", "破案", "嫌疑人", "刑警"),
    "灵异惊悚": ("灵异", "鬼魂", "厉鬼", "驱鬼", "阴阳", "僵尸", "闹鬼", "诅咒", "道士", "鬼怪"),
    "末世废土": ("末世", "废土", "丧尸", "变异生物", "灾变", "末日", "避难所", "幸存者", "废墟", "感染者"),
    "科幻未来": ("科幻", "星际", "宇宙", "飞船", "机甲", "外星", "未来世界", "机器人", "基因改造", "太空"),
    "游戏竞技": ("网游", "游戏", "玩家", "副本", "战队", "电竞", "服务器", "职业选手", "公会", "比赛地图"),
    "军事战争": ("军队", "战争", "战场", "军官", "士兵", "部队", "司令", "抗战", "军阀", "作战"),
}


def clean_title(title: str) -> str:
    match = re.search(r"《([^》]+)》", title)
    return match.group(1) if match else title.split("作者：", 1)[0]


def score_genres(title: str, summaries: str) -> tuple[str, int, int, list[str]] | None:
    ranked = []
    for genre, terms in GENRES.items():
        title_hits = [term for term in terms if term in title]
        summary_hits = [term for term in terms if term in summaries]
        score = len(title_hits) * 8 + sum(min(summaries.count(term), 4) for term in summary_hits)
        ranked.append((score, genre, title_hits, summary_hits))
    ranked.sort(reverse=True)
    best_score, best_genre, title_hits, summary_hits = ranked[0]
    second_score = ranked[1][0]
    evidence = list(dict.fromkeys(title_hits + summary_hits))
    # Require multiple independent content signals, or one explicit title signal.
    if best_score < 3 or (not title_hits and len(evidence) < 2):
        return None
    return best_genre, best_score, second_score, evidence[:8]


def main() -> int:
    parser = argparse.ArgumentParser(description="审计WebNovelBench对20种中文网文题材的支持度")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-chars", type=int, default=1000)
    parser.add_argument("--max-chars", type=int, default=8000)
    args = parser.parse_args()

    pools: dict[str, list[dict]] = defaultdict(list)
    base_valid = 0
    for index, record in enumerate(load_records(args.input), 1):
        sample = normalize_record(record, index, {})
        if sample is None or len(sample.chapters) != 10:
            continue
        if any(not chapter.summary for chapter in sample.chapters):
            continue
        lengths = [len(re.sub(r"\s+", "", chapter.content)) for chapter in sample.chapters]
        if min(lengths) < args.min_chars or max(lengths) > args.max_chars:
            continue
        if len({re.sub(r"\s+", "", chapter.content) for chapter in sample.chapters}) != 10:
            continue
        base_valid += 1
        title = clean_title(sample.title)
        summaries = "\n".join(chapter.summary for chapter in sample.chapters)
        match = score_genres(title, summaries)
        if match is None:
            continue
        genre, score, second_score, evidence = match
        pools[genre].append(
            {
                "source_id": sample.source_id,
                "title": sample.title,
                "author": sample.author,
                "score": score,
                "margin": score - second_score,
                "evidence": evidence,
            }
        )

    for values in pools.values():
        values.sort(key=lambda item: (item["score"], item["margin"], item["title"]), reverse=True)
    result = {
        "dataset_records": 4334,
        "base_valid_records": base_valid,
        "method": "书名与10章摘要的确定性关键词计分；每本只归入得分最高的一个主类；正式抽样仍需人工复核。",
        "minimum_books_required_per_genre": 3,
        "genres": {
            genre: {
                "candidate_count": len(pools[genre]),
                "supported": len(pools[genre]) >= 3,
                "top_candidates": pools[genre][:10],
            }
            for genre in GENRES
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "genre_support_audit.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# WebNovelBench二十种题材支持度审计",
        "",
        f"- 原始记录：4,334本",
        f"- 通过10章正文、摘要、字数与重复检查：{base_valid}本",
        "- 分类方法：书名与10章摘要的确定性关键词计分，每本只归入一个得分最高的主类。",
        "- 使用限制：这些是实验标签，不是数据集官方标签；正式入选的60本仍需人工复核。",
        "",
        "| 题材 | 候选数 | 至少3本 | 高分候选示例 |",
        "|---|---:|:---:|---|",
    ]
    for genre in GENRES:
        info = result["genres"][genre]
        examples = "、".join(item["title"] for item in info["top_candidates"][:3]) or "—"
        lines.append(f"| {genre} | {info['candidate_count']} | {'是' if info['supported'] else '否'} | {examples} |")
    md_path = args.output_dir / "genre_support_audit.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json_path.resolve())
    print(md_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
