# 待确认事项（意图阶段 + GT 阶段生成）

## appnp
- 起草者的疑问：论文表 2 的结果来自 TensorFlow 实验，而用户指定作者的 PyTorch 实现：请确认是以表 2 的论文均值为复现目标，还是希望比较 PyTorch 复现笔记本自身给出的结果？

## tstcc
- 无需确认
  - 备注 `epilepsy_ts_tcc_linear_acc`：haiku55: underspecified (split) -- Table 2 TS-TCC (ours), Epilepsy ACC column matches the request. The text says 60/20/20 split, but Table 1 lists 9200 train and 2300 test samples, which is an 80/20 division of 11500. The split used is therefore ambiguous and could change the number, so it is flagged.
  - 备注 `epilepsy_ts_tcc_linear_mf1`：haiku55: underspecified (split) -- Table 2 TS-TCC (ours), Epilepsy MF1 column matches the request. Same split ambiguity as the ACC item (text 60/20/20 vs. Table 1 counts 9200/2300).

## patchtst
- 起草者的疑问：正文将 PatchTST/42 定义为历史输入长度 336，但附录表 9 和图 3 表明 ILI 的对应实验使用历史长度 104；是否以表 3 的 ILI 项及仓库 illness 脚本配置为准，而非要求严格使用长度 336 的 42 个输入补丁？
  - 备注 `ili_24_patchtst42_mse`：haiku55: underspecified (variant) -- Table 3 ILI row 24, PatchTST/42 MSE column is the target. The text defines /42 as L=336, but Appendix A.4.2 Table 9 (column labelled 336(104)) and A.2 / Figure 3 show ILI uses L=104 for this result. The draft's setting matches the paper, but the look-back choice (336 vs 104) would give different numbers, so it is worth keeping explicit. ILI is small, so CPU runs are feasible.
  - 备注 `ili_24_patchtst42_mae`：haiku55: underspecified (variant) -- Table 3 ILI row 24, PatchTST/42 MAE column. Same look-back ambiguity as the MSE item (L=104 used for ILI per Table 9 and Figure 3, versus the nominal L=336 for /42). Same metric pairing as the MSE question.

## ngboost
- 无需确认
  - 备注 `concrete_ngboost_nll`：sonnet55: measurable on CPU unclear -- Concrete data file is not in data/uci listing (needs download), but the regression_exp.py script exists. Table 1 NGBoost Concrete is a single value 3.04.
  - 备注 `concrete_ngboost_rmse`：sonnet55: measurable on CPU unclear -- Table 3 NGBoost Concrete mean. Concrete data must be downloaded.

## ecod
- 无需确认
  - 备注 `breastw_ecod_roc_auc`：sonnet55: measurable on CPU unclear -- breastw.mat is not in the repo files; it would need downloading from ODDS.
  - 备注 `mammography_ecod_roc_auc`：sonnet55: measurable on CPU unclear -- mammography.mat is not in the repo files; it would need downloading from ODDS.

## mc_dropout
- 起草者的疑问：用户要对照论文表 1 的原始贝叶斯优化结果，还是要运行仓库当前默认的逐划分网格搜索版本并对照 README 中更新后的结果？两者的调参协议不同；本草案以明确指定的论文表 1 为准。
- 起草者的疑问：论文表 2 另列增加训练轮数及双隐层的结果，仓库默认示例使用增加训练轮数的单隐层设置；是否也需要对照这些后续设置？本草案不将它们作为表 1 目标。
  - 备注 `boston_mc_dropout_test_rmse`：sonnet55: measurable on CPU unclear -- Table 1 Dropout RMSE for Boston is 2.97. The repo's current code uses grid search, not the paper's BO, and the README says it needs a GPU (Theano). On a CPU it is slow, but it should be feasible.；haiku55: underspecified (setting, variant) -- Table 1 Boston Housing row, Dropout RMSE column is 2.97 ±0.19. The locator is correct. The draft picks the paper's Bayesian-optimisation tuning, but the repo default is grid search, and the README reports different numbers for each. The draft also omits the dropout probabilities (0.05 / 0.005) and the training-length setting (10x iterations), which affect the result.
  - 备注 `boston_mc_dropout_test_ll`：sonnet55: measurable on CPU unclear -- Table 1 Dropout LL for Boston is -2.46. The same protocol caveat applies: the repo uses grid search and the paper used BO.；haiku55: underspecified (setting, variant) -- Table 1 Boston Housing row, Dropout LL column is -2.46 ±0.06. The locator is correct. Same ambiguity as the RMSE item: BO tuning in the paper vs. grid search in the repo. Dropout rate, prior length-scale (1e-2) and tau selection procedure are not stated in the draft.

## doc2vecc
- 问题 `imdb_doc2vecc_include_test_error`（表 1，Doc2VecC 行，Error rate % (include test) 列）：all checkers: underspecified (variant) -- sonnet55: The user asked for the Doc2VecC IMDB error rate in Table 1. Table 1 has two columns, include test (10.48) and exclude test (11.70), and the request doesn't pick one. The draft chose 'include test' on its own and admits the README doesn't settle it. Either column could be the intended number. The draft covers only one of the two Table 1 values. The code needs only a CPU plus liblinear. | haiku55: Table 1 Doc2VecC row, include-test column = 10.48. The user did not name a column, and the two columns (include test / exclude test) give different numbers. The draft picked include test on the assumption that go.sh uses it, but the README does not say which protocol go.sh runs. The question should either name the column explicitly or be paired with the exclude-test question. The draft's own open_issues already acknowledge this. Runs on CPU (C code plus liblinear), so no GPU or API is needed.
- 起草者的疑问：表 1 还有“exclude test”列，即仅用训练集及无标签集学习表示。您要复现的是默认选取的“include test”列，还是“exclude test”列？README 未明确 go.sh 对应哪一列。
- sonnet55 认为漏了：Doc2VecC IMDB error rate in Table 1, 'exclude test' column (representation learned on training and unlabeled data only)
- haiku55 认为漏了：imdb_doc2vecc_exclude_test_error: Doc2VecC on IMDB, Table 1 'exclude test' column (representation learned only on train + unlabeled data). The user asked for the Doc2VecC error rate in Table 1 without choosing a column, and this column is not covered by the draft.

