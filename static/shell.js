// Compartido por las 4 secciones: recuerda la última carpeta de proyecto usada para
// no tener que renavegar hasta ella en cada módulo.
const LAST_ROOT_KEY = "conversor-last-root";

function rememberRoot(path) {
  if (path) localStorage.setItem(LAST_ROOT_KEY, path);
}

function lastRememberedRoot() {
  return localStorage.getItem(LAST_ROOT_KEY) || "";
}

// Errores de /api/browse. El caso interesante es `blocked`: macOS no ha concedido
// permiso sobre la carpeta (Escritorio, Descargas, Documentos) y el servidor ha
// desistido de listarla en vez de quedarse colgado. Como el permiso se concede fuera
// de la app, hace falta un reintento explícito: sin él habría que reiniciar el
// servidor para que volviera a probar la carpeta.
function showBrowseError(statusEl, data, retryFn) {
  if (!statusEl) return;
  statusEl.dataset.browseError = "1";
  statusEl.textContent = data.error || "No se pudo leer la carpeta.";
  if (!data.blocked || !retryFn) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "link-btn";
  btn.textContent = "Reintentar";
  btn.addEventListener("click", () => retryFn());
  statusEl.append(" ", btn);
}

// Retira solo el aviso que puso showBrowseError. El mismo hueco lo comparten los
// mensajes de escaneo, que no tienen por qué desaparecer al navegar entre carpetas.
function clearBrowseError(statusEl) {
  if (!statusEl || !statusEl.dataset.browseError) return;
  statusEl.textContent = "";
  delete statusEl.dataset.browseError;
}

// Se ejecuta como script de bloqueo al final del <body>: el campo #path-input ya
// existe en el DOM en este punto, y esto debe correr ANTES de que el script propio
// de cada página lance su primera carga de carpeta — por eso no se espera a
// DOMContentLoaded (que dispararía después de que ese script ya haya arrancado).
(() => {
  const input = document.getElementById("path-input");
  const remembered = lastRememberedRoot();
  if (input && remembered) input.value = remembered;
})();
