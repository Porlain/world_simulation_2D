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
  await expect(page.locator(".map-title h1")).toContainText("示例城");

  const openMenu = async () => {
    const dialog = page.locator("dialog.menu-dialog");
    if (!(await dialog.getAttribute("open"))) {
      await page.getByRole("button", { name: "打开 Menu" }).click();
    }
    await expect(dialog).toBeVisible();
  };
  const closeMenu = async () => {
    const dialog = page.locator("dialog.menu-dialog");
    if (await dialog.getAttribute("open")) {
      await page.getByRole("button", { name: "关闭 Menu" }).click();
    }
    if (await dialog.isVisible()) await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
  };

  await openMenu();
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

  await openMenu();
  await page.getByRole("button", { name: "暂停" }).click();
  await expect(page.getByRole("button", { name: "继续" })).toBeEnabled();
  const pausedTick = Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, ""));
  await page.waitForTimeout(1_200);
  await expect(page.locator(".tick-readout")).toHaveText(`T+${pausedTick.toString().padStart(4, "0")}`);
  await page.getByRole("button", { name: "继续" }).click();
  await expect.poll(async () => Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, ""))).toBeGreaterThan(pausedTick);
  await closeMenu();

  const range = page.locator("input.timeline-range");
  await range.evaluate((input: HTMLInputElement) => {
    input.value = "0";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator(".tick-readout")).toHaveText("T+0000");
  await page.getByRole("button", { name: "返回最新" }).click();
  await expect.poll(async () => Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, ""))).toBeGreaterThan(0);

  await openMenu();
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("button[title='结束当前运行']").click();
  await expect(page.locator("button[title='结束当前运行']")).toBeDisabled();
  await expect(page.locator(".map-title")).toContainText("已结束");
  await closeMenu();
  await expect(page.locator("button[aria-label='播放回放']")).toBeVisible();

  if (testInfo.project.name === "desktop") {
    const boxes = await page.locator(".map-workspace, .timeline").evaluateAll((elements) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect();
        return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
      }),
    );
    expect(boxes).toHaveLength(2);
    expect(boxes[0].left).toBe(0);
    expect(boxes[0].right).toBe(1440);
    expect(boxes[0].bottom).toBeLessThanOrEqual(boxes[1].top + 1);
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
  await page.getByRole("button", { name: "打开 Menu" }).click();
  await page.getByLabel("世界种子").fill("8815907750467");
  await page.getByLabel("居民数量").fill("11499");
  await page.getByRole("button", { name: "生成城镇" }).click();
  await expect(page.locator(".map-title h1")).toHaveText("Town-8815907750467", { timeout: 20_000 });
  await page.getByRole("button", { name: "打开 Menu" }).click();
  await expect(page.locator(".scenario-meta").filter({ hasText: "已就绪" })).toBeVisible();

  await page.getByRole("button", { name: "启动模拟" }).click();
  await expect.poll(async () => Number((await page.locator(".tick-readout").innerText()).replace(/\D/g, "")), {
    timeout: 20_000,
  }).toBeGreaterThanOrEqual(2);
  await expect(page.locator(".map-legend")).toContainText("人流");
  await expect(page.locator(".map-legend")).toContainText("车流");
  await expect(page.locator(".map-legend")).toContainText("热力");
  await expect(page.locator("canvas#deckgl-overlay")).toBeVisible();

  await page.getByRole("button", { name: "打开 Menu" }).click();
  await page.getByLabel("热力").uncheck();
  await expect(page.locator(".map-legend")).not.toContainText("热力");
  await page.getByLabel("热力").check();
  await page.keyboard.press("Escape");
  await expect(page.locator("dialog.menu-dialog")).not.toBeVisible();

  expect(consoleErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("generated-town.png"), fullPage: true });
});
