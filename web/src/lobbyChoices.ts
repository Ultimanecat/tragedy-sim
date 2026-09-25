import type { ModuleId, RoomOccupant, ScenarioSummary, Seat } from "./api/types";

export type AiStrategy = NonNullable<RoomOccupant["ai_type"]>;

export interface AiChoice {
  id: AiStrategy;
  label: string;
  description: string;
  group: "推荐试玩" | "其他策略" | "实验与对照" | "开眼测试";
  role: "both" | "mastermind" | "protagonist";
  modules?: readonly ModuleId[];
  teamOnly?: boolean;
}

export const AI_CHOICES: readonly AiChoice[] = [
  { id: "strategic_mcts_mastermind", label: "策略 MCTS", description: "结合获胜路线和搜索；当前低预算测试中表现较好的通用剧作家选择。", group: "推荐试玩", role: "mastermind" },
  { id: "defensive_protagonist", label: "公开信息防守", description: "依据公开信息防守；适合快速试玩，多人主人公局也可使用。", group: "推荐试玩", role: "protagonist" },
  { id: "particle_ensemble_protagonist", label: "粒子集成", description: "根据可见证据估计隐藏身份，联合搜索三张牌；FS/BTX 单人控制主人公时可用，思考较慢，棋力尚未稳定验证。", group: "推荐试玩", role: "protagonist", modules: ["FS", "BTX"], teamOnly: true },
  { id: "random", label: "随机", description: "随机选择合法行动；适合检验流程。", group: "其他策略", role: "both" },
  { id: "fixed_mastermind", label: "定式", description: "选择一条可行获胜路线执行；速度快，容易被针对。", group: "其他策略", role: "mastermind" },
  { id: "optimized_mcts_mastermind", label: "优化 MCTS", description: "用渐进拓宽和行动先验搜索；比朴素版更有效率。", group: "其他策略", role: "mastermind" },
  { id: "joint_mastermind", label: "三牌联合搜索", description: "把当天三张暗牌一起搜索，并估计主人公回应；仅 FS/BTX，计算较慢。", group: "实验与对照", role: "mastermind", modules: ["FS", "BTX"] },
  { id: "belief_joint_mastermind", label: "信念采样联合搜索", description: "估计主人公可能知道什么，再联合搜索三张暗牌；仅 BTX，实验版，思考较慢。", group: "实验与对照", role: "mastermind", modules: ["BTX"] },
  { id: "mcts_mastermind", label: "朴素 MCTS", description: "早期搜索基线；行动空间大，速度与棋力均不推荐用于日常试玩。", group: "实验与对照", role: "mastermind" },
  { id: "baseline_protagonist", label: "基础干扰", description: "尝试逆向移动和禁止密谋；轻量级对照策略。", group: "其他策略", role: "protagonist" },
  { id: "risk_aware_protagonist", label: "历史风险", description: "按公开揭牌历史估计风险；实验对照，已有 FS 测试表现弱于公开信息防守，并非最强。", group: "实验与对照", role: "protagonist" },
  { id: "ismcts_protagonist", label: "团队 ISMCTS", description: "在隐藏信息下联合搜索三张主人公牌；仅 FS/BTX 单人控制主人公。", group: "实验与对照", role: "protagonist", modules: ["FS", "BTX"], teamOnly: true },
  { id: "survival_ismcts_protagonist", label: "当日生存 ISMCTS", description: "采样暗牌并优先避免当日失败；仅 FS/BTX 单人控制主人公。", group: "实验与对照", role: "protagonist", modules: ["FS", "BTX"], teamOnly: true },
  { id: "ismcts_legacy_protagonist", label: "旧版团队 ISMCTS", description: "旧算法对照组，后两张牌由防守策略补全；仅 FS/BTX 单人控制主人公。", group: "实验与对照", role: "protagonist", modules: ["FS", "BTX"], teamOnly: true },
  { id: "oracle_script_protagonist", label: "已知剧本＋暗牌", description: "开眼测试 AI：知道全部剧本秘密，但看不到当天暗牌；不适合公平对局。", group: "开眼测试", role: "protagonist", modules: ["FS", "BTX"], teamOnly: true },
  { id: "oracle_cards_protagonist", label: "已知剧本＋明牌", description: "开眼测试 AI：知道全部剧本秘密和当天剧作家出牌；不适合公平对局。", group: "开眼测试", role: "protagonist", modules: ["FS", "BTX"], teamOnly: true },
];

export function availableAiChoices(seat: Seat, module: ModuleId, protagonistCount: number): AiChoice[] {
  return AI_CHOICES.filter(choice =>
    (choice.role === "both" || choice.role === (seat === "m" ? "mastermind" : "protagonist"))
    && (!choice.modules || choice.modules.includes(module))
    && (!choice.teamOnly || protagonistCount === 1));
}

export function aiChoice(strategy: AiStrategy | null): AiChoice | undefined {
  return AI_CHOICES.find(choice => choice.id === strategy);
}

export function scenarioOptionLabel(item: ScenarioSummary): string {
  const loops = item.loop_options.length > 1
    ? `${item.loop_options[0]}–${item.loop_options.at(-1)} 轮（默认 ${item.loops}）`
    : `${item.loops} 轮`;
  return `[${item.module}] ${item.title} · ${item.days} 天/${loops}`;
}
