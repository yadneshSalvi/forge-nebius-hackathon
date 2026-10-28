import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { writeFile } from "node:fs/promises";
import { browserExecutable } from "./browser.mjs";
const browser = await chromium.launch({
  executablePath: await browserExecutable(),
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
const result = {};
const home = "http://127.0.0.1:4401/?campaign=fg-a7f42769f2&camera=top";
await page.goto(home);
await page.locator(".incident-stage").waitFor();
await page
  .getByRole("button", { name: "Fork this failure", exact: true })
  .click();
await page.keyboard.press("Escape");
result.forkRestoresFocus = await page
  .getByRole("button", { name: "Fork this failure", exact: true })
  .evaluate((el) => el === document.activeElement);
await page
  .getByRole("group", { name: "Select measured failure boundary" })
  .getByRole("button")
  .nth(1)
  .click();
await page.getByText("No bound camera frame", { exact: true }).waitFor();
result.secondaryCameraHidden =
  (await page.locator(".incident-camera img").count()) === 0;
await page.goto(home);
await page.route("**/images/source.png", (r) =>
  r.fulfill({ status: 404, body: "missing" }),
);
await page.reload();
await page.getByText("Camera frame unavailable", { exact: true }).waitFor();
result.missingImageExplained = true;
await page.unroute("**/images/source.png");
await page.goto(home);
await page.locator(".incident-stage").waitFor();
await page.route("**/api/**", (r) => r.abort("internetdisconnected"));
await page
  .getByRole("button", { name: "Reconnect", exact: true })
  .waitFor({ timeout: 7000 });
result.offlineEvidenceRetained = await page
  .locator(".replay-instrument")
  .isVisible();
await page.unroute("**/api/**");
await page.getByRole("button", { name: "Reconnect", exact: true }).click();
await page.locator(".network-banner").waitFor({ state: "hidden" });
result.reconnect = true;
await page
  .getByRole("button", { name: "Fork this failure", exact: true })
  .click();
await page.getByRole("dialog").waitFor();
const audit = await new AxeBuilder({ page })
  .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
  .analyze();
result.drawerAxe = audit.violations.map((v) => ({
  id: v.id,
  nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })),
}));
await page.keyboard.press("Escape");
await page.setViewportSize({ width: 390, height: 844 });
await page
  .getByRole("button", { name: "Open navigation", exact: true })
  .click();
await page.getByRole("button", { name: "Campaigns", exact: true }).click();
result.mobileNavigation =
  new URL(page.url()).searchParams.get("view") === "campaigns";
await writeFile(
  new URL("./qa-output/incident/controls.json", import.meta.url),
  JSON.stringify(result, null, 2),
);
console.log(result);
await browser.close();
if (
  Object.values(result).some((x) => typeof x === "boolean" && !x) ||
  result.drawerAxe.length
)
  process.exitCode = 1;
