import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

async function createGame(page: Page, module = "BTX") {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "悲剧轮回" })).toBeVisible();
  await expect(page.getByLabel("规则集").locator("option")).toHaveCount(8);
  await page.getByLabel("规则集").selectOption(module);
  await page.getByRole("button", { name: "新建对局" }).click();
  await expect(page.getByText(/轮回 1\/.*第 1 天/)).toBeVisible();
}

const createBtxGame = (page: Page) => createGame(page, "BTX");

async function selectFirstAction(page: Page) {
  await expect(page.locator(
    ".actions-panel .hand button, .actions-panel .guess-characters button, .actions-panel .action-grid button",
  ).first()).toBeVisible();
  const hand = page.locator(".actions-panel .hand button");
  if (await hand.count()) {
    await hand.first().click();
    await page.locator(".board .legal-board-target").last().click();
  } else if (await page.locator(".actions-panel .guess-characters button").count()) {
    await page.locator(".actions-panel .guess-characters button").first().click();
    await page.locator(".actions-panel .action-grid button").first().click();
  } else {
    await page.locator(".actions-panel .action-grid button").first().click();
  }
  await expect(page.getByRole("button", { name: "确认执行" })).toBeVisible();
  const accepted = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/commands"));
  await page.getByRole("button", { name: "确认执行" }).click();
  await accepted;
  await expect(page.getByRole("button", { name: "确认执行" })).toBeHidden();
  if (await page.getByRole("button", { name: "新建对局" }).count()) {
    await expect(page.getByRole("button", { name: "新建对局" })).toBeEnabled();
  }
}

async function dragFirstCardToFirstTarget(page: Page) {
  const card = page.locator(".actions-panel .hand button").first();
  await expect(card).toBeVisible();
  await card.click();
  const target = page.locator(".board .legal-board-target").last();
  await expect(target).toBeVisible();
  await card.scrollIntoViewIfNeeded();
  const cardBox = await card.boundingBox();
  if (!cardBox) throw new Error("card has no layout box");
  await page.mouse.move(cardBox.x + cardBox.width / 2, cardBox.y + cardBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(cardBox.x + cardBox.width / 2 + 12, cardBox.y + cardBox.height / 2 + 12,
                        { steps: 3 });
  const targetBox = await target.boundingBox();
  if (!targetBox) throw new Error("target has no layout box");
  await page.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2,
                        { steps: 6 });
  await page.mouse.up();
}

test("a missing room offers a direct return to the lobby", async ({ page }) => {
  await page.goto("/?room=000000");
  await expect(page.getByRole("alert")).toContainText("房间不存在或已经关闭");
  await expect(page.getByRole("heading", { name: "无法进入房间" })).toBeVisible();
  await page.getByRole("button", { name: "返回大厅" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "创建局域网房间" })).toBeVisible();
  await page.getByLabel("房间码").fill("12ab3456");
  await expect(page.getByLabel("房间码")).toHaveValue("123456");
  await expect(page.getByRole("button", { name: "进入房间" })).toBeEnabled();
});

test("a host can fill an empty side with a random AI and play against it", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("主人公玩家人数").selectOption("1");
  await page.getByLabel("昵称").fill("Host");
  await page.getByRole("button", { name: "创建房间" }).click();
  const heroSeat = page.locator(".seat-grid article").filter({ hasText: "主人公 A" });
  await heroSeat.getByRole("button", { name: "用 AI 填充" }).click();
  await expect(heroSeat).toContainText("随机 AI");
  await expect(heroSeat).toContainText("自动随机行动");
  await page.getByRole("button", { name: "我已准备" }).click();
  await expect(page.getByRole("button", { name: "开始游戏" })).toBeEnabled();
  await page.getByRole("button", { name: "开始游戏" }).click();

  // Start the day and place three mastermind cards. The AI consumes the opposing turns.
  for (let step = 0; step < 4; step += 1) await selectFirstAction(page);
  await expect(page.locator(".actions-panel.has-actions")).toBeVisible();
  await expect(page.getByText(/现在轮到你以剧作家身份行动/)).toBeVisible();
});

