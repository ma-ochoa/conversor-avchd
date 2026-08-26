const pathInput = document.getElementById("path-input");
const crumb = document.getElementById("crumb");
const dirList = document.getElementById("dir-list");
const goBtn = document.getElementById("go-btn");
const browseBtn = document.getElementById("browse-btn");
const scanBtn = document.getElementById("scan-btn");
const scanStatus = document.getElementById("scan-status");

const resultsSection = document.getElementById("results-section");
const videoBody = document.querySelector("#video-table tbody");
const checkAll = document.getElementById("check-all");

const runBtn = document.getElementById("run-btn");
const progressSection = document.getElementById("progress-section");
const progressBody = document.querySelector("#progress-table tbody");
const jobSummary = document.getElementById("job-summary");

let root = "";

function formatBytes(bytes) {
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return (mb / 1024).toFixed(2) + " GB";
  return mb.toFixed(1) + " MB";
}

function formatDate(iso) {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19);
}

// ── Explorador de carpetas (idéntico al del resto de secciones) ──────────────
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

// ── Listado de vídeos ────────────────────────────────────────────────────────
function renderRow(item) {
  const tr = document.createElement("tr");

  const cbTd = document.createElement("td");
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.className = "select-video";
  cb.dataset.path = item.path;
  cbTd.appendChild(cb);

  const nameTd = document.createElement("td");
  nameTd.textContent = item.relative;

  const dateTd = document.createElement("td");
  dateTd.textContent = formatDate(item.capture_dt);

  const sizeTd = document.createElement("td");
  sizeTd.textContent = formatBytes(item.size);

  tr.append(cbTd, nameTd, dateTd, sizeTd);
  return tr;
}

checkAll.addEventListener("change", () => {
  document.querySelectorAll(".select-video").forEach((cb) => {
    cb.checked = checkAll.checked;
  });
});

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
  root = data.root;
  rememberRoot(root);

  const videos = [...(data.avchd || []), ...(data.other_videos || [])];
  videoBody.innerHTML = "";
  videos.forEach((item) => videoBody.appendChild(renderRow(item)));
  document.getElementById("video-empty").classList.toggle("hidden", videos.length > 0);
  checkAll.checked = false;

  resultsSection.classList.remove("hidden");
});

// ── Selector de proceso ──────────────────────────────────────────────────────
function procesoActual() {
  return document.querySelector('input[name="proceso"]:checked').value;
}

function actualizarPaneles() {
  const p = procesoActual();
  document.querySelectorAll(".proceso-panel").forEach((el) => {
    el.classList.toggle("hidden", el.dataset.proceso !== p);
  });
}
document.querySelectorAll('input[name="proceso"]').forEach((r) => {
  r.addEventListener("change", actualizarPaneles);
});
actualizarPaneles();

// ── Deslizadores con valor visible ───────────────────────────────────────────
function enlazar(idRange, idValor, decimales = 0) {
  const range = document.getElementById(idRange);
  const valor = document.getElementById(idValor);
  if (!range || !valor) return;
  const pinta = () => {
    valor.textContent = decimales ? Number(range.value).toFixed(decimales) : range.value;
  };
  range.addEventListener("input", pinta);
  pinta();
}
enlazar("bloq-suavizado", "bloq-suav-value", 1);
enlazar("bloq-anclas", "bloq-anclas-value");
enlazar("bloq-calidad", "bloq-calidad-value");
enlazar("bloq-margen", "bloq-margen-value");
enlazar("seg-focal", "seg-focal-value");
enlazar("hoja-columnas", "hoja-col-value");
enlazar("hoja-celda", "hoja-celda-value");

document.getElementById("bloq-modo").addEventListener("change", (e) => {
  document.getElementById("bloq-suav-row").classList.toggle("hidden", e.target.value !== "suavizado");
});
document.getElementById("seg-radio-modo").addEventListener("change", (e) => {
  const manual = e.target.value === "manual";
  document.getElementById("seg-radio-row").classList.toggle("hidden", !manual);
  document.getElementById("seg-optica-panel").classList.toggle("hidden", manual);
});
document.getElementById("seg-lado-modo").addEventListener("change", (e) => {
  document.getElementById("seg-lado-row").classList.toggle("hidden", e.target.value !== "manual");
});

