import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./client";
import created from "../../fixtures/protocol-v1/btx-created.json";
import actions from "../../fixtures/protocol-v1/btx-day-start-actions.json";
import catalog from "../../fixtures/protocol-v1/btx-catalog.json";

afterEach(() => vi.unstubAllGlobals());

describe("ApiClient", () => {
  it("stores credentials and submits only action id plus revision", async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push([url, init]);
      const body = calls.length === 1 ? created : calls.length === 2 ? actions : {
        ...created.view, revision: 1, accepted_action: actions.actions[0], view: created.view,
      };
      return new Response(JSON.stringify(body), { status: calls.length === 1 ? 201 : 200 });
    }));
    const client = new ApiClient();
    await client.create("BTX");
    const offered = await client.actions("m");
    await client.command("m", offered.actions[0].id);
    expect(JSON.parse(String(calls[2][1]?.body))).toEqual({
      action_id: offered.actions[0].id, expected_revision: 0,
    });
    expect(calls[2][1]?.headers).toMatchObject({ Authorization: "Bearer fixture-m" });
  });

  it("uses stable error codes", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      protocol_version: 1,
      error: { code: "STALE_REVISION", message: "stale", details: { current: 2 } },
    }), { status: 409 })));
    const client = new ApiClient();
    await expect(client.create("FS")).rejects.toMatchObject({ code: "STALE_REVISION" });
  });

  it("loads public catalog data without credentials", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(catalog)));
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient();
    await expect(client.catalog("BTX")).resolves.toMatchObject({ module: { id: "BTX" } });
    expect(fetchMock).toHaveBeenCalledWith("/v1/catalog/BTX?lang=zh", expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("keeps one LAN seat credential and polls revisions before acting", async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    const room = {
      protocol_version: 1, self: { seat: "a" }, is_host: false,
      room: { code: "123234", module: "BTX", status: "playing", revision: 2,
        game_revision: 0, spectators: true,
        seats: { m: null, a: { nickname: "Alice", ready: true, connected: true }, b: null, c: null } },
      credential: { room_token: "room-a", seat: "a" },
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push([url, init]);
      const index = calls.length;
      const body = index === 1 ? room
        : index === 2 ? { ...room, credential: undefined, game_changed: true,
          room: { ...room.room, game_revision: 1 } }
        : index === 3 ? { ...created.view, viewer: "a", revision: 1 }
        : index === 4 ? { ...actions, actor: "a", revision: 1 }
        : { ...created.view, revision: 2, accepted_action: actions.actions[0], view: created.view };
      return new Response(JSON.stringify(body), { status: index === 1 ? 201 : 200 });
    }));
    const client = new ApiClient();
    await client.createRoom("BTX", "Alice", "a");
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({
      module: "BTX", nickname: "Alice", seat: "a", spectators: true,
    });
    await client.roomUpdates();
    await client.view("a");
    const offered = await client.actions("a");
    await client.command("a", offered.actions[0].id);
    expect(calls.map(call => call[0])).toEqual([
      "/v1/rooms", "/v1/rooms/123234/updates?room_revision=2&game_revision=0",
      "/v1/rooms/123234/game/view?lang=zh", "/v1/rooms/123234/game/actions",
      "/v1/rooms/123234/game/commands",
    ]);
    expect(calls[4][1]?.headers).toMatchObject({ Authorization: "Bearer room-a" });
    expect(JSON.parse(String(calls[4][1]?.body))).toMatchObject({ expected_revision: 1 });
    expect(client.room).not.toHaveProperty("seatTokens");
  });
});
