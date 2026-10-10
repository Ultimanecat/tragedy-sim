# 剧本数据目录

把经过核对、可公开提交的剧本 JSON 放在此目录顶层。服务启动后会自动发现顶层的 `*.json`，逐一通过引擎的严格校验，
并按剧本内的 `id` 加入 Web 大厅目录；无需修改 Python 或前端代码。

格式以 `examples/*-tutorial.json` 为准。文件包含身份、规则和事件当事人等完整答案，不应直接交给主人公玩家。
`GET /v1/scenarios` 只返回标题、规则集、天数和可选/默认轮回数，不会返回这些秘密。

截至 2026-10-10，顶层包含 31 个可玩剧本文件，展开轮回数后为 55 个条目：26 个官方本对应 46 个条目，
5 个社区本对应 9 个条目；另有八个内置原创教学局。原始 22 个官方本来自项目维护者提供的卡图：
FS 2 个、BT/BTX 11 个、MZ 4 个、MC 5 个。网站采集新增官方 FS 2 个、BTX 2 个，社区 FS 1 个、BTX 4 个。
BT 卡按 BTX 规则集运行。原始参考图片及临时采集脚本位于被 Git 忽略的 `references/`，不会随仓库发布。

部分卡面允许多个轮回数，源 JSON 用 `loop_options` 保存全部合法值。目录加载时会把它们展开为独立剧本：
最少轮回数使用原 ID 和标题，更多轮回数依次追加 `-easy` / `-very-easy` 与 `(Easy)` / `(Very Easy)`。
每个大厅条目因此只有一个确定轮回数，房间、回放和 AI 基准不会再混淆难度；更多轮回对主人公方更容易。
`role_slots` 仅用于记录卡面明确给出的、与通用速查推导不同的精确身份槽；`special_rules` 只接受引擎已经显式
支持并校验的剧本规则。新增剧本不得用这些字段绕开普通校验。

## 网站资料与分类

[tragic-aiplay 的剧本收藏页](https://tragic-aiplay.cn/played_scripts.html)采集数据保存在 `sources/tragic-aiplay/`。
临时昵称使用站点提供的一键解锁功能后，读取公开信息与非公开剧本配置；仓库未保存认证信息、玩家通关记录、评论或结局剧情。

- [collection-index.json](sources/tragic-aiplay/collection-index.json)：全部 75 个源剧本的分类、兼容状态与可玩文件关系。
- [import-index.json](sources/tragic-aiplay/import-index.json)：11 个 G 编号本；对应源档案位于该目录顶层。
- [community-index.json](sources/tragic-aiplay/community-index.json)：64 个社区本；对应源档案位于 `community/`。

分类沿用维护者提供的约定：网站编号含 G 记为 `official`（官方），其余记为 `community`（社区）。
网站编号与本项目早先的官方卡图编号分别保存，例如网站 BTX-07G 对应现有《序文》BTX-10，不根据编号直接覆盖现有文件。
`has_special_rules` 根据网站公开表中是否存在非空 `special_rules` 设置；兼容状态单独记录。

| 来源 | 特殊规则标记 | 源剧本数 | 当前处理 |
| --- | --- | ---: | --- |
| 官方 | 无 | 8 | 新增 4 个，已有 3 个，冲突待核对 1 个 |
| 官方 | 有 | 3 | 归档待支持 |
| 社区 | 无 | 11 | 新增 5 个，配置不兼容 6 个 |
| 社区 | 有 | 53 | 归档待支持 |

可玩社区本为 BTX-08、BTX-129、BTX-41、BTX-45、FS-27，标题带 `[社区·无特殊规则]` 标记。
无特殊规则的标记描述网站公开表；这些剧本仍需通过角色、事件、身份槽和角色配置校验。
有特殊规则的档案保留规则原文与可提取的固定出牌等配置段，尚未加入可玩目录。

## 源档案字段与兼容状态

每个源档案包含 `origin` / `origin_label`、`has_special_rules` / `special_rules_label`，以及网站 ID、编号、
来源文件名和采集日期。`public_setup` 保留轮回数、天数、公开事件与特殊规则；`source_setup_text` 保留配置原文，
社区档案的 `source_configuration_sections` 保存额外的固定出牌、隐藏规则等配置段。
`normalized_setup` 是使用本项目 ID 的转换结果，部分待支持档案可能只有不完整或不合法的转换结果。
`engine_setup_valid` 只表示基础配置能否通过校验；特殊规则的执行还由 `status` 决定。

| `status` | 含义 |
| --- | --- |
| `imported` | 已新增可玩文件，`playable_file` 指向顶层 JSON |
| `already_present` | 与已有剧本配置一致，记录现有文件并去重 |
| `existing_data_conflict` | 来源与现有数据有差异，保留双方并等待核对 |
| `blocked_special_rules` | 尚未支持特殊规则，仅归档 |
| `blocked_incompatible_setup` | 角色、角色参数、事件或模组等不兼容，仅归档 |

BTX-07G 的源文将男学生设为心上人、女学生设为求爱者，现有《序文》将两者反置；未覆盖已有数据。
不兼容社区本 BTX-105、BTX-42、MC-27、MC-63、MC-66 涉及当前模组未支持的角色，HSA-31 涉及学者初始标记的固定配置。

所有源档案包含剧本秘密，供维护与核对使用。当前 `GET /v1/scenarios` 的 `source` 只区分 `tutorial` / `library`，
官方／社区及特殊规则字段保存在资料索引中；源档案不会通过该接口下发，也不会被自动创建为游戏。

## 后续录入与验证

1. 保留来源编号、公开表和配置原文，填写分类及兼容状态；采集密码与会话保存在临时环境中。
2. 映射角色、身份、规则和事件 ID，明确神灵登场轮回、转校生登场日及大人物领地等参数，核对公开事件与私有当事人。
3. 与既有配置去重；发现差异时保留冲突记录，核对后再修改可玩文件。
4. 校验通过且规则可执行时，把可玩 JSON 放入顶层；待支持资料留在 `sources/`，更新分类索引与统计。
5. 运行目录及数据回归测试：

```powershell
python -m unittest tests.test_scenario_library tests.test_scenario_import_data
```

目录测试依据顶层文件和 `loop_options` 校验条目与开局，不固定总数量；导入测试核对索引、分类、去重配置与归档边界，
并为当前可玩社区本的每个难度运行合法行动流程到正式胜负。后续人工试玩发现的规则问题另补引擎回归测试。
FS/BTX 的估值上下文测试及 BTX 的真实世界 witness 检查覆盖当前目录中的所有对应剧本；校准恢复测试按实际运行的
剧本 ID 定位断点文件，支持官方与社区本共同参与。完整回归可运行 `python -m unittest discover -s tests`。
