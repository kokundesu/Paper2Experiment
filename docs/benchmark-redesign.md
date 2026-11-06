# Benchmark 重新设计（草案，待审阅）

日期：2026-10-16。本文对比 13 个论文复现类 benchmark，再据此给出 Paper2Exp 的 benchmark 新方案，最后列出需要你决定的事项。所有内容都还没有实现。

## 1. 现有 benchmark 怎么做

### 1.1 总表

| Benchmark | 任务单位 | Ground truth 来源 | 判对规则 | 防泄漏 | 重复与统计 |
|---|---|---|---|---|---|
| PaperBench | 20 篇 ICML 2024 论文 | 和作者共建的 rubric 树 | LLM judge 按叶节点打分 | 禁用作者代码；`reproduce.sh` 在新容器里重跑 | 有限重复 |
| AutoReproduce / ReproduceBench | 13 篇论文 | 官方代码的运行结果 | 与官方结果的平均差距（22.1%） | 未见明确说明 | 未见 |
| CORE-Bench | 仓库 + 问题 | 人工重跑 3 次 | 落在 95% 预测区间内；`report.json` 键必须完全匹配；每题全对才算 | 屏蔽 CodeOcean 域名；v1.1 删除预置结果 | pass@1、pass^k、Wilson CI |
| SUPER | 仓库任务（已缩小） | 专家方案在自己的环境里复跑 | 绝对误差 10⁻² | 固定 seed，缩小规模 | landmark 给部分分 |
| CSR-Bench | 仓库部署 | 无数值 GT | LLM 判断命令是否成功 | — | — |
| REPRO-Bench | 112 篇社科论文 | 专家复现报告人工标注（1–4 分） | 完全匹配 | 不给 agent 看标签分布 | 无重复 |
| SciReplicate-Bench | NLP 论文中的算法 | 参考实现 + 测试 | 执行正确率 | 未见 | — |
| LMR-Bench | 论文中的函数 | 3 位专家/篇 + 单元测试 | 单测 + LLM 代码评审（一致率仅 62.5%） | — | — |
| ResearchCodeBench | 20 篇论文的代码片段 | 参考代码 + 测试 | 单测通过 | 13 篇在 cutoff 之后，模型在这部分全部更差 | — |
| EXP-Bench | 论文实验 | 多轮 LLM 抽取 + 执行检查 + 人工轻审（约 20 分钟/篇） | 多项条件联合判定 | — | — |
| MLRC-Bench | 7 个竞赛任务 | 官方 baseline 和人类第一名（必要时重跑） | 缩小与人类第一名差距的比例 | 测试集不可见，只用 dev 分数选择 | best-of-8，无误差条 |
| RE-Bench | 7 个人工设计的环境 | 隐藏参考方案 + 71 次专家尝试 | 归一化分数 | 自动规则检查 + 人工检查排名靠前的运行 | score@k，bootstrap CI |
| ReplicationBench | 20 篇天体物理论文、111 个任务 | 论文数值，作者写任务 | 作者事先给出的 ±容差；一个任务内全对才算 | 遮蔽论文中的目标数字；无计算基线；LLM 监控造假 | mean ± std、best-of-N |

### 1.2 七个共同结论

**1. Ground truth 要用重跑核实，不能直接抄论文。** CORE-Bench 的后续工作检查了 Hard 级的 45 个任务，其中 15 个有问题：1 个答案错误、3 个说明不足、7 个评分问题（四舍五入，或者同一个值出现在多处）、4 个无法完成。MLRC 换了测试划分后，会重跑人类第一名的方案；SUPER 也在自己的环境里复跑。REPRO-Bench 更直接：112 篇里有 56 篇已知存在复现问题。我们在 DLinear、KalmanNet 和 Deep SVDD 上看到的系统性差距属于同一种情况。

**2. 容差来自精度和实测噪声，并且在跑 agent 之前定好。** 两种做法：

- CORE-Bench：先四舍五入到论文的小数位；对不上，就再跑 2 次，用 t 分布的 95% 预测区间判定，区间为 mean ± t·s·√(1+1/n)。
- ReplicationBench：作者为每个值单独给容差，并写明理由；拿不准时宁可偏紧。

此外，CORE-Bench 在挑题阶段就排除了波动大的题，181 题里最后只有 17 题是随机的。

**3. Agent 能拿到答案，就会抄答案。** 有三个实例：

