/* Audiobook Converter — Vanilla JS frontend */
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  uploads: [],        // WYSIWYG list: [{id,name,size,info,lastModified,order,kind:'upload'|'lib'}]
  libMeta: {},        // "lib:<path>" -> {title,track,album,artist,composer,duration}
  libPath: "",
  libRoots: [],
  presets: [],
  jobs: {},
  coverUploadId: null,
  sort: { key: null, dir: 1 },     // null key = 上传顺序
  columns: { name: true, title: true, track: true, album: true, artist: true,
             composer: true, duration: true, size: true, mtime: false },
};

const COLUMNS = [
  { key: "name",     label: "文件名" },
  { key: "title",    label: "标题" },
  { key: "track",    label: "Track" },
  { key: "album",    label: "专辑" },
  { key: "artist",   label: "作者" },
  { key: "composer", label: "演播者" },
  { key: "duration", label: "时长" },
  { key: "size",     label: "大小" },
  { key: "mtime",    label: "修改时间", def: false },
];

const AUDIO_EXT = new Set([".mp3", ".m4a", ".m4b", ".aac", ".flac", ".ogg",
                           ".opus", ".wav", ".wma", ".aiff", ".mka"]);
const M4B_CODECS = new Set(["aac", "libfdk_aac"]);
const DEFAULT_CODEC = {
  mp3: "libmp3lame", m4a: "aac", m4b: "aac", opus: "libopus",
  ogg: "libvorbis", flac: "flac", wav: "pcm_s16le",
};

const escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const fmtSize = (b) => {
  if (b == null) return "";
  if (b > 1e9) return (b / 1e9).toFixed(2) + " GB";
  if (b > 1e6) return (b / 1e6).toFixed(1) + " MB";
  if (b > 1e3) return Math.round(b / 1e3) + " KB";
  return b + " B";
};

const fmtDur = (s) => {
  if (!s) return "";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.round(s % 60);
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
};

/* ============ session persistence (F3) ============ */

const SESSION_KEY = "hac.session.v1";

let _saveTimer = null;
function saveSession() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(_saveSessionNow, 200);
}

function _saveSessionNow() {
  try {
    const libPicks = state.uploads.filter((u) => u.kind === "lib")
      .map((u) => ({ id: u.id, name: u.name, size: u.size }));
    const s = {
      preset: $("preset").value,
      format: $("format").value,
      codec: $("codec").value,
      bitrate: $("bitrate").value,
      samplerate: $("samplerate").value,
      channels: $("channels").value,
      normalize: $("normalize").checked,
      mergeOn: $("merge-on").checked,
      mergeTitle: $("merge-title").value,
      mergeArtist: $("merge-artist").value,
      mergeComposer: $("merge-composer").value,
      metaTitle: $("meta-title").value,
      metaArtist: $("meta-artist").value,
      metaAlbum: $("meta-album").value,
      metaComposer: $("meta-composer").value,
      titleSource: $("title-source").value,
      titlePattern: $("title-pattern").value,
      sort: state.sort,
      columns: state.columns,
      libPicks,
    };
    localStorage.setItem(SESSION_KEY, JSON.stringify(s));
  } catch (e) { /* storage unavailable */ }
}

function restoreSession() {
  let s;
  try { s = JSON.parse(localStorage.getItem(SESSION_KEY) || "null"); } catch (e) { s = null; }
  if (!s) return;
  const setv = (id, v) => { if (v != null) $(id).value = v; };
  setv("preset", s.preset); setv("format", s.format); setv("codec", s.codec);
  setv("bitrate", s.bitrate); setv("samplerate", s.samplerate); setv("channels", s.channels);
  if (s.normalize != null) $("normalize").checked = s.normalize;
  if (s.mergeOn != null) {
    $("merge-on").checked = s.mergeOn;
    $("merge-fields").classList.toggle("hidden", !s.mergeOn);
  }
  setv("merge-title", s.mergeTitle); setv("merge-artist", s.mergeArtist);
  setv("merge-composer", s.mergeComposer);
  setv("meta-title", s.metaTitle); setv("meta-artist", s.metaArtist);
  setv("meta-album", s.metaAlbum); setv("meta-composer", s.metaComposer);
  if (s.titleSource) {
    $("title-source").value = s.titleSource;
    $("title-pattern-row").classList.toggle("hidden", s.titleSource !== "pattern");
    $("meta-title").disabled = s.titleSource !== "inherit";
  }
  setv("title-pattern", s.titlePattern);
  if (s.sort) state.sort = s.sort;
  if (s.columns) state.columns = { ...state.columns, ...s.columns };
  if (Array.isArray(s.libPicks)) {
    for (const p of s.libPicks) {
      if (!state.uploads.some((u) => u.id === p.id))
        state.uploads.push({ ...p, kind: "lib", order: state.uploads.length });
    }
  }
}

