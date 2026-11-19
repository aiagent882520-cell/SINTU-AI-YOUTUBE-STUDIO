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
  let undoStack = [];
  let redoStack = [];
  let restoring = false;

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

  let lastSnapshot = snapshot();

  function updateButtons() {
    const undo = document.getElementById("timelineUndo");
    const redo = document.getElementById("timelineRedo");
    if (undo) undo.disabled = undoStack.length === 0;
    if (redo) redo.disabled = redoStack.length === 0;
  }

  function recordChange() {
    if (restoring) return;
    const next = snapshot();
    if (JSON.stringify(next) === JSON.stringify(lastSnapshot)) return;
    undoStack.push(lastSnapshot);
    if (undoStack.length > MAX_HISTORY) undoStack.shift();
    redoStack = [];
    lastSnapshot = next;
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
      if (typeof window.timelineRows === "function" &&
          typeof window.syncTimelineFields === "function") {
        window.syncTimelineFields(window.timelineRows());
      }
    } finally {
      restoring = false;
    }
    lastSnapshot = snapshot();
    updateButtons();
  }

  function undo() {
    if (!undoStack.length) return;
    redoStack.push(snapshot());
    restoreState(undoStack.pop());
  }

  function redo() {
    if (!redoStack.length) return;
    undoStack.push(snapshot());
    restoreState(redoStack.pop());
  }

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
