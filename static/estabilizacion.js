const pathInput = document.getElementById("path-input");
const crumb = document.getElementById("crumb");
const dirList = document.getElementById("dir-list");
const goBtn = document.getElementById("go-btn");
const browseBtn = document.getElementById("browse-btn");
const scanBtn = document.getElementById("scan-btn");
const scanStatus = document.getElementById("scan-status");

const resultsSection = document.getElementById("results-section");
const avchdBody = document.querySelector("#avchd-table tbody");

const stabilizeBtn = document.getElementById("stabilize-btn");
const stabilizeProgressSection = document.getElementById("stabilize-progress-section");
const stabilizeProgressBody = document.querySelector("#stabilize-progress-table tbody");
const stabilizeJobSummary = document.getElementById("stabilize-job-summary");

let lastScan = null;

function formatBytes(bytes) {
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return (mb / 1024).toFixed(2) + " GB";
  return mb.toFixed(1) + " MB";
}

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleString("es-ES");
}

function formatStats(stats) {
  if (!stats) return "—";
  const parts = [];
  if (stats.zoom_percent != null) parts.push(`recorte/zoom: ${stats.zoom_percent}%`);
  if (stats.confidence_percent != null) {
    parts.push(`confianza de seguimiento: ${stats.confidence_percent}% (${stats.low_contrast_frames}/${stats.total_frames} fotogramas con poco contraste)`);
  }
  if (stats.mode) parts.push(`modo ${stats.mode}`);
  if (stats.reused_analysis) parts.push("análisis reutilizado (rápido)");
  if (stats.encoder) parts.push(stats.encoder);
  return parts.length ? parts.join(" · ") : "—";
}

async function loadDirs(path) {
  const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
  const data = await res.json();
  if (data.error) {
    scanStatus.textContent = data.error;
    return;
  }
  pathInput.value = data.path;
  crumb.textContent = data.path;
  dirList.innerHTML = "";
  rememberRoot(data.path);

  if (data.parent) {
    const up = document.createElement("li");
    up.textContent = "⬆︎ ..";
    up.addEventListener("click", () => loadDirs(data.parent));
    dirList.appendChild(up);
  }
  for (const dir of data.dirs) {
    const li = document.createElement("li");
    li.textContent = "📁 " + dir.name;
    li.addEventListener("click", () => loadDirs(dir.path));
    dirList.appendChild(li);
  }
}

goBtn.addEventListener("click", () => loadDirs(pathInput.value));
pathInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadDirs(pathInput.value);
});

browseBtn.addEventListener("click", async () => {
  scanStatus.textContent = "";
  const res = await fetch("/api/pick-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: pathInput.value }),
  });
  const data = await res.json();
  if (data.error) {
    scanStatus.textContent = data.error;
    return;
  }
  if (data.canceled || !data.path) return;
  loadDirs(data.path);
});

loadDirs(pathInput.value);

function renderRow(item) {
  const tr = document.createElement("tr");

  const cbTd = document.createElement("td");
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.className = "select-stabilize";
  cb.checked = !item.already_stabilized;
  cb.dataset.path = item.path;
  cbTd.appendChild(cb);

  const nameTd = document.createElement("td");
  nameTd.textContent = item.relative;
  if (item.format) {
    const fmt = document.createElement("span");
    fmt.className = "tag";
    fmt.style.marginLeft = "0.4rem";
    fmt.textContent = item.format;
    nameTd.appendChild(fmt);
  }

  const dateTd = document.createElement("td");
  dateTd.textContent = formatDate(item.capture_dt) + (item.date_source === "archivo" ? " (fecha de archivo)" : "");

  const sizeTd = document.createElement("td");
  sizeTd.textContent = formatBytes(item.size);

  const statusTd = document.createElement("td");
  statusTd.dataset.statsCell = "1";
  renderStatusCell(statusTd, item);

  const adjustTd = document.createElement("td");
  const adjustBtn = document.createElement("button");
  adjustBtn.textContent = "🔍 Analizar y ajustar";
  adjustBtn.addEventListener("click", () => openClipStabModal(item.path));
  adjustTd.appendChild(adjustBtn);

  tr.append(cbTd, nameTd, dateTd, sizeTd, statusTd, adjustTd);
  return tr;
}