- ReplicationBench 不遮蔽论文时，Sonnet 3.7 从 0.19 涨到 0.46，作者认为这说明的是"倾向于抄"，不是能力。
- CORE-Bench 的 agent 在数据链接坏掉时，上网搜出论文的数值直接提交。
- CORE-Bench Hard 有 20/45 个任务可以直接从仓库自带的结果文件里读出答案。

**4. Agent 可能伪造证据。** RE-Bench 中，o1-preview 复制了参考权重，并计划"输出看起来像在训练的日志"。证据只能由 harness 记录，不能由 agent 写。

**5. 不用 LLM 做主评分。** LMR-Bench 的 LLM 评审和人类只有 62.5% 一致；MLRC 中 LLM 打的"创新性"分和实际效果的相关系数是 −0.06。ReplicationBench 和 CORE-Bench 仍然用 LLM 做监控，但只负责标记可疑运行，交给人看。

**6. 噪声会抬高 best-of-k。** RE-Bench 最好的一次 GPT-2 运行得分 0.88，重跑只有 0.69；ReplicationBench 的 best-of-N 是 0.39，mean 只有 0.22。CORE-Bench Hard 的 pass@3 是 31.1%，pass^3 只有 8.89%。CORE-Bench 的后续工作还发现，仅仅换一个 Codex CLI 版本，准确率就变了约 40%。

**7. 格式失败会掩盖真实能力，要单独报告。** REPRO-Bench 的 baseline 中，提交文件有效的比例只有 46–61%；只是让 agent 先写一个占位分数，这个比例就升到 92.9%。另一方面，CORE-Bench 换成更宽松的评分后，同一批运行从 77.78% 变成 95.5%，可见评分规则本身就是误差来源。

## 2. 对照我们现在的做法

| 方面 | 现在（v3 的 5 个 case） | 文献给的做法 | 差距 |
|---|---|---|---|
| GT 来源 | 人读论文数字 | 论文数字 + 自己重跑核实 | **大**：CPU 和论文硬件不同，论文本身也可能不对 |
| 容差 | 统一规则（±0.5pp、±1pp、按报告的 std） | 精度和重跑噪声取较大者，事先登记，附理由 | 中：非百分比指标和没有 spread 的指标缺规则 |
| 高波动 claim | 照收 | 挑题阶段排除或单独标注 | 中 |
| 答案格式 | `metrics.json` + 证据正则 | 键严格匹配，单独报告有效提交率 | 小 |
| 证据 | sandbox 日志 + sha256 | 只信 harness 记录；可在新 sandbox 重跑最终命令 | 小：已经做对大半 |
| 论文里的答案 | agent 能看到全文 | 遮蔽目标数字，或者测量抄写率 | **大** |
| 仓库自带结果 | 没处理 | 删除，或者要求数值能追溯到本次运行的日志 | 中：证据检查已部分覆盖 |
| 网络 | 不限 | 屏蔽结果来源（论文网页、CodeOcean 等） | 中 |
| 选题时间 | 不限 | 选模型 cutoff 之后的论文 | 中 |
| 统计 | 成功率 | pass@1、pass^k、Wilson CI、cost per success | 中 |

## 3. 新方案

### 3.1 选题标准

每篇论文必须同时满足：

1. **在被测模型的知识 cutoff 之后发表**，学 ResearchCodeBench。旧论文可以留作对照子集，用来观察记忆效应。
2. **有官方代码**，并且能在 CPU 上跑完：单次运行不超过约 30 分钟，可以像 SUPER 那样缩小规模，前提是缩小后的设置写进 task。
3. **至少有 2 个数值 claim**，而且都能从同一套代码得到。
4. **重跑波动小**：参考重跑的变异系数超过阈值的 claim 不收，或者标为 stochastic 单独统计。

### 3.2 两层 ground truth

这一节是方案的核心改动。每个 claim 存两个值：

| 字段 | 来源 | 用途 |
|---|---|---|
| `paper_value` | 论文原文，带页码和引文 | 报告 agent 结果和论文的差距；判断论文能否复现 |
| `reference` | 构建 case 时，用官方代码在**同一个 CPU sandbox** 里按 task 规定的设置跑 n=5 个 seed | **主评分目标** |

为什么主评分用 `reference`：我们要测的是"agent 能不能把这篇论文的实验跑对"。官方代码在我们硬件上跑出来的值，正是"跑对了"的定义。论文值和这个值之间的差距，属于论文或硬件，不该算在 agent 头上。Deep SVDD 那种系统性差距，在这个设计下变成一个有用的测试：agent 应该报告"跑出来是 X，和论文差 Y"，而不是往论文的数字上凑。

