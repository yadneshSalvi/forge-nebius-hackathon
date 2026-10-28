import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFile, writeFile, unlink } from "node:fs/promises";
import { createHash } from "node:crypto";
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
await page.addInitScript(() => {
  const original = URL.createObjectURL.bind(URL);
  URL.createObjectURL = (blob) => {
    window.__forgeExportBlob = blob;
    return original(blob);
  };
});
const result = { pageErrors: [], mutations: [] };
page.on("pageerror", (error) => result.pageErrors.push(error.message));
page.on("request", (request) => {
  if (request.url().includes("/api/") && request.method() !== "GET")
    result.mutations.push({ method: request.method(), url: request.url() });
});
const jobs = await (
  await page.request.get("http://127.0.0.1:4401/api/incidents")
).json();
const job = jobs.find((item) =>
  process.env.FORGE_QA_INCIDENT
    ? item.id === process.env.FORGE_QA_INCIDENT
    : item.status === "completed",
);
if (!job)
  throw new Error(
    "No completed incident is available for this read-only download check.",
  );
result.incident = job.id;
await page.goto("http://127.0.0.1:4401/?campaign=fg-a7f42769f2&camera=top");
await page
  .getByRole("button", { name: "Fork this failure", exact: true })
  .click();
await page.getByRole("combobox", { name: "Intervention factor" }).waitFor();
await page.locator(".fork-history>button").filter({ hasText: job.id }).click();
const exportButton = page.getByRole("button", {
  name: "Export executable incident test",
  exact: true,
});
await exportButton.waitFor();
const exportUrl = `/api/incidents/${job.id}/export`;
let first = true;
await page.route(`**${exportUrl}`, async (route) => {
  if (first) {
    first = false;
    await new Promise((resolve) => setTimeout(resolve, 300));
    return route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "QA transport interruption: retry this export.",
      }),
    });
  }
  return route.continue();
});
await exportButton.click();
result.pendingVisible = await page
  .getByRole("button", { name: "Preparing incident test…", exact: true })
  .isDisabled();
await page
  .getByText("QA transport interruption: retry this export.", { exact: true })
  .waitFor();
result.errorVisible = true;
const downloaded = page.waitForEvent("download");
const fetched = page.waitForResponse(
  (response) => response.url().endsWith(exportUrl) && response.ok(),
);
await page
  .locator(".fork-export-area")
  .getByRole("button", { name: "Try again", exact: true })
  .click();
const response = await fetched;
const expected = await response.body();
const download = await downloaded;
const temp = `/tmp/forge-export-check-${job.id}.zip`;
await download.saveAs(temp);
const bytes = await readFile(temp);
result.downloadFailure = await download.failure();
result.blobDownload = download.url().startsWith("blob:");
result.filename = download.suggestedFilename();
result.expectedFilename = `forge-${job.id}-incident.zip`;
result.bytes = bytes.length;
result.zipSignature = bytes.readUInt32LE(0) === 0x04034b50;
const sourceBlob = await page.evaluate(async () => {
  const blob = window.__forgeExportBlob;
  const digest = new Uint8Array(
    await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
  );
  return {
    bytes: blob.size,
    sha256: [...digest]
      .map((value) => value.toString(16).padStart(2, "0"))
      .join(""),
  };
});
result.sourceBlob = sourceBlob;
result.exactFetchedBytes =
  bytes.length === sourceBlob.bytes &&
  createHash("sha256").update(bytes).digest("hex") === sourceBlob.sha256;
result.playwrightAttachmentBodyBytes = expected.length;
result.sha256 = createHash("sha256").update(bytes).digest("hex");
result.successStatus = await page
  .getByText("Incident test download requested.", { exact: true })
  .isVisible();
const audit = await new AxeBuilder({ page })
  .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
  .analyze();
result.axe = audit.violations.map((violation) => ({
  id: violation.id,
  targets: violation.nodes.map((node) => node.target),
}));
await page.locator(".fork-export-area").scrollIntoViewIfNeeded();
await page.screenshot({
  path: "web/qa-output/incident/export-download-1440.jpg",
  quality: 85,
});
await unlink(temp);
await writeFile(
  "web/qa-output/incident/export-download.json",
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (
  result.pageErrors.length ||
  result.mutations.length ||
  result.axe.length ||
  result.downloadFailure ||
  !result.pendingVisible ||
  !result.zipSignature ||
  !result.blobDownload ||
  !result.exactFetchedBytes ||
  result.filename !== result.expectedFilename
)
  process.exitCode = 1;
