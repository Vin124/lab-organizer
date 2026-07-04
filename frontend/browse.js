// Nested-box tree view (paper-notebook design): server → project cards → user →
// folder → file chips. Depth maps to a "kind" class; palettes flow down via
// inherited CSS custom props set on each project card. Top-level project cards are
// freely movable/resizable on a canvas, persisted to localStorage. Pure rendering
// + lazy expand; all data comes from the real /api endpoints.
import { api } from "./api.js";
import { typeMeta, humanSize } from "./util.js";

const canvas = document.getElementById("canvas");
const breadcrumb = document.getElementById("breadcrumb");
const PALETTES = ["pal-rose", "pal-sky", "pal-mint", "pal-butter", "pal-lavender"];
const LAYOUT_KEY = "labOrganizer.layout.v1";

let viewRoot = null;

export function getViewRoot() { return viewRoot; }

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- free-layout persistence ----
function loadLayout() {
  try { const o = JSON.parse(localStorage.getItem(LAYOUT_KEY)); if (o && typeof o === "object") return o; }
  catch { /* ignore */ }
  return {};
}
let layout = loadLayout();
function saveLayout() { try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); } catch { /* ignore */ } }
function defaultPos(i) { return { x: (i % 2) * 508 + 8, y: Math.floor(i / 2) * 392 + 8, w: 476 }; }
function getL(path, i) {
  if (!layout[path]) layout[path] = defaultPos(i);
  return layout[path];
}
export function resetLayout() {
  for (const k of Object.keys(layout)) delete layout[k];
  saveLayout();
  loadRoot(viewRoot);
}

// ---- load + render ----
export async function loadRoot(path) {
  canvas.innerHTML = '<div class="loading">Loading…</div>';
  const node = await api.tree(path, 2); // projects + their children in one payload
  viewRoot = node.path;
  canvas.innerHTML = "";
  canvas.appendChild(renderNode(node, 0, true));
  renderBreadcrumb(node.path);
  requestAnimationFrame(recomputeCanvas);
}

export function renderNode(node, depth, isRoot = false) {
  if (node.type === "file") return renderChip(node);

  const kind = depth === 0 ? "server" : depth === 1 ? "project" : depth === 2 ? "user" : "folder";
  const el = document.createElement("div");
  el.className = `node dir ${kind}`;
  if (depth === 1) el.classList.add(PALETTES[paletteIndex(node.path) % PALETTES.length]);
  el.dataset.path = node.path;
  el.dataset.type = "dir";
  el.dataset.name = node.name;
  el.dataset.depth = String(depth);
  el.dataset.loaded = node.children_loaded ? "1" : "0";
  el.draggable = depth >= 2; // user/folder draggable; server/project move via grip
  // Root always visible; project cards open by default when their children
  // came down in the payload. Deeper folders start collapsed (lazy expand).
  const open = isRoot || (depth === 1 && Boolean(node.children));
  if (open) el.classList.add("open");

  const head = document.createElement("div");
  head.className = "node-head";
  head.innerHTML =
    `<span class="caret">${open ? "–" : "+"}</span>` +
    `<span class="marker"></span>` +
    `<span class="node-name">${escapeHtml(isRoot ? rootLabel(node) : node.name)}</span>` +
    `<span class="node-meta">${metaText(node)}</span>`;
  el.appendChild(head);
  if (node.size === undefined) fillStats(el, head);

  // server gets a Reset-layout button; project cards get a move grip.
  if (kind === "server") {
    const reset = document.createElement("button");
    reset.className = "reset-btn"; reset.type = "button"; reset.textContent = "Reset layout";
    reset.title = "Restore the default arrangement";
    reset.addEventListener("click", (e) => { e.stopPropagation(); resetLayout(); });
    head.appendChild(reset);
  } else if (kind === "project") {
    const grip = document.createElement("span");
    grip.className = "grip"; grip.textContent = "⠿"; grip.title = "Drag to move this card";
    grip.addEventListener("pointerdown", (e) => startMove(e, el));
    head.appendChild(grip);
  }

  const body = document.createElement("div");
  body.className = kind === "server" ? "node-body proj-canvas" : "node-body";
  el.appendChild(body);
  if (node.children) renderChildren(body, node, depth);

  head.addEventListener("click", (e) => {
    if (e.target.closest(".chip") || e.target.closest(".reset-btn") || e.target.closest(".grip")) return;
    toggle(el, depth);
  });

  if (kind === "project") positionCard(el);
  return el;
}

function renderChildren(body, node, depth) {
  body.innerHTML = "";
  appendChildren(body, node, depth);
  body.dataset.rendered = "1";
}

