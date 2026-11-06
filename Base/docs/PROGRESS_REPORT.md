# Paper2Experiment 进度报告（Day 1）

日期：2026-10-01 · 机器：Apple M4，16 GB，仅 CPU · 作者：HU YANZHI（单人）

## 1. 一句话现状

三篇论文都已手动复现，三篇都判为 **full**，作为 benchmark 的 ground truth。三种 workflow（deterministic / single-agent / multi-agent）的框架都已写完，离线测试 10/10 通过。deterministic baseline 已在三篇论文上实测，三篇都判为 fail，原因见第 4 节。single-agent 和 multi-agent 两种 workflow 要等 `ANTHROPIC_API_KEY` 设好后才能实测。

## 2. Benchmark：三篇论文的手动复现

| Case | 论文 | 难度 | Claim | 论文值 | 复现值 | 判定 |
|---|---|---|---|---|---|---|
| `gcn` | Kipf & Welling, ICLR 2017（arXiv 1609.02907） | 易 | Cora / Citeseer / Pubmed 测试准确率（Table 2） | 81.5 / 70.3 / 79.0 % | 81.76 / 71.15 / 79.08 %（10 seeds，均值） | full |
| `l2o_wmmse` | Sun et al., IEEE TSP 2018（arXiv 1705.09412） | 中 | K=10/20/30 时 DNN 和速率占 WMMSE 的比例；K=10 时相对 Python WMMSE 的加速比（Table I） | 98.33 / 92.04 / 84.29 %；382.6× | 97.88 / 90.61 / 84.86 %；446×（3 seeds，均值） | full |
| `pinn_burgers` | Raissi et al., arXiv 1711.10561（JCP 2019） | 中 | Burgers 方程相对 L2 误差：主结果、Table 1 N_u=200、Table 2 4×20 | 6.7e-4 / 4.9e-4 / 9.4e-4 | 2.58e-3 / 1.12e-3 / 5.11e-3（中位数，11/4/4 seeds） | full（容差为 10 倍）|

所有 ground truth 都已和论文 PDF 原文逐一核对。每篇的完整记录在 `benchmark/<case>/MANUAL_REPRO.md`。

### 每篇需要修什么（这些是 agent 要面对的难点）

| Case | 环境修复 | 主要陷阱 | 人工耗时 / 计算时间 |
|---|---|---|---|
| gcn | 包路径（PYTHONPATH）；新版 SciPy 删了 `eigen.arpack`；TF1 要改成 `compat.v1`；seed 写死在代码里 | `tkipf/pygcn` 用的数据划分不同，跑出约 83%，看着接近论文但不可比 | 约 15 min / 每次几秒 |
| l2o_wmmse | NumPy 2 的标量转换报错；Matplotlib 样式名改了；没有现成的训练脚本，要自己写一个；Python 版 WMMSE 生成 100 万样本太慢，需要向量化；K=30 用 float64 会占满内存 | `test.py` 直接加载作者的预训练权重，不训练也能得到接近论文的数字；`demo.py` 并不是论文的实验设置；论文和代码给的网络结构不一致 | 约 35 min / 每次训练 7–17 min |
| pinn_burgers | 代码在 `appendix/` 下，路径带空格；`pyDOE` 包改名，要固定在 0.3.8；plotting 一导入就崩；`tf.contrib` 里的 L-BFGS 要自己重写 | 默认 seed 1234 是最差的一次（1.1e-2）；如果限制迭代次数，结果会彻底跑坏；论文里的 "9-layer" 实际是 8 个隐藏层 | 约 25 min / 每次 0.5–3 min |

### 评估器校准

`scripts/calibrate_manual.py` 把三篇手动复现的日志交给自动评估器打分，三篇都判为 **full**，和人工结论一致。这说明评估器的容差、聚合方式和证据检查不会误判一次正确的复现。

### 需要你拍板的一点：PINN 的容差

PINN 的复现值比论文高 2–5 倍，但仍在同一数量级，论文的定性结论都成立。容差是看到结果之后才定为 10 倍的。依据有两条：论文自己对同一配置报了 6.7e-4 和 9.6e-4 两个数；我们 11 个 seed 的结果从 7.8e-4 到 1.1e-2 不等，3 倍的阈值会落在 seed 波动范围中间，判定结果全凭运气。如果按严格的 3 倍，判定就是 partial。**建议报告里两个标准都写。**

## 3. 系统框架

```
task.yaml（agent 可见：论文、仓库、claim id，没有目标值）
   │
   ├─ deterministic：clone → 按 requirements 安装 → 跑 README 里的命令 → 用正则抓数字（不用 LLM）
   ├─ single-agent：一个 agent 拿着所有工具，从头做到尾，自己提交数字
   └─ multi-agent：
        Paper Analyst（只读）→ PaperSpec
        Env Agent（可执行 shell）→ EnvReport
        Planner（只读）→ ExperimentPlan（每个 claim × seed 对应一次运行）
        Executor（普通代码，不是 LLM）→ 执行并从日志里解析数字
           ↺ Debugger（最多 4 次）→ 给出修正后的运行配置
   │
Evaluator（不用 LLM）+ case.yaml（隐藏的 ground truth）→ full / partial / fail
```

