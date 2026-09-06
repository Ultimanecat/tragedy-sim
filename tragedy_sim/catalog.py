"""Ruleset content transcribed from the user's sheets; no executable script data."""

from dataclasses import dataclass

ROLE_NAMES = {"ordinary": "平民", "key": "关键人物", "killer": "杀手", "brain": "主谋",
              "cultist": "邪教徒", "conspiracy": "传谣人", "serial": "杀人狂",
              "curmudgeon": "暴徒", "friend": "亲友", "time_traveler": "时间旅行者",
              "witch": "魔女", "loved": "心上人", "lover": "求爱者", "factor": "不安定因子",
              "puppet": "傀儡", "assassin": "刺客", "terrorist": "恐怖分子",
              "returner_enemy": "归来者·敌", "returner_friend": "归来者·友",
              "trickster": "捣蛋鬼", "ninja": "忍者", "obsessive": "强迫症",
              "magician": "魔术师", "immortal": "永生者", "prophet": "预言家",
              "poisoner": "投毒者", "fool": "愚者", "paranoid": "偏执狂",
              "psychiatrist": "心理医生", "detective": "侦探", "twin": "双胞胎",
              "vampire": "吸血鬼", "werewolf": "狼人", "nightmare": "梦魇",
              "ghost": "鬼魂", "paper_tiger": "纸老虎", "chicken": "胆小鬼",
              "zombie": "丧尸", "sacrifice": "祭品", "deep_one": "深潜者",
              "wizard": "巫师", "witness": "目击者", "faceless": "无面者"}
REFUSAL = {"killer": "optional", "brain": "optional", "curmudgeon": "optional",
           "factor": "optional", "cultist": "mandatory", "witch": "mandatory",
           "puppet": "optional", "assassin": "optional", "terrorist": "optional",
           "returner_enemy": "optional", "trickster": "optional"}
REFUSAL.update({"ninja": "optional", "obsessive": "mandatory"})
REFUSAL.update({"poisoner": "optional", "paranoid": "mandatory"})
REFUSAL.update({"vampire": "optional", "werewolf": "optional", "nightmare": "optional",
                "witch": "mandatory"})
REFUSAL.update({"deep_one": "optional", "paranoid": "mandatory", "faceless": "optional"})
INCIDENT_NAMES = {"murder": "谋杀", "unease": "不安扩散", "suicide": "自杀",
                  "hospital": "医院事故", "faraway": "远距离杀人", "missing": "失踪",
                  "spreading": "散播", "foul_play": "邪气污染", "butterfly": "蝴蝶效应",
                  "malicious_rumor": "恶意谣言", "poison_gas": "毒气扩散",
                  "exposure": "曝光", "time_distortion": "时空扭曲", "confession": "自白"}
INCIDENT_NAMES.update({"serial_murder": "连续杀人", "covert_activity": "隐蔽活动",
                       "riot": "暴乱", "breakthrough": "破局", "fake_suicide": "伪装自杀",
                       "fake_incident": "伪造事件"})
INCIDENT_NAMES.update({"terror_attack": "恐怖袭击", "omen": "前兆",
                       "bizarre_murder": "猎奇杀人", "suspicious_letter": "可疑信件",
                       "lockdown": "封锁", "silver_bullet": "银色子弹"})
INCIDENT_NAMES.update({"frenzied_murder": "癫狂杀人", "funeral": "送葬",
                       "curse_declaration": "宣告诅咒", "barricade": "孤守",
                       "frenzied_night": "疯狂之夜", "curse_awakening": "诅咒活化",
                       "filth_overflow": "污秽溢出", "dead_apocalypse": "死者默示录"})
INCIDENT_NAMES.update({"mass_suicide": "集体自杀", "extinction": "灭绝之灾",
                       "dagon_whisper": "达贡黑井之息", "discovery": "发现"})
