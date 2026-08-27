// Sincronización: medios y base de datos del móvil, y descifrado de la base.

let tiposGuardados = [];
let todosLosTipos = [];

function tiposMarcados() {
  return [...document.querySelectorAll("#wa-tipos input[type=checkbox]")]
    .filter((c) => c.checked).map((c) => c.value);
}

function pintaTipos() {
  const body = document.querySelector("#wa-tipos tbody");
  body.innerHTML = "";
  for (const t of todosLosTipos) {
    const tr = document.createElement("tr");
    const marca = document.createElement("td");
    const casilla = document.createElement("input");
    casilla.type = "checkbox";
    casilla.value = t.key;
    casilla.checked = tiposGuardados.length ? tiposGuardados.includes(t.key) : t.default;
    marca.appendChild(casilla);
    const nombre = document.createElement("td");
    nombre.textContent = t.label;
    tr.append(marca, nombre);
    body.appendChild(tr);
  }
}

// ------------------------------------------------------------- sincronizar

el("wa-dest-btn").addEventListener("click", async () => {
  const data = await postJson("/api/pick-folder", { path: el("wa-dest").value });
  if (data.canceled || !data.path) return;
  el("wa-dest").value = data.path;
});

el("wa-sync").addEventListener("click", async () => {
  el("wa-sync").disabled = true;
  el("wa-sync-estado").textContent = "Iniciando…";
  el("wa-progreso").classList.remove("hidden");
  el("wa-avisos").innerHTML = "";
  try {
    const { job_id } = await postJson("/api/whatsapp/sync", {
      destination: el("wa-dest").value,
      kinds: tiposMarcados(),
    });
    await postJson("/api/whatsapp/config", {
      destination: el("wa-dest").value, kinds: tiposMarcados(),
    });
    sondeaSync(job_id);
  } catch (err) {
    el("wa-sync-estado").textContent = err.message;
    el("wa-sync").disabled = false;
  }
});

function pintaFases(job) {
  const orden = job.fases.map((f) => f.clave);
  const actual = orden.indexOf(job.fase);
  el("wa-fases").innerHTML = job.fases.map((f, i) => {
    const estado = job.state === "error" && i === actual ? "✕"
                 : i < actual ? "✓" : (i === actual ? "▸" : "·");
    const clase = i < actual ? "hecha" : (i === actual ? "actual" : "");
    return `<li class="${clase}">${estado} ${esc(f.titulo)}</li>`;
  }).join("");
}

async function sondeaSync(jobId) {
  let job;
  try {
    job = await api(`/api/whatsapp/sync/${jobId}`);
  } catch (err) {
    el("wa-sync-estado").textContent = err.message;
    el("wa-sync").disabled = false;
    return;
  }

  pintaFases(job);

  const m = job.medios;
  const b = job.base;
  let detalle = "";
  if (job.fase === "medios") {
    el("wa-barra").value = m.total ? m.copiados / m.total : 0;
    // El total en bytes solo se enseña si es fiable: el inventario no pregunta el
    // tamaño de cada fichero, así que casi siempre se sabe cuánto se lleva copiado
    // pero no cuánto queda.
    const tamaño = m.sin_tamano
      ? `${formatBytes(m.bytes)} copiados`
      : `${formatBytes(m.bytes)} de ${formatBytes(m.bytes_total)}`;
    detalle = `${formatNumero(m.copiados)}/${formatNumero(m.total)} archivos · ${tamaño}` +
              (m.actual ? ` · ${m.actual}` : "");
  } else if (job.fase === "base") {
    el("wa-barra").value = b.bytes_total ? b.bytes / b.bytes_total : 0;
    detalle = `${b.nombre || ""} — ${formatBytes(b.bytes)} de ${formatBytes(b.bytes_total)}`;
  } else if (job.fase === "inventario") {
    // Recorrer todo el WhatsApp por USB son varios minutos: se enseña por dónde va y
    // cuántos lleva, en vez de una barra indeterminada que no dice nada.
    const inv = job.inventario || {};
    el("wa-barra").value = inv.de ? inv.hechos / inv.de : 0;
    detalle = `Inventariando ${inv.tipo || "el móvil"}… ` +
              `${formatNumero(inv.vistos)} archivos vistos ` +
              `(${inv.hechos || 0} de ${inv.de || 0} carpetas)`;
  }
  el("wa-detalle").textContent = detalle;

  if (job.state === "finalizado" || job.state === "error") {
    el("wa-barra").value = job.state === "finalizado" ? 1 : 0;
    el("wa-sync-estado").textContent = job.state === "error"
      ? `Error: ${job.error}`
      : `Terminado: ${formatNumero(m.copiados)} archivos nuevos` +
        (m.omitidos ? `, ${formatNumero(m.omitidos)} ya estaban` : "") +
        (b.descargada ? ". Base de datos descargada — ya puedes descifrarla." : ".");
    for (const aviso of job.avisos || []) {
      const li = document.createElement("li");
      li.textContent = aviso;
      el("wa-avisos").appendChild(li);
    }
    for (const e of (m.errores || []).slice(0, 20)) {
      const li = document.createElement("li");
      li.textContent = e;
      el("wa-avisos").appendChild(li);
    }
    el("wa-sync").disabled = false;
    cargaEstado();
    return;
  }
  setTimeout(() => sondeaSync(jobId), 700);
}

