"""FS/BTX content transcribed from the user's sheets; no executable script data."""

from dataclasses import dataclass

ROLE_NAMES = {"ordinary": "平民", "key": "关键人物", "killer": "杀手", "brain": "主谋",
              "cultist": "邪教徒", "conspiracy": "传谣人", "serial": "杀人狂",
              "curmudgeon": "暴徒", "friend": "亲友", "time_traveler": "时间旅行者",
              "witch": "魔女", "loved": "心上人", "lover": "求爱者", "factor": "不安定因子"}
REFUSAL = {"killer": "optional", "brain": "optional", "curmudgeon": "optional",
           "factor": "optional", "cultist": "mandatory", "witch": "mandatory"}
INCIDENT_NAMES = {"murder": "谋杀", "unease": "不安扩散", "suicide": "自杀",
                  "hospital": "医院事故", "faraway": "远距离杀人", "missing": "失踪",
                  "spreading": "散播", "foul_play": "邪气污染", "butterfly": "蝴蝶效应"}
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
}
MODULE_PLOTS = {"FS": ("murder_plan", "avenger", "protect", "ripper", "rumor", "hideous"),
                "BTX": ("murder_plan", "sealed", "sign", "change", "bomb", "friends", "love",
                        "lurking", "rumor", "virus", "threads", "unknown")}

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
}

TRAIT_NAMES = {"student": "学生", "boy": "少年", "girl": "少女", "adult": "成人", "man": "男性", "woman": "女性"}