# id: (name, Y/X, required roles). Duplicate roles are capped by their printed maximum.
PLOTS = {
    "murder_plan": ("谋杀计划", "Y", {"key": 1, "killer": 1, "brain": 1}),
    "avenger": ("复仇的火种", "Y", {"brain": 1}),
    "protect": ("守护此地", "Y", {"key": 1, "cultist": 1}),
    "ripper": ("开膛者的魔影", "X", {"conspiracy": 1, "serial": 1}),
    "rumor": ("流言四起", "X", {"conspiracy": 1}),
    "hideous": ("最黑暗的剧本", "X", {"conspiracy": 1, "friend": 1}),
    "sealed": ("被封印的邪灵", "Y", {"brain": 1, "cultist": 1}),
    "sign": ("和我签订契约吧！", "Y", {"key": 1}),
    "change": ("改变未来", "Y", {"cultist": 1, "time_traveler": 1}),
    "bomb": ("巨大定时炸弹 X", "Y", {"witch": 1}),
    "friends": ("好友圈", "X", {"friend": 2, "conspiracy": 1}),
    "love": ("恋爱风景线", "X", {"loved": 1, "lover": 1}),
    "lurking": ("潜伏的杀人狂", "X", {"friend": 1, "serial": 1}),
    "virus": ("妄想扩大病毒", "X", {"conspiracy": 1}),
    "threads": ("因果线", "X", {}),
    "unknown": ("未知因子 X", "X", {"factor": 1}),
    "of_dream_beauty": ("梦中的美人", "Y", {"key": 1, "puppet": 1, "brain": 1}),
    "of_retry": ("重来", "Y", {"key": 1}),
    "of_endless": ("循环无止境", "Y", {"brain": 1, "assassin": 1}),
    "of_time_patrol": ("时空巡逻队", "Y", {"terrorist": 1}),
    "of_terminator": ("来自天网的刺客", "Y", {"key": 1, "terrorist": 1}),
    "of_truman": ("捏造的世界", "X", {"friend": 1}),
    "of_delorean": ("德罗宁时光机", "X", {"loved": 1, "lover": 1}),
    "of_blue_cat": ("蓝色狸猫的阴谋", "X", {"returner_enemy": 1, "conspiracy": 1}),
    "of_lavender": ("薰衣草香气", "X", {"returner_friend": 1, "friend": 1}),
    "of_doomsday": ("破灭的预言", "X", {"friend": 1, "conspiracy": 1, "trickster": 1}),
    "of_grandfather": ("祖父悖论", "X", {"returner_enemy": 1, "friend": 1, "trickster": 1}),
    "of_time_war": ("时间战争", "X", {"puppet": 1, "returner_enemy": 1,
                                      "returner_friend": 1, "conspiracy": 1}),
    "mz_secret_record": ("绝密报告", "Y", {"key": 1, "brain": 1, "conspiracy": 1}),
    "mz_battle": ("男子汉的战争", "Y", {"ninja": 1}),
    "mz_approaching": ("魔爪渐近", "Y", {"key": 1, "cultist": 1, "ninja": 1}),
    "mz_causal": ("因果之绊", "Y", {"friend": 1, "serial": 1, "conspiracy": 1}),
    "mz_love_hate": ("爱与恨的螺旋", "X", {"friend": 1, "obsessive": 1}),
    "mz_witch_tea": ("魔女的茶会", "X", {"friend": 1, "conspiracy": 1, "witch": 2}),
    "mz_gods_dice": ("诸神之骰", "X", {"serial": 1, "obsessive": 1}),
    "mz_factor": ("X 异因子", "X", {"factor": 1}),
    "mz_death_show": ("死亡真人秀", "X", {"magician": 1, "immortal": 1}),
    "mz_clear_mind": ("心无重障", "X", {"conspiracy": 1, "magician": 1}),
    "mz_doom_song": ("灭亡颂歌", "X", {"prophet": 1}),
    "mc_event_web": ("事件交织的罗网", "Y", {"fool": 1, "conspiracy": 1}),
    "mc_tightrope": ("命悬一线的计划", "Y", {"killer": 1, "brain": 1}),
    "mc_dark_school": ("黑暗学园", "Y", {"brain": 1}),
    "mc_strychnine": ("士的宁毒液", "Y", {"key": 1, "poisoner": 1, "fool": 1}),
    "mc_isolation": ("隔离病房惊魂记", "X", {"conspiracy": 1, "paranoid": 1,
                                                 "psychiatrist": 1}),
    "mc_gunpowder": ("火药的味道", "X", {"serial": 1}),
    "mc_detective": ("我是名侦探", "X", {"conspiracy": 1, "friend": 1, "detective": 1}),
    "mc_fool_dance": ("愚者之舞", "X", {"fool": 1, "friend": 1}),
    "mc_absolute": ("绝对意志", "X", {"obsessive": 1}),
    "mc_twins": ("双子的诡计", "X", {"paranoid": 1, "twin": 1}),
    "hsa_noble": ("高贵的血族", "Y", {"key": 1, "vampire": 1}),
    "hsa_moon_beast": ("月夜凶兽", "Y", {"werewolf": 1}),
    "hsa_fog_nightmare": ("雾中夜惊梦", "Y", {"nightmare": 1}),
    "hsa_ancient_dead": ("古墓活尸", "Y", {}),
    "hsa_cursed_land": ("被诅咒的土地", "Y", {"ghost": 1, "paper_tiger": 1}),
    "hsa_panic_party": ("心慌派对", "X", {"ghost": 1, "serial": 1, "lover": 1}),
    "love_hsa": ("恋爱风景线", "X", {"lover": 1, "loved": 1}),
    "hsa_witch_curse": ("魔女诅咒", "X", {"conspiracy": 1, "witch": 1}),
    "hsa_girl_crisis": ("少女大危机", "X", {"key": 1}),
    "hsa_monster_plot": ("怪物们的阴谋", "X", {"conspiracy": 1}),
    "hsa_fear_delusion": ("恐慌与妄想", "X", {"serial": 1, "chicken": 1, "witch": 1}),
    "hsa_unlistening": ("不听劝的人", "X", {"paper_tiger": 1, "conspiracy": 1,
                                                   "chicken": 1}),
    "wm_outer_chorus": ("外神合唱曲", "Y", {"key": 1, "sacrifice": 1, "immortal": 1}),
    "wm_gospel": ("达贡的福音书", "Y", {"key": 1, "cultist": 1, "deep_one": 1}),
    "wm_yellow_king": ("黄衣之王", "Y", {"sacrifice": 1, "cultist": 1}),
    "wm_bomb": ("巨大定时炸弹 Y", "Y", {"witch": 1, "deep_one": 1}),
    "wm_blood_ritual": ("染血的仪式", "Y", {"witch": 1, "immortal": 1}),
    "wm_rumor": ("流言四起", "X", {"conspiracy": 1}),
    "wm_resistance": ("抗争者", "X", {"conspiracy": 1, "wizard": 1, "serial": 1}),
    "wm_witness_terror": ("见证恐惧", "X", {"conspiracy": 1, "witness": 1}),
    "wm_great_race": ("伊斯之伟大种族", "X", {"serial": 1, "time_traveler": 1}),
    "wm_deep_whisper": ("深渊之都的私语", "X", {"deep_one": 1, "paranoid": 1}),
    "wm_faceless_god": ("无貌之神", "X", {"wizard": 1, "faceless": 1}),
    "wm_mad_truth": ("疯狂的真相", "X", {"paranoid": 1}),
}


