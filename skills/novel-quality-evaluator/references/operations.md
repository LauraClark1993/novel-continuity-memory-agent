# 操作说明

在项目根目录运行：

```powershell
python ".\skills\novel-quality-evaluator\scripts\quality_skill.py" doctor `
  --db "data\experiment.db" --novel-id 1
```

提供原作第5—10章作为评估参考时：

```powershell
python ".\skills\novel-quality-evaluator\scripts\quality_skill.py" evaluate `
  --db "data\experiment.db" --novel-id 1 --start 5 --end 10 `
  --reference "datasets\book_001\reference_chapters.md" `
  --chapter-map "datasets\book_001\chapter_map.json" `
  --output "outputs_webnovelbench"
```

不提供原作时省略`--reference`。输出位于`<output>/novel_<id>/quality_evaluation/`：

- `quality_evaluation.md`：面向阅读的逐章与整书报告。
- `book_summary.json`：用于50本跨书汇总的指标。
- `chapters/chapter_XXX.json`：逐章评分、问题证据和未确认疑点。

该命令会产生新的评估API费用，但不会修改或重写任何章节。

WebNovelBench抽到原书中段时，`chapter_map.json`使用下面的格式。`reference_index`是该章在参考文件中的顺序，`source_chapter`保留原书真实章节号：

```json
{
  "5": {"reference_index": 5, "source_chapter": "1502"},
  "6": {"reference_index": 6, "source_chapter": "1503"},
  "7": {"reference_index": 7, "source_chapter": "1504"},
  "8": {"reference_index": 8, "source_chapter": "1505"},
  "9": {"reference_index": 9, "source_chapter": "1506"},
  "10": {"reference_index": 10, "source_chapter": "1507"}
}
```

如果参考文件只保存原作后6章，则把`reference_index`改为1至6，但`source_chapter`仍填写真实章节号。
