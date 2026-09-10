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
});
