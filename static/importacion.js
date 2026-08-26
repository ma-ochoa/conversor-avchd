const el = (id) => document.getElementById(id);

const sourceList = el("source-list");
const sourceStatus = el("source-status");
const camerasBox = el("cameras");
const previewGrid = el("preview-grid");
const progressBody = document.querySelector("#progress-table tbody");

let scanId = null;
let scan = null;
let selectedSource = null;
let previewShown = 0;

const PREVIEW_PAGE = 60;

function formatBytes(bytes) {
  if (bytes == null) return "—";
  const gb = bytes / 1e9;
  if (gb >= 1) return gb.toFixed(2) + " GB";
  return (bytes / 1e6).toFixed(1) + " MB";
}

function formatDay(day) {
  const [y, m, d] = day.split("-");
  return `${d}/${m}/${y}`;
}

async function api(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({ error: "Respuesta inesperada del servidor" }));
  if (data.error) throw new Error(data.error);
  return data;
}

async function postJson(url, body) {
  return api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ------------------------------------------------------------------- Origen

function renderSources(sources) {
  sourceList.innerHTML = "";
  el("source-empty").classList.toggle("hidden", sources.length > 0);

  for (const source of sources) {
    const li = document.createElement("li");
    li.dataset.path = source.path;

    const icon = document.createElement("span");
    icon.className = "source-icon";
    icon.textContent = source.is_card ? "💳" : source.kind === "carpeta" ? "📁" : "💽";

    const box = document.createElement("div");
    const name = document.createElement("div");
    name.className = "source-name";
    name.textContent = source.label;
    const meta = document.createElement("div");
    meta.className = "source-meta";
    const bits = [source.path];
    if (source.is_card) bits.push("estructura de tarjeta");
    if (source.parent) bits.push(`en ${source.parent}`);
    if (source.total_bytes) bits.push(`${formatBytes(source.total_bytes)} totales`);
    meta.textContent = bits.join(" · ");
    box.append(name, meta);

    li.append(icon, box);
    li.addEventListener("click", () => selectSource(source.path, li));
    sourceList.appendChild(li);
  }
}

async function detectSources(retry) {
  sourceStatus.textContent = "Buscando…";
  try {
    const data = await api(`/api/importacion/sources${retry ? "?retry=1" : ""}`);
    renderSources(data.sources);
    sourceStatus.textContent = data.sources.length ? "" : "Nada detectado.";
    renderBlockedWarning(data.blocked_folders);
    renderPhones();
    renderPendingDownloads();
  } catch (err) {
    sourceStatus.textContent = err.message;
  }
}

// Lo descargado del móvil espera en una carpeta oculta hasta que se importa. Si no se
// avisa, esos archivos desaparecen de la vista y el usuario no sabe dónde han ido.
async function renderPendingDownloads() {
  const box = el("pending-downloads");
  let downloads = [];
  try {
    downloads = (await api("/api/importacion/mtp/pending")).downloads;
  } catch {
    return;
  }
  if (!downloads.length) {
    box.classList.add("hidden");
    return;
  }

  box.innerHTML = "";
  box.classList.remove("hidden");

  const total = downloads.reduce((n, d) => n + d.files, 0);
  const bytes = downloads.reduce((n, d) => n + d.bytes, 0);

  const title = document.createElement("div");
  title.innerHTML =
    `📥 <strong>${total} archivos descargados del móvil (${formatBytes(bytes)}) todavía sin importar.</strong>`;
  box.appendChild(title);

  const text = document.createElement("p");
  text.className = "muted";
  text.textContent =
    "Están guardados a la espera de que completes la importación: elige la carpeta de " +
    "destino, revisa el plan y pulsa «Importar». Hasta entonces no se organizan ni se " +
    "copian a tu fototeca.";
  box.appendChild(text);

  for (const download of downloads) {
    const row = document.createElement("div");
    row.className = "pending-row";

    const label = document.createElement("span");
    label.textContent = `${download.name} — ${download.files} archivos, ${formatBytes(download.bytes)}` +
      (download.partial ? ` (+${download.partial} incompleto por una descarga cortada)` : "");
    row.appendChild(label);

    const use = document.createElement("button");
    use.className = "primary";
    use.textContent = "Continuar la importación";
    use.addEventListener("click", () => selectSource(download.path, null));
    row.appendChild(use);

    const drop = document.createElement("button");
    drop.textContent = "Descartar";
    drop.addEventListener("click", async () => {
      if (!confirm(
        `Se borrarán ${download.files} archivos descargados de «${download.name}».\n\n` +
        "Siguen estando en el móvil, así que podrás volver a bajarlos. ¿Continuar?")) return;
      await postJson("/api/importacion/mtp/cleanup", { path: download.path });
      renderPendingDownloads();
    });
    row.appendChild(drop);

    box.appendChild(row);
  }
}

function offerCleanupDownload(path, copied) {
  const box = el("pending-downloads");
  box.innerHTML = "";
  box.classList.remove("hidden");

  const text = document.createElement("div");
  text.innerHTML =
    `✅ <strong>${copied} archivos ya están en tu fototeca.</strong> La copia intermedia de ` +
    "la descarga del móvil ya no hace falta.";
  box.appendChild(text);

  const row = document.createElement("div");
  row.className = "pending-row";

  const drop = document.createElement("button");
  drop.className = "primary";
  drop.textContent = "Liberar ese espacio";
  drop.addEventListener("click", async () => {
    try {
      await postJson("/api/importacion/mtp/cleanup", { path });
      renderPendingDownloads();
    } catch (err) {
      sourceStatus.textContent = err.message;
    }
  });
  row.appendChild(drop);

  const keep = document.createElement("button");
  keep.textContent = "Conservarla";
  keep.addEventListener("click", () => renderPendingDownloads());
  row.appendChild(keep);

  box.appendChild(row);
}

async function renderPhones() {
  const box = el("phone-notice");
  let data = { phones: [], readable: [], mtp_available: false };
  try {
    data = await api("/api/importacion/phones");
  } catch {
    // La detección de móviles es un extra: si falla, no debe estropear la de tarjetas.
  }
  const phones = data.phones || [];
  if (!phones.length) {
    box.classList.add("hidden");
    return;
  }

  box.innerHTML = "";
  box.classList.remove("hidden");

  const title = document.createElement("div");
  title.innerHTML = `📱 <strong>${phones.map((p) => p.label).join(", ")}</strong> conectado` +
    (phones.length > 1 ? "s" : "") + " por USB.";
  box.appendChild(title);

  const text = document.createElement("p");
  text.className = "muted";
  text.textContent =
    "Los móviles no se conectan como disco, sino por MTP/PTP, así que no aparecen en el " +
    "Finder ni se pueden leer directamente desde aquí. Vuelca las fotos con Captura de " +
    "Imagen a una carpeta y esa carpeta se detectará aquí como si fuera una tarjeta.";
  box.appendChild(text);

  // Si se puede abrir por MTP, el camino bueno es explorar sus carpetas desde aquí.
  if (data.readable && data.readable.length) {
    text.textContent =
      "Se pueden leer sus carpetas: entra en DCIM/Camera para las fotos de la cámara del " +
      "móvil, y deja fuera lo descargado de Telegram o WhatsApp.";
    const explore = document.createElement("button");
    explore.className = "primary";
    explore.textContent = "Explorar el móvil";
    explore.addEventListener("click", () => {
      el("mtp-browser").classList.remove("hidden");
      browseMtp("/");
    });
    box.appendChild(explore);
    return;
  }

  const detail = document.createElement("p");
  detail.className = "hint warn";
  detail.textContent = data.mtp_available
    ? "Ahora mismo no se puede leer. Casi siempre es porque el móvil está en modo " +
      "«Transferencia de imágenes (PTP)»: cámbialo a «Transferencia de archivos (MTP)» " +
      "en la notificación USB del móvil, que además es el único modo que muestra carpetas."
    : "Para leer las carpetas del móvil hace falta gphoto2:  brew install libgphoto2  y  " +
      "pip install gphoto2. Mientras tanto, puedes volcar con Captura de Imagen.";
  box.appendChild(detail);

  const button = document.createElement("button");
  button.textContent = "Abrir Captura de Imagen";
  button.addEventListener("click", async () => {
    try {
      const result = await postJson("/api/importacion/open-transfer-app", { kind: phones[0].kind });
      sourceStatus.textContent = result.message;
    } catch (err) {
      sourceStatus.textContent = err.message;
    }
  });
  box.appendChild(button);
}

// ---------------------------------------------------- Explorador del móvil (MTP)
//
// El móvil es un origen más: se elige una carpeta y, a partir de ahí, el flujo es
// idéntico al de una tarjeta. No hay descarga previa a ninguna carpeta intermedia — los
// archivos se bajan directamente a su destino final cuando se pulsa «Importar».

let mtpPath = "/";

async function browseMtp(path) {
  el("mtp-status").textContent = "";
  el("mtp-path").textContent = "Leyendo…";
  try {
    const data = await postJson("/api/importacion/mtp/folder", { path });
    mtpPath = data.path;
    el("mtp-path").textContent = mtpPath;
    el("mtp-up-btn").disabled = mtpPath === "/";

    const list = el("mtp-list");
    list.innerHTML = "";
    for (const folder of data.folders) {
      const li = document.createElement("li");
      li.textContent = (folder.interesting ? "⭐ " : "📁 ") + folder.name;
      li.addEventListener("click", () => browseMtp(folder.path));
      list.appendChild(li);
    }
    if (!data.folders.length) {
      list.innerHTML = "<li class='muted'>No hay subcarpetas aquí.</li>";
    }
  } catch (err) {
    el("mtp-path").textContent = mtpPath;
    el("mtp-status").textContent = err.message;
  }
}

el("mtp-up-btn").addEventListener("click", () => browseMtp(
  mtpPath.includes("/") && mtpPath !== "/" ? (mtpPath.slice(0, mtpPath.lastIndexOf("/")) || "/") : "/"
));

el("mtp-close-btn").addEventListener("click", () => {
  el("mtp-browser").classList.add("hidden");
});

el("mtp-use-btn").addEventListener("click", async () => {
  el("mtp-status").textContent =
    "Leyendo el móvil… en una carpeta con miles de fotos esto tarda unos segundos.";
  el("mtp-use-btn").disabled = true;
  try {
    // El prefijo mtp:// distingue un origen del móvil de una ruta de disco.
    await selectSource("mtp://" + mtpPath, null);
    el("mtp-browser").classList.add("hidden");
    el("mtp-status").textContent = "";
  } catch (err) {
    el("mtp-status").textContent = err.message;
  } finally {
    el("mtp-use-btn").disabled = false;
  }
});

function renderBlockedWarning(blocked) {
  const box = el("blocked-warning");
  if (!blocked || blocked.length === 0) {
    box.classList.add("hidden");
    return;
  }
  box.textContent =
    `macOS todavía no deja leer ${blocked.join(" ni ")}. Concede el permiso en Ajustes del Sistema → ` +
    `Privacidad y seguridad → Archivos y carpetas (o Acceso total al disco) para la app desde la que ` +
    `arrancas el conversor, y vuelve a pulsar «Detectar tarjetas». Mientras tanto, «Elegir una carpeta…» ` +
    `sí funciona con cualquier carpeta.`;
  box.classList.remove("hidden");
}

async function selectSource(path, li) {
  selectedSource = path;
  document.querySelectorAll("#source-list li").forEach((n) => n.classList.remove("selected"));
  if (li) li.classList.add("selected");

  sourceStatus.textContent = "Leyendo metadatos del origen…";
  try {
    const data = await postJson("/api/importacion/scan", { path });
    scanId = data.scan_id;
    scan = data;
    sourceStatus.textContent = "";
    renderScan(data);
  } catch (err) {
    sourceStatus.textContent = err.message;
  }
}

el("detect-btn").addEventListener("click", () => detectSources(true));

el("pick-source-btn").addEventListener("click", async () => {
  const data = await postJson("/api/pick-folder", {});
  if (data.canceled || !data.path) return;
  renderSources([{ path: data.path, label: data.path.split("/").filter(Boolean).pop() || data.path,
                   kind: "carpeta", is_card: false, parent: null, total_bytes: null }]);
  selectSource(data.path, sourceList.firstElementChild);
});

// -------------------------------------------------------- Contenido y cámaras

function renderScan(data) {
  const t = data.totals;
  el("scan-summary").textContent =
    `${t.files} archivos · ${t.jpg} JPG · ${t.raw} RAW · ${t.video} vídeos · ${formatBytes(t.bytes)}` +
    ` · ${t.with_gps} con ubicación, ${t.without_gps} sin ella` +
    (t.duplicates ? ` · ${t.duplicates} ya importados antes` : "");

  camerasBox.innerHTML = "";
  for (const camera of data.cameras) {
    camerasBox.appendChild(renderCamera(camera));
  }

  setupRangeFilter(data.cameras);

  el("content-section").classList.remove("hidden");
  el("preview-section").classList.remove("hidden");
  el("options-section").classList.remove("hidden");
  el("plan-result").classList.add("hidden");

  fillDaySelector(data.cameras);
  applyPreviewFilters();
  updateSpaceInfo(data.free_bytes, t.bytes);
}

// La carpeta de fotos de un móvil abarca meses: marcar 255 días a mano no es viable, así
// que se ofrece marcar por rango. Con pocos días la lista se maneja sola y no aparece.
const RANGE_FILTER_FROM_DAYS = 8;

function setupRangeFilter(cameras) {
  const days = cameras.flatMap((c) => c.days.map((d) => d.date)).sort();
  const box = el("range-filter");
  box.classList.toggle("hidden", days.length < RANGE_FILTER_FROM_DAYS);
  if (days.length < RANGE_FILTER_FROM_DAYS) return;

  el("range-from").value = days[0];
  el("range-to").value = days[days.length - 1];
  // Sin `max`: acotarlo a la última foto deja inservible el botón «Hoy» del calendario
  // del navegador en cuanto el material no llega hasta hoy mismo.
  el("range-from").min = el("range-to").min = days[0];
  el("range-from").removeAttribute("max");
  el("range-to").removeAttribute("max");
  applyRange(true);
}

function applyRange(check) {
  const from = el("range-from").value;
  const to = el("range-to").value;
  for (const row of document.querySelectorAll(".day-row")) {
    const day = row.dataset.day;
    const dentro = (!from || day >= from) && (!to || day <= to);
    row.querySelector(".day-include").checked = check ? dentro : false;
    // Además de desmarcarlos, se ocultan: con 255 días, dejar en pantalla los que
    // quedan fuera del rango hace imposible ver qué se va a importar de verdad.
    row.classList.toggle("hidden", !dentro);
  }
  // Una cámara sin ningún día dentro del rango tampoco pinta nada.
  for (const card of document.querySelectorAll(".camera-card")) {
    const visibles = card.querySelectorAll(".day-row:not(.hidden)").length;
    card.classList.toggle("hidden", visibles === 0);
  }
  el("plan-result").classList.add("hidden");
  updateRangeSummary();
  // La vista rápida enseña lo que se va a importar, así que sigue al rango.
  if (scan) {
    fillDaySelector(scan.cameras);
    applyPreviewFilters();
  }
}

function updateRangeSummary() {
  const rows = Array.from(document.querySelectorAll(".day-row"));
  const visibles = rows.filter((r) => !r.classList.contains("hidden"));
  const marcados = rows.filter((r) => r.querySelector(".day-include").checked);
  const fuera = rows.length - visibles.length;
  el("range-summary").textContent =
    `${marcados.length} días marcados` +
    (fuera ? ` · ${fuera} fuera del rango, ocultos` : ` de ${rows.length}`) + ".";
}

for (const id of ["range-from", "range-to"]) {
  el(id).addEventListener("change", () => applyRange(true));
}
// «Todos» devuelve el rango a su extensión completa, en vez de marcar por lo bajo días
// que están ocultos: marcar lo que no se ve es justo lo que hay que evitar aquí.
el("range-all-btn").addEventListener("click", () => {
  const days = allDays();
  if (!days.length) return;
  el("range-from").value = days[0];
  el("range-to").value = days[days.length - 1];
  applyRange(true);
});

// «Ninguno» desmarca solo lo visible; lo que está fuera del rango ya estaba desmarcado.
el("range-none-btn").addEventListener("click", () => {
  document.querySelectorAll(".day-row:not(.hidden) .day-include")
    .forEach((c) => { c.checked = false; });
  el("plan-result").classList.add("hidden");
  updateRangeSummary();
});

function allDays() {
  return Array.from(document.querySelectorAll(".day-row"))
    .map((r) => r.dataset.day).sort();
}

function renderCamera(camera) {
  const card = document.createElement("div");
  card.className = "camera-card";
  card.dataset.key = camera.key;

  const head = document.createElement("div");
  head.className = "camera-head";

  const label = document.createElement("strong");
  label.textContent = "Carpeta de la cámara:";

  const input = document.createElement("input");
  input.type = "text";
  input.className = "camera-folder";
  input.value = camera.folder || camera.suggested;
  input.addEventListener("input", () => el("plan-result").classList.add("hidden"));

  const model = document.createElement("span");
  model.className = "camera-model";
  if (camera.key) {
    // El modelo EXIF a menudo ya incluye la marca ("Canon PowerShot G5 X"): repetirla daría
    // "Canon Canon PowerShot G5 X".
    const label = camera.model.toLowerCase().startsWith(camera.make.toLowerCase())
      ? camera.model
      : `${camera.make} ${camera.model}`.trim();
    model.textContent = camera.known
      ? `${label} (recordada)`
      : `${label} — nueva, se recordará al importar`;
  } else {
    model.textContent = camera.hint
      ? `Sin modelo en los metadatos. Por la estructura de la tarjeta parece: ${camera.hint}`
      : "Sin modelo en los metadatos: confirma el nombre a mano.";
  }

  head.append(label, input, model);
  card.appendChild(head);

  const counts = document.createElement("p");
  counts.className = "muted";
  counts.textContent =
    `${camera.counts.jpg} JPG · ${camera.counts.raw} RAW · ${camera.counts.video} vídeos · ${formatBytes(camera.bytes)}`;
  card.appendChild(counts);

  for (const day of camera.days) {
    card.appendChild(renderDay(camera.key, day));
  }
  return card;
}

function renderDay(cameraKey, day) {
  const row = document.createElement("div");
  row.className = "day-row";
  row.dataset.day = day.date;
  row.dataset.cameraKey = cameraKey;

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "day-include";
  check.checked = true;
  check.addEventListener("change", () => {
    el("plan-result").classList.add("hidden");
    updateRangeSummary();
  });

  const label = document.createElement("button");
  label.type = "button";
  label.className = "day-label";
  label.textContent = formatDay(day.date);
  const counts = document.createElement("span");
  counts.className = "day-counts";
  counts.textContent = ` (${day.photos} fotos, ${day.videos} vídeos, ${formatBytes(day.bytes)})`;
  if (day.without_gps) {
    const noGps = document.createElement("span");
    noGps.className = "day-counts nogps";
    noGps.textContent = ` · ${day.without_gps} sin ubicación`;
    counts.appendChild(noGps);
  }
  label.appendChild(counts);
  // Pulsar el día lleva a la vista rápida ya filtrada por él, que es como se decide
  // qué nombre de evento ponerle.
  label.addEventListener("click", () => focusDay(`${cameraKey}|${day.date}`));

  const event = document.createElement("input");
  event.type = "text";
  event.className = "day-event";
  event.placeholder = "Nombre del evento para este día (opcional)";
  event.addEventListener("input", () => {
    el("plan-result").classList.add("hidden");
    if (el("preview-day").value === `${cameraKey}|${day.date}`) {
      el("event-inline-input").value = event.value;
    }
  });

  row.append(check, label, event);
  return row;
}

function dayRowFor(key) {
  return Array.from(document.querySelectorAll(".day-row"))
    .find((row) => `${row.dataset.cameraKey}|${row.dataset.day}` === key);
}

function focusDay(key) {
  el("preview-day").value = key;
  applyPreviewFilters();
  el("preview-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

function fillDaySelector(cameras) {
  const select = el("preview-day");
  const previous = select.value;
  const rangeActive = !el("range-filter").classList.contains("hidden");
  const from = rangeActive ? el("range-from").value : "";
  const to = rangeActive ? el("range-to").value : "";

  select.innerHTML = "";
  select.appendChild(new Option("Todos los días", "all"));
  for (const camera of cameras) {
    const name = camera.folder || camera.suggested || "Sin identificar";
    for (const day of camera.days) {
      // Fuera del rango no se ofrece: son días que no se van a importar.
      if ((from && day.date < from) || (to && day.date > to)) continue;
      const label = `${formatDay(day.date)} — ${name} (${day.photos + day.videos})`;
      select.appendChild(new Option(label, `${camera.key}|${day.date}`));
    }
  }
  // Si el día que estaba elegido ha quedado fuera del rango, se vuelve a "todos".
  select.value = Array.from(select.options).some((o) => o.value === previous) ? previous : "all";
}

function cameraFolders() {
  const folders = {};
  document.querySelectorAll(".camera-card").forEach((card) => {
    folders[card.dataset.key] = card.querySelector(".camera-folder").value.trim();
  });
  return folders;
}

function dayEvents() {
  const events = {};
  document.querySelectorAll(".day-row").forEach((row) => {
    const value = row.querySelector(".day-event").value.trim();
    if (value) events[`${row.dataset.cameraKey}|${row.dataset.day}`] = value;
  });
  return events;
}

function excludedDays() {
  return Array.from(document.querySelectorAll(".day-row"))
    .filter((row) => !row.querySelector(".day-include").checked)
    .map((row) => `${row.dataset.cameraKey}|${row.dataset.day}`);
}

// ------------------------------------------------------------- Vista previa

// Las miniaturas se piden solo cuando la celda entra en pantalla: una tarjeta puede
// tener miles de fotos y generarlas todas de golpe bloquearía la interfaz.
const thumbObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    const item = entry.target;
    thumbObserver.unobserve(item);
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = item.dataset.name;
    img.addEventListener("error", () => {
      img.remove();
      item.classList.add("failed");
    });
    img.src = `/api/importacion/thumb?path=${encodeURIComponent(item.dataset.path)}`;
    item.prepend(img);
  }
}, { rootMargin: "300px" });

