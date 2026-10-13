# Codex 会话交接（2026-10-08）

本文是新会话的启动入口，整理截至源码提交 `0ec96eb` 的上下文。本次交接只增加文档。
开始工作时先执行 `git status --short --branch`、`git log -8 --oneline`，确认是否已有后续提交或其他会话的修改。

2026-10-13 补测完成：同源码标准 BTX-01G／BTX06 seed 1／2 八局已结束，与六剧本报告组合后红胜旧 3/16、矩阵 5/16，改善两对、退化零对；407 根／5932 命令审计通过，无回退。默认仍关闭，正对 BTX-01G／BTX06 seed 2 做固定工作量四局复测，报告 `matrix-default-validation-fixed-work-seed2.json`；接续时检查进程及 progress，不根据文字重启。源码不得在评测期间变化。详细表见跨剧本报告；小样本胜率不宣称统计显著。

2026-10-13 最新对比：`7c57978` 同源码六剧本 seed 0／3、旧／prior 矩阵＋联合当事人 24 局已完整结束，红胜均 2/12，303 每日根／4412 命令硬兼容、矩阵真值与 replay 通过，无回退。终猜有升有降，证据每根平均约 160／99 ms，不同轨迹不作严格性能归因。默认保持关闭，目标未完成；继续相同源码标准 BTX-01G／BTX06 seed 1／2 八局，报告路径 `references/ai-calibration/2026-10-13/matrix-default-validation-standard-seeds12.json`。先检查实时进程／报告完整性，不能根据本段文字假定仍运行。见 [跨剧本报告](matrix-cross-script-comparison.md)。

2026-10-13 当前接续：两条接口均已实现，witness 进入矩阵／共同后验，采样使用矩阵硬域、数量／剧情及完整 matcher。主线 `matrix_proposals` 和 `joint_culprits` 仍关闭；未完成跨剧本默认门槛。查询实际返回当前身份，新增 `identity_knowledge` 保存安全初始推导；病毒转变后的杀人狂答案允许初始平民，先前查到的平民不被重查覆盖，原临时工平民答案不暴露秘密身份。黑方对病毒下初始平民的历史查询暂不编造答案。可续跑评测 `benchmarks.ai_matrix_validation` 冻结源码／剧本顺序／预算，默认六剧本 seed 0／3、24 局，每局强制逐命令 replay／硬证据及每日矩阵真值审计，失败保存 incomplete；见 [默认验证](matrix-default-validation.md)。当前验证结果以路线图为准。用户附件目录不触碰，references 产物不强制加入 Git。

2026-10-13 前置支持集切片：`belief_role_solver` 对 FS／BTX 小空间枚举与 MAP 复用矩阵剧情／数量／域，修复随机非法事件占位漏剧情、模仿者额外身份和未来已知当事人占位；普通完成器接收额外亲友性别占用。`PublicEvidence.known_initial_roles` 区分安全初始身份知识；共享输入转换修复临时工替身答案丢失，持续库和共同 target 直接条件化新知识。初始计数清除全部知识字段，先验／soft score 未变；六组额外身份初始计数和 MAP 独立枚举一致。737 项全量通过（164.979 秒），前端未改，见 [支持集审计](exact-role-support-audit.md)。主线矩阵开关仍关闭，目标未完成。下方是前置切片。

2026-10-13 当前切片：矩阵变体新增 `matrix_variant_policy="prior"`（矩阵开发路径默认），历史 `uniform` 可消融；变体按 `N_v/C_p` 抽样，q=`1/(Z*C_p)`，原概率目标／soft witness／行动评分未变。729 项完整回归通过。全部 151 历史根平均 ESS 46.70→53.63；同源码 BTX-01G／BTX06 seed 1／2、联合黑方、固定联合当事人八局，红胜 uniform 0/4→prior 3/4，107 根／1578 命令真值与 replay 通过、无回退。当前所有评测进程已正常结束；来源 `f448dd7b623ff38798896e859c337276d54b62d31af5c712245e803062e40092`，报告 `matrix-prior-paired-seeds12.json` 完整，见 [先验质量提议](prior-mass-matrix-proposals.md)。主线 `matrix_proposals` 仍关闭，用户目标仍未完成：先审计少角色随机事件占位漏支持、Copycat／Irregular MAP 和初始计数，再跑留出 BTX-02G／BTX04／FS、多 seed／Easy；确认优势并完成范围验证后默认启用。历史报告缺 policy 字段时应按 uniform 重建，不能用新默认 prior 复现旧库。下方是前置切片。

2026-10-13 联合当事人接续：`JointCulpritPosterior` 实现原逐天软分乘积条件化到合法重复限制的精确配分／直接采样／边际。共享硬支持接入矩阵和因子信念，跨日约束可产生 always／never；开发 `joint_culprits=True`、评测 `--joint-culprits` 开启直接抽样，默认暂时关闭。726 项全量通过（160.393 秒），冻结库工具保留开关的 5 项另通过；40 个已录入 FS／BTX 难度版本初始域均可构造。U2 同源码十局红胜 3/10→5/10，耗时接近，22 局／3511 命令 replay 与硬兼容完成，已推送 `92933dd`。接着做 U3 同源码对弈消融，再审计少角色任意事件占位遗漏／特殊额外身份 MAP，扩大 seed／剧本检验矩阵默认门槛。当前目标仍未完成；默认切换前禁止把单剧本两胜外推。见 [联合当事人](joint-culprit-posterior.md)。下方是前置切片。

2026-10-13 最新接续：矩阵重要性提议已实现，`matrix_proposals=True` 对非完整枚举 FS／BTX 身份库完全替换旧正常提议，按 `target/q` 保留重复质量，不混入未知密度库；默认暂时关闭。后端 720 项通过，16 局／172 根／2517 命令完整 replay 与真值硬兼容通过。BTX-01G seed 1 对两黑方均红胜；BTX06 仍黑胜；留出 FS-02G／BTX-02G seed 2 胜负保持。FS01 小空间固定工作量开关等价，墙钟结果有波动。用户当前目标是验证优化至确认矩阵更优或发现致命缺陷，随后默认启用；不能用单个好结果验收。正在补同源码主实验基线；后续合法当事人联合采样、少角色事件占位遗漏／额外身份 MAP 审计、多 seed 与新剧本。见 [重要性提议](matrix-importance-proposals.md)及路线图 U。

