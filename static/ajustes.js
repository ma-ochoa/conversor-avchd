const pathInput = document.getElementById("wd-path-input");
const crumb = document.getElementById("wd-crumb");
const dirList = document.getElementById("wd-dir-list");
const goBtn = document.getElementById("wd-go-btn");
const browseBtn = document.getElementById("wd-browse-btn");
const saveBtn = document.getElementById("save-btn");
const clearBtn = document.getElementById("clear-btn");
const saveStatus = document.getElementById("save-status");
const currentWorkingDirEl = document.getElementById("current-working-dir");

async function loadDirs(path, retry = false) {
  const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}${retry ? "&retry=1" : ""}`);
  const data = await res.json();
  if (data.error) {
    showBrowseError(saveStatus, data, () => loadDirs(path, true));
    return;
  }
  clearBrowseError(saveStatus);
  pathInput.value = data.path;
  crumb.textContent = data.path;
  dirList.innerHTML = "";

  if (data.parent) {
    const up = document.createElement("li");
    up.textContent = "⬆︎ ..";
    up.addEventListener("click", () => loadDirs(data.parent));
    dirList.appendChild(up);
  }
  for (const dir of data.dirs) {
    const li = document.createElement("li");
    li.textContent = "📁 " + dir.name;
    li.addEventListener("click", () => loadDirs(dir.path));
    dirList.appendChild(li);
  }
}

goBtn.addEventListener("click", () => loadDirs(pathInput.value));
pathInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadDirs(pathInput.value);
});

browseBtn.addEventListener("click", async () => {
  saveStatus.textContent = "";
  const res = await fetch("/api/pick-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: pathInput.value }),
  });
  const data = await res.json();
  if (data.error) {
    saveStatus.textContent = data.error;
    return;
  }
  if (data.canceled || !data.path) return;
  loadDirs(data.path);
});

function renderCurrentWorkingDir(workingDir) {
  currentWorkingDirEl.textContent = workingDir
    ? `Carpeta de trabajo actual: ${workingDir}`
    : "Carpeta de trabajo actual: ninguna — cada carpeta de origen es su propia carpeta de trabajo (por defecto).";
}

async function loadConfig() {
  const res = await fetch("/api/config");
  const data = await res.json();
  renderCurrentWorkingDir(data.working_dir);
  loadDirs(data.working_dir || pathInput.dataset.home);
}

saveBtn.addEventListener("click", async () => {
  saveStatus.textContent = "Guardando…";
  const res = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ working_dir: pathInput.value }),
  });
  const data = await res.json();
  if (data.error) {
    saveStatus.textContent = data.error;
    return;
  }
  renderCurrentWorkingDir(data.working_dir);
  saveStatus.textContent = "Guardado.";
});

clearBtn.addEventListener("click", async () => {
  saveStatus.textContent = "";
  const res = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ working_dir: null }),
  });
  const data = await res.json();
  renderCurrentWorkingDir(data.working_dir);
  saveStatus.textContent = "Se ha quitado la carpeta de trabajo — vuelta al comportamiento por defecto.";
});

loadConfig();
