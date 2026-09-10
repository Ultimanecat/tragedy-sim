import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Actions, Board } from "./App";
import { abilityUseName } from "./display";
import type { ActionOffer, CatalogResponse, GameView } from "./api/types";
import catalogFixture from "../fixtures/protocol-v1/btx-catalog.json";
import viewFixture from "../fixtures/protocol-v1/btx-mastermind-view.json";

const catalog = catalogFixture as unknown as CatalogResponse;
const game = viewFixture.state as unknown as GameView;

describe("local game components", () => {
  it("formats both goodwill and two-part private ability keys without undefined", () => {
    expect(abilityUseName(game, "goodwill:doctor:adjust", catalog)).toContain("医生 · 同区域另一名角色不安");
    expect(abilityUseName(game, "brain:doctor", catalog)).toContain("医生 ·");
    expect(abilityUseName(game, "brain:doctor", catalog)).not.toContain("undefined");
  });

  it("renders concealed placements without leaking their card", () => {
    const publicGame = { ...game, pending: [{ actor: "m", target: "student", card: null }] };
    render(<Board game={publicGame} catalog={catalog} />);
    expect(screen.getByText(/剧作家 → 男学生：暗牌/)).toBeInTheDocument();
    expect(screen.queryByText(/不安\+1/)).not.toBeInTheDocument();
  });

  it("requires card, target and confirmation before dispatch", () => {
    const offers: ActionOffer[] = [
      { id: "one", actor: "m", type: "play", parameters: { card: "p1a", target: "student" }, label: "不安+1 → 男学生" },
      { id: "two", actor: "m", type: "play", parameters: { card: "p1a", target: "girl" }, label: "不安+1 → 女学生" },
    ];
    const dispatch = vi.fn();
    render(<Actions offers={offers} catalog={catalog} game={game} busy={false} onAction={dispatch} />);
    expect(screen.queryByText("确认执行")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /不安 \+1（第1张）.*2 个合法目标/ }));
    fireEvent.click(screen.getByRole("button", { name: "男学生" }));
    expect(dispatch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
    expect(dispatch).toHaveBeenCalledWith(offers[0]);
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
