import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Actions, Board } from "./App";
import { abilityUseName } from "./display";
import { parseReplayTimeline } from "./replay";
import type { ActionOffer, CatalogResponse, GameView } from "./api/types";
import catalogFixture from "../fixtures/protocol-v1/btx-catalog.json";
import viewFixture from "../fixtures/protocol-v1/btx-mastermind-view.json";

const catalog = catalogFixture as unknown as CatalogResponse;
const game = viewFixture.state as unknown as GameView;

describe("local game components", () => {
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
    expect(screen.getByText(/密谋 0 · 9 人/)).toBeInTheDocument();

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

  it("groups AHR dual-identity guesses without exposing internal target ids", () => {
    const offers: ActionOffer[] = [
      { id: "surface-key", actor: "a", type: "guess", parameters: { character: "student@surface", role: "key" }, label: "男学生（表身份）是关键人物" },
      { id: "surface-brain", actor: "a", type: "guess", parameters: { character: "student@surface", role: "brain" }, label: "男学生（表身份）是幕后黑手" },
      { id: "hidden-key", actor: "a", type: "guess", parameters: { character: "student@hidden", role: "key" }, label: "男学生（里身份）是关键人物" },
    ];
    const dispatch = vi.fn();
    render(<Actions offers={offers} catalog={catalog} game={game} busy={false} onAction={dispatch} />);
    expect(screen.queryByText("student@surface")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /男学生（表身份）2 个身份候选/ }));
    fireEvent.click(screen.getByRole("button", { name: "关键人物" }));
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
    expect(dispatch).toHaveBeenCalledWith(offers[0]);
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
