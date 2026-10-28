import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { writeFile, unlink } from "node:fs/promises";
import { browserExecutable } from "./browser.mjs";
const browser = await chromium.launch({
  executablePath: await browserExecutable(),
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  reducedMotion: "reduce",
  acceptDownloads: true,
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const result = { errors };
await page.goto("http://127.0.0.1:4401/?campaign=fg-a7f42769f2&camera=top");
await page
  .getByRole("button", { name: "Fork this failure", exact: true })
  .click();
await page.getByRole("combobox", { name: "Intervention factor" }).waitFor();
const intervention = Number(process.env.FORGE_QA_INTERVENTION || "0.065");
const slider = page.getByRole("slider", {
  name: "Intervention Obstacle Height",
});
await slider.focus();
await slider.press("Home");
for (let step = 0; step < Math.round((intervention - 0.045) / 0.005); step++)
  await slider.press("ArrowRight");
await page
  .getByRole("combobox", { name: "Fresh paired draws" })
  .selectOption(process.env.FORGE_QA_DRAWS || "5");
const posted = page.waitForResponse(
  (response) =>
    response.url().endsWith("/api/incidents") &&
    response.request().method() === "POST",
);
await page
  .getByRole("button", { name: "Run paired experiment", exact: true })
  .click();
const response = await posted;
const submitted = await response.json();
if (!response.ok()) throw Error(JSON.stringify(submitted));
result.id = submitted.id;
console.log(`Started actual diagnostic ${submitted.id}`);
result.submitted = JSON.parse(response.request().postData());
let offlineInjected = false;
await page.route(`**/api/incidents/${submitted.id}`, (route) => {
  if (!offlineInjected && route.request().method() === "GET") {
    offlineInjected = true;
    return route.abort("internetdisconnected");
  }
  return route.continue();
});
await page.locator(".fork-results").waitFor();
await page.waitForFunction(
  () =>
    document
      .querySelector(".fork-result-heading .status")
      ?.textContent?.includes("Completed"),
  null,
  { timeout: 180000 },
);
result.offlineInjected = offlineInjected;
result.formPreserved = Number(await slider.inputValue()) === intervention;
result.freshHeadline = await page
  .locator(".fork-result-heading h2")
  .innerText();
result.uncertainty = await page.locator(".fork-uncertainty").innerText();
result.final = await (
  await page.request.get(`http://127.0.0.1:4401/api/incidents/${submitted.id}`)
).json();
result.freshCountMatches =
  result.final.summary.fresh_pairs === result.final.config.nuisance_repeats;
result.anchorExcluded =
  result.final.summary.anchor_pairs === 1 &&
  result.final.pairs.length === result.final.summary.fresh_pairs + 1;
result.measuredReplay = await page
  .locator(".fork-results .replay-instrument")
  .isVisible();
const freshButton = page.getByRole("button", {
  name: "Replay fresh 1",
  exact: true,
});
await freshButton.click();
result.freshReplaySelection =
  (await freshButton.getAttribute("aria-pressed")) === "true";
await page.getByRole("button", { name: "Replay anchor", exact: true }).click();
const audit = await new AxeBuilder({ page })
  .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
  .analyze();
result.axe = audit.violations.map((v) => ({
  id: v.id,
  nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })),
}));
await page.locator(".fork-result-heading").scrollIntoViewIfNeeded();
await page.screenshot({
  path: "web/qa-output/incident/fork-result-1440.jpg",
  quality: 85,
});
const downloaded = page.waitForEvent("download");
await page
  .getByRole("button", { name: "Export executable incident test", exact: true })
  .click();
const download = await downloaded;
const temp = `/tmp/forge-ui-${submitted.id}.zip`;
await download.saveAs(temp);
result.exportFilename = download.suggestedFilename();
result.exportDownload = !(await download.failure());
await unlink(temp);
await page.setViewportSize({ width: 390, height: 844 });
result.mobileDrawerOverflow = await page.evaluate(() => {
  const e = document.querySelector(".drawer-content");
  return e.scrollWidth > e.clientWidth + 1;
});
const mobileAudit = await new AxeBuilder({ page })
  .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
  .analyze();
result.mobileAxe = mobileAudit.violations.map((v) => ({
  id: v.id,
  nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })),
}));
await writeFile(
  "web/qa-output/incident/live-run.json",
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (
  errors.length ||
  result.axe.length ||
  result.mobileAxe.length ||
  result.mobileDrawerOverflow ||
  !result.formPreserved ||
  !result.anchorExcluded ||
  !result.freshCountMatches ||
  !result.exportDownload
)
  process.exitCode = 1;
