const pathInput = document.getElementById("path-input");
const goBtn = document.getElementById("go-btn");
const browseBtn = document.getElementById("browse-btn");

const projectSection = document.getElementById("project-section");
const clipsSection = document.getElementById("clips-section");
const timelineSection = document.getElementById("timeline-section");
const exportSection = document.getElementById("export-section");

const projectNameInput = document.getElementById("project-name");
const projectSelect = document.getElementById("project-select");
const projectStatus = document.getElementById("project-status");

const clipsGrid = document.getElementById("clips-grid");
const clipsEmpty = document.getElementById("clips-empty");

const timelineEl = document.getElementById("timeline");
const timelineEmptyHint = document.getElementById("timeline-empty");
const timelineDurationEl = document.getElementById("timeline-duration");
const transitionInput = document.getElementById("transition-seconds");

const exportBtn = document.getElementById("export-btn");
const exportProgressWrap = document.getElementById("export-progress-wrap");
const exportProgress = document.getElementById("export-progress");
const exportStatus = document.getElementById("export-status");
const exportResult = document.getElementById("export-result");

const previewModal = document.getElementById("preview-modal");
const previewVideo = document.getElementById("preview-video");
const previewClose = document.getElementById("preview-close");
const trimControls = document.getElementById("trim-controls");
const trimIn = document.getElementById("trim-in");
const trimOut = document.getElementById("trim-out");
const markInBtn = document.getElementById("mark-in-btn");
const markOutBtn = document.getElementById("mark-out-btn");
const trimApplyBtn = document.getElementById("trim-apply-btn");

const titleModal = document.getElementById("title-modal");
const titleClose = document.getElementById("title-close");
const titleText = document.getElementById("title-text");
const titleFont = document.getElementById("title-font");
const titleDuration = document.getElementById("title-duration");
const titleImage = document.getElementById("title-image");
const titleImagePick = document.getElementById("title-image-pick");
const titleImageClear = document.getElementById("title-image-clear");
const titleImagePreview = document.getElementById("title-image-preview");
const titleSaveBtn = document.getElementById("title-save-btn");
const titleClearBtn = document.getElementById("title-clear-btn");

let root = "";
let clipsByPath = {};
let timeline = [];
let editingTimelineId = null;
let dragPayload = null;

function formatDuration(seconds) {
  seconds = Math.max(seconds, 0);
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

// ---------- Navegación de carpetas ----------

async function loadDirs(path) {
  const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
  const data = await res.json();
  if (data.error) return;
  pathInput.value = data.path;
}

goBtn.addEventListener("click", () => {
  loadDirs(pathInput.value).then(() => setRoot(pathInput.value));
});
pathInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadDirs(pathInput.value).then(() => setRoot(pathInput.value));
});

browseBtn.addEventListener("click", async () => {
  const res = await fetch("/api/pick-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: pathInput.value }),
  });
  const data = await res.json();
  if (data.canceled || data.error || !data.path) return;
  pathInput.value = data.path;
  setRoot(data.path);
});

// ---------- Carga de raíz / clips / proyectos ----------

async function setRoot(newRoot) {
  root = newRoot;
  rememberRoot(newRoot);
  projectSection.classList.remove("hidden");
  clipsSection.classList.remove("hidden");
  timelineSection.classList.remove("hidden");
  exportSection.classList.remove("hidden");
  await Promise.all([loadClips(), loadProjectsList(), loadFonts()]);
}

async function loadClips() {
  const res = await fetch(`/api/montaje/clips?root=${encodeURIComponent(root)}`);
  const data = await res.json();
  if (data.error) {
    clipsGrid.innerHTML = "";
    clipsEmpty.textContent = data.error;
    clipsEmpty.classList.remove("hidden");
    return;
  }
  clipsByPath = {};
  data.clips.forEach((c) => (clipsByPath[c.path] = c));
  renderClipsGrid(data.clips);
}

