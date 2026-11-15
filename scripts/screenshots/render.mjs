import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { chromium } from "playwright";

const root = "/work";
const types = { ".html": "text/html", ".js": "text/javascript" };
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

const browser = await chromium.launch();
const errors = [];
async function shot(name, query, viewport, actions = async () => {}) {
  const page = await browser.newPage({ viewport, deviceScaleFactor: 2 });
  page.on("console", (msg) => msg.type() === "error" && errors.push(`${name}: ${msg.text()}`));
  page.on("pageerror", (err) => errors.push(`${name}: ${err.message}`));
  await page.goto(`http://localhost:8080/readme.html?${query}`);
  await page.waitForSelector("notification-journal-record");
  await actions(page);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${root}/out/${name}.png`, fullPage: false, animations: "disabled" });
  await page.close();
}


const group = async (page) => {
  await page.locator("button.chip.group").first().click();
};
const byOrigin = async (page) => {
  await page.locator(".view button").nth(1).click();
  await page.waitForTimeout(300);
};
await shot("timeline-light", "lang=en", { width: 1280, height: 1180 }, group);
await shot("timeline-dark", "lang=en&theme=dark", { width: 1280, height: 1180 }, group);
await shot("automations-light", "lang=en", { width: 1280, height: 1000 }, byOrigin);
await shot("automations-dark", "lang=en&theme=dark", { width: 1280, height: 1000 }, byOrigin);
const statistics = async (page) => {
  await page.locator('button[title="Statistics"]').click();
  await page.waitForSelector("notification-journal-statistics .stats");
  await page.locator("notification-journal-statistics .hit").last().hover();
};
await shot("statistics-light", "lang=en", { width: 1280, height: 1100 }, statistics);
await shot("statistics-dark", "lang=en&theme=dark", { width: 1280, height: 1100 }, statistics);
await shot("mobile-light", "lang=en&narrow=1", { width: 390, height: 844 });
await shot("mobile-dark", "lang=en&narrow=1&theme=dark", { width: 390, height: 844 });
console.log(errors.length ? errors.join("\n") : "no console errors");
await browser.close();
server.close();
