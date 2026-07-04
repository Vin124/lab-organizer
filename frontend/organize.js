// Organize mode: drag files/folders, queue moves client-side, analyze, preview,
// execute, undo. The client only ever proposes {src,dst} pairs — the server builds
// and runs the commands. Rendering follows the paper-notebook design (rail Checks +
// Queued moves, terminal command modal, success toast).
import { api } from "./api.js";
import { dirname } from "./util.js";
import { escapeHtml } from "./browse.js";

let config = null;
const moves = new Map(); // src -> { src, dst, type, name, dstPath }
let warnings = [];
const dismissed = new Set();
let toastTimer = null;

const $ = (id) => document.getElementById(id);

export function initOrganize(cfg) {
  config = cfg;
  wireDnd();
  wirePanel();
  wireModals();
  wireUndo();
  refreshUndo();
}

export function setMode(mode) {
  const organize = mode === "organize";
  document.body.classList.toggle("organize", organize);
  $("organize-panel").hidden = !organize;
  $("queue-head").hidden = !organize;
}

// ---- path helpers ----
function sepOf(p) { return p.includes("\\") ? "\\" : "/"; }
function join(dir, name) { return dir.replace(/[/\\]+$/, "") + sepOf(dir) + name; }
function isAncestor(anc, p) { return p === anc || p.startsWith(anc.replace(/[/\\]+$/, "") + sepOf(anc)); }

// ---- drag & drop (delegated on the canvas) ----
function wireDnd() {
  const canvas = $("canvas");

  canvas.addEventListener("dragstart", (e) => {
    if (!document.body.classList.contains("organize")) return;
    const el = e.target.closest(".chip, .node.dir");
    if (!el || !el.draggable) { e.preventDefault(); return; }
    const payload = { path: el.dataset.path, type: el.dataset.type, name: el.dataset.name };
    e.dataTransfer.setData("text/plain", JSON.stringify(payload));
    e.dataTransfer.effectAllowed = "move";
    el.classList.add("dragging");
  });

  canvas.addEventListener("dragend", (e) => {
    const el = e.target.closest(".chip, .node.dir");
    if (el) el.classList.remove("dragging");
    canvas.querySelectorAll(".drop-target").forEach((n) => n.classList.remove("drop-target"));
  });

  canvas.addEventListener("dragover", (e) => {
    if (!document.body.classList.contains("organize")) return;
    const dir = e.target.closest(".node.dir");
    if (!dir) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    canvas.querySelectorAll(".drop-target").forEach((n) => n.classList.remove("drop-target"));
    dir.classList.add("drop-target");
  });

  canvas.addEventListener("dragleave", (e) => {
    const dir = e.target.closest(".node.dir");
    if (dir && !dir.contains(e.relatedTarget)) dir.classList.remove("drop-target");
  });

  canvas.addEventListener("drop", (e) => {
    if (!document.body.classList.contains("organize")) return;
    const dir = e.target.closest(".node.dir");
    if (!dir) return;
    e.preventDefault();
    dir.classList.remove("drop-target");
    let payload;
    try { payload = JSON.parse(e.dataTransfer.getData("text/plain")); } catch { return; }
    queueMove(payload, dir.dataset.path);
  });
}

function queueMove(item, dstDir) {
  const { path: src, type, name } = item;
  if (!src || !dstDir) return;
  if (isAncestor(src, dstDir)) return; // can't move a folder into itself
  if (dirname(src) === dstDir.replace(/[/\\]+$/, "")) return; // already there

  moves.set(src, { src, dst: dstDir, type, name, dstPath: join(dstDir, name) });
  markPending(src);
  refresh();
}

