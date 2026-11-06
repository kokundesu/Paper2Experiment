# ReproSpec：统一的复现规格层

日期：2026-10-16。这一层替代此前讨论的"capsule 模式"。

## 1. 为什么加这一层

任务有三个来源，本质上回答的是同一个问题："要复现哪些结果、每个结果是什么类型、用什么证据证明"：

| 来源 | 规格怎么来 |
|---|---|
| demo：用户的 prompt | 意图阶段生成，经多供应商校验，由用户确认 |
| CORE-Bench | 确定性转换，不经过 LLM（oracle 规格） |
| 自建论文 case | 确定性转换（待迁移） |

执行层（A–D）和评分层只读 ReproSpec。如果每种来源都在每个版本里开一个分支，复杂度是"来源数 × 版本数"；加了这一层之后，每种来源只需要一个转换器。

## 2. 依据

| 设计点 | 依据 |
|---|---|
| 统一的问题和答案 schema | CORE-Bench（`report.json` 的键必须和问题完全匹配）；ReplicationBench（agent 填事先规定好的数值结构） |
| LLM 起草任务，人审定 | ReplicationBench Plus（LLM 生成、专家筛选）；EXP-Bench（多轮 LLM 抽取 + 执行检查 + 轻量人工审核） |
| 规格不清是主要的出错来源 | CORE-Bench 后续工作：Hard 级 45 题中有 3 题说明不足；SWE-bench Verified 筛掉描述不清的 issue |
| 规格不清时提问，不猜 | MAST 的"未请求澄清"失败类别 |
| 多供应商评审团 + 确定性汇总 | PoLL（Verga et al. 2024）；LLM 评审偏爱自己的输出（Panickssery et al. 2024） |
| 上下文隔离 | Anthropic 多 agent 研究系统 |
| 遮蔽答案 | ReplicationBench：不遮蔽时得分 0.19 → 0.46 |

## 3. 两条入口与对照实验

- **主实验（A–D 对比）**：只走确定性入口，规格已经给定。这样意图阶段的误差不会混进执行架构的比较。
- **附加实验**：只给 CORE-Bench 的 capsule 和一段不含问题的模糊 prompt，由意图阶段自己起草问题。测两个数：起草的问题和原题的匹配率，以及端到端成功率比 oracle 条件低多少。

## 4. 意图阶段（P3，待做）

1. **起草**：主 LLM 根据用户 prompt、论文文本、仓库的 README 和文件列表起草候选问题，不写任何数值。
2. **校验**：K 个其他供应商的模型各自独立地对每道候选题填一张固定清单（`in_scope`、`locator_ok`、`underspecified`、`answer_type_ok`、`measurable`），并补充漏掉的问题。
3. **汇总**：用代码完成。多数通过的题直接接受；只要有一家标了 `underspecified`，就进入澄清队列。
4. **澄清**：向用户提问，用户确认后冻结。

隔离要求：
- 意图阶段的 agent 看不到 GT。
- 各供应商的对话互相独立。
- 论文文本只当数据，不当指令。
- 规格冻结之后才进入 GT 阶段，GT 冻结之后才开始运行。
- 问题文本里不得出现 GT 数值。

## 5. 实施状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| P1 | `p2e/spec.py`：ReproSpec、Question、Answers、`answer_problems`、`brief`；CORE-Bench 转换器（`corebench.to_spec`、`export` 写 `spec.yaml` + `case.yaml`）；`corebench.finish` 改为接收 Answers | 完成，离线测试通过 |
| P2 | A（`SingleAgent`）和 C / C⁻ / D（`PlannerRuntime`）的 spec 模式。runtime 中 run 任务不再要求指标正则和训练过程；结束提议携带答案；闸门打开时，结束闸门调用 `corebench.provenance_problems` 检查每个答案的来源（不透露对错）；Planner 多一个 `read_log` 工具，唤醒消息附带运行输出的末尾。B 暂不支持 | 完成，离线测试通过 |
| P2 | 自建论文 case 迁移到 ReproSpec，统一评分器 | 待做 |
| P3 | 意图阶段 | 待做 |
| P4 | demo 前端 | 待做 |

运行命令：`p2e corebench run downloaded --workflow single planner planner_nogates planner_workers --model haiku55`。