@dataclass(frozen=True)
class ModuleSpec:
    """Declarative module differences consumed by validation and the front ends."""

    name: str
    plots: tuple[str, ...]
    subplot_count: int
    incidents: tuple[str, ...]
    role_caps: dict[str, int]
    final_guess: bool
    early_final_guess: bool
    characters: tuple[str, ...]
    gui_supported: bool
    cli_supported: bool = True
    friend_gender_split: bool = False


_ALL_CHARACTERS = ("student", "girl", "rich", "class_rep", "teacher", "maiden", "outsider",
                   "police", "worker", "informer", "idol", "journalist", "forensic", "doctor",
                   "patient", "nurse", "soldier")
_MC_CHARACTERS = (*_ALL_CHARACTERS[:-1], "henchman")
_FS_PLOTS = ("murder_plan", "avenger", "protect", "ripper", "rumor", "hideous")
_BTX_PLOTS = ("murder_plan", "sealed", "sign", "change", "bomb", "friends", "love",
              "lurking", "rumor", "virus", "threads", "unknown")
_OF_PLOTS = ("of_dream_beauty", "of_retry", "of_endless", "of_time_patrol", "of_terminator",
             "of_truman", "of_delorean", "of_blue_cat", "of_lavender", "of_doomsday",
             "of_grandfather", "of_time_war")
_MZ_PLOTS = ("sealed", "mz_secret_record", "mz_battle", "mz_approaching", "mz_causal",
             "mz_love_hate", "mz_witch_tea", "mz_gods_dice", "mz_factor",
             "mz_death_show", "mz_clear_mind", "mz_doom_song")
_MC_PLOTS = ("murder_plan", "mc_event_web", "mc_tightrope", "mc_dark_school",
             "mc_strychnine", "lurking", "mc_isolation", "mc_gunpowder",
             "mc_detective", "mc_fool_dance", "mc_absolute", "mc_twins")
_HSA_PLOTS = ("hsa_noble", "hsa_moon_beast", "hsa_fog_nightmare", "hsa_ancient_dead",
              "hsa_cursed_land", "hsa_panic_party", "love_hsa", "hsa_witch_curse",
              "hsa_girl_crisis", "hsa_monster_plot", "hsa_fear_delusion", "hsa_unlistening")
_WM_PLOTS = ("wm_outer_chorus", "wm_gospel", "wm_yellow_king", "wm_bomb", "wm_blood_ritual",
             "wm_rumor", "wm_resistance", "wm_witness_terror", "wm_great_race",
             "wm_deep_whisper", "wm_faceless_god", "wm_mad_truth")
_FS_INCIDENTS = ("murder", "unease", "suicide", "hospital", "faraway", "missing", "spreading")
_BTX_INCIDENTS = (*_FS_INCIDENTS, "foul_play", "butterfly")
_OF_INCIDENTS = ("murder", "suicide", "malicious_rumor", "hospital", "poison_gas", "exposure",
                 "time_distortion", "confession")
_MZ_INCIDENTS = ("serial_murder", "suicide", "unease", "missing", "covert_activity",
                 "hospital", "riot", "confession", "breakthrough", "fake_suicide", "fake_incident")