function filteredFiles() {
  const kind = el("preview-filter").value;
  const day = el("preview-day").value;
  // La vista rápida sirve para decidir qué importar, así que tiene que enseñar lo mismo
  // que se va a importar: si el rango de fechas acota los días, aquí también.
  const rangeActive = !el("range-filter").classList.contains("hidden");
  const from = rangeActive ? el("range-from").value : "";
  const to = rangeActive ? el("range-to").value : "";

  return scan.files.filter((f) => {
    if (from && f.day < from) return false;
    if (to && f.day > to) return false;
    if (day !== "all" && `${f.camera_key}|${f.day}` !== day) return false;
    if (kind === "all") return true;
    if (kind === "nogps") return !f.gps;
    return f.category === kind;
  });
}

function showMorePreview() {
  const files = filteredFiles();
  const slice = files.slice(previewShown, previewShown + PREVIEW_PAGE);

  for (const file of slice) {
    const item = document.createElement("div");
    item.className = "preview-item" + (file.duplicate ? " dup" : "");
    item.dataset.path = file.path;
    item.dataset.name = file.name;
    item.title = `${file.name}\n${file.capture_dt.replace("T", " ")}` +
      (file.gps ? `\n📍 ${file.gps[0].toFixed(5)}, ${file.gps[1].toFixed(5)}` : "\nSin ubicación GPS");

    const badge = document.createElement("span");
    badge.className = "preview-badge";
    badge.textContent = file.duplicate ? "ya importada" : file.category.toUpperCase();
    item.appendChild(badge);

    const gps = document.createElement("span");
    gps.className = "gps-badge" + (file.gps ? " has-gps" : " no-gps");
    gps.textContent = "📍";
    gps.setAttribute("aria-label", file.gps ? "Con ubicación GPS" : "Sin ubicación GPS");
    item.appendChild(gps);

    previewGrid.appendChild(item);
    thumbObserver.observe(item);
  }

  previewShown += slice.length;
  el("preview-count").textContent = `Mostrando ${previewShown} de ${files.length}`;
  el("preview-more").classList.toggle("hidden", previewShown >= files.length);
}