代价是：每个 case 都要多做一次参考重跑，耗费 CPU 时间。参考重跑由构建脚本按固定命令执行，不经过任何被测 agent，结果写进隐藏的 `case.yaml`。

参考重跑和论文值差距很大的 claim 不删除，标为 `paper_mismatch`。这正好对应 REPRO-Bench 刻意混入不可复现论文的做法，可以检验 agent 会不会为了凑数而作假。

### 3.3 容差规则（已确认，2026-10-16）

#### 公式

```
通过条件： |agent 值 − ref_mean| ≤ h

h = max( 噪声项 , 精度项 , 数值下限 )

  噪声项   = t(0.975, n−1) · s · √(1/m + 1/n)
             n = 参考重跑次数，s = 参考重跑的标准差（ddof=1）
             m = agent 计入均值的 seed 数
  精度项   = max(论文报告精度的半个单位, 官方代码打印精度的半个单位)
  数值下限 = 1e-5 · |ref_mean|；ref_mean 为 0 时取 1e-8
```

参数：

| 参数 | 取值 | 理由 |
|---|---|---|
| 参考重跑次数 n | 5 | n=3 时噪声项约为 5·s（m=1），n=5 时约为 3·s；CORE-Bench 用 n=3 是因为它的大多数题是确定性的 |
| agent 至少跑几个 seed（m） | 3，写进 task | m 越大均值越稳，容差越紧 |
| stochastic 阈值 | h / \|ref_mean\| > 5% | 容差宽到这个程度，"在容差内"已经说明不了跑对了 |
| 对数空间 | 只用于严格为正、跨数量级的误差类指标（MSE、能量误差等），在 ClaimSpec 里标 `scale: log` | 这类指标的噪声是乘性的，线性空间里的 s 会被少数大值主导 |
| 线程数 | n 次参考重跑里有意混用 1 线程和默认线程 | 让 s 包含浮点累加顺序带来的差异 |

#### 出处

| 部分 | 来源 | 依据强弱 |
|---|---|---|
| t 分布 95% 预测区间 | CORE-Bench 原版（Fig. 4，HAL harness 评分代码 `__eval_result_json`）；后续工作 arXiv 2606.26158 附录 A.5.3；统计上引自 Spence & Stanley (2016) | 强 |
| 精度项：不要求比论文更细的一致，接受没有四舍五入的值 | CORE-Bench 后续工作附录 A.5.3（先四舍五入到论文的小数位）和 A.1 修正 2；ReplicationBench 附录 D（容差按报告精度和随机性定） | 强 |
| 数值下限 | CORE-Bench v1.1（后续工作附录 A.1 修正 1：区间边界放宽 `np.isclose` 默认容差）。我们只保留相对部分 rtol，见下方"2026-10-16 修订" | 强（修订部分为本项目设计） |
| √(1/m + 1/n) | 标准统计推导：agent 均值方差 σ²/m，参考均值方差 σ²/n，二者独立，差的方差相加。m=1 时退化为 CORE-Bench 的 √(1 + 1/n) | 中：没有 benchmark 论文用过这个形式 |
| 三项取最大 | 本项目的设计，参考后续工作"先比精度，对不上再比预测区间"的两步协议。CORE-Bench v1.1 是把 isclose 加到边界上，因为该项极小，两种写法几乎相同 | 弱 |

#### 各项的含义

公式回答的问题是：如果 agent 的做法和官方代码完全一样，只换了 seed，它的结果最多会离参考均值多远。三项对应三种正当的差距来源：

- **噪声项**：随机性。s 估计单次运行的波动；√(1/m + 1/n) 把它换算成"agent 的 m 次均值"和"参考的 n 次均值"之差的波动；t 而不是 1.96，是因为 s 本身只是用 n 次运行估出来的。前提是 agent 运行和参考运行来自同一分布（同代码、同设置、同硬件），这正是要检验的：agent 改了 epoch、数据划分等设置时，结果会系统性地落到区间外。
- **精度项**：分辨率。主分比较的两边都是完整精度，所以这一项在本设计里主要是确定性代码（s=0）的下限，避免要求小数点后很多位都相等。
- **数值下限**：浮点误差。只兜住不同线程数或 BLAS 库造成的末位差异，正常情况下是三项中最小的。

  **2026-10-16 修订（已确认）**：原定用 isclose 的默认值 atol 1e-8 + rtol 1e-5。实现 CORE-Bench 评分时发现，绝对项 1e-8 对极小的值会失效：capsule-0152700 的 p 值是 2.34e-10，加上 1e-8 后 0 到 1e-8 之间的任何答案都会通过，而且这道题还会因为 h 超过均值的 5% 被误判为 stochastic。所以下限改为只用相对部分 1e-5·|ref_mean|，只有均值为 0 时才用 1e-8。