2026-10-13 共用概率目标首切片：用户要求优先统一概率、避免按单剧本调参，持续沿矩阵路线推进；以路线图 U 为最高优先级。`RolePosteriorTarget` 的 `uniform-printed-casts-v1` 按初始印刷限制计算每剧情分配数，完整／有限库及终猜使用同一目标；观察不改变先验分母。旧提议 RNG、矩阵 RNG、淘汰 RNG 拆开。软分／行动估值／horizon 未改，正常补样仍默认关闭；**提议 q／去重偏差还没有校正**，下一步明确记录 q、target/q 和重复质量，避免直接混入旧库。独立 FS／BTX 四角色排列＋validator 已验证先验质量及各入口一致；特殊额外角色 MAP 和任意事件占位造成的枚举遗漏仍列为后续审计。六局标准 seed 1 基线：FS01 两局直接红胜，01G 黑胜 3/7、5/7，06 黑胜 3/9、6/9；无回退，72 根／1041 命令公开 witness 真值兼容与 replay 通过。源码指纹及复现见 [目标定义](unified-belief-target.md)。旧轨迹重建须检查 recorded_sampling_matches，不将新权重的重建当成旧算法原批次。下方是历史切片。

本批最终完整后端 712 项通过（152.639 秒），新增目标专项 6 项；生产概率变化来源为共同目标与 RNG 隔离，软分参数及行动评分保持。当前目标继续进行，下一切片是提议密度／重复质量校正。

2026-10-12 逐步矩阵回归诊断：新增 `ai_proposal_regression_audit`，固定原命令重建持续库／三维抽样，每条命令记录 witness 增减，56 根三维计数与原 Trace 一致。01G 第二轮第二天补样 17 个，男学生真身份加权支持 17.6%→19.5%；第 60 命令移动不同。两种原世界批次分别偏好旧新完整三牌，冻结库重抽 12／48 世界仍翻转。新第二轮少了偶像被杀的观察，缺少 terminal serial 硬证据，第三轮男学生仅 20%支持；终猜亲友解释先验权重为真实潜伏解释 2 倍。最终 MAP 独立于补样开关；不要把返回对象的占位事件当作完整当事人推断验证。BTX06 医院记者仍在硬域，同人重复限制后的当事人维度条件权重 12.5%，实际 0/12；先独立抽样再拒绝，仅约 15.16%提议通过重复限制。正常混合提议尚无目标密度校正，补样和旧提议／淘汰共 RNG，需要下一阶段受控实验。用户本轮要求诊断，生产算法未改，默认开关保持关闭。完整逐步表、限制及复现见 [退化排查](matrix-regression-step-audit.md)，JSON 在 ignored references；勿据单 seed 宣称胜率退化。

本批完整后端 **706 项通过（145.384 秒）**，新增诊断专项 5 项；56 根真值及四个终猜角色投影均硬兼容，前端未改。

2026-10-12 前期根／正常矩阵提议接续：BTX06 联合黑方第三轮前两天冷启动身份库只有 5 个，大小姐全为平民，真值魔女仍满足硬域；非空库不会触发原恢复。新增默认关闭的 `matrix_proposals=True`，仅非完整枚举的 FS／BTX 旧正常提议不足 `min(64, capacity)` 时矩阵补样，保留硬 matcher／少角色穷举／整套 MAP；与空库恢复分别计数。`ai_self_play`／`ai_mastermind_matrix --matrix-proposals` 只启用实际红方，黑方回应保持基线；开眼配置拒绝该开关。`proposal_summary()` 只读库大小／身份剧情计数，不推进 RNG、不代表后验概率；根比较记录 `search.proposal_diagnostics`。同根库 5→56、大小姐魔女从 0/12→2/12／1/12，第 2 天日末改守医院，有限整轮续演仍全败。正式 `normal-matrix-proposals-seed1.json` 四局仍黑胜、无回退（06 5/9、4/9；01G 3/7、5/7），未证明提升，01G 策略旧 5/7→3/7；暂不默认启用。下一步查混合提议权重／持续库及有限世界覆盖，再查跨日续演；报告 [正常矩阵补样](normal-matrix-proposals-audit.md)。

本次完整后端 701 项通过（181.456 秒），四份 replay 和 54 个每日根／全部失败观察真值硬兼容通过，前端未改。新实战第三轮前两天大小姐魔女均 2/12，第 2 天仍全好感；真实医院当事人记者 0/12，主要抽成局外人（7/12）。该根医院守卫平均分高、尾分低，信息小奖励未越过风险排序。下一步优先查当事人硬域／软权重／有限批次覆盖，再查跨日准备；旧 01G 有唯一男学生的 terminal serial 硬 witness，新轨迹没有对应死亡观察，勿跨局注入答案。下方为前置切片。

2026-10-12 候选覆盖接续：已修复公平提议 24 索引循环与高索引贪心填充不变化；共享 Oracle 提议器保留前缀，24 之后锚点搭配／自由组合确定性采样，公平循环最多 `max(12, 4*nodes)` 轮，保留提议 25% 软墙钟和实际评估上限。新同根报告 `progressive-proposals-budget-probe-32.json` 对旧 32 候选报告的世界／对手指纹均一致，01G 两根 5 秒评估 18→32、新增 17／16 个组合，四根行动仍与旧版相同，06 第 4 天未救下。完整 `progressive-proposals-seed1.json` 四局仍全黑胜、无回退（06 策略 5/9、联合 4/9；01G 5/7、5/7），合计 240.472 秒；四份 replay 和 59 个根／全部失败观察真值硬兼容通过。下一步向前查 BTX06 第 1／2 天准备与评分，随后 01G；有限候选失败不证明无解，联合黑方信念回应共用提议器，不把整局变化归为单侧。指纹、方法及限制见 [候选覆盖审计](joint-proposal-diversity-audit.md)。以下均为前置切片。

