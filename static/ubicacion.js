const el = (id) => document.getElementById(id);

const ROOT_KEY = "conversor-biblioteca-fotos";

let root = "";
let groups = [];
const selected = new Set();
let chosen = null;      // {gps: [lat, lon], place: "", source: "manual"|"referencia"|"gpx"}
let map = null;
let marker = null;
let groupLayer = null;

// ------------------------------------------------------------------ Utilidades

async function api(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({ error: "Respuesta inesperada del servidor" }));
  if (data.error) throw new Error(data.error);
  return data;
}

const postJson = (url, body) =>
  api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function formatRange(group) {
  const start = new Date(group.start);
  const end = new Date(group.end);
  const time = (d) => d.toTimeString().slice(0, 5);
  const date = start.toLocaleDateString("es-ES");
  return start.toDateString() === end.toDateString()
    ? `${date} · ${time(start)}–${time(end)}`
    : `${date} ${time(start)} → ${end.toLocaleDateString("es-ES")} ${time(end)}`;
}

function formatDelta(seconds) {
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${(minutes / 60).toFixed(1)} h`;
}

// ------------------------------------------------------------- Carpeta e índice

el("pick-root-btn").addEventListener("click", async () => {
  const data = await postJson("/api/pick-folder", { path: el("root-input").value });
  if (data.canceled || !data.path) return;
  el("root-input").value = data.path;
});

el("pick-reference-btn").addEventListener("click", async () => {
  const data = await postJson("/api/pick-folder", { path: el("reference-folder").value });
  if (data.canceled || !data.path) return;
  el("reference-folder").value = data.path;
});

el("pick-gpx-btn").addEventListener("click", async () => {
  const data = await postJson("/api/ubicacion/pick-gpx", {});
  if (data.canceled || !data.path) return;
  el("gpx-path").value = data.path;
});

async function loadGroups() {
  el("folder-status").textContent = "Cargando…";
  try {
    const data = await postJson("/api/ubicacion/groups", {
      root: el("root-input").value.trim(),
      gap_minutes: parseInt(el("gap-input").value, 10) || 60,
    });
    root = data.root;
    localStorage.setItem(ROOT_KEY, root);
    el("root-input").value = root;
    groups = data.groups;
    selected.clear();

    const s = data.stats;
    el("index-stats").textContent = s.total
      ? `${s.total} archivos en el índice · ${s.with_gps} con ubicación · ${s.without_gps} sin ella`
      : "El índice está vacío. Pulsa «Buscar archivos nuevos» para construirlo.";
    el("folder-status").textContent = "";

    renderGroups();
    el("groups-section").classList.remove("hidden");
    el("match-section").classList.remove("hidden");
    el("map-section").classList.remove("hidden");
    ensureMap();
  } catch (err) {
    el("folder-status").textContent = err.message;
  }
}

el("load-btn").addEventListener("click", loadGroups);
el("gap-input").addEventListener("change", () => { if (root) loadGroups(); });

async function runReindex(full) {
  el("reindex-status").textContent = "Indexando…";
  try {
    const { job_id } = await postJson("/api/ubicacion/reindex", {
      root: el("root-input").value.trim(), full,
    });
    await pollReindex(job_id);
  } catch (err) {
    el("reindex-status").textContent = err.message;
  }
}

async function pollReindex(jobId) {
  const job = await api(`/api/ubicacion/assign-status/${jobId}`);
  if (job.state === "en_curso") {
    el("reindex-status").textContent = job.total
      ? `Leyendo metadatos… ${job.done}/${job.total}`
      : "Buscando archivos…";
    setTimeout(() => pollReindex(jobId), 600);
    return;
  }
  if (job.state === "error") {
    el("reindex-status").textContent = job.errors.join(" · ");
    return;
  }
  el("reindex-status").textContent = `Índice actualizado (${job.added} archivos nuevos).`;
  loadGroups();
}

el("reindex-btn").addEventListener("click", () => runReindex(false));
el("reindex-full-btn").addEventListener("click", () => runReindex(true));

// ------------------------------------------------------------------- Sesiones

function visibleGroups() {
  const filter = el("group-filter").value;
  return groups.filter((g) => {
    if (filter === "missing") return g.without_gps > 0;
    if (filter === "located") return g.without_gps === 0;
    return true;
  });
}

function renderGroups() {
  const list = el("groups-list");
  list.innerHTML = "";
  const shown = visibleGroups();

  for (const group of shown) {
    list.appendChild(renderGroup(group));
  }

  const missing = groups.filter((g) => g.without_gps > 0).length;
  el("groups-summary").textContent =
    `${groups.length} sesiones · ${missing} con archivos sin ubicar · mostrando ${shown.length}`;
  updateSelectionSummary();
  drawGroupMarkers();
}

function renderGroup(group) {
  const card = document.createElement("div");
  card.className = "group-card" + (group.without_gps === 0 ? " located" : "");
  card.dataset.id = group.id;

  const head = document.createElement("div");
  head.className = "group-head";

  const check = document.createElement("input");
  check.type = "checkbox";
  check.checked = selected.has(group.id);
  check.addEventListener("change", () => {
    if (check.checked) selected.add(group.id); else selected.delete(group.id);
    card.classList.toggle("selected", check.checked);
    updateSelectionSummary();
  });

  const title = document.createElement("div");
  const range = document.createElement("strong");
  range.textContent = formatRange(group);
  const counts = document.createElement("div");
  counts.className = "muted";
  counts.textContent = `${group.count} archivos · ${group.with_gps} con ubicación · ${group.without_gps} sin ella`;
  title.append(range, counts);

  if (group.unwritable) {
    const blocked = document.createElement("div");
    blocked.className = "blocked-note";
    blocked.textContent = group.unwritable === 1
      ? "⚠ 1 clip AVCHD (.MTS) no admite guardar la ubicación dentro del archivo. " +
        "Conviértelo a MP4 en Conversión y vuelve aquí."
      : `⚠ ${group.unwritable} clips AVCHD (.MTS) no admiten guardar la ubicación dentro del ` +
        "archivo. Conviértelos a MP4 en Conversión y vuelve aquí.";
    title.appendChild(blocked);
  }

  head.append(check, title);

  if (group.place) {
    const place = document.createElement("span");
    place.className = "tag place-tag";
    place.textContent = group.place;
    head.appendChild(place);
  } else if (group.center) {
    const coords = document.createElement("span");
    coords.className = "tag";
    coords.textContent = `${group.center[0].toFixed(4)}, ${group.center[1].toFixed(4)}`;
    head.appendChild(coords);
  }

  card.appendChild(head);
  card.classList.toggle("selected", check.checked);

  if (group.suggestion) {
    card.appendChild(renderSuggestion(group));
  }

  const strip = document.createElement("div");
  strip.className = "thumb-strip";
  // Se muestran unas pocas por sesión: es para reconocer dónde se tomó, no para revisarlas.
  for (const file of group.files.slice(0, 8)) {
    const thumb = document.createElement("div");
    thumb.className = "strip-thumb" + (file.gps ? "" : " nogps");
    thumb.title = file.relative;
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = file.relative;
    img.addEventListener("error", () => thumb.classList.add("failed"));
    img.src = `/api/importacion/thumb?path=${encodeURIComponent(root + "/" + file.relative)}`;
    thumb.appendChild(img);
    strip.appendChild(thumb);
  }
  if (group.files.length > 8) {
    const more = document.createElement("span");
    more.className = "muted";
    more.textContent = `+${group.files.length - 8} más`;
    strip.appendChild(more);
  }
  card.appendChild(strip);

  return card;
}

function renderSuggestion(group) {
  const box = document.createElement("div");
  box.className = "suggestion";
  const s = group.suggestion;

  const text = document.createElement("span");
  text.textContent =
    `Propuesta: ${s.gps[0].toFixed(5)}, ${s.gps[1].toFixed(5)} — de ${s.label} ` +
    `(${s.origin}), con ${formatDelta(s.delta_seconds)} de diferencia`;
  if (s.distance_m != null && s.distance_m > 500) {
    const warn = document.createElement("span");
    warn.className = "suggestion-warn";
    warn.textContent = ` · ojo: está a ${(s.distance_m / 1000).toFixed(1)} km de las fotos que sí tienen GPS en esta sesión`;
    text.appendChild(warn);
  }

  const use = document.createElement("button");
  use.type = "button";
  use.textContent = "Usar esta";
  use.addEventListener("click", () => {
    // El nombre del lugar se resuelve por geocodificación inversa; de dónde salió la
    // posición es otra cosa y se guarda como origen, no como nombre del sitio.
    setChosen(s.gps, "", s.origin === "gpx" ? "gpx" : "referencia");
    if (!selected.has(group.id)) {
      selected.add(group.id);
      renderGroups();
    }
  });

  box.append(text, use);
  return box;
}

function updateSelectionSummary() {
  const chosenGroups = groups.filter((g) => selected.has(g.id));
  const files = chosenGroups.reduce((n, g) => n + g.without_gps, 0);
  const total = chosenGroups.reduce((n, g) => n + g.count, 0);
  el("selection-summary").textContent = chosenGroups.length
    ? `${chosenGroups.length} sesiones marcadas · ${files} archivos sin ubicar (de ${total})`
    : "Ninguna sesión marcada.";
}

el("group-filter").addEventListener("change", renderGroups);

el("select-all-btn").addEventListener("click", () => {
  visibleGroups().forEach((g) => selected.add(g.id));
  renderGroups();
});

el("select-none-btn").addEventListener("click", () => {
  selected.clear();
  renderGroups();
});

// -------------------------------------------------------------- Coincidencias

el("match-btn").addEventListener("click", async () => {
  el("match-status").textContent = "Buscando…";
  el("match-btn").disabled = true;
  try {
    const data = await postJson("/api/ubicacion/match", {
      root,
      gap_minutes: parseInt(el("gap-input").value, 10) || 60,
      tolerance_minutes: parseInt(el("tolerance-input").value, 10) || 20,
      use_index: el("use-index").checked,
      reference_folder: el("reference-folder").value.trim(),
      gpx_path: el("gpx-path").value.trim(),
      utc_offset: parseFloat(el("utc-offset").value),
    });
    groups = data.groups;
    renderGroups();
    el("match-status").textContent = data.references
      ? `${data.matched} sesiones con propuesta, a partir de ${data.used.join(" y ")}.`
      : "No se ha encontrado ninguna referencia con GPS.";
  } catch (err) {
    el("match-status").textContent = err.message;
  } finally {
    el("match-btn").disabled = false;
  }
});

// --------------------------------------------------------------------- Mapa

function ensureMap() {
  if (map) {
    map.invalidateSize();
    return;
  }
  map = L.map("map").setView([40.4168, -3.7038], 5);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© colaboradores de OpenStreetMap",
  }).addTo(map);
  groupLayer = L.layerGroup().addTo(map);
  map.on("click", (event) => setChosen([event.latlng.lat, event.latlng.lng], ""));
  drawGroupMarkers();
}

// Marcadores dibujados con CSS en vez de las imágenes por defecto de Leaflet, que
// tendrían que descargarse aparte.
const dotIcon = (className) => L.divIcon({ className: `map-dot ${className}`, iconSize: [14, 14] });

function drawGroupMarkers() {
  if (!groupLayer) return;
  groupLayer.clearLayers();
  const points = [];
  for (const group of groups) {
    if (!group.center) continue;
    L.marker(group.center, { icon: dotIcon(selected.has(group.id) ? "sel" : "") })
      .bindTooltip(`${formatRange(group)} (${group.count})`)
      .addTo(groupLayer);
    points.push(group.center);
  }
  if (points.length && !chosen) map.fitBounds(points, { padding: [30, 30], maxZoom: 14 });
}

const SOURCE_LABELS = {
  manual: "elegida en el mapa",
  referencia: "deducida de una foto con GPS",
  gpx: "deducida de un track GPX",
};

function describeChosen() {
  const { gps, place, source } = chosen;
  return `Posición elegida: ${gps[0].toFixed(5)}, ${gps[1].toFixed(5)}` +
    (place ? ` — ${place}` : "") +
    ` · ${SOURCE_LABELS[source] || source}`;
}

function setChosen(gps, place, source = "manual") {
  chosen = { gps, place, source };
  ensureMap();
  if (marker) marker.remove();
  marker = L.marker(gps, { icon: dotIcon("chosen") }).addTo(map);
  map.setView(gps, Math.max(map.getZoom(), 13));
  el("chosen-place").textContent = describeChosen();

  if (!place) nameChosen(gps);
}

async function nameChosen(gps) {
  try {
    const data = await api(`/api/ubicacion/reverse?lat=${gps[0]}&lon=${gps[1]}`);
    if (data.name && chosen && chosen.gps === gps) {
      chosen.place = data.name;
      el("chosen-place").textContent = describeChosen();
    }
  } catch {
    // El nombre del sitio es un extra: sin internet se sigue pudiendo asignar por coordenadas.
  }
}

el("search-btn").addEventListener("click", doSearch);
el("place-search").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });

async function doSearch() {
  const query = el("place-search").value.trim();
  if (!query) return;
  el("search-status").textContent = "Buscando…";
  const list = el("search-results");
  list.innerHTML = "";
  try {
    const data = await api(`/api/ubicacion/search?q=${encodeURIComponent(query)}`);
    el("search-status").textContent = data.results.length ? "" : "Sin resultados.";
    for (const result of data.results) {
      const li = document.createElement("li");
      li.textContent = result.name;
      li.addEventListener("click", () => {
        setChosen(result.gps, result.name, "manual");
        list.innerHTML = "";
        el("place-search").value = result.name;
      });
      list.appendChild(li);
    }
  } catch (err) {
    el("search-status").textContent = err.message;
  }
}

// ------------------------------------------------------------------- Asignar

function selectedFiles(onlyMissing = true) {
  const files = [];
  for (const group of groups) {
    if (!selected.has(group.id)) continue;
    for (const file of group.files) {
      if (onlyMissing && file.gps) continue;
      // Los AVCHD se descartan aquí en vez de dejar que fallen uno a uno en el job.
      if (onlyMissing && file.writable === false) continue;
      files.push(file.relative);
    }
  }
  return files;
}

function selectedUnwritable() {
  return groups
    .filter((g) => selected.has(g.id))
    .reduce((n, g) => n + (g.unwritable || 0), 0);
}

el("assign-btn").addEventListener("click", async () => {
  if (!chosen) {
    el("assign-status").textContent = "Elige antes una posición en el mapa o con el buscador.";
    return;
  }
  const relatives = selectedFiles(true);
  const blocked = selectedUnwritable();
  if (!relatives.length) {
    el("assign-status").textContent = blocked
      ? (blocked === 1
          ? "El único archivo sin ubicar de esta selección es un AVCHD (.MTS), que no admite "
          : `Los ${blocked} archivos sin ubicar de esta selección son AVCHD (.MTS), que no admiten `) +
        "guardar la ubicación dentro. Conviértelo" + (blocked === 1 ? "" : "s") +
        " a MP4 en Conversión primero."
      : "No hay archivos sin ubicar en las sesiones marcadas.";
    return;
  }

  const backup = el("backup-originals").checked;
  const message =
    `Se va a escribir la ubicación dentro de ${relatives.length} archivo(s).\n\n` +
    (blocked ? `Se omiten ${blocked} clip(s) AVCHD que no lo admiten.\n\n` : "") +
    (backup
      ? "Se guardará una copia del original en _originales_sin_gps/ antes de tocarlos."
      : "SIN copia de seguridad: los archivos se modifican de forma irreversible.") +
    "\n\n¿Continuar?";
  if (!confirm(message)) return;

  el("assign-btn").disabled = true;
  el("assign-errors").innerHTML = "";
  el("assign-bar").classList.remove("hidden");
  try {
    const data = await postJson("/api/ubicacion/assign", {
      root, relatives, gps: chosen.gps, place: chosen.place, source: chosen.source, backup,
    });
    pollAssign(data.job_id);
  } catch (err) {
    el("assign-status").textContent = err.message;
    el("assign-btn").disabled = false;
  }
});

async function pollAssign(jobId) {
  let job;
  try {
    job = await api(`/api/ubicacion/assign-status/${jobId}`);
  } catch (err) {
    el("assign-status").textContent = err.message;
    el("assign-btn").disabled = false;
    return;
  }

  el("assign-bar").value = job.total ? job.done / job.total : 0;
  el("assign-status").textContent = `${job.done}/${job.total}${job.current ? ` — ${job.current}` : ""}`;

  if (job.state !== "finalizado") {
    setTimeout(() => pollAssign(jobId), 500);
    return;
  }

  el("assign-status").textContent =
    `Terminado: ${job.written} archivos con ubicación escrita, ${job.errors.length} con error.`;
  for (const message of job.errors) {
    const li = document.createElement("li");
    li.textContent = message;
    el("assign-errors").appendChild(li);
  }
  el("assign-btn").disabled = false;
  el("assign-bar").classList.add("hidden");
  loadGroups();
}

el("restore-btn").addEventListener("click", async () => {
  const relatives = selectedFiles(false);
  if (!relatives.length) {
    el("assign-status").textContent = "No hay ninguna sesión marcada.";
    return;
  }
  if (!confirm(`Se restaurará el archivo original (sin ubicación) de ${relatives.length} archivo(s). ¿Continuar?`)) return;

  try {
    const data = await postJson("/api/ubicacion/restore", { root, relatives });
    el("assign-status").textContent =
      `Restaurados ${data.restored} de ${data.total} (solo los que tenían copia de seguridad).`;
    loadGroups();
  } catch (err) {
    el("assign-status").textContent = err.message;
  }
});

// ------------------------------------------------------------------ Arranque

(async () => {
  const remembered = localStorage.getItem(ROOT_KEY);
  if (remembered) {
    el("root-input").value = remembered;
  } else {
    try {
      const config = await api("/api/importacion/config");
      el("root-input").value = config.destination;
    } catch {
      // Sin configuración todavía: el usuario elige la carpeta a mano.
    }
  }
})();
