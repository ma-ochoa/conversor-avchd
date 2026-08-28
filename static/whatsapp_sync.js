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
    el("wa-sync").disabled = el("wa-sync-db").disabled = false;
  }
});

// Saltarse los medios cambia una sincronización de varios minutos a una de segundos: el
// grueso del tiempo se va en inventariar las 9 carpetas del móvil por USB, no en la base.
el("wa-sync-db").addEventListener("click", async () => {
  el("wa-sync").disabled = el("wa-sync-db").disabled = true;
  el("wa-sync-estado").textContent = "Trayendo solo la base de datos…";
  el("wa-progreso").classList.remove("hidden");
  el("wa-avisos").innerHTML = "";
  try {
    const { job_id } = await postJson("/api/whatsapp/sync", { con_medios: false });
    sondeaSync(job_id);
  } catch (err) {
    el("wa-sync-estado").textContent = err.message;
    el("wa-sync").disabled = el("wa-sync-db").disabled = false;
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
    el("wa-sync").disabled = el("wa-sync-db").disabled = false;
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
    el("wa-sync").disabled = el("wa-sync-db").disabled = false;
    cargaEstado();
    return;
  }
  setTimeout(() => sondeaSync(jobId), 700);
}

// ---------------------------------------------------------------- descifrar

let claveGuardada = false;

el("wa-descifrar").addEventListener("click", async () => {
  const campo = el("wa-clave");
  // Con una clave ya guardada no hace falta teclear nada: el campo vacío significa
  // «usa la que tienes», que es el caso normal a partir de la segunda vez.
  const usarGuardada = !campo.value.trim() && claveGuardada;
  if (!campo.value.trim() && !usarGuardada) {
    el("wa-descifrar-estado").textContent = "Falta la clave.";
    return;
  }
  el("wa-descifrar-estado").textContent =
    "Descifrando y preparando índices… (la primera vez tarda cerca de un minuto)";
  el("wa-descifrar").disabled = true;
  try {
    const data = await postJson("/api/whatsapp/decrypt", usarGuardada
      ? { use_saved: true }
      : { key: campo.value, remember: el("wa-recordar").checked });
    campo.value = "";                    // fuera en cuanto deja de hacer falta
    const r = data.resumen;
    el("wa-db-info").textContent =
      `${formatNumero(r.mensajes)} mensajes en ${formatNumero(r.chats)} conversaciones, ` +
      `${formatNumero(r.medios)} archivos y ${formatNumero(r.eliminados)} mensajes eliminados. ` +
      (data.resultado.agenda ? "Agenda de contactos incluida." : "Sin agenda: se verán números.");
    el("wa-resumen-db").classList.remove("hidden");
    el("wa-descifrar-estado").textContent = "Listo.";
    // Se dice qué trae la `wa.db` de esta copia: es la única forma de enterarse de que
    // WhatsApp ha vuelto a rellenar sus contactos, si algún día lo hace.
    const c = data.contactos_wa_db;
    if (c) {
      el("wa-descifrar-estado").textContent += c.con_nombre
        ? ` La copia trae ${formatNumero(c.con_nombre)} contactos con nombre.`
        : " La copia sigue sin traer contactos (wa_contacts vacía): los nombres salen de la agenda importada.";
    }
    if (data.clave_guardada && !String(data.clave_guardada).startsWith("error")) {
      claveGuardada = true;
    }
    const arch = data.archivo;
    if (arch && !arch.error) {
      el("wa-descifrar-estado").textContent += arch.primera_vez
        ? ` Archivo histórico creado con ${formatNumero(arch.mensajes)} mensajes.`
        : ` Archivo: +${formatNumero(arch.insertados?.message || 0)} mensajes nuevos,` +
          ` ${formatNumero(arch.mensajes_idos)} ya no están en el móvil.`;
    } else if (arch?.error) {
      el("wa-descifrar-estado").textContent += ` (el archivo histórico falló: ${arch.error})`;
    }
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
  pintaArchivo(s.archivo);

  // Una copia descargada más nueva que la descifrada = solo falta la clave.
  const pendiente = s.encrypted.present &&
    (!s.decrypted.present || s.decrypted.modified < s.encrypted.modified);
  const aviso = el("wa-pendiente");
  aviso.classList.toggle("hidden", !pendiente);
  if (pendiente) {
    aviso.textContent = `Hay una copia descargada del ${s.encrypted.modified.replace("T", " ")}` +
      ` (${formatBytes(s.encrypted.size)}) sin descifrar. ` +
      (claveGuardada ? "Pulsa «Descifrar»: la clave ya está guardada."
                     : "Solo falta introducir la clave.");
  }

  if (!s.tool_installed) {
    el("wa-descifrar").disabled = true;
    el("wa-descifrar-estado").textContent =
      `Falta la herramienta de descifrado. Instálala con: ${s.tool_command || ""}`;
  }
}

// ------------------------------------------------------------- fotos de perfil

el("wa-av-copiar").addEventListener("click", async () => {
  try {
    const js = await fetch("/api/whatsapp/avatares/extractor").then(r => r.text());
    await navigator.clipboard.writeText(js);
    el("wa-av-estado").textContent =
      "Copiado. Pégalo en la consola de web.whatsapp.com (F12 → Console).";
  } catch (err) {
    el("wa-av-estado").textContent =
      "No se pudo copiar al portapapeles. Ábrelo a mano: /api/whatsapp/avatares/extractor";
  }
});

el("wa-av-fichero").addEventListener("change", async (ev) => {
  const fichero = ev.target.files[0];
  if (!fichero) return;
  el("wa-av-estado").textContent = "Leyendo el fichero…";
  try {
    const lista = JSON.parse(await fichero.text());
    // Va por la misma ruta que usa el navegador de WhatsApp, pero desde aquí es el mismo
    // origen: sin CORS de por medio y sin el bloqueo de red privada de Chrome.
    const r = await postJson("/api/whatsapp/avatares", { avatares: lista });
    el("wa-av-estado").textContent =
      `${formatNumero(r.utiles)} fotos en la lista. Pulsa «Descargar las fotos».`;
    estadoAvatares();
  } catch (err) {
    el("wa-av-estado").textContent = "No se pudo leer: " + err.message;
  }
  ev.target.value = "";
});

el("wa-av-descargar").addEventListener("click", async () => {
  el("wa-av-descargar").disabled = true;
  el("wa-av-estado").textContent = "Descargando… (una cada cuarto de segundo, sin prisa)";
  try {
    const r = await postJson("/api/whatsapp/avatares/descargar", {});
    el("wa-av-estado").textContent =
      `Listo: ${formatNumero(r.hechos)} procesadas` + (r.errores ? `, ${r.errores} fallaron.` : ".");
    estadoAvatares();
  } catch (err) {
    el("wa-av-estado").textContent = err.message;
  } finally {
    el("wa-av-descargar").disabled = false;
  }
});

async function estadoAvatares() {
  const e = await api("/api/whatsapp/avatares").catch(() => null);
  if (!e) return;
  const filas = [["Fotos guardadas", `${formatNumero(e.guardados)} · ${formatBytes(e.bytes)}`]];
  if (e.guardados) {
    const c = await api("/api/whatsapp/avatares/casar").catch(() => null);
    if (c && !c.error) {
      filas.push(["Emparejadas con una conversación",
        `${formatNumero(c.casados)} de ${formatNumero(c.total)}`]);
      // Los ambiguos son nombres repetidos en varias conversaciones: no se puede saber
      // cuál es sin preguntar, así que se dicen en vez de elegir al azar.
      if (c.ambiguos) filas.push(["Nombre repetido en varias conversaciones", formatNumero(c.ambiguos)]);
      if (c.sin_casar) filas.push(["Sin conversación que les corresponda", formatNumero(c.sin_casar)]);
    }
  }
  document.querySelector("#wa-av-tabla tbody").innerHTML = filas
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
}

function pintaArchivo(a) {
  const cuerpo = document.querySelector("#wa-archivo tbody");
  el("wa-archivo-vacio").classList.toggle("hidden", !!(a && a.existe));
  if (!a || !a.existe) { cuerpo.innerHTML = ""; return; }
  if (a.error) {
    cuerpo.innerHTML = `<tr><td>Archivo</td><td>${esc(a.error)}</td></tr>`;
    return;
  }
  const filas = [
    ["Mensajes guardados", formatNumero(a.mensajes)],
    ["Conversaciones", formatNumero(a.chats)],
    // Lo que da sentido a todo esto: lo que ya no está en el teléfono y sigue aquí.
    ["Ya no están en el móvil",
      `${formatNumero(a.mensajes_idos)} mensajes · ${formatNumero(a.chats_idos)} conversaciones`],
    ["Última fusión", a.ultima_fusion ? a.ultima_fusion.replace("T", " ").slice(0, 19) : "—"],
    ["Tamaño", formatBytes(a.bytes)],
  ];
  cuerpo.innerHTML = filas
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
}

async function estadoClave() {
  const k = await api("/api/whatsapp/clave").catch(() => null);
  if (!k) return;
  claveGuardada = k.guardada;
  el("wa-recordar").checked = k.guardada;
  el("wa-clave-estado").textContent = k.guardada
    ? (k.donde === "llavero"
        ? "Clave guardada, cifrada y con su maestra en el llavero del sistema. Deja el campo vacío y pulsa Descifrar."
        : "Clave guardada y cifrada, pero la maestra está en un fichero junto a ella: este equipo no tiene llavero disponible, así que quien acceda a la carpeta puede descifrarla.")
    : "No hay ninguna clave guardada.";
  el("wa-clave").placeholder = k.guardada
    ? "Guardada — déjalo vacío para usarla"
    : "Pega aquí los 64 dígitos (los espacios dan igual)";
}

// Desmarcar es una orden inmediata de borrar: no tiene sentido esperar al próximo
// descifrado para dejar de guardar algo que el usuario acaba de decir que no quiere.
el("wa-recordar").addEventListener("change", async (ev) => {
  if (!ev.target.checked && claveGuardada) {
    await fetch("/api/whatsapp/clave", { method: "DELETE" }).catch(() => null);
    await estadoClave();
  }
});

estadoClave().then(cargaEstado).then(estadoAvatares);
