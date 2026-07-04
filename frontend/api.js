// Thin fetch wrappers. All paths are server-validated; client only proposes.

async function jget(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
async function jpost(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

export const api = {
  config: () => jget("/api/config"),
  tree: (path, depth = 3) =>
    jget(`/api/tree?depth=${depth}` + (path ? `&path=${encodeURIComponent(path)}` : "")),
  expand: (path, offset = 0) =>
    jget(`/api/tree/expand?path=${encodeURIComponent(path)}&offset=${offset}`),
  dirStats: (path) => jget(`/api/dir-stats?path=${encodeURIComponent(path)}`),
  search: (q, path) =>
    jget(`/api/search?q=${encodeURIComponent(q)}` + (path ? `&path=${encodeURIComponent(path)}` : "")),
  analyze: (moves) => jpost("/api/analyze-moves", { moves }),
  preview: (moves) => jpost("/api/preview-moves", { moves }),
  execute: (moves, confirmed, force) =>
    jpost("/api/execute-moves", { moves, confirmed, force }),
  undoInfo: () => jget("/api/undo-info"),
  undo: (confirmed) => jpost("/api/undo", { confirmed }),
  askAi: (context, question) => jpost("/api/ask-ai", { context, question }),
};