_MC_INCIDENTS = ("serial_murder", "terror_attack", "hospital", "suicide", "unease", "omen",
                 "bizarre_murder", "fake_suicide", "suspicious_letter", "lockdown", "silver_bullet")
_HSA_INCIDENTS = ("frenzied_murder", "unease", "missing", "foul_play", "funeral",
                  "curse_declaration", "barricade", "frenzied_night", "curse_awakening",
                  "filth_overflow", "dead_apocalypse")
_WM_INCIDENTS = ("frenzied_murder", "mass_suicide", "unease", "missing", "foul_play",
                 "hospital", "riot", "extinction", "dagon_whisper", "discovery", "funeral")
_OF_CHARACTERS = ("student", "girl", "rich", "class_rep", "maiden", "police", "worker",
                  "informer", "idol", "doctor", "patient")

MODULES = {
    "FS": ModuleSpec("FirstSteps", _FS_PLOTS, 1, _FS_INCIDENTS,
                     {"conspiracy": 1, "friend": 2}, False, False, _ALL_CHARACTERS, True),
    "BTX": ModuleSpec("BasicTragedyX", _BTX_PLOTS, 2, _BTX_INCIDENTS,
                      {"conspiracy": 1, "friend": 2}, True, True, _ALL_CHARACTERS, True),
    "OF": ModuleSpec("OldFashion", _OF_PLOTS, 2, _OF_INCIDENTS,
                     {"returner_enemy": 1, "conspiracy": 1, "friend": 2}, True, True,
                     _OF_CHARACTERS, True, friend_gender_split=True),
    "MZ": ModuleSpec("MidnightZone", _MZ_PLOTS, 2, _MZ_INCIDENTS,
                     {"conspiracy": 1, "friend": 2}, True, True, _ALL_CHARACTERS, True),
    "MC": ModuleSpec("MysteryCircle", _MC_PLOTS, 2, _MC_INCIDENTS,
                     {"conspiracy": 1, "friend": 2, "fool": 1}, True, True,
                     _MC_CHARACTERS, True),
    "HSA": ModuleSpec("HauntedStageAgain", _HSA_PLOTS, 2, _HSA_INCIDENTS,
                      {"ghost": 1, "conspiracy": 1}, True, True, _ALL_CHARACTERS, True),
    "WM": ModuleSpec("WeirdMythology", _WM_PLOTS, 2, _WM_INCIDENTS,
                     {"deep_one": 1, "conspiracy": 1, "wizard": 1}, True, True,
                     _ALL_CHARACTERS, True),
}

# Historical public name retained for callers and saved-game compatibility.
MODULE_PLOTS = {module: spec.plots for module, spec in MODULES.items()}

