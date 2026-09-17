# V2.1 架构与版本边界

## 版本定义

- V2.0：检索上下文、结构化故事状态、机器审核、预算停止和断点续跑的可运行原型；65章单书实验与双方案报告均属于V2.0证据。
- V2.1：在不改变V2.0检索算法的前提下，将能力封装为可插拔Skill，增加标准入口、运行前检查和接入说明。
- V2.1评测：Skill封装完成后才开始。不得把V2.0单书数据标注成V2.1多书验证结果。

## 组件边界

基础 NovelMemory Agent 负责DeepSeek客户端、任务卡、草稿、机器审核、SQLite持久化和用量记录。本Skill负责编排初始化、上下文最小化、确认后状态更新、预算停止、断点恢复和评测。

数据集属于外部输入，不属于Skill包。API Key只通过环境变量或基础Agent的安全输入机制提供。

## 基础Agent接口

Skill期望基础Agent至少提供 `state-init`、`preview`、`generate`、`regenerate`、`accept`、`run-book`、`usage` 和 `evaluate`。
