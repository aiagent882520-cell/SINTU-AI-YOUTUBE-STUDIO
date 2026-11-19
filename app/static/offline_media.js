/* Durable browser-side media queue. Server-side SHA-256 is the deduplication authority. */
(() => {
  const input = document.getElementById("offlineMediaFiles");
  if (!input) return;
  const importButton = document.getElementById("offlineMediaImport");
  const syncButton = document.getElementById("offlineMediaSync");
  const status = document.getElementById("offlineMediaStatus");
  const queueNode = document.getElementById("offlineMediaQueue");
  const serverNode = document.getElementById("offlineMediaServerList");
  const DB_NAME = "sintu-offline-media-v1";
  const ALLOWED_EXTENSIONS = new Set([".mp4",".mov",".mkv",".webm",".avi",".mp3",".wav",".m4a",".aac",".ogg",".flac",".jpg",".jpeg",".png",".webp"]);
  const STORE = "queue";
  let dbPromise;
  let syncing = false;

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("IndexedDB unavailable."));
      request.onblocked = () => reject(new Error("Close another SINTU tab to upgrade local media storage."));
    });
    return dbPromise;
  }

  async function transaction(mode, action) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const store = tx.objectStore(STORE);
      let result;
      try { result = action(store); } catch (error) { reject(error); return; }
      tx.oncomplete = () => resolve(result?.result);
      tx.onerror = () => reject(tx.error || new Error("Local media transaction failed."));
      tx.onabort = () => reject(tx.error || new Error("Local media transaction aborted."));
    });
  }

  const allItems = () => transaction("readonly", store => store.getAll());
  const putItem = item => transaction("readwrite", store => store.put(item));
  const removeItem = id => transaction("readwrite", store => store.delete(id));

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  async function renderQueue() {
    const items = await allItems();
    queueNode.replaceChildren();
    if (!items.length) queueNode.append(node("p", "No media queued on this device."));
    for (const item of items.sort((a, b) => b.createdAt - a.createdAt)) {
      const card = node("article", undefined, "local-draft");
      card.append(node("b", item.name));
      card.append(node("small", (item.size / 1048576).toFixed(1) + " MiB · " + item.status + (item.attempts ? " · retries " + item.attempts : "")));
      if (item.error) card.append(node("small", item.error));
      const remove = node("button", "Remove local copy", "secondary");
      remove.type = "button";
      remove.dataset.removeOfflineMedia = item.id;
      card.append(remove);
      queueNode.append(card);
    }
    status.textContent = (navigator.onLine ? "Online" : "Offline") + " · " + items.length + " on-device media item(s).";
  }

  async function renderServerLibrary() {
    serverNode.replaceChildren();
    if (!navigator.onLine) {
      serverNode.append(node("p", "Server library unavailable while offline."));
      return;
    }
    try {
      const response = await fetch("/api/offline-media", { credentials: "same-origin" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Server library unavailable.");
      if (!data.media.length) serverNode.append(node("p", "No server media yet."));
      for (const item of data.media) {
        const card = node("article", undefined, "local-draft");
        card.append(node("b", item.original_name));
        card.append(node("small", (item.size_bytes / 1048576).toFixed(1) + " MiB · SHA-256 " + item.sha256.slice(0, 12) + "…"));
        const link = node("a", "Download verified server copy", "secondary");
        link.href = item.download_url;
        link.rel = "noopener";
        card.append(link);
        serverNode.append(card);
      }
    } catch (error) {
      serverNode.append(node("p", error.message));
    }
  }

  async function importSelectedFiles() {
    const files = Array.from(input.files || []);
    if (!files.length) { status.textContent = "Pehle media file select karein."; return; }
    importButton.disabled = true;
    try {
      if (navigator.storage?.persist) await navigator.storage.persist().catch(() => false);
      for (const file of files) {
        const extension = "." + (file.name.split(".").pop() || "").toLowerCase();
        if (!ALLOWED_EXTENSIONS.has(extension)) throw new Error(file.name + ": unsupported media extension.");
        if (!file.size || file.size > 256 * 1024 * 1024) throw new Error(file.name + ": file must be 1 byte to 256 MiB.");
        const id = crypto.randomUUID();
        await putItem({
          id, name: file.name, type: file.type || "application/octet-stream",
          size: file.size, lastModified: file.lastModified, blob: file,
          status: "QUEUED", attempts: 0, nextAttemptAt: 0,
          createdAt: Date.now(), error: ""
        });
      }
      input.value = "";
      await renderQueue();
      status.textContent = files.length + " file(s) saved in this device's persistent offline queue.";
      if (navigator.onLine) await syncQueue(false);
    } catch (error) {
      status.textContent = "Local save failed: " + error.message + ". Browser storage quota/permission check karein.";
    } finally {
      importButton.disabled = false;
    }
  }

  async function syncQueue(force) {
    if (syncing || !navigator.onLine) {
      if (!navigator.onLine) status.textContent = "Offline. Queue safe hai; internet restore hone par sync retry hoga.";
      return;
    }
    syncing = true;
    syncButton.disabled = true;
    try {
      const items = await allItems();
      for (const item of items) {
        if (item.status === "SYNCED" || (!force && item.nextAttemptAt > Date.now())) continue;
        if (!item.blob) continue;
        item.status = "UPLOADING";
        item.error = "";
        await putItem(item);
        await renderQueue();
        try {
          const response = await fetch("/api/offline-media/import?filename=" + encodeURIComponent(item.name), {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": item.type },
            body: item.blob
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(data.detail || "Upload failed (" + response.status + ").");
          item.status = "SYNCED";
          item.sha256 = data.media.sha256;
          item.duplicate = Boolean(data.duplicate);
          item.serverUrl = data.media.download_url;
          item.error = "";
          item.blob = null;
          item.nextAttemptAt = 0;
        } catch (error) {
          item.attempts += 1;
          item.status = "RETRY";
          item.error = error.message;
          item.nextAttemptAt = Date.now() + Math.min(3600000, 5000 * (2 ** Math.min(item.attempts, 9)));
        }
        await putItem(item);
      }
      await renderQueue();
      await renderServerLibrary();
    } finally {
      syncing = false;
      syncButton.disabled = false;
    }
  }

  importButton.addEventListener("click", importSelectedFiles);
  syncButton.addEventListener("click", () => syncQueue(true));
  queueNode.addEventListener("click", async event => {
    const button = event.target.closest("[data-remove-offline-media]");
    if (!button) return;
    await removeItem(button.dataset.removeOfflineMedia);
    await renderQueue();
  });
  window.addEventListener("online", () => { renderServerLibrary(); syncQueue(true); });
  window.addEventListener("offline", renderQueue);
  renderQueue().then(renderServerLibrary).catch(error => { status.textContent = error.message; });
})();
