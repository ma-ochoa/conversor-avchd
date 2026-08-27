// Contactos: navegación propia sobre la tabla `jid`, que WhatsApp no enseña como tal.
//
// El número asusta —120.011 en la base de prueba— y la explicación no es evidente, así
// que la página la da en vez de dejar al usuario pensando que tiene un problema.

let todos = [];

async function cargaExplicacion() {
  const e = await api("/api/whatsapp/jids").catch(() => null);
  if (!e) return;
  const porServidor = e.por_servidor
    .map((s) => `<tr><td><code>${esc(s.servidor)}</code></td><td>${formatNumero(s.total)}</td>
                 <td class="muted">${esc(explica(s.servidor))}</td></tr>`).join("");
  el("explicacion-jid").innerHTML = `
    <p>La base guarda <strong>${formatNumero(e.total)} identificadores</strong>, pero eso no es
    tu agenda: es <em>todo identificador que la base ha visto alguna vez</em> — cada miembro de
    cada grupo, cada canal, cada número que escribió una vez. De todos ellos,
    <strong>${formatNumero(e.han_escrito)} han escrito algún mensaje</strong>, que es el orden
    de magnitud de una agenda real.</p>
    <table class="compacta">
      <thead><tr><th>Servidor</th><th>Cuántos</th><th>Qué es</th></tr></thead>
      <tbody>${porServidor}</tbody>
    </table>
    <p class="hint">Los <code>lid</code> son identificadores que no revelan el teléfono. Desde que
    WhatsApp los introdujo, <strong>la misma persona puede aparecer dos veces</strong>, una por
    servidor — que es de dónde sale casi el doble de filas de las esperadas.</p>`;
}

function explica(servidor) {
  return {
    "s.whatsapp.net": "Usuarios con número de teléfono",
    "lid": "Identificador sin teléfono (misma persona, otra ficha)",
    "g.us": "Grupos",
    "newsletter": "Canales",
    "broadcast": "Listas de difusión",
    "status_me": "Tus propios estados",
    "temp": "Provisionales",
    "bot": "Asistentes automáticos",
  }[servidor] || "";
}

async function carga() {
  const todosLosJid = el("todos").checked ? "1" : "0";
  el("contactos-resumen").textContent = "Cargando…";
  const datos = await api(`/api/whatsapp/contactos?todos=${todosLosJid}&limit=500`)
    .catch((e) => { el("contactos-resumen").textContent = e.message; return null; });
  if (!datos) return;
  todos = datos.contactos;
  el("contactos-resumen").textContent =
    `${formatNumero(datos.total)} contactos` +
    (el("todos").checked ? " (incluidos los que nunca han escrito)" : " que han escrito alguna vez");
  el("contactos-mas").textContent = datos.total > todos.length
    ? `Mostrando los ${formatNumero(todos.length)} primeros, ordenados por número de mensajes.` : "";
  pinta(todos);
}

function pinta(lista) {
  document.querySelector("#tabla-contactos tbody").innerHTML = lista.map((c) => `
    <tr>
      <td>${c.nombre === "+" + c.numero
              // Sin la agenda descifrada, el «nombre» es el propio número: repetirlo en
              // las dos columnas solo ocupa sitio y hace pensar que falta algo.
              ? "<span class='muted'>sin nombre</span>"
              : esc(c.nombre)}${c.en_agenda ? " <span class='muted'>· en agenda</span>" : ""}</td>
      <td>${c.numero ? "+" + esc(c.numero) : "<span class='muted'>—</span>"}</td>
      <td>${formatNumero(c.mensajes)}</td>
      <td class="muted">${esc(explica(c.servidor) || c.servidor)}</td>
      <td>${c.chat_id ? `<a href="/whatsapp/chats#chat=${c.chat_id}">ver chat →</a>` : ""}</td>
    </tr>`).join("");
}

el("busca").addEventListener("input", (e) => {
  const q = e.target.value.trim().toLowerCase();
  pinta(q ? todos.filter((c) => c.nombre.toLowerCase().includes(q) ||
                                (c.numero || "").includes(q)) : todos);
});
el("todos").addEventListener("change", carga);

// ------------------------------------------------------------------ agenda

async function estadoAgenda() {
  const a = await api("/api/whatsapp/agenda").catch(() => null);
  if (!a) return;
  el("agenda-estado").textContent = a.numeros
    ? `${formatNumero(a.contactos)} contactos importados (${formatNumero(a.numeros)} números). ` +
      `Origen: ${a.origen}`
    : "Sin agenda importada: los contactos se ven como números de teléfono.";
  el("agenda-olvidar").disabled = !a.numeros;
}

el("agenda-elegir").addEventListener("click", async () => {
  el("agenda-resultado").textContent = "";
  const elegido = await postJson("/api/whatsapp/agenda/elegir", {}).catch(() => null);
  if (!elegido || elegido.canceled || !elegido.path) return;

  el("agenda-resultado").textContent = "Leyendo…";
  try {
    const r = await postJson("/api/whatsapp/agenda/importar", { path: elegido.path });
    el("agenda-resultado").textContent =
      `Importados ${formatNumero(r.contactos_con_nombre)} contactos con nombre ` +
      `(${formatNumero(r.numeros_indexados)} números). Recargando…`;
    await estadoAgenda();
    carga();
  } catch (err) {
    el("agenda-resultado").textContent = err.message;
  }
});

el("agenda-olvidar").addEventListener("click", async () => {
  await postJson("/api/whatsapp/agenda/olvidar", {}).catch(() => null);
  el("agenda-resultado").textContent = "Agenda olvidada.";
  await estadoAgenda();
  carga();
});

(async () => {
  if (await compruebaBase()) { estadoAgenda(); cargaExplicacion(); carga(); }
})();
