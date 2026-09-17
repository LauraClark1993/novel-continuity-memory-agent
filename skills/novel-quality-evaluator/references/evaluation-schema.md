# V2.0量化评分规范

沿用V2.0数据集评测计划的十项一致性指标，每项0至100分，综合分取十项算术平均。

| 字段 | 含义 |
|---|---|
| `factual_consistency` | 身份、关系、经历、物品和已发生事件无冲突 |
| `character_consistency` | 动机、性格、语言、能力和知情范围合理 |
| `state_consistency` | 身体、情绪、物品持有和关系变化得到延续 |
| `spatial_consistency` | 地点名称、方位、归属、距离和移动路径正确 |
| `temporal_consistency` | 日期、时辰、持续时间和事件先后合理 |
| `chapter_transition` | 上一章末态被下一章首段准确承接 |
| `cross_chapter_causality` | 事件由上游原因自然引发并产生后续影响 |
| `foreshadowing_consistency` | 伏笔被保留，没有错误回收或提前泄露 |
| `outline_boundary` | 完成目标事件，没有遗漏或提前写后续剧情 |
| `narrative_pacing` | 重点情节篇幅、冲突升级和章节密度合理 |

分数锚点：90至100稳定优秀；80至89整体良好；70至79基本成立但有明显不足；60至69多处问题影响阅读；0至59基本不可用。这些锚点仅用于裁判统一尺度，报告不输出质量等级或通过/失败。

提供原作时额外记录0至100分的`reference_plot_function_score`，只衡量核心剧情功能是否相近，合理改写不扣分。该项不改变V2.0十项一致性综合分，但会与十项一致性指标等权计算新增的`experiment_effect_score`，即十一项算术平均。

评估器只输出分数，不输出问题、严重度、评价或修改建议。分数不触发重写、状态回滚或正文修改。
