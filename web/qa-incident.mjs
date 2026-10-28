import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { browserExecutable } from "./browser.mjs";
const out = new URL("./qa-output/incident/", import.meta.url);
await mkdir(out, { recursive: true });
const browser = await chromium.launch({
  executablePath: await browserExecutable(),
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto("http://127.0.0.1:4401/?campaign=fg-a7f42769f2");
await page.locator(".incident-stage").waitFor();
await page.waitForFunction(
  () => document.querySelectorAll("canvas").length === 2,
);
await page.waitForTimeout(500);
const result = {
  errors,
  firstViewport: await page.evaluate(() =>
    Object.fromEntries(
      [
        ".incident-replay",
        ".incident-camera",
        ".incident-fork-action",
        ".incident-policy-note",
        ".incident-decision-bar",
      ].map((s) => {
        const r = document.querySelector(s).getBoundingClientRect();
        return [
          s,
          {
            x: r.x,
            y: r.y,
            width: r.width,
            height: r.height,
            bottom: r.bottom,
          },
        ];
      }),
    ),
  ),
  checks: [],
  axe: [],
};
await page.screenshot({
  path: new URL("entry-1440.jpg", out).pathname,
  quality: 85,
});
await page
  .getByRole("button", { name: "Fork this failure", exact: true })
  .click();
await page.getByRole("dialog").waitFor();
await page.waitForTimeout(500);
await page.screenshot({
  path: new URL("fork-1440.jpg", out).pathname,
  quality: 85,
});
await page.keyboard.press("Escape");
for (const width of [320, 390, 768, 1280, 1440]) {
  await page.setViewportSize({ width, height: 900 });
  for (const view of [
    "workcell",
    "campaigns",
    "failures",
    "curricula",
    "policies",
    "reports",
  ]) {
    await page.goto(
      `http://127.0.0.1:4401/?view=${view}&campaign=fg-a7f42769f2&camera=top`,
    );
    await page.locator("h1").waitFor();
    await page.waitForFunction(() => !document.querySelector(".loading-state"));
    const sizes = await page.evaluate(() => ({
      width: innerWidth,
      scroll: document.documentElement.scrollWidth,
    }));
    result.checks.push({ width, view, overflow: sizes.scroll > width + 1 });
    if ([390, 1440].includes(width)) {
      const audit = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      result.axe.push({
        width,
        view,
        violations: audit.violations.map((v) => ({
          id: v.id,
          nodes: v.nodes.map((n) => ({
            target: n.target,
            summary: n.failureSummary,
          })),
        })),
      });
    }
    if (view === "workcell" && width === 390)
      await page.screenshot({
        path: new URL("entry-390.jpg", out).pathname,
        quality: 85,
      });
  }
  console.log(`Checked ${width}px`);
}
await writeFile(new URL("ui.json", out), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (
  result.errors.length ||
  result.checks.some((v) => v.overflow) ||
  result.axe.some((v) => v.violations.length)
)
  process.exitCode = 1;
