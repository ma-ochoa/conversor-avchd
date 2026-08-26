const pathInput = document.getElementById("path-input");
const crumb = document.getElementById("crumb");
const dirList = document.getElementById("dir-list");
const goBtn = document.getElementById("go-btn");
const browseBtn = document.getElementById("browse-btn");
const scanBtn = document.getElementById("scan-btn");
const scanStatus = document.getElementById("scan-status");

const resultsSection = document.getElementById("results-section");
const otherBody = document.querySelector("#other-table tbody");
const clipsBody = document.querySelector("#clips-table tbody");

const recompressBtn = document.getElementById("recompress-btn");
const progressSection = document.getElementById("progress-section");
const progressBody = document.querySelector("#progress-table tbody");
const jobSummary = document.getElementById("job-summary");

let root = "";

function formatBytes(bytes) {
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return (mb / 1024).toFixed(2) + " GB";
  return mb.toFixed(1) + " MB";
}

function formatDuration(seconds) {
  if (!seconds) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
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

function renderOtherRow(item) {
  const tr = document.createElement("tr");
  const cbTd = document.createElement("td");
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.className = "select-recompress";
  cb.checked = true;
  cb.dataset.path = item.path;
  cbTd.appendChild(cb);

  const nameTd = document.createElement("td");
  nameTd.textContent = item.relative;
  const fmtTd = document.createElement("td");
  fmtTd.textContent = item.relative.slice(item.relative.lastIndexOf(".") + 1).toLowerCase();
  const sizeTd = document.createElement("td");
  sizeTd.textContent = formatBytes(item.size);

  tr.append(cbTd, nameTd, fmtTd, sizeTd);
  return tr;
}

function renderClipRow(item) {
  const tr = document.createElement("tr");
  const cbTd = document.createElement("td");
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.className = "select-recompress";
  cb.checked = false;
  cb.dataset.path = item.path;
  cbTd.appendChild(cb);

  const nameTd = document.createElement("td");
  nameTd.textContent = item.name;
  const tag = document.createElement("span");
  tag.className = "tag";
  tag.style.marginLeft = "0.4rem";
  tag.textContent = item.source;
  nameTd.appendChild(tag);

  const sizeTd = document.createElement("td");
  sizeTd.textContent = formatBytes(item.size);
  const durTd = document.createElement("td");
  durTd.textContent = formatDuration(item.duration);

  tr.append(cbTd, nameTd, sizeTd, durTd);
  return tr;
}

scanBtn.addEventListener("click", async () => {
  scanStatus.textContent = "Escaneando…";
  resultsSection.classList.add("hidden");
  progressSection.classList.add("hidden");
  rememberRoot(pathInput.value);
  root = pathInput.value;

  const [scanRes, clipsRes] = await Promise.all([
    fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: pathInput.value }),
    }),
    fetch(`/api/montaje/clips?root=${encodeURIComponent(pathInput.value)}`),
  ]);
  const scanData = await scanRes.json();
  if (scanData.error) {
    scanStatus.textContent = scanData.error;
    return;
  }
  const clipsData = await clipsRes.json();
  scanStatus.textContent = "";
  root = scanData.root;
  rememberRoot(root);

  document.getElementById("other-count").textContent = scanData.other_videos.length;
  otherBody.innerHTML = "";
  scanData.other_videos.forEach((item) => otherBody.appendChild(renderOtherRow(item)));
  document.getElementById("other-empty").classList.toggle("hidden", scanData.other_videos.length > 0);

  const clips = clipsData.clips || [];
  document.getElementById("clips-count").textContent = clips.length;
  clipsBody.innerHTML = "";
  clips.forEach((item) => clipsBody.appendChild(renderClipRow(item)));
  document.getElementById("clips-empty").classList.toggle("hidden", clips.length > 0);

  resultsSection.classList.remove("hidden");
});

recompressBtn.addEventListener("click", async () => {
  if (!root) return;
  const paths = Array.from(document.querySelectorAll(".select-recompress:checked")).map((cb) => cb.dataset.path);
  if (paths.length === 0) {
    scanStatus.textContent = "No hay nada seleccionado.";
    return;
  }

  recompressBtn.disabled = true;
  const quality = document.getElementById("quality-select").value;
  const maxWidth = document.getElementById("resolution-select").value;
  const force = document.getElementById("force").checked;

  const res = await fetch("/api/recompress", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ root, paths, quality, max_width: maxWidth, force }),
  });
  const data = await res.json();
  if (data.error) {
    jobSummary.textContent = data.error;
    recompressBtn.disabled = false;
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
    const statusTd = document.createElement("td");
    statusTd.textContent = item.status;
    const progTd = document.createElement("td");
    const bar = document.createElement("progress");
    bar.max = 1;
    bar.value = item.percent;
    progTd.appendChild(bar);
    const resultTd = document.createElement("td");
    resultTd.textContent = "—";

    tr.append(nameTd, statusTd, progTd, resultTd);
    progressBody.appendChild(tr);
    rowsByPath[item.path] = { statusTd, bar, resultTd };
  });
}

function formatResult(stats) {
  if (!stats || stats.reduction_percent == null) return "—";
  return `${formatBytes(stats.original_size)} → ${formatBytes(stats.new_size)} (-${stats.reduction_percent}%)`;
}

async function pollJob(jobId) {
  const res = await fetch(`/api/recompress-status/${jobId}`);
  const job = await res.json();
  if (job.error) {
    jobSummary.textContent = job.error;
    recompressBtn.disabled = false;
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
    if (item.stats) row.resultTd.textContent = formatResult(item.stats);
  });

  if (job.state === "finalizado") {
    const done = job.items.filter((i) => i.status === "completado").length;
    const skipped = job.items.filter((i) => i.status.startsWith("omitido")).length;
    const errors = job.items.filter((i) => i.status === "error").length;
    jobSummary.textContent = `Terminado: ${done} recomprimidos, ${skipped} omitidos, ${errors} con error.`;
    recompressBtn.disabled = false;
    return;
  }

  setTimeout(() => pollJob(jobId), 800);
}
