(() => {
  "use strict";

  const STORAGE_KEY = "sintu.video-editor-draft.v1";
  const MAX_DRAFT_BYTES = 128 * 1024;
  const FIELD_IDS = [
    "renderTitle", "renderScenes", "sceneSeconds", "renderResolution",
    "renderFps", "renderQuality", "renderTimeline", "renderImageIds",
    "renderVideoIds", "renderAudioId", "aiMusicPrompt", "aiMusicDuration",
    "renderMusicId", "musicVolume", "renderTransition", "renderMotion",
    "renderSubtitles", "renderSoundEffects", "renderSfxVolume",
  ];

  function controls() {
    return FIELD_IDS.map(id => document.getElementById(id)).filter(Boolean);
  }

  function readDraft() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw || raw.length > MAX_DRAFT_BYTES) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || parsed.version !== 1 || !parsed.values || typeof parsed.values !== "object") return null;
      return parsed;
    } catch (_) {
      return null;
    }
  }

  function setNotice(message) {
    const notice = document.getElementById("editorDraftNotice");
    if (notice) notice.textContent = message;
  }

  function updateButtons() {
    const hasDraft = Boolean(readDraft());
    const restore = document.getElementById("restoreEditorDraft");
    const clear = document.getElementById("clearEditorDraft");
    if (restore) restore.disabled = !hasDraft;
    if (clear) clear.disabled = !hasDraft;
  }

  function saveDraft() {
    if (draftClearedUntilNextEdit) return;
    const values = {};
    for (const field of controls()) {
      values[field.id] = field.type === "checkbox" ? field.checked : field.value;
    }
    const hasContent = Object.values(values).some(value =>
      typeof value === "boolean" ? value : String(value).trim() !== ""
    );
    if (!hasContent) return;
    const payload = JSON.stringify({ version: 1, savedAt: new Date().toISOString(), values });
    if (payload.length > MAX_DRAFT_BYTES) {
      setNotice("Draft is too large for local recovery; shorten long text fields.");
      return;
    }
    try {
      localStorage.setItem(STORAGE_KEY, payload);
      updateButtons();
      setNotice("Editor draft saved on this device · " + new Date().toLocaleTimeString() +
        ". Uploaded media files are not included.");
    } catch (_) {
      setNotice("Browser storage is unavailable; editor draft could not be saved.");
    }
  }

  function restoreDraft() {
    const draft = readDraft();
    if (!draft) {
      updateButtons();
      setNotice("No valid saved editor draft is available.");
      return;
    }
    for (const field of controls()) {
      if (!Object.prototype.hasOwnProperty.call(draft.values, field.id)) continue;
      const value = draft.values[field.id];
      if (field.type === "checkbox") field.checked = value === true;
      else if (typeof value === "string") field.value = value;
      field.dispatchEvent(new Event("input", { bubbles: true }));
      field.dispatchEvent(new Event("change", { bubbles: true }));
    }
    if (typeof window.timelineRows === "function" &&
        typeof window.syncTimelineFields === "function") {
      try { window.syncTimelineFields(window.timelineRows()); } catch (_) {}
    }
    setNotice("Saved editor draft restored · " +
      (draft.savedAt ? new Date(draft.savedAt).toLocaleString() : "saved previously") +
      ". Re-select any local files that were not part of the draft.");
  }

  function clearDraft() {
    draftClearedUntilNextEdit = true;
    clearTimeout(saveTimer);
    try {
      localStorage.removeItem(STORAGE_KEY);
      updateButtons();
      setNotice("Saved editor draft cleared from this browser.");
    } catch (_) {
      setNotice("Browser storage is unavailable; saved draft could not be cleared.");
    }
  }

  let saveTimer = null;
  let draftClearedUntilNextEdit = false;
  document.addEventListener("input", event => {
    if (FIELD_IDS.includes(event.target?.id)) {
      draftClearedUntilNextEdit = false;
      clearTimeout(saveTimer);
      saveTimer = setTimeout(saveDraft, 300);
    }
  });
  document.addEventListener("change", event => {
    if (FIELD_IDS.includes(event.target?.id)) {
      draftClearedUntilNextEdit = false;
      clearTimeout(saveTimer);
      saveDraft();
    }
  });
  window.addEventListener("pagehide", () => {
    clearTimeout(saveTimer);
    saveDraft();
  });
  document.getElementById("restoreEditorDraft")?.addEventListener("click", restoreDraft);
  document.getElementById("clearEditorDraft")?.addEventListener("click", clearDraft);
  updateButtons();
})();
