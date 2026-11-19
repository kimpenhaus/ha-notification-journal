import { createServer } from "node:http";
import { mkdir, readFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { chromium } from "playwright";
import sharp from "sharp";

const root = "/work";
// A Saturday afternoon: the mock data's "today" and the camera snapshots' timestamps.
const NOW = new Date("2026-11-21T16:40:00Z");
const types = { ".html": "text/html", ".js": "text/javascript", ".jpg": "image/jpeg", ".png": "image/png" };
const server = createServer(async (req, res) => {
  const path = join(root, new URL(req.url, "http://x").pathname);
  try {
    const body = await readFile(path);
    res.writeHead(200, { "Content-Type": types[extname(path)] ?? "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end();
  }
}).listen(8080);

await mkdir(`${root}/raw`, { recursive: true });
const browser = await chromium.launch();
const errors = [];
const watch = (page, name) => {
  page.on("console", (msg) => msg.type() === "error" && errors.push(`${name}: ${msg.text()}`));
  page.on("pageerror", (err) => errors.push(`${name}: ${err.message}`));
};

/** The bottom of the last card or heading that fits into the viewport, so a shot never ends in the middle of one. */
const lastWholeCard = async (page) => {
  const height = page.viewportSize().height;
  const boxes = await page.locator("notification-journal-record, button.section").evaluateAll((items) =>
    items.map((item) => item.getBoundingClientRect()).filter((box) => box.height).map(({ top, bottom }) => ({ top, bottom })),
  );
  const bottom = Math.max(...boxes.map((box) => box.bottom).filter((bottom) => bottom <= height));
  const next = Math.min(...boxes.map((box) => box.top).filter((top) => top > bottom));
  return Math.min(bottom + 24, next - 1);
};

async function shot(name, query, viewport, actions = async () => {}, bottom = lastWholeCard) {
  const page = await browser.newPage({ viewport, deviceScaleFactor: 2 });
  watch(page, name);
  await page.clock.setFixedTime(NOW);
  await page.goto(`http://localhost:8080/readme.html?${query}`);
  await page.waitForSelector("notification-journal-record");
  await page.evaluate(() => document.fonts.ready);
  await actions(page);
  await page.waitForTimeout(400);
  const height = bottom ? Math.ceil(await bottom(page)) : viewport.height;
  await page.screenshot({ path: `${root}/raw/${name}.png`, clip: { x: 0, y: 0, width: viewport.width, height }, animations: "disabled" });
  await page.close();
}

// Sharp enough for the README's retina display, and quantised to a palette to keep the repository small.
async function frame(name, query, deviceScaleFactor = 1.25) {
  const page = await browser.newPage({ viewport: { width: 1800, height: 1400 }, deviceScaleFactor });
  watch(page, name);
  await page.goto(`http://localhost:8080/frame.html?${query}`);
  await page.waitForSelector("body[data-ready]");
  const png = await page.locator("#stage").screenshot({ omitBackground: true });
  await sharp(png).png({ palette: true, quality: 90, effort: 10 }).toFile(`${root}/out/${name}.png`);
  await page.close();
}

const group = async (page) => {
  await page.locator("button.chip.group").first().click();
};
const byOrigin = async (page) => {
  await page.locator(".view button").nth(1).click();
  await page.waitForTimeout(300);
  await page.getByRole("button", { name: "Collapse all" }).click();
  await page.locator("button.section.group").nth(1).click();
};
const partlyFailed = async (page) => {
  await page.locator("select:has(option[value=partial])").selectOption("partial");
  await page.locator("notification-journal-record").nth(1).waitFor({ state: "detached" });
  await group(page);
};
const statistics = async (page) => {
  await page.locator('button[title="Statistics"]').click();
  await page.waitForSelector("notification-journal-statistics .stats");
  await page.locator("notification-journal-statistics .hit").nth(5).hover();
};
const statisticsEnd = async (page) => {
  const box = await page.locator("notification-journal-statistics .stats").boundingBox();
  return box.y + box.height + 32;
};

for (const theme of ["light", "dark"]) {
  const query = `lang=en&theme=${theme}`;
  await shot(`timeline-${theme}`, query, { width: 1280, height: 1250 }, group);
  await shot(`automations-${theme}`, query, { width: 1280, height: 1100 }, byOrigin);
  await shot(`failed-${theme}`, query, { width: 1280, height: 900 }, partlyFailed);
  await shot(`statistics-${theme}`, query, { width: 1280, height: 1400 }, statistics, statisticsEnd);
  await shot(`mobile-${theme}`, `${query}&narrow=1`, { width: 390, height: 844 }, async () => {}, null);

  await frame(`hero-nordic-${theme}`, `theme=${theme}&layout=hero&a=timeline-${theme}&b=mobile-${theme}`);
  for (const view of ["timeline", "automations", "failed", "statistics"]) {
    await frame(`${view}-nordic-${theme}`, `theme=${theme}&layout=window&a=${view}-${theme}`);
  }
}
// GitHub shows the social preview at 1280 × 640 and takes it only by hand, under Settings → General.
await frame("social-preview-nordic-light", "theme=light&layout=social&a=timeline-light&b=mobile-light", 1);
console.log(errors.length ? errors.join("\n") : "no console errors");
await browser.close();
server.close();