function renderStatusCell(statusTd, item) {
  statusTd.innerHTML = "";
  if (item.already_stabilized) {
    const span = document.createElement("span");
    span.className = "tag done";
    span.textContent = "ya estabilizado";
    statusTd.appendChild(span);
    statusTd.appendChild(document.createElement("br"));
    statusTd.appendChild(document.createTextNode(formatStats(item.stabilize_stats)));
    return;
  }
  if (item.stabilize_draft) {
    const span = document.createElement("span");
    span.className = "tag adjusted";
    span.textContent = "🩹 ajustado";
    statusTd.appendChild(span);
    if (item.has_analysis) {
      statusTd.appendChild(document.createTextNode(" (analizado con este ajuste)"));
    }
    return;
  }
  if (item.has_analysis) {
    const span = document.createElement("span");
    span.className = "tag analyzed";
    span.textContent = "🔍 analizado";
    statusTd.appendChild(span);
    return;
  }
  statusTd.textContent = "—";
}

scanBtn.addEventListener("click", async () => {
  scanStatus.textContent = "Escaneando…";
  resultsSection.classList.add("hidden");
  stabilizeProgressSection.classList.add("hidden");
  rememberRoot(pathInput.value);

  const res = await fetch("/api/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: pathInput.value }),
  });
  const data = await res.json();
  if (data.error) {
    scanStatus.textContent = data.error;
    return;
  }
  scanStatus.textContent = "";
  lastScan = data;
  rememberRoot(data.root);

  avchdBody.innerHTML = "";
  data.avchd_clips.forEach((item) => avchdBody.appendChild(renderRow(item)));
  document.getElementById("avchd-empty").classList.toggle("hidden", data.avchd_clips.length > 0);

  resultsSection.classList.remove("hidden");
});

function selectedPaths(tbody, selector) {
  return Array.from(tbody.querySelectorAll(selector)).map((cb) => cb.dataset.path);
}

const stabCustomPanel = document.getElementById("stab-custom-panel");
const zoomModeSelect = document.getElementById("zoom-mode");
const zoomPercentRow = document.getElementById("zoom-percent-row");

document.querySelectorAll('input[name="stab-mode"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    stabCustomPanel.classList.toggle("hidden", document.getElementById("stab-mode-auto").checked);
  });
});

["shakiness", "smoothing", "zoom-percent"].forEach((id) => {
  const input = document.getElementById(id);
  const label = document.getElementById(`${id}-value`);
  input.addEventListener("input", () => (label.textContent = input.value));
});

zoomModeSelect.addEventListener("change", () => {
  zoomPercentRow.classList.toggle("hidden", zoomModeSelect.value !== "manual");
});

function stabilizeParams() {
  if (document.getElementById("stab-mode-auto").checked) {
    return { shakiness: 5, accuracy: 15, smoothing: 10, zoom_mode: "auto_static", zoom_percent: 0 };
  }
  return {
    shakiness: parseInt(document.getElementById("shakiness").value, 10),
    accuracy: 15,
    smoothing: parseInt(document.getElementById("smoothing").value, 10),
    zoom_mode: zoomModeSelect.value,
    zoom_percent: parseFloat(document.getElementById("zoom-percent").value),
  };
}

stabilizeBtn.addEventListener("click", async () => {
  if (!lastScan) return;
  const avchdPaths = selectedPaths(avchdBody, ".select-stabilize:checked");
  if (avchdPaths.length === 0) {
    scanStatus.textContent = "No hay clips marcados para estabilizar.";
    return;
  }

  stabilizeBtn.disabled = true;
  const force = document.getElementById("force-stabilize").checked;
  const fastHw = document.getElementById("fast-hw").checked;

  const res = await fetch("/api/stabilize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      root: lastScan.root, avchd_paths: avchdPaths, force: force, fast_hw: fastHw,
      ...stabilizeParams(),
    }),
  });
  const data = await res.json();
  if (data.error) {
    stabilizeJobSummary.textContent = data.error;
    stabilizeBtn.disabled = false;
    return;
  }

  stabilizeProgressSection.classList.remove("hidden");
  pollStabilizeJob(data.job_id);
});

