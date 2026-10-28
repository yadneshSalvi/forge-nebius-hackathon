import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { writeFile } from "node:fs/promises";
import { browserExecutable } from "./browser.mjs";

const executablePath = await browserExecutable();
const browser = await chromium.launch({ executablePath, headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
const bootstrap = await (
  await page.request.get("http://127.0.0.1:4401/api/bootstrap")
).json();
const id = process.env.FORGE_QA_CAMPAIGN || bootstrap.selected_campaign_id;
const campaign = await (
  await page.request.get(`http://127.0.0.1:4401/api/campaigns/${id}`)
).json();
const result = {
  campaign: id,
  cluster: null,
  contact: null,
  playback: null,
  webglFallback: null,
};
await page.goto(
  `http://127.0.0.1:4401/?view=failures&campaign=${id}&camera=top`,
);
await page.locator(".active-campaign-strip select").waitFor();
const secondary = campaign.counterexample?.secondary_boundaries?.[0];
if (secondary) {
  const selector = page.getByRole("group", {
    name: "Select measured failure boundary",
  });
  await selector.getByRole("button").nth(1).click();
  await page.waitForFunction(
    (prefix) =>
      document
        .querySelector(".scene-source .scene-pane-footer .mono")
        ?.textContent?.startsWith(prefix),
    secondary.source_episode_id.slice(0, 22),
  );
  const source = (
    await page.locator(".scene-source .scene-pane-footer .mono").innerText()
  ).trim();
  const reduced = (
    await page.locator(".scene-reduced .scene-pane-footer .mono").innerText()
  ).trim();
  result.cluster = {
    urlBoundary: new URL(page.url()).searchParams.get("boundary"),
    sourceMatches: secondary.source_episode_id.startsWith(source),
    reducedMatches: secondary.minimized_episode_id.startsWith(reduced),
    hypothesisLabel: await page
      .locator(".hypothesis-block .evidence-type")
      .innerText(),
  };
  await page.screenshot({
    path: new URL("./qa-output/secondary-boundary-1440.png", import.meta.url)
      .pathname,
    fullPage: true,
  });
  await selector.getByRole("button").nth(0).click();
}
await page
  .getByRole("button", { name: "Inspect oracle evidence", exact: true })
  .click();
await page.getByRole("dialog").waitFor();
const contactButton = page.getByRole("button", {
  name: "Inspect first replay frame after contact",
  exact: true,
});
if (await contactButton.count()) {
  const episode = await (
    await page.request.get(
      `http://127.0.0.1:4401/api/episodes/${campaign.counterexample.minimized_episode_id}`,
    )
  ).json();
  await contactButton.click();
  const sample = Number(await page.locator("#sample-seek").inputValue());
  const first = episode.metrics.first_violation.time;
  const at = episode.trace.frames[sample].time;
  const preceding = episode.trace.frames[Math.max(0, sample - 1)].time;
  result.contact = {
    firstViolationSeconds: first,
    selectedSampleSeconds: at,
    precedingSampleSeconds: preceding,
    firstAtOrAfter: at >= first && (sample === 0 || preceding < first),
  };
}
await page.keyboard.press("Escape");
await page.goto(`http://127.0.0.1:4401/?campaign=${id}`);
await page.locator("canvas").first().waitFor();
await page.waitForFunction(
  () => document.querySelectorAll("canvas").length === 2,
);
await page.waitForTimeout(700);
result.playback = await page.evaluate(async () => {
  const input = document.querySelector(".timeline-slider");
  const before = Number(input.value);
  let commits = 0;
  const observer = new MutationObserver(() => commits++);
  observer.observe(input, { attributes: true, attributeFilter: ["value"] });
  const start = performance.now();
  document.querySelector('[aria-label="Play replay"]').click();
  await new Promise((resolve) => setTimeout(resolve, 1600));
  document.querySelector('[aria-label="Pause replay"]').click();
  observer.disconnect();
  const wall = (performance.now() - start) / 1000;
  return {
    measurement:
      "DOM playback-state commits with two WebGL scenes; not a GPU frame-time benchmark",
    wallSeconds: wall,
    simulationAdvanceSeconds: Number(input.value) - before,
    stateCommits: commits,
    commitsPerSecond: commits / wall,
  };
});
await browser.close();
await writeFile(
  new URL("./qa-output/replay-integrity.json", import.meta.url),
  JSON.stringify(result, null, 2),
);
const fallbackBrowser = await chromium.launch({
  executablePath,
  headless: true,
  args: ["--disable-webgl"],
});
const fallbackContext = await fallbackBrowser.newContext({
  viewport: { width: 1280, height: 900 },
  reducedMotion: "reduce",
});
const fallback = await fallbackContext.newPage();
await fallback.goto(`http://127.0.0.1:4401/?campaign=${id}`);
await fallback
  .locator(".scene-fidelity-note")
  .first()
  .waitFor({ timeout: 15000 });
const axe = await new AxeBuilder({ page: fallback })
  .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
  .analyze();
result.webglFallback = {
  labeledPanes: await fallback.locator(".scene-fidelity-note").count(),
  staticTopViews: await fallback.locator(".top-view").count(),
  objectInspectorAvailable: await fallback
    .getByRole("button", { name: "Inspect measured objects", exact: true })
    .isEnabled(),
  axeViolations: axe.violations.map((v) => v.id),
};
await fallback.screenshot({
  path: new URL("./qa-output/webgl-fallback-1280.png", import.meta.url)
    .pathname,
  fullPage: true,
});
await fallbackBrowser.close();
await writeFile(
  new URL("./qa-output/replay-integrity.json", import.meta.url),
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result, null, 2));
if (
  (result.cluster &&
    (!result.cluster.sourceMatches ||
      !result.cluster.reducedMatches ||
      result.cluster.urlBoundary !== "1")) ||
  (result.contact && !result.contact.firstAtOrAfter) ||
  result.webglFallback.labeledPanes !== 2 ||
  result.webglFallback.staticTopViews !== 2 ||
  result.webglFallback.axeViolations.length
)
  process.exitCode = 1;