PLOT_RULES = {
    "murder_plan": "无追加规则；失败来源由身份能力决定。",
    "avenger": "轮回结束：主谋的初始区域密谋 ≥2，主人公失败。",
    "protect": "轮回结束：学校密谋 ≥2，主人公失败。",
    "ripper": "无追加规则。", "hideous": "剧本制作时另可加入 0–2 名暴徒。",
    "rumor": "剧作家能力阶段可给任意版图密谋 +1，每轮一次。",
    "sealed": "轮回结束：神社密谋 ≥2，主人公失败。",
    "sign": "关键人物必须具有少女属性；轮回结束时其密谋 ≥2，主人公失败。",
    "change": "轮回结束：本轮发生过蝴蝶效应，主人公失败（不要求效果成功）。",
    "bomb": "轮回结束：魔女的初始区域密谋 ≥2，主人公失败。",
    "friends": "无追加规则。", "love": "无追加规则。", "lurking": "无追加规则。",
    "virus": "常驻强制：存活平民的不安达到 3，即变为杀人狂，持续到轮回重置。",
    "threads": "轮回开始：上轮结束时带有友好的所有角色（含尸体）各得不安 +2。",
    "unknown": "无追加规则。",
    "of_dream_beauty": "回合结束阶段：主谋存活且关键人物密谋 ≥2，主人公失败。",
    "of_retry": "最终日的回合结束阶段强制使主人公死亡；制作剧本时每轮最大日数 -1（不公开）。",
    "of_endless": "轮回结束：神社密谋 ≥2，主人公失败。",
    "of_time_patrol": "轮回结束：恐怖分子（无论生死）密谋 ≥2，主人公失败。",
    "of_terminator": "无追加规则。",
    "of_truman": "常驻强制：本局所有平民身份均视为傀儡。",
    "of_delorean": "轮回结束：心上人友好 ≥3，主人公失败。",
    "of_blue_cat": "剧作家能力阶段可给任意版图或角色密谋 +1，每轮一次。",
    "of_lavender": "无追加规则。",
    "of_doomsday": "回合结束：任意角色不安 ≥4 时，该角色强制死亡。",
    "of_grandfather": "回合结束阶段（含本阶段）：存在死去的亲友时，所有归来者·敌强制死亡。",
    "of_time_war": "无追加规则。",
    "mz_secret_record": "轮回结束：本轮曾公开主谋、不安定因子或魔术师中的任一身份名，主人公失败。",
    "mz_battle": "制作剧本：忍者必须具有男性属性（不能是少年）；轮回结束：忍者（无论生死）密谋 ≥2，主人公失败。",
    "mz_approaching": "轮回开始：给一名上轮结束时死亡的角色放置一张 Ex 牌；不与因果之绊重复发动。",
    "mz_causal": "轮回开始：给一名上轮结束时死亡的角色放置一张 Ex 牌；有 Ex 牌的角色变为关键人物并失去原身份。",
    "mz_love_hate": "无追加规则。",
    "mz_witch_tea": "无追加规则。",
    "mz_gods_dice": "轮回开始：给一名上轮结束时死亡的角色放置一张 Ex 牌；不与因果之绊重复发动。",
    "mz_factor": "剧作家能力阶段：给一名存活不安定因子所在版图密谋 +1，每轮一次。",
    "mz_death_show": "轮回结束：存活角色不多于 6 名，主人公失败。",
    "mz_clear_mind": "行动结算：禁止友好也同时具有禁止移动的效果。",
    "mz_doom_song": "制作剧本时必须有至少一起自杀；事件阶段：平民为当事人且预言家存活时，该当事人的不安临界 -1。",
    "mc_event_web": "轮回结束：Ex 槽为 3 或以上，主人公失败。",
    "mc_tightrope": "轮回结束：Ex 槽为 1 或以下，主人公失败。",
    "mc_dark_school": "轮回结束：学校密谋不低于当前轮回数 - 1，主人公失败；第 1 轮必败。",
    "mc_strychnine": "判定连续杀人或自杀是否发生时，密谋也视作不安。",
    "mc_isolation": "轮回开始：若上一轮结束时 Ex 槽不高于 2，本轮 Ex 槽 +1。",
    "mc_gunpowder": "轮回结束：所有存活角色身上的密谋合计不低于 12，主人公失败。",
    "mc_detective": "无追加规则。", "mc_fool_dance": "无追加规则。",
    "mc_absolute": "无追加规则。", "mc_twins": "无追加规则。",
    "hsa_noble": "剧本制作：关键人物与吸血鬼必须为异性。",
    "hsa_moon_beast": "无追加规则。",
    "hsa_fog_nightmare": "无追加规则。",
    "hsa_ancient_dead": "常驻强制：平民、纸老虎的尸体身份变为丧尸。",
    "hsa_cursed_land": "轮回开始可在鬼魂初始版图放置诅咒；日末若版图诅咒没有可附身目标，可使主人公死亡。",
    "hsa_panic_party": "无追加规则。", "love_hsa": "无追加规则。",
    "hsa_witch_curse": "轮回开始可在魔女初始版图放置诅咒。",
    "hsa_girl_crisis": "剧本制作：关键人物必须具有少女属性。",
    "hsa_monster_plot": "剧作家能力阶段可在具有无视友好身份的角色所在版图放置一具尸体；每日一次、每轮两次。",
    "hsa_fear_delusion": "无追加规则。", "hsa_unlistening": "无追加规则。",
    "wm_outer_chorus": "轮回结束：至少 5 名存活角色各有至少 1 密谋，主人公失败。",
    "wm_gospel": "轮回结束：神社密谋不低于 Ex 槽，主人公失败。",
    "wm_yellow_king": "轮回结束：本轮 Ex 槽没有增加，主人公失败。",
    "wm_bomb": "轮回结束：魔女初始版图密谋不少于 2，主人公失败。",
    "wm_blood_ritual": "轮回结束：尸体数不少于 Ex 槽，主人公失败。",
    "wm_rumor": "剧作家能力阶段可给任意版图密谋 +1，每轮一次。",
    "wm_resistance": "无追加规则。", "wm_witness_terror": "无追加规则。",
    "wm_great_race": "无追加规则。",
    "wm_deep_whisper": "偏执狂获得关键人物能力，身份不变。",
    "wm_faceless_god": "无追加规则。",
    "wm_mad_truth": "轮回开始时 Ex 槽不少于 2，本轮规则 Y 失败条件替换为剧本指定的另一条规则 Y。",
}
ROLE_RULES = {
    "ordinary": "没有身份能力。",
    "key": "死亡时强制立即结束轮回，主人公失败。",
    "killer": "可拒绝自身友好能力。日末可杀死同区域密谋 ≥2 的关键人物；自身密谋 ≥4 时可使主人公死亡。",
    "brain": "可拒绝自身友好能力。剧作家能力阶段可给同区域角色或所在版图密谋 +1。",
    "cultist": "必须拒绝自身友好能力。行动结算时可无效化同区域所有角色及版图上的禁止密谋。",
    "conspiracy": "剧作家能力阶段可给同区域任意角色不安 +1。剧本人数上限 1。",
    "serial": "日末强制：同区域恰好有另一名存活角色时，使其死亡；尸体不计人数。",
    "curmudgeon": "可拒绝自身友好能力。",
    "friend": "轮回结束时若已死，公开身份且主人公失败。身份曾公开，则以后轮回开始得友好 +1。人数上限 2。",
    "time_traveler": "不会死亡，强制忽略自身的禁止友好。最终日日末若友好 ≤2，可使主人公失败。",
    "witch": "必须拒绝自身友好能力。",
    "loved": "求爱者死亡时，强制得不安 +6。",
    "lover": "心上人死亡时，强制得不安 +6。日末若自身不安 ≥3 且密谋 ≥1，可使主人公死亡。",
    "factor": "可拒绝自身友好能力。学校密谋 ≥2 时获得传谣人能力；都市密谋 ≥2 时获得关键人物能力。身份仍为因子。",
    "puppet": "可拒绝自身友好能力；友好 ≥4 时必须拒绝。拒绝后强制死亡，一旦死亡，之后轮回均保持尸体状态。日末可杀死同区域友好 ≥4 的任意角色。",
    "assassin": "可拒绝自身友好能力。回合结束时自身密谋 ≥3，可使主人公死亡。",
    "terrorist": "可拒绝自身友好能力。回合结束时所在版图密谋 ≥3，可使主人公死亡；≥2 时可杀死同区域任意一名角色。",
    "returner_enemy": "可拒绝自身友好能力。行动结算阶段可无效化同区域主人公放置的一张行动牌，每轮一次。上轮结束时若存活且友好 ≥3，本轮继承全部计数物。人数上限 1。",
    "returner_friend": "轮回开始时，若上轮结束时存活且友好 ≥3，本轮继承上轮结束时的所有计数物。",
    "trickster": "可拒绝自身友好能力。回合结束时，同区域除自身外有至少三名角色，可选择一名死亡（每轮一次、每名角色全局至多被指定一次）；若同区域没有其他角色则自身死亡。",
    "ninja": "可拒绝自身友好能力。日末可杀死同区域密谋 ≥2 的一名角色；公开自身身份时可改为宣称本剧本中的任意非平民身份。",
    "obsessive": "必须拒绝自身友好能力。制作剧本时必须担任至少一起事件的当事人；其作为当事人的事件必定发生。",
    "magician": "剧作家能力阶段可将同区域友好 ≥1 的角色移至相邻版图，所有魔术师合计每轮一次；死亡时强制移除自身全部友好。",
    "immortal": "不会死亡。",
    "prophet": "剧作家不能在其身上放置行动牌；同区域的其他角色不会引发事件。",
    "poisoner": "可拒绝友好。日末 Ex 槽 ≥2 时强制使同区域一名角色死亡（每轮一次）；Ex 槽 ≥4 时强制使主人公死亡。",
    "fool": "制作剧本时必须担任一起事件的当事人；其事件结算后强制移除自身全部不安。人数上限 1。",
    "paranoid": "必须拒绝友好；剧作家能力阶段可给自身密谋 +1。",
    "psychiatrist": "剧作家能力阶段 Ex 槽 ≥1 时，强制移除同区域另一名角色的 1 不安。",
    "detective": "不会死亡且不能担任事件当事人；Ex 槽为 0 且与今日存活当事人同区域时，事件必定发生。",
    "twin": "制作剧本时必须担任一起事件的当事人；结算其事件时，视为位于实际位置对角线的版图。",
    "vampire": "可拒绝友好且不会死亡。日末可杀死同区域密谋 ≥2 的关键人物；初始版图有至少两具尸体时可使主人公死亡。",
    "werewolf": "可拒绝友好；剧作家不能在其身上放置行动牌。日末若本轮发生疯狂之夜，可使主人公死亡。",
    "nightmare": "可拒绝友好且不会死亡。日末可杀死同区域一名角色；场上诅咒不少于三张时可使主人公死亡。",
    "ghost": "尸体状态下，剧作家能力阶段强制给同区域或初始版图的一名角色不安 +1。上限 1。",
    "paper_tiger": "不会死亡；不安不少于 2 时必须拒绝友好。",
    "chicken": "剧作家能力阶段不安不少于 2 时，强制移动至相邻版图。",
    "zombie": "日末强制：在丧尸数多于非丧尸角色数且有活人的版图杀死一人（每日一次）；尸体状态下可移动至相邻版图（每日一次）。",
    "sacrifice": "不会死亡；事件判定时密谋也视作不安。剧本制作时必须是第一个事件的当事人；日末密谋和不安均不少于 2 时可使所有角色与主人公死亡。",
    "deep_one": "可拒绝友好；剧作家能力阶段可给同区域角色或所在版图密谋 +1。上限 1。",
    "wizard": "可正常死亡；轮回结束时若已死亡，主人公失败。友好能力结算后公开身份，领队可选择令 Ex 槽 +1。上限 1。",
    "witness": "日末不安不少于 4 时强制死亡，并令 Ex 槽 +1。",
    "faceless": "不会死亡且可拒绝友好。Ex 槽不少于 1/2 时分别获得传谣人/深潜者能力，身份不变。",
}
INCIDENT_RULES = {
    "murder": "同当事人一个区域的另一名存活角色死亡。",
    "unease": "任意存活角色不安 +2，随后另一名存活角色密谋 +1。",
    "suicide": "当事人死亡。",
    "hospital": "医院密谋 ≥1：医院所有存活角色同时死亡；医院密谋 ≥2：主人公死亡。",
    "faraway": "任意密谋 ≥2 的存活角色死亡，不限区域。",
    "missing": "当事人移至任意合法版图（可不移动）；随后其实际所在版图密谋 +1。",
    "spreading": "任意存活角色友好 -2（不足减至零），随后另一名存活角色友好 +2。",
    "foul_play": "神社密谋 +2。",
    "butterfly": "与当事人同区域任意存活角色（可含当事人）获得友好、不安或密谋 +1。",
    "malicious_rumor": "当事人所在区域的所有角色不安 +2。",
    "poison_gas": "当事人所在版图及另一个任意版图各获得密谋 +1。",
    "exposure": "选择其一：从当事人所在区域的角色合计移除 2 友好，或合计放置 2 友好；可分给两名角色。",
    "time_distortion": "下一日行动阶段剧作家放置四张行动牌，主人公合计只能放置两张，领队不能放置。",
    "confession": "公开当事人的身份。",
    "serial_murder": "与当事人同区域的另一名存活角色死亡；一名角色可以担任多起连续杀人的当事人。",
    "covert_activity": "选择此前已经发生的一起事件，执行该事件的效果。",
    "riot": "医院密谋 ≥1：医院所有角色死亡；≥2：主人公死亡。学校密谋 ≥1：学校所有角色死亡。都市密谋 ≥1：都市所有角色死亡。",
    "breakthrough": "领队选择一名角色或一个版图，移除其 2 枚密谋（不足则减至 0）。",
    "fake_suicide": "在当事人身上放置一张 Ex 牌；MC 中，本轮余下时间主人公不能在有 Ex 牌的角色上放置行动牌。",
    "fake_incident": "在当事人身上放置一张 Ex 牌；本轮余下时间主人公不能在有 Ex 牌的角色上放置行动牌；若当事人密谋 ≥2，主人公失败。公开事件表可使用任意事件名。",
    "terror_attack": "都市密谋 ≥1：都市所有角色死亡；都市密谋 ≥2：主人公死亡。",
    "omen": "发生临界为当事人不安临界 -1；同区域一名角色不安 +1。",
    "bizarre_murder": "发生临界为当事人不安临界 +1；Ex 槽改为增加 2；依次结算连续杀人和不安扩散。",
    "suspicious_letter": "将同区域一名角色移至任意版图；若实际移动，次日该角色不能移动。",
    "lockdown": "指定当事人所在版图；从当日起三天内，角色不能通过移动进入或离开该版图。",
    "silver_bullet": "Ex 槽不增加；事件阶段结束时立即结束本轮。",
    "frenzied_murder": "与当事人同区域另一名角色死亡，或在当事人所在版图放置一具尸体。",
    "funeral": "当事人的不安临界 -1；领队选择一名角色死亡。",
    "curse_declaration": "在当事人身上放置一张诅咒牌。",
    "barricade": "将与当事人同区域的其他角色分别移动至任意其他版图。",
    "frenzied_night": "群聚事件，要求版图尸体数 >0；若场上尸体不少于六具，本日日末主人公死亡。",
    "curse_awakening": "群聚事件，要求版图尸体数 >1；在当事版图放置一张诅咒牌。",
    "filth_overflow": "群聚事件，要求版图尸体数 >2；同区域一名角色不安 +2，任意版图增加一具尸体。",
    "dead_apocalypse": "群聚事件，要求版图尸体数 >2；该版图所有角色死亡，之后若该版图尸体不少于五具，主人公死亡。",
    "mass_suicide": "当事人密谋不少于 1 时，其所在区域所有角色死亡。",
    "extinction": "本局游戏中首次发生时，所有角色与主人公死亡；之后再次发生没有效果。",
    "dagon_whisper": "改用当事人的密谋判定发生；本轮之后若有其他事件发生，主人公在该事件阶段结束时死亡。",
    "discovery": "Ex 槽 +1。",
}


