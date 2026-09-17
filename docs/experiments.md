# 实验数据与复现说明

## 实验一：上下文方案对照

实验在同一小说、相同基础Agent、相同生成范围和相同评分器下，对比两种方案：

- 整书上下文：每章携带此前累计的完整正文。
- 检索上下文：每章只检索任务相关的结构化状态、记忆和必要前文。

两组各生成第5—65章，共122章。报告使用逐次API usage统计生产Token，并使用V2.0十项一致性评分器逐章评分。

公开结果位于`reports/baseline/`。仓库只保留聚合指标和图表，不包含实验小说正文与数据库。

## 实验二：多题材泛化

实验覆盖20种题材、60本小说。每本使用前4章与本地大纲初始化独立状态库，生成本地第5—10章，共360章。

最终简化分析将60本书的相同续写位置汇总：

- Token使用跨60本的输入Token中位数与第25—75百分位区间。
- 质量使用跨60本的V2.0十项一致性评分均值与标准差。
- 每个续写位置包含60章，六个位置合计360章。

公开结果位于`reports/generalization/`。

## 数据准备

原始数据来自[WebNovelBench](https://github.com/OedonLestrange42/webnovelbench)，许可为CC BY-NC-SA 4.0。本仓库不分发原始小说数据。请自行下载并在本地准备以下私有输入：

```text
private_data/
└─ book_001/
   ├─ initial_4_chapters.md
   ├─ local_outline.md
   ├─ reference_chapters.md
   └─ chapter_map.json
```

复制`configs/experiment_manifest.example.json`并改为`experiment_manifest.json`，填写本机相对路径。该文件默认被`.gitignore`排除。

## 运行

初始化独立数据库：

```powershell
python ".\scripts\run_v21_generalization.py" init `
  --manifest ".\configs\experiment_manifest.json" `
  --stage 1
```

生成章节：

```powershell
python ".\scripts\run_v21_generalization.py" run `
  --manifest ".\configs\experiment_manifest.json" `
  --stage 1 `
  --target-chars 3000 `
  --max-revisions 2
```

评分并汇总：

```powershell
python ".\scripts\evaluate_v21_generalization.py" evaluate `
  --manifest ".\configs\experiment_manifest.json" `
  --stage 1

python ".\scripts\evaluate_v21_generalization.py" summarize `
  --manifest ".\configs\experiment_manifest.json" `
  --stage 1
```

## 公开与私有边界

可以公开：代码、测试、聚合CSV、统计图和技术报告。

不应公开：API Key、原始小说、生成正文、数据库、调用日志、含本机绝对路径的实验清单。

