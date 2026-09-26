import type { ActionOffer, GameView } from "./api/types";

const eventLabels: Record<string, { label: string; tone: string }> = {
  protagonists_lost: { label: "失败", tone: "danger" },
  loop_lost: { label: "轮回失败", tone: "danger" },
  heroes_died: { label: "死亡", tone: "danger" },
  character_died: { label: "死亡", tone: "danger" },
  game_ended: { label: "胜负", tone: "important" },
  final_guess_result: { label: "最终猜测", tone: "important" },
  final_guess_started: { label: "最终猜测", tone: "important" },
  goodwill_refused: { label: "能力拒绝", tone: "important" },
  role_revealed: { label: "身份信息", tone: "information" },
  culprit_revealed: { label: "当事人信息", tone: "information" },
  plot_revealed: { label: "规则信息", tone: "information" },
  private_information_gained: { label: "信息获取", tone: "information" },
  incident_status: { label: "事件", tone: "important" },
  incident_ended: { label: "事件", tone: "important" },
  cards_revealed: { label: "揭牌", tone: "information" },
};

export function eventPresentation(kind: string) {
  return eventLabels[kind] ?? { label: "结算", tone: "normal" };
}

export function actionHint(game: GameView, offers: ActionOffer[], busy: boolean, batch: boolean, localDebug = false): string {
  if (game.winner) return "对局已结束，房主可查看或导出回放。";
  if (busy) return "正在与服务端同步，请等待；不要重复提交。";
  if (!offers.length) return localDebug ? "本机调试请切换到当前操作者视角，继续行动。" : "等待当前操作者完成行动，状态会自动同步。";
  if (batch) return "安排三张行动牌：拖放或点击目标进入草稿，可任意撤回，最后一起确认。";
  if (offers.some(offer => offer.type === "guess_all")) return "填写全部角色的初始身份，再统一提交最终猜测。";
  if (offers.some(offer => offer.type === "play")) return "选择自己的行动牌，再拖放或点击合法目标，确认后提交这一张。";
  if (offers.some(offer => offer.ui?.source)) return "先点击版图上可操作的角色，再选择具体能力或结算选项。"
    + (offers.some(offer => offer.type === "next") ? "也可选择结束阶段。" : "");
  if (offers.some(offer => offer.type === "choose")) return "选择服务端给出的结算选项，并确认执行。";
  return "检查当前阶段信息，点击下方行动按钮并确认，推进结算。";
}