function renderClipsGrid(clips) {
  clipsGrid.innerHTML = "";
  clipsEmpty.classList.toggle("hidden", clips.length > 0);
  clips.forEach((clip) => {
    const card = document.createElement("div");
    card.className = "clip-card";
    card.draggable = true;
    card.dataset.path = clip.path;

    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = `/api/montaje/thumbnail?root=${encodeURIComponent(root)}&path=${encodeURIComponent(clip.path)}`;
    card.appendChild(img);

    const info = document.createElement("div");
    info.className = "clip-info";
    const name = document.createElement("div");
    name.className = "clip-name";
    name.textContent = clip.name;
    const meta = document.createElement("div");
    meta.className = "clip-meta";
    meta.innerHTML = `<span>${formatDuration(clip.duration)}</span><span class="tag">${clip.source}</span>`;
    info.append(name, meta);
    card.appendChild(info);

    card.addEventListener("click", () => openPreview(clip, null));
    card.addEventListener("dragstart", (e) => {
      dragPayload = { kind: "new", path: clip.path };
      e.dataTransfer.effectAllowed = "copy";
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => card.classList.remove("dragging"));

    clipsGrid.appendChild(card);
  });
}

async function loadFonts() {
  const res = await fetch("/api/montaje/fonts");
  const data = await res.json();
  titleFont.innerHTML = "";
  (data.fonts || []).forEach((f) => {
    const opt = document.createElement("option");
    opt.value = f.path;
    opt.textContent = f.name;
    titleFont.appendChild(opt);
  });
}

async function loadProjectsList() {
  const res = await fetch(`/api/montaje/projects?root=${encodeURIComponent(root)}`);
  const data = await res.json();
  projectSelect.innerHTML = '<option value="">— Cargar proyecto guardado —</option>';
  (data.projects || []).forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    projectSelect.appendChild(opt);
  });
}

// ---------- Timeline: añadir / reordenar / quitar ----------

function addClipToTimeline(path, atIndex = null) {
  const clip = clipsByPath[path] || { name: path.split("/").pop(), duration: 0, path };
  const item = {
    id: uid(),
    path,
    in: 0,
    out: clip.duration || 0,
    title: null,
    stabilize: null,
  };
  if (atIndex === null || atIndex >= timeline.length) {
    timeline.push(item);
  } else {
    timeline.splice(atIndex, 0, item);
  }
  renderTimeline();
}

function findTimelineIndexById(id) {
  return timeline.findIndex((t) => t.id === id);
}

function moveTimelineItem(id, toIndex) {
  const from = findTimelineIndexById(id);
  if (from === -1) return;
  const [item] = timeline.splice(from, 1);
  timeline.splice(toIndex > from ? toIndex - 1 : toIndex, 0, item);
  renderTimeline();
}

function removeTimelineItem(id) {
  timeline = timeline.filter((t) => t.id !== id);
  renderTimeline();
}

