import { expect, test } from "@playwright/test";

test.afterEach(async ({ request }) => {
  const response = await request.get("/api/runs?limit=20");
  if (!response.ok()) return;
  const body = (await response.json()) as { items: Array<{ id: string; status: string }> };
  const active = body.items.find((run) => run.status === "running" || run.status === "paused");
  if (active) await request.post(`/api/runs/${active.id}/commands`, { data: { action: "end" } });
});

test("runs, pauses, seeks, and ends a city simulation", async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto("/");
  await expect(page.locator(".city-map")).toBeVisible();
  await expect(page.locator(".brand-lockup h1")).toContainText("示例城");

  const openControls = async () => {
    if (testInfo.project.name !== "mobile") return;
    const open = await page.locator(".panel-shell--controls").evaluate((element) => element.classList.contains("panel-shell--open"));
    if (!open) await page.getByRole("button", { name: "打开控制面板" }).click();
  };
  const closeControls = async () => {
    if (testInfo.project.name !== "mobile") return;
    const open = await page.locator(".panel-shell--controls").evaluate((element) => element.classList.contains("panel-shell--open"));
    if (open) await page.getByRole("button", { name: "打开控制面板" }).click();
  };

  await openControls();
  await page.getByRole("button", { name: "启动模拟" }).click();
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

  await openControls();
  await page.getByRole("button", { name: "暂停" }).click();
  const pausedTick = Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, ""));
  await page.waitForTimeout(1_200);
  await expect(page.locator(".tick-readout")).toHaveText(`T+${pausedTick.toString().padStart(4, "0")}`);
  await page.getByRole("button", { name: "继续" }).click();
  await expect.poll(async () => Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, ""))).toBeGreaterThan(pausedTick);
  await closeControls();

  const range = page.locator("input.timeline-range");
  await range.evaluate((input: HTMLInputElement) => {
    input.value = "0";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator(".tick-readout")).toHaveText("T+0000");
  await page.getByRole("button", { name: "返回最新" }).click();
  await expect.poll(async () => Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, ""))).toBeGreaterThan(0);

  await openControls();
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("button[title='结束当前运行']").click();
  await expect(page.locator("button[title='结束当前运行']")).toBeDisabled();
  await expect(page.locator(".topbar-readout")).toContainText("已结束");
  await expect(page.locator("button[aria-label='播放回放']")).toBeVisible();

  if (testInfo.project.name === "desktop") {
    const boxes = await page.locator(".panel-shell--controls, .map-workspace, .panel-shell--stats, .timeline").evaluateAll((elements) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect();
        return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
      }),
    );
    expect(boxes).toHaveLength(4);
    expect(boxes[0].right).toBeLessThanOrEqual(boxes[1].left + 1);
    expect(boxes[1].right).toBeLessThanOrEqual(boxes[2].left + 1);
  }

  await expect(page.locator("body")).toBeVisible();
  expect(consoleErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("lifecycle.png"), fullPage: true });
});

test("generates a seeded town with people, vehicles, and heat", async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto("/");
  if (testInfo.project.name === "mobile") await page.getByRole("button", { name: "打开控制面板" }).click();
  await page.getByLabel("世界种子").fill("8815907750467");
  await page.getByLabel("居民数量").fill("11499");
  await page.getByRole("button", { name: "生成城镇" }).click();
  await expect(page.locator(".map-source")).toHaveText("RADIAL-V1", { timeout: 20_000 });
  await expect(page.locator(".scenario-meta").filter({ hasText: "已就绪" })).toBeVisible();

  await page.getByRole("button", { name: "启动模拟" }).click();
  await expect.poll(async () => Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, "")), {
    timeout: 20_000,
  }).toBeGreaterThanOrEqual(2);
  await expect(page.locator(".map-legend")).toContainText("人流");
  await expect(page.locator(".map-legend")).toContainText("车流");
  await expect(page.locator(".map-legend")).toContainText("热力");
  await expect(page.locator("canvas#deckgl-overlay")).toBeVisible();

  expect(consoleErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("generated-town.png"), fullPage: true });
});
