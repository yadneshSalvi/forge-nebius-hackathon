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
const result = {
  fixture:
    "Read-only browser transport fixture: stale queued history and a running detail precede the real canceled API response. Failed/interrupted variants only alter private browser responses; no server writes or physics.",
  mutations: [],
  pageErrors: [],
};
page.on("request", (request) => {
  if (request.url().includes("/api/") && request.method() !== "GET")
    result.mutations.push(request.method());
});
page.on("pageerror", (error) => result.pageErrors.push(error.message));
const jobs = await (
  await page.request.get("http://127.0.0.1:4401/api/incidents")
).json();
const canceled = jobs.find((job) => job.status === "canceled");
const completed = jobs.find((job) => job.status === "completed");
if (!canceled || !completed)
  throw new Error(
    "Read-only QA needs retained canceled and completed records.",
  );
result.canceled = canceled.id;
result.completed = completed.id;
await page.route("**/api/incidents", (route) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(
      jobs.map((job) =>
        job.id === canceled.id ? { ...job, status: "queued" } : job,
      ),
    ),
  }),
);
let firstDetail = true;
await page.route(`**/api/incidents/${canceled.id}`, (route) => {
  if (firstDetail) {
    firstDetail = false;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...canceled, status: "running" }),
    });
  }
  return route.continue();
});
await page.goto("http://127.0.0.1:4401/?campaign=fg-a7f42769f2&camera=top");
await page
  .getByRole("button", { name: "Fork this failure", exact: true })
  .click();
await page.getByRole("combobox", { name: "Intervention factor" }).waitFor();
const row = (id) =>
  page.locator(".fork-history>button").filter({ hasText: id });
result.staleFixtureVisible = (await row(canceled.id).innerText()).includes(
  "Queued",
);
await row(canceled.id).click();
await page
  .getByRole("heading", { name: "Run canceled", exact: true })
  .waitFor();
result.canceledHeading = true;
const expected = `${canceled.progress.completed} of ${canceled.progress.total} physical episodes completed`;
result.partialCountExact = (
  await page.locator(".fork-progress").innerText()
).includes(expected);
result.partialEvidenceExplicit = (
  await page.locator(".fork-progress").innerText()
).includes("Partial evidence retained");
await row(completed.id).click();
result.historyTerminalRetained = (await row(canceled.id).innerText()).includes(
  "Canceled",
);
for (const [status, title] of [
  ["failed", "Run failed"],
  ["interrupted", "Run interrupted"],
]) {
  await page.unroute(`**/api/incidents/${canceled.id}`);
  await page.route(`**/api/incidents/${canceled.id}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...canceled, status }),
    }),
  );
  await row(canceled.id).click();
  await page.getByRole("heading", { name: title, exact: true }).waitFor();
  result[`${status}Copy`] = (
    await page.locator(".fork-progress").innerText()
  ).includes(expected);
}
const audit = await new AxeBuilder({ page })
  .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
  .analyze();
result.axe = audit.violations.map((violation) => violation.id);
await writeFile(
  "web/qa-output/incident/terminal-history.json",
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (
  result.mutations.length ||
  result.pageErrors.length ||
  result.axe.length ||
  Object.values(result).some((value) => value === false)
)
  process.exitCode = 1;