function renderTimeline() {
  Array.from(timelineEl.querySelectorAll(".timeline-item, .transition-glyph")).forEach((el) => el.remove());
  timelineEmptyHint.classList.toggle("hidden", timeline.length > 0);

  timeline.forEach((item, index) => {
    if (index > 0) {
      const glyph = document.createElement("div");
      glyph.className = "transition-glyph";
      glyph.textContent = "⇄";
      glyph.title = "Transición cruzada";
      timelineEl.appendChild(glyph);
    }

    const clip = clipsByPath[item.path] || { name: item.path.split("/").pop() };
    const card = document.createElement("div");
    card.className = "timeline-item";
    card.draggable = true;
    card.dataset.id = item.id;

    const removeBtn = document.createElement("button");
    removeBtn.className = "ti-remove";
    removeBtn.textContent = "✕";
    removeBtn.title = "Quitar del montaje";
    removeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      removeTimelineItem(item.id);
    });
    card.appendChild(removeBtn);

    const img = document.createElement("img");
    img.src = `/api/montaje/thumbnail?root=${encodeURIComponent(root)}&path=${encodeURIComponent(item.path)}`;
    card.appendChild(img);

    const body = document.createElement("div");
    body.className = "ti-body";
    const name = document.createElement("div");
    name.className = "ti-name";
    name.textContent = clip.name;
    const dur = document.createElement("div");
    dur.className = "ti-dur";
    dur.textContent = `${item.in.toFixed(1)}s → ${item.out.toFixed(1)}s (${formatDuration(item.out - item.in)})`;
    body.append(name, dur);

    if (item.title) {
      const badge = document.createElement("div");
      badge.className = "ti-title-badge";
      badge.textContent = item.title.text ? `🔤 "${item.title.text}"` : "🖼️ imagen";
      body.appendChild(badge);
    }
    if (item.stabilize) {
      const stabBadge = document.createElement("div");
      stabBadge.className = "ti-stab-badge";
      stabBadge.textContent = "🩹 estabilizado";
      body.appendChild(stabBadge);
    }

    const actions = document.createElement("div");
    actions.className = "ti-actions";
    const trimBtn = document.createElement("button");
    trimBtn.textContent = "Recortar";
    trimBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openPreview(clip, item.id);
    });
    const titleBtn = document.createElement("button");
    titleBtn.textContent = "Título";
    titleBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openTitleModal(item.id);
    });
    const stabBtn = document.createElement("button");
    stabBtn.textContent = "Estabilizar";
    stabBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openStabilizeModal(item.id);
    });
    actions.append(trimBtn, titleBtn, stabBtn);
    body.appendChild(actions);
    card.appendChild(body);

    card.addEventListener("dragstart", (e) => {
      dragPayload = { kind: "reorder", id: item.id };
      e.dataTransfer.effectAllowed = "move";
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      clearDropIndicators();
    });
    card.addEventListener("dragover", (e) => {
      e.preventDefault();
      clearDropIndicators();
      const rect = card.getBoundingClientRect();
      const before = e.clientX - rect.left < rect.width / 2;
      card.classList.add(before ? "drop-before" : "drop-after");
    });

    timelineEl.appendChild(card);
  });

  updateTotalDuration();
}

function clearDropIndicators() {
  timelineEl.querySelectorAll(".drop-before, .drop-after").forEach((el) => {
    el.classList.remove("drop-before", "drop-after");
  });
}

function updateTotalDuration() {
  const t = parseFloat(transitionInput.value) || 0;
  const raw = timeline.reduce((sum, item) => sum + (item.out - item.in), 0);
  const total = Math.max(raw - t * Math.max(timeline.length - 1, 0), 0);
  timelineDurationEl.textContent = timeline.length
    ? `Duración total estimada: ${formatDuration(total)}`
    : "";
}
transitionInput.addEventListener("input", updateTotalDuration);

timelineEl.addEventListener("dragover", (e) => {
  e.preventDefault();
  timelineEl.classList.add("drag-over");
});
timelineEl.addEventListener("dragleave", (e) => {
  if (e.target === timelineEl) timelineEl.classList.remove("drag-over");
});
timelineEl.addEventListener("drop", (e) => {
  e.preventDefault();
  timelineEl.classList.remove("drag-over");
  clearDropIndicators();
  if (!dragPayload) return;

  let targetIndex = timeline.length;
  const overCard = e.target.closest(".timeline-item");
  if (overCard) {
    const rect = overCard.getBoundingClientRect();
    const before = e.clientX - rect.left < rect.width / 2;
    const overIndex = findTimelineIndexById(overCard.dataset.id);
    targetIndex = before ? overIndex : overIndex + 1;
  }

  if (dragPayload.kind === "new") {
    addClipToTimeline(dragPayload.path, targetIndex);
  } else if (dragPayload.kind === "reorder") {
    moveTimelineItem(dragPayload.id, targetIndex);
  }
  dragPayload = null;
});

// ---------- Modal de previsualización / recorte ----------

function openPreview(clip, timelineId) {
  editingTimelineId = timelineId;
  previewVideo.src = `/media?path=${encodeURIComponent(clip.path)}`;
  previewModal.classList.remove("hidden");
  previewVideo.currentTime = 0;

  if (timelineId) {
    const item = timeline.find((t) => t.id === timelineId);
    trimControls.classList.remove("hidden");
    trimIn.value = item.in.toFixed(1);
    trimOut.value = item.out.toFixed(1);
  } else {
    trimControls.classList.add("hidden");
  }
}

