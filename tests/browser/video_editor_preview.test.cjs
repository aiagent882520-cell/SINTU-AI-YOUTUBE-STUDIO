const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { after, before, test } = require("node:test");
const { chromium } = require("playwright");

const STATIC_ROOT = path.resolve(__dirname, "../../app/static");
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC",
  "base64",
);

let browser;
let server;
let baseUrl;
let tempDir;
let webm;
let videoRangeRequests = [];

function contentType(file) {
  if (file.endsWith(".html")) return "text/html; charset=utf-8";
  if (file.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (file.endsWith(".css")) return "text/css; charset=utf-8";
  if (file.endsWith(".json")) return "application/json; charset=utf-8";
  if (file.endsWith(".svg")) return "image/svg+xml";
  return "application/octet-stream";
}

before(async () => {
  tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "sintu-browser-e2e-"));
  const videoPath = path.join(tempDir, "timeline-fixture.webm");
  const generated = spawnSync("ffmpeg", [
    "-y", "-hide_banner", "-loglevel", "error",
    "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=15:duration=2",
    "-an", "-c:v", "libvpx-vp9", "-deadline", "realtime",
    "-cpu-used", "8", "-pix_fmt", "yuv420p", "-f", "webm", videoPath,
  ], { encoding: "utf8" });
  assert.equal(generated.status, 0, generated.stderr || "FFmpeg fixture generation failed.");
  webm = fs.readFileSync(videoPath);

  server = http.createServer((request, response) => {
    const pathname = new URL(request.url, "http://127.0.0.1").pathname;
    if (pathname.startsWith("/api/ai-videos/")) {
      const range = request.headers.range;
      videoRangeRequests.push(range || null);
      response.setHeader("Content-Type", "video/webm");
      response.setHeader("Accept-Ranges", "bytes");
      response.setHeader("Cache-Control", "no-store");
      if (range) {
        const match = /^bytes=(\d*)-(\d*)$/.exec(range);
        if (!match || (!match[1] && !match[2])) {
          response.writeHead(416, { "Content-Range": "bytes */" + webm.length });
          response.end();
          return;
        }
        let start = match[1] ? Number(match[1]) : Math.max(0, webm.length - Number(match[2]));
        let end = match[2] && match[1] ? Math.min(Number(match[2]), webm.length - 1) : webm.length - 1;
        if (start >= webm.length || end < start) {
          response.writeHead(416, { "Content-Range": "bytes */" + webm.length });
          response.end();
          return;
        }
        const chunk = webm.subarray(start, end + 1);
        response.writeHead(206, {
          "Content-Range": "bytes " + start + "-" + end + "/" + webm.length,
          "Content-Length": String(chunk.length),
        });
        response.end(chunk);
        return;
      }
      response.writeHead(200, { "Content-Length": String(webm.length) });
      response.end(webm);
      return;
    }
    if (pathname.startsWith("/api/images/")) {
      if (pathname.split("/").pop().startsWith("b")) {
        response.writeHead(404); response.end("missing image"); return;
      }
      response.writeHead(200, { "Content-Type": "image/png", "Content-Length": String(PNG.length) });
      response.end(PNG); return;
    }
    if (pathname.startsWith("/api/")) {
      const payload = Buffer.from(JSON.stringify({
        tasks: [], items: [], projects: [], media: [],
        providers: { local: { model_available: false } },
      }));
      response.writeHead(200, { "Content-Type": "application/json", "Content-Length": String(payload.length) });
      response.end(payload); return;
    }
    const relative = pathname === "/" ? "index.html"
      : pathname.startsWith("/static/") ? pathname.slice("/static/".length) : null;
    if (relative === null) {
      response.writeHead(404); response.end("Not found"); return;
    }
    const target = path.resolve(STATIC_ROOT, relative);
    if (!target.startsWith(STATIC_ROOT + path.sep) && target !== STATIC_ROOT) {
      response.writeHead(403); response.end("Forbidden"); return;
    }
    fs.readFile(target, (error, bytes) => {
      if (error) { response.writeHead(404); response.end("Not found"); return; }
      response.writeHead(200, { "Content-Type": contentType(target), "Content-Length": String(bytes.length), "Cache-Control": "no-store" });
      response.end(bytes);
    });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  baseUrl = "http://127.0.0.1:" + server.address().port + "/";
  browser = await chromium.launch({ headless: true, args: ["--autoplay-policy=no-user-gesture-required"] });
});

after(async () => {
  if (browser) await browser.close();
  if (server) await new Promise(resolve => server.close(resolve));
  if (tempDir) fs.rmSync(tempDir, { recursive: true, force: true });
});

async function openStudio() {
  const context = await browser.newContext({ serviceWorkers: "block" });
  const page = await context.newPage();
  await page.addInitScript(() => {
    const attach = () => {
      const video = document.querySelector("#timelinePreviewStage video");
      if (video && !video.dataset.sintuPlayProbe) {
        video.dataset.sintuPlayProbe = "1";
        window.__sintuMediaEvents = [];
        for (const name of ["loadedmetadata", "seeking", "seeked", "play", "playing", "timeupdate", "error", "stalled", "waiting"]) {
          video.addEventListener(name, () => window.__sintuMediaEvents.push({ name, currentTime: video.currentTime, readyState: video.readyState, networkState: video.networkState, error: video.error?.code || null }));
        }
        video.addEventListener("play", () => { window.__sintuPlayTime = video.currentTime; }, { once: true });
      }
    };
    new MutationObserver(attach).observe(document.documentElement, { childList: true, subtree: true });
  });
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => typeof window.playTimelinePreview === "function");
  return { context, page };
}