@dataclass(frozen=True)
class Ability:
    id: str
    threshold: int
    text: str
    kind: str
    scope: str = "same"
    counter: str = "paranoia"
    amount: int = -1
    once: bool = False
    unrefusable: bool = False


@dataclass(frozen=True)
class CharacterDef:
    name: str
    start: str
    limit: int
    traits: tuple[str, ...]
    abilities: tuple[Ability, ...] = ()
    forbidden: tuple[str, ...] = ()
    passive: str = ""


CHARACTERS = {
    "student": CharacterDef("男学生", "school", 2, ("student", "boy"),
                            (Ability("calm", 2, "同区域另一名学生不安 -1", "counter", "other_student"),)),
    "girl": CharacterDef("女学生", "school", 3, ("student", "girl"),
                         (Ability("calm", 2, "同区域另一名学生不安 -1", "counter", "other_student"),)),
    "rich": CharacterDef("大小姐", "school", 1, ("student", "girl"),
                         (Ability("befriend", 3, "位于学校/都市：同区域角色友好 +1", "counter", "rich", "goodwill", 1),)),
    "class_rep": CharacterDef("班长", "school", 2, ("student", "girl"),
                              (Ability("recover", 2, "领队收回一张已用限次牌", "recover", once=True),)),
    "teacher": CharacterDef("教师", "school", 2, ("adult", "woman"),
                            (Ability("adjust", 3, "同区域一名学生不安 +1 或 -1", "adjust", "student"),
                             Ability("reveal", 4, "公开同区域一名学生身份", "reveal", "student", once=True))),
    "maiden": CharacterDef("巫女", "shrine", 2, ("student", "girl"),
                           (Ability("purify", 3, "位于神社：神社密谋 -1", "purify"),
                            Ability("reveal", 5, "公开同区域一名角色身份", "reveal", once=True)), ("city",)),
    "outsider": CharacterDef("异界人", "shrine", 2, ("girl",),
                             (Ability("kill", 4, "同区域另一名角色死亡", "kill", "other", once=True),
                              Ability("revive", 5, "同区域一具尸体复活", "revive", "corpse", once=True)), ("hospital",)),
    "police": CharacterDef("刑警", "city", 3, ("adult", "man"),
                           (Ability("culprit", 4, "公开本轮已发生的一起事件的当事人", "culprit", once=True),
                            Ability("guard", 5, "同区域角色获得一次死亡替代护卫", "guard", once=True))),
    "worker": CharacterDef("职员", "city", 2, ("adult", "man"),
                           (Ability("reveal", 3, "公开自身身份", "reveal", "self"),), ("school",)),
    "informer": CharacterDef("情报商", "city", 3, ("adult", "woman"),
                             (Ability("plot", 5, "声明一个规则 X，剧作家公开一个未被声明的实际规则 X", "plot", once=True),)),
    "idol": CharacterDef("偶像", "city", 2, ("student", "girl"),
                         (Ability("calm", 3, "同区域另一名角色不安 -1", "counter", "other"),
                          Ability("befriend", 4, "同区域另一名角色友好 +1", "counter", "other", "goodwill", 1))),
    "journalist": CharacterDef("媒体人", "city", 2, ("adult", "man"),
                               (Ability("alarm", 2, "任意另一名角色不安 +1", "counter", "any_other", "paranoia", 1),
                                Ability("intrigue", 2, "同区域角色或当前版图密谋 +1", "counter", "same_or_location", "intrigue", 1))),
    "forensic": CharacterDef("鉴识官", "city", 3, ("adult", "man"),
                             (Ability("transfer", 2, "在同区域另两名角色间移动一个计数物", "transfer", once=True),
                              Ability("reveal_dead", 5, "公开任意一具尸体的身份", "reveal", "any_corpse", once=True))),
    "doctor": CharacterDef("医生", "hospital", 2, ("adult", "man"),
                           (Ability("adjust", 2, "同区域另一名角色不安 +1 或 -1", "adjust", "other"),
                            Ability("release", 3, "本轮取消住院患者的禁行区域", "release")),
                           passive="若医生有无视友好特性且友好 ≥2，剧作家也能在能力阶段使用其第一项能力（共用每日次数）。"),
    "patient": CharacterDef("住院患者", "hospital", 2, ("boy",), (), ("shrine", "city", "school")),
    "nurse": CharacterDef("护士", "hospital", 3, ("adult", "woman"),
                          (Ability("calm", 2, "同区域另一名不安达临界角色不安 -1（不可拒绝）", "counter", "panicked_other", unrefusable=True),)),
    "soldier": CharacterDef("军人", "hospital", 3, ("adult", "man"),
                            (Ability("alarm", 2, "同区域角色不安 +2", "counter", "same", "paranoia", 2, True),
                             Ability("protect", 5, "本轮主人公不会死亡", "protect", once=True))),
    "henchman": CharacterDef("手下", "school", 1, ("adult", "man"),
                              (Ability("prevent_incident", 3, "阻止自身担任当事人的今日事件发生",
                                       "prevent_incident", "self"),),
                              passive="每轮开始时由剧作家决定初始区域。"),
}

TRAIT_NAMES = {"student": "学生", "boy": "少年", "girl": "少女", "adult": "成人", "man": "男性", "woman": "女性"}