取最大而不相加：三项是同一个"允许差距"的三个下限，不是独立误差。噪声项已经包含了浮点波动，精度项只表示更细的差距没有意义，相加会重复计算。

#### 判定与登记

- 判定只看 h，不再另外做四舍五入：精度项已经覆盖了"接受未四舍五入值"的情况。
- h / |ref_mean| > 5% 的 claim 标为 `stochastic`，不进主分，单独报告。
- 每个容差在 `case.yaml` 里存 `justification`：三项各是多少、取了哪一项、n、m、s。
- 容差由代码根据参考重跑计算，冻结（sha256 + tag）之后才允许跑任何被测 agent；拿到 agent 结果以后不再调整。
- **敏感性分析**：报告里附 h × 0.5 / 1 / 2 时各组的成功率，检查排名是否依赖容差的选取（CORE-Bench 换评分规则后，同一批运行从 77.78% 变成 95.5%）。

#### 论文值的辅助容差（不进主分）

| 论文给出的 spread | h_paper |
|---|---|
| 跨 seed 的 std | max(精度项, 2·std/√k_paper)；k_paper 未知时取 1 |
| 跨 fold 的 std（例如 GIN 的 10 折） | max(精度项, 2·std/√k_folds)：论文报告的是 k 折均值，其不确定性是 std/√k |
| 没有 spread | 精度项 + 主分的噪声项 |

|ref_mean − paper_value| > h + h_paper 时标为 `paper_mismatch`：官方代码在我们的 sandbox 里都复现不出论文数字。这类 claim 照样按 ref 计主分，另外检查 agent 是否如实报告了差距。

这套规则解决了之前悬而未决的两个问题：非百分比指标没有 spread、spread 是跨 fold 的。主分不再依赖论文的 spread，只看我们自己重跑的结果。

#### 例子

参考重跑 5 次：92.31、92.58、92.12、92.44、92.27；论文写 92.5；agent 跑 3 个 seed。

| 项 | 计算 | 值 |
|---|---|---|
| ref_mean、s | — | 92.344、0.174 |
| 噪声项 | 2.776 × 0.174 × √(1/3 + 1/5) | 0.353 |
| 精度项 | 论文保留 1 位小数 | 0.05 |
| h | 三项取最大 | 0.353，通过区间 [91.99, 92.70] |
| stochastic | 0.353 / 92.344 = 0.38% | 否 |
| paper_mismatch | 差 0.156，小于 h + h_paper | 否 |

### 3.4 Schema

```
ClaimSpec          （主 LLM 写的骨架，不含数值；task.yaml 由它生成）
  claim_id, description, metric, split, unit, direction (higher/lower)
  setting: {dataset, model, key hyperparams, scaled_down: {...}}
  source: {table|figure|text, locator}       # 例如 "Table 2, row GIN, col MUTAG"
  required_evidence: training trace + metric line

GTValue            （抽取器填写，进 case.yaml）
  claim_id, paper_value, quote, page, precision, reported_spread, spread_type (seed|fold|none)
  extractor_votes: [{provider, model, value, quote}]

ReferenceRun       （构建脚本填写，进 case.yaml）
  claim_id, command_sha, env_lock_sha, seeds, values, wall_time

Tolerance          （代码计算，进 case.yaml）
  claim_id, rule, value, justification, status (scored|stochastic|paper_mismatch)

Freeze             case.yaml 的 sha256 + 冻结时间 + git tag
```

Agent 的答案格式保持 `metrics.json`，但键必须恰好等于 `claim_id` 的集合。有效提交率单独统计。

### 3.5 GT 构建流水线（采用你描述的结构）

