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
  if (item.already_stabilized) {
    const span = document.createElement("span");
    span.className = "tag done";
    span.textContent = "ya estabilizado";
    statusTd.appendChild(span);
    statusTd.appendChild(document.createElement("br"));
    statusTd.appendChild(document.createTextNode(formatStats(item.stabilize_stats)));
  } else {
    statusTd.textContent = "—";
  }

  tr.append(cbTd, nameTd, dateTd, sizeTd, statusTd);
  return tr;
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
