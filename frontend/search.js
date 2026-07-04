// Tree-wide name search. Type to find files/folders anywhere under the root;
// click a hit to jump to it in Browse mode and highlight it briefly.
import { api } from "./api.js";
import { escapeHtml, loadRoot } from "./browse.js";
import { dirname } from "./util.js";

const DEBOUNCE_MS = 250;

export function initSearch() {
  const input = document.getElementById("search-input");
  const results = document.getElementById("search-results");
  let timer = null;

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (!q) { hide(results); return; }
    timer = setTimeout(() => runSearch(q, results), DEBOUNCE_MS);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { hide(results); input.blur(); }
  });
  // click outside closes the dropdown
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search")) hide(results);
  });
}

function hide(results) {
  results.hidden = true;
  results.innerHTML = "";
}

async function runSearch(q, results) {
  results.hidden = false;
  results.innerHTML = '<div class="search-empty">Searching…</div>';
  let data;
  try {
    data = await api.search(q);
  } catch (e) {
    results.innerHTML = `<div class="search-empty">Error: ${escapeHtml(e.message)}</div>`;
    return;
  }
  renderResults(q, data, results);
}

function renderResults(q, data, results) {
  const hits = data.hits || [];
  results.innerHTML = "";
  if (!hits.length) {
    results.innerHTML = `<div class="search-empty">No matches for "${escapeHtml(q)}"</div>`;
    return;
  }
  for (const h of hits) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "search-hit";
    item.innerHTML =
      `<span class="hit-icon">${h.type === "dir" ? "📁" : "📄"}</span>` +
      `<span class="hit-name">${escapeHtml(h.name)}</span>` +
      `<span class="hit-path">${escapeHtml(h.path)}</span>`;
    item.addEventListener("click", () => jumpTo(h, results));
    results.appendChild(item);
  }
  if (data.truncated) {
    const note = document.createElement("div");
    note.className = "search-empty";
    note.textContent = `Showing the first ${hits.length} — refine your search for more.`;
    results.appendChild(note);
  }
}

async function jumpTo(hit, results) {
  hide(results);
  // Search is a Browse action — make sure we're in Browse mode.
  const browseBtn = document.getElementById("mode-browse");
  if (browseBtn && !browseBtn.classList.contains("active")) browseBtn.click();
  // Root the view at the hit (a dir) or its parent (a file) so it's visible.
  const target = hit.type === "dir" ? hit.path : dirname(hit.path);
  await loadRoot(target);
  highlight(hit.path);
}

function highlight(path) {
  const canvas = document.getElementById("canvas");
  const sel = (window.CSS && CSS.escape) ? CSS.escape(path) : path.replace(/["\\]/g, "\\$&");
  const el = canvas.querySelector(`[data-path="${sel}"]`);
  if (!el) return;
  el.classList.add("search-target");
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  setTimeout(() => el.classList.remove("search-target"), 2500);
}
