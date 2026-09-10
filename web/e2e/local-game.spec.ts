import { expect, test, type Page } from "@playwright/test";

async function createBtxGame(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "悲剧轮回" })).toBeVisible();
  await expect(page.getByLabel("规则集").locator("option")).toHaveCount(8);
  await page.getByLabel("规则集").selectOption("BTX");
  await page.getByRole("button", { name: "新建对局" }).click();
  await expect(page.getByText(/轮回 1\/.*第 1 天/)).toBeVisible();
}

async function selectFirstAction(page: Page) {
  const hand = page.locator(".actions-panel .hand button");
  if (await hand.count()) {
    await hand.first().click();
    await page.locator(".actions-panel .action-grid button").first().click();
  } else {
    await page.locator(".actions-panel .action-grid button").first().click();
  }
  const accepted = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/commands"));
  await page.getByRole("button", { name: "确认执行" }).click();
  await accepted;
  await expect(page.getByRole("button", { name: "确认执行" })).toBeHidden();
  await expect(page.getByRole("button", { name: "新建对局" })).toBeEnabled();
}

test("real service preserves private card boundary while actions advance", async ({ page }) => {
  await createBtxGame(page);
  await page.getByRole("button", { name: "剧作家", exact: true }).click();
  await expect(page.getByRole("heading", { name: "剧作家资料" })).toBeVisible();
  await selectFirstAction(page);
  await expect(page.getByText(/第 1 天剧作家出牌阶段/, { exact: true })).toBeVisible();

  await page.locator(".actions-panel .hand button").first().click();
  const chosenCard = await page.locator(".actions-panel .hand button.selected strong").innerText();
  await page.locator(".actions-panel .action-grid button").first().click();
  await page.getByRole("button", { name: "确认执行" }).click();
  await expect(page.locator(".placement")).toContainText(chosenCard);

  await page.getByRole("button", { name: "公开视角" }).click();
  await expect(page.getByRole("heading", { name: "剧作家资料" })).toHaveCount(0);
  await expect(page.locator(".placement")).toContainText("暗牌");
  await expect(page.locator(".placement")).not.toContainText(chosenCard);
});

test("session survives reload and narrow screens retain all controls", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await createBtxGame(page);
  await page.reload();
  await expect(page.getByText(/轮回 1\/.*第 1 天/)).toBeVisible();
  await expect(page.getByRole("button", { name: "保存 JSON" })).toBeVisible();
  await expect(page.getByRole("button", { name: "剧作家", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("a deterministic legal-action walk reaches a result and opens replay", async ({ page }) => {
  test.setTimeout(60_000);
  await createBtxGame(page);
  for (let step = 0; step < 300; step += 1) {
    if (await page.locator(".outcome").count()) break;
    const actor = (await page.locator(".status-strip > div").nth(2).locator("strong").innerText()).trim();
    await page.getByRole("button", { name: actor, exact: true }).click();
    await expect(page.locator(".actions-panel button").first()).toBeVisible();
    await selectFirstAction(page);
  }
  await expect(page.locator(".outcome")).toContainText("胜利");
  await page.getByRole("button", { name: "查看回放" }).click();
  await expect(page.getByRole("dialog", { name: "只读回放" })).toBeVisible();
  await expect(page.locator(".replay pre")).toContainText("第 1 天");
});

test("stale controls are rejected and refreshed to authoritative state", async ({ page }) => {
  await createBtxGame(page);
  await page.getByRole("button", { name: "剧作家", exact: true }).click();
  await page.locator(".actions-panel .action-grid button").first().click();
  await page.evaluate(async () => {
    const session = JSON.parse(localStorage.getItem("tragedy-sim.local-session.v1")!);
    const headers = { Authorization: `Bearer ${session.seatTokens.m}` };
    const offers = await fetch(`/v1/games/${session.sessionId}/actions?actor=m`, { headers }).then(response => response.json());
    await fetch(`/v1/games/${session.sessionId}/commands`, {
      method: "POST", headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ action_id: offers.actions[0].id, expected_revision: offers.revision }),
    });
  });
  const stale = page.waitForResponse(response => response.url().endsWith("/commands") && response.status() === 409);
  await page.getByRole("button", { name: "确认执行" }).click();
  await stale;
  await expect(page.getByRole("alert")).toContainText("对局状态已经改变");
  await expect(page.getByText(/第 1 天剧作家出牌阶段/, { exact: true })).toBeVisible();
});

test("every supported ruleset creates and renders through the browser protocol", async ({ page }) => {
  const modules = ["FS", "BTX", "MZ", "MC", "HSA", "WM", "AHR", "LL"];
  const pageErrors: string[] = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.goto("/");
  for (const module of modules) {
    await page.getByLabel("规则集").selectOption(module);
    const created = page.waitForResponse(response => response.url().endsWith("/v1/games") && response.request().method() === "POST");
    await page.getByRole("button", { name: "新建对局" }).click();
    const payload = await (await created).json();
    expect(payload.view.state.module).toBe(module);
    await expect(page.locator(".board .location")).toHaveCount(4);
    await page.getByRole("button", { name: "剧作家", exact: true }).click();
    await expect(page.getByRole("heading", { name: "剧作家资料" })).toBeVisible();
    await page.getByRole("button", { name: "公开视角" }).click();
    await expect(page.getByRole("heading", { name: "剧作家资料" })).toHaveCount(0);
  }
  expect(pageErrors).toEqual([]);
});
