import { expect, test } from "@playwright/test";

test.afterEach(async ({ request }) => {
  const response = await request.get("/api/runs?limit=20");
  if (!response.ok()) return;
  const body = (await response.json()) as { items: Array<{ id: string; status: string }> };
  const active = body.items.find((run) => run.status === "running" || run.status === "paused");
  if (active) {
    await request.post(`/api/runs/${active.id}/commands`, { data: { action: "end" } });
    await expect.poll(async () => {
      const latest = await request.get(`/api/runs/${active.id}`);
      if (!latest.ok()) return "missing";
      return (await latest.json() as { run: { status: string } }).run.status;
    }, { timeout: 5_000 }).toBe("ended");
  }
});

test("runs, pauses, seeks, and ends a city simulation", async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto("/");
  await expect(page.locator(".alliance-map")).toBeVisible();
  if (testInfo.project.name === "mobile") {
    await expect(page.locator(".menu-drawer")).not.toBeVisible();
    await page.getByRole("button", { name: "控制", exact: true }).click();
  }
  await expect(page.locator(".menu-drawer")).toBeVisible();
  const worldStart = page.getByRole("button", { name: "启动模拟" });
  await expect(worldStart).toBeEnabled();
  await worldStart.click();
  await expect(page.getByRole("button", { name: "暂停" })).toBeEnabled();
  const movingDot = page.locator(".alliance-flow-dot").first();
  const movingStart = await movingDot.getAttribute("cx");
  await expect.poll(() => movingDot.getAttribute("cx")).not.toBe(movingStart);
  await page.getByRole("button", { name: "暂停" }).click();
  await expect(page.getByRole("button", { name: "继续" })).toBeEnabled();
  const pausedPosition = await movingDot.getAttribute("cx");
  await page.waitForTimeout(900);
  await expect(movingDot).toHaveAttribute("cx", pausedPosition ?? "");
  await page.getByRole("button", { name: "继续" }).click();
  await expect.poll(() => movingDot.getAttribute("cx")).not.toBe(pausedPosition);
  await page.locator("button[title='结束当前运行']").click();
  await page.getByLabel("联盟聚落").selectOption("town-0-0");
  await expect(page.locator(".city-map")).toBeVisible();
  await expect(page.locator(".scenario-meta").filter({ hasText: "已就绪" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: "启动模拟" })).toBeEnabled({ timeout: 20_000 });
  const initialTownName = (await page.locator(".map-title h1").innerText()).trim();
  expect(initialTownName).not.toBe("");
  await expect(page.locator(".map-inspector .inspector-heading strong")).toHaveText(initialTownName);
  await page.getByRole("button", { name: "启动模拟" }).click();
  await expect(page.locator(".menu-drawer")).toBeVisible();
  await expect(page.locator(".history-row[aria-current='true'] small")).toContainText(initialTownName, { timeout: 20_000 });
  await expect.poll(async () => Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, "")), {
    timeout: 15_000,
  }).toBeGreaterThanOrEqual(2);

  const drawn = await page.locator("canvas#deckgl-overlay").evaluate((canvas: HTMLCanvasElement) => {
    const context = canvas.getContext("webgl2");
    if (!context || canvas.width === 0 || canvas.height === 0) return false;
    const pixels = new Uint8Array(canvas.width * canvas.height * 4);
    context.readPixels(0, 0, canvas.width, canvas.height, context.RGBA, context.UNSIGNED_BYTE, pixels);
    for (let index = 0; index < pixels.length; index += 4) {
      if (pixels[index] !== 0 || pixels[index + 1] !== 0 || pixels[index + 2] !== 0) return true;
    }
    return false;
  });
  expect(drawn).toBe(true);

  await page.getByRole("button", { name: "暂停" }).click();
  await expect(page.getByRole("button", { name: "继续" })).toBeEnabled();
  const pausedTick = Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, ""));
  await page.waitForTimeout(1_200);
  await expect(page.locator(".tick-readout")).toHaveText(`T+${pausedTick.toString().padStart(4, "0")}`);
  await page.getByRole("button", { name: "继续" }).click();
  await expect.poll(async () => Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, ""))).toBeGreaterThan(pausedTick);

  const range = page.locator("input.timeline-range");
  await range.evaluate((input: HTMLInputElement) => {
    input.value = "0";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator(".tick-readout")).toHaveText("T+0000");
  await page.getByRole("button", { name: "返回最新" }).click();
  await expect.poll(async () => Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, ""))).toBeGreaterThan(0);

  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("button[title='结束当前运行']").click();
  await expect(page.locator("button[title='结束当前运行']")).toBeDisabled();
  await expect(page.locator(".map-title")).toContainText("已结束");
  await expect(page.locator("button[aria-label='播放回放']")).toBeVisible();

  if (testInfo.project.name === "desktop") {
    const mapBox = await page.locator(".city-map").boundingBox();
    const menuBox = await page.locator(".menu-drawer").boundingBox();
    const inspectorBox = await page.locator(".map-inspector").boundingBox();
    const timelineBox = await page.locator(".timeline").boundingBox();
    expect(mapBox).not.toBeNull();
    expect(menuBox).not.toBeNull();
    expect(inspectorBox).not.toBeNull();
    expect(timelineBox).not.toBeNull();
    expect(menuBox!.x + menuBox!.width).toBeLessThanOrEqual(mapBox!.x + 1);
    expect(mapBox!.x + mapBox!.width).toBeLessThanOrEqual(inspectorBox!.x + 1);
    expect(mapBox!.y + mapBox!.height).toBeLessThanOrEqual(timelineBox!.y + 1);
  } else {
    await page.getByRole("button", { name: "关闭控制面板" }).click();
    await expect(page.locator(".menu-drawer")).not.toBeVisible();
    const mapBox = await page.locator(".city-map").boundingBox();
    const timelineBox = await page.locator(".timeline").boundingBox();
    expect(mapBox?.x).toBe(0);
    expect(mapBox?.width).toBe(page.viewportSize()?.width);
    expect(mapBox!.y + mapBox!.height).toBeLessThanOrEqual(timelineBox!.y + 1);
  }

  await expect(page.locator("body")).toBeVisible();
  expect(consoleErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("lifecycle.png"), fullPage: true });
});

