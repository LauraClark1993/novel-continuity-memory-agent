# 运行、恢复与评测

## 首次接入

```powershell
python .\skills\novel-continuity-memory\scripts\novel_skill.py create --db data\novel_001.db --title "小说名称"
python .\skills\novel-continuity-memory\scripts\novel_skill.py import --db data\novel_001.db --novel-id 1 --manuscript dataset\novel_001\initial_chapters.md --outline dataset\novel_001\outline.md
python .\skills\novel-continuity-memory\scripts\novel_skill.py doctor --db data\novel.db --novel-id 1
python .\skills\novel-continuity-memory\scripts\novel_skill.py state-init --db data\novel.db --novel-id 1 --through-chapter 4 --output outputs_v2
python .\skills\novel-continuity-memory\scripts\novel_skill.py preview --db data\novel.db --novel-id 1 --outline 5 --output outputs_v2
```

`create`必须使用一个新的数据库路径。导入后先运行`doctor`核对小说标题和前置章节数量，再调用会产生费用的`state-init`。

## 整书运行与断点恢复

```powershell
python .\skills\novel-continuity-memory\scripts\novel_skill.py run-book --db data\novel.db --novel-id 1 --start 5 --end 65 --target-chars 3000 --max-revisions 2 --output outputs_v2 --instruction "遵循任务卡和状态库，不提前发生后续剧情。"
```

同一命令可用于恢复；运行器跳过已确认章节，从断点继续。提高预算后可以续跑，但不得删除历史用量。

## 评测口径

至少报告后台实际费用、估算费用、输入与输出Token、缓存命中、单章成本、重写率、失败类型、标题与长度合规、人物一致性、地点一致性、章节衔接和跨章因果。后台只有整批实扣时，可按逐章Token权重分摊用于趋势图，但必须标注为“校准分摊”，不能称为逐章实扣。