async function setTimeline(page, entry, scenes = "Browser acceptance scene", subtitles = "") {
  await page.evaluate(({ entry, scenes, subtitles }) => {
    document.getElementById("renderTimeline").value = entry;
    document.getElementById("renderScenes").value = scenes;
    document.getElementById("renderSubtitles").value = subtitles;
    syncTimelineFields(timelineRows());
  }, { entry, scenes, subtitles });
}

test("real Chromium loads an image and completes its scene timer", async () => {
  const { context, page } = await openStudio();
  try {
    await setTimeline(page, "image:" + "a".repeat(32) + ":2:cut");
    await page.locator("#timelinePreviewPlay").click({ force: true });
    await page.waitForFunction(() => {
      const image = document.querySelector("#timelinePreviewStage img");
      return image && image.complete && image.naturalWidth === 1;
    });
    await page.waitForFunction(
      () => document.getElementById("timelinePreviewNotice").textContent === "Sequence preview complete.",
      null, { timeout: 7000 },
    );
  } finally {
    await context.close();
  }
});

test("real Chromium reports an image load error", async () => {
  const { context, page } = await openStudio();
  try {
    await setTimeline(page, "image:" + "b".repeat(32) + ":2:cut");
    await page.locator("#timelinePreviewPlay").click({ force: true });
    await page.waitForFunction(
      () => document.getElementById("timelinePreviewNotice").textContent.includes("image preview load failed"),
    );
  } finally {
    await context.close();
  }
});

test("real Chromium seeks to trim-start before video playback and stops at trim-end", async () => {
  const { context, page } = await openStudio();
  try {
    await setTimeline(page, "video:" + "c".repeat(32) + ":0.25:0.8:0.25:cut");
    await page.locator("#timelinePreviewPlay").click({ force: true });
    await page.waitForFunction(() => Number.isFinite(window.__sintuPlayTime), null, { timeout: 12000 }).catch(async error => {
      const state = await page.evaluate(() => ({ notice: document.getElementById("timelinePreviewNotice").textContent, events: window.__sintuMediaEvents || [], video: (() => { const v = document.querySelector("#timelinePreviewStage video"); return v ? { currentTime: v.currentTime, duration: v.duration, readyState: v.readyState, networkState: v.networkState, error: v.error?.code || null, seeking: v.seeking } : null; })() }));
      throw new Error(error.message + " Media diagnostics: " + JSON.stringify(state) + " Range requests: " + JSON.stringify(videoRangeRequests));
    });
    const playStart = await page.evaluate(() => window.__sintuPlayTime);
    assert.ok(playStart >= 0.2, "video started before trim-start: " + playStart);
    await page.waitForFunction(
      () => document.getElementById("timelinePreviewNotice").textContent === "Sequence preview complete.",
      null, { timeout: 7000 },
    );
  } finally {
    await context.close();
  }
});

test("real Chromium rejects an invalid video trim range without playing", async () => {
  const { context, page } = await openStudio();
  try {
    await setTimeline(page, "video:" + "d".repeat(32) + ":0.8:0.2:0.25:cut");
    await page.locator("#timelinePreviewPlay").click({ force: true });
    await page.waitForFunction(
      () => document.getElementById("timelinePreviewNotice").textContent.includes("trim range"),
    );
    assert.equal(await page.evaluate(() => window.__sintuPlayTime), undefined);
  } finally {
    await context.close();
  }
});

test("real Chromium stop control cancels an active image preview", async () => {
  const { context, page } = await openStudio();
  try {
    await setTimeline(page, "image:" + "e".repeat(32) + ":12:cut");
    await page.locator("#timelinePreviewPlay").click({ force: true });
    await page.waitForFunction(() => {
      const image = document.querySelector("#timelinePreviewStage img");
      return image && image.complete && image.naturalWidth === 1;
    });
    await page.locator("#timelinePreviewStop").click({ force: true });
    await page.waitForFunction(
      () => document.getElementById("timelinePreviewNotice").textContent === "Preview stopped.",
    );
    await page.waitForTimeout(250);
    assert.notEqual(
      await page.locator("#timelinePreviewNotice").textContent(),
      "Sequence preview complete.",
    );
  } finally {
    await context.close();
  }
});

test("real Chromium keeps subtitles aligned when timeline clips are reordered", async () => {
  const { context, page } = await openStudio();
  try {
    await setTimeline(
      page,
      "image:" + "a".repeat(32) + ":2:cut\nimage:" + "f".repeat(32) + ":2:cut",
      "First scene\nSecond scene",
      "First subtitle\nSecond subtitle",
    );
    await page.locator('#timelineEditor button[data-action="down"]').first().click({ force: true });
    assert.equal(await page.locator("#renderSubtitles").inputValue(), "Second subtitle\nFirst subtitle");
    assert.match(await page.locator("#renderTimeline").inputValue(), /^image:f{32}:2:cut\nimage:a{32}:2:cut$/);
  } finally {
    await context.close();
  }
});
