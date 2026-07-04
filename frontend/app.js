// Bootstrap: load config + root tree, wire mode toggle and search.
import { api } from "./api.js";
import { loadRoot } from "./browse.js";
import { initOrganize, setMode } from "./organize.js";
import { initSearch } from "./search.js";

let cfg = null;

async function boot() {
  try {
    cfg = await api.config();
  } catch (e) {
    document.getElementById("canvas").innerHTML =
      `<div class="loading">Cannot reach backend: ${e.message}</div>`;
    return;
  }
  showStatus();
  initOrganize(cfg);
  initSearch();
  await loadRoot(null);
  wireModes();
}

function showStatus() {
  const sub = document.getElementById("brand-sub");
  if (sub) {
    const root = String(cfg.lab_root || "");
    sub.textContent = (root ? root + " · " : "") + "nested map & safe reorganizer";
  }
  if (cfg.read_only) {
    const pill = document.getElementById("status-pill");
    pill.hidden = false;
    pill.textContent = "READ-ONLY";
    pill.classList.add("ro");
    const org = document.getElementById("mode-organize");
    org.disabled = true;
    org.title = "Disabled in read-only mode";
  }
}

function wireModes() {
  document.querySelectorAll(".mode").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      document.querySelectorAll(".mode").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      setMode(btn.dataset.mode);
    });
  });
}

boot();