// ---------------------------------------------------------------- descifrar

el("wa-descifrar").addEventListener("click", async () => {
  const campo = el("wa-clave");
  if (!campo.value.trim()) {
    el("wa-descifrar-estado").textContent = "Falta la clave.";
    return;
  }
  el("wa-descifrar-estado").textContent =
    "Descifrando y preparando índices… (la primera vez tarda cerca de un minuto)";
  el("wa-descifrar").disabled = true;
  try {
    const data = await postJson("/api/whatsapp/decrypt", { key: campo.value });
    campo.value = "";                    // fuera en cuanto deja de hacer falta
    const r = data.resumen;
    el("wa-db-info").textContent =
      `${formatNumero(r.mensajes)} mensajes en ${formatNumero(r.chats)} conversaciones, ` +
      `${formatNumero(r.medios)} archivos y ${formatNumero(r.eliminados)} mensajes eliminados. ` +
      (data.resultado.agenda ? "Agenda de contactos incluida." : "Sin agenda: se verán números.");
    el("wa-resumen-db").classList.remove("hidden");
    el("wa-descifrar-estado").textContent = "Listo.";
    if (data.indices && !data.indices.completo) {
      el("wa-descifrar-estado").textContent +=
        ` Aviso: ${data.indices.fallidos.length} índice(s) no se pudieron crear; las consultas irán lentas.`;
    }
    cargaEstado();
  } catch (err) {
    el("wa-descifrar-estado").textContent = err.message;
  } finally {
    el("wa-descifrar").disabled = false;
  }
});

// ------------------------------------------------------------------ estado

async function cargaEstado() {
  const cfg = await api("/api/whatsapp/estado").catch(() => null);
  if (!cfg) return;

  el("wa-dest").value = cfg.destination;
  tiposGuardados = cfg.kinds || [];
  todosLosTipos = cfg.all_kinds;
  pintaTipos();

  const s = cfg.sync;
  const filas = [
    ["Medios copiados al ordenador", formatNumero(s.medios_copiados)],
    ["Última sincronización", s.ultima_sync ? s.ultima_sync.replace("T", " ") : "nunca"],
    ["Copia cifrada", s.encrypted.present
      ? `${formatBytes(s.encrypted.size)} — del ${s.encrypted.modified.replace("T", " ")}` : "no descargada"],
    ["Base descifrada", s.decrypted.present
      ? `${formatBytes(s.decrypted.size)} — del ${s.decrypted.modified.replace("T", " ")}` : "no"],
    ["Agenda de contactos", s.agenda_cifrada ? "descargada" : "no"],
    // Las incrementales solo aparecen cuando WhatsApp ha hecho alguna después de la
    // última copia completa; lo normal es que no haya ninguna recién sincronizado.
    ["Copias incrementales", s.incrementales?.length
        ? `${s.incrementales.length} descargada(s)` : "ninguna pendiente"],
    ["Índices de consulta", s.indices_listos ? "listos" : "sin preparar"],
    ["Herramienta de descifrado", s.tool_installed ? "instalada" : `FALTA — ${s.tool_command || ""}`],
  ];
  document.querySelector("#wa-estado tbody").innerHTML = filas
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");

  if (cfg.db) {
    el("wa-db-info").textContent =
      `${formatNumero(cfg.db.mensajes)} mensajes en ${formatNumero(cfg.db.chats)} conversaciones, ` +
      `${formatNumero(cfg.db.medios)} archivos y ${formatNumero(cfg.db.eliminados)} eliminados.`;
    el("wa-resumen-db").classList.remove("hidden");
  }
  if (!s.tool_installed) {
    el("wa-descifrar").disabled = true;
    el("wa-descifrar-estado").textContent =
      `Falta la herramienta de descifrado. Instálala con: ${s.tool_command || ""}`;
  }
}

cargaEstado();