const stabilizeRowsByPath = {};

function ensureStabilizeProgressRows(items) {
  stabilizeProgressBody.innerHTML = "";
  for (const key in stabilizeRowsByPath) delete stabilizeRowsByPath[key];
  items.forEach((item) => {
    const tr = document.createElement("tr");
    const nameTd = document.createElement("td");
    nameTd.textContent = item.relative;
    const statusTd = document.createElement("td");
    statusTd.textContent = item.status;
    const progTd = document.createElement("td");
    const bar = document.createElement("progress");
    bar.max = 1;
    bar.value = item.percent;
    progTd.appendChild(bar);
    const statsTd = document.createElement("td");
    statsTd.textContent = "—";

    tr.append(nameTd, statusTd, progTd, statsTd);
    stabilizeProgressBody.appendChild(tr);
    stabilizeRowsByPath[item.path] = { statusTd, bar, statsTd };
  });
}

function updateAvchdRowStats(path, stats) {
  const cb = avchdBody.querySelector(`.select-stabilize[data-path="${CSS.escape(path)}"]`);
  if (!cb) return;
  const row = cb.closest("tr");
  const statusTd = row.querySelector("td[data-stats-cell]");
  if (!statusTd) return;
  statusTd.innerHTML = "";
  const span = document.createElement("span");
  span.className = "tag done";
  span.textContent = "ya estabilizado";
  statusTd.appendChild(span);
  statusTd.appendChild(document.createElement("br"));
  statusTd.appendChild(document.createTextNode(formatStats(stats)));
}

async function pollStabilizeJob(jobId) {
  const res = await fetch(`/api/stabilize-status/${jobId}`);
  const job = await res.json();
  if (job.error) {
    stabilizeJobSummary.textContent = job.error;
    stabilizeBtn.disabled = false;
    return;
  }

  if (Object.keys(stabilizeRowsByPath).length === 0) {
    ensureStabilizeProgressRows(job.items);
  }
  job.items.forEach((item) => {
    const row = stabilizeRowsByPath[item.path];
    if (!row) return;
    row.statusTd.textContent = item.status + (item.error ? `: ${item.error}` : "");
    row.bar.value = item.percent;
    if (item.stats) {
      row.statsTd.textContent = formatStats(item.stats);
      updateAvchdRowStats(item.path, item.stats);
    }
  });

  if (job.state === "finalizado") {
    const done = job.items.filter((i) => i.status === "completado").length;
    const skipped = job.items.filter((i) => i.status.startsWith("omitido")).length;
    const errors = job.items.filter((i) => i.status === "error").length;
    stabilizeJobSummary.textContent = `Terminado: ${done} estabilizados, ${skipped} omitidos, ${errors} con error.`;
    stabilizeBtn.disabled = false;
    return;
  }

  setTimeout(() => pollStabilizeJob(jobId), 800);
}

// ---------- Modal de análisis y ajuste por clip (marca, previsualiza, guarda/descarta) ----------

const clipStabModal = document.getElementById("clip-stab-modal");
const clipStabClose = document.getElementById("clip-stab-close");
const clipStabClipName = document.getElementById("clip-stab-clip-name");
const clipStabAnalyzeBtn = document.getElementById("clip-stab-analyze-btn");
const clipStabAnalyzeStatus = document.getElementById("clip-stab-analyze-status");
const clipStabAnalyzeProgress = document.getElementById("clip-stab-analyze-progress");
const clipStabPreviewWrap = document.getElementById("clip-stab-preview-wrap");
const clipStabPlayBtn = document.getElementById("clip-stab-play-btn");
const clipStabSeek = document.getElementById("clip-stab-seek");
const clipStabPreviewToggle = document.getElementById("clip-stab-preview-toggle");
const clipStabCustomPanel = document.getElementById("clip-stab-custom-panel");
const clipStabZoomModeSelect = document.getElementById("clip-stab-zoom-mode");
const clipStabZoomPercentRow = document.getElementById("clip-stab-zoom-percent-row");
const clipStabDiscardBtn = document.getElementById("clip-stab-discard-btn");
const clipStabSaveBtn = document.getElementById("clip-stab-save-btn");