2026-10-12 最新预算切片：修复公平粒子证据／世界准备挤占行动墙钟，行动截止从准备结束后开始；同配置可能增加端到端延迟，不能和旧版本称为等总墙钟。新增预算工具 `ai_causal_audit --budget-probe-ms 1000 --budget-probe-ms 5000`，四个历史根（32 候选／12 世界）世界与对手指纹一致；大预算增加评估，仅 BTX06 第 3 天改行动，第 4 天仍失败。另修复地点守卫补牌造成两张禁止密谋互相取消但获奖励，及部分 Oracle 重规划再出禁止密谋；引擎合法集合未改。最终 seed 1 四局仍黑胜（BTX06 4/9、5/9；01G 5/7、5/7），无回退；下一步查 24 索引周期提议的高预算重复和更早的好感／因果线／医院准备。完整 691 项通过（177.366 秒），六份新 replay／硬兼容通过。方法、结果和限制见 [行动预算审计](action-budget-audit.md)。路线图 P1 历史已合并为关键节点，当前任务以该页为准。

本次候选覆盖最新验证：695 项完整后端通过（178.334 秒），四份 replay 和 59 个每日根硬兼容通过；HTTP 断连仍有 Windows 10053 日志，总体通过，前端未改。下方 691／687 等为历史切片。

2026-10-12 最新模型切片：seed 1 的 BTX06／BTX-01G 四局留出旧模型红胜 1/4，无回退；BTX06 两个对手均黑胜 4/9，01G 策略直接红胜、联合黑胜 2/7。发现 FixedStrategy 模拟没有医院事故路线，补充 FS／BTX 动态医院／当事人双门槛进攻，医院流言与传谣人组合被真实引擎反例验证；事件进攻不再选择给当事人降不安。新模型四局全黑胜（5/9、4/9、5/7、5/7），无回退，平均评估候选下降；共享定式也影响黑方搜索，不能把结果归因于单方棋力。下一步同根做红方 1 秒／更大预算与攻击覆盖对照，固定对手模型后再测整局。结果／局限见 [医院路线审计](hospital-route-audit.md)。以下为前置切片。

最新验证：684 项完整后端测试通过（174.588 秒）；raw-risk 配对四份 replay／硬兼容审计通过。前端未改。

2026-10-12 最新评分切片：发现地点守卫 0.08 奖励混进 tail_value，BTX-01G 已知关键人物的密谋风险被医院守卫奖励压过。修复为原始风险尾分优先，地点奖励保留在后置平均值；同候选／模拟分数重排消融确认选择由医院改为偶像。四局新配对 BTX-01G 策略红胜 7/7、联合黑胜 5/7，社区 BTX-45 策略终猜 8/8 红胜、联合第三轮直接红胜；均无回退，整局胜负保持。新联合 BTX-01G 的猜错角色又是男学生／巫女，尚未得到揭露杀人狂的强制死亡，不把前次公开知识带入不同轨迹。下一步看医院事故、不安准备与黑方对偶像堆密谋的权衡，并用 BTX06／留出 seed 检查地点守卫回归。传谣人增加不安，之前写“传谣人密谋增长”已订正。报告 [风险奖励审计](btx01g-risk-shaping-audit.md)；下方为前置切片。

2026-10-12 最新切片：BTX-01G 最新候选顺序版本仍黑胜 5/7、3/7。发现强制杀人狂导致关键人物立即死亡时窗口完成标记缺失，新增 `btx.terminal_mandatory_serial`／`public_btx_terminal_mandatory_serial_route`。组件只从公开死亡与失败的 `phase: day_end` 识别未完成窗口，保留病毒普通人替代，旧日志／可选阶段／替身不生成硬约束。真实反例、矩阵及 source 消融通过；同旧轨迹终猜仍 5/7、3/7，但男学生改猜杀人狂，老师转被误猜亲友，不能宣称整套猜测提升。新完整配对为对策略终猜 7/7 红胜、对联合黑胜 5/7，无回退；下一步审计联合黑方下的传谣人压力与跨日准备，之后留出 seed／Easy。完整后端 682 项通过（177.127 秒），阶段字段加强反例后的 21 项专项通过。详见 [中断窗口审计](btx01g-terminal-window-audit.md)。下方记录均为前置切片。

2026-10-12 最新接续：路线图已精简为 P1–P6。两份新 BTX 失败根确认直接事实已进入硬域，进一步修复固定模拟黑方不发动邪教徒、三牌组合遗漏事件压不安、公平守卫未复用唯一当事人域、优先候选评估顺序相反。最终社区 BTX-45 seed 0、1000 ms／8 候选／12 世界配对红胜两局，分别终猜 8/8 和第三轮直接胜；同旧根公平计划已选择完整三牌防御。公开跨日续演仍失败，知剧本续演可存活，后续策略误差尚未解决。BTX-01G 中间切片两局仍黑胜 5/7，尚未用最终排序重跑；不能据 BTX-45 单种子宣布稳定棋力提升。详细反例／复现／结果见 [失败审计](fs-btx-failure-audit.md)，下一步向前回溯 BTX-01G，随后 FS-02G／BTX04。因果工具支持 `--scenario`／`--probe-day`／`--probe-loop`／`--all-days` 并保存硬域、真实失败时间、输入指纹与完成状态；默认仍只选自杀附近日期。

