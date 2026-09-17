from __future__ import annotations

import csv, datetime as dt, json, sqlite3, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs_v2" / "双方案对比分析"
OUT.mkdir(parents=True, exist_ok=True)
CONFIG = {
    "检索上下文组": (ROOT / "data/novel_memory_v2_experiment.db", 25.92,
                    {"task_card":1,"draft_generation":1,"continuity_check":1,"v2_state_update":1}),
    "整书上下文组": (ROOT / "outputs_v2/整书上下文对照组/database/full_context_control.db", 62.84,
                    {"task_card":1,"draft_generation":1,"continuity_check":1}),
}

def peak_cost(r):
    return (r["cache_hit_tokens"]*.014+r["cache_miss_tokens"]*.44+r["completion_tokens"]*1.32)/1e6*7.2

def rows_for(path, actual):
    c=sqlite3.connect(path); c.row_factory=sqlite3.Row
    ends=[(r["ordinal"],dt.datetime.fromisoformat(r["created_at"])) for r in c.execute(
        "select ordinal,created_at from chapters where novel_id=1 and ordinal>=5 order by ordinal")]
    logs=[dict(r) for r in c.execute("select * from usage_logs where novel_id=1 order by created_at,id")]
    rows=[]; i=0
    for chapter,end in ends:
        part=[]
        while i<len(logs) and dt.datetime.fromisoformat(logs[i]["created_at"])<=end:
            part.append(logs[i]); i+=1
        counts={}
        for x in part: counts[x["task_type"]]=counts.get(x["task_type"],0)+1
        rows.append({"chapter":chapter,"calls":len(part),"input_tokens":sum(x["prompt_tokens"] for x in part),
          "cache_hit_tokens":sum(x["cache_hit_tokens"] for x in part),"cache_miss_tokens":sum(x["cache_miss_tokens"] for x in part),
          "output_tokens":sum(x["completion_tokens"] for x in part),"estimated_peak_cost":sum(peak_cost(x) for x in part),"counts":counts})
    scale=actual/sum(x["estimated_peak_cost"] for x in rows)
    for x in rows: x["actual_allocated_cost"]=x["estimated_peak_cost"]*scale
    return rows

def slope(rows,key):
    xs=[x["chapter"] for x in rows]; ys=[x[key] for x in rows]
    xm=statistics.mean(xs); ym=statistics.mean(ys)
    return sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/sum((x-xm)**2 for x in xs)

all_rows=[]; summary={}
for group,(path,actual,expected) in CONFIG.items():
    rows=rows_for(path,actual)
    clean=[x for x in rows if x["counts"]==expected]
    for x in rows: x["group"]=group; x["clean_first_pass"]=x in clean; all_rows.append(x)
    summary[group]={"chapters":len(rows),"calls":sum(x["calls"] for x in rows),
      "input_tokens":sum(x["input_tokens"] for x in rows),"output_tokens":sum(x["output_tokens"] for x in rows),
      "actual_cost":actual,"actual_cost_per_chapter":actual/len(rows),"clean_chapters":len(clean),
      "clean_rate":len(clean)/len(rows),"clean_input_slope_per_chapter":slope(clean,"input_tokens"),
      "clean_actual_cost_slope_per_chapter":slope(clean,"actual_allocated_cost")}

with (OUT/"chapter_cost_metrics.csv").open("w",newline="",encoding="utf-8-sig") as f:
    keys=["group","chapter","calls","input_tokens","cache_hit_tokens","cache_miss_tokens","output_tokens","estimated_peak_cost","actual_allocated_cost","clean_first_pass"]
    w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows({k:x[k] for k in keys} for x in all_rows)
(OUT/"comparison_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")

import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"]=["Microsoft YaHei","SimHei","DejaVu Sans"]
plt.rcParams["axes.unicode_minus"]=False
fig,axes=plt.subplots(1,2,figsize=(13,5.2))
colors={"检索上下文组":"#2563eb","整书上下文组":"#dc2626"}
for group in CONFIG:
    rr=[x for x in all_rows if x["group"]==group]
    clean=[x for x in rr if x["clean_first_pass"]]
    axes[0].scatter([x["chapter"] for x in clean],[x["actual_allocated_cost"] for x in clean],s=18,alpha=.65,label=group,color=colors[group])
    m=summary[group]["clean_actual_cost_slope_per_chapter"]; b=statistics.mean(x["actual_allocated_cost"] for x in clean)-m*statistics.mean(x["chapter"] for x in clean)
    axes[0].plot([5,65],[m*5+b,m*65+b],color=colors[group],linewidth=2)
    running=[]; total=0
    for x in rr: total+=x["actual_allocated_cost"];running.append(total)
    axes[1].plot([x["chapter"] for x in rr],running,label=group,color=colors[group],linewidth=2)
axes[0].set(title="一次通过章节：单章成本趋势",xlabel="章节",ylabel="后台实扣分摊（元/章）")
axes[1].set(title="累计实际费用趋势",xlabel="章节",ylabel="累计费用（元）")
for ax in axes: ax.grid(alpha=.2);ax.legend()
fig.tight_layout();fig.savefig(OUT/"cost_trend.png",dpi=180);plt.close(fig)
print(json.dumps(summary,ensure_ascii=False,indent=2))