let _uploadsFetchSeq = 0;
async function fetchUploads() {
  const seq = ++_uploadsFetchSeq;
  try {
    const res = await (await fetch("/api/uploads")).json();
    if (seq !== _uploadsFetchSeq) return;          // superseded by a newer call
    const known = new Set(state.uploads.map((u) => u.id));
    // cover uploads live in the same server registry — never list them
    const add = res
      .filter((u) => !known.has(u.id) && !(u.info && u.info.kind === "cover"))
      .map((u) => ({ ...u, kind: "upload", order: state.uploads.length }));
    state.uploads.push(...add);
    renderFiles();
  } catch (e) { /* server unreachable */ }
}

/* ============ health & presets ============ */

async function loadHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    const el = $("health-badge");
    el.textContent = `ffmpeg ✓ · ${h.encoders.length} 编码器` +
      (h.presets_disabled ? ` · ${h.presets_disabled} 预设停用` : "");
    el.className = "pill ok";
    el.title = h.ffmpeg + "\n" + h.encoders.join(", ");
  } catch {
    $("health-badge").textContent = "ffmpeg ✗";
    $("health-badge").className = "pill warn";
  }
}

async function loadPresets() {
  const list = await (await fetch("/api/presets")).json();
  state.presets = list;
  const sel = $("preset");
  sel.innerHTML = '<option value="">— 自定义 —</option>';
  for (const p of list) {
    const o = document.createElement("option");
    o.value = p.id;
    o.textContent = p.name + (p.enabled ? "" : `（缺 ${p.requires_encoder}）`);
    o.disabled = !p.enabled;
    sel.appendChild(o);
  }
}

function applyPreset(id) {
  $("preset-hint").textContent = "";
  const p = state.presets.find((x) => x.id === id);
  if (!p) return;
  $("format").value = p.settings.format;
  $("codec").value = p.settings.codec;
  $("bitrate").value = p.settings.bitrate || "";
  $("samplerate").value = p.settings.samplerate || "";
  $("channels").value = p.settings.channels || "";
  if (!p.enabled) $("preset-hint").textContent = p.disabled_reason || "";
}

/* ============ upload with per-file XHR progress ============ */

const hasAudioExt = (name) => AUDIO_EXT.has(name.slice(name.lastIndexOf(".")).toLowerCase());

async function uploadFiles(fileList) {
  // SEQUENTIAL uploads: state.uploads order must equal the user's file order,
  // because it defines the chapter order for M4B merging (WYSIWYG).
  for (const f of fileList) {
    if (!hasAudioExt(f.name)) continue;
    await new Promise((resolve) => {
      const row = document.createElement("div");
      row.className = "uprow";
      row.innerHTML = `<span class="uname">${escapeHtml(f.name)}</span>` +
        `<div class="upbar"><div></div></div><span class="pct">0%</span>`;
      $("upload-progress").appendChild(row);
      const bar = row.querySelector(".upbar > div");
      const pct = row.querySelector(".pct");

      const fd = new FormData();
      fd.append("files", f, f.name);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload");
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const p = Math.round((e.loaded / e.total) * 100);
          bar.style.width = p + "%";
          pct.textContent = p + "%";
        }
      };
      xhr.onload = () => {
        if (xhr.status === 200) {
          const { uploads } = JSON.parse(xhr.responseText);
          for (const u of uploads) {
            u.kind = "upload";
            u.lastModified = f.lastModified;
            u._pushedAt = Date.now();
            u.order = state.uploads.length;   // original upload sequence
          }
          state.uploads.push(...uploads);
          scheduleRender();
          saveSession();
          bar.style.width = "100%";
          pct.textContent = "✓";
        } else {
          let msg = "HTTP " + xhr.status;
          try { msg = JSON.parse(xhr.responseText).detail; } catch (e) {}
          pct.textContent = "✗ " + msg;
        }
        setTimeout(() => { row.remove(); resolve(); }, 300);
      };
      xhr.onerror = () => { pct.textContent = "✗ 网络错误"; resolve(); };
      xhr.send(fd);
    });
  }
}

