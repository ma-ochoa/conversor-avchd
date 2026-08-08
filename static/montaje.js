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
    actions.append(trimBtn, titleBtn);
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
    clips: timeline.map((t) => ({ id: t.id, path: t.path, in: t.in, out: t.out, title: t.title })),
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
  }));
  renderTimeline();
  projectStatus.textContent = `Proyecto "${name}" cargado.`;
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

loadDirs(pathInput.value);
