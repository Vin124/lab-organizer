// Bootstrap: load config + root tree, wire mode toggle and search.
import { api } from "./api.js";
import { loadRoot } from "./browse.js";
import { initOrganize, setMode } from "./organize.js";
import { initSearch } from "./search.js";

let cfg = null;

const THEME_KEY = "labOrganizer.theme";
function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "cream";
}
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  const dark = theme === "dark";
  btn.textContent = dark ? "☀" : "☾";
  btn.title = dark ? "Switch to light mode" : "Switch to dark mode";
  btn.setAttribute("aria-label", btn.title);
}
function initTheme() {
  // The inline head script already set data-theme (no-flash); reflect it on the
  // button, then let the toggle flip + persist the choice.
  applyTheme(currentTheme());
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "cream" : "dark";
    try { localStorage.setItem(THEME_KEY, next); } catch { /* ignore */ }
    applyTheme(next);
  });
}

async function boot() {
  initTheme();
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