previewClose.addEventListener("click", () => {
  previewVideo.pause();
  previewVideo.src = "";
  previewModal.classList.add("hidden");
});
previewModal.addEventListener("click", (e) => {
  if (e.target === previewModal) previewClose.click();
});

markInBtn.addEventListener("click", () => (trimIn.value = previewVideo.currentTime.toFixed(1)));
markOutBtn.addEventListener("click", () => (trimOut.value = previewVideo.currentTime.toFixed(1)));

trimApplyBtn.addEventListener("click", () => {
  if (!editingTimelineId) return;
  const item = timeline.find((t) => t.id === editingTimelineId);
  const inVal = parseFloat(trimIn.value) || 0;
  const outVal = parseFloat(trimOut.value) || inVal + 1;
  if (outVal <= inVal) {
    alert("El fin debe ser mayor que el inicio.");
    return;
  }
  item.in = inVal;
  item.out = outVal;
  renderTimeline();
  previewClose.click();
});

// ---------- Modal de título ----------

function openTitleModal(timelineId) {
  editingTimelineId = timelineId;
  const item = timeline.find((t) => t.id === timelineId);
  const title = item.title || {};
  titleText.value = title.text || "";
  titleDuration.value = title.duration || 3;
  if (title.font) titleFont.value = title.font;
  titleImage.value = title.image || "";
  updateTitleImagePreview();
  titleModal.classList.remove("hidden");
}

function updateTitleImagePreview() {
  if (titleImage.value) {
    titleImagePreview.src = `/media?path=${encodeURIComponent(titleImage.value)}`;
    titleImagePreview.classList.remove("hidden");
  } else {
    titleImagePreview.classList.add("hidden");
  }
}

titleClose.addEventListener("click", () => titleModal.classList.add("hidden"));
titleModal.addEventListener("click", (e) => {
  if (e.target === titleModal) titleModal.classList.add("hidden");
});

titleImagePick.addEventListener("click", async () => {
  const res = await fetch("/api/pick-file", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: root }),
  });
  const data = await res.json();
  if (data.canceled || data.error || !data.path) return;
  titleImage.value = data.path;
  updateTitleImagePreview();
});
titleImageClear.addEventListener("click", () => {
  titleImage.value = "";
  updateTitleImagePreview();
});

titleClearBtn.addEventListener("click", () => {
  const item = timeline.find((t) => t.id === editingTimelineId);
  item.title = null;
  renderTimeline();
  titleModal.classList.add("hidden");
});

titleSaveBtn.addEventListener("click", () => {
  const item = timeline.find((t) => t.id === editingTimelineId);
  const text = titleText.value.trim();
  const image = titleImage.value.trim();
  if (!text && !image) {
    item.title = null;
  } else {
    item.title = {
      text: text || null,
      font: titleFont.value || null,
      image: image || null,
      duration: parseFloat(titleDuration.value) || 3,
    };
  }
  renderTimeline();
  titleModal.classList.add("hidden");
});

// ---------- Guardar / cargar proyecto ----------

function serializeProject() {
  return {
    version: 1,
    root: root,
    transition_seconds: parseFloat(transitionInput.value) || 0,
    clips: timeline.map((t) => ({
      id: t.id, path: t.path, in: t.in, out: t.out, title: t.title, stabilize: t.stabilize || null,
    })),
  };
}

document.getElementById("save-project-btn").addEventListener("click", async () => {
  const name = projectNameInput.value.trim();
  if (!name) {
    projectStatus.textContent = "Ponle un nombre al proyecto.";
    return;
  }
  const res = await fetch("/api/montaje/project", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ root, name, project: serializeProject() }),
  });
  const data = await res.json();
  projectStatus.textContent = data.error || "Guardado.";
  loadProjectsList();
});

