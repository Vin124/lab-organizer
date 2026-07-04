// Small shared helpers: file-type meta (diamond color + tag), human sizes, paths.

// Color + short label per extension (mirrors the design's type palette).
const TYPES = {
  py: { color: "#5B8DEF", label: "py" },
  csv: { color: "#3FB27F", label: "csv" },
  log: { color: "#9AA0A6", label: "log" },
  txt: { color: "#9AA0A6", label: "txt" },
  md: { color: "#9AA0A6", label: "md" },
  sh: { color: "#E0A14B", label: "sh" },
  ipynb: { color: "#E8833A", label: "ipynb" },
  yaml: { color: "#A07CDB", label: "yml" },
  yml: { color: "#A07CDB", label: "yml" },
  toml: { color: "#A07CDB", label: "toml" },
  json: { color: "#A07CDB", label: "json" },
  docx: { color: "#5566C9", label: "docx" },
  pdf: { color: "#C9544B", label: "pdf" },
};

// `ext` is server-sanitized to [a-z0-9]; default safely for anything unknown.
export function typeMeta(ext) {
  const e = /^[a-z0-9]+$/.test(ext || "") ? ext : "";
  return TYPES[e] || { color: "#9AA0A6", label: e || "file" };
}

export function humanSize(bytes) {
  if (bytes == null) return "";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let n = bytes, i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i === 0 ? n : n.toFixed(1)) + " " + u[i];
}

export function basename(p) {
  const parts = p.replace(/[/\\]+$/, "").split(/[/\\]/);
  return parts[parts.length - 1] || p;
}

export function dirname(p) {
  const cleaned = p.replace(/[/\\]+$/, "");
  const idx = Math.max(cleaned.lastIndexOf("/"), cleaned.lastIndexOf("\\"));
  return idx > 0 ? cleaned.slice(0, idx) : cleaned;
}
