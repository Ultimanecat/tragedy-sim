# 基础行动牌结算（FS / BTX / OF 共用）

本文记录独立 `ActionGame` / `--practice` 的规则与最初里程碑。
默认命令行现已切换为完整对局；能力、事件和胜负的新增实现见 [完整对局](rules-match.md)。

## 依据优先级

1. 用户提供的 FS、BTX、OF 模组图片；作为模组内容的第一优先级。
2. `resources/data.xml` 的牌组索引及对应中文牌面；确认独立副本、限次标记和冲突效果。
3. 对图片没有列出的通用放牌/回收流程，补查英文《Player's Handbook》第 21–22 页
   （[手册镜像](https://cdn.1j1ju.com/medias/4a/87/06-tragedy-looper-rulebook.pdf)）。
   仅补充基础流程，不引入英文 Basic Tragedy 的身份或事件覆盖 BTX。

本次直接查看的主要本地资料：

| 资料 | 图像 |
| --- | --- |
| FirstSteps(FS) | [FS](../resources/rulebooks/0b2d84f17c995d604bf04e818f20af880a5e5a4d388d87450e5969933f33a90b.png) |
| BasicTragedyX(BTX) | [BTX](../resources/rulebooks/52184bc7f3f57b2166130ecfe1d3579412161208d72faff5f1164fab99a4bf64.png) |
| OldFashion(OF) | [OF](../resources/rulebooks/3fa84bd5c4510724dee88df812473d947da2b1b2e27a9e67ccfa04662756bf76.png) |
| 主人公禁止密谋 | [牌面](../resources/4ecef910e3551883a48b174eadb3e9eb92b8d3b1d61f7d404dfc89b3c12e0f23.png) |
| 主人公纵向移动 | [牌面](../resources/c78d47c868ea8c38b52295758384b40bd14109fdebe0070fecc402c5b42d9551.png) |
| 主人公移动禁止 | [牌面](../resources/90449762e653bc0c8db066cfbb7e9ba580a24e8cca9b01435373d635a928106a.png) |
| 主人公不安 -1 | [牌面](../resources/252da5fa4bc3436afc22a0b819355d7ae835a46fb975ffb4a95529a41486a677.png) |
| 主人公友好 +2 | [牌面](../resources/5dd6768f4dbb0fdaf5dc80da9b7201c3f31d13516625b3c1c509404fc88f096f.png) |
| 剧作家斜向移动 | [牌面](../resources/fc1344cb1fff7b4f4de9f4f95eeb3869aab7a2d4b830f864beb0289407af6b46.png) |
| 剧作家密谋 +2 | [牌面](../resources/bdb310ea355bd01cd1f77107d6b0f37d5b3e35efe4121c9d21661c865af42d94.png) |
| 领队 | [牌面](../resources/5b960b9c8057a8a647074cdcadd27d2053bdfd6608cd231aee4ce89416ad4e81.png) |

`resources/rulebooks/` 内是原图副本；`data.xml` 的 front 值对应 `resources/<front>.png`。
索引和图片不是可执行配置，也没有运行其中的脚本。

## 已实现与测试对应

| 行为 | 主要测试（tests/test_actions.py） |
| --- | --- |
| 剧作家 10 张；主人公 A/B/C 各 8 张，牌组独立 | `test_deck_contents`、`test_decks_match_resource_index` |
| 剧作家三张，然后从领队开始主人公各一张 | `test_three_master_cards_then_each_hero_in_leader_order` |
| 同阵营不得重复目标，对立阵营可以共用目标 | `test_protagonists_cannot_share_target_or_play_twice` |
| 揭示前不改变棋盘；暗牌内容只向出牌者可见 | `test_only_own_facedown_cards_are_visible` |
| 同方向两张移动只移动一次，不是抵消 | `test_movement_table_all_start_locations` |
| 横+纵=斜，斜+横=纵，斜+纵=横 | 同上，覆盖四个起点 |
| 移动禁止优先；移动的最终落点不得进入禁行区域 | 同上及 `test_forbidden_location_checks_final_combined_move` |
| 一张禁止密谋仅作用于自己的目标；两张或三张全场失效 | `test_single_forbid_intrigue_blocks_character_or_location`、`test_two_or_three_forbid_intrigues_cancel_globally` |
| 禁止不安阻止增减，禁止友好阻止友好增加 | `test_other_forbids` |
| 不安增加先于减少，计数物不低于零 | `test_paranoia_add_then_remove_and_floor_zero` |
| 任意牌可放地点佯攻，但只有密谋及其禁止对地点有效 | `test_any_card_can_bluff_on_location` |
| 所有移动先于其他计数物结算；角色牌上的行动仍作用于该角色 | `test_movement_resolves_before_counters_and_counters_stay_with_target` |
| 结算后普通牌立即回手；限次牌即使无效也公开留置 | `test_hands_return_on_resolve_and_limited_cards_are_independent` |

阶段结构：`mastermind → protagonists → reveal → resolved`。
完整游戏在行动结算之后还有其他步骤，本阶段刻意停在 `resolved`。

## 独立练习模式的边界

- 任何身份、角色能力或模组特殊规则；包括会影响行动结算的邪教徒、时间旅行者等。
- 好感/友好能力、剧作家能力、事件、死亡触发、胜负及最终猜测。
- 不同人数的座位分配、通信限制、联机及 AI。
- 正式的日末/轮回开始结算；`next` 和 `reset` 只是反复验证出牌用的练习按钮。

上述边界仅适用于 `ActionGame` / `--practice`，不适用于新的 `Game` 完整对局。
练习棋盘上的角色只有位置、禁行区域和三个计数物，没有隐藏身份。
练习默认五个角色便于验证出牌，不是官方剧本；完整模式从经过校验的剧本载入。