function applyPreviewFilters() {
  previewShown = 0;
  previewGrid.innerHTML = "";
  showMorePreview();

  const key = el("preview-day").value;
  const row = key === "all" ? null : dayRowFor(key);
  el("event-inline").classList.toggle("hidden", !row);
  if (row) {
    el("event-inline-day").textContent = formatDay(row.dataset.day);
    el("event-inline-input").value = row.querySelector(".day-event").value;
  }
}

el("preview-more").addEventListener("click", showMorePreview);
el("preview-filter").addEventListener("change", applyPreviewFilters);
el("preview-day").addEventListener("change", applyPreviewFilters);

// El campo de evento de la vista rápida y el de la lista de días son el mismo dato.
el("event-inline-input").addEventListener("input", () => {
  const row = dayRowFor(el("preview-day").value);
  if (!row) return;
  row.querySelector(".day-event").value = el("event-inline-input").value;
  el("plan-result").classList.add("hidden");
});

// -------------------------------------------------------- Destino y opciones

function updateSpaceInfo(free, needed) {
  if (free == null) {
    el("space-info").textContent = "";
    return;
  }
  const enough = needed == null || free >= needed;
  el("space-info").textContent =
    `Espacio libre en el destino: ${formatBytes(free)}` +
    (needed != null ? ` · hacen falta ${formatBytes(needed)}${enough ? "" : " — NO CABE"}` : "");
  el("space-info").style.color = enough ? "" : "var(--err)";
}

