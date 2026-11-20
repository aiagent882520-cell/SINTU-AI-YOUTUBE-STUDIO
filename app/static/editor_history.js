(() => {
  "use strict";

  const FIELD_IDS = [
    "renderTitle", "renderScenes", "sceneSeconds", "renderResolution",
    "renderFps", "renderQuality", "renderTimeline", "renderImageIds",
    "renderVideoIds", "renderAudioId", "renderMusicId", "musicVolume",
    "renderTransition", "renderMotion", "renderSubtitles",
    "renderSoundEffects", "renderSfxVolume",
  ];
  const MAX_HISTORY = 50;
  const GROUP_DELAY_MS = 350;
  let undoStack = [];
  let redoStack = [];
  let restoring = false;
  let groupTimer = null;
  let groupBefore = null;

  function fields() {
    return FIELD_IDS.map(id => document.getElementById(id)).filter(Boolean);
  }

  function snapshot() {
    const values = {};
    for (const field of fields()) {
      values[field.id] = field.type === "checkbox" ? field.checked : field.value;
    }
    return values;
  }

  function updateButtons() {
    const undo = document.getElementById("timelineUndo");
    const redo = document.getElementById("timelineRedo");
    if (undo) undo.disabled = undoStack.length === 0 && !groupBefore;
    if (redo) redo.disabled = redoStack.length === 0;
  }

  function flushGroup() {
    if (!groupBefore) return;
    clearTimeout(groupTimer);
    const before = groupBefore;
    groupBefore = null;
    if (JSON.stringify(before) !== JSON.stringify(snapshot())) {
      undoStack.push(before);
      if (undoStack.length > MAX_HISTORY) undoStack.shift();
      redoStack = [];
    }
    updateButtons();
  }

  function recordChange() {
    if (restoring) return;
    if (!groupBefore) groupBefore = snapshotLast;
    clearTimeout(groupTimer);
    groupTimer = setTimeout(() => {
      flushGroup();
      snapshotLast = snapshot();
    }, GROUP_DELAY_MS);
    updateButtons();
  }

  function restoreState(values) {
    restoring = true;
    try {
      for (const field of fields()) {
        if (!Object.prototype.hasOwnProperty.call(values, field.id)) continue;
        const value = values[field.id];
        if (field.type === "checkbox") field.checked = value === true;
        else if (typeof value === "string") field.value = value;
      }
      for (const field of fields()) {
        field.dispatchEvent(new Event("input", { bubbles: true }));
        field.dispatchEvent(new Event("change", { bubbles: true }));
      }
      if (typeof window.timelineRows === "function" &&
          typeof window.syncTimelineFields === "function") {
        window.syncTimelineFields(window.timelineRows());
      }
      if (typeof window.timelineRows === "function" &&
          typeof window.renderTimelineEditor === "function") {
        window.renderTimelineEditor(window.timelineRows());
      }
    } finally {
      restoring = false;
    }
    snapshotLast = snapshot();
    updateButtons();
  }

  function undo() {
    flushGroup();
    if (!undoStack.length) return;
    redoStack.push(snapshot());
    restoreState(undoStack.pop());
  }

  function redo() {
    flushGroup();
    if (!redoStack.length) return;
    undoStack.push(snapshot());
    restoreState(redoStack.pop());
  }

  let snapshotLast = snapshot();
  document.addEventListener("input", event => {
    if (FIELD_IDS.includes(event.target?.id)) recordChange();
  });
  document.addEventListener("change", event => {
    if (FIELD_IDS.includes(event.target?.id)) recordChange();
  });
  document.getElementById("timelineUndo")?.addEventListener("click", undo);
  document.getElementById("timelineRedo")?.addEventListener("click", redo);
  updateButtons();
})();