// Visor de conversaciones: lista a la izquierda, hilo a la derecha, como WhatsApp.
//
// Dos decisiones que condicionan todo lo demás:
//
// 1. **Los mensajes se piden hacia atrás, por tandas.** Un chat de esta base llega a
//    18.626 mensajes; cargarlo entero bloquearía el navegador. Se abre por el final —que
//    es donde uno mira— y se piden más al subir, como hace la app.
//
// 2. **Los eliminados se pintan siempre, pero encogidos.** En el hilo queda una papelera
//    en su sitio exacto, para que se vea que ahí hubo algo. El interruptor de arriba los
//    despliega. No se pueden «recuperar»: WhatsApp borra el texto de verdad y solo deja
//    constancia de que existió (ver /api/whatsapp/eliminados).

let chatActual = null;
let masAntiguo = null;      // `_id` más bajo cargado: por dónde seguir subiendo
let cargando = false;
let hayMas = false;
let todosLosChats = [];

// -------------------------------------------------------------- lista de chats

async function cargaChats() {
  const datos = await api("/api/whatsapp/chats?limit=1000").catch((e) => {
    el("chats-resumen").textContent = e.message;
    return null;
  });
  if (!datos) return;
  todosLosChats = datos.chats;
  pintaChats(todosLosChats);
  el("chats-resumen").textContent =
    `${formatNumero(datos.total)} conversaciones`;
}

function pintaChats(chats) {
  const lista = el("lista-chats");
  lista.innerHTML = "";
  for (const c of chats) {
    const li = document.createElement("li");
    li.className = "chat-item" + (c.id === chatActual ? " activo" : "");
    li.dataset.id = c.id;

    const icono = c.es_grupo ? "👥" : (c.es_canal ? "📢" : "👤");
    // Si la foto no está o falla, se cae al icono de siempre: un hueco en blanco en
    // mitad de la lista se lee como que la aplicación está rota.
    const avatar = c.avatar
      ? `<img class="chat-avatar" src="/api/whatsapp/avatar/${c.id}" alt="" loading="lazy"
              onerror="this.replaceWith(Object.assign(document.createElement('div'),
                       {className:'chat-avatar', textContent:'${icono}'}))">`
      : `<div class="chat-avatar">${icono}</div>`;
    li.innerHTML = `
      ${avatar}
      <div class="chat-texto">
        <div class="chat-linea1">
          <span class="chat-nombre">${esc(c.nombre)}</span>
          <span class="chat-fecha">${formatFechaLista(c.ultima_fecha)}</span>
        </div>
        <div class="chat-linea2">
          <span class="chat-ultimo">${esc(resumenMensaje(c.ultimo_tipo, c.ultimo_texto, c.ultimo_mio))}</span>
          <span class="chat-contadores">${formatNumero(c.mensajes)}${c.medios ? " · 📎" + formatNumero(c.medios) : ""}</span>
        </div>
      </div>`;
    li.addEventListener("click", () => abreChat(c.id));
    lista.appendChild(li);
  }
}

el("busca-chat").addEventListener("input", (e) => {
  const q = e.target.value.trim().toLowerCase();
  pintaChats(q ? todosLosChats.filter((c) => c.nombre.toLowerCase().includes(q))
               : todosLosChats);
});

// ----------------------------------------------------------------- el hilo

async function abreChat(id) {
  chatActual = id;
  masAntiguo = null;
  hayMas = false;
  el("hilo").innerHTML = '<p class="vacio">Cargando…</p>';
  el("cabecera-chat").classList.remove("hidden");
  pintaChats(todosLosChats);                 // repinta para marcar el activo

  const datos = await api(`/api/whatsapp/chat/${id}/mensajes?limit=60`).catch((e) => {
    el("hilo").innerHTML = `<p class="vacio">${esc(e.message)}</p>`;
    return null;
  });
  if (!datos) return;

  const info = todosLosChats.find((c) => c.id === id) || {};
  el("chat-nombre").textContent = datos.chat.nombre;
  el("chat-datos").textContent =
    `${formatNumero(info.mensajes)} mensajes · ${formatNumero(info.medios)} archivos`;

  el("hilo").innerHTML = "";
  añadeMensajes(datos.mensajes, false);
  hayMas = datos.hay_mas;
  masAntiguo = datos.siguiente;
  el("hilo").scrollTop = el("hilo").scrollHeight;
}

async function cargaMasAntiguos() {
  if (cargando || !hayMas || !chatActual || masAntiguo == null) return;
  cargando = true;
  const hilo = el("hilo");
  const altoAntes = hilo.scrollHeight;

  const datos = await api(
    `/api/whatsapp/chat/${chatActual}/mensajes?limit=60&antes_de=${masAntiguo}`
  ).catch(() => null);

  if (datos) {
    añadeMensajes(datos.mensajes, true);
    hayMas = datos.hay_mas;
    masAntiguo = datos.siguiente;
    // Se mantiene la posición de lectura: si no, insertar arriba daría un salto.
    hilo.scrollTop = hilo.scrollHeight - altoAntes;
  }
  cargando = false;
}