## pinn_gradpath
- 起草者的疑问：表 2 同时列出每层 30、50、100 个单元及 3、5、7 个隐藏层的多种结构，用户想要哪一行的 M1/M2 结果？这里暂选 50 units / 5 hidden layers；README 未指定默认复现命令或网络结构，仓库文件清单也不能确认脚本默认配置。
- haiku55 认为漏了：表 2 中其余 8 种结构（30/50/100 units × 3/5/7 hidden layers，去掉已选的 50 units / 5 hidden layers）下的 M1 和 M2 相对 L2 误差未被覆盖；若用户要的是整张表的 M1、M2 结果，需要补充这些行。
  - 备注 `helmholtz2d_m1_relative_l2_50x5`：sonnet55: underspecified (setting) -- The user did not name an architecture. Table 2 has 9 rows, and the draft picks 50x5 on its own.；haiku55: underspecified (variant) -- 表 2 中确有 50 units / 5 hidden layers 行、M1 列。但用户要求的是表 2 的 M1 结果，表中有 9 种结构，草稿只选了一行，且“表格居中”这一选择是草稿自行假定的，用户并未指定。
  - 备注 `helmholtz2d_m2_relative_l2_50x5`：sonnet55: underspecified (setting) -- Same architecture ambiguity as M1.；haiku55: underspecified (variant) -- 表 2 中确有 50 units / 5 hidden layers 行、M2 列。同上，结构选择是草稿假定的，用户未指定；M2 的定义与论文表 1 一致。

## set_transformer
- 起草者的疑问：您要复现的是模型直接输出的 LL0/data 吗？若您特指经过一次 EM 更新后的每点对数似然，则应改用同一行的 LL1/data 列。
- haiku55 认为漏了：synthetic_2d_isab16_pma_ll1_per_data: 同一模型（ISAB(16)+PMA）在二维合成四高斯混合任务中，经过一次 EM 更新后的测试集平均每点对数似然（表 3 的 LL1/data 列；补充材料表 5 同名行）。用户请求的是表 3 中的每点对数似然，而草稿只覆盖了 LL0/data，LL1/data 未被列出。
  - 备注 `synthetic_2d_isab16_pma_ll0_per_data`：haiku55: underspecified (variant) -- Table 3 (Synthetic LL0/data, ISAB (16) + PMA row) and Table 5 in the supplement both list this value. The request says '每点对数似然（表 3）' without choosing LL0 or LL1. Table 3 has both columns, and they give different numbers (LL0 vs LL1 after one EM step), so the variant is ambiguous. The draft resolves it to LL0 and only mentions LL1 in open_issues. The task is small and PyTorch-based, so no GPU is clearly required.

## nngp
- 问题 `mnist_1k_relu_nngp_test_accuracy`（表 1，MNIST:1k 分组，Model (ReLU) 下 GP 行对应的 Test accuracy 列）：sonnet55: not what the user asked for -- The user asked for MNIST 1k NNGP test accuracy from Table 1 and did not say ReLU or tanh. Table 1 reports both (ReLU 0.9279, tanh 0.9266), so the draft's choice of ReLU alone is one reading and leaves out the other. The draft should have one question per nonlinearity. This ReLU question is in scope as one of the two, but in_scope is set to no because the draft picked a single variant without the user's confirmation. The ReLU question itself can be run on a CPU.；all checkers: underspecified (variant) -- sonnet55: The user asked for MNIST 1k NNGP test accuracy from Table 1 and did not say ReLU or tanh. Table 1 reports both (ReLU 0.9279, tanh 0.9266), so the draft's choice of ReLU alone is one reading and leaves out the other. The draft should have one question per nonlinearity. This ReLU question is in scope as one of the two, but in_scope is set to no because the draft picked a single variant without the user's confirmation. The ReLU question itself can be run on a CPU. | haiku55: Table 1 MNIST:1k GP row, ReLU column (GP-20-1.45-0.28) matches the locator. The user did not name a nonlinearity, and Table 1 reports both ReLU and tanh for this setting, so choosing ReLU is an assumption that should be confirmed. The README example uses ReLU, which supports the choice. Runs on CPU with the provided grid data.
- 起草者的疑问：表 1 同时列有 ReLU 和 tanh 的 GP 测试准确率：您希望复现的是按仓库 README 示例选定的 ReLU，还是 tanh？
- sonnet55 认为漏了：MNIST 1000 个训练样本时 tanh NNGP (GP) 的测试准确率（表 1）
- haiku55 认为漏了：MNIST 1000 个训练样本时 tanh 版本的 NNGP（表 1 中 Model (tanh) 下 GP 行的 Test accuracy）：用户未指定非线性，表中同时列有两者，若需要应补充此题