function readEntriesAll(reader) {
  return new Promise((resolve) => {
    const all = [];
    const step = () => reader.readEntries((batch) => {
      if (!batch.length) return resolve(all);
      all.push(...batch);
      step();
    }, () => resolve(all));
    step();
  });
}

async function collectFilesFromDrop(dt) {
  const entries = [...(dt.items || [])]
    .map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry())
    .filter(Boolean);
  if (!entries.length) return [...dt.files].filter((f) => hasAudioExt(f.name));
  const out = [];
  async function walk(entry, depth) {
    if (depth > 10) return;
    if (entry.isFile) {
      const f = await new Promise((res) => entry.file(res, () => res(null)));
      if (f && hasAudioExt(f.name)) out.push(f);
    } else if (entry.isDirectory) {
      for (const child of await readEntriesAll(entry.createReader()))
        await walk(child, depth + 1);
    }
  }
  for (const en of entries) await walk(en, 0);
  return out;
}

/* ============ unified file table (WYSIWYG) ============ */

let _renderQueued = false;
function scheduleRender() {
  if (_renderQueued) return;
  _renderQueued = true;
  setTimeout(() => { _renderQueued = false; renderFiles(); }, 120);
}

function rowMeta(u) {
  const tags = (u.info && u.info.tags) || {};
  const lib = u.kind === "lib" ? (state.libMeta[u.id] || {}) : {};
  const pick = (t, l) => (l || t || null);
  return {
    title: pick(tags.title, lib.title),
    track: parseTrackTag(tags.track ?? tags.TRCK ?? tags.tracknumber ?? lib.track),
    album: pick(tags.album, lib.album),
    artist: pick(tags.artist, lib.artist),
    composer: pick(tags.composer, lib.composer),
    duration: u.info && u.info.duration ? u.info.duration : (lib.duration || null),
  };
}

