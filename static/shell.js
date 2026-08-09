// Compartido por las 4 secciones: recuerda la última carpeta de proyecto usada para
// no tener que renavegar hasta ella en cada módulo.
const LAST_ROOT_KEY = "conversor-last-root";

function rememberRoot(path) {
  if (path) localStorage.setItem(LAST_ROOT_KEY, path);
}

function lastRememberedRoot() {
  return localStorage.getItem(LAST_ROOT_KEY) || "";
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