function currentOptions() {
  return {
    rename_by_date: el("opt-rename").checked,
    group_videos_by_day: el("opt-group-videos").checked,
    skip_duplicates: el("opt-skip-duplicates").checked,
    verify_checksum: el("opt-verify").checked,
    delete_after_import: el("opt-delete").checked,
    upload_to_nas: el("opt-upload").checked,
    excluded_days: excludedDays(),
  };
}

function planPayload() {
  return {
    scan_id: scanId,
    destination: el("destination-input").value.trim(),
    camera_folders: cameraFolders(),
    events: dayEvents(),
    options: currentOptions(),
  };
}

el("pick-dest-btn").addEventListener("click", async () => {
  const data = await postJson("/api/pick-folder", { path: el("destination-input").value });
  if (data.canceled || !data.path) return;
  el("destination-input").value = data.path;
  el("plan-result").classList.add("hidden");
});

el("opt-verify").addEventListener("change", () => {
  if (!el("opt-verify").checked && el("opt-delete").checked) {
    el("opt-delete").checked = false;
    el("plan-status").textContent =
      "Se ha desactivado el borrado del origen: sin verificación no se puede borrar con seguridad.";
  }
});

el("opt-delete").addEventListener("change", () => {
  if (el("opt-delete").checked) el("opt-verify").checked = true;
});

