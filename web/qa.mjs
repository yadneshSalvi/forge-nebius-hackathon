import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { browserExecutable } from "./browser.mjs";

const output = new URL("./qa-output/", import.meta.url);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: await browserExecutable(),
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(error.message));
const bootstrap = await (
  await page.request.get("http://127.0.0.1:4401/api/bootstrap")
).json();
const campaign =
  process.env.FORGE_QA_CAMPAIGN || bootstrap.selected_campaign_id || "";
const result = {
  campaign,
  overflow: [],
  axe: [],
  pageErrors,
  interactions: {},
  screenshots: [],
};
const views = process.env.FORGE_QA_VIEWS
  ? process.env.FORGE_QA_VIEWS.split(",")
  : ["workcell", "campaigns", "failures", "curricula", "policies", "reports"];
async function loaded() {
  await page.locator("h1").waitFor();
  if (campaign) await page.locator(".active-campaign-strip select").waitFor();
  await page
    .waitForFunction(() => !document.querySelector(".loading-state"), null, {
      timeout: 10000,
    })
    .catch(() => {});
  await page.evaluate(() => document.fonts.ready);
}
for (const width of [320, 390, 768, 1280, 1440]) {
  await page.setViewportSize({ width, height: 1000 });
  for (const view of views) {
    await page.goto(
      `http://127.0.0.1:4401/?view=${view}&campaign=${campaign}&camera=top`,
    );
    await loaded();
    const overflow = await page.evaluate(() => ({
      width: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      outliers: [...document.querySelectorAll("body *")]
        .filter((el) => {
          const r = el.getBoundingClientRect();
          return (
            r.width > 0 &&
            r.right > innerWidth + 1 &&
            !el.closest(
              ".table-scroll,.matrix-chart,.campaign-library,.arm-tabs,.drawer",
            )
          );
        })
        .slice(0, 8)
        .map((el) => ({
          tag: el.tagName,
          className: typeof el.className === "string" ? el.className : "svg",
          right: el.getBoundingClientRect().right,
        })),
    }));
    if (overflow.scrollWidth > width + 1)
      result.overflow.push({ view, ...overflow });
    if (
      view === "policies" &&
      (await page.locator(".challenge-parameters").count())
    ) {
      const values = await page
        .locator(".challenge-parameters input[type=range]")
        .evaluateAll((inputs) =>
          inputs.map((input) => ({
            id: input.id,
            visible_control: input.valueAsNumber,
            submitted_state: Number(input.getAttribute("value")),
          })),
        );
      result.interactions.challengeRangeValues = values.every(
        (v) => v.visible_control === v.submitted_state,
      );
      result.challengeRangeValues = values;
    }
    if ([390, 1440].includes(width)) {
      const audit = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      if (audit.violations.length)
        result.axe.push({
          width,
          view,
          violations: audit.violations.map((v) => ({
            id: v.id,
            impact: v.impact,
            help: v.help,
            nodes: v.nodes.map((n) => ({
              target: n.target,
              summary: n.failureSummary,
            })),
          })),
        });
    }
    if (
      [390, 1440].includes(width) &&
      ["workcell", "policies", "reports", "campaigns", "curricula"].includes(
        view,
      )
    ) {
      const name = `${view}-${width}.png`;
      await page.screenshot({
        path: new URL(name, output).pathname,
        fullPage: true,
      });
      result.screenshots.push(name);
    }
  }
  console.log(`Checked ${width}px`);
}
await writeFile(
  new URL("responsive-accessibility.json", output),
  JSON.stringify(result, null, 2),
);
await page.setViewportSize({ width: 1440, height: 1000 });
await page.goto(`http://127.0.0.1:4401/?campaign=${campaign}`);
await loaded();
await page
  .waitForFunction(
    () => document.querySelectorAll("canvas").length === 2,
    null,
    { timeout: 12000 },
  )
  .catch(() => {});
await page.waitForTimeout(700);
await page.screenshot({
  path: new URL("workcell-3d-1440.png", output).pathname,
  fullPage: true,
});
result.interactions.canvases = await page.locator("canvas").count();
const launch = page.getByRole("button", { name: "New campaign", exact: true });
await launch.click();
await page.getByRole("dialog").waitFor();
await page
  .getByRole("textbox", { name: /Campaign name/ })
  .fill("Keyboard review");
await page
  .getByRole("button", { name: "Review campaign", exact: true })
  .click();
result.interactions.launchReview = await page
  .getByText("What starts now", { exact: true })
  .isVisible();
await page.keyboard.press("Escape");
result.interactions.dialogRestoresFocus = await launch.evaluate(
  (el) => el === document.activeElement,
);
if (
  await page
    .getByRole("button", { name: "Play replay", exact: true })
    .isEnabled()
    .catch(() => false)
) {
  const slider = page.getByRole("slider", {
    name: "Replay simulation time in seconds",
  });
  const before = Number(await slider.inputValue());
  await page.locator(".replay-controls").focus();
  await page.keyboard.press("ArrowRight");
  const after = Number(await slider.inputValue());
  result.interactions.keyboardSteps = after > before;
  await page.keyboard.press("Space");
  await page.waitForTimeout(180);
  await page.keyboard.press("Space");
  result.interactions.keyboardPlayback =
    Number(await slider.inputValue()) > after;
  await page
    .getByRole("button", { name: "Inspect measured objects", exact: true })
    .click();
  await page.getByRole("dialog").waitFor();
  result.interactions.objectInspector = await page
    .getByText("Measured object state", { exact: true })
    .isVisible();
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Inspect oracle evidence", exact: true })
    .click();
  await page.getByRole("dialog").waitFor();
  result.interactions.oracleRules = await page
    .getByRole("columnheader", { name: "Registered rule", exact: true })
    .isVisible();
  await page.screenshot({
    path: new URL("oracle-inspector-1440.png", output).pathname,
    fullPage: true,
  });
  await page.keyboard.press("Escape");
}
await page.route("**/api/**", (route) => route.abort("internetdisconnected"));
await page
  .getByRole("button", { name: "Reconnect", exact: true })
  .waitFor({ timeout: 7000 });
result.interactions.offlineEvidenceRetained = campaign
  ? await page.locator(".replay-instrument").isVisible()
  : true;
await page.unroute("**/api/**");
await page.getByRole("button", { name: "Reconnect", exact: true }).click();
await page
  .locator(".network-banner")
  .waitFor({ state: "hidden", timeout: 8000 });
result.interactions.networkRecovered = true;
await page.setViewportSize({ width: 390, height: 844 });
await page
  .getByRole("button", { name: "Open navigation", exact: true })
  .click();
await page.getByRole("button", { name: "Campaigns", exact: true }).click();
result.interactions.mobileNavigation =
  new URL(page.url()).searchParams.get("view") === "campaigns";
await writeFile(
  new URL("responsive-accessibility.json", output),
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (
  result.overflow.length ||
  result.axe.length ||
  pageErrors.length ||
  Object.values(result.interactions).some((v) => typeof v === "boolean" && !v)
)
  process.exitCode = 1;
