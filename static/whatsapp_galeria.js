// Galería: los medios agrupados por la conversación de la que vinieron, y limpieza.
//
// La estructura es virtual: en el disco los archivos están por tipo y mes (que es como
// hay que guardarlos, porque el nombre es la llave con la base de datos), pero aquí se
// ven por chat, que es como uno los recuerda. El cruce lo hace `galeria.py`.

let chatActual = null;
let mediosActuales = [];
let todosLosChats = [];
const elegidos = new Set();

// --------------------------------------------------- lista de conversaciones

async function cargaChats() {
  const datos = await api("/api/whatsapp/galeria/chats").catch((e) => {
    el("galeria-resumen").textContent = e.message;
    return null;
  });
  if (!datos) return;
  todosLosChats = datos.chats;
  pintaChats(todosLosChats);
  const total = datos.chats.reduce((a, c) => a + c.medios, 0);
  el("galeria-resumen").textContent =
    `${formatNumero(datos.total)} conversaciones · ${formatNumero(total)} archivos`;
}

function pintaChats(chats) {
  el("lista-chats").innerHTML = "";
  for (const c of chats) {
    const li = document.createElement("li");
    li.className = "chat-item" + (c.chat_id === chatActual ? " activo" : "");
    li.innerHTML = `
      <div class="chat-avatar">${c.es_grupo ? "👥" : "👤"}</div>
      <div class="chat-texto">
        <div class="chat-linea1">
          <span class="chat-nombre">${esc(c.nombre)}</span>
          <span class="chat-fecha">${formatFechaLista(c.hasta)}</span>
        </div>
        <div class="chat-linea2">
          <span class="chat-ultimo">${formatNumero(c.medios)} archivos</span>
          <span class="chat-contadores">${formatBytes(c.bytes)}</span>
        </div>
      </div>`;
    li.addEventListener("click", () => abreChat(c.chat_id));
    el("lista-chats").appendChild(li);
  }
}

el("busca-chat").addEventListener("input", (e) => {
  const q = e.target.value.trim().toLowerCase();
  pintaChats(q ? todosLosChats.filter((c) => c.nombre.toLowerCase().includes(q))
               : todosLosChats);
});

// ------------------------------------------------------------------ rejilla

async function abreChat(id) {
  chatActual = id;
  elegidos.clear();
  actualizaBarra();
  pintaChats(todosLosChats);
  el("rejilla").innerHTML = "<p class='vacio'>Cargando…</p>";

  const soloDisco = el("solo-disco").checked ? "1" : "0";
  const datos = await api(
    `/api/whatsapp/galeria/chat/${id}?en_disco=${soloDisco}&limit=400`
  ).catch((e) => {
    el("rejilla").innerHTML = `<p class="vacio">${esc(e.message)}</p>`;
    return null;
  });
  if (!datos) return;

  mediosActuales = datos.medios;
  el("galeria-titulo").textContent = datos.chat.nombre;
  el("galeria-datos").textContent =
    `${formatNumero(datos.total)} archivos · ${formatNumero(datos.en_disco)} en el ordenador`;
  pintaRejilla();
}

function pintaRejilla() {
  const rejilla = el("rejilla");
  rejilla.innerHTML = "";
  if (!mediosActuales.length) {
    rejilla.innerHTML = "<p class='vacio'>No hay archivos que enseñar.</p>";
    return;
  }

  for (const m of mediosActuales) {
    const celda = document.createElement("div");
    celda.className = "celda";
    const info = tipoDe(m.tipo);

    if (!m.en_disco) {
      // La base lo conoce pero el fichero ya no está: se enseña el hueco, no se oculta.
      celda.classList.add("ausente");
      celda.innerHTML = `<div>${info.icono}<br>${esc(m.nombre || info.etiqueta)}<br>
        <span class="muted">no está en el ordenador</span></div>`;
      rejilla.appendChild(celda);
      continue;
    }

    const url = `/api/whatsapp/archivo?ruta=${encodeURIComponent(m.local)}`;
    const casilla = document.createElement("input");
    casilla.type = "checkbox";
    casilla.checked = elegidos.has(m.local);
    casilla.addEventListener("change", () => {
      casilla.checked ? elegidos.add(m.local) : elegidos.delete(m.local);
      celda.classList.toggle("elegida", casilla.checked);
      actualizaBarra();
    });

    // `#t=0.5` pide el fotograma de medio segundo: sin eso el navegador pinta un
    // rectángulo negro y la rejilla de vídeos no se puede leer de un vistazo.
    const vista = (m.tipo === "video" || m.tipo === "gif" || m.tipo === "notas_video")
      ? Object.assign(document.createElement("video"),
                      { src: url + "#t=0.5", preload: "metadata", muted: true })
      : Object.assign(document.createElement("img"), { src: url, loading: "lazy", alt: "" });
    if (m.tipo === "notas_video") vista.classList.add("redonda");
    vista.addEventListener("click", () => abreVisor(url, m));

    const marca = document.createElement("span");
    marca.className = "marca";
    marca.textContent = `${info.icono}${m.mio ? " ↗" : ""}`;

    celda.append(casilla, vista, marca);
    celda.classList.toggle("elegida", casilla.checked);
    rejilla.appendChild(celda);
  }
}