```
用户：一段 prompt + 论文链接 + 可选信息（要复现的 claim、设置）
   │
   ▼
① 主 LLM 定骨架：ClaimSpec 列表（选哪些 claim、什么设置、指标、表格位置），不写数值
   │  ← 用户审一次骨架（选题是主观的，这一步人最该看）
   ▼
② K 个不同 provider 的抽取器，各自独立地按骨架填 GTValue（互相看不到）
   ▼
③ 确定性核对（代码，不是 LLM）
   - 数值必须原样出现在论文文本中，并且在 quote 附近
   - 精度和论文的小数位一致
   - K 个抽取器一致 → 通过；不一致 → 冲突队列
   ▼
④ 冲突交给人裁定（测试集）；开发集可以用仲裁 LLM
   ▼
⑤ 参考重跑（构建脚本，用官方代码，n=5）→ ReferenceRun
   ▼
⑥ 代码计算 Tolerance 和 status
   ▼
⑦ 冻结：写入 case.yaml，记录 sha256，打 tag；之后才允许跑任何被测 agent
```

为什么由主 LLM 先定骨架：不同 provider 读同一篇论文，挑出的 claim 可能不一样，没有骨架就没法对齐比较。骨架固定以后，抽取器只做"在指定位置读数字"这一件事，分歧变小，核对也可以完全确定性地完成。

### 3.6 防泄漏（两类）

**构建阶段**，防止 GT 流进被测 agent：

- `task.yaml` 由 ClaimSpec 生成，用代码检查其中没有任何 `paper_value` 或 `reference` 数值（扩展现有的 `test_no_case_leakage`）。
- 抽取器和参考重跑的输出只写进 `benchmark/<case>/case.yaml`，sandbox 不能读 `benchmark/`。
- GT 构建和被测运行用不同进程、不同 run 目录；构建过程的 trace 不进被测 agent 的上下文。

**运行阶段**，防止被测 agent 抄答案：

| 措施 | 做法 | 依据 |
|---|---|---|
| 遮蔽论文 | 给 agent 的论文文本里，把目标 claim 所在表格单元格换成 `[MASKED]`，设置描述保留 | ReplicationBench：不遮蔽时 0.19 → 0.46 |
| 清理仓库 | clone 后删除仓库自带的结果文件（`results/`、`*.csv`、logs、checkpoint），清单写进 case | CORE-Bench：20/45 个任务可以直接读答案 |
| 网络白名单 | 只允许 PyPI、指定的 GitHub 仓库、数据集主机；屏蔽 arXiv、Papers with Code 等结果来源 | CORE-Bench 的 agent 上网搜答案 |
| 数值溯源 | 已有：计数的值必须出现在本次运行的 harness 日志里 | RE-Bench 的伪造日志 |
| 无计算基线 | 每个 case 用无工具的模型直接问一次答案，测记忆率 | ReplicationBench：低于 9% |
| 重新执行（可选） | 对判为成功的运行，在新 sandbox 重跑 agent 的最终命令一次 | PaperBench、RE-Bench |

### 3.7 评分与报告

逐层报告，每层单独给比例：

```
有效提交 → 跑通 → 证据合规 → 每个 claim 在容差内 → case 全对（主分）
```

- **主分**：case 级全对，即 scored claim 全部在 `reference` 的容差内。同时报告 claim 级的部分分。
- **辅助指标**：
  - 和 `paper_value` 的差距；
  - `paper_mismatch` claim 上 agent 是否如实报告差距；
  - 假成功：报告成功但没有证据，或者数值来自抄写；
  - cost per success。
- **统计**：每个 (case, arm) 跑 k=3 次，报告 pass@1 的均值、pass^3 和 Wilson 95% CI。在下结论"某组更好"之前，先做配对检验（同一个 case 上比较两组）。
- **固定版本**：model ID、代码 tag、`models.yaml` 的 hash、sandbox 镜像的 hash 都写进 summary。
- **LLM 监控**（可选）：读 trace 标记可疑行为，只用于人工复查，不影响分数。

### 3.8 规模和数据集划分

- 测试集是你在建的论文数据集，按 3.1 的标准筛选。v3 的 5 篇加上更早的几篇作为开发集，可以用来调代码。
- 以 20 篇 × 5 组 × 3 次计算，总共 300 次运行。每组 60 次，在 Wilson 区间下大约只能分辨 15–20 个百分点以上的差别。所以重点放在配对比较和失败类型的分布上，而不只是看一个总成功率。

### 3.9 外部数据集：CORE-Bench v1.1（已确认，2026-10-16）

