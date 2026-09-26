import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Actions, AnimatedCounter, Board, PublicLog } from "./App";
import { actionHint, eventPresentation } from "./presentation";
import { abilityUseName } from "./display";
import { parseReplayTimeline } from "./replay";
import type { ActionOffer, CardPlanResponse, CatalogResponse, GameView, Seat } from "./api/types";
import catalogFixture from "../fixtures/protocol-v1/btx-catalog.json";
import viewFixture from "../fixtures/protocol-v1/btx-mastermind-view.json";

const catalog = catalogFixture as unknown as CatalogResponse;
const game = viewFixture.state as unknown as GameView;

describe("local game components", () => {
  it("shows recent logs across loops and keeps every record accessible through filters", () => {
    const events = Array.from({ length: 15 }, (_, index) => ({
      loop: index < 10 ? 1 : 2, round: 1, phase: "day_end", timing: "day_end",
      timepoint: "第 1 天结束时", kind: index === 9 ? "loop_lost" : "counter_changed", message: `记录 ${index}`,
    }));
    const { container } = render(<PublicLog game={{ ...game, loop: 2, events }} catalog={catalog} />);
    expect(container.querySelectorAll(".log article")).toHaveLength(12);
    expect(screen.getByText("记录 9")).toBeInTheDocument();
    expect(container.querySelector(".log-danger")).toHaveTextContent("记录 9");
    fireEvent.click(screen.getByLabelText("仅看关键记录"));
    expect(container.querySelectorAll(".log article")).toHaveLength(1);
    fireEvent.click(screen.getByLabelText("仅看关键记录"));
    fireEvent.change(screen.getByLabelText("日志范围"), { target: { value: "all" } });
    expect(container.querySelectorAll(".log article")).toHaveLength(15);
    fireEvent.change(screen.getByLabelText("搜索公开日志"), { target: { value: "记录 0" } });
    expect(container.querySelectorAll(".log article")).toHaveLength(1);
  });

  it("uses structured action types for guidance and never offers unavailable phase completion", () => {
    const choice: ActionOffer = { id: "x", actor: "a", type: "choose", parameters: {}, label: "任意文本", ui: { source: "doctor" } };
    expect(actionHint(game, [choice], false, false)).toContain("先点击版图");
    expect(actionHint(game, [choice], false, false)).not.toContain("结束阶段");
    expect(actionHint(game, [choice], false, true)).toContain("安排三张");
    expect(actionHint(game, [], true, true)).toContain("不要重复提交");
    expect(actionHint(game, [], false, false)).toContain("自动同步");
    expect(actionHint(game, [], false, false, true)).toContain("切换");
    expect(eventPresentation("goodwill_refused").label).toBe("能力拒绝");
    expect(eventPresentation("unknown_extension").tone).toBe("normal");
  });
  for (const side of ["m", "a"] as const) {
    it(`edits and submits ${side === "m" ? "mastermind" : "team protagonist"} cards only as a complete local draft`, () => {
      const actors: Seat[] = side === "m" ? ["m", "m", "m"] : ["a", "b", "c"];
      const cards = side === "m" ? ["p1a", "p1b", "i1"] : ["g1"];
      const targets = ["student", "girl", "doctor"];
      const plan: CardPlanResponse = {
        protocol_version: 1, session_id: "test", revision: 4,
        slots: actors.map(actor => ({ actor, actions: cards.flatMap(card => targets.map(target => ({
          id: `${actor}:${card}:${target}`, actor, type: "play", parameters: { card, target }, label: `${card} → ${target}`,
        }))) })),
        constraints: { distinct_targets: true, card_limits: Object.fromEntries(actors.map(actor => [actor,
          Object.fromEntries(cards.map(card => [card, 1]))])) },
      };
      const dispatch = vi.fn();
      const submit = vi.fn();
      const props = { offers: [], catalog, game, onAction: dispatch, cardPlan: plan, onCardPlan: submit };
      const { container, rerender } = render(<Actions {...props} busy={false} />);
      const final = screen.getByRole("button", { name: "确认三张牌并提交" });
      expect(final).toBeDisabled();
      for (let index = 0; index < 3; index += 1) {
        fireEvent.click(container.querySelector(".hand button")!);
        fireEvent.click(container.querySelectorAll(".character.legal-board-target")[0]);
        expect(dispatch).not.toHaveBeenCalled();
        expect(submit).not.toHaveBeenCalled();
        expect(container.querySelectorAll(".draft-placement")).toHaveLength(index + 1);
      }
      expect(final).toBeEnabled();
      fireEvent.click(screen.getByRole("button", { name: "撤回第 2 张" }));
      expect(final).toBeDisabled();
      expect(container.querySelectorAll(".draft-placement")).toHaveLength(2);
      fireEvent.click(container.querySelector(".hand button")!);
      fireEvent.click(container.querySelectorAll(".character.legal-board-target")[0]);
      const draftTexts = container.querySelector(".draft-slots")!.textContent;
      fireEvent.click(final);
      expect(submit).toHaveBeenCalledTimes(1);
      expect(submit.mock.calls[0][0].map((play: { actor: Seat }) => play.actor)).toEqual(actors);
      expect(submit.mock.calls[0][1]).toBe(4);
      rerender(<Actions {...props} busy={true} />);
      expect(screen.getByRole("button", { name: "正在提交…" })).toBeDisabled();
      rerender(<Actions {...props} busy={false} />);
      expect(container.querySelector(".draft-slots")!.textContent).toBe(draftTexts);
      fireEvent.click(screen.getByRole("button", { name: "清空草稿" }));
      expect(container.querySelectorAll(".draft-placement")).toHaveLength(0);
      expect(screen.getByRole("button", { name: "确认三张牌并提交" })).toBeDisabled();
    });
  }
  it("indicates whether a visible counter increased or decreased", () => {
    const { rerender } = render(<AnimatedCounter label="友好" value={0} />);
    expect(screen.getByLabelText("友好 0")).not.toHaveClass("counter-up");
    rerender(<AnimatedCounter label="友好" value={1} />);
    expect(screen.getByLabelText("友好 1")).toHaveClass("counter-up");
    rerender(<AnimatedCounter label="友好" value={0} />);
    expect(screen.getByLabelText("友好 0")).toHaveClass("counter-down");
  });

  it("turns the stable replay text into decisions and attached resolution steps", () => {
    const timeline = parseReplayTimeline([
      'ACTION\t{"action":"next","actor":"m"}\t# 0001 | 第 1 天开始时 · 一日开始阶段 | 剧作家结束阶段',
      '#        => [第 1 天开始时] 第 1 天开始。',
      'ACTION\t{"action":"play","actor":"m"}\t# 0002 | 第 1 天剧作家出牌阶段 · 剧作家出牌阶段 | 剧作家暗置行动牌',
    ].join("\n"));
    expect(timeline).toHaveLength(2);
    expect(timeline[0]).toMatchObject({ number: 1, timepoint: "第 1 天开始时", phase: "一日开始阶段" });
    expect(timeline[0].steps).toEqual([{ timepoint: "第 1 天开始时", message: "第 1 天开始。" }]);
  });

  it("formats both goodwill and two-part private ability keys without undefined", () => {
    expect(abilityUseName(game, "goodwill:doctor:adjust", catalog)).toContain("医生 · 同区域另一名角色不安");
    expect(abilityUseName(game, "brain:doctor", catalog)).toContain("医生 ·");
    expect(abilityUseName(game, "brain:doctor", catalog)).not.toContain("undefined");
  });

  it("renders concealed placements without leaking their card", () => {
    const publicGame = { ...game, pending: [{ actor: "m", target: "student", card: null }] };
    const { container } = render(<Board game={publicGame} catalog={catalog} />);
    expect(screen.getByText(/剧作家 → 男学生：暗牌/)).toBeInTheDocument();
    expect(screen.queryByText(/不安\+1/)).not.toBeInTheDocument();
    expect(container.querySelector('.character-art[src^="/game-assets/"]')).toBeInTheDocument();
  });

  it("uses a packed grid for nine characters and keeps details in a modal", () => {
    const packedCharacters = Object.fromEntries(Array.from({ length: 9 }, (_, index) => {
      const id = `crowd-${index}`;
      return [id, { ...game.characters.student, id, name: `拥挤角色 ${index + 1}`, location: "school" }];
    }));
    const packedGame = { ...game, characters: packedCharacters } as GameView;
    const { container } = render(<Board game={packedGame} catalog={catalog} />);
    const school = container.querySelector(".location-school");
    expect(school).toHaveClass("location-packed");
    expect(school?.querySelectorAll(".character")).toHaveLength(9);
    expect(school?.querySelector('.location-summary [aria-label="密谋 0"]')).toBeInTheDocument();
    expect(screen.getByText("9 人")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "查看拥挤角色 1资料" }));
    expect(screen.getByRole("dialog", { name: "拥挤角色 1" })).toBeInTheDocument();
    expect(screen.getByText(/属性：/)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("requires card, target and confirmation before dispatch", () => {
    const offers: ActionOffer[] = [
      { id: "one", actor: "m", type: "play", parameters: { card: "p1a", target: "student" }, label: "不安+1 → 男学生" },
      { id: "two", actor: "m", type: "play", parameters: { card: "p1a", target: "girl" }, label: "不安+1 → 女学生" },
    ];
    const dispatch = vi.fn();
    render(<Actions offers={offers} catalog={catalog} game={game} busy={false} onAction={dispatch} />);
    expect(screen.queryByText("确认执行")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "不安 +1（第1张）" }));
    fireEvent.click(screen.getByRole("button", { name: "查看男学生资料" }));
    expect(screen.getByRole("dialog", { name: "男学生" })).toBeInTheDocument();
    expect(screen.queryByText("确认执行")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    fireEvent.click(document.querySelector('.character.legal-board-target') as HTMLElement);
    expect(dispatch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
    expect(dispatch).toHaveBeenCalledWith(offers[0]);
  });

  it("selects a character before presenting that character's ability actions", () => {
    const ability: ActionOffer = {
      id: "doctor-adjust", actor: "a", type: "choose", parameters: {}, ui: { source: "doctor" },
      label: "医生 · 同区域另一名角色不安 -1 → 男学生",
    };
    const { container } = render(<Actions offers={[ability]} catalog={catalog} game={game} busy={false} onAction={vi.fn()} />);
    expect(screen.queryByRole("button", { name: ability.label })).not.toBeInTheDocument();
    fireEvent.click(container.querySelector('.character.ability-source') as HTMLElement);
    expect(screen.getByRole("button", { name: ability.label })).toBeInTheDocument();
  });

  it("submits the final identity table as one decision", () => {
    const offer: ActionOffer = {
      id: "all-guesses", actor: "a", type: "guess_all",
      parameters: { characters: ["student", "girl"], roles: ["ordinary", "key"] },
      label: "一次提交全部最终猜测",
    };
    const dispatch = vi.fn();
    render(<Actions offers={[offer]} catalog={catalog} game={game} busy={false} onAction={dispatch} />);
    const submit = screen.getByRole("button", { name: "统一提交最终猜测" });
    expect(submit).toBeDisabled();
    const selectors = screen.getAllByRole("combobox");
    fireEvent.change(selectors[0], { target: { value: "ordinary" } });
    fireEvent.change(selectors[1], { target: { value: "key" } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(dispatch).toHaveBeenCalledWith(offer, {
      guesses: { student: "ordinary", girl: "key" },
    });
  });

  it("treats ruleset ability choices as opaque server-owned actions", () => {
    const spell: ActionOffer = {
      id: "wm-spell-offer", actor: "a", type: "choose", parameters: {},
      label: "发动感知法术：查看公开规则候选",
    };
    const dispatch = vi.fn();
    render(<Actions offers={[spell]} catalog={catalog} game={game} busy={false} onAction={dispatch} />);
    fireEvent.click(screen.getByRole("button", { name: spell.label }));
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
    expect(dispatch).toHaveBeenCalledWith(spell);
  });
});