function appendChildren(body, node, depth) {
  const old = body.querySelector(":scope > .more");
  if (old) old.remove();
  for (const child of node.children) body.appendChild(renderNode(child, depth + 1));
  if (node.truncated) {
    const more = document.createElement("button");
    more.type = "button"; more.className = "more";
    more.textContent = `+ ${node.remaining} more — click to load`;
    more.addEventListener("click", async (e) => {
      e.stopPropagation();
      more.disabled = true; more.textContent = "Loading…";
      try {
        const next = await api.expand(body.closest(".node").dataset.path, node.next_offset);
        appendChildren(body, next, depth);
        requestAnimationFrame(recomputeCanvas);
      } catch (err) { more.disabled = false; more.textContent = `Error: ${err.message} — retry`; }
    });
    body.appendChild(more);
  }
}

async function toggle(el, depth) {
  const opening = !el.classList.contains("open");
  el.classList.toggle("open");
  requestAnimationFrame(recomputeCanvas);
  el.querySelector(":scope > .node-head .caret").textContent = opening ? "–" : "+";
  if (!opening) return;

  const body = el.querySelector(":scope > .node-body");
  if (body.dataset.rendered === "1" || el.dataset.loaded === "1") return;
  body.innerHTML = '<div class="loading">Loading…</div>';
  try {
    const node = await api.expand(el.dataset.path);
    renderChildren(body, node, Number(el.dataset.depth));
    el.dataset.loaded = "1";
    requestAnimationFrame(recomputeCanvas);
  } catch (err) {
    body.innerHTML = `<div class="loading">Error: ${escapeHtml(err.message)}</div>`;
  }
}

function renderChip(file) {
  const t = typeMeta(file.ext);
  const chip = document.createElement("div");
  chip.className = "chip";
  chip.dataset.path = file.path;
  chip.dataset.type = "file";
  chip.dataset.name = file.name;
  chip.draggable = true;
  chip.style.setProperty("--type", t.color);
  chip.title = file.name;
  chip.innerHTML =
    `<span class="fmark"></span>` +
    `<span class="fname">${escapeHtml(file.name)}</span>` +
    `<span class="ftag">${escapeHtml(t.label)}</span>` +
    `<span class="fsize">${humanSize(file.size)}</span>`;
  return chip;
}

// ---- meta (lazy recursive size/count), breadcrumb, palette ----
function rootLabel(node) {
  return node.name || node.path || "root";
}
function metaText(node) {
  if (node.size === undefined) return "…";
  return `${node.item_count ?? 0} items · ${humanSize(node.size)}`;
}

const STATS_MAX = 5;
let statsActive = 0;
const statsQueue = [];
function pumpStats() {
  while (statsActive < STATS_MAX && statsQueue.length) {
    const job = statsQueue.shift();
    statsActive += 1;
    job().finally(() => { statsActive -= 1; pumpStats(); });
  }
}
function fillStats(el, head) {
  statsQueue.push(async () => {
    const meta = head.querySelector(".node-meta");
    if (!meta) return;
    try {
      const s = await api.dirStats(el.dataset.path);
      meta.textContent = `${s.item_count ?? 0} items · ${humanSize(s.size)}`;
    } catch { meta.textContent = "—"; }
  });
  pumpStats();
}

// Stable palette index per project path (so colors don't shuffle on re-render).
const palMap = new Map();
function paletteIndex(path) {
  if (!palMap.has(path)) palMap.set(path, palMap.size);
  return palMap.get(path);
}

function renderBreadcrumb(path) {
  breadcrumb.innerHTML = "";
  const sep = path.includes("\\") ? "\\" : "/";
  const segs = path.split(sep);
  let cur = "";
  const crumbs = [];
  segs.forEach((s, i) => {
    if (!s) { if (i === 0) cur = sep; return; }
    cur = cur && cur !== sep ? cur + sep + s : (cur === sep ? sep + s : s);
    crumbs.push({ label: s, full: cur });
  });
  crumbs.forEach((c, i) => {
    if (i) { const sp = document.createElement("span"); sp.className = "sep"; sp.textContent = "›"; breadcrumb.appendChild(sp); }
    const a = document.createElement("a");
    a.textContent = c.label;
    if (i === crumbs.length - 1) a.className = "here";
    a.onclick = () => loadRoot(c.full);
    breadcrumb.appendChild(a);
  });
}

// ---- free layout: position, move, resize, canvas sizing ----
function positionCard(el) {
  const i = paletteIndex(el.dataset.path);
  const L = getL(el.dataset.path, i);
  el.classList.add("positioned");
  el.style.left = L.x + "px";
  el.style.top = L.y + "px";
  el.style.width = L.w + "px";
  el.style.height = "";
  if (L.h) { el.style.minHeight = L.h + "px"; }
  addHandles(el);
}