el("plan-btn").addEventListener("click", async () => {
  if (!scanId) return;
  el("plan-status").textContent = "Calculando…";
  try {
    const plan = await postJson("/api/importacion/plan", planPayload());
    const body = document.querySelector("#plan-table tbody");
    body.innerHTML = "";
    for (const node of plan.tree) {
      const tr = document.createElement("tr");
      const folder = document.createElement("td");
      folder.textContent = node.folder;
      const files = document.createElement("td");
      files.textContent = node.files;
      const size = document.createElement("td");
      size.textContent = formatBytes(node.bytes);
      tr.append(folder, files, size);
      body.appendChild(tr);
    }
    el("plan-totals").textContent =
      `${plan.totals.files} archivos · ${formatBytes(plan.totals.bytes)}` +
      (plan.totals.skipped_duplicates ? ` · ${plan.totals.skipped_duplicates} omitidos por duplicados` : "");
    updateSpaceInfo(plan.free_bytes, plan.totals.bytes);
    el("plan-result").classList.remove("hidden");
    el("plan-status").textContent = "";
  } catch (err) {
    el("plan-status").textContent = err.message;
  }
});

// ------------------------------------------------------------------ Importar

el("import-btn").addEventListener("click", async () => {
  if (!scanId) return;

  if (el("opt-delete").checked) {
    const confirmed = confirm(
      "Vas a BORRAR los archivos del origen después de copiarlos.\n\n" +
      "Solo se borrará lo que se haya copiado y verificado por checksum. " +
      "Aun así, es irreversible.\n\n¿Continuar?"
    );
    if (!confirmed) return;
  }

  el("import-btn").disabled = true;
  el("plan-status").textContent = "";
  try {
    const data = await postJson("/api/importacion/start", planPayload());
    trabajoEnCurso = true;
    el("progress-section").classList.remove("hidden");
    progressBody.innerHTML = "";
    rows.clear();
    pollJob(data.job_id);
  } catch (err) {
    el("plan-status").textContent = err.message;
    el("import-btn").disabled = false;
  }
});