const clipStabPreview = createStabilizePreview({
  video: document.getElementById("clip-stab-proxy-video"),
  canvas: document.getElementById("clip-stab-canvas"),
  seek: clipStabSeek,
  playBtn: clipStabPlayBtn,
  toggle: clipStabPreviewToggle,
});

let clipStabEditingPath = null;
let clipStabAnalyzedThisSession = false;

document.querySelectorAll('input[name="clip-stab-mode"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    clipStabCustomPanel.classList.toggle("hidden", document.getElementById("clip-stab-mode-auto").checked);
    clipStabPreview.recomputeAndRender(clipStabParams());
  });
});
["clip-stab-shakiness", "clip-stab-smoothing", "clip-stab-zoom-percent"].forEach((id) => {
  const input = document.getElementById(id);
  const label = document.getElementById(`${id}-value`);
  input.addEventListener("input", () => {
    label.textContent = input.value;
    if (id !== "clip-stab-shakiness") clipStabPreview.recomputeAndRender(clipStabParams());
  });
});
clipStabZoomModeSelect.addEventListener("change", () => {
  clipStabZoomPercentRow.classList.toggle("hidden", clipStabZoomModeSelect.value !== "manual");
  clipStabPreview.recomputeAndRender(clipStabParams());
});

function clipStabParams() {
  if (document.getElementById("clip-stab-mode-auto").checked) {
    return { shakiness: 5, accuracy: 15, smoothing: 10, zoom_mode: "auto_static", zoom_percent: 0 };
  }
  return {
    shakiness: parseInt(document.getElementById("clip-stab-shakiness").value, 10),
    accuracy: 15,
    smoothing: parseInt(document.getElementById("clip-stab-smoothing").value, 10),
    zoom_mode: clipStabZoomModeSelect.value,
    zoom_percent: parseFloat(document.getElementById("clip-stab-zoom-percent").value),
  };
}

function findClip(path) {
  return (lastScan && lastScan.avchd_clips || []).find((c) => c.path === path);
}

function refreshRowStatus(path) {
  const clip = findClip(path);
  const cb = avchdBody.querySelector(`.select-stabilize[data-path="${CSS.escape(path)}"]`);
  const row = cb && cb.closest("tr");
  const statusTd = row && row.querySelector("td[data-stats-cell]");
  if (clip && statusTd) renderStatusCell(statusTd, clip);
}

function openClipStabModal(path) {
  clipStabEditingPath = path;
  clipStabAnalyzedThisSession = false;
  const clip = findClip(path);
  const draft = clip && clip.stabilize_draft;

  clipStabPreview.stop();
  clipStabPreviewWrap.classList.add("hidden");
  clipStabAnalyzeStatus.textContent = "";
  clipStabAnalyzeProgress.classList.add("hidden");
  clipStabClipName.textContent = clip ? clip.relative : path;

  const isCustom = draft && (draft.zoom_mode !== "auto_static" || draft.smoothing !== 10 || draft.shakiness !== 5);
  document.getElementById("clip-stab-mode-auto").checked = !isCustom;
  document.getElementById("clip-stab-mode-custom").checked = !!isCustom;
  clipStabCustomPanel.classList.toggle("hidden", !isCustom);
  const shakiness = draft ? draft.shakiness : 5;
  const smoothing = draft ? draft.smoothing : 10;
  const zoomMode = draft ? draft.zoom_mode : "auto_static";
  const zoomPercent = draft ? draft.zoom_percent : 10;
  document.getElementById("clip-stab-shakiness").value = shakiness;
  document.getElementById("clip-stab-shakiness-value").textContent = shakiness;
  document.getElementById("clip-stab-smoothing").value = smoothing;
  document.getElementById("clip-stab-smoothing-value").textContent = smoothing;
  clipStabZoomModeSelect.value = zoomMode;
  document.getElementById("clip-stab-zoom-percent").value = zoomPercent;
  document.getElementById("clip-stab-zoom-percent-value").textContent = zoomPercent;
  clipStabZoomPercentRow.classList.toggle("hidden", zoomMode !== "manual");

  clipStabModal.classList.remove("hidden");
}