function parseTrackTag(raw) {
  if (raw == null) return null;
  const m = String(raw).match(/(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

function naturalName(name) {
  return name.replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

function naturalCompare(a, b) {
  const A = naturalName(a).match(/\d+|\D+/g) || [];
  const B = naturalName(b).match(/\d+|\D+/g) || [];
  for (let k = 0; k < Math.max(A.length, B.length); k++) {
    if (A[k] === undefined) return -1;
    if (B[k] === undefined) return 1;
    const an = /^\d/.test(A[k]), bn = /^\d/.test(B[k]);
    if (an && bn) {
      const d = parseInt(A[k], 10) - parseInt(B[k], 10);
      if (d) return d;
    } else if (an !== bn) {
      return an ? -1 : 1;
    } else {
      const c = A[k].localeCompare(B[k]);
      if (c) return c;
    }
  }
  return 0;
}

function sortUploads() {
  const { key, dir } = state.sort;
  if (!key) {
    state.uploads.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    return;
  }
  const keyed = state.uploads.map((u, i) => ({ u, m: rowMeta(u), i }));
  keyed.sort((x, y) => {
    let d = 0;
    if (key === "name") d = naturalCompare(x.u.name, y.u.name);
    else if (key === "size") d = (x.u.size || 0) - (y.u.size || 0);
    else if (key === "mtime") d = (x.u.lastModified || 0) - (y.u.lastModified || 0);
    else {
      const xv = x.m[key], yv = y.m[key];
      if (key === "track" || key === "duration") {
        const xn = xv == null, yn = yv == null;
        if (xn && yn) d = naturalCompare(x.u.name, y.u.name);
        else if (xn) return 1;
        else if (yn) return -1;
        else d = xv - yv;
      } else {
        const xs = String(xv ?? "").trim(), ys = String(yv ?? "").trim();
        if (!xs && !ys) d = naturalCompare(x.u.name, y.u.name);
        else if (!xs) return 1;
        else if (!ys) return -1;
        else d = xs.localeCompare(ys);
      }
    }
    return (d * dir) || (x.i - y.i);
  });
  state.uploads = keyed.map((k) => k.u);
}

function renderColumnPopover() {
  const pop = $("columns-pop");
  pop.innerHTML = "";
  for (const c of COLUMNS) {
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!state.columns[c.key];
    cb.onchange = () => {
      state.columns[c.key] = cb.checked;
      renderFiles();
      saveSession();
    };
    label.appendChild(cb);
    label.appendChild(document.createTextNode(c.label));
    pop.appendChild(label);
  }
}

function renderFiles() {
  sortUploads();
  const head = $("file-head");
  const tbody = $("file-list");
  const vis = COLUMNS.filter((c) => state.columns[c.key]);

  head.innerHTML = `<th class="nosort">#</th><th class="nosort"></th>` +
    vis.map((c) => {
      let arrow = "";
      if (state.sort.key === c.key) arrow = state.sort.dir === 1 ? " ▲" : " ▼";
      return `<th data-key="${c.key}">${c.label}${arrow}</th>`;
    }).join("") + `<th class="nosort"></th>`;

  head.querySelectorAll("th[data-key]").forEach((th) => {
    th.onclick = () => {
      const k = th.dataset.key;
      if (state.sort.key === k) {
        if (state.sort.dir === 1) state.sort.dir = -1;
        else state.sort = { key: null, dir: 1 };   // third click: back to upload order
      } else state.sort = { key: k, dir: 1 };
      $("btn-sort-reset").classList.toggle("hidden", state.sort.key == null);
      renderFiles();
      saveSession();
    };
  });

  tbody.innerHTML = "";
  $("file-empty").classList.toggle("hidden", state.uploads.length > 0);
  $("file-count").textContent = state.uploads.length ? `（${state.uploads.length} 个）` : "";

  state.uploads.forEach((u, i) => {
    const m = rowMeta(u);
    const tr = document.createElement("tr");
    tr.draggable = true;
    tr.dataset.idx = i;
    const cell = (c) => {
      if (c.key === "name")
        return `<td class="name-cell" title="${escapeHtml(u.name)}">🎵 ${escapeHtml(u.name)}</td>`;
      if (c.key === "duration") return `<td>${fmtDur(m.duration)}</td>`;
      if (c.key === "size") return `<td>${fmtSize(u.size)}</td>`;
      if (c.key === "mtime")
        return `<td>${u.lastModified ? new Date(u.lastModified).toLocaleString() : ""}</td>`;
      return `<td title="${escapeHtml(m[c.key] ?? "")}">${escapeHtml(m[c.key] ?? "")}</td>`;
    };
    tr.innerHTML = `<td class="pos">${i + 1}</td><td class="handle">⠿</td>` +
      vis.map(cell).join("") +
      `<td><button class="del" title="移除">✕</button></td>`;
    tr.querySelector(".del").onclick = () => {
      state.uploads = state.uploads.filter((x) => x.id !== u.id);
      if (state.coverUploadId === u.id) state.coverUploadId = null;
      renderFiles();
      saveSession();
    };
    tr.addEventListener("dragstart", (e) => {
      tr.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(i));
    });
    tr.addEventListener("dragend", () => tr.classList.remove("dragging"));
    tr.addEventListener("dragover", (e) => e.preventDefault());
    tr.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const from = parseInt(e.dataTransfer.getData("text/plain"));
      if (isNaN(from) || from === i) return;
      const arr = state.uploads.slice();
      const [moved] = arr.splice(from, 1);
      arr.splice(Math.min(i, arr.length), 0, moved);
      // dedupe + reindex: the manual sequence becomes the new WYSIWYG baseline
      // (otherwise renderFiles' order-sort would undo the move)
      state.uploads = [...new Map(arr.map((u) => [u.id, u])).values()];
      state.uploads.forEach((u, idx) => { u.order = idx; });
      if (state.sort.key) state.sort = { key: null, dir: 1 };
      $("btn-sort-reset").classList.add("hidden");
      renderFiles();
      saveSession();
    });
    tbody.appendChild(tr);
  });
  updateMergeHint();
}

/* ============ folder drop & pickers ============ */

function wireDrop() {
  const zone = $("col-files");
  zone.addEventListener("dragover", (e) => e.preventDefault());
  zone.addEventListener("drop", async (e) => {
    e.preventDefault();
    const files = await collectFilesFromDrop(e.dataTransfer);
    if (!files.length) { alert("拖拽内容中没有可识别的音频文件"); return; }
    uploadFiles(files);
  });
  $("file-input").onchange = (e) => { uploadFiles([...e.target.files]); e.target.value = ""; };
  $("folder-input").onchange = (e) => {
    const files = [...e.target.files].filter((f) => hasAudioExt(f.name));
    if (!files.length) { alert("所选文件夹中没有可识别的音频文件"); return; }
    uploadFiles(files);
    e.target.value = "";
  };
  $("btn-clear-files").onclick = () => {
    state.uploads = [];
    state.coverUploadId = null;
    renderFiles();
    saveSession();
  };
  $("btn-columns").onclick = (e) => {
    e.stopPropagation();
    $("columns-pop").classList.toggle("hidden");
  };
  document.addEventListener("click", (e) => {
    if (!$("columns-pop").classList.contains("hidden") &&
        !$("columns-pop").contains(e.target) && e.target.id !== "btn-columns")
      $("columns-pop").classList.add("hidden");
  });
  $("btn-sort-reset").onclick = () => {
    state.sort = { key: null, dir: 1 };
    $("btn-sort-reset").classList.add("hidden");
    renderFiles();
    saveSession();
  };
}

/* ============ tabs & library ============ */

function wireTabs() {
  document.querySelectorAll(".tab").forEach((t) => {
    t.onclick = () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
      $("pane-upload").classList.toggle("hidden", t.dataset.tab !== "upload");
      $("panel-library").classList.toggle("hidden", t.dataset.tab !== "library");
      if (t.dataset.tab === "library") loadRoots();
    };
  });
}