2026-10-12 新剧本评测：从 `3349758` 出发，FS-02G、BTX-01G／02G、社区 BTX-08／45 标准版 seed 0、公平粒子对策略／联合黑方，共十局完成，红方直接胜 5/10，无出牌回退；十个 replay／107 个根审计通过。FS-02G 暴露旧身份提议完全遗漏可选暴徒，已共享数量方案补全枚举、随机构造、MAP 与矩阵。修复后 FS-02G 两局仍黑胜、无回退，23 根审计通过；有正确候选不保证防御成功。下一步审计 BTX-01G 和社区 BTX-45 的重复失败及两名猜错身份，再扩 seed／Easy 和正常矩阵提议消融。报告与复现见 [新剧本基线](imported-ai-baseline.md)，完整 JSON 保存在忽略目录 `references/ai-calibration/2026-10-12/`。未追踪的 `.codex-remote-attachments/` 属用户附件，本阶段未修改／提交。

最新本批完整后端 678 项通过（174.288 秒），六份新对局 replay 完整重演；前端未改。FS01 原谋杀／死亡和 replay 断言保持，策略变更后的硬编码摘要改为重复固定工作量的一致性校验；完整回归重新跑过。HTTP 断开连接时出现 Windows 10053 线程日志，但相关测试与总体均通过，网络层未改。此前新增剧本／可选暴徒切片为 669 项通过，属于历史记录。

2026-10-10 重构接续：当前顺序以精简后的 [路线图](future-roadmap.md)为准。共享 `PublicBeliefPlanner` 已提取，粒子红方不再继承旧 ISMCTS；房间注册表与大厅收敛完成，旧四个实验 ID 显式停用。开眼保留直接可选，联合黑方用回应模型选项配置。矩阵首切片见 [表示与复用](belief-matrix.md)，当前为观察投影／开发日志并共用黑方身份域，未替换完整采样器。下方接续记录属于历史上下文，不代表最新实施顺序。

随后矩阵扩展到剧情／数量与正式暗牌，构造恢复接入因子信念：仅旧身份库和两条提议路径均为空时触发。共享暗牌域参与世界重建；self-play 可用 `--disable-matrix-recovery` 消融红方恢复。正常库和终猜 MAP 路径保留，完整 matcher 不可省略；四个低预算配对回放等价，实际恢复率收益尚待强黑方根审计。详见 [验证记录](belief-matrix-validation.md)。

最新矩阵接续：强黑方 BTX04／08 四局 72 个历史出牌根，真值无硬排除；关闭／开启恢复均逐根采到 12 世界、批次一致、恢复次数为零。当事人矩阵补齐事件触发快照阈值，与采样器提成共享 `belief_culprit_constraints`；因果日志补传 witness。本批完整后端回归 624 项通过。可复现工具 `benchmarks.ai_belief_matrix_audit`，详见 [历史根审计](belief-matrix-historical-audit.md)。这些是历史根验证，不能报告为新对弈胜率。下一步评估正常身份提议的矩阵开发选项；BTX04 仍需向更早日期审计行动准备与跨日规划。

最新接续：`69c290b` 加入可选 `BeliefAuditTrail` 与 `benchmarks.ai_causal_audit`，最终 578 项测试通过；用法见 [信念日志](belief-audit.md)。开发日志默认关闭，记录证据增减、再次观察、原始时间点、来源、身份／当事人／暗牌样本及历史出牌模型，不能送入玩家界面。原始 BTX04 日志已保存 `references/ai-calibration/2026-10-10/btx04-belief-changes.txt`。

因果审计确认：BTX04 女学生自杀后，第 6 天当事人硬候选唯一为女学生；轮回末公开亲友身份，属于正常轮回末失败，不能推为关键人物立即失败。第二／三轮第 5／6 天原 Trace 都是亲友 12/12。两种黑方的六个失败观察均保留真值。同根日末／轮回末、仅知剧本／知暗牌对照没有救下原轨迹的第 6 天所选计划；有限候选结果不能证明无解。下一步向前几天回溯资源／好感准备、候选覆盖和后续动作模型，完整对局开眼对照仍待进行。报告 `btx04-root-comparison-continuations.json`；不要把该诊断的固定黑方续演当成原 MCTS 黑方或正式胜率。

2026-10-10 接续：强黑方 BTX08 seed 2 完整报告保存在忽略目录 `references/ai-calibration/2026-10-10/btx08-seed2-replays.json`，含完整 replay 与回退授权视图，两个完整回放均重演通过。strategic 黑胜 7/9，joint 黑胜 8/9；前者第 3 轮第 1 天有两次 `no_compatible_factor` 及一次 `no_legal_bundle`。三个根节点的真值均满足硬证据。轮回末及其他硬存在条件现共享 `role_routes` 构造，专项 102 项测试通过；两个回退快照分别用四个 seed 均恢复 12 个合法世界。第三张牌的固定三牌长度拒绝已修复，真实授权根节点现有 12 世界／96 次策略模拟，无回退。公平粒子、两种 Oracle 均支持部分重规划，部分计划不走三牌批量接口；38 项规划器和 6 项接口回归通过。整局重跑尚待完成。离线真值只能审计，禁止用于补样。

随后的完整 570 项回归及 BTX08 seed 2 串行配对通过：两种黑方仍胜（7/9、8/9），回退均为零；见 `btx08-seed2-hard-routes.json` 与校准文档。终猜 MAP 的异格角色域已提前剪枝，构造反例展开 246→8；保存根的完整候选／权重／计数等价，专项 103 项通过。下一步跑完整回归并扩展 BTX04 seed 2，不将单种子结果当棋力排名。

随后完整 571 项回归通过。BTX04 seed 2 配对完成，两种黑方均胜（4/9、6/9），回退均零、真值硬兼容；报告 `btx04-seed2-hard-routes.json`。本批 BTX04/08 四个文本回放均完整重演通过。当前下一步为 BTX02/09/11 等其他剧本及共同 seed，优先审计新增回退、原子搜索超时和 BTX04 重复自杀失败的风险世界覆盖；不直接按离线真值添加身份硬约束。