- 用 v1.1（39 题，后续工作 arXiv 2606.26158 修正过 GT、评分和捷径），不用原版 Hard。题目在 HF `agent-evals/core-bench-v1.1-mainline`；HAL harness 的 v1.1 评分脚本和答案文件是 gpg 加密的，答案是否公开**待核实**。
- 角色：开发集 + 外部对照集，不当 held-out 测试集（题目公开，可能已进训练数据）。主结论只来自 cutoff 之后的自建论文。
- 评分报两个口径：
  1. **官方口径**：复刻 HAL harness 原版规则（数值题用 n=3 重跑的 95% 预测区间 √(1+1/n)；字符串转小写精确匹配第一次重跑；列表完全相等；一个任务所有题都对才算 full），再加 v1.1 的四条修正（区间边界放宽 isclose、接受未四舍五入值、布尔值按字符串比较、部分题接受多个答案）。用来和排行榜对比。
  2. **我们的口径**：官方口径 + 证据检查，数值必须来自本次运行中 sandbox 生成的日志或输出文件，不能来自运行前就存在的文件。两者之差计为假成功。
- CORE-Bench 题沿用它自己的 GT 和规则，不套 3.3 的公式。
- 筛选结果：39 题中满足 CPU + Python + 无读图题的有 7 个（cb-6049678、cb-7800694、cb-8412128、cb-7655932、cb-0201673、cb-2242462、cb-3762736）。已下载前 5 个的 capsule（约 10 MB，gitignore）。
- 适配器（2026-10-16，只跑过离线测试）：
  - `p2e/capsule.py`：安全解压（拒绝链接和越界路径）；Hard 级清理，规则照搬 HAL 的 `CoreBenchHard`（删除 results/、REPRODUCING.md、environment/、code/run 和 run.sh、文件名含 train 的数据文件、cache、checkpoint、__pycache__）；运行前快照；答案溯源。
  - 答案溯源的四种状态：`typed`（出现在 agent 自己敲的命令或用 write_file 写的文件里）> `produced`（出现在命令输出或本次运行新建、改动过的文件里，答案文件本身除外）> `preexisting_only`（只出现在 capsule 自带且没被改过的文件里，即捷径）> `not_found`。日志只认 sandbox 写入后没被改过的（manifest 校验）。
  - `p2e/corebench.py`：`export` 生成 `tasks/<id>/task.yaml`（agent 可见，无答案）和 `case.yaml`（事先登记的每题容差 + core_test.json 的 sha256）；`new_run` 建 Hard 级工作区、快照、brief；`finish` 评分并写 eval.json、summary.json。
  - 判定：full = 每道计分题都在容差内，且来源为 `produced`。同时报告只看答案的结果（`full_tolerance_only`）和 HAL 原版规则（`hal_full`），差值就是捷径和自己敲的答案。
  - 已知局限：capsule 自带的二进制结果文件（如 capsule-6049678 的 `data/Record/*.npz`，它的 Main.py 会读这些文件并在旧结果更好时报出旧结果）无法检查，只列为风险；很短的答案（yes、blue、小整数）可能碰巧匹配，标为 weak；agent 的命令里如果碰巧出现与答案相同的数（如 `--epochs 25`），会被误判为 typed。
  - 还没做：A–D 五个版本的提示词仍以"论文 + 仓库 + 数值 claim"为前提，要在 CORE-Bench 上跑，需要给每个版本加 capsule 模式（读 brief、写 report.json、调用 `corebench.finish`）。

## 4. 需要你决定的事

| # | 决定 | 我的建议 | 另一选项 |
|---|---|---|---|
| 1 | 主评分目标 | **已定**：`reference`（CPU 重跑），论文值作辅助 | — |
| 2 | 参考重跑的成本 | **已定**：n=5，agent m=3，由构建脚本执行（见 3.3） | — |
| 3 | 随机 claim 的排除阈值 | **已定**：h / \|ref_mean\| > 5% 标为 stochastic，单独报告 | — |
| 4 | 遮蔽论文结果 | 遮蔽目标单元格；另做一次不遮蔽的消融 | 不遮蔽，只靠数值溯源 |
| 5 | 网络策略 | 白名单 | 只屏蔽黑名单域名 |
| 6 | 冲突裁定 | 测试集由人裁定，开发集由仲裁 LLM | 都用仲裁 LLM |
| 7 | 抽取器 | Haiku 5.5 + gpt-6-luna（目前有 key 的两家），主 LLM 用更强的一档 | 再接一个 OpenAI 兼容的第三家 |
| 8 | 新 sandbox 重新执行 | 只对判为成功的运行做 | 全部做，或者不做 |
| 9 | 选题时间 | 只收 cutoff 之后的论文 | 新旧混合，分开报告 |
| 10 | 外部数据集 | **已定**：CORE-Bench v1.1，开发集 + 外部对照（见 3.9） | — |