clipStabClose.addEventListener("click", () => {
  clipStabPreview.stop();
  clipStabModal.classList.add("hidden");
});
clipStabModal.addEventListener("click", (e) => {
  if (e.target === clipStabModal) clipStabClose.click();
});

clipStabAnalyzeBtn.addEventListener("click", async () => {
  if (!lastScan || !clipStabEditingPath) return;
  const params = clipStabParams();
  clipStabAnalyzeBtn.disabled = true;
  clipStabAnalyzeStatus.textContent = "Analizando… (puede tardar, sobre todo la primera vez en 4K)";
  clipStabAnalyzeProgress.classList.remove("hidden");
  clipStabAnalyzeProgress.value = 0;

  const res = await fetch("/api/montaje/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      root: lastScan.root, path: clipStabEditingPath,
      shakiness: params.shakiness, accuracy: params.accuracy,
    }),
  });
  const data = await res.json();
  if (data.error) {
    clipStabAnalyzeStatus.textContent = data.error;
    clipStabAnalyzeBtn.disabled = false;
    return;
  }
  pollClipStabAnalyze(data.job_id);
});

async function pollClipStabAnalyze(jobId) {
  const res = await fetch(`/api/montaje/analyze-status/${jobId}`);
  const job = await res.json();
  if (job.error) {
    clipStabAnalyzeStatus.textContent = job.error;
    clipStabAnalyzeBtn.disabled = false;
    return;
  }
  clipStabAnalyzeProgress.value = job.percent;
  if (job.status === "completado") {
    const analysis = job.data;
    const conf = analysis.stats && analysis.stats.confidence_percent;
    clipStabAnalyzeStatus.textContent =
      `Listo (${analysis.path.length} fotogramas${conf != null ? " · confianza " + conf + "%" : ""})`;
    clipStabAnalyzeBtn.disabled = false;
    clipStabAnalyzedThisSession = true;
    clipStabPreviewWrap.classList.remove("hidden");
    clipStabPreview.setupPreview(analysis).then(() => clipStabPreview.recomputeAndRender(clipStabParams()));
    return;
  }
  if (job.status === "error") {
    clipStabAnalyzeStatus.textContent = job.error;
    clipStabAnalyzeBtn.disabled = false;
    return;
  }
  setTimeout(() => pollClipStabAnalyze(jobId), 700);
}

clipStabSaveBtn.addEventListener("click", async () => {
  if (!lastScan || !clipStabEditingPath) return;
  const params = clipStabParams();
  const res = await fetch("/api/stabilize-draft", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ root: lastScan.root, path: clipStabEditingPath, ...params }),
  });
  const data = await res.json();
  if (data.error) {
    clipStabAnalyzeStatus.textContent = data.error;
    return;
  }
  const clip = findClip(clipStabEditingPath);
  if (clip) {
    clip.stabilize_draft = data.draft;
    if (clipStabAnalyzedThisSession) clip.has_analysis = true;
  }
  refreshRowStatus(clipStabEditingPath);
  clipStabPreview.stop();
  clipStabModal.classList.add("hidden");
});

clipStabDiscardBtn.addEventListener("click", async () => {
  if (!lastScan || !clipStabEditingPath) return;
  await fetch("/api/stabilize-draft", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ root: lastScan.root, path: clipStabEditingPath }),
  });
  const clip = findClip(clipStabEditingPath);
  if (clip) clip.stabilize_draft = null;
  refreshRowStatus(clipStabEditingPath);
  clipStabPreview.stop();
  clipStabModal.classList.add("hidden");
});
