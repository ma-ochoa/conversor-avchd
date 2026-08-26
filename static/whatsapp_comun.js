// Utilidades compartidas por las cuatro páginas de WhatsApp.
//
// Se mantiene como un fichero sin módulos ni dependencias a propósito: la sección va a
// migrarse a .NET, y cuanto menos andamiaje propio tenga, más directa es la traducción.

const el = (id) => document.getElementById(id);

function formatBytes(bytes) {
  if (bytes == null) return "—";
  const gb = bytes / 1e9;
  if (gb >= 1) return gb.toFixed(2) + " GB";
  const mb = bytes / 1e6;
  if (mb >= 1) return mb.toFixed(1) + " MB";
  return Math.round(bytes / 1e3) + " KB";
}

function formatNumero(n) {
  return (n ?? 0).toLocaleString("es");
}

// WhatsApp guarda los tiempos en milisegundos desde época.
function fechaDe(ms) {
  return ms ? new Date(Number(ms)) : null;
}

function formatFecha(ms) {
  const d = fechaDe(ms);
  if (!d || isNaN(d)) return "";
  return d.toLocaleDateString("es", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function formatHora(ms) {
  const d = fechaDe(ms);
  if (!d || isNaN(d)) return "";
  return d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
}

/** Fecha relativa como la de la lista de WhatsApp: hora si es hoy, día si no. */
function formatFechaLista(ms) {
  const d = fechaDe(ms);
  if (!d || isNaN(d)) return "";
  const hoy = new Date();
  const mismoDia = d.toDateString() === hoy.toDateString();
  if (mismoDia) return formatHora(ms);
  const ayer = new Date(hoy);
  ayer.setDate(hoy.getDate() - 1);
  if (d.toDateString() === ayer.toDateString()) return "ayer";
  return d.toLocaleDateString("es", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

async function api(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({ error: "Respuesta inesperada del servidor" }));
  if (data.error) throw new Error(data.error);
  return data;
}

const postJson = (url, body) => api(url, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/** Icono y etiqueta de cada tipo de mensaje, para no repetirlos en cada página. */
const TIPOS = {
  texto:       { icono: "",   etiqueta: "" },
  imagen:      { icono: "📷", etiqueta: "Foto" },
  video:       { icono: "🎥", etiqueta: "Vídeo" },
  notas_video: { icono: "⭕", etiqueta: "Nota de vídeo" },
  audio:       { icono: "🎤", etiqueta: "Audio" },
  gif:         { icono: "🎞️", etiqueta: "GIF" },
  sticker:     { icono: "🌟", etiqueta: "Sticker" },
  documento:   { icono: "📄", etiqueta: "Documento" },
  contacto:    { icono: "👤", etiqueta: "Contacto" },
  ubicacion:   { icono: "📍", etiqueta: "Ubicación" },
  llamada:     { icono: "📞", etiqueta: "Llamada" },
  encuesta:    { icono: "📊", etiqueta: "Encuesta" },
  sistema:     { icono: "ℹ️", etiqueta: "Aviso del sistema" },
  eliminado:   { icono: "🗑️", etiqueta: "Mensaje eliminado" },
  efimero:     { icono: "⏱️", etiqueta: "Mensaje temporal" },
  otro:        { icono: "•",  etiqueta: "" },
};

const tipoDe = (t) => TIPOS[t] || TIPOS.otro;

/** Resumen de una línea para la lista de chats, como el que enseña WhatsApp. */
function resumenMensaje(tipo, texto, mio) {
  const info = tipoDe(tipo);
  const cuerpo = tipo === "texto" ? (texto || "")
               : `${info.icono} ${info.etiqueta}${texto ? ": " + texto : ""}`;
  return (mio ? "Tú: " : "") + cuerpo;
}

/** Muestra el aviso de «no hay base descifrada» y devuelve si la hay. */
async function compruebaBase() {
  const estado = await api("/api/whatsapp/estado").catch(() => null);
  const hay = Boolean(estado && estado.db);
  const aviso = el("wa-aviso-base");
  if (aviso) aviso.classList.toggle("hidden", hay);
  return hay ? estado : null;
}

/** Escapa texto para insertarlo como HTML. Los mensajes son contenido ajeno. */
function esc(s) {
  const div = document.createElement("div");
  div.textContent = s ?? "";
  return div.innerHTML;
}