el("hilo").addEventListener("scroll", () => {
  if (el("hilo").scrollTop < 200) cargaMasAntiguos();
});

function añadeMensajes(mensajes, alPrincipio) {
  const hilo = el("hilo");
  const trozo = document.createDocumentFragment();
  let ultimoDia = alPrincipio ? null : hilo.dataset.ultimoDia;

  for (const m of mensajes) {
    const dia = formatFecha(m.fecha);
    if (dia && dia !== ultimoDia) {
      const sep = document.createElement("div");
      sep.className = "separador-dia";
      sep.textContent = dia;
      trozo.appendChild(sep);
      ultimoDia = dia;
    }
    trozo.appendChild(burbuja(m));
  }

  if (alPrincipio) hilo.prepend(trozo);
  else { hilo.appendChild(trozo); hilo.dataset.ultimoDia = ultimoDia || ""; }
}

function burbuja(m) {
  const div = document.createElement("div");

  if (m.tipo === "sistema") {
    div.className = "aviso-sistema";
    div.textContent = m.texto || "Aviso del sistema";
    return div;
  }

  div.className = "burbuja " + (m.mio ? "mia" : "suya");
  if (m.eliminado) div.classList.add("eliminada");
  div.dataset.id = m.id;

  const partes = [];

  if (m.autor && !m.mio) {
    // Cuando lo que se enseña es el nombre de la agenda, el número queda a un palmo del
    // ratón: en un grupo grande hace falta a menudo y abrir la ficha del contacto para
    // verlo es un viaje de ida y vuelta.
    const numero = m.autor_numero ? `+${m.autor_numero}` : "";
    const titulo = numero && numero !== m.autor ? ` title="${esc(numero)}"` : "";
    partes.push(`<div class="autor"${titulo}>${esc(m.autor)}</div>`);
  }
  if (m.citado) {
    const info = tipoDe(m.citado.tipo);
    partes.push(`<div class="citado">${info.icono} ${esc(m.citado.texto || info.etiqueta)}</div>`);
  }

  if (m.eliminado) {
    // Siempre visible: la papelera marca el hueco en su sitio exacto de la conversación.
    // El detalle solo aparece con el interruptor, y dice la verdad — el texto no está.
    // La papelera va como SVG y no como emoji: 🗑️ lleva un selector de variación que
    // no todas las fuentes resuelven, y salía un cuadro vacío en mitad del hilo.
    partes.push(`
      <div class="marca-eliminado" title="Aquí había un mensaje que se eliminó">
        <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
          <path fill="currentColor" d="M9 3h6l1 2h4v2H4V5h4l1-2zM6 9h12l-1 12H7L6 9zm3 2v8h1.5v-8H9zm4.5 0v8H15v-8h-1.5z"/>
        </svg>
        <span class="sr">Mensaje eliminado</span>
      </div>
      <div class="detalle-eliminado">${detalleEliminado(m)}</div>`);
  } else {
    if (m.medio) partes.push(pintaMedio(m));
    if (m.texto) partes.push(`<div class="texto">${esc(m.texto)}</div>`);
    if (!m.medio && !m.texto) {
      const info = tipoDe(m.tipo);
      partes.push(`<div class="texto muted">${info.icono} ${info.etiqueta || "Sin contenido"}</div>`);
    }
  }

  partes.push(`<div class="meta">${m.destacado ? "⭐ " : ""}${formatHora(m.fecha)}</div>`);
  div.innerHTML = partes.join("");

  for (const img of div.querySelectorAll("img.miniatura")) {
    img.addEventListener("click", () => abreVisor(img.src, (m.medio && m.medio.pie) || m.texto));
  }
  return div;
}

/** Qué se puede enseñar de un mensaje eliminado, sin prometer de más.
 *
 * WhatsApp borra el **texto** de verdad al revocar un mensaje: en la base quedan el
 * quién y el cuándo, pero `text_data` viene vacío en los 1.660 revocados de una base
 * real. El **archivo adjunto, en cambio, puede sobrevivir**: si se había descargado al
 * móvil antes de que lo borraran y nosotros lo copiamos, sigue en el ordenador. Ahí sí
 * hay algo que enseñar, y es justo lo que el interruptor sirve para ver.
 */
function detalleEliminado(m) {
  const partes = ["<em>Mensaje eliminado.</em>"];
  if (m.medio && m.medio.local) {
    partes.push(`<span class="muted">El archivo se había copiado antes de que lo
      borraran, así que se conserva:</span>`);
    partes.push(pintaMedio({ ...m, tipo: m.tipo_real }));
  } else if (m.medio) {
    partes.push(`<span class="muted">Llevaba un archivo adjunto que no está en el
      ordenador, así que se perdió con el mensaje.</span>`);
  } else {
    partes.push(`<span class="muted">WhatsApp borra el contenido al eliminarlo: solo
      queda constancia de que existió, de quién era y de cuándo.</span>`);
  }
  return partes.join("");
}