function markPending(src) {
  const el = $("canvas").querySelector(`[data-path="${cssEscape(src)}"]`);
  if (el) el.classList.add("ghost-removed");
}
function unmarkPending(src) {
  const el = $("canvas").querySelector(`[data-path="${cssEscape(src)}"]`);
  if (el) el.classList.remove("ghost-removed");
}
function cssEscape(s) { return (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/["\\]/g, "\\$&"); }

// ---- panel ----
function wirePanel() {
  $("clear-btn").addEventListener("click", clearAll);
  $("preview-btn").addEventListener("click", openPreview);
}

function clearAll() {
  for (const src of moves.keys()) unmarkPending(src);
  moves.clear();
  warnings = [];
  dismissed.clear();
  refresh();
}

function refresh() {
  renderMoveList();
  analyze();
}

function moveList() {
  return [...moves.values()].map((m) => ({ src: m.src, dst: m.dst, type: m.type }));
}

function renderMoveList() {
  const list = $("move-list");
  list.innerHTML = "";
  for (const m of moves.values()) {
    const li = document.createElement("li");
    const mark = document.createElement("span");
    mark.className = m.type === "dir" ? "mv-mark dir" : "mv-mark";
    const path = document.createElement("div");
    path.className = "mv-path";
    path.title = `${m.src} → ${m.dstPath}`;
    path.innerHTML =
      `<div class="mv-name">${escapeHtml(m.name)}</div>` +
      `<div class="mv-dest"><span class="arr">→</span> ${escapeHtml(m.dstPath)}</div>`;
    const x = document.createElement("button");
    x.className = "x-btn"; x.textContent = "×"; x.title = "Remove";
    x.onclick = () => { moves.delete(m.src); unmarkPending(m.src); refresh(); };
    li.append(mark, path, x);
    list.appendChild(li);
  }
  $("move-count").textContent = String(moves.size);
  $("preview-btn").disabled = moves.size === 0;
  $("moves-section").hidden = moves.size === 0;
  updateRailEmpty();
}

// ---- analyze (dependency + collision warnings) ----
async function analyze() {
  if (moves.size === 0) { warnings = []; renderWarnings(); return; }
  try {
    const res = await api.analyze(moveList());
    warnings = res.warnings || [];
  } catch { warnings = []; }
  renderWarnings();
}

function activeWarnings() { return warnings.filter((w, i) => !dismissed.has(warnKey(w, i))); }
function warnKey(w, i) { return `${w.file}|${w.kind}|${i}`; }
function hasErrors() { return activeWarnings().some((w) => w.severity === "error"); }

function renderWarnings() {
  const list = $("warn-list");
  list.innerHTML = "";
  const active = activeWarnings();
  warnings.forEach((w, i) => {
    if (dismissed.has(warnKey(w, i))) return;
    const li = document.createElement("li");
    li.className = `sev-${w.severity}`;
    const dot = document.createElement("span"); dot.className = "warn-dot";
    const text = document.createElement("div"); text.className = "warn-text";
    text.innerHTML =
      `<strong>${escapeHtml(w.message)}</strong>` +
      `<div class="warn-tag">${escapeHtml(w.kind)} · ${escapeHtml(w.file || "")}</div>`;
    const actions = document.createElement("div");
    actions.className = "warn-actions";
    const ask = document.createElement("button");
    ask.className = "ask"; ask.textContent = "Ask AI";
    ask.onclick = () => openAi(`Warning on ${w.file}: ${w.message}\nMove plan: ${JSON.stringify(moveList(), null, 2)}`);
    const dis = document.createElement("button");
    dis.className = "dismiss"; dis.textContent = "Dismiss";
    dis.onclick = () => { dismissed.add(warnKey(w, i)); renderWarnings(); };
    actions.append(ask, dis);
    const wrap = document.createElement("div"); wrap.className = "warn-msg";
    wrap.append(dot, text);
    text.appendChild(actions);
    li.appendChild(wrap);
    list.appendChild(li);
  });

  const errCount = active.filter((w) => w.severity === "error").length;
  const warnCount = active.length - errCount;
  const errBadge = $("err-badge");
  errBadge.hidden = errCount === 0;
  errBadge.textContent = `${errCount} error`;
  const warnBadge = $("warn-count");
  warnBadge.hidden = active.length === 0;
  warnBadge.textContent = `${warnCount} warn`;
  $("checks-section").hidden = active.length === 0;
  updateRailEmpty();
}

function updateRailEmpty() {
  $("rail-empty").hidden = !(moves.size === 0 && activeWarnings().length === 0);
}

// ---- preview + execute modal ----
function wireModals() {
  $("modal-cancel").addEventListener("click", () => ($("modal").hidden = true));
  $("modal-confirm").addEventListener("click", execute);
  $("force-check").addEventListener("change", updateConfirmState);
  $("ai-cancel").addEventListener("click", () => ($("ai-modal").hidden = true));
  $("ai-send").addEventListener("click", sendAi);
}

async function openPreview() {
  if (moves.size === 0) return;
  const modal = $("modal");
  $("modal-title").textContent = "Review commands";
  $("modal-results").innerHTML = "";
  $("modal-commands").textContent = "Loading…";
  $("force-check").checked = false;
  modal.hidden = false;
  try {
    const res = await api.preview(moveList());
    $("modal-commands").textContent = (res.commands || []).map((c) => "$ " + c).join("\n");
  } catch (e) {
    $("modal-commands").textContent = "Error building preview: " + e.message;
  }
  $("force-row").hidden = !hasErrors();
  updateConfirmState();
}

function updateConfirmState() {
  const blocked = hasErrors() && !$("force-check").checked;
  $("modal-confirm").disabled = blocked;
  $("modal-confirm").title = blocked ? "Resolve errors or check Override" : "";
}

async function execute() {
  const btn = $("modal-confirm");
  btn.disabled = true;
  const results = $("modal-results");
  results.innerHTML = "Running…";
  try {
    const res = await api.execute(moveList(), true, $("force-check").checked);
    const rows = res.results || [];
    const okCount = rows.filter((r) => r.ok).length;
    const failed = rows.filter((r) => !r.ok);
    for (const r of rows) if (r.ok) moves.delete(r.src);

    if (failed.length === 0) {
      $("modal").hidden = true;
      showToast(`Moved ${okCount} item${okCount === 1 ? "" : "s"} · logged`);
    } else {
      results.innerHTML = "";
      for (const r of rows) {
        const div = document.createElement("div");
        div.className = r.ok ? "ok" : "fail";
        div.textContent = (r.ok ? "✓ " : "✗ ") + r.src + (r.error ? ` — ${r.error}` : "");
        results.appendChild(div);
      }
      $("modal-title").textContent = "Results";
      btn.disabled = false;
    }
    setTimeout(() => { import("./browse.js").then((m) => m.loadRoot(m.getViewRoot())); }, 200);
    refresh();
    refreshUndo();
  } catch (e) {
    results.innerHTML = `<div class="fail">Execute failed: ${escapeHtml(e.message)}</div>`;
    btn.disabled = false;
  }
}

// ---- toast ----
function showToast(msg) {
  $("toast-msg").textContent = msg;
  $("toast").hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, 2800);
}

// ---- undo last batch ----
let undoState = null;

function wireUndo() {
  $("undo-btn").addEventListener("click", openUndo);
  $("undo-cancel").addEventListener("click", () => ($("undo-modal").hidden = true));
  $("undo-confirm").addEventListener("click", doUndo);
}

async function refreshUndo() {
  const section = $("undo-section");
  if (config && config.read_only) { section.hidden = true; return; }
  try { undoState = await api.undoInfo(); } catch { undoState = null; }
  section.hidden = !(undoState && undoState.available);
  if (undoState && undoState.available) $("undo-btn").textContent = `↩ Undo last move (${undoState.count})`;
}

function openUndo() {
  if (!undoState || !undoState.available) return;
  $("undo-summary").textContent =
    `This reverses the last executed batch of ${undoState.count} move(s), putting each file ` +
    `back where it came from. It never overwrites — if an original spot is now occupied the whole undo is refused.`;
  $("undo-list").textContent = undoState.moves.map((m) => `${m.src}  →  ${m.dst}`).join("\n");
  $("undo-results").innerHTML = "";
  $("undo-confirm").disabled = false;
  $("undo-title").textContent = "Undo last move batch";
  $("undo-modal").hidden = false;
}

async function doUndo() {
  const btn = $("undo-confirm");
  btn.disabled = true;
  const results = $("undo-results");
  results.innerHTML = "Undoing…";
  try {
    const res = await api.undo(true);
    results.innerHTML = "";
    if (res.error && (!res.results || res.results.length === 0)) {
      results.innerHTML = `<div class="fail">${escapeHtml(res.error)}</div>`;
    }
    for (const r of res.results || []) {
      const div = document.createElement("div");
      div.className = r.ok ? "ok" : "fail";
      div.textContent = (r.ok ? "✓ " : "✗ ") + r.src + (r.error ? ` — ${r.error}` : "");
      results.appendChild(div);
    }
    if (res.undone) { $("undo-modal").hidden = true; showToast("Undid last move batch · logged"); }
    else { $("undo-title").textContent = "Undo incomplete"; }
    setTimeout(() => { import("./browse.js").then((m) => m.loadRoot(m.getViewRoot())); }, 200);
    refreshUndo();
  } catch (e) {
    results.innerHTML = `<div class="fail">Undo failed: ${escapeHtml(e.message)}</div>`;
    btn.disabled = false;
  }
}

// ---- ask AI ----
function openAi(context) {
  $("ai-context").textContent = context;
  $("ai-answer").textContent = "";
  $("ai-question").value = "";
  $("ai-modal").hidden = false;
  if (!config.ai_enabled) $("ai-answer").textContent = "AI not configured (set ANTHROPIC_API_KEY).";
}

async function sendAi() {
  const q = $("ai-question").value.trim();
  if (!q) return;
  $("ai-answer").textContent = "Thinking…";
  try {
    const res = await api.askAi($("ai-context").textContent, q);
    $("ai-answer").textContent = res.answer || "(no answer)";
  } catch (e) {
    $("ai-answer").textContent = "Error: " + e.message;
  }
}
