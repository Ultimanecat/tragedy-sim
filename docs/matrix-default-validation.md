# 矩阵默认切换验证

## 已接入和未完成的部分

FS／BTX 的身份硬域、剧情数量／析取与完整 matcher 已共用。小空间枚举、MAP、矩阵构造恢复和正常重要性提议复用相同支持；软 witness 通过共同后验目标计分，采样使用 target/q 修正提议偏差。合法联合当事人后验也已实现。暗牌采样使用相同公开允许域。公平主线 `ParticleEnsembleProtagonistAgent`、房间与自对弈默认启用 prior 矩阵正常提议和联合当事人；小空间继续精确枚举。原始 `FactorizedBeliefState`／历史 ISMCTS 和联合黑方内部回复保留旧基线。

矩阵格子里的概率是完整合法世界的近似边际；不能独立按格子拼接身份。原始 witness 和析取保留，未投影的关系由完整 matcher 检查。未采到某身份不产生 never，12/12 不产生 always。

## 可续跑的配对评测

```powershell
python -X utf8 -m benchmarks.ai_matrix_validation --output references/ai-calibration/matrix-validation-new.json
```

默认六剧本：FS01、FS-02G、BTX-02G、BTX04、BTX-01G Easy、BTX06。seed 0／3，每组旧路径／prior 矩阵＋联合当事人，共 24 局。使用联合黑方、belief 回应模型、信息权重 0.02；黑方 24 节点／1000 ms，红方 8 候选／12 世界／1000 ms，depth 8、日末 horizon。证据维护另记耗时，软截止不保证端到端一秒。秒级实验与分钟级后续实验分别报告。

`--max-jobs 4` 完成四局后退出；相同命令加 `--resume` 接着运行。续跑必须保持 Python 源码、所选剧本内容／字典顺序和预算完全一致。`--fixed-work` 同时关闭双方墙钟上限；`--variant uniform` 可显式增加变体选择消融。输出已存在时必须显式续跑或使用新路径。

每局按实际 replay 重演全部命令，检查公开硬 witness 和身份知识保留真实初始剧本；每日红方根额外检查矩阵无错误硬排除。这些真值检查在对局后执行，不输入公平 AI。结果与配置核对、审计成功后原子保存；失败记录保留已有完整局数，不计未完成配对。

## 判定与下一步

记录整局胜负、直接胜／最终猜测、猜中数量、回退、响应耗时、完整配对改善／退化数。历史不同源码或配置结果不能合并成单一胜率。

正确性通过与棋力提升分开验收。跨剧本、标准／Easy、留出 seed 的受控比较支持优势后，将主线矩阵提议和联合当事人设为默认，保留旧路径消融；未确认时继续优化候选覆盖、抽样方差或规划，并记录反例。发现矩阵表示本身的致命缺陷时停止切换，与用户讨论。

当前身份查询的实现修正见 [支持集审计](exact-role-support-audit.md)：查询当前杀人狂不能直接确定初始杀人狂；病毒下要保留初始平民，安全旧知识另存。黑方重建历史查询暂取确定知识下界，历史动态答案重建留作后续任务。

## 本批验收与保留边界

192 批次／缓存源码同一 Python 指纹的精度实验、24 局六剧本秒级对弈和四局固定工作量复测均已完整结束。角色边际平均误差五类状态降低约 30%～53%；秒级红胜旧 3/12、矩阵 5/12，固定工作量均 1/2。384 根／5575 命令重演和硬支持审计全部通过，无回退。详细范围与反例见 [对弈报告](matrix-cross-script-comparison.md)，不宣称普遍或统计显著胜率优势。

默认切换的 53 项专项已通过，包括默认／显式矩阵的精确与有限根三牌计划相同、完整 FS 对局与文本 replay 相同、CLI 默认／禁用／Oracle 参数解析、黑方两处回复保持旧基线、房间注册与历史因果诊断。默认源码完整 759 项通过（178.932 秒），日志 `references/matrix-default-enabled-regression-20261013.txt`；所有已录入 FS／BTX 标准剧本的实际三牌服务执行／逐牌等价回归包含其中。切换前 754 项属于前置源码。

实际房间注册入口烟测：选择 BTX-01G／团队公平 AI，默认 192 次提议、12 行动世界，无回退；人类提交黑方三牌后，AI 原子提交 A／B／C 三牌并到 reveal，总共记录六条独立牌执行，清空计划缓存。本机该根约 2.246 秒，不作为平均延迟保证。默认切换 Python 指纹 `63b77dfa833503ee7ba5a92f114fd903872e2214806ed98d6b5f1751b3e71c96`；原算法对照指纹仍为 `c395d03e…`，默认／显式新路径等价另测，不能把前置对弈标为切换后重跑。

旧红方对照须同时禁用两项：

```powershell
python -X utf8 -m benchmarks.ai_self_play --protagonists particle_ensemble --strategy fixed --games 1 --no-matrix-proposals --no-joint-culprits
```

Python 使用 `ParticleEnsembleProtagonistAgent(matrix_proposals=False, joint_culprits=False)`；`play()` 同名参数可显式设为 False。只禁用一项是混合消融。Oracle／其他策略默认不启用这两项，显式开启报错，报告保存实际解析后的布尔值。`ai_matrix_validation` 总是显式选择旧／新路径，默认切换不改变其对照配置；历史因果根比较固定旧当事人，预算比较固定完整旧路径。

终猜联合成功概率另列 TODO：压缩 MAP 代表集和 compatible_count 不能作为完整概率分母；同身份表跨剧情需汇总，先独立枚举验证，再讨论大空间估计。此切片未改变终猜策略。