2026-10-09 接续更新：已补充 BTX 日末强制窗口无死亡尝试的反证组件，修正 BTX10 大小姐被误推为杀人狂。
seed 1、8 候选/32 世界的 BTX10 终猜为 1/9→2/9，BTX04 为 5/9→7/9，BTX08 保持 7/9；均仍黑胜。
`ai_factor_audit` 已保存终猜完整合法观察及真值快照，并支持 `--reanalyze FILE` 离线 source 消融。
本次全量 549 项测试通过。
同日后续接续：补充公开历史联合暗牌提议，修复日末／轮回末 Oracle 在末轮失败后用全知终猜误评存活的问题。
BTX10 seed 1、8 候选/32 世界转为第 4 轮直接红胜；两项各自消融仍黑胜 2/9。
BTX04/08 seed 1 保持黑胜 7/9，FS01 seed 1 保持红胜。全量 553 项测试通过。
`ai_factor_audit --capture-action-worlds` 可保存根观察和采样暗牌／身份联合细节，
`--independent-dark-history` 可关闭新历史提议。仅是离线开发报告，禁止进入玩家界面／公开 replay。
继续接续：FS01 seed 0 的第二轮谋杀日缺少移动已知关键人物的候选，新增硬证据引导的逃离候选后红胜，
`--disable-incident-escape` 完整复现旧败局。候选预算保持不变，无额外奖励；555 项测试通过。
`LoopLossRecord` 每轮汇总的跨命令遗漏已修复，死亡／触发事件从本轮完整日志采集至失败时为止。
FS01 实局第 2 天谋杀现正确记录，决策摘要不变，基准工具 13 项测试通过。接下来进行 A2 强黑方对照。
另修复临时工内部替身进入最终猜测、黑方按运行时角色评分的边界问题。
最终猜测始终枚举初始 cast，AHR 保留每名初始角色表／里两面；完整 559 项测试通过。
强黑方矩阵现逐局原子保存，源码指纹在启动时冻结，读取 `progress.complete` 判断是否完成配对。
工具尚无自动 resume；14 项工具回归通过，包括第二局中断时保留第一局。
2026-10-10：强黑方 BTX08 长局的主要卡点是终猜 MAP 等价 witness 前缀重复枚举，
已加入前缀记忆与身份数量剪枝，保存终猜观察的猜测／权重等字段不变，完整 561 项测试通过。
慢调用可用 `ai_mastermind_matrix --slow-trace-seconds 30`，异常退出也清理计时器。
探索／诊断对局不作等时间排名，下一步串行正式 BTX04/08 配对并审计联合黑方超时。
正式配对已完成：`104aac3` 的 BTX04 两种黑方均胜，BTX08 strategic 黑胜、joint 的红方终猜 9/9 获胜。
后续刷新熵预处理后的回复预算，重跑 BTX08 两种黑方均胜 7/9，joint 最大单步仍 4.415 秒。
先前 3 次回退此次未复现，未取得旧根，不能声称已修复。工具 `--trace` 后续保存完整红方 Trace、
回退合法观察／离线真值及完整 `replay_text`，均只供开发诊断。
另修复文本回放排序 cast 键导致数字选项变化的错误，保存原顺序；已排序旧档可能需要重新导出。
本文下方摘要表属于加入该组件前的历史基线，最新结果与接续项见 [校准审计](ai-cutoff-calibration.md)和 [路线图](future-roadmap.md)。

## 先读什么

1. 根目录 [AGENTS.md](../AGENTS.md)：平铺直叙；阶段完成并验证后提交、推送远端。
2. 本文，随后读 [AI 路线图](future-roadmap.md)：当前任务顺序以该文件为准。
3. [近期实验与审计](ai-cutoff-calibration.md)：最近三个 AI 切片的证据、反例和完整决策摘要。
4. 按任务读 [AI 调优指南](ai-tuning-guide.md)、[witness 组件](witness-components.md)、[覆盖审计](witness-coverage-audit.md)。
5. 前端或联机任务另读 [Web/LAN 路线图](web-and-lan-roadmap.md)、[JSON 协议](json-api.md)和 [README](../README.md)。

[AI 阶段性总结](ai-current-state.md)和 [历史对弈结果](ai-benchmark-results.md)保留了多个旧版本。
其中团队 ISMCTS 的候选公式、旧胜率、旧回复模型不能直接套到当前粒子集成版。
遇到文档冲突，核对当前源码与实验配置；不要把历史章节中的“下一步”当成最新任务。

## 用户方向与约束

- 这是桌游自动裁判和局域网联机工具；规则引擎、公开信息和结算正确性优先。
- 当前 AI 主线覆盖全部已录入 FS/BTX 剧本，避免长期只在两个 FS 剧本调参。
- 红方指主人公，黑方指剧作家。当前强红方是一名参与者控制 A/B/C 的两人局团队 AI。
  独立三主人公 AI 仍在后续计划；不能把三个完整团队 AI 当三个独立席位。
- 身份/剧情、事件当事人、当前暗牌分维维护。跨维关联按实际反例增加，完整关联模型优先级较低。
- 证据维护与行动节点预算分开。证据用于缩小可能世界和最终猜测；仍须记录它的实际耗时。
- 黑方应建模红方实际知识、暗牌回应和可能信念。`full`/`hidden` 开眼回复用于诊断，正式棋力评测注明回复模型。
- 允许未来用牺牲一轮换决定性信息的策略；尚未实现可靠的跨轮回价值评估。
  用户已撤销早期“不得为了信息故意输掉本轮”的绝对限制。
- 信息类能力价值已有微量 shaping。用户明确反对为提高能力使用率而硬加奖励；降不安、防御等能力同样重要。
  重复调查、目标身份已知、异界人首轮不可用、因果线跨轮回代价都要计入。
- 保留随机、固定、朴素 MCTS 等可选基线；新算法要有对照、消融、trace 和独立提交。
- 秒级、分钟级预算分别评测；必要时显式使用每步数分钟档。相同节点数不等于相同时间。
- 规则书以用户图片为优先。不要花大量时间联网找完整规则书；明确规则问题可查用户给的日文 wiki。
  入口为 `https://w.atwiki.jp/rooper/`，角色表 `/pages/58.html`，多语言表 `/pages/92.html`。
