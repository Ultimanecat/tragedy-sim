# Codex 会话交接（2026-10-13）

先执行 `git status --short --branch`、`git log -8 --oneline`，以当前源码和 [AI 路线图](future-roadmap.md)为准。本页保留当前实现、验证证据和易错信息；历史实验进入专题报告，不按旧报告的“下一步”开展工作。

## 最新状态

公平 FS／BTX 粒子红方已默认使用 prior 矩阵重要性提议和合法联合当事人。主线构造器、房间工厂、self-play API／CLI、黑方对弈 CLI 一致；两处联合黑方内部红方模型显式保持旧提议＋旧当事人，避免同时更换对手。原始 `FactorizedBeliefState`／历史 ISMCTS 保留旧基线。

默认切换源码 Python 指纹 `63b77dfa833503ee7ba5a92f114fd903872e2214806ed98d6b5f1751b3e71c96`：53 项专项通过，完整 759 项通过（178.932 秒）。实际房间选择公平 AI 后，BTX-01G 第一天默认 192 次提议／12 行动世界，无回退，原子执行三张红牌到 reveal；本机耗时 2.246 秒，仅为单根烟测。前端未改。

切换前的同源码 `2398cf4`、Python 指纹 `c395d03e…` 完成：

- 五类公开状态各 16 seed，矩阵平均身份 TV 降低约 30%～53%；缓存开／关完整候选、q 和 RNG 等价。
- 六剧本 seed 0／3、24 局秒级：红胜旧 3/12／矩阵 5/12，改善两对、退化零对；BTX06 终猜下降。
- BTX04／BTX-01G Easy seed 3、四局固定工作量：双方红胜均 1/2，BTX04 终猜旧 5/9／新 7/9，Easy 均 7/7。
- 384 每日根／5575 命令全部 replay 和硬支持审计通过，无行动回退。未发现矩阵表示的致命缺陷；不宣称所有剧本／预算下严格更强或统计显著胜率提升。

完整报告位于忽略目录 `references/ai-calibration/2026-10-13/`，文件 `matrix-posterior-accuracy-192-cached-16trials.json`、`matrix-default-validation-192-cached-seeds03.json`、`matrix-default-validation-192-fixed-work-seed3.json`。Git 中保留 [精度](matrix-posterior-accuracy.md)、[对弈表](matrix-cross-script-comparison.md)和 [默认验收](matrix-default-validation.md)。这些任务均已结束；接续时仍须核对真实进程／报告，不从本文推断新任务是否运行。

权限恢复后临时目录和本机 HTTP 测试均可运行；此前 WinError 5／10013 是受限环境记录，不修改测试断言、网络代码或 Windows 防火墙规避。用户未追踪 `.codex-remote-attachments/` 不触碰，`references/` 不强制加入 Git。

## 下一步

1. 终猜联合成功概率：当前压缩 MAP 只保留代表，未累计完整后验质量；同身份表跨剧情先汇总，再归一化全部合法世界。小空间独立枚举，大空间加权计数／重要性估计记录误差与 ESS。不能归一化 top 候选、相乘角色边际或把 compatible_count 当概率分母。本次未改终猜。
   用户追加：每次 witness 变化和行动判定／结算／决策记录概率前后值、delta 及推荐切换，复用 BeliefAuditTrail，供 debug 和黑方信息隐藏评估。默认关闭、独立诊断 RNG／计时、保留同时批次及观察权限；见 [详细计划](final-guess-probability-audit.md)。尚未实现，不把未来示例当已有日志。
2. FS-02G／BTX04／BTX06 的危险覆盖、联合防御候选和更早的资源准备；保留日末基线，短跨日规划单独消融。
3. 信息收益与黑方实际信念／回应模型，先做终猜概率诊断再讨论信息隐藏与跨轮回价值。
4. 扩默认矩阵版的 seed／标准与 Easy，再按开眼 → witness／矩阵 → 公平规划迁移 MC。更多未来项见路线图。

## 实际算法与代码入口

