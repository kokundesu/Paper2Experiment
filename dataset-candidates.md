# 复现数据集候选（20 篇 + 备选）

整理于 2026-10-16，供 v4 对比实验（A / B / C / C⁻ / D）使用。这一版是**候选清单**，正式的 `task.yaml` / `case.yaml` 还没写。

## 筛选标准

| 标准 | 具体要求 |
|---|---|
| 耗时 | 在 Mac M4（16 GB、只用 CPU）上，一次运行约 20 分钟以内，3 个 seed 能在 1 小时内跑完。**下表的耗时都是估计值**：按预注册规则，写真值之前不运行论文代码 |
| 代码 | 作者的官方仓库，仓库里有复现某张表的脚本、命令、配置或 notebook；仓库在 2026-10-16 通过 GitHub API 确认可以访问 |
| 质量 | 优先 NeurIPS / ICML / ICLR / KDD / SIGIR / RecSys / AAAI / IJCAI / TKDE / SIAM 等 |
| 数据 | 1 GB 以内，可以不登录直接下载 |
| 排除 | 已经用过的 13 篇（GCN、SGC、DGI、DLinear、FITS、KalmanNet、L2O-WMMSE、PINN Burgers、fastText、GIN、HNN、ROCKET、Deep SVDD），以及它们用的数据集（Cora、Citeseer、PubMed、MUTAG、PTC、ETT 系列、Burgers、MNIST 单类异常检测）；不选需要调用付费 LLM 的论文 |

难度一栏的含义：**易** = 按 README 命令直接跑；**中** = 需要打小补丁（去掉写死的 CUDA、补数据或文件）；**难** = 需要移植旧框架（Theano、TF1），或者论文和代码有出入、存在陷阱。

---

## 一、主清单（20 篇）

### 图学习与推荐系统（5 篇）