- 不实现旧 Haunted Stage 和 Another Horizon；已有 HSA、AHR 替代。OF 已删除。
  角色范围为 37 张中的 35 张，排除 UP 主和仙人。
- 新官方剧本继续由用户提供并人工核对；远程 ECS 部署是独立方向，当前交接不包含部署授权或凭据。

## 项目现在能做什么

Python 3.11+，后端无第三方运行依赖。CLI、Tk GUI、React Web、JSON 服务和 LAN 房间均已实现。
规则集包括 FS、BTX、MZ、MC、HSA、WM、AHR、LL，特殊行动由后端提供合法行动，前端不重复实现规则。
已有 35 张范围内角色、22 个官方基础剧本；难度展开后 40 个官方可选条目。
其中 FS/BTX 为 13 个基础剧本、25 个难度版本。

支持 1 名剧作家加 1–3 名主人公玩家；两名主人公玩家轮流担任真人队长并代管 C。
LL 强制四人。房间、令牌和状态保存在服务内存，重启后房间消失。
SSE 推送 revision 通知，断线自动重连并临时使用条件轮询。
剧作家及两人局团队红方可在前端编辑三牌草稿，原子提交；三人/四人局红方继续单步。

### 代码入口

| 方向 | 文件/目录 | 要点 |
| --- | --- | --- |
| 规则裁判 | `tragedy_sim/game.py`、`engine.py`、`domain.py`、`model.py` | 正式 dispatch、观察、决策历史；搜索有专用轻量转移 |
| 阶段与效果 | `phases/`、`effects/`、`rulesets/` | 按阶段和规则集组合；部分其他规则集代码仍在 `rulesets/legacy/` |
| 场景 | `scenarios/`、`scenario_library.py`、`scenario.py` | 严格验证；公开目录不能暴露剧情、身份、当事人 |
| 公平红方主线 | `particle_ensemble.py` | 有限三牌候选跨同一批世界评价，日末默认 |
| 信念/终猜 | `belief.py`、`ismcts.py` | `PublicEvidence`、分维粒子、独立完整身份 MAP |
| witness | `witness_types.py`、`witness_components.py`、`witness_rules/`、`witness.py` | 编译器读合法观察，matcher 判定假设，组件按规则集复用 |
| 诊断红方 | `oracle_protagonist.py` | 开眼剧本＋明牌/暗牌，支持 day/loop/match |
| 黑方 | `ai.py`、`mcts.py`、`optimized_mcts.py`、`strategic_mcts.py`、`joint_mastermind.py` | 定式、基线树搜索、三牌联合、belief 回复 |
| 估值/信息 | `evaluation.py`、`information_value.py` | 剧本条件化威胁、微量信息价值，不能当校准胜率 |
| 执行/网络 | `ai_decisions.py`、`service.py`、`rooms.py`、`server.py` | `AiDecision` 与 Trace 分离，revision 和授权在服务层 |
| 回放/语言 | `replay.py`、`transcript.py`、`locales/terminology.json` | 结构化 timing、确定性重演、中英日术语 |
| Web | `web/src/` | 地图拖牌、三牌草稿、手机固定操作栏、回放、图片 |

R1–R3 重构及三牌接口接入已完成。继续实现时沿这些模块分工，避免重新堆进 `Game` 或建立难追踪的全局 hook。

## 当前 AI 实际算法

公平红方主线 `ParticleEnsembleProtagonistAgent` 从合法团队观察建立 witness，分别采样剧情/身份、事件当事人和暗牌。
每个采样世界借 Oracle 提出完整三牌组合，随后将同一组合在同一批世界上交叉评价。
每个世界还采样可用黑方路线，采用最危险的采样路线评价；跨世界按存活、尾部及估值等排序。
这仍是有限根候选规划器，尚未建立完整跨日信息集树。`node_limit=8` 在此处限制约 8 个三牌候选，
与旧 ISMCTS 的访问计数及黑方 MCTS 节点数含义不同。

当前默认 horizon 为日末；公平粒子版支持 day/loop，Oracle 支持 day/loop/match。
长 horizon 的后续行动由便宜策略补全，误差随距离累积。公开阶段与能力选择常回退公开防守策略。
终猜独立调用 `FactorizedBeliefState.exact_role_map`，按完整初始身份分配选择 MAP，不依赖行动世界容量。
目标是整套猜对获胜，逐角色正确数用于诊断。

房间中的联合黑方与两人局团队红方通过 `AiDecision.card_plan` 原子提交；执行器不从 `last_trace` 取实际行动。
CLI、自对弈和 rollout 继续按引擎单步顺序执行，缓存后两张牌；这与房间批量执行已有等价回归。
不要为每个模拟候选引入 HTTP、SSE 或服务层事务复制。

## 最近完成的三个切片

### `a5e1265`：BTX04 稀有硬约束补样

BTX04 seed 1、8 候选/32 世界，原第 1 轮第 4 天后有 24 次 `no_compatible_factor`。
真实设置始终满足硬 witness；独立随机提议很难同时满足恋爱剧情、班长/打工仔恋爱身份和指定杀人狂路线。
现在先保留原拒绝采样路径，仅当它完全没有提议时才用 `condition_hard=True` 补样。
补样后仍通过原场景验证器和全部 hard matcher。原 24 次回退降为 0，该局仍黑胜、终猜 5/9。

曾试过全局使用硬条件提议：BTX04 seed 2 转红胜，但 BTX08 seed 1 终猜从 7/9 降到 6/9。
正式实现已经收窄；前述全局试验成绩不能当作当前算法的成绩。

### `dcfd35d`：FS01 临界事件防守候选

FS01 seed 1、8 候选/32 世界，原两轮都在第 3 天因女学生自杀失败。
第二轮已公开知道她是当事人，她不安 2、阈值 3，黑方又在她身上放暗牌，原 8 个组合却没有“不安 -1”。
`_incident_guard_targets` 根据当天日程、硬 `culprit_is`、公开阈值及暗牌目标补一个合法联合候选。
它占用既有候选名额，仍由共同世界评分，不额外奖励该牌。
新防守在 32/32 采样世界存活，实际第二轮获胜；4 世界仍红胜，BTX04/08 对照摘要不变。