// ── Lanzar el trabajo ────────────────────────────────────────────────────────
function reunirParametros(proceso) {
  const params = {
    deinterlace: document.getElementById("deinterlace").checked,
    formato: document.getElementById("formato").value,
  };
  if (proceso === "bloqueo") {
    Object.assign(params, {
      modo: document.getElementById("bloq-modo").value,
      suavizado_seg: parseFloat(document.getElementById("bloq-suavizado").value),
      anclas_seg: parseFloat(document.getElementById("bloq-anclas").value),
      calidad_min: parseFloat(document.getElementById("bloq-calidad").value),
      recorte_extra: parseFloat(document.getElementById("bloq-margen").value) / 100,
    });
  } else if (proceso === "seguimiento" || proceso === "auditoria") {
    Object.assign(params, {
      radio_modo: document.getElementById("seg-radio-modo").value,
      radio_px: parseFloat(document.getElementById("seg-radio-px").value),
      objeto: document.getElementById("seg-objeto").value,
      focal_mm: parseFloat(document.getElementById("seg-focal").value),
      sensor_mm: parseFloat(document.getElementById("seg-sensor").value),
      medir_objeto: document.getElementById("aud-objeto").checked,
    });
    if (proceso === "seguimiento" && document.getElementById("seg-lado-modo").value === "manual") {
      params.lado = parseInt(document.getElementById("seg-lado").value, 10);
    }
  } else if (proceso === "extraccion") {
    Object.assign(params, {
      ratio: parseInt(document.getElementById("ext-ratio").value, 10),
      descartar_negros: document.getElementById("ext-negros").checked,
      descartar_movidos: document.getElementById("ext-movidos").checked,
      salida: document.getElementById("ext-salida").value,
    });
  } else if (proceso === "hoja") {
    Object.assign(params, {
      columnas: parseInt(document.getElementById("hoja-columnas").value, 10),
      celda: parseInt(document.getElementById("hoja-celda").value, 10),
      reticula: document.getElementById("hoja-reticula").checked,
    });
  }
  return params;
}

runBtn.addEventListener("click", async () => {
  if (!root) return;
  const paths = Array.from(document.querySelectorAll(".select-video:checked")).map((cb) => cb.dataset.path);
  if (paths.length === 0) {
    scanStatus.textContent = "No hay ningún vídeo marcado.";
    return;
  }

  const proceso = procesoActual();
  runBtn.disabled = true;
  jobSummary.textContent = "";

  const res = await fetch("/api/avanzada", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ root, proceso, paths, params: reunirParametros(proceso) }),
  });
  const data = await res.json();
  if (data.error) {
    jobSummary.textContent = data.error;
    progressSection.classList.remove("hidden");
    runBtn.disabled = false;
    return;
  }

  progressSection.classList.remove("hidden");
  pollJob(data.job_id);
});

// ── Progreso ─────────────────────────────────────────────────────────────────
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

function formatStats(proceso, stats) {
  if (!stats) return "—";
  if (proceso === "bloqueo") {
    return `${stats.recorte} (${stats.porcentaje_imagen}% de imagen) · recorrido ${stats.recorrido_px} · `
      + `${stats.medidas_descartadas} medidas descartadas`;
  }
  if (proceso === "seguimiento") {
    return `${stats.fotogramas} fotogramas · lado ${stats.lado} px · radio ${stats.radio_px} px · `
      + `${stats.extrapolados} extrapolados`;
  }
  if (proceso === "extraccion") {
    return `${stats.escritos} de ${stats.fotogramas_origen} (${stats.duracion_s}s) · `
      + `${stats.negros_detectados} negros, ${stats.movidos_detectados} movidos · `
      + `${stats.grupos_omitidos} grupos sin candidato`;
  }
  if (proceso === "hoja") return `${stats.miniaturas} miniaturas`;
  if (proceso === "auditoria") {
    const t = stats.temblor_consecutivo;
    const d = stats.desvio_vs_primero;
    const o = stats.descentrado_objeto;
    let txt = "";
    if (t) txt += `temblor mediana ${t.mediana} px (p95 ${t.p95})`;
    if (d) txt += ` · desvío vs 1º mediana ${d.mediana} px (máx ${d.max})`;
    if (o) txt += ` · descentrado objeto ${o.mediana} px`;
    return txt || "—";
  }
  return "—";
}

async function pollJob(jobId) {
  const res = await fetch(`/api/avanzada-status/${jobId}`);
  const job = await res.json();
  if (job.error) {
    jobSummary.textContent = job.error;
    runBtn.disabled = false;
    return;
  }

  if (Object.keys(rowsByPath).length === 0) ensureProgressRows(job.items);

  job.items.forEach((item) => {
    const row = rowsByPath[item.path];
    if (!row) return;
    let estado = item.status;
    if (item.phase && item.status === "procesando") estado += ` — ${item.phase}`;
    if (item.error) estado += `: ${item.error}`;
    row.statusTd.textContent = estado;
    row.bar.value = item.percent;
    if (item.stats) row.resultTd.textContent = formatStats(job.proceso, item.stats);
  });

  if (job.state === "finalizado") {
    const done = job.items.filter((i) => i.status === "completado").length;
    const errors = job.items.filter((i) => i.status === "error").length;
    jobSummary.textContent = `Terminado: ${done} procesados, ${errors} con error. `
      + `La salida está en avanzada/${job.proceso}/ dentro de tu carpeta de trabajo.`;
    runBtn.disabled = false;
    return;
  }

  setTimeout(() => pollJob(jobId), 800);
}