| 方向 | 入口 | 要点 |
| --- | --- | --- |
| 规则／阶段 | `game.py`、`engine.py`、`phases/`、`effects/`、`rulesets/` | 正式裁判与轻量搜索转移，禁止全局难追踪 hook |
| 公平红方 | `particle_ensemble.py`、`belief_planner.py` | 合法团队观察，完整三牌候选跨共同世界评价 |
| 后验 | `belief.py`、`belief_posterior.py` | 共同目标、分维维护、target/q 与重复质量 |
| 矩阵／支持 | `belief_matrix.py`、`belief_plot_constraints.py`、`belief_matrix_sampler.py`、`belief_role_solver.py` | 硬域／数量／析取，合法完整分配，小空间枚举和 MAP |
| 当事人／暗牌 | `belief_culprit_constraints.py`、`belief_culprit_posterior.py`、`belief_dark_constraints.py` | 联合重复限制及公开暗牌 all-different |
| witness | `witness_components.py`、`witness_rules/`、`witness.py` | 编译器读观察、matcher 检查世界，按规则集复用 |
| 黑方／开眼 | `joint_mastermind.py`、`strategic_mcts.py`、`oracle_protagonist.py` | 三牌联合、红方回应；开眼仅诊断／趣味 |
| 执行／网络 | `ai_registry.py`、`ai_decisions.py`、`service.py`、`rooms.py`、`server.py` | AiDecision 与 Trace 分离，revision、授权、SSE |
| 剧本／回放 | `scenarios/`、`scenario_library.py`、`replay.py`、`transcript.py` | 严格验证、结构化时间点和确定性重演 |

路径均相对 `tragedy_sim/`。红方为有限根候选规划器，尚无完整跨日信息集树。8 节点表示约 8 个三牌候选，与黑方 MCTS 节点意义不同。每个世界用采样的危险黑方路线评价，跨世界按存活、原始尾部风险与后置平均值排序；有限采样／候选不能证明必胜或无解。

默认身份目标为公开 setup 下等权剧情组合、每剧情内印刷合法初始身份分配等权，乘硬兼容及启发式 `2**soft_score`。先验及软似然未校准为真实人类剧作家分布。新鲜角色重要性批次固定 `min(192, capacity)`，不混入无 q 旧库、不按随机 ESS 停采。行动世界数与身份提议数不同，证据维护不占行动节点或行动墙钟，端到端响应仍有额外成本。

身份／剧情、当事人、暗牌分维维护。析取保留，未投影关系继续完整 matcher 检查；未采到不写 never，样本 12/12 不写 always。主线小空间精确枚举，终猜仍独立压缩 MAP，不依赖行动世界容量。终猜输出的前列边际不是完整后验。

房间通过 `AiDecision.card_plan` 原子提交，CLI／rollout 缓存后两张并按引擎单步执行；已有全部已录入 FS／BTX 标准剧本的等价回归。执行器不从 last_trace 取行动，模拟不走 HTTP／SSE。部分出牌后的重规划只补未出席位；多人权限不得扩成团队权限。

## 易错规则与信息边界

- 同时点先同时触发强制能力，再由控制方任意排序可选能力。两个杀人狂单独同处必须同时死亡。
- 各主人公各自有轮回限次牌；团队可各用禁止移动、不安 -1、友好 +2。同日友好 +1／+2 冲突必须用引擎合法行动校验。
- 时间旅行者好感至少 2；禁止好感无效；其失败在末日日末可选窗口，区别于轮回结束。因果线按上一轮好感产生下一轮不安。
- 查询返回当前身份。病毒下当前杀人狂可来自初始平民；安全初始推导另存 `initial_roles`，不被后续重查覆盖。原临时工平民答案不能揭露其初始身份，替身需映射回初始列。
- 初始身份、能力来源与死亡替代区分，硬 witness 保留所有合法解释。拒绝／申请／同身份群调查不自动给出单人答案。
- 只用结构化 timing、kind 和公开快照推理；中文文本、标题或剧本 ID 不作证据。公开角色配置／禁用牌等需贯通 view → evidence → sample → determinizer。
- 最终一次猜整套初始身份，全对才胜，正确数量仅供审计。Oracle 终猜直接用答案，不能只看总胜率评估行动防御。
- 公平红方只读合法视图和自己的私密答案；黑方仅补入由已完成公开查询必然推知的答案，病毒历史查询目前取保守知识下界。
- 内部矩阵、采样世界、Trace、真值诊断和完整存档不能进入玩家界面／SSE。开发完整 replay 与玩家观察回放遵守各自信息边界。