document.getElementById("load-project-btn").addEventListener("click", async () => {
  const name = projectSelect.value;
  if (!name) return;
  const res = await fetch(`/api/montaje/project?root=${encodeURIComponent(root)}&name=${encodeURIComponent(name)}`);
  const data = await res.json();
  if (data.error) {
    projectStatus.textContent = data.error;
    return;
  }
  projectNameInput.value = name;
  transitionInput.value = data.transition_seconds ?? 2;
  timeline = (data.clips || []).map((c) => ({
    id: c.id || uid(),
    path: c.path,
    in: c.in,
    out: c.out,
    title: c.title || null,
    stabilize: c.stabilize || null,
  }));
  renderTimeline();
  projectStatus.textContent = `Proyecto "${name}" cargado.`;
});

document.getElementById("delete-project-btn").addEventListener("click", async () => {
  const name = projectSelect.value;
  if (!name) return;
  if (!confirm(`¿Eliminar el proyecto guardado "${name}"? Esto no borra ningún vídeo, solo el proyecto.`)) return;
  await fetch(`/api/montaje/project?root=${encodeURIComponent(root)}&name=${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  projectStatus.textContent = `Proyecto "${name}" eliminado.`;
  loadProjectsList();
});

document.getElementById("new-project-btn").addEventListener("click", () => {
  timeline = [];
  projectNameInput.value = "Mi montaje";
  transitionInput.value = 2;
  renderTimeline();
  exportResult.classList.add("hidden");
  projectStatus.textContent = "Proyecto nuevo.";
});

// ---------- Exportar ----------

exportBtn.addEventListener("click", async () => {
  if (timeline.length === 0) {
    projectStatus.textContent = "Añade al menos un clip a la línea de tiempo.";
    return;
  }
  exportBtn.disabled = true;
  exportProgressWrap.classList.remove("hidden");
  exportResult.classList.add("hidden");
  exportProgress.value = 0;
  exportStatus.textContent = "Iniciando…";

  const project = serializeProject();
  const res = await fetch("/api/montaje/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      root,
      name: projectNameInput.value.trim() || "montaje",
      clips: project.clips,
      transition_seconds: project.transition_seconds,
    }),
  });
  const data = await res.json();
  if (data.error) {
    exportStatus.textContent = data.error;
    exportBtn.disabled = false;
    return;
  }
  pollExport(data.job_id);
});

async function pollExport(jobId) {
  const res = await fetch(`/api/montaje/export-status/${jobId}`);
  const job = await res.json();
  if (job.error) {
    exportStatus.textContent = job.error;
    exportBtn.disabled = false;
    return;
  }
  exportProgress.value = job.percent;
  exportStatus.textContent = `${job.status} (${Math.round(job.percent * 100)}%)`;

  if (job.status === "completado") {
    exportResult.classList.remove("hidden");
    exportResult.textContent = `Listo: ${job.dest}`;
    exportBtn.disabled = false;
    return;
  }
  if (job.status === "error") {
    exportBtn.disabled = false;
    return;
  }
  setTimeout(() => pollExport(jobId), 900);
}

// ---------- Modal de estabilización ----------

const stabilizeModal = document.getElementById("stabilize-modal");
const stabilizeClose = document.getElementById("stabilize-close");
const stabilizeAnalyzeBtn = document.getElementById("stabilize-analyze-btn");
const stabilizeAnalyzeStatus = document.getElementById("stabilize-analyze-status");
const stabilizeAnalyzeProgress = document.getElementById("stabilize-analyze-progress");
const stabilizePreviewWrap = document.getElementById("stabilize-preview-wrap");
const stabilizeProxyVideo = document.getElementById("stabilize-proxy-video");
const stabilizeCanvas = document.getElementById("stabilize-canvas");
const stabilizeCtx = stabilizeCanvas.getContext("2d");
const stabilizePlayBtn = document.getElementById("stabilize-play-btn");
const stabilizeSeek = document.getElementById("stabilize-seek");
const stabilizePreviewToggle = document.getElementById("stabilize-preview-toggle");
const stabilizeClearBtn = document.getElementById("stabilize-clear-btn");
const stabilizeSaveBtn = document.getElementById("stabilize-save-btn");

const montajeStabCustomPanel = document.getElementById("montaje-stab-custom-panel");
const montajeZoomModeSelect = document.getElementById("montaje-zoom-mode");
const montajeZoomPercentRow = document.getElementById("montaje-zoom-percent-row");

let stabilizeEditingId = null;
let stabilizeAnalysis = null;
let stabilizeCorrections = null;
let stabilizeRafId = null;

document.querySelectorAll('input[name="montaje-stab-mode"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    montajeStabCustomPanel.classList.toggle("hidden", document.getElementById("montaje-stab-mode-auto").checked);
    recomputeAndRender();
  });
});
["montaje-shakiness", "montaje-smoothing", "montaje-zoom-percent"].forEach((id) => {
  const input = document.getElementById(id);
  const label = document.getElementById(`${id}-value`);
  input.addEventListener("input", () => {
    label.textContent = input.value;
    if (id !== "montaje-shakiness") recomputeAndRender();
  });
});
montajeZoomModeSelect.addEventListener("change", () => {
  montajeZoomPercentRow.classList.toggle("hidden", montajeZoomModeSelect.value !== "manual");
  recomputeAndRender();
});

function montajeStabParams() {
  if (document.getElementById("montaje-stab-mode-auto").checked) {
    return { shakiness: 5, accuracy: 15, smoothing: 10, zoom_mode: "auto_static", zoom_percent: 0 };
  }
  return {
    shakiness: parseInt(document.getElementById("montaje-shakiness").value, 10),
    accuracy: 15,
    smoothing: parseInt(document.getElementById("montaje-smoothing").value, 10),
    zoom_mode: montajeZoomModeSelect.value,
    zoom_percent: parseFloat(document.getElementById("montaje-zoom-percent").value),
  };
}

function openStabilizeModal(timelineId) {
  stabilizeEditingId = timelineId;
  const item = timeline.find((t) => t.id === timelineId);
  const stab = item.stabilize;

  stopStabilizePlayback();
  stabilizeAnalysis = null;
  stabilizeCorrections = null;
  stabilizePreviewWrap.classList.add("hidden");
  stabilizeAnalyzeStatus.textContent = "";
  stabilizeAnalyzeProgress.classList.add("hidden");
  stabilizeSaveBtn.disabled = true;

  const isCustom = stab && (stab.zoom_mode !== "auto_static" || stab.smoothing !== 10 || stab.shakiness !== 5);
  document.getElementById("montaje-stab-mode-auto").checked = !isCustom;
  document.getElementById("montaje-stab-mode-custom").checked = !!isCustom;
  montajeStabCustomPanel.classList.toggle("hidden", !isCustom);
  if (stab) {
    document.getElementById("montaje-shakiness").value = stab.shakiness;
    document.getElementById("montaje-shakiness-value").textContent = stab.shakiness;
    document.getElementById("montaje-smoothing").value = stab.smoothing;
    document.getElementById("montaje-smoothing-value").textContent = stab.smoothing;
    montajeZoomModeSelect.value = stab.zoom_mode;
    document.getElementById("montaje-zoom-percent").value = stab.zoom_percent;
    document.getElementById("montaje-zoom-percent-value").textContent = stab.zoom_percent;
    montajeZoomPercentRow.classList.toggle("hidden", stab.zoom_mode !== "manual");
  }

  stabilizeModal.classList.remove("hidden");
}

stabilizeClose.addEventListener("click", () => {
  stopStabilizePlayback();
  stabilizeModal.classList.add("hidden");
});
stabilizeModal.addEventListener("click", (e) => {
  if (e.target === stabilizeModal) stabilizeClose.click();
});

stabilizeAnalyzeBtn.addEventListener("click", async () => {
  const item = timeline.find((t) => t.id === stabilizeEditingId);
  const params = montajeStabParams();
  stabilizeAnalyzeBtn.disabled = true;
  stabilizeAnalyzeStatus.textContent = "Analizando… (puede tardar, sobre todo la primera vez en 4K)";
  stabilizeAnalyzeProgress.classList.remove("hidden");
  stabilizeAnalyzeProgress.value = 0;

  const res = await fetch("/api/montaje/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ root, path: item.path, shakiness: params.shakiness, accuracy: params.accuracy }),
  });
  const data = await res.json();
  if (data.error) {
    stabilizeAnalyzeStatus.textContent = data.error;
    stabilizeAnalyzeBtn.disabled = false;
    return;
  }
  pollStabilizeAnalyze(data.job_id);
});

async function pollStabilizeAnalyze(jobId) {
  const res = await fetch(`/api/montaje/analyze-status/${jobId}`);
  const job = await res.json();
  if (job.error) {
    stabilizeAnalyzeStatus.textContent = job.error;
    stabilizeAnalyzeBtn.disabled = false;
    return;
  }
  stabilizeAnalyzeProgress.value = job.percent;
  if (job.status === "completado") {
    stabilizeAnalysis = job.data;
    const conf = stabilizeAnalysis.stats && stabilizeAnalysis.stats.confidence_percent;
    stabilizeAnalyzeStatus.textContent =
      `Listo (${stabilizeAnalysis.path.length} fotogramas${conf != null ? " · confianza " + conf + "%" : ""})`;
    stabilizeAnalyzeBtn.disabled = false;
    stabilizeSaveBtn.disabled = false;
    setupStabilizePreview();
    return;
  }
  if (job.status === "error") {
    stabilizeAnalyzeStatus.textContent = job.error;
    stabilizeAnalyzeBtn.disabled = false;
    return;
  }
  setTimeout(() => pollStabilizeAnalyze(jobId), 700);
}

// ---------- Suavizado y renderizado en canvas (todo en el navegador, sin servidor) ----------

function medianAbs(values) {
  const sorted = values.map(Math.abs).sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function computeCorrections(analysis, smoothingWindow) {
  const n = analysis.path.length;
  // Algún fotograma aislado con poco contraste puede dar un valor de movimiento
  // disparatado; se recorta a 4x la mediana para que no arrastre el resto de la
  // trayectoria acumulada (si no, un solo fotograma malo desplaza todo lo siguiente).
  const dxs = analysis.path.map((f) => f.dx);
  const dys = analysis.path.map((f) => f.dy);
  const limX = Math.max(medianAbs(dxs) * 4, 1);
  const limY = Math.max(medianAbs(dys) * 4, 1);
  const clamp = (v, lim) => Math.max(-lim, Math.min(lim, v));

  const cumX = new Array(n), cumY = new Array(n), cumA = new Array(n);
  let x = 0, y = 0, a = 0;
  for (let i = 0; i < n; i++) {
    x += clamp(analysis.path[i].dx, limX);
    y += clamp(analysis.path[i].dy, limY);
    a += analysis.path[i].angle;
    cumX[i] = x; cumY[i] = y; cumA[i] = a;
  }
  const w = Math.max(smoothingWindow, 0);
  const smoothX = new Array(n), smoothY = new Array(n), smoothA = new Array(n);
  for (let i = 0; i < n; i++) {
    const lo = Math.max(0, i - w), hi = Math.min(n - 1, i + w);
    let sx = 0, sy = 0, sa = 0;
    for (let j = lo; j <= hi; j++) { sx += cumX[j]; sy += cumY[j]; sa += cumA[j]; }
    const count = hi - lo + 1;
    smoothX[i] = sx / count; smoothY[i] = sy / count; smoothA[i] = sa / count;
  }
  const corrections = new Array(n);
  let maxAbs = 0;
  for (let i = 0; i < n; i++) {
    const ox = smoothX[i] - cumX[i], oy = smoothY[i] - cumY[i], oa = smoothA[i] - cumA[i];
    corrections[i] = { ox, oy, oa };
    maxAbs = Math.max(maxAbs, Math.abs(ox), Math.abs(oy));
  }
  return { corrections, maxAbs };
}

function autoZoomPercent(analysis, maxAbs) {
  // Aproximación: nunca será idéntico al cálculo real de vid.stab (que usa un
  // algoritmo de optimización más sofisticado), solo orienta visualmente.
  const dim = Math.min(analysis.width, analysis.height);
  if (!dim) return 5;
  return Math.min(40, Math.max(1, (2 * maxAbs / dim) * 100));
}

function setupStabilizePreview() {
  stabilizeProxyVideo.src = `/media?path=${encodeURIComponent(stabilizeAnalysis.proxy_path)}`;
  stabilizeProxyVideo.load();
  stabilizeProxyVideo.addEventListener("loadedmetadata", () => {
    stabilizeSeek.max = stabilizeProxyVideo.duration || stabilizeAnalysis.duration;
    recomputeAndRender();
  }, { once: true });
  stabilizePreviewWrap.classList.remove("hidden");
}

function recomputeAndRender() {
  if (!stabilizeAnalysis) return;
  const params = montajeStabParams();
  const result = computeCorrections(stabilizeAnalysis, params.smoothing);
  const zoomPercent = params.zoom_mode === "manual"
    ? params.zoom_percent
    : autoZoomPercent(stabilizeAnalysis, result.maxAbs);
  stabilizeCorrections = { ...result, zoomPercent };
  renderStabilizeFrame();
}

function renderStabilizeFrame() {
  const canvas = stabilizeCanvas;
  const ctx = stabilizeCtx;
  const video = stabilizeProxyVideo;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (video.readyState < 2) return;

  const useCorrection = stabilizePreviewToggle.checked && stabilizeCorrections;
  if (!useCorrection) {
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return;
  }

  const fps = stabilizeAnalysis.fps || 25;
  const idx = Math.min(
    stabilizeCorrections.corrections.length - 1,
    Math.max(0, Math.round(video.currentTime * fps)),
  );
  const c = stabilizeCorrections.corrections[idx];
  const scaleX = canvas.width / stabilizeAnalysis.width;
  const scaleY = canvas.height / stabilizeAnalysis.height;
  const zoom = 1 + (stabilizeCorrections.zoomPercent || 0) / 100;

  ctx.save();
  ctx.translate(canvas.width / 2, canvas.height / 2);
  ctx.rotate(c.oa);
  ctx.scale(zoom, zoom);
  ctx.translate(-canvas.width / 2 + c.ox * scaleX, -canvas.height / 2 + c.oy * scaleY);
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  ctx.restore();
}

function stabilizeRenderLoop() {
  renderStabilizeFrame();
  stabilizeSeek.value = stabilizeProxyVideo.currentTime;
  if (!stabilizeProxyVideo.paused && !stabilizeProxyVideo.ended) {
    stabilizeRafId = requestAnimationFrame(stabilizeRenderLoop);
  }
}

function stopStabilizePlayback() {
  if (stabilizeRafId) cancelAnimationFrame(stabilizeRafId);
  stabilizeRafId = null;
  stabilizeProxyVideo.pause();
  stabilizePlayBtn.textContent = "▶️";
}

stabilizePlayBtn.addEventListener("click", () => {
  if (stabilizeProxyVideo.paused) {
    stabilizeProxyVideo.play();
    stabilizePlayBtn.textContent = "⏸️";
    stabilizeRafId = requestAnimationFrame(stabilizeRenderLoop);
  } else {
    stopStabilizePlayback();
  }
});

stabilizeSeek.addEventListener("input", () => {
  stopStabilizePlayback();
  stabilizeProxyVideo.currentTime = parseFloat(stabilizeSeek.value);
});
stabilizeProxyVideo.addEventListener("seeked", renderStabilizeFrame);
stabilizePreviewToggle.addEventListener("change", renderStabilizeFrame);

stabilizeClearBtn.addEventListener("click", () => {
  const item = timeline.find((t) => t.id === stabilizeEditingId);
  item.stabilize = null;
  renderTimeline();
  stopStabilizePlayback();
  stabilizeModal.classList.add("hidden");
});

stabilizeSaveBtn.addEventListener("click", () => {
  const item = timeline.find((t) => t.id === stabilizeEditingId);
  item.stabilize = montajeStabParams();
  renderTimeline();
  stopStabilizePlayback();
  stabilizeModal.classList.add("hidden");
});

loadDirs(pathInput.value);