test("generates random towns with people, vehicles, and heat", async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto("/");
  if (testInfo.project.name === "mobile") {
    await page.getByRole("button", { name: "控制", exact: true }).click();
  }
  await page.getByLabel("世界种子").fill("");
  await page.getByLabel("居民数量").fill("11499");
  await page.getByRole("button", { name: "生成城镇" }).click();
  await expect(page.locator(".scenario-meta").filter({ hasText: "已就绪" })).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".map-title h1")).not.toHaveText("", { timeout: 20_000 });
  const firstTown = (await page.locator(".map-title h1").innerText()).trim();
  await expect(page.locator(".map-inspector .inspector-heading strong")).toHaveText(firstTown);
  await page.getByRole("button", { name: "生成城镇" }).click();
  await expect(page.locator(".map-title h1")).not.toHaveText(firstTown, { timeout: 20_000 });
  await expect(page.locator(".scenario-meta").filter({ hasText: "已就绪" })).toBeVisible({ timeout: 20_000 });
  const secondTown = (await page.locator(".map-title h1").innerText()).trim();
  expect(secondTown).not.toBe("");
  await expect(page.locator(".map-inspector .inspector-heading strong")).toHaveText(secondTown);
  await expect(page.locator(".scenario-meta").filter({ hasText: "已就绪" })).toBeVisible();

  const startButton = page.getByRole("button", { name: "启动模拟" });
  await expect(startButton).toBeEnabled();
  await startButton.click();
  await expect(startButton).toBeDisabled();
  await expect(page.locator(".history-row[aria-current='true'] small")).toContainText(secondTown, { timeout: 20_000 });
  await expect.poll(async () => Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, "")), {
    timeout: 20_000,
  }).toBeGreaterThanOrEqual(2);
  await expect(page.locator(".map-legend")).toContainText("人流样本");
  await expect(page.locator(".map-legend")).toContainText("车辆样本");
  await expect(page.locator(".map-legend")).toContainText("人流方向热力");
  await expect(page.locator("canvas#deckgl-overlay")).toBeVisible();

  if (testInfo.project.name === "mobile") {
    await page.getByRole("button", { name: "关闭控制面板" }).click();
    await expect(page.locator(".menu-drawer")).not.toBeVisible();
  }
  await page.getByRole("button", { name: "车流", exact: true }).click();
  await expect(page.locator(".map-legend")).toContainText("车流方向热力");
  if (testInfo.project.name === "mobile") {
    await page.getByRole("button", { name: "控制", exact: true }).click();
    await expect(page.locator(".menu-drawer")).toBeVisible();
  }
  await page.getByLabel("方向热力").uncheck();
  await expect(page.locator(".map-legend")).not.toContainText("方向热力");
  await page.getByLabel("方向热力").check();
  await expect(page.locator(".menu-drawer")).toBeVisible();

  if (testInfo.project.name === "mobile") {
    await page.getByRole("button", { name: "关闭控制面板" }).click();
    await expect(page.locator(".menu-drawer")).not.toBeVisible();
  }

  expect(consoleErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("generated-town.png"), fullPage: true });
});