主要设计决定（报告里可以作为方法论来讲）：

1. **ground truth 对 agent 隐藏。** agent 只能看到 `task.yaml`。沙箱会拦截所有访问 `case.yaml` 和 `benchmark/` 的命令。
2. **数字只能来自日志。** multi-agent 的数字由 Executor 从日志里解析出来。single-agent 由 agent 自己提交数字，但评估器会检查：每个提交的数都必须能在它引用的日志里找到，否则判失败（有单测覆盖）。
3. **证据模式。** L2O 的 claim 要求引用的日志里必须有训练过程的输出（`epoch:` … `training time:`），这样只加载预训练权重跑 `test.py` 不会被算作复现。
4. **容差逐个 claim 设定，有据可查。** 可选绝对误差、相对误差或倍数，聚合方式可选均值或中位数。每个 case 都写明了容差的理由。
5. **预算硬上限。** 默认模型是 Sonnet 5.5，每次运行最多花 5 美元，所有 agent 共用一个账本。在 multi-agent 里，每个角色还有自己的份额。钱花完以后不再调 Debugger，但已经跑出的结果照常评分。
6. **可追溯。** 每次运行都会留下 `trace.jsonl`（每一轮 LLM 对话和每次工具调用）、`logs/`（每条命令的完整输出），以及 multi-agent 各阶段产出的 JSON 文件。

代码：`p2e/`（约 1,150 行，含注释）。测试：`tests/`，共 10 个，包括一个用假 Claude client 跑通 multi-agent 全流程的端到端测试。

## 4. Baseline 实测（deterministic，不用 LLM）

| Case | 判定 | 用时 | 卡在哪里 |
|---|---|---|---|
| gcn | fail（0/3） | 30 s | 固定版本的 TF 1.15.4 在 Python 3.11 上装不了，去掉版本号后能装上，正确找到了 `gcn/train.py`；运行时卡在 SciPy 的 `eigen.arpack` 导入错误 |
| pinn_burgers | fail（0/3） | 28 s | 仓库没有 `requirements.txt`，README 里也没有运行命令，找不到实验入口 |
| l2o_wmmse | fail（0/4） | 105 s | 找到了 README 里的 `demo.py`（而且这本身就不是论文的实验设置）；运行时卡在 NumPy 2 的 `only 0-dimensional arrays` 报错 |

三篇的失败点和手动复现时遇到的第一个坑完全一致。这说明 benchmark 的难点是真实存在的：光照着仓库说明跑不通，必须能 debug 和理解代码。这正是拿 LLM workflow 来做对比的意义。

## 5. 风险与未解决的问题

- **LLM workflow 还没有实测。** 离线测试只证明各部分接得上，Claude 实际会怎么做还不知道。最大的不确定性在 L2O：要在 20 分钟和 5 美元以内达到论文规模，agent 需要自己发现 WMMSE 数据生成慢，并把它向量化。更可能的情况是它缩小数据规模，结果落到 partial 或 fail。这本身也是值得报告的发现。
- **沙箱隔离是约定性的。** 拦截靠匹配命令文本，挡不住刻意绕过的进程。报告里要写明这一点；Docker 后端可以作为后续工作。
- **L2O 的加速比受机器负载影响。** 同一台机器上 Python 版 WMMSE 的耗时能差 3 倍，所以这个 claim 的容差设成了 3 倍。
- **CPU 争用。** 并行跑会让每次运行慢 3–5 倍，所以实验必须串行跑。

## 6. 下一步（Day 2–3）

| 时间 | 任务 |
|---|---|
| Day 2 上午 | 设好 API key。先在 GCN 上各跑一次 single 和 multi，看实际花费和 agent 的行为，必要时修 prompt |
| Day 2 下午 | 3 个 case × 2 种 LLM workflow × 3 次重复 = 18 次运行，串行执行。花费上限约 18 × 5 = 90 美元，实际应该更少 |
| Day 3 上午 | 汇总对比表：成功率、各 claim 的误差、耗时、花费、调试次数。从 trace 里归类失败原因 |
| Day 3 下午 | 准备 demo（选一次完整的 multi-agent 运行回放），写报告 |

## 7. 文件索引

- `README.md`：用法和配置项
- `p2e/`：系统代码。`schemas.py` / `sandbox.py` / `llm.py` / `runner.py` / `evaluator.py` / `workflows/` / `cli.py`
- `benchmark/<case>/`：`task.yaml`、`case.yaml`、`MANUAL_REPRO.md`、`results/`、`manual/*.patch`
- `scripts/calibrate_manual.py`：评估器校准
- `runs/`：每次运行的完整产物（已 gitignore）
- `envs/`：手动复现用的虚拟环境（已 gitignore）