test("four isolated browser sessions join, ready and receive synchronized private views", async ({ browser }) => {
  const contexts = await Promise.all([0, 1, 2, 3].map(index => browser.newContext(
    index === 1 ? { viewport: { width: 390, height: 844 } } : undefined)));
  const pages = await Promise.all(contexts.map(context => context.newPage()));
  try {
    const [host, a, b, c] = pages;
    await host.goto("/");
    await host.getByLabel("规则集").selectOption("BTX");
    await host.getByLabel("昵称").fill("Host");
    await host.getByRole("button", { name: "创建房间" }).click();
    await expect(host.getByRole("heading", { name: "等待所有玩家入座并准备" })).toBeVisible();
    await expect(host.locator(".room-heading strong")).toHaveText(/^\d{6}$/);
    const invite = host.url();

    for (const [page, seat, name] of [[a, "A", "Alice"], [b, "B", "Bob"], [c, "C", "Carol"]] as const) {
      await page.goto(invite);
      await expect(page.getByRole("heading", { name: "等待所有玩家入座并准备" })).toBeVisible();
      await page.getByLabel("你的昵称").fill(name);
      const card = page.locator(".seat-grid article").filter({ hasText: `主人公 ${seat}` });
      await card.getByRole("button", { name: "坐到这里" }).click();
      await expect(page.getByText(`你是：主人公 ${seat}`)).toBeVisible();
    }

    for (const page of pages) await page.getByRole("button", { name: "我已准备" }).click();
    await expect(host.getByRole("button", { name: "开始游戏" })).toBeEnabled();
    await host.getByRole("button", { name: "开始游戏" }).click();
    await expect(host.getByRole("heading", { name: "剧作家资料" })).toBeVisible();
    const portrait = host.locator(".character-art").first();
    await expect(portrait).toBeVisible();
    await expect.poll(() => portrait.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
    for (const page of [a, b, c]) {
      await expect(page.locator(".status-strip")).toBeVisible();
      await expect(page.getByRole("heading", { name: "剧作家资料" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "保存 JSON" })).toHaveCount(0);
    }

    await selectFirstAction(host);
    for (const page of [a, b, c]) {
      await expect(page.getByText("第 1 天剧作家出牌阶段", { exact: true })).toBeVisible({ timeout: 4_000 });
    }
    await a.reload();
    await expect(a.getByText("第 1 天剧作家出牌阶段", { exact: true })).toBeVisible();
    await expect(a.getByText("你的席位：主人公 A", { exact: true })).toBeVisible();
    expect(await a.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  } finally {
    await Promise.all(contexts.map(context => context.close()));
  }
});

test("a broken SSE connection falls back to revision polling", async ({ browser }) => {
  const hostContext = await browser.newContext();
  const heroContext = await browser.newContext();
  const host = await hostContext.newPage();
  const hero = await heroContext.newPage();
  await hero.route("**/events?*", route => route.abort());
  try {
    await host.goto("/");
    await host.getByLabel("主人公玩家人数").selectOption("1");
    await host.getByLabel("昵称").fill("Host");
    await host.getByRole("button", { name: "创建房间" }).click();
    await expect(host.getByRole("heading", { name: "等待所有玩家入座并准备" })).toBeVisible();
    await hero.goto(host.url());
    await hero.getByLabel("你的昵称").fill("Fallback");
    await hero.locator(".seat-grid article").filter({ hasText: "主人公 A" })
      .getByRole("button", { name: "坐到这里" }).click();
    await host.getByRole("button", { name: "我已准备" }).click();
    await hero.getByRole("button", { name: "我已准备" }).click();
    await expect(host.getByRole("button", { name: "开始游戏" })).toBeEnabled();
    await host.getByRole("button", { name: "开始游戏" }).click();
    await expect(hero.locator(".status-strip")).toBeVisible();

    await selectFirstAction(host);
    await expect(hero.getByText("第 1 天剧作家出牌阶段", { exact: true })).toBeVisible({ timeout: 7_000 });
  } finally {
    await Promise.all([hostContext.close(), heroContext.close()]);
  }
});

test("one protagonist browser controls A, B and C in a two-person room", async ({ browser }) => {
  const hostContext = await browser.newContext();
  const heroContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const host = await hostContext.newPage();
  const hero = await heroContext.newPage();
  try {
    await host.goto("/");
    await host.getByLabel("主人公玩家人数").selectOption("1");
    await host.getByLabel("昵称").fill("Host");
    await host.getByRole("button", { name: "创建房间" }).click();
    await expect(host.getByRole("heading", { name: "等待所有玩家入座并准备" })).toBeVisible();
    const invite = host.url();
    await hero.goto(invite);
    await expect(hero.getByRole("heading", { name: "等待所有玩家入座并准备" })).toBeVisible();
    await hero.getByLabel("你的昵称").fill("Solo");
    await hero.locator(".seat-grid article").filter({ hasText: "主人公 A" }).getByRole("button", { name: "坐到这里" }).click();
    await host.getByRole("button", { name: "我已准备" }).click();
    await hero.getByRole("button", { name: "我已准备" }).click();
    await expect(host.getByRole("button", { name: "开始游戏" })).toBeEnabled();
    await host.getByRole("button", { name: "开始游戏" }).click();

    for (let step = 0; step < 4; step += 1) await selectFirstAction(host);
    await expect(hero.getByRole("heading", { name: "主人公 A手牌" })).toBeVisible();
    await expect(hero.getByRole("heading", { name: "主人公 B手牌（由你代管）" })).toBeVisible();
    await expect(hero.getByRole("heading", { name: "主人公 C手牌（由你代管）" })).toBeVisible();
    await expect(hero.locator(".actions-panel .hand button").first()).toBeVisible();
    for (const actor of ["A", "B", "C"]) {
      await selectFirstAction(hero);
      await expect(hero.locator(".placement").filter({ hasText: `主人公 ${actor}` })).toBeVisible();
    }
    await hero.getByRole("button", { name: "返回大厅" }).click();
    await expect(hero.getByRole("heading", { name: "创建局域网房间" })).toBeVisible();
  } finally {
    await Promise.all([hostContext.close(), heroContext.close()]);
  }
});

test("two protagonist browsers alternate fixed cards and delegate C to the leader", async ({ browser }) => {
  const contexts = await Promise.all([0, 1, 2].map(() => browser.newContext()));
  const [host, a, b] = await Promise.all(contexts.map(context => context.newPage()));
  try {
    await host.goto("/");
    await host.getByLabel("主人公玩家人数").selectOption("2");
    await host.getByLabel("昵称").fill("Host");
    await host.getByRole("button", { name: "创建房间" }).click();
    await expect(host.getByRole("heading", { name: "等待所有玩家入座并准备" })).toBeVisible();
    const invite = host.url();
    for (const [page, seat, name] of [[a, "A", "Alice"], [b, "B", "Bob"]] as const) {
      await page.goto(invite);
      await expect(page.getByRole("heading", { name: "等待所有玩家入座并准备" })).toBeVisible();
      await page.getByLabel("你的昵称").fill(name);
      await page.locator(".seat-grid article").filter({ hasText: `主人公 ${seat}` }).getByRole("button", { name: "坐到这里" }).click();
    }
    for (const page of [host, a, b]) await page.getByRole("button", { name: "我已准备" }).click();
    await expect(host.getByRole("button", { name: "开始游戏" })).toBeEnabled();
    await host.getByRole("button", { name: "开始游戏" }).click();
    for (let step = 0; step < 4; step += 1) await selectFirstAction(host);

    await expect(a.getByText("今日真人领队：Alice（代管 C）", { exact: true })).toBeVisible();
    await expect(a.getByRole("heading", { name: "主人公 C手牌（由你代管）" })).toBeVisible();
    await expect(b.getByRole("heading", { name: "主人公 C手牌（由你代管）" })).toHaveCount(0);
    await expect(a.locator(".actions-panel .hand button").first()).toBeVisible();
    await selectFirstAction(a);
    await selectFirstAction(b);
    await selectFirstAction(a);
    await expect(a.locator(".placement").filter({ hasText: "主人公 C" })).toBeVisible();
  } finally {
    await Promise.all(contexts.map(context => context.close()));
  }
});

test("real service preserves private card boundary while actions advance", async ({ page }) => {
  await createBtxGame(page);
  await page.getByRole("button", { name: "剧作家", exact: true }).click();
  await expect(page.getByRole("heading", { name: "剧作家资料" })).toBeVisible();
  await selectFirstAction(page);
  await expect(page.getByText(/第 1 天剧作家出牌阶段/, { exact: true })).toBeVisible();

  await page.locator(".actions-panel .hand button").first().click();
  const chosenCard = await page.locator(".actions-panel .hand button.selected strong").innerText();
  await page.locator(".board .legal-board-target").last().click();
  await page.getByRole("button", { name: "确认执行" }).click();
  await expect(page.locator(".placement")).toContainText(chosenCard);

  await page.getByRole("button", { name: "公开视角" }).click();
  await expect(page.getByRole("heading", { name: "剧作家资料" })).toHaveCount(0);
  await expect(page.locator(".placement")).toContainText("暗牌");
  await expect(page.locator(".placement")).not.toContainText(chosenCard);
});

test("action cards can be dragged only onto server-provided legal targets", async ({ page }) => {
  await createBtxGame(page);
  await page.getByRole("button", { name: "剧作家", exact: true }).click();
  await selectFirstAction(page);
  await dragFirstCardToFirstTarget(page);
  await expect(page.getByRole("button", { name: "确认执行" })).toBeVisible();
  await expect(page.locator(".drag-card-overlay")).toHaveCount(0);
  const accepted = page.waitForResponse(response => response.request().method() === "POST"
    && response.url().endsWith("/commands"));
  await page.getByRole("button", { name: "确认执行" }).click();
  await accepted;
  await expect(page.locator(".placement")).toHaveCount(1);
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

test("snapshot download restores the exact intermediate game", async ({ page }) => {
  await createBtxGame(page);
  await page.getByRole("button", { name: "剧作家", exact: true }).click();
  await selectFirstAction(page);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "保存 JSON" }).click();
  const snapshot = await download;
  expect(snapshot.suggestedFilename()).toBe("tragedy-sim-save.json");
  const snapshotPath = await snapshot.path();
  expect(snapshotPath).not.toBeNull();

  await createGame(page, "FS");
  await expect(page.locator(".status-strip")).toContainText("First Steps");
  await page.locator('input[type="file"]').setInputFiles(snapshotPath!);
  await expect(page.locator(".status-strip")).toContainText("Basic Tragedy X");
  await expect(page.getByText(/第 1 天剧作家出牌阶段/, { exact: true })).toBeVisible();
});

test("custom scenario JSON loads through the same isolated protocol", async ({ page }) => {
  await page.goto("/");
  const scenario = fileURLToPath(new URL("../../examples/ll-tutorial.json", import.meta.url));
  await page.locator('input[type="file"]').setInputFiles(scenario);
  await expect(page.locator(".status-strip")).toContainText("Last Liar");
  await page.getByRole("button", { name: "主人公 A", exact: true }).click();
  await expect(page.getByRole("heading", { name: "你的 Last Liar 秘密" })).toBeVisible();
});

test("a deterministic legal-action walk reaches a result and opens replay", async ({ page }) => {
  test.setTimeout(60_000);
  await createBtxGame(page);
  for (let step = 0; step < 300; step += 1) {
    if (await page.locator(".outcome").count()) break;
    const actor = (await page.locator(".status-strip > div").nth(2).locator("strong").innerText()).trim();
    await page.getByRole("button", { name: actor, exact: true }).click();
    await expect(page.locator(".actions-panel button").first()).toBeVisible({ timeout: 10_000 });
    await selectFirstAction(page);
  }
  await expect(page.locator(".outcome")).toContainText("胜利");
  await page.getByRole("button", { name: "查看回放" }).click();
  await expect(page.getByRole("dialog", { name: "只读回放" })).toBeVisible();
  await expect(page.locator(".replay-timeline button").first()).toContainText("第 1 天");
  await page.locator(".replay-timeline button").first().click();
  await expect(page.locator(".replay-detail")).toContainText("决策 1/");
  await expect(page.getByRole("button", { name: "上一步" })).toBeDisabled();
  await page.getByRole("button", { name: "关闭" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出回放" }).click();
  await expect((await download).suggestedFilename()).toBe("tragedy-sim-replay.tlr");
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

test("ruleset-specific private and public resources have dedicated presentation", async ({ page }) => {
  await createGame(page, "LL");
  await page.getByRole("button", { name: "主人公 A", exact: true }).click();
  await expect(page.getByRole("heading", { name: "你的 Last Liar 秘密" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "剧作家资料" })).toHaveCount(0);
  await page.getByRole("button", { name: "公开视角" }).click();
  await expect(page.getByRole("heading", { name: "你的 Last Liar 秘密" })).toHaveCount(0);

  await createGame(page, "AHR");
  await expect(page.getByText("Ex 槽 0", { exact: true })).toBeVisible();
  await expect(page.getByText("当前世界：表世界", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "剧作家", exact: true }).click();
  await page.getByText("身份配置", { exact: true }).click();
  await expect(page.getByText(/里身份/).first()).toBeVisible();

  await createGame(page, "HSA");
  await expect(page.locator(".location").first()).toContainText("尸体 0");
  await expect(page.getByRole("heading", { name: "事件日程" }).locator(".." )).toContainText("癫狂杀人");

  await createGame(page, "WM");
  await expect(page.getByText("Ex 槽 0", { exact: true })).toBeVisible();
});

for (const module of ["FS", "MZ", "MC", "HSA", "WM", "AHR", "LL"]) {
  test(`${module} generic action UI reaches a formal result`, async ({ page }) => {
    test.setTimeout(120_000);
    await createGame(page, module);
    for (let step = 0; step < 600; step += 1) {
      if (await page.locator(".outcome").count()) break;
      const actor = (await page.locator(".status-strip > div").nth(2).locator("strong").innerText()).trim();
      await page.getByRole("button", { name: actor, exact: true }).click();
      await expect(page.locator(".actions-panel button").first()).toBeVisible({ timeout: 10_000 });
      await selectFirstAction(page);
    }
    await expect(page.locator(".outcome"), `${module} did not reach game_over`).toContainText("胜利");
  });
}