function addHandles(el) {
  const specs = [
    ["e", { top: "16px", bottom: "16px", right: "-4px", width: "7px", cursor: "ew-resize", opacity: ".3" }],
    ["w", { top: "16px", bottom: "16px", left: "-4px", width: "7px", cursor: "ew-resize", opacity: ".3" }],
    ["s", { left: "16px", right: "16px", bottom: "-4px", height: "7px", cursor: "ns-resize", opacity: ".3" }],
    ["n", { left: "16px", right: "16px", top: "-4px", height: "7px", cursor: "ns-resize", opacity: ".3" }],
    ["se", { right: "-5px", bottom: "-5px", width: "13px", height: "13px", cursor: "nwse-resize", opacity: ".55" }],
    ["sw", { left: "-5px", bottom: "-5px", width: "13px", height: "13px", cursor: "nesw-resize", opacity: ".55" }],
    ["ne", { right: "-5px", top: "-5px", width: "13px", height: "13px", cursor: "nesw-resize", opacity: ".55" }],
    ["nw", { left: "-5px", top: "-5px", width: "13px", height: "13px", cursor: "nwse-resize", opacity: ".55" }],
  ];
  for (const [type, css] of specs) {
    const h = document.createElement("div");
    h.className = "rsz";
    Object.assign(h.style, css);
    h.addEventListener("pointerdown", (e) => startResize(e, el, type));
    el.appendChild(h);
  }
}

let drag = null;
function startMove(e, el) {
  e.preventDefault(); e.stopPropagation();
  const L = getL(el.dataset.path, paletteIndex(el.dataset.path));
  drag = { el, mode: "move", sx: e.clientX, sy: e.clientY, ox: L.x, oy: L.y };
  el.classList.add("active");
  try { e.target.setPointerCapture(e.pointerId); } catch { /* ignore */ }
}
function startResize(e, el, type) {
  e.preventDefault(); e.stopPropagation();
  const L = getL(el.dataset.path, paletteIndex(el.dataset.path));
  drag = { el, mode: "resize", type, sx: e.clientX, sy: e.clientY,
    ox: L.x, oy: L.y, ow: L.w, oh: L.h || el.offsetHeight };
  el.classList.add("active");
  try { e.target.setPointerCapture(e.pointerId); } catch { /* ignore */ }
}
function onPointerMove(e) {
  if (!drag) return;
  const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
  const path = drag.el.dataset.path;
  const L = Object.assign({}, layout[path]);
  if (drag.mode === "move") {
    L.x = Math.max(0, Math.round(drag.ox + dx));
    L.y = Math.max(0, Math.round(drag.oy + dy));
  } else {
    const MINW = 252, MINH = 120;
    let x = drag.ox, y = drag.oy, w = drag.ow, h = drag.oh;
    if (drag.type.includes("e")) w = drag.ow + dx;
    if (drag.type.includes("w")) { w = drag.ow - dx; x = drag.ox + dx; }
    if (drag.type.includes("s")) h = drag.oh + dy;
    if (drag.type.includes("n")) { h = drag.oh - dy; y = drag.oy + dy; }
    if (w < MINW) { if (drag.type.includes("w")) x = drag.ox + (drag.ow - MINW); w = MINW; }
    if (h < MINH) { if (drag.type.includes("n")) y = drag.oy + (drag.oh - MINH); h = MINH; }
    if (x < 0) { if (drag.type.includes("w")) w += x; x = 0; }
    if (y < 0) { if (drag.type.includes("n")) h += y; y = 0; }
    L.x = Math.round(x); L.y = Math.round(y); L.w = Math.round(w); L.h = Math.round(h);
  }
  layout[path] = L;
  drag.el.style.left = L.x + "px";
  drag.el.style.top = L.y + "px";
  drag.el.style.width = L.w + "px";
  drag.el.style.height = "";
  if (L.h) drag.el.style.minHeight = L.h + "px";
  recomputeCanvas();
}
function onPointerUp() {
  if (!drag) return;
  drag.el.classList.remove("active");
  drag = null;
  saveLayout();
  recomputeCanvas();
}
window.addEventListener("pointermove", onPointerMove);
window.addEventListener("pointerup", onPointerUp);

function recomputeCanvas() {
  const cv = canvas.querySelector(".proj-canvas");
  if (!cv) return;
  let maxR = 600, maxB = 460;
  for (const el of cv.querySelectorAll(":scope > .node.project")) {
    maxR = Math.max(maxR, el.offsetLeft + el.offsetWidth);
    maxB = Math.max(maxB, el.offsetTop + el.offsetHeight);
  }
  cv.style.width = (maxR + 36) + "px";
  cv.style.height = (maxB + 36) + "px";
}