async function libLoad(path) {
  const ul = $("lib-list");
  try {
    const res = await fetch("/api/library/list?path=" + encodeURIComponent(path || ""));
    if (res.status === 403) {
      ul.innerHTML = `<li class="empty">⛔ 无权访问（白名单外路径）</li>`;
      return;
    }
    if (!res.ok) { ul.innerHTML = `<li class="empty">HTTP ${res.status}</li>`; return; }
    const data = await res.json();
    state.libPath = data.path;
    $("lib-path").textContent = data.path;
    ul.innerHTML = "";
    if (!data.dirs.length && !data.files.length)
      ul.innerHTML = `<li class="empty">空目录（无音频文件）</li>`;
    for (const d of data.dirs) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="icon">📂</span><span class="name" style="cursor:pointer">${escapeHtml(d.name)}/</span>`;
      li.onclick = () => libLoad(d.path);
      ul.appendChild(li);
    }
    for (const f of data.files) {
      const inList = state.uploads.some((u) => u.id === f.id);
      const li = document.createElement("li");
      li.innerHTML = `<input type="checkbox" class="libpick" data-libid="${escapeHtml(f.id)}" ` +
        `data-libname="${escapeHtml(f.name)}" ${inList ? "checked" : ""}>` +
        `<span class="name">🎵 ${escapeHtml(f.name)}</span><span class="meta">${fmtSize(f.size)}</span>`;
      li.querySelector("input").addEventListener("change", (e) => {
        toggleLibFile({ id: f.id, name: f.name, size: f.size }, e.target.checked);
      });
      ul.appendChild(li);
    }
  } catch (e) {
    $("lib-path").textContent = "加载失败: " + e;
  }
}

function toggleLibFile(f, add) {
  state.uploads = state.uploads.filter((u) => u.id !== f.id);
  if (add) {
    state.uploads.push({ ...f, kind: "lib", order: state.uploads.length });
    ensureLibMeta();
  }
  renderFiles();
  saveSession();
}

async function ensureLibMeta() {
  const missing = state.uploads
    .filter((u) => u.kind === "lib" && !(u.id in state.libMeta))
    .map((u) => u.id.slice(4));
  if (!missing.length) return;
  const res = await fetch("/api/library/probe", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths: missing }),
  });
  if (!res.ok) return;
  const data = await res.json();
  for (const [p, v] of Object.entries(data)) state.libMeta[`lib:${p}`] = v;
}

async function loadRoots() {
  try {
    const res = await (await fetch("/api/library/roots")).json();
    $("lib-roots").textContent = res.roots.join(" ; ");
  } catch (e) { /* ignore */ }
  libLoad("");
}

/* ============ merge helpers ============ */

function updateMergeHint() {
  const n = state.uploads.length;
  const mergeOn = $("merge-on").checked;
  const errCount = renderMergeHints();
  $("merge-hint").textContent = mergeOn
    ? `将按列表顺序合并 ${n} 个文件为一个 .m4b（采用下方编码设置）；章节名取各文件标题标签，缺省用文件名` +
      (n < 2 ? "（⚠ 至少 2 个文件）" : "")
    : `将为 ${n} 个文件各创建一个转码任务`;
  $("btn-start").disabled =
    n === 0 || (mergeOn && n < 2) || (mergeOn && errCount > 0);
}

/* ============ merge compatibility hints ============ */

function mergeCompatErrors() {
  if (!$("merge-on").checked) return {};
  const errs = {};
  const f = $("format").value;
  const codec = $("codec").value || DEFAULT_CODEC[f];
  if (!M4B_CODECS.has(codec)) {
    errs.codec = `M4B 不支持 ${codec}：仅支持 AAC 系（aac / libfdk_aac），Opus/MP3 请用逐文件模式`;
  }
  const p = state.presets.find((x) => x.id === $("preset").value);
  const profile = (p && p.settings.profile) || null;
  if (profile === "aac_he_v2" && $("channels").value === "1") {
    errs.channels = "HE-AAC v2 需要立体声：请把声道设为 2（或保持源）";
  }
  return errs;
}

function renderMergeHints() {
  const errs = mergeCompatErrors();
  $("err-codec").textContent = errs.codec || "";
  $("err-channels").textContent = errs.channels || "";
  return Object.keys(errs).length;
}

/* ============ jobs via SSE ============ */

const STATUS_TXT = {
  queued: "排队", running: "转码中", tagging: "写元数据", merging: "合并中",
  done: "完成", failed: "失败", cancelled: "已取消",
};
const ACTIVE = new Set(["queued", "running", "tagging", "merging"]);

function jobCardHTML(j) {
  const p = (j.progress || 0).toFixed(1);
  let html =
    `<div class="job-top">` +
      `<span class="job-name" title="${escapeHtml(j.output_filename)}">` +
      `${j.mode === "merge" ? "📚 " : ""}${escapeHtml(j.output_filename)}</span>` +
      `<span class="badge ${j.status}">${STATUS_TXT[j.status] || j.status}</span>` +
    `</div>` +
    `<div class="pbar"><div style="width:${p}%"></div></div>` +
    `<div class="small pct-text" style="color:var(--dim)">${p}%</div>`;
  if (j.verify) {
    const v = j.verify;
    html += `<div class="verify">✓ <b>${escapeHtml(v.codec)}</b> · <b>${Math.round((v.bitrate || 0) / 1000)}k</b>` +
      ` · ${v.sample_rate}Hz · ${v.channels}ch` +
      (v.savings_pct != null ? ` · 体积省 <b>${v.savings_pct}%</b>（${fmtSize(v.output_size)} / 源 ${fmtSize(v.source_size)}）` : "") +
      `</div>`;
  }
  if (j.error) html += `<div class="joberr">✗ ${escapeHtml(j.error)}</div>`;
  const acts = [];
  if (j.status === "done") acts.push(`<button class="btn small" data-act="dl" data-id="${j.id}">⬇ 下载</button>`);
  if (j.status === "failed" || j.status === "cancelled")
    acts.push(`<button class="btn small" data-act="retry" data-id="${j.id}">↻ 重试</button>`);
  if (ACTIVE.has(j.status))
    acts.push(`<button class="btn small subtle" data-act="cancel" data-id="${j.id}">✕ 取消</button>`);
  html += `<div class="job-actions">${acts.join("")}</div>`;
  return `<li data-job="${j.id}">${html}</li>`;
}

function bindJobActions(scope) {
  scope.querySelectorAll("[data-act]").forEach((b) => {
    b.onclick = async () => {
      const { act, id } = b.dataset;
      if (act === "dl") location.href = `/api/jobs/${id}/download`;
      else if (act === "retry") await fetch(`/api/jobs/${id}/retry`, { method: "POST" });
      else if (act === "cancel") await fetch(`/api/jobs/${id}`, { method: "DELETE" });
    };
  });
}

function renderJobs() {
  const ul = $("job-list");
  const jobs = Object.values(state.jobs)
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  ul.innerHTML = "";
  if (!jobs.length) {
    ul.innerHTML = `<li class="empty">暂无任务 — 选择文件后点「开始转换」</li>`;
    return;
  }
  for (const j of jobs) ul.insertAdjacentHTML("beforeend", jobCardHTML(j));
  bindJobActions(ul);
}

function updateJobCard(j, prev) {
  const li = document.querySelector(`#job-list li[data-job="${j.id}"]`);
  if (!li) return renderJobs();
  if (prev.status !== j.status) {
    li.outerHTML = jobCardHTML(j);
    bindJobActions($("job-list"));
    return;
  }
  const p = (j.progress || 0).toFixed(1);
  const bar = li.querySelector(".pbar > div");
  if (bar) bar.style.width = p + "%";
  const pct = li.querySelector(".pct-text");
  if (pct) pct.textContent = p + "%";
}

function connectSSE() {
  const es = new EventSource("/api/events");
  es.addEventListener("job.list", (e) => {
    state.jobs = {};
    for (const j of JSON.parse(e.data)) state.jobs[j.id] = j;
    renderJobs();
  });
  es.addEventListener("job.update", (e) => {
    const j = JSON.parse(e.data);
    const prev = state.jobs[j.id];
    state.jobs[j.id] = j;
    if (prev) updateJobCard(j, prev);
    else renderJobs();
  });
  es.addEventListener("uploads.changed", (e) => {
    // auto-cleanup after a finished job: drop the consumed entries exactly
    let removed = [];
    try { removed = JSON.parse(e.data).removed || []; } catch (err) {}
    const gone = new Set(removed);
    state.uploads = state.uploads.filter((u) => !gone.has(u.id));
    renderFiles();
    saveSession();
  });
}

/* ============ start conversion ============ */

async function postJob(body) {
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail; } catch (e) {}
    alert("创建任务失败: " + detail);
    return false;
  }
  return true;
}