## 常用命令

从仓库根目录运行：

```powershell
python -m tragedy_sim --gui --module BTX
python -m tragedy_sim --serve
python -m tragedy_sim --host-room --port 8765
python -X utf8 -m unittest discover -s tests
python -X utf8 -m unittest tests.test_matrix_defaults tests.test_role_importance tests.test_role_support_solver tests.test_joint_culprit_posterior
```

本地浏览器 `http://127.0.0.1:8765/`；LAN 手机使用终端显示地址，同 Wi-Fi。前端构建在 `web/` 中执行 `npm run build`，随后重启 Python 服务；前端另有 test、lint、test:e2e。房间及令牌在内存，重启后消失；LL 强制四人，其余支持 1 名黑方＋1–3 名真人红方。

```powershell
# 默认矩阵红方；两个负开关同时使用才是完整旧消融
python -X utf8 -m benchmarks.ai_self_play --protagonists particle_ensemble --strategy fixed --games 1
python -X utf8 -m benchmarks.ai_self_play --protagonists particle_ensemble --strategy fixed --games 1 --no-matrix-proposals --no-joint-culprits
# 新输出名，默认六剧本 seed 0/3、旧/新 24 局，每局强制 replay/硬支持审计
python -X utf8 -m benchmarks.ai_matrix_validation --output references/ai-calibration/matrix-new.json --max-jobs 4
# 同源码/剧本顺序/预算续跑加 --resume；--fixed-work 关闭双方墙钟
python -X utf8 -m benchmarks.ai_matrix_posterior_accuracy --output references/ai-calibration/accuracy-new.json
python -X utf8 -m benchmarks.ai_mastermind_matrix --scenario official-btx-04-young-womens-battlefield --games 2 --seed 1 --mastermind-ms 1000 --protagonist-ms 1000 --protagonist-nodes 8 --protagonist-particles 12 --joint-reply-model belief --trace --output references/ai-calibration/black-new.json
```

先用 --help 核对参数。self-play API 用 `None` 解析实际策略的默认：公平粒子两项 True，其他策略 False；显式给 Oracle 开启报错。联合黑方回复与历史因果工具显式固定旧基线，默认切换不让旧根诊断暗中改算法。

## 诊断与执行纪律

遇到失败按：引擎结算 → 真值 hard 兼容 → 采样／重建 → 防御候选覆盖 → 同世界评分 → 信息轨迹／终猜模型。joint_plan_followup 是缓存后续牌；no_compatible_factor 查身份与当事人，no_legal_bundle 查联合候选／手牌／公开配置。不要只凭增加粒子后胜负变化归因于预算。

校准串行、空闲机器运行；保留源码、剧本顺序、难度、seed、对手、horizon、节点、世界数和实际耗时。Easy 与标准共用秘密，不能视为独立剧本。报告 progress.complete／paired_summary 及真实进程决定任务状态，观察超时不重启。墙钟是软截止，原子评价可超限；证据时间单列。

`references/` 被忽略，新 clone 没有本机图片和完整 JSON。专题报告有方法和摘要，按新输出路径重建；禁止 force-add 原始产物。原始规则图片优先，日文 wiki 仅作明确规则核对，不花大量时间搜索完整规则书。旧 HS／AH 已被 HSA／AHR 替代，OF 已删除，UP 主和仙人不在角色范围。

用 apply_patch 编辑、rg 搜索，保护用户改动和附件。每阶段验证后 diff --check，明确选文件提交并推送 origin master。AI 调优参考 [指南](ai-tuning-guide.md)、[witness 组件](witness-components.md)、[覆盖审计](witness-coverage-audit.md)。前端／LAN 任务另读 [路线图](web-and-lan-roadmap.md)、[JSON 协议](json-api.md)和 [README](../README.md)。