FS01 seed 0 的旧 32 世界报告曾红胜，当前源码败局。关闭这个新增候选仍得到完全相同败局。
此差异早于本次候选修改，历史源码/配置变化仍须追查，不能称为本次修改引起的退化。

### `0ec96eb`：BTX08 终猜审计

BTX08 seed 1、8 候选/32 世界复现 7/9：大小姐被猜为传谣人，实际是不安定因子；
情报商被猜为平民，实际是传谣人。真实剧本通过全部硬 witness。
前四个最高权重候选对这两人的传谣人位置打平，实际“未知因子”剧情的权重更低。
终猜前显式公开确认身份数为 1；其他身份也可能通过 witness 间接受约束。
目前未找到足以确定因子位置或区分这两人的公开证据，因此保留生产评分，扩充诊断输出。

`final_role_candidates=323288` 是 `exact_role_map` 在剧情、角色域预过滤层累计的配置数。
它在路线类硬 matcher 前累计，不能称为“323288 套通过全部硬证据的世界”。
Trace 的 `final_belief_roles` 从返回的前列 MAP 方案汇总，不能当完整后验边际。

### 固定工作量的重复性基线

统一条件：`ai_factor_audit`，固定黑方 2 节点、depth 8；粒子红方 8 候选、32 世界、日末；搜索无墙钟截止。

| 剧本、种子 | 当前结果 | 完整决策 SHA-256 |
| --- | --- | --- |
| FS01 seed 1 | 红胜，失败 1 轮 | `6a8c670fed6775415358485c1ef572f3680911177f63f57252738a220fbb89e7` |
| FS01 seed 0 | 黑胜，关闭事件候选也相同 | `05b7e3c10fa511aaa294f47e0bc703e2861bfb347e45405fd3049dcdd32f818d` |
| BTX04 seed 1 | 黑胜，终猜 5/9，无采样回退 | `0a94cae98f24d9172be72726a22c278fbb99c410e15925142a9966593646b632` |
| BTX08 seed 1 | 黑胜，终猜 7/9 | `063d3244a95f5ef03ed2b54da61bd532aae53e3c0df8a0c419e74efadbe9cebf` |

这些摘要验证当前基线；改变策略后摘要变化本身不算错误，须解释行动和结算差异。

## 接下来建议怎样接续

当前仍处于路线图 A1。最近没有运行中的任务或未提交实现。

1. BTX10 seed 1 的终猜硬反证已补，仍应检查为何各轮重复失去关键人物巫女，以及其他身份的信息可辨识性。
2. 追查 FS01 seed 0 当前与旧报告的源码/配置差异；随后按 seed 0–4 建立当前版本的统一回归。
3. BTX08 的进一步工作应检查信息能力是否能获得决定性证据、原行动候选是否覆盖这些路径、黑方沉默造成何种歧义。
   最终合法观察和 witness 已保存，可通过 `ai_factor_audit --reanalyze FILE` 离线反复分析，减少重跑成本。
4. 分拆证据、候选生成、模拟、终猜求解与整局计时。最后一次 BTX08 审计记录异常高耗时约 3749.8 秒，
   早先同摘要多次约 80–86 秒；目前原因未查明，不能用单次异常测算算法成本。
5. A1 稳定后进入 A2：`strategic` 对 `joint --joint-reply-model belief` 的相同墙钟、多种子配对，扩到全部标准 FS/BTX。
6. A4 的整局价值校准、黑方逆向信念、跨日搜索仍未完成。历史校准缺终猜红胜标签，模型只保留在离线基准。

不要一开始重新调整信息类奖励或扩大默认粒子数。先取得可复现的具体失败链和同源码消融。
候选覆盖、暗牌压力、身份覆盖、最终信息不足分别需要对应证据。

## 容易犯错的规则与边界

- 同一时点先同时触发所有强制能力，再按控制方选择的顺序发动可选能力。
  两个杀人狂单独同处的强制效果应保留同时触发，不能顺序杀掉第一人后漏掉另一人的效果。
- 各人独立拥有每轮一次的牌，例如禁止移动、不安 -1、友好 +2；全队可各用三张。
  同日友好 +1 与友好 +2 的冲突按引擎规则处理，候选器不能产生非法组合。
- 时间旅行者：好感 **至少 2** 才满足末日要求；禁止友好对其无效。
  其失败发生在最后一天的日末可选能力窗口，与轮回结束失败是不同可观察时点。
  在适用规则前提下，这个时点是强 witness；充分好感也提供否定时间旅行者解释的证据。
- 因果线依据上一轮的好感在下一轮产生不安，评价信息投资须计入跨轮回风险。
- 公开事件使用结构化 `timing`、kind、target 和状态快照推理。日志中文、翻译文本、剧本标题或稳定 ID 不构成身份证据。
- 初始身份、当前临时身份和能力来源要区分；病毒、因子、临时工/临时工？、模仿者容易误删真值。
- BTX11 曾因采样世界漏掉公开角色配置导致整局回退，现已修复。
  神格登场轮回、大人物领地、禁用牌等公开设置须贯通 view → evidence → sample → determinizer。
- 强制死亡批次、护卫、死亡替代等存在多个解释时，硬 witness 必须保留所有合法解释。
- 最终猜测一次提交整套初始身份，公开正确数量，全对才红胜；不逐人回答或逐人公布正确性。
- 红方只读合法 Observation 和自己的私密调查答案。黑方知识下界只在查身份已实际结算后推知红方获得的答案。
  申请、拒绝和查同身份群不能自动揭示单人身份。
- `last_trace`、隐藏采样世界、完整存档和 `.tlr` 可包含秘密。开发报告和结束后完整回放要遵守各自信息边界。
- Oracle 的 BTX 最终猜测直接使用已知答案；仅看总胜率容易掩盖行动阶段失败，须报告失败轮回和原因。