| # | 论文 | 会议/期刊 | 论文链接 | 官方仓库 | 复现入口 | 复现设置 | 论文值（表号） | 估计耗时/次 | 难度 | 主要风险 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | BSPM: Blurring-Sharpening Process Models for CF | SIGIR 2023 | [2211.09324](https://arxiv.org/abs/2211.09324) | [jeongwhanchoi/BSPM](https://github.com/jeongwhanchoi/BSPM) | README 里的 CPU 命令（`bspm/main.py --dataset gowalla ...`） | Gowalla，BSPM-EM | Recall@20 0.1920，NDCG@20 0.1597（表 4） | 1–3 分钟 | 易 | 方法完全确定性；`sparsesvd` C 扩展要在 arm64 上编译 |
| 2 | Revisiting the Performance of iALS | RecSys 2022 | [2110.14037](https://arxiv.org/abs/2110.14037) | [google-research/ials](https://github.com/google-research/google-research/tree/master/ials) | `ncf_benchmarks/ials_simple.py`（README 给出了论文的参数） | ML-1M，NCF 留一法协议 | HR@10 0.730，NDCG@10 0.453（表 5，10 次平均） | 3–8 分钟 | 中 | 要从 NCF 仓库补 `Dataset.py`、`evaluate.py` 和数据 |
| 3 | GPR-GNN | ICLR 2021 | [2006.07988](https://arxiv.org/abs/2006.07988) | [jianhao2016/GPRGNN](https://github.com/jianhao2016/GPRGNN) | `src/Reproduce_GPRGNN.sh`（chameleon 那一行） | Chameleon，60/20/20 划分 | 67.48 ± 0.40（表 2） | 每个划分 5–20 秒；论文跑 100 次，需要减少 | 中 | `torch_sparse` 在 arm64 上可能装不上，可改用 PyG 自带函数 |
| 4 | Correct & Smooth | ICLR 2021 | [2010.13993](https://arxiv.org/abs/2010.13993) | [CUAI/CorrectAndSmooth](https://github.com/CUAI/CorrectAndSmooth) | `gen_models.py` + `run_experiments.py --method plain` | ogbn-arxiv，Plain Linear + C&S | Autoscale 71.11（表 2）；README 写 71.26 | 2–5 分钟 | 中 | 代码里写死了 `.cuda()`；论文和 README 数字不一致 |
| 5 | APPNP (Predict then Propagate) | ICLR 2019 | [1810.05997](https://arxiv.org/abs/1810.05997) | [gasteigerjo/ppnp](https://github.com/gasteigerjo/ppnp) | `reproduce_results_pytorch.ipynb`（作者的 PyTorch 版本） | MS Academic，APPNP | 93.27 ± 0.08（表 2） | 每个划分 1–3 分钟；论文跑 100 次，需要减少 | 难 | notebook 里的数据集名称和文件名对不上，会**悄悄**改用默认超参；TF1 原版在 arm64 上不能用 |

### 时间序列与信号（5 篇）

| # | 论文 | 会议/期刊 | 论文链接 | 官方仓库 | 复现入口 | 复现设置 | 论文值（表号） | 估计耗时/次 | 难度 | 主要风险 |
|---|---|---|---|---|---|---|---|---|---|---|
| 6 | iTransformer | ICLR 2024 | [2310.06625](https://arxiv.org/abs/2310.06625) | [thuml/iTransformer](https://github.com/thuml/iTransformer) | `scripts/multivariate_forecasting/Exchange/iTransformer.sh` | Exchange，输入 96，预测 96 | MSE 0.086，MAE 0.206（表 10）；5 个 seed 0.088 ± 0.001（表 5） | 1–3 分钟 | 易 | 数据要从 Google Drive 的数据包里取 |
| 7 | TS-TCC | IJCAI 2021 | [2106.14112](https://arxiv.org/abs/2106.14112) | [emadeldeen24/TS-TCC](https://github.com/emadeldeen24/TS-TCC) | `main.py --training_mode self_supervised` 再 `train_linear` | Epilepsy 脑电，线性评估 | ACC 97.23 ± 0.10，MF1 95.54 ± 0.08（表 2） | 10–20 分钟 | 中 | 默认 `--device cuda`；要先跑预处理脚本；两阶段训练 |
| 8 | TS2Vec | AAAI 2022 | [2106.10466](https://arxiv.org/abs/2106.10466) | [zhihanyue/ts2vec](https://github.com/zhihanyue/ts2vec) | `scripts/ucr.sh`（按数据集逐行） | UCR 子集：ECG200、GunPoint、ItalyPowerDemand、TwoLeadECG、Chinatown | 0.920、0.980、0.925、0.986、0.965（表 9，B=8 列） | 每个数据集 1–3 分钟 | 中 | `--gpu 0` 会强制使用 CUDA，要改一行；UCR 压缩包 316 MB，需要公开的解压密码 |
| 9 | CycleNet | NeurIPS 2024 | [2409.18479](https://arxiv.org/abs/2409.18479) | [ACAT-SCUT/CycleNet](https://github.com/ACAT-SCUT/CycleNet) | `scripts/CycleNet/MLP-Input-96/weather.sh`（脚本自带 5 个 seed） | Weather，输入 96，预测 96，MLP 版 | MSE 0.158 ± 0.001，MAE 0.203 ± 0.001（表 7） | 3–8 分钟 | 易 | 依赖没有固定版本；Linear 版和 DLinear/FITS 太像，选 MLP 版 |
| 10 | PatchTST | ICLR 2023 | [2211.14730](https://arxiv.org/abs/2211.14730) | [yuqinie98/PatchTST](https://github.com/yuqinie98/PatchTST) | `PatchTST_supervised/scripts/PatchTST/illness.sh` | ILI，预测 24 | PatchTST/42：MSE 1.522，MAE 0.814（表 3） | 1–3 分钟 | 中 | 脚本的输入长度是 104，和表里 /42、/64 两行都对不上，要事先选定一行；ILI 波动大，容差要放宽 |

### 经典 / 概率机器学习（5 篇）

| # | 论文 | 会议/期刊 | 论文链接 | 官方仓库 | 复现入口 | 复现设置 | 论文值（表号） | 估计耗时/次 | 难度 | 主要风险 |
|---|---|---|---|---|---|---|---|---|---|---|
| 11 | NGBoost | ICML 2020 | [1910.03225](https://arxiv.org/abs/1910.03225) | [stanfordmlgroup/ngboost](https://github.com/stanfordmlgroup/ngboost) | `examples/experiments/regression_exp.py --dataset concrete --natural ...` | Concrete，20 次随机 90/10 划分 | NLL 3.04 ± 0.17（表 1），RMSE 5.06 ± 0.61（表 3） | 5–10 分钟 | 易 | `--natural` 默认关闭，忘了开就不对 |
| 12 | ECOD | TKDE 2022 | [2201.00382](https://arxiv.org/abs/2201.00382) | [yzhao062/pyod](https://github.com/yzhao062/pyod) | `notebooks/benchmark.py`（60/40 划分，10 次） | ODDS：Cardio、Breastw、Mammography | ROC-AUC 0.897、0.994、0.894（表 4） | 几秒 | 易 | 方法确定性，seed 只影响划分；脚本默认只跑 1 次，数据集列表也不同；期刊信息在 arXiv 里没有写明（待核实） |
| 13 | Stein Variational Gradient Descent | NeurIPS 2016 | [1608.04471](https://arxiv.org/abs/1608.04471) | [dilinwang820/Stein-Variational-Gradient-Descent](https://github.com/dilinwang820/Stein-Variational-Gradient-Descent) | `python/bayesian_nn.py` | Boston，Bayesian NN，20 次划分 | RMSE 2.957 ± 0.099，LL −2.504 ± 0.029（第 5 节的 BNN 表，没有表号） | 5–10 分钟 | 难 | Python 2 + Theano，需要移植；要自己加 20 次划分的循环 |
| 14 | Dropout as a Bayesian Approximation | ICML 2016 | [1506.02142](https://arxiv.org/abs/1506.02142) | [yaringal/DropoutUncertaintyExps](https://github.com/yaringal/DropoutUncertaintyExps) | `experiment.py --dir bostonHousing --epochx 10 --hidden 1` | Boston，20 次固定划分（在仓库里），网格搜索 | RMSE 2.97 ± 0.19，LL −2.46 ± 0.06（表 1）；README 重跑值 2.90 / −2.40 | 10–20 分钟 | 难 | Theano + Keras 2.2，需要移植；论文和 README 数字不一致 |
| 15 | FairBatch | ICLR 2021 | [2012.01696](https://arxiv.org/abs/2012.01696) | [yuji-roh/fairbatch](https://github.com/yuji-roh/fairbatch) | `FairBatch_Synthetic.ipynb`（equal opportunity 部分） | 合成数据，逻辑回归 | Accuracy 0.855，EO disparity 0.012 ± 0.001（表 1） | 2 分钟以内 | 易 | notebook 自带运行结果，**交给 agent 前要清掉输出**；只发布了合成数据的代码 |

### 科学计算、NLP、表示学习、组合优化（5 篇）

| # | 论文 | 会议/期刊 | 论文链接 | 官方仓库 | 复现入口 | 复现设置 | 论文值（表号） | 估计耗时/次 | 难度 | 主要风险 |
|---|---|---|---|---|---|---|---|---|---|---|
| 16 | Doc2VecC | ICLR 2017 | [1707.02377](https://arxiv.org/abs/1707.02377) | [mchen24/iclr2017](https://github.com/mchen24/iclr2017) | `go.sh`（C 代码 + liblinear） | IMDB 情感分类，表示学习时包含测试文档 | 错误率 10.48%（表 1） | 10–15 分钟 | 中 | Apple clang 可能不接受 `-march=native`；脚本用逻辑回归而论文写线性 SVM；多线程导致结果不完全确定 |
| 17 | Understanding and Mitigating Gradient Pathologies in PINNs | SIAM J. Sci. Comput. 2021 | [2001.04536](https://arxiv.org/abs/2001.04536) | [PredictiveIntelligenceLab/GradientPathologiesPINNs](https://github.com/PredictiveIntelligenceLab/GradientPathologiesPINNs) | `Helmholtz/Helmholtz2D.py`（`mode='M2'`） | 2D Helmholtz 方程 | 相对 L2 误差 M2 1.12e-02，M1 1.06e-01（表 2，arXiv 版） | 3–8 分钟 | 难 | TF1 代码，要用 `tf.compat.v1`；默认是 M1，要改成 M2；期刊版的表号待核实 |
| 18 | Set Transformer | ICML 2019 | [1810.00825](https://arxiv.org/abs/1810.00825) | [juho-lee/set_transformer](https://github.com/juho-lee/set_transformer) | `run.py --net=set_transformer` | 摊销聚类，2D 4 个高斯的混合 | 每点对数似然 −1.5009 ± 0.0068（ISAB(16)+PMA，表 3） | 10–20 分钟 | 难 | 写死 `.cuda()`；仓库默认值和论文有 3 处不同（每组点数、学习率衰减步数、诱导点数），是"按论文还是按代码"的考验 |
| 19 | Deep Neural Networks as Gaussian Processes (NNGP) | ICLR 2018 | [1711.00165](https://arxiv.org/abs/1711.00165) | [brain-research/nngp](https://github.com/brain-research/nngp)（已归档） | `run_experiments.py --num_train=1000 ... depth=20,weight_var=1.45,bias_var=0.28` | MNIST 1000 个训练样本 | 测试准确率 0.9279（表 1） | 1–5 分钟 | 中 | TF1，MNIST 加载器在 TF2 里已删除，要重写；基本确定性 |
| 20 | Attention, Learn to Solve Routing Problems! | ICLR 2019 | [1803.08475](https://arxiv.org/abs/1803.08475) | [wouterkool/attention-learn-to-route](https://github.com/wouterkool/attention-learn-to-route) | `generate_data.py` 再 `eval.py ... --model pretrained/tsp_20 --decode_strategy greedy --no_cuda` | TSP20/50/100，贪心解码，用仓库自带的预训练模型 | 平均路径长度 3.85 / 5.80 / 8.12（表 1） | 5 分钟以内 | 中 | **只做推理不训练**（训练需要 GPU）；PyTorch 2.6 以后 `torch.load` 默认 `weights_only=True` |

---

## 二、备选（主清单里的某篇不合适时替换）

| 论文 | 会议/期刊 | 可替换 | 不放进主清单的原因 |
|---|---|---|---|
| GF-CF | CIKM 2021 | #1 | 和 BSPM 同一套代码和数据 |
| A Critical Look at GNNs under Heterophily | ICLR 2023 | #3、#5 | DGL 在 arm64 上有风险；10 个划分约 35 分钟，接近上限 |
| LINKX | NeurIPS 2021 | #3 | 固定的 torch 1.7 环境在 M4 上装不了，需要改写 |
| Koopa | NeurIPS 2023 | #10 | 和 PatchTST 或 iTransformer 用同一个数据集 |
| TimesNet（分类） | ICLR 2023 | #8 | 用测试集做验证；代码库自论文发表后变化很大 |
| SparseTSF | ICML 2024 | #9 | 又一个线性预测器，和 DLinear、FITS 太像 |
| COPOD | ICDM 2020 | #12 | 和 ECOD 同一批作者、同一套协议 |
| CATENets | AISTATS 2021 | #15 | IHDP 100 次实现，单个模型估计 15–45 分钟，3 个 seed 会超时 |
| Einsum Networks | ICML 2020 | #13 | 表 1 的结构参数没有写在仓库里 |
| TabPFN v1 | ICLR 2023 | #11 | 仓库已经换成新模型，复现流程依赖预先算好的结果 |
| SympNets | Neural Networks 2020 | #17 | 主题和开发集的 HNN 太接近 |
| Prototypical Networks | NeurIPS 2017 | #18 | 估计 25–40 分钟，超出单次运行的预算 |
| EGNN（N-body） | ICML 2021 | — | 估计每次超过 1 小时 |

---

## 三、建数据集前需要先定下来的几件事

1. **确定性的方法**（#1 BSPM、#12 ECOD、#19 NNGP、#20 AM-TSP 贪心解码）：3 个 seed 的结果会相同或几乎相同。可以接受，把它们当成"能否跑通、能否对上数字"的题；也可以从备选里换掉一部分。
2. **论文的数字是很多次划分的平均**（#3 跑 100 次、#5 跑 100 次、#11 和 #13 跑 20 次、#14 跑 20 次）：要定义"一次运行"是指完整协议，还是其中的一个子集；如果是子集，容差要相应放宽。
3. **论文和代码给的数字不一致**（#4、#14），**或者设置不一致**（#10、#16、#18）：按之前的规则，以论文表格为真值，另一个数字作为参考记在 `case.yaml` 里，并在预注册时写明。
4. **耗时都是估计值**：真跑起来超过 1 小时的，按协议换成备选，而不是放宽时间。
5. **难度分布**：易 6 篇（#1、#6、#9、#11、#12、#15），中 9 篇（#2、#3、#4、#7、#8、#10、#16、#19、#20），难 5 篇（#5、#13、#14、#17、#18）。这样对比实验能看出不同架构在不同难度上的差别。