async function startConversion() {
  const sources = state.uploads.map((u) => u.id);
  if (!sources.length) { alert("请先在左侧选择文件"); return; }
  const mergeOn = $("merge-on").checked;
  if (mergeOn && sources.length < 2) { alert("合并模式至少需要 2 个文件"); return; }

  const titleSource = $("title-source").value;
  const titlePattern = $("title-pattern").value.trim();
  if (titleSource === "pattern" && !titlePattern) {
    alert("标题来源为 pattern 时必须填写 pattern（如：第${TrackNum:3}集）");
    return;
  }

  let coverId = null;
  const coverFile = $("merge-cover").files[0];
  if (mergeOn && coverFile) {
    const cf = new FormData();
    cf.append("cover", coverFile);
    try {
      const r = await fetch("/api/upload/cover", { method: "POST", body: cf });
      if (r.ok) state.coverUploadId = (await r.json()).id;
    } catch (e) { /* cover optional */ }
  }

  const base = {
    preset_id: $("preset").value || null,
    settings: currentSettings(),
    metadata: currentMetadata(),
    normalize: $("normalize").checked,
    title_source: titleSource,
    title_pattern: titleSource === "pattern" ? titlePattern : null,
  };

  if (mergeOn) {
    const body = {
      ...base, mode: "merge", source_ids: sources,
      merge: {
        book_title: $("merge-title").value || null,
        book_artist: $("merge-artist").value || null,
        composer: $("merge-composer").value || null,
        cover_upload_id: state.coverUploadId,
      },
    };
    if (!(await postJob(body)).ok) return;
  } else {
    for (let i = 0; i < sources.length; i++) {
      const ok = await postJob({
        ...base, mode: "single", source_ids: [sources[i]],
        position: i + 1, total: sources.length,
      });
      if (!ok) return;
    }
  }
}