el("solo-disco").addEventListener("change", () => { if (chatActual) abreChat(chatActual); });

// ------------------------------------------------------------------ selección

function actualizaBarra() {
  el("elegidos").textContent = elegidos.size ? `${formatNumero(elegidos.size)} elegidos` : "";
  el("borrar").disabled = elegidos.size === 0;
}

el("elegir-todo").addEventListener("click", () => {
  const enDisco = mediosActuales.filter((m) => m.en_disco).map((m) => m.local);
  const todosPuestos = enDisco.every((r) => elegidos.has(r));
  enDisco.forEach((r) => todosPuestos ? elegidos.delete(r) : elegidos.add(r));
  pintaRejilla();
  actualizaBarra();
});

el("borrar").addEventListener("click", async () => {
  const rutas = [...elegidos];
  // Borrar del disco es irreversible y no hay papelera de por medio: se confirma
  // diciendo cuántos y de dónde, no con un «¿seguro?» genérico.
  if (!confirm(
    `Se van a borrar ${rutas.length} archivo(s) del ordenador.\n\n` +
    `No se toca nada del móvil, pero en el ordenador es irreversible. ` +
    `Dejarán de contar como copiados, así que la próxima sincronización los traería otra vez ` +
    `si siguen en el teléfono.\n\n¿Continuar?`)) return;

  el("borrar").disabled = true;
  try {
    const r = await postJson("/api/whatsapp/galeria/borrar", { rutas });
    let mensaje = `Borrados ${r.borrados}.`;
    if (r.rechazados.length) mensaje += ` ${r.rechazados.length} fuera de la carpeta de destino (no se tocan).`;
    if (r.fallidos.length) mensaje += ` ${r.fallidos.length} con error.`;
    el("galeria-datos").textContent = mensaje;
    elegidos.clear();
    abreChat(chatActual);
    cargaChats();
  } catch (err) {
    el("galeria-datos").textContent = err.message;
  } finally {
    actualizaBarra();
  }
});

// -------------------------------------------------- visor y búsqueda cruzada

async function abreVisor(url, m) {
  el("visor-img").src = url;
  el("visor-pie").textContent = m.pie || m.nombre || "";
  el("visor-donde").textContent = "Buscando en qué conversaciones aparece…";
  el("visor-imagen").classList.remove("hidden");

  // Búsqueda cruzada: el mismo fichero puede estar en varias conversaciones porque un
  // reenvío conserva el nombre. Es el primer paso del «de esta foto a su chat».
  const datos = await api(
    `/api/whatsapp/galeria/donde?nombre=${encodeURIComponent(m.nombre)}`).catch(() => null);
  if (!datos) { el("visor-donde").textContent = ""; return; }

  // Cada sitio es un enlace al punto exacto de esa conversación: es el salto
  // «de esta foto al contexto en que se mandó», que es para lo que sirve la galería.
  const sitios = datos.apariciones;
  const enlaces = sitios.map((a) =>
    `<a href="/whatsapp/chats#chat=${a.chat_id}&mensaje=${a.mensaje_id}"
        target="_blank" rel="noopener">${esc(a.chat)} (${formatFecha(a.fecha)})</a>`
  ).join(" · ");
  el("visor-donde").innerHTML = sitios.length <= 1
    ? `Ver en la conversación: ${enlaces || "—"}`
    : `Aparece en ${sitios.length} conversaciones: ${enlaces}`;
}

el("cerrar-visor").addEventListener("click", () => el("visor-imagen").classList.add("hidden"));
el("visor-imagen").addEventListener("click", (e) => {
  if (e.target.id === "visor-imagen") el("visor-imagen").classList.add("hidden");
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") el("visor-imagen").classList.add("hidden");
});

(async () => {
  if (await compruebaBase()) cargaChats();
})();
