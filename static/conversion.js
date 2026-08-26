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
const avchdSelectAll = document.getElementById("avchd-select-all");
const photoSelectAll = document.getElementById("photo-select-all");

const convertBtn = document.getElementById("convert-btn");
const progressSection = document.getElementById("progress-section");
const progressBody = document.querySelector("#progress-table tbody");
const jobSummary = document.getElementById("job-summary");

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

function currentPrefix() {
  return document.getElementById("prefix-input").value.trim().replace(/[^A-Za-z0-9_-]/g, "");
}

function outputName(iso, ext) {
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  const stem = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  const prefix = currentPrefix();
  return `${prefix ? prefix + "_" : ""}${stem}${ext}`;
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

function renderRow(item, ext) {
  const tr = document.createElement("tr");

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

  tr.append(cbTd, nameTd, dateTd, sizeTd, destTd, statusTd);
  return tr;
}

function syncSelectAll(headerCb, tbody) {
  const boxes = Array.from(tbody.querySelectorAll(".select-convert"));
  const checkedCount = boxes.filter((cb) => cb.checked).length;
  headerCb.checked = boxes.length > 0 && checkedCount === boxes.length;
  headerCb.indeterminate = checkedCount > 0 && checkedCount < boxes.length;
}

function wireSelectAll(headerCb, tbody) {
  headerCb.addEventListener("change", () => {
    tbody.querySelectorAll(".select-convert").forEach((cb) => (cb.checked = headerCb.checked));
    headerCb.indeterminate = false;
  });
  tbody.addEventListener("change", (e) => {
    if (e.target.classList.contains("select-convert")) syncSelectAll(headerCb, tbody);
  });
}
wireSelectAll(avchdSelectAll, avchdBody);
wireSelectAll(photoSelectAll, photoBody);

function renderResultsTables() {
  if (!lastScan) return;

  avchdBody.innerHTML = "";
  lastScan.avchd_clips.forEach((item) => avchdBody.appendChild(renderRow(item, ".mp4")));
  document.getElementById("avchd-empty").classList.toggle("hidden", lastScan.avchd_clips.length > 0);
  syncSelectAll(avchdSelectAll, avchdBody);

  photoBody.innerHTML = "";
  lastScan.photos.forEach((item) => {
    const ext = item.relative.slice(item.relative.lastIndexOf(".")).toLowerCase();
    photoBody.appendChild(renderRow(item, ext));
  });
  document.getElementById("photo-empty").classList.toggle("hidden", lastScan.photos.length > 0);
  syncSelectAll(photoSelectAll, photoBody);
}

scanBtn.addEventListener("click", async () => {
  scanStatus.textContent = "Escaneando…";
  resultsSection.classList.add("hidden");
  progressSection.classList.add("hidden");
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

  document.getElementById("avchd-count").textContent = data.avchd_clips.length;
  document.getElementById("photo-count").textContent = data.photos.length;
  document.getElementById("other-count").textContent = data.other_videos.length;
  outputDirNote.textContent = `Los ficheros convertidos se guardarán en: ${data.output_dir}`;

  renderResultsTables();

  otherList.innerHTML = "";
  otherBlock.classList.toggle("hidden", data.other_videos.length === 0);
  data.other_videos.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = `${item.relative} (${formatBytes(item.size)})`;
    otherList.appendChild(li);
  });

  resultsSection.classList.remove("hidden");
});

document.getElementById("prefix-input").addEventListener("input", renderResultsTables);

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
      prefix: currentPrefix(),
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