const rows = new Map();

// Mientras corre una importación o una subida, «Subir pendientes» se queda en gris aunque
// haya archivos sin subir: lanzar una segunda subida en paralelo mandaría los mismos
// ficheros dos veces. La etiqueta de al lado explica por qué está desactivado.
let trabajoEnCurso = false;

// Cada cuántos sondeos (de 800 ms) se refresca el recuento de pendientes mientras hay un
// trabajo en curso. Antes solo se refrescaba al terminar, y durante toda la subida el
// panel seguía diciendo que no quedaba nada por subir.
const REFRESCO_PENDIENTES = 10;

const PHASE_LABELS = {
  copiando: "Copiando y verificando archivos…",
  borrando: "Borrando del origen lo ya verificado…",
  subiendo: "Enviando al NAS…",
  terminado: "Terminado",
};

function ensureRows(items) {
  for (const item of items) {
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    name.textContent = item.relative;
    const dest = document.createElement("td");
    dest.textContent = item.dest_relative;
    const status = document.createElement("td");
    const progTd = document.createElement("td");
    const bar = document.createElement("progress");
    bar.max = 1;
    bar.value = 0;
    progTd.appendChild(bar);
    tr.append(name, dest, status, progTd);
    progressBody.appendChild(tr);
    rows.set(item.path, { status, bar });
  }
}

async function pollJob(jobId, tick = 0) {
  let job;
  try {
    job = await api(`/api/importacion/status/${jobId}`);
  } catch (err) {
    el("job-summary").textContent = err.message;
    el("import-btn").disabled = false;
    trabajoEnCurso = false;
    loadHistory();
    return;
  }

  if (rows.size === 0) ensureRows(job.items);

  let copiado = 0;
  for (const item of job.items) {
    const row = rows.get(item.path);
    if (!row) continue;
    row.status.textContent = item.status + (item.error ? `: ${item.error}` : "");
    row.bar.value = item.percent;
    copiado += item.percent;
  }

  // Durante la subida la barra general pasa a medir la subida. Dejándola con el progreso
  // de la copia se quedaba clavada al 100 % durante todos los minutos que tarda el envío,
  // y parecía que la importación se había colgado o que no estaba subiendo nada.
  const subiendo = job.phase === "subiendo" && job.upload.total > 0;
  el("overall-bar").value = subiendo
    ? job.upload.done / job.upload.total
    : (job.items.length ? copiado / job.items.length : 0);

  let phase = PHASE_LABELS[job.phase] || job.phase;
  if (subiendo) {
    phase += ` (${job.upload.done}/${job.upload.total})`;
    if (job.upload.current) phase += ` — ${job.upload.current}`;
  }
  el("phase-label").textContent = phase;

  if (job.state === "finalizado") {
    const s = job.summary;
    let text = `Terminado: ${s.copied} archivos copiados (${formatBytes(s.bytes)}), ${s.errors} con error`;
    if (s.deleted) text += `, ${s.deleted} borrados del origen`;
    if (job.upload.enabled) {
      text += job.upload.state === "completado"
        ? ", subida al NAS completada"
        : `, subida al NAS: ${job.upload.error || job.upload.state}`;
    }
    el("job-summary").textContent = text + ".";

    // Si lo importado venía de una descarga del móvil, esa copia intermedia ya no hace
    // falta: se ofrece liberarla en vez de dejar los archivos duplicados en una carpeta
    // oculta.
    if (selectedSource && selectedSource.includes("/descargas-movil/") && s.copied && !s.errors) {
      offerCleanupDownload(selectedSource, s.copied);
    }

    const warnings = el("job-warnings");
    warnings.innerHTML = "";
    for (const message of job.delete_errors) {
      const li = document.createElement("li");
      li.textContent = message;
      warnings.appendChild(li);
    }

    el("import-btn").disabled = false;
    trabajoEnCurso = false;
    loadHistory();
    return;
  }

  if (tick % REFRESCO_PENDIENTES === 0) loadHistory();
  setTimeout(() => pollJob(jobId, tick + 1), 800);
}

// ---------------------------------------------------------------------- NAS