function currentSettings() {
  const p = state.presets.find((x) => x.id === $("preset").value);
  const s = p ? JSON.parse(JSON.stringify(p.settings))
              : { format: $("format").value, codec: $("codec").value || null };
  s.format = $("format").value;
  s.codec = $("codec").value || null;
  s.bitrate = $("bitrate").value || null;
  s.samplerate = $("samplerate").value ? +$("samplerate").value : null;
  s.channels = $("channels").value ? +$("channels").value : null;
  return s;
}

function currentMetadata() {
  return {
    title: $("title-source").value === "inherit" ? ($("meta-title").value || null) : null,
    artist: $("meta-artist").value || null,
    album: $("meta-album").value || null,
    composer: $("meta-composer").value || null,
  };
}

/* ============ header actions ============ */

function wireHeaderButtons() {
  $("btn-zip").onclick = () => {
    const done = Object.values(state.jobs).filter((j) => j.status === "done");
    if (!done.length) { alert("暂无已完成任务"); return; }
    location.href = "/api/download/zip?ids=" + done.map((j) => j.id).join(",");
  };
  $("btn-cancel-all").onclick = () => fetch("/api/jobs/cancel-all", { method: "POST" });
  $("btn-clear-finished").onclick = () => fetch("/api/jobs/clear-finished", { method: "POST" });
}