## 常用运行与验证命令

从仓库根目录运行 Python。Web 构建后重启 Python 服务，否则页面可能仍使用旧产物。

```powershell
python -m tragedy_sim --demo --module BTX
python -m tragedy_sim --gui --module BTX
python -m tragedy_sim --serve
# 浏览器 http://127.0.0.1:8765/
python -m tragedy_sim --host-room --port 8765
# 手机与主机同一 Wi-Fi，使用终端显示的局域网地址
```

前端命令在 `web/` 执行：

```powershell
npm install
npm run build
npm test
npm run lint
npm run test:e2e
# 素材或 resources/data.xml 更新后：npm run assets，再 build
```

Python 验证：

```powershell
python -m unittest discover -q
python -m unittest tests.test_belief tests.test_particle_ensemble -q
python -m unittest tests.test_witness tests.test_witness_components -q
python -m unittest tests.test_ai_card_plans tests.test_card_plans tests.test_rooms tests.test_replay -q
```

最近全量验证为 **543 项通过**（`dcfd35d` 切片，约 137 秒）；`0ec96eb` 的诊断/文档切片验证了 51 项相关测试，
并复现 BTX08 完整摘要。这些是历史结果，修改实现后仍需运行适用测试。本次交接无需重跑长对局。

重点诊断入口：

```powershell
python -m benchmarks.ai_factor_audit --scenario official-fs-01-first-script --seed 1 --nodes 8 --worlds 32 --expected-digest 6a8c670fed6775415358485c1ef572f3680911177f63f57252738a220fbb89e7 --output references/ai-calibration/handoff/fs01.json
python -m benchmarks.ai_factor_audit --scenario official-btx-08-mirror-passcode --seed 1 --nodes 8 --worlds 32 --expected-digest 063d3244a95f5ef03ed2b54da61bd532aae53e3c0df8a0c419e74efadbe9cebf --output references/ai-calibration/handoff/btx08.json
python -m benchmarks.ai_cutoff_calibration --scenario official-btx-10-prologue --seed 1 --games 1 --strategy fixed --mastermind-nodes 2 --protagonist-nodes 8 --protagonist-particles 32 --fixed-work --repeat-check --output references/ai-calibration/handoff/btx10.json
```

`ai_factor_audit` 的黑方、depth、horizon 在工具中固定；仅支持列出的配置参数。
`ai_self_play` 的 CLI 与 `play()` Python 参数不完全相同；独立世界数可用校准工具或 `play(protagonist_particles=...)`。

全矩阵和黑方配对：

```powershell
python -m benchmarks.ai_calibration_matrix --output-dir references/ai-calibration/handoff/matrix --protagonist-nodes 8 --protagonist-particles 32 --games 2 --seed 1 --max-jobs 3
# 后续继续同配置时加 --resume；改源码/剧本/预算会产生新指纹目录
python -m benchmarks.ai_mastermind_matrix --scenario official-btx-04-young-womens-battlefield --games 2 --seed 1 --mastermind-ms 1000 --protagonist-ms 1000 --protagonist-nodes 8 --protagonist-particles 32 --joint-reply-model belief --trace --output references/ai-calibration/handoff/black-pair.json
```

先用 `--help` 核对参数。固定工作量用于复现/标签采集；等时间评测使用墙钟工具并报告实际超时。
矩阵基准串行运行，避免 CPU 竞争改变限时轨迹。Windows 浏览器长局 E2E 也应串行，
并发短连接曾导致 `WSAENOBUFS`，不是 MZ 等规则非确定性。

## 实验资料与报告读取

`references/` 在 `.gitignore` 中，本机有原图、下载资料和完整实验 JSON，新 clone 不会获得这些文件。
本次交接已把结论和复现摘要写进 Git；不要用 `git add -f references/` 将整批原始报告推送。
同一工作目录的新会话可直接读取；换机器时按命令重建所需报告。

- `references/ai-calibration/2026-09-26/paired-seeds/run-ca235d3f4410e6e4/`：旧 4 世界共同 seed 1/2。
- `references/ai-calibration/2026-09-26/paired-seeds/run-0fff68345b298496/`：旧 32 世界共同 seed 1/2。
- `references/ai-calibration/2026-09-29/`：补样、FS01 候选、BTX08 终猜审计与消融。
- 文件名含 `conditioned` 的部分报告对应已放弃的全局硬条件提议；
  `fallback-only`、`incident-guard` 和 `final-audit` 对应后续切片，须结合提交与摘要确认。

PowerShell 读取 JSON：

```powershell
$report = Get-Content references/ai-calibration/2026-09-29/btx08-seed1-final-audit.json | ConvertFrom-Json
$report.final_guesses | Format-Table
$report.final_belief_setups | ConvertTo-Json -Depth 8
# 校准矩阵单局胜负在 .matches[0].red_win；audit 胜负在 .winner
```

报告中 `joint_plan_followup` 是缓存的后续牌，不是新搜索或异常回退。
`no_compatible_factor` 应检查身份和当事人两个维度；`no_legal_bundle` 检查联合候选/手牌/公开设置。
检查顺序为：引擎结算 → 真值 hard 相容 → 采样与重建 → 防守候选覆盖 → 同世界评分 → 最终信息与先验。
先读具体 trace 再归因；不要仅凭提高粒子数后胜负变化推断预算不足。

不同难度、种子、源码指纹、对手、horizon、候选数和世界数都要保留。
Easy 与标准共用秘密，不能当独立样本；缺终猜红胜时不能拟合可靠终猜胜率。

## 交接执行纪律

保留用户未提交修改，避免将其他会话改动混入本次提交。用 `apply_patch` 编辑、`rg` 搜索。
每个完成切片先验收，再 `git diff --check`、明确选择文件 `git add`、commit、push `origin master`。
三牌/信息边界/规则修改必须有对应回归；文档交接只核对路径、命令和 diff。
后续会话没有必要重做已完成的 A3 或重新迁移前端；从本文未完成项接续。