function fillNasForm(config) {
  el("destination-input").value = config.destination;
  el("opt-rename").checked = config.rename_by_date;
  el("opt-group-videos").checked = config.group_videos_by_day;
  el("opt-skip-duplicates").checked = config.skip_duplicates;
  el("opt-verify").checked = config.verify_checksum;

  const nas = config.nas;
  el("nas-method").value = nas.method;
  el("nas-host").value = nas.host;
  el("nas-port").value = nas.port || "";
  el("nas-user").value = nas.user;
  el("nas-root").value = nas.remote_root;
  el("nas-https").checked = nas.use_https;
  el("nas-verify-tls").checked = nas.verify_tls;
  el("opt-upload").checked = nas.upload_after_import;
  el("nas-password").placeholder = nas.has_password ? "(guardada — dejar vacío para no cambiarla)" : "";
  hasDeviceToken = !!nas.has_device_token;
  updateNasFields();
}

let hasDeviceToken = false;

function updateNasFields() {
  const isSynology = el("nas-method").value === "synology";
  el("nas-https").closest("label").classList.toggle("hidden", !isSynology);

  // El token de dispositivo es cosa de Synology; en SFTP/FTP no pinta nada.
  el("nas-device").classList.toggle("hidden", !isSynology);
  el("nas-device-text").textContent = hasDeviceToken
    ? "✅ Este equipo está autorizado en el NAS: no se pedirá el código de verificación."
    : "Este equipo aún no está autorizado. Si la cuenta tiene verificación en dos pasos, " +
      "se te pedirá el código al probar la conexión.";
  el("nas-forget-btn").classList.toggle("hidden", !hasDeviceToken);
  if (!isSynology) el("nas-otp-row").classList.add("hidden");
}

el("nas-method").addEventListener("change", updateNasFields);

function nasPayload(includeOtp = false) {
  return {
    method: el("nas-method").value,
    host: el("nas-host").value.trim(),
    port: parseInt(el("nas-port").value, 10) || 0,
    user: el("nas-user").value.trim(),
    password: el("nas-password").value,
    // Solo viaja cuando el usuario acaba de teclearlo; nunca se guarda.
    ...(includeOtp ? { otp: el("nas-otp").value.trim() } : {}),
    remote_root: el("nas-root").value.trim() || "/photo",
    use_https: el("nas-https").checked,
    verify_tls: el("nas-verify-tls").checked,
    upload_after_import: el("opt-upload").checked,
  };
}

el("nas-save-btn").addEventListener("click", async () => {
  el("nas-status").textContent = "Guardando…";
  try {
    const config = await postJson("/api/importacion/config", {
      destination: el("destination-input").value.trim(),
      rename_by_date: el("opt-rename").checked,
      group_videos_by_day: el("opt-group-videos").checked,
      skip_duplicates: el("opt-skip-duplicates").checked,
      verify_checksum: el("opt-verify").checked,
      nas: nasPayload(),
    });
    el("nas-password").value = "";
    fillNasForm(config);
    el("nas-status").textContent = "Guardado.";
  } catch (err) {
    el("nas-status").textContent = err.message;
  }
});

async function testNas(withOtp) {
  const button = el(withOtp ? "nas-otp-btn" : "nas-test-btn");
  el("nas-status").textContent = "Probando… (hasta 30 s si el servidor no responde)";
  button.disabled = true;
  try {
    const result = await postJson("/api/importacion/nas-test", nasPayload(withOtp));

    // El NAS pide el segundo factor: no es un fallo, hay que enseñar el campo del código.
    if (result.needs_otp) {
      el("nas-otp-row").classList.remove("hidden");
      el("nas-otp").focus();
      el("nas-status").textContent = result.message;
      return;
    }

    el("nas-otp-row").classList.add("hidden");
    el("nas-otp").value = "";
    el("nas-status").textContent = result.message;
    if (result.device_token_saved) {
      hasDeviceToken = true;
      updateNasFields();
    }
  } catch (err) {
    el("nas-status").textContent = err.message;
  } finally {
    button.disabled = false;
  }
}

el("nas-test-btn").addEventListener("click", () => testNas(false));
el("nas-otp-btn").addEventListener("click", () => testNas(true));
el("nas-otp").addEventListener("keydown", (e) => { if (e.key === "Enter") testNas(true); });

// ------------------------------------------------ Explorador de carpetas del NAS

let browserPath = "";
let browserFolders = [];

async function browseNas(path) {
  el("browser-status").textContent = "Cargando…";
  try {
    const data = await postJson("/api/importacion/nas-browse", { ...nasPayload(), path });

    // Explorar también exige estar autenticado: si falta el 2FA, se pide igual que al probar.
    if (data.needs_otp) {
      el("nas-otp-row").classList.remove("hidden");
      el("nas-otp").focus();
      el("browser-status").textContent = data.message + " Introdúcelo arriba y vuelve a explorar.";
      return;
    }

    browserPath = data.path;
    browserFolders = data.folders;
    el("browser-path").textContent = browserPath || "Carpetas compartidas del NAS";
    el("browser-up-btn").disabled = !browserPath;
    el("browser-status").textContent = data.folders.length ? "" : "No hay subcarpetas aquí.";
    renderBrowserList();
  } catch (err) {
    el("browser-status").textContent = err.message;
  }
}

function renderBrowserList() {
  const filter = el("browser-filter").value.trim().toLowerCase();
  const list = el("browser-list");
  list.innerHTML = "";

  const shown = browserFolders.filter((f) => !filter || f.name.toLowerCase().includes(filter));
  for (const folder of shown) {
    const li = document.createElement("li");
    li.textContent = `📁 ${folder.name}`;
    li.title = folder.path;
    // Un clic entra en la carpeta; para elegirla está «Usar esta carpeta», que evita
    // seleccionar sin querer una por la que solo estabas pasando.
    li.addEventListener("click", () => browseNas(folder.path));
    list.appendChild(li);
  }
  if (filter && !shown.length) {
    el("browser-status").textContent = "Ninguna carpeta coincide con el filtro.";
  }
}

