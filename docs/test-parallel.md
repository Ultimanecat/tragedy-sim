# 并行跑 Python 测试（2026-10-27）

## 为什么全量测试慢

当前全量：

- 1148 项测试
- 单进程串行约 **400.8 秒**
- 前 60 项测试合计约 **317 秒**，占 79%
- 其余 1088 项测试合计约 84 秒

慢的原因不是 `sleep` 或网络等待，而是若干测试真的在跑完整 AI 自对弈、全剧本枚举和引擎搜索。

最慢的单项：

| 测试 | 时间 |
| --- | --- |
| `test_ai_card_plans.test_actual_ai_batch_matches_three_single_decisions` | 36.1s |
| `test_evaluation.test_every_recorded_script_is_bounded_across_reachable_phases` | 32.5s |
| `test_witness.test_true_world_survives_every_public_checkpoint_in_recorded_btx` | 16.6s |
| `test_game.test_seeded_legal_playouts_and_replay` | 16.2s |
| `test_gui.test_complete_gui_callback_flow_for_all_modules` | 14.8s |
| `test_oracle_protagonist.test_worst_hidden_state_blocks_key_intrigue_before_the_last_day` | 12.3s |
| `test_defense_counterexamples.test_refined_regression_plan_survives_all_legal_dark_faces` | 12.2s |

其中 `test_ai_card_plans` 会遍历全部标准 FS/BTX 剧本，并对多种 AI 模式执行单步/批量决策；`test_evaluation` 会遍历 recorded script 的可达阶段。这些都是 CPU 计算。

## 并行方式

本环境没有 `pytest-xdist`，所以新增了仓库内脚本：

```powershell
python benchmarks/run_tests_parallel.py --workers 12
```

做法：

- 按 `tests/test_*.py` 模块拆任务。
- 每个模块一个 `python -m unittest tests.module` 子进程。
- 固定 12 个 worker，动态领取下一个模块，慢模块不会卡住整轮。
- 每个子进程独立导入、独立 RNG、独立临时目录。
- HTTP 测试使用 `127.0.0.1:0` 随机端口，不会互相抢端口。

## 实测

同一份源码：

| 方式 | 墙钟时间 | 结果 |
| --- | --- | --- |
| 单进程串行 | 400.8s | 1148 项通过 |
| 8 worker 并行 | 65.9s | 98 个模块全部通过 |
| 12 worker 并行 | 47.8s | 98 个模块全部通过 |

12 worker 已接近最快模块 `test_ai_card_plans` 的 40s 关键路径，继续加 worker 收益有限。

## 注意事项

- 这个脚本按模块并行，不按测试用例并行；单个模块内部仍串行。
- 时间敏感测试在 CPU 竞争下理论上可能变慢；本次 8/12 worker 全量均通过。若以后出现偶发失败，先把该模块标为串行。
- 全量测试和后台 AI 基准同时跑会互相抢 CPU，墙钟时间不可比较。
- 提交前仍建议至少跑一次串行全量，或用 12 worker 全量通过后再跑受影响模块。