/* ============ wiring & init ============ */

const FORMAT_OPTIONS = [
  ["m4a", "AAC/M4A (.m4a)"], ["m4b", "M4B 有声书 (.m4b)"], ["opus", "Opus (.opus)"],
  ["mp3", "MP3 (.mp3)"], ["ogg", "Ogg Vorbis (.ogg)"], ["flac", "FLAC 无损 (.flac)"], ["wav", "WAV (.wav)"],
];
const CODEC_OPTIONS = [
  ["", "自动"], ["aac", "aac（原生）"], ["libfdk_aac", "libfdk_aac（HE-AAC）"],
  ["libopus", "libopus"], ["libmp3lame", "libmp3lame"],
  ["libvorbis", "libvorbis"], ["flac", "flac"], ["pcm_s16le", "pcm_s16le"],
];

function populateFormatCodec() {
  for (const [v, label] of FORMAT_OPTIONS) {
    const o = document.createElement("option");
    o.value = v; o.textContent = label;
    $("format").appendChild(o);
  }
  for (const [v, label] of CODEC_OPTIONS) {
    const o = document.createElement("option");
    o.value = v; o.textContent = label;
    $("codec").appendChild(o);
  }
  $("format").value = "m4a";
}

function wireSettings() {
  $("preset").onchange = (e) => { applyPreset(e.target.value); updateMergeHint(); saveSession(); };
  ["format", "codec", "bitrate", "samplerate", "channels"].forEach((id) =>
    $(id).addEventListener("change", () => {
      $("preset").value = "";
      updateMergeHint();
      saveSession();
    }));
  $("merge-on").onchange = (e) => {
    $("merge-fields").classList.toggle("hidden", !e.target.checked);
    updateMergeHint();
    saveSession();
  };
  // text inputs: save on every keystroke (debounced) so a crash/refresh
  // never loses what the user typed
  ["merge-title", "merge-artist", "merge-composer", "meta-title", "meta-artist",
   "meta-album", "meta-composer", "title-pattern"].forEach((id) => {
    $(id).addEventListener("input", saveSession);
    $(id).addEventListener("change", saveSession);
  });
  $("normalize").addEventListener("change", saveSession);
  $("title-source").onchange = (e) => {
    $("title-pattern-row").classList.toggle("hidden", e.target.value !== "pattern");
    $("meta-title").disabled = e.target.value !== "inherit";
    $("meta-title").placeholder = e.target.value === "inherit" ? "" : "（该来源下不生效）";
    saveSession();
  };
  $("btn-start").onclick = startConversion;
}

function wireLibrary() {
  $("lib-up").onclick = () => {
    const p = state.libPath || "";
    libLoad(p.split("/").slice(0, -1).join("/") || "/");
  };
}

function init() {
  populateFormatCodec();
  restoreSession();
  loadPresets();
  loadHealth();
  renderColumnPopover();
  wireDrop();
  wireTabs();
  wireSettings();
  wireLibrary();
  wireHeaderButtons();
  connectSSE();
  $("btn-sort-reset").classList.toggle("hidden", state.sort.key == null);
  fetchUploads();
  renderFiles();
  updateMergeHint();
}

document.addEventListener("DOMContentLoaded", init);
