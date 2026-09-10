import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Actions, Board } from "./App";
import type { ActionOffer, CatalogResponse, GameView } from "./api/types";
import catalogFixture from "../fixtures/protocol-v1/btx-catalog.json";
import viewFixture from "../fixtures/protocol-v1/btx-mastermind-view.json";

const catalog = catalogFixture as unknown as CatalogResponse;
const game = viewFixture.state as unknown as GameView;

describe("local game components", () => {
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
});