el("nas-browse-btn").addEventListener("click", () => {
  el("nas-browser").classList.remove("hidden");
  const current = el("nas-root").value.trim();
  browseNas(current && current !== "/" ? current : "");
});

el("browser-close-btn").addEventListener("click", () => {
  el("nas-browser").classList.add("hidden");
});

el("browser-up-btn").addEventListener("click", () => browseNas(
  browserPath.includes("/") ? browserPath.slice(0, browserPath.lastIndexOf("/")) : ""
));

el("browser-filter").addEventListener("input", renderBrowserList);

el("browser-use-btn").addEventListener("click", () => {
  if (!browserPath) {
    el("browser-status").textContent = "Entra en una carpeta compartida antes de elegirla.";
    return;
  }
  el("nas-root").value = browserPath;
  el("nas-browser").classList.add("hidden");
  el("nas-status").textContent = `Carpeta remota: ${browserPath} (recuerda guardar).`;
});

el("browser-mkdir-btn").addEventListener("click", async () => {
  const name = el("browser-new-name").value.trim();
  if (!name) {
    el("browser-status").textContent = "Escribe un nombre para la carpeta nueva.";
    return;
  }
  el("browser-status").textContent = "Creando…";
  try {
    const data = await postJson("/api/importacion/nas-mkdir",
      { ...nasPayload(), parent: browserPath, name });
    if (data.needs_otp) {
      el("browser-status").textContent = data.message;
      return;
    }
    el("browser-new-name").value = "";
    // Se entra directamente en la carpeta recién creada: es lo que se quiere el 99% de
    // las veces al crearla desde aquí.
    await browseNas(data.path);
    el("browser-status").textContent = `Creada «${name}».`;
  } catch (err) {
    el("browser-status").textContent = err.message;
  }
});

el("nas-forget-btn").addEventListener("click", async () => {
  if (!confirm(
    "Se olvidará la autorización de este equipo y volverá a pedirte el código 2FA.\n\n" +
    "Esto solo lo borra de aquí. Para revocarlo también en el NAS, quítalo en DSM → " +
    "Panel de control → Usuario → Avanzado → dispositivos de confianza.")) return;
  try {
    await postJson("/api/importacion/nas-forget-device", {});
    hasDeviceToken = false;
    updateNasFields();
    el("nas-status").textContent = "Autorización olvidada en este equipo.";
  } catch (err) {
    el("nas-status").textContent = err.message;
  }
});

el("upload-pending-btn").addEventListener("click", async () => {
  el("upload-status").textContent = "Iniciando…";
  el("upload-pending-btn").disabled = true;
  try {
    const data = await postJson("/api/importacion/nas-upload", {});
    trabajoEnCurso = true;
    pollUpload(data.job_id);
  } catch (err) {
    el("upload-status").textContent = err.message;
    el("upload-pending-btn").disabled = false;
  }
});

async function pollUpload(jobId, tick = 0) {
  let job;
  try {
    job = await api(`/api/importacion/nas-status/${jobId}`);
  } catch (err) {
    el("upload-status").textContent = err.message;
    trabajoEnCurso = false;
    loadHistory();
    return;
  }

  el("upload-status").textContent = `${job.done}/${job.total}${job.current ? ` — ${job.current}` : ""}`;

  if (job.state === "finalizado") {
    el("upload-status").textContent = `Subida completada (${job.done} archivos).`;
    trabajoEnCurso = false;
    loadHistory();
    return;
  }
  if (job.state === "error") {
    el("upload-status").textContent = `Error: ${job.error}`;
    trabajoEnCurso = false;
    loadHistory();
    return;
  }
  if (tick % REFRESCO_PENDIENTES === 0) loadHistory();
  setTimeout(() => pollUpload(jobId, tick + 1), 800);
}

// ----------------------------------------------------------------- Historial

async function loadHistory() {
  const data = await api("/api/importacion/history").catch(() => null);
  if (!data) {
    // Si la consulta falla no se deja el botón bloqueado para siempre: se devuelve al
    // estado que corresponda por si el usuario quiere reintentar a mano.
    el("upload-pending-btn").disabled = trabajoEnCurso;
    return;
  }

  const pending = data.pending_upload.length;
  let etiqueta = pending
    ? `${pending} archivo(s) importados siguen sin subir al NAS.`
    : "Todo lo importado está subido al NAS (o no hay nada pendiente).";
  if (pending && trabajoEnCurso) etiqueta += " Espera a que termine el trabajo en curso.";
  el("pending-label").textContent = etiqueta;
  el("upload-pending-btn").disabled = pending === 0 || trabajoEnCurso;

  const body = document.querySelector("#history-table tbody");
  body.innerHTML = "";
  for (const run of data.runs) {
    const tr = document.createElement("tr");
    const cells = [
      run.finished_at.replace("T", " "),
      run.source,
      String(run.copied),
      String(run.deleted || 0),
      formatBytes(run.bytes),
      run.upload_state || "—",
    ];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
  el("history-empty").classList.toggle("hidden", data.runs.length > 0);
}

// ------------------------------------------------------------------ Arranque

(async () => {
  try {
    fillNasForm(await api("/api/importacion/config"));
  } catch (err) {
    el("nas-status").textContent = err.message;
  }
  loadHistory();
  detectSources();
})();
