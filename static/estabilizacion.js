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

async function loadDirs(path, retry = false) {
  const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}${retry ? "&retry=1" : ""}`);
  const data = await res.json();
  if (data.error) {
    showBrowseError(scanStatus, data, () => loadDirs(path, true));
    return;
  }
  clearBrowseError(scanStatus);
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

const bulkStabParamsPanel = createStabParamsPanel("bulk-stab");

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
      ...bulkStabParamsPanel.getParams(),
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
const clipStabDiscardBtn = document.getElementById("clip-stab-discard-btn");
const clipStabSaveBtn = document.getElementById("clip-stab-save-btn");
const clipStabPropagateBtn = document.getElementById("clip-stab-propagate-btn");

const clipStabPreview = createStabilizePreview({
  video: document.getElementById("clip-stab-proxy-video"),
  canvas: document.getElementById("clip-stab-canvas"),
  seek: clipStabSeek,
  playBtn: clipStabPlayBtn,
  toggle: clipStabPreviewToggle,
});

const clipStabParamsPanel = createStabParamsPanel("clip-stab", {
  onChange: (params) => clipStabPreview.recomputeAndRender(params),
});

let clipStabEditingPath = null;

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

let clipStabAnalyzedThisSession = false;

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
  clipStabParamsPanel.setParams(draft);
  clipStabModal.classList.remove("hidden");

  // Si ya hay un análisis en caché que coincide con estos parámetros (el escaneo ya
  // lo comprobó al construir has_analysis), no hace falta pulsar "Analizar clip": se
  // carga la previsualización directamente.
  if (clip && clip.has_analysis) {
    runClipAnalysis();
  }
}

clipStabClose.addEventListener("click", () => {
  clipStabPreview.stop();
  clipStabModal.classList.add("hidden");
});
clipStabModal.addEventListener("click", (e) => {
  if (e.target === clipStabModal) clipStabClose.click();
});

function runClipAnalysis() {
  if (!lastScan || !clipStabEditingPath) return;
  const params = clipStabParamsPanel.getParams();
  clipStabAnalyzeBtn.disabled = true;
  clipStabAnalyzeStatus.textContent = "Analizando… (puede tardar, sobre todo la primera vez en 4K)";
  clipStabAnalyzeProgress.classList.remove("hidden");
  clipStabAnalyzeProgress.value = 0;

  fetch("/api/montaje/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      root: lastScan.root, path: clipStabEditingPath,
      shakiness: params.shakiness, accuracy: params.accuracy,
      stepsize: params.stepsize, mincontrast: params.mincontrast,
    }),
  }).then((res) => res.json()).then((data) => {
    if (data.error) {
      clipStabAnalyzeStatus.textContent = data.error;
      clipStabAnalyzeBtn.disabled = false;
      return;
    }
    pollClipStabAnalyze(data.job_id);
  });
}

clipStabAnalyzeBtn.addEventListener("click", runClipAnalysis);

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
    clipStabPreview.setupPreview(analysis).then(() => clipStabPreview.recomputeAndRender(clipStabParamsPanel.getParams()));
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
  const params = clipStabParamsPanel.getParams();
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

// ---------- Propagar ajustes a otros clips de la misma carpeta ----------

const propagateModal = document.getElementById("propagate-modal");
const propagateClose = document.getElementById("propagate-close");
const propagateList = document.getElementById("propagate-list");
const propagateSelectAllBtn = document.getElementById("propagate-select-all-btn");
const propagateApplyBtn = document.getElementById("propagate-apply-btn");
const propagateStatus = document.getElementById("propagate-status");

function folderOf(relativePath) {
  const idx = relativePath.lastIndexOf("/");
  return idx === -1 ? "" : relativePath.slice(0, idx);
}

clipStabPropagateBtn.addEventListener("click", () => {
  const current = findClip(clipStabEditingPath);
  if (!current) return;
  const folder = folderOf(current.relative);
  const siblings = (lastScan.avchd_clips || []).filter(
    (c) => c.path !== current.path && folderOf(c.relative) === folder
  );

  propagateStatus.textContent = "";
  propagateList.innerHTML = "";
  if (siblings.length === 0) {
    propagateList.innerHTML = "<li class=\"muted\">No hay más clips en esta misma carpeta.</li>";
  }
  siblings.forEach((clip) => {
    const li = document.createElement("li");
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "propagate-target";
    cb.dataset.path = clip.path;
    label.append(cb, document.createTextNode(clip.relative));
    li.appendChild(label);
    propagateList.appendChild(li);
  });

  propagateModal.classList.remove("hidden");
});

propagateClose.addEventListener("click", () => propagateModal.classList.add("hidden"));
propagateModal.addEventListener("click", (e) => {
  if (e.target === propagateModal) propagateModal.classList.add("hidden");
});

propagateSelectAllBtn.addEventListener("click", () => {
  const boxes = Array.from(propagateList.querySelectorAll(".propagate-target"));
  const allChecked = boxes.length > 0 && boxes.every((cb) => cb.checked);
  boxes.forEach((cb) => (cb.checked = !allChecked));
});

propagateApplyBtn.addEventListener("click", async () => {
  const targets = Array.from(propagateList.querySelectorAll(".propagate-target:checked")).map((cb) => cb.dataset.path);
  if (targets.length === 0) {
    propagateStatus.textContent = "No hay clips marcados.";
    return;
  }
  propagateApplyBtn.disabled = true;
  propagateStatus.textContent = `Propagando a ${targets.length} clip(s)…`;
  const params = clipStabParamsPanel.getParams();

  let done = 0;
  for (const targetPath of targets) {
    const res = await fetch("/api/stabilize-draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root: lastScan.root, path: targetPath, ...params }),
    });
    const data = await res.json();
    if (!data.error) {
      const clip = findClip(targetPath);
      if (clip) clip.stabilize_draft = data.draft;
      refreshRowStatus(targetPath);
      done += 1;
    }
  }

  propagateApplyBtn.disabled = false;
  propagateStatus.textContent = `Ajuste propagado a ${done} de ${targets.length} clip(s).`;
});
