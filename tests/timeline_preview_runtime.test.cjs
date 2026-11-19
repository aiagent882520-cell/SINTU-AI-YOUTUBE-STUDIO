"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "app", "static", "app.js"), "utf8");
const start = source.indexOf("let activeTimelinePreview = null;");
const end = source.indexOf('\n$("timelinePreviewPlay").addEventListener', start);
assert.notEqual(start, -1, "timeline preview implementation must exist");
assert.notEqual(end, -1, "timeline preview implementation boundary must exist");
const implementation = source.slice(start, end);

class FakeMedia {
  constructor(properties = {}) {
    Object.assign(this, {
      complete: false,
      naturalWidth: 0,
      readyState: 0,
      duration: 10,
      currentTime: 0,
      volume: 1,
      paused: true,
      playCalls: 0,
      listeners: new Map(),
    }, properties);
  }

  addEventListener(name, callback, options = {}) {
    const entries = this.listeners.get(name) || [];
    entries.push({ callback, once: Boolean(options.once) });
    this.listeners.set(name, entries);
  }

  removeEventListener(name, callback) {
    const entries = this.listeners.get(name) || [];
    this.listeners.set(name, entries.filter(entry => entry.callback !== callback));
  }

  dispatch(name) {
    const entries = [...(this.listeners.get(name) || [])];
    for (const entry of entries) {
      entry.callback();
      if (entry.once) this.removeEventListener(name, entry.callback);
    }
  }

  listenerCount() {
    return [...this.listeners.values()].reduce((total, entries) => total + entries.length, 0);
  }

  play() {
    this.playCalls += 1;
    this.paused = false;
    return Promise.resolve();
  }

  pause() {
    this.paused = true;
  }
}

function createHarness(rows, media) {
  const stage = { innerHTML: "", querySelector: () => media };
  const notice = { textContent: "" };
  const stopButton = { onclick: null };
  const elements = {
    timelinePreviewStage: stage,
    timelinePreviewNotice: notice,
    timelinePreviewStop: stopButton,
  };
  const sandbox = {
    $: id => elements[id],
    timelineRows: () => rows,
    setTimeout,
    clearTimeout,
    Number,
    Math,
    Promise,
    Error,
  };
  vm.createContext(sandbox);
  vm.runInContext(implementation, sandbox, { filename: "app/static/app.js" });
  return {
    run: () => sandbox.playTimelinePreview(),
    stop: () => sandbox.stopActiveTimelinePreview(),
    notice,
    stage,
    media,
  };
}

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

test("image preview duration starts only after the image load event", async () => {
  const image = new FakeMedia();
  const app = createHarness([{ kind: "image", id: "a".repeat(32), duration: 0.08 }], image);
  const run = app.run();

  await wait(15);
  assert.match(app.notice.textContent, /Preview scene 1/);
  assert.equal(app.notice.textContent, "Preview scene 1 / 1");
  image.naturalWidth = 320;
  image.dispatch("load");
  await wait(15);
  assert.equal(app.notice.textContent, "Preview scene 1 / 1");
  await run;

  assert.equal(app.notice.textContent, "Sequence preview complete.");
  assert.equal(image.listenerCount(), 0);
});

test("image preview reports load errors and removes listeners", async () => {
  const image = new FakeMedia();
  const app = createHarness([{ kind: "image", id: "b".repeat(32), duration: 4 }], image);
  const run = app.run();
  image.dispatch("error");
  await run;

  assert.match(app.notice.textContent, /image preview load failed/i);
  assert.equal(image.listenerCount(), 0);
});

test("video preview waits for trim-start seeked before calling play", async () => {
  const video = new FakeMedia({ readyState: 1, duration: 12 });
  const app = createHarness([{
    kind: "video", id: "c".repeat(32), trimStart: 2, trimEnd: 5, audioVolume: 0.5,
  }], video);
  const run = app.run();

  assert.equal(video.playCalls, 0);
  assert.ok((video.listeners.get("seeked") || []).length > 0);
  video.currentTime = 2;
  video.dispatch("seeked");
  await wait(0);
  assert.equal(video.playCalls, 1);
  video.currentTime = 5;
  video.dispatch("timeupdate");
  await run;

  assert.equal(app.notice.textContent, "Sequence preview complete.");
  assert.equal(video.paused, true);
  assert.equal(video.listenerCount(), 0);
});

test("video preview rejects trim ranges outside source duration", async () => {
  const video = new FakeMedia({ readyState: 1, duration: 10 });
  const app = createHarness([{ kind: "video", id: "d".repeat(32), trimStart: 11 }], video);
  await app.run();

  assert.match(app.notice.textContent, /trim range/i);
  assert.equal(video.playCalls, 0);
  assert.equal(video.listenerCount(), 0);
});

test("stopping a pending video preview detaches listeners and pauses media", async () => {
  const video = new FakeMedia({ readyState: 0, duration: 10 });
  const app = createHarness([{ kind: "video", id: "e".repeat(32), trimStart: 0 }], video);
  const run = app.run();

  assert.ok(video.listenerCount() > 0);
  app.stop();
  await run;

  assert.equal(app.notice.textContent, "Preview stopped.");
  assert.equal(video.listenerCount(), 0);
  assert.equal(video.paused, true);
});
