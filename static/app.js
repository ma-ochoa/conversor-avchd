const pathInput = document.getElementById("path-input");
const crumb = document.getElementById("crumb");
const dirList = document.getElementById("dir-list");
const goBtn = document.getElementById("go-btn");
const browseBtn = document.getElementById("browse-btn");
const scanBtn = document.getElementById("scan-btn");
const scanStatus = document.getElementById("scan-status");

const resultsSection = document.getElementById("results-section");
const outputDirNote = document.getElementById("output-dir-note");
const avchdBody = document.querySelector("#avchd-table tbody");
const photoBody = document.querySelector("#photo-table tbody");
const otherList = document.getElementById("other-list");
const otherBlock = document.getElementById("other-block");

const convertBtn = document.getElementById("convert-btn");
const progressSection = document.getElementById("progress-section");
const progressBody = document.querySelector("#progress-table tbody");
const jobSummary = document.getElementById("job-summary");

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

function outputName(iso, ext) {
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}${ext}`;
}

function formatStats(stats) {
  if (!stats) return "—";
  const parts = [];
  if (stats.zoom_percent != null) parts.push(`recorte/zoom: ${stats.zoom_percent}%`);
  if (stats.confidence_percent != null) {
    parts.push(`confianza de seguimiento: ${stats.confidence_percent}% (${stats.low_contrast_frames}/${stats.total_frames} fotogramas con poco contraste)`);
  }
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

function baseRowCells(item, ext) {
  const cbTd = document.createElement("td");
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.className = "select-convert";
  cb.checked = !item.already_converted;
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

  const destTd = document.createElement("td");
  destTd.textContent = item.already_converted ? item.output_name : outputName(item.capture_dt, ext);

  const statusTd = document.createElement("td");
  if (item.already_converted) {
    const span = document.createElement("span");
    span.className = "tag done";
    span.textContent = "ya convertido";
    statusTd.appendChild(span);
  }

  return { cbTd, cb, nameTd, dateTd, sizeTd, destTd, statusTd };
}

function renderRow(item, ext) {
  const tr = document.createElement("tr");
  const cells = baseRowCells(item, ext);
  tr.append(cells.cbTd, cells.nameTd, cells.dateTd, cells.sizeTd, cells.destTd, cells.statusTd);
  return tr;
}

function renderAvchdRow(item) {
  const tr = document.createElement("tr");
  const cells = baseRowCells(item, ".mp4");
  tr.append(cells.cbTd, cells.nameTd, cells.dateTd, cells.sizeTd, cells.destTd, cells.statusTd);

  const stabCbTd = document.createElement("td");
  const stabCb = document.createElement("input");
  stabCb.type = "checkbox";
  stabCb.className = "select-stabilize";
  stabCb.checked = !item.already_stabilized;
  stabCb.dataset.path = item.path;
  stabCbTd.appendChild(stabCb);
  tr.appendChild(stabCbTd);

  const statsTd = document.createElement("td");
  statsTd.dataset.statsCell = "1";
  if (item.already_stabilized) {
    const span = document.createElement("span");
    span.className = "tag done";
    span.textContent = "ya estabilizado";
    statsTd.appendChild(span);
    statsTd.appendChild(document.createElement("br"));
    statsTd.appendChild(document.createTextNode(formatStats(item.stabilize_stats)));
  } else {
    statsTd.textContent = "—";
  }
  tr.appendChild(statsTd);

  return tr;
}

scanBtn.addEventListener("click", async () => {
  scanStatus.textContent = "Escaneando…";
  resultsSection.classList.add("hidden");
  progressSection.classList.add("hidden");

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

  document.getElementById("avchd-count").textContent = data.avchd_clips.length;
  document.getElementById("photo-count").textContent = data.photos.length;
  document.getElementById("other-count").textContent = data.other_videos.length;
  outputDirNote.textContent = `Los ficheros convertidos se guardarán en: ${data.output_dir}`;

  avchdBody.innerHTML = "";
  data.avchd_clips.forEach((item) => avchdBody.appendChild(renderAvchdRow(item)));
  document.getElementById("avchd-empty").classList.toggle("hidden", data.avchd_clips.length > 0);

  photoBody.innerHTML = "";
  data.photos.forEach((item) => {
    const ext = item.relative.slice(item.relative.lastIndexOf(".")).toLowerCase();
    photoBody.appendChild(renderRow(item, ext));
  });
  document.getElementById("photo-empty").classList.toggle("hidden", data.photos.length > 0);

  otherList.innerHTML = "";
  otherBlock.classList.toggle("hidden", data.other_videos.length === 0);
  data.other_videos.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = `${item.relative} (${formatBytes(item.size)})`;
    otherList.appendChild(li);
  });

  resultsSection.classList.remove("hidden");
});

function selectedPaths(tbody, selector = 'input[type="checkbox"]:checked') {
  return Array.from(tbody.querySelectorAll(selector)).map((cb) => cb.dataset.path);
}

convertBtn.addEventListener("click", async () => {
  if (!lastScan) return;
  const avchdPaths = selectedPaths(avchdBody, ".select-convert:checked");
  const photoPaths = selectedPaths(photoBody);
  if (avchdPaths.length === 0 && photoPaths.length === 0) {
    scanStatus.textContent = "No hay elementos seleccionados.";
    return;
  }

  convertBtn.disabled = true;
  const transcodeAudio = document.getElementById("transcode-audio").checked;
  const force = document.getElementById("force").checked;

  const res = await fetch("/api/convert", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      root: lastScan.root,
      avchd_paths: avchdPaths,
      photo_paths: photoPaths,
      transcode_audio: transcodeAudio,
      force: force,
    }),
  });
  const data = await res.json();
  if (data.error) {
    scanStatus.textContent = data.error;
    convertBtn.disabled = false;
    return;
  }

  progressSection.classList.remove("hidden");
  pollJob(data.job_id);
});

const rowsByPath = {};

function ensureProgressRows(items) {
  progressBody.innerHTML = "";
  for (const key in rowsByPath) delete rowsByPath[key];
  items.forEach((item) => {
    const tr = document.createElement("tr");
    const nameTd = document.createElement("td");
    nameTd.textContent = item.relative;
    const typeTd = document.createElement("td");
    typeTd.textContent = item.type === "avchd" ? "vídeo" : "foto";
    const statusTd = document.createElement("td");
    statusTd.textContent = item.status;
    const progTd = document.createElement("td");
    const bar = document.createElement("progress");
    bar.max = 1;
    bar.value = item.percent;
    progTd.appendChild(bar);

    tr.append(nameTd, typeTd, statusTd, progTd);
    progressBody.appendChild(tr);
    rowsByPath[item.path] = { statusTd, bar };
  });
}

async function pollJob(jobId) {
  const res = await fetch(`/api/status/${jobId}`);
  const job = await res.json();
  if (job.error) {
    jobSummary.textContent = job.error;
    convertBtn.disabled = false;
    return;
  }

  if (Object.keys(rowsByPath).length === 0) {
    ensureProgressRows(job.items);
  }
  job.items.forEach((item) => {
    const row = rowsByPath[item.path];
    if (!row) return;
    row.statusTd.textContent = item.status + (item.error ? `: ${item.error}` : "");
    row.bar.value = item.percent;
  });

  if (job.state === "finalizado") {
    const done = job.items.filter((i) => i.status === "completado").length;
    const skipped = job.items.filter((i) => i.status.startsWith("omitido")).length;
    const errors = job.items.filter((i) => i.status === "error").length;
    jobSummary.textContent = `Terminado: ${done} convertidos, ${skipped} omitidos, ${errors} con error.`;
    convertBtn.disabled = false;
    return;
  }

  setTimeout(() => pollJob(jobId), 800);
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
    body: JSON.stringify({ root: lastScan.root, avchd_paths: avchdPaths, force: force, fast_hw: fastHw }),
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

function updateAvchdRowStats(path, outputName, stats) {
  const cb = avchdBody.querySelector(`.select-stabilize[data-path="${CSS.escape(path)}"]`);
  if (!cb) return;
  const row = cb.closest("tr");
  const statsCell = row.querySelector("td[data-stats-cell]");
  if (!statsCell) return;
  statsCell.innerHTML = "";
  const span = document.createElement("span");
  span.className = "tag done";
  span.textContent = "ya estabilizado";
  statsCell.appendChild(span);
  statsCell.appendChild(document.createElement("br"));
  statsCell.appendChild(document.createTextNode(formatStats(stats)));
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
      updateAvchdRowStats(item.path, item.output_name, item.stats);
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