function pintaMedio(m) {
  const medio = m.medio;
  const info = tipoDe(m.tipo);

  // Lo que la base conoce pero ya no está en el ordenador. Es la mitad de los medios de
  // una base real: WhatsApp libera espacio por su cuenta. Enseñar el hueco es más útil
  // que fingir que el mensaje no llevaba nada.
  if (!medio.local) {
    return `<div class="medio-ausente">
        ${info.icono} ${info.etiqueta}
        <span class="muted">— no está en el ordenador${medio.bytes ? " (" + formatBytes(medio.bytes) + ")" : ""}</span>
      </div>`;
  }

  const url = `/api/whatsapp/archivo?ruta=${encodeURIComponent(medio.local)}`;
  if (m.tipo === "imagen" || m.tipo === "sticker") {
    return `<img class="miniatura ${m.tipo === "sticker" ? "sticker" : ""}" src="${url}" alt="" loading="lazy">`;
  }
  if (m.tipo === "video" || m.tipo === "gif" || m.tipo === "notas_video") {
    // `#t=0.5`: el fotograma de medio segundo como portada, para que no sea un rectángulo negro.
    // Las notas de vídeo son redondas en WhatsApp; se marca el tipo para darles forma.
    return `<video class="miniatura ${m.tipo === "notas_video" ? "redonda" : ""}"
                   src="${url}#t=0.5" controls preload="metadata"></video>`;
  }
  if (m.tipo === "audio") {
    return `<audio src="${url}" controls preload="none"></audio>`;
  }
  return `<a class="documento" href="${url}" target="_blank" rel="noopener">
            ${info.icono} ${esc(medio.nombre || info.etiqueta)}
            <span class="muted">${formatBytes(medio.bytes)}</span>
          </a>`;
}

// ------------------------------------------------- interruptor de eliminados

el("ver-eliminados").addEventListener("change", (e) => {
  el("hilo").classList.toggle("mostrar-eliminados", e.target.checked);
});

// --------------------------------------------------------- visor de imágenes

function abreVisor(src, pie) {
  el("visor-img").src = src;
  el("visor-pie").textContent = pie || "";
  el("visor-imagen").classList.remove("hidden");
}

el("cerrar-visor").addEventListener("click", () => el("visor-imagen").classList.add("hidden"));
el("visor-imagen").addEventListener("click", (e) => {
  if (e.target.id === "visor-imagen") el("visor-imagen").classList.add("hidden");
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") el("visor-imagen").classList.add("hidden");
});

// ------------------------------------------- salto desde la galería

/** Lee `#chat=123&mensaje=456` de la URL. Es como la galería enlaza aquí. */
function destinoEnLaUrl() {
  const trozos = new URLSearchParams(location.hash.slice(1));
  const chat = parseInt(trozos.get("chat"), 10);
  const mensaje = parseInt(trozos.get("mensaje"), 10);
  return chat ? { chat, mensaje: mensaje || null } : null;
}

/** Abre un chat centrado en un mensaje concreto, en vez de por el final. */
async function abreEnMensaje(chatId, mensajeId) {
  chatActual = chatId;
  el("cabecera-chat").classList.remove("hidden");
  el("hilo").innerHTML = '<p class="vacio">Buscando ese punto de la conversación…</p>';
  pintaChats(todosLosChats);

  const datos = await api(
    `/api/whatsapp/chat/${chatId}/contexto?mensaje=${mensajeId}&alrededor=30`
  ).catch((e) => {
    el("hilo").innerHTML = `<p class="vacio">${esc(e.message)}</p>`;
    return null;
  });
  if (!datos) return;

  const info = todosLosChats.find((c) => c.id === chatId) || {};
  el("chat-nombre").textContent = datos.chat.nombre;
  el("chat-datos").textContent =
    `${formatNumero(info.mensajes)} mensajes · ${formatNumero(info.medios)} archivos`;

  el("hilo").innerHTML = "";
  añadeMensajes(datos.mensajes, false);
  hayMas = datos.hay_mas;
  masAntiguo = datos.siguiente;

  // Se resalta y se centra el mensaje al que se venía, que es el sentido del salto.
  const diana = el("hilo").querySelector(`.burbuja[data-id="${datos.destacado}"]`);
  if (diana) {
    diana.classList.add("destacada");
    diana.scrollIntoView({ block: "center" });
  }
}

window.addEventListener("hashchange", () => {
  const destino = destinoEnLaUrl();
  if (!destino) return;
  destino.mensaje ? abreEnMensaje(destino.chat, destino.mensaje) : abreChat(destino.chat);
});

// ---------------------------------------------------------------- arranque

(async () => {
  if (!(await compruebaBase())) return;
  await cargaChats();
  const destino = destinoEnLaUrl();
  if (destino) {
    destino.mensaje ? abreEnMensaje(destino.chat, destino.mensaje) : abreChat(destino.chat);
  }
})();
