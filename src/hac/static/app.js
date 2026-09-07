/* Audiobook Converter — Vanilla JS frontend */
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  uploads: [],        // WYSIWYG list: [{id,name,size,info,lastModified,order,kind:'upload'|'lib'}]
  libMeta: {},        // "lib:<path>" -> {title,track,album,artist,composer,duration}
  libPath: "",
  libRoots: [],       // [{path, name}] —— name = 面向用户的书库名（根目录名）
  presets: [],
  jobs: {},
  coverUploadId: null,
  sort: { key: null, dir: 1 },     // null key = 上传顺序
  columns: { name: true, track: true, title: true, codec: true, bitrate: true,
             srate: true, channels: true, duration: true, size: true,
             album: false, artist: false, composer: false, mtime: false },
  columnsTouched: {},
  upSort: { key: null, dir: 1 },   // 已上传文件表排序
  libSort: { key: null, dir: 1 },  // 书库表排序
};

const COLUMNS = [
  { key: "name",     label: "文件名" },
  { key: "track",    label: "章节" },
  { key: "title",    label: "标题" },
  { key: "codec",    label: "编码" },
  { key: "bitrate",  label: "码率" },
  { key: "srate",    label: "采样率" },
  { key: "channels", label: "声道" },
  { key: "duration", label: "时长" },
  { key: "size",     label: "大小" },
  { key: "album",    label: "专辑", def: false },
  { key: "artist",   label: "作者", def: false },
  { key: "composer", label: "演播者", def: false },
  { key: "mtime",    label: "修改时间", def: false },
];

const AUDIO_EXT = new Set([".mp3", ".m4a", ".m4b", ".aac", ".flac", ".ogg",
                           ".opus", ".wav", ".wma", ".aiff", ".mka"]);
const M4B_CODECS = new Set(["aac", "libfdk_aac"]);
const DEFAULT_CODEC = {
  mp3: "libmp3lame", m4a: "aac", m4b: "aac", opus: "libopus",
  ogg: "libvorbis", flac: "flac", wav: "pcm_s16le",
};

const icon = (name, cls = "ic") =>
  `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

const escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const fmtSize = (b) => {
  if (b == null) return "";
  if (b > 1e9) return (b / 1e9).toFixed(2) + " GB";
  if (b > 1e6) return (b / 1e6).toFixed(1) + " MB";
  if (b > 1e3) return Math.round(b / 1e3) + " KB";
  return b + " B";
};

const fmtKbps = (b) => (b ? Math.max(1, Math.round(b / 1000)) + "k" : "");
const fmtHz = (h) => (h ? Math.round(h / 1000) + " kHz" : "");

const fmtDur = (s) => {
  if (!s) return "";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.round(s % 60);
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
};

/* ============ session persistence (F3) ============ */

const SESSION_KEY = "hac.session.v1";

function buildSessionPayload() {
  const workingSet = state.uploads.map((u) =>
    ({ id: u.id, name: u.name, size: u.size, kind: u.kind,
       lastModified: u.lastModified }));
  return {
    preset: $("preset").value,
    format: $("format").value,
    codec: $("codec").value,
    bitrate: $("bitrate").value,
    samplerate: $("samplerate").value,
    channels: $("channels").value,
    normalize: $("normalize").checked,
    mergeOn: $("merge-on").checked,
    splitMode: $("split-on").checked,
    splitN: $("merge-split").value,
    copyAudio: $("audio-copy").checked,
    mergeTitle: $("merge-title").value,
    mergeArtist: $("merge-artist").value,
    mergeComposer: $("merge-composer").value,
    metaTitle: $("meta-title").value,
    metaArtist: $("meta-artist").value,
    metaAlbum: $("meta-album").value,
    metaComposer: $("meta-composer").value,
    titleSource: $("title-source").value,
    titlePattern: $("title-pattern").value,
    outputPattern: $("output-pattern").value,
    sort: state.sort,
    columns: state.columns,
    columnsTouched: state.columnsTouched,
    workingSet,
  };
}

let _sessionDebounce = null;
let _sessionDirty = false;
function saveSession() {
  // server-first (multi-device consistent), localStorage as offline fallback
  _sessionDirty = true;
  try { localStorage.setItem(SESSION_KEY, JSON.stringify(buildSessionPayload())); }
  catch (e) { /* storage unavailable */ }
  clearTimeout(_sessionDebounce);
  _sessionDebounce = setTimeout(() => {
    fetch("/api/session", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildSessionPayload()),
    }).catch(() => {});
  }, 500);
}

function flushSessionBeacon() {
  // only flush when the user actually changed something this page life;
  // a blind flush would clobber the server session with pristine defaults
  if (!_sessionDirty) return;
  _sessionDirty = false;
  try {
    navigator.sendBeacon("/api/session-beacon",
      new Blob([JSON.stringify(buildSessionPayload())],
               { type: "application/json" }));
  } catch (e) { /* not supported */ }
}

async function restoreSessionFromServer() {
  try {
    const r = await fetch("/api/session");
    if (r.ok) {
      const s = await r.json();
      applySession(s);
      // server session wins: re-apply working set (before initial restore effect)
      state.sessionWorkingSet = Array.isArray(s.workingSet) ? s.workingSet
        : (Array.isArray(s.libPicks) ? s.libPicks.map((x) => ({ ...x, kind: "lib" })) : []);
      renderFiles();
      updateMergeHint();
      saveSession();  // re-sync local fallback copy
      return true;
    }
    // 404: no server session — migrate legacy localStorage if present
    await migrateLocalSession();
  } catch (e) { /* server unreachable, local fallback stays */ }
  return false;
}

async function migrateLocalSession() {
  // one-time: push old localStorage session to server, apply it, then refresh
  // the local fallback copy from the imported state
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return;
    const r = await fetch("/api/settings/import", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: raw,
    });
    if (r.ok) {
      applySession(JSON.parse(raw));   // UI 必须反映导入值，防默认值覆盖
      localStorage.setItem(SESSION_KEY, raw);  // 与服务端一致（saveSession 也会刷新）
    }
  } catch (e) { /* server unreachable */ }
}

function syncMergeModeUi() {
  const splitOn = $("split-on").checked;
  $("split-n-wrap").classList.toggle("hidden", !splitOn);
  $("split-hint").classList.toggle("hidden", !splitOn);
  const copy = $("audio-copy").checked;
  $("copy-note").classList.toggle("hidden", !copy);
  validateCopySources();
}

function validateCopySources() {
  const err = $("copy-err");
  if (!$("audio-copy").checked || !$("merge-on").checked) {
    err.classList.add("hidden");
    return;
  }
  const unknown = [], bad = [];
  for (const u of state.uploads) {
    const codec = (u.info || {}).codec;
    if (!codec) unknown.push(u.name);
    else if (codec !== "aac") bad.push(`${u.name} (${codec})`);
  }
  const badAll = [...bad, ...unknown.map((n) => `${n} (未知编码)`)];
  if (badAll.length) {
    err.textContent = `检测到 ${badAll.length} 个非 AAC 文件（${badAll.slice(0, 3).join("、")}${badAll.length > 3 ? "…" : ""}）。直通仅支持 AAC，请改用重新编码或先转码`;
    err.classList.remove("hidden");
  } else {
    err.classList.add("hidden");
  }
}

function restoreSession() {
  let s;
  try { s = JSON.parse(localStorage.getItem(SESSION_KEY) || "null"); } catch (e) { s = null; }
  if (s) applySession(s);
}

function applySession(s) {
  if (!s) return;
  const setv = (id, v) => { if (v != null) $(id).value = v; };
  setv("preset", s.preset); setv("format", s.format); setv("codec", s.codec);
  setv("bitrate", s.bitrate); setv("samplerate", s.samplerate); setv("channels", s.channels);
  if (s.normalize != null) $("normalize").checked = s.normalize;
  if (s.mergeOn != null) {
    $("merge-on").checked = s.mergeOn;
    $("merge-fields").classList.toggle("hidden", !s.mergeOn);
    document.querySelectorAll(".meta-dup").forEach((el) =>
      el.classList.toggle("hidden", s.mergeOn));
  }
  if (s.splitMode) $("split-on").checked = true;
  if (s.splitN != null) $("merge-split").value = s.splitN;
  if (s.copyAudio) $("audio-copy").checked = true;
  syncMergeModeUi();
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
  setv("output-pattern", s.outputPattern);
  if (s.sort) state.sort = s.sort;
  if (s.columns) state.columns = { ...state.columns, ...s.columns };
  if (s.columnsTouched) state.columnsTouched = s.columnsTouched;
  state.sessionWorkingSet = Array.isArray(s.workingSet) ? s.workingSet
    : (Array.isArray(s.libPicks) ? s.libPicks.map((x) => ({ ...x, kind: "lib" })) : []);
}

let _uploadsFetchSeq = 0;
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
  renderPresetSummary();
}

function presetSummaryText(p) {
  const st = p.settings || {};
  const bits = [];
  if (st.format) bits.push(String(st.format).toUpperCase());
  if (st.profile) bits.push(st.profile.toUpperCase());
  if (st.bitrate) bits.push(st.bitrate);
  if (st.samplerate) bits.push(st.samplerate + " Hz");
  if (st.channels === 1) bits.push("单声道");
  else if (st.channels === 2) bits.push("立体声");
  return bits.join(" · ");
}

function renderPresetSummary() {
  const el = $("preset-summary");
  if (!el) return;
  const p = state.presets.find((x) => x.id === $("preset").value);
  if (!p) { el.hidden = true; el.textContent = ""; return; }
  el.textContent = presetSummaryText(p);
  el.hidden = false;
}

function applyPreset(id) {
  $("preset-hint").textContent = "";
  const p = state.presets.find((x) => x.id === id);
  if (!p) { renderPresetSummary(); return; }
  renderPresetSummary();
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
  // 已上传列表若已打开/打开过，刷新注册表视图
  refreshUploadsLibrary();
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
    codec: (u.info && u.info.codec) || lib.codec || null,
    bitrate: (u.info && u.info.bitrate) || lib.bitrate || null,
    srate: (u.info && u.info.sample_rate) || lib.sample_rate || null,
    channels: (u.info && u.info.channels) || lib.channels || null,
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
      if (key === "track" || key === "duration" || key === "bitrate" || key === "srate" || key === "channels") {
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

function moveUpload(idx, delta) {
  const to = idx + delta;
  if (to < 0 || to >= state.uploads.length) return;
  const arr = state.uploads.slice();
  const [moved] = arr.splice(idx, 1);
  arr.splice(to, 0, moved);
  state.uploads = [...new Map(arr.map((u) => [u.id, u])).values()];
  state.uploads.forEach((u, i) => { u.order = i; });
  if (state.sort.key) state.sort = { key: null, dir: 1 };
  renderFiles();
  saveSession();
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
      state.columnsTouched[c.key] = true;
      renderFiles();
      renderUploadsLibrary();
      if (state.libPath) libLoad(state.libPath);
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
  // auto-hide metadata columns that are entirely empty in the current set
  const emptyCols = {};
  for (const c of COLUMNS) {
    if (c.key === "name") continue;
    emptyCols[c.key] = state.uploads.every((u) => {
      const m = rowMeta(u);
      const v = c.key === "size" ? u.size
        : c.key === "mtime" ? u.lastModified : m[c.key];
      return v == null || v === "";
    });
  }
  const vis = COLUMNS.filter((c) => state.columns[c.key] &&
    (c.key === "name" || state.columnsTouched[c.key] ||
     !emptyCols[c.key] || !state.uploads.length));

  head.innerHTML = `<th class="nosort"><input type="checkbox" id="sel-all" class="sel-cb" aria-label="全选"></th><th class="nosort">#</th><th class="nosort"></th>` +
    vis.map((c) => {
      let arrow = "", as = "";
      if (state.sort.key === c.key) {
        arrow = state.sort.dir === 1 ? " ▲" : " ▼";
        as = ` aria-sort="${state.sort.dir === 1 ? "ascending" : "descending"}"`;
      }
      return `<th data-key="${c.key}"${as} aria-label="按${c.label}排序">${c.label}${arrow}</th>`;
    }).join("") + `<th class="nosort"></th>`;

  head.querySelectorAll("th[data-key]").forEach((th) => {
    th.onclick = () => {
      const k = th.dataset.key;
      if (state.sort.key === k) {
        if (state.sort.dir === 1) state.sort.dir = -1;
        else state.sort = { key: null, dir: 1 };   // third click: back to upload order
      } else state.sort = { key: k, dir: 1 };
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
        return `<td class="name-cell" title="${escapeHtml(u.name)}">${icon("music")} ${escapeHtml(u.name)}</td>`;
      if (c.key === "duration") return `<td>${fmtDur(m.duration)}</td>`;
      if (c.key === "codec") return `<td class="mono">${escapeHtml(m.codec ?? "")}</td>`;
      if (c.key === "bitrate") return `<td>${fmtKbps(m.bitrate)}</td>`;
      if (c.key === "srate") return `<td>${fmtHz(m.srate)}</td>`;
      if (c.key === "channels") return `<td>${m.channels ? (m.channels === 1 ? "单" : m.channels === 2 ? "双" : m.channels) : ""}</td>`;
      if (c.key === "size") return `<td>${fmtSize(u.size)}</td>`;
      if (c.key === "mtime")
        return `<td>${u.lastModified ? new Date(u.lastModified).toLocaleString() : ""}</td>`;
      return `<td title="${escapeHtml(m[c.key] ?? "")}">${escapeHtml(m[c.key] ?? "")}</td>`;
    };
    tr.innerHTML = `<td><input type="checkbox" class="sel-cb sel-row" data-sel-id="${escapeHtml(u.id)}" aria-label="选择 ${escapeHtml(u.name)}"></td><td class="pos">${i + 1}</td><td class="handle">${icon("grip")}</td>` +
      vis.map(cell).join("") +
      `<td class="acts-cell">` +
      `<button class="mv" data-mv="-1" title="上移" aria-label="上移 ${escapeHtml(u.name)}" ${i === 0 ? "disabled" : ""}>${icon("arrow-up")}</button>` +
      `<button class="mv" data-mv="1" title="下移" aria-label="下移 ${escapeHtml(u.name)}" ${i === state.uploads.length - 1 ? "disabled" : ""}>${icon("arrow-down")}</button>` +
      `<button class="del" title="移除" aria-label="从列表移除 ${escapeHtml(u.name)}">${icon("x")}</button></td>`;
    tr.querySelectorAll(".mv").forEach((b) => {
      b.onclick = () => moveUpload(i, parseInt(b.dataset.mv));
    });
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
      renderFiles();
      saveSession();
    });
    tbody.appendChild(tr);
  });
  // 多选：全选/半选/操作条
  const selAll = $("sel-all");
  if (selAll) {
    selAll.checked = state.uploads.length > 0 &&
      tbody.querySelectorAll(".sel-row:checked").length === state.uploads.length;
    selAll.indeterminate = !selAll.checked &&
      tbody.querySelectorAll(".sel-row:checked").length > 0;
    selAll.onclick = () => {
      tbody.querySelectorAll(".sel-row").forEach((cb) => { cb.checked = selAll.checked; });
      updateSelBar();
    };
  }
  tbody.querySelectorAll(".sel-row").forEach((cb) => {
    cb.addEventListener("change", updateSelBar);
  });
  updateSelBar();
  updateMergeHint();
}

function updateSelBar() {
  const n = document.querySelectorAll("#file-list .sel-row:checked").length;
  const bar = $("sel-bar");
  if (!bar) return;
  $("sel-count").textContent = n;
  bar.classList.toggle("hidden", n === 0);
}

/* ============ folder drop & pickers ============ */

function wireDrop() {
  const zone = $("col-files");
  let dragDepth = 0;
  zone.addEventListener("dragover", (e) => e.preventDefault());
  zone.addEventListener("dragenter", (e) => {
    e.preventDefault();
    dragDepth++;
    zone.classList.add("dropping");
  });
  zone.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) zone.classList.remove("dropping");
  });
  zone.addEventListener("drop", async (e) => {
    e.preventDefault();
    dragDepth = 0;
    zone.classList.remove("dropping");
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
  $("btn-remove-selected").onclick = () => {
    const ids = new Set([...document.querySelectorAll("#file-list .sel-row:checked")]
      .map((cb) => cb.dataset.selId));
    state.uploads = state.uploads.filter((u) => !ids.has(u.id));
    if (state.coverUploadId && ids.has(state.coverUploadId)) state.coverUploadId = null;
    renderFiles();
    saveSession();
    toast(`已移除 ${ids.size} 个文件`);
  };
  $("btn-select-none").onclick = () => {
    document.querySelectorAll("#file-list .sel-row:checked").forEach((cb) => {
      cb.checked = false;
    });
    updateSelBar();
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
}

/* ============ tabs & library ============ */

/* ============ 已上传文件 tab（服务端注册表管理） ============ */

function isReferenced(u) {
  return !!u.referenced || Object.values(state.jobs).some(
    (j) => ACTIVE.has(j.status) && j.source_ids.includes(u.id));
}

async function refreshUploadsLibrary() {
  try {
    state.uploadsAllRaw = await (await fetch("/api/uploads")).json();
    renderUploadsLibrary();
  } catch (e) { /* unreachable */ }
}

const UP_COLUMNS = [
  { key: "name",    label: "文件名" },
  { key: "ext",     label: "类型" },
  { key: "codec",   label: "编码" },
  { key: "bitrate", label: "码率" },
  { key: "srate",   label: "采样率" },
  { key: "duration", label: "时长" },
  { key: "size",    label: "大小" },
];

const LIB_COLUMNS = [
  { key: "name",     label: "文件名" },
  { key: "ext",      label: "类型" },
  { key: "codec",    label: "编码" },
  { key: "bitrate",  label: "码率" },
  { key: "srate",    label: "采样率" },
  { key: "channels", label: "声道" },
  { key: "duration", label: "时长" },
  { key: "size",     label: "大小" },
];

function libRowMeta(f) {
  const m = state.libMeta[f.id] || {};
  return {
    name: f.name,
    ext: (f.name.includes(".") ? f.name.split(".").pop() : "").toUpperCase(),
    codec: m.codec || null,
    bitrate: m.bitrate || null,
    srate: m.sample_rate || null,
    channels: m.channels || null,
    duration: m.duration || null,
    size: f.size,
  };
}

function sortLibFiles(files) {
  const { key, dir } = state.libSort;
  if (!key) return files;
  const regIdx = new Map(files.map((f, i) => [f.id, i]));
  const keyed = files.map((f) => ({ f, m: libRowMeta(f), i: regIdx.get(f.id) }));
  keyed.sort((x, y) => {
    let d = 0;
    if (key === "name") d = naturalCompare(x.f.name, y.f.name);
    else if (key === "size" || key === "bitrate" || key === "srate" ||
             key === "channels" || key === "duration") {
      const xn = x.m[key] == null, yn = y.m[key] == null;
      if (xn && yn) d = naturalCompare(x.f.name, y.f.name);
      else if (xn) return 1;
      else if (yn) return -1;
      else d = x.m[key] - y.m[key];
    } else {
      const xs = String(x.m[key] ?? ""), ys = String(y.m[key] ?? "");
      if (!xs && !ys) d = naturalCompare(x.f.name, y.f.name);
      else if (!xs) return 1;
      else if (!ys) return -1;
      else d = xs.localeCompare(ys);
    }
    return (d * dir) || (x.i - y.i);
  });
  return keyed.map((k) => k.f);
}

function upRowMeta(u) {
  const info = u.info || {};
  return {
    name: u.name,
    ext: (u.name.includes(".") ? u.name.split(".").pop() : "").toUpperCase(),
    codec: info.codec || null,
    bitrate: info.bitrate || null,
    srate: info.sample_rate || null,
    duration: info.duration || null,
    size: u.size,
  };
}

function sortUploadsAll() {
  // always re-derive from the raw server order so sorting never mutates the
  // canonical list and a third click cleanly restores registration order
  state.uploadsAll = [...(state.uploadsAllRaw || state.uploadsAll)];
  const { key, dir } = state.upSort;
  if (!key) return;   // 服务器注册顺序
  const regIdx = new Map(state.uploadsAll.map((u, i) => [u.id, i]));
  const keyed = state.uploadsAll.map((u) => ({ u, m: upRowMeta(u), i: regIdx.get(u.id) }));
  keyed.sort((x, y) => {
    let d = 0;
    if (key === "name") d = naturalCompare(x.u.name, y.u.name);
    else if (key === "size" || key === "bitrate" || key === "srate" || key === "duration") {
      const xn = x.m[key] == null, yn = y.m[key] == null;
      if (xn && yn) d = naturalCompare(x.u.name, y.u.name);
      else if (xn) return 1;
      else if (yn) return -1;
      else d = x.m[key] - y.m[key];
    } else {
      const xs = String(x.m[key] ?? ""), ys = String(y.m[key] ?? "");
      if (!xs && !ys) d = naturalCompare(x.u.name, y.u.name);
      else if (!xs) return 1;
      else if (!ys) return -1;
      else d = xs.localeCompare(ys);
    }
    return (d * dir) || (x.i - y.i);
  });
  state.uploadsAll = keyed.map((k) => k.u);
}

function renderUploadsLibrary() {
  const tbody = $("uploads-list");
  const head = $("uploads-head");
  if (!tbody) return;
  sortUploadsAll();
  const rows = state.uploadsAll;
  const cnt = $("up-count");
  if (cnt) cnt.textContent = `共 ${rows.length} 个文件`;

  const upVis = UP_COLUMNS.filter((c) => c.key === "name" || c.key === "ext" ||
    !(c.key in state.columns) || state.columns[c.key]);
  head.innerHTML = `<th class="nosort"></th><th class="nosort"></th>` +
    upVis.map((c) => {
      let arrow = "", as = "";
      if (state.upSort.key === c.key) {
        arrow = state.upSort.dir === 1 ? " ▲" : " ▼";
        as = ` aria-sort="${state.upSort.dir === 1 ? "ascending" : "descending"}"`;
      }
      return `<th data-ukey="${c.key}"${as}>${c.label}${arrow}</th>`;
    }).join("") +
    `<th class="nosort">操作</th>`;

  head.querySelectorAll("th[data-ukey]").forEach((th) => {
    th.onclick = () => {
      const k = th.dataset.ukey;
      if (state.upSort.key === k) {
        if (state.upSort.dir === 1) state.upSort.dir = -1;
        else state.upSort = { key: null, dir: 1 };
      } else state.upSort = { key: k, dir: 1 };
      renderUploadsLibrary();
    };
  });

  tbody.innerHTML = "";
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="${upVis.length + 2}" class="empty">暂无已上传文件</td></tr>`;
    return;
  }
  for (const u of rows) {
    const locked = isReferenced(u);
    const isCover = u.info && u.info.kind === "cover";
    const m = upRowMeta(u);
    const tr = document.createElement("tr");
    const upCell = (key) => {
      if (key === "name")
        return `<td class="name-cell" title="${escapeHtml(u.name)}">${icon(isCover ? "library" : "music")} ${escapeHtml(u.name)}${locked ? " 🔒" : ""}</td>`;
      if (key === "ext") return `<td>${escapeHtml(m.ext)}</td>`;
      if (key === "codec") return `<td class="mono">${escapeHtml(m.codec ?? "")}</td>`;
      if (key === "bitrate") return `<td>${fmtKbps(m.bitrate)}</td>`;
      if (key === "srate") return `<td>${fmtHz(m.srate)}</td>`;
      if (key === "channels") return `<td>${m.channels ? (m.channels === 1 ? "单" : m.channels === 2 ? "双" : m.channels) : ""}</td>`;
      if (key === "duration") return `<td>${fmtDur(m.duration)}</td>`;
      if (key === "size") return `<td>${fmtSize(u.size)}</td>`;
      return `<td></td>`;
    };
    tr.innerHTML =
      `<td><input type="checkbox" class="up-pick" data-upid="${escapeHtml(u.id)}" ${locked ? "disabled" : ""} aria-label="选择 ${escapeHtml(u.name)}"></td>` +
      (isCover ? `<td></td>` :
        `<td><button class="del play-btn" title="试听" aria-label="试听 ${escapeHtml(u.name)}" data-play="upload" data-pid="${escapeHtml(u.id)}">${icon("play")}</button></td>`) +
      upVis.map((c) => upCell(c.key)).join("") +
      `<td class="up-acts">` +
      (isCover ? "" : `<button class="btn small subtle" data-add="${escapeHtml(u.id)}">${icon("download")} 加入列表</button>`) +
      `<button class="del" data-del="${escapeHtml(u.id)}" title="删除" aria-label="删除 ${escapeHtml(u.name)}" ${locked ? "disabled" : ""}>${icon("x")}</button></td>`;
    tbody.appendChild(tr);
  }
  tbody.querySelectorAll("[data-add]").forEach((b) => {
    b.onclick = () => addToWorkingSet(b.dataset.add);
  });
  tbody.querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = async () => {
      const res = await fetch(`/api/uploads/${b.dataset.del}`, { method: "DELETE" });
      if (res.status === 409) {
        const d = await res.json();
        alert(d.detail);
      } else if (!res.ok) {
        alert("删除失败: HTTP " + res.status);
      }
      refreshUploadsLibrary();
    };
  });
  tbody.querySelectorAll("input.up-pick").forEach((cb) => {
    cb.addEventListener("change", () => {
      const n = tbody.querySelectorAll("input.up-pick:checked").length;
      const btn = $("btn-batch");
      if (btn) btn.disabled = n === 0;
    });
  });
  const n = tbody.querySelectorAll("input.up-pick:checked").length;
  const btn = $("btn-batch");
  if (btn) btn.disabled = n === 0;
}

function addToWorkingSet(id) {
  if (state.uploads.some((u) => u.id === id)) { alert("该文件已在当前列表中"); return; }
  const u = state.uploadsAll.find((x) => x.id === id);
  if (!u) return;
  state.uploads.push({ ...u, kind: "upload", order: state.uploads.length });
  renderFiles();
  saveSession();
  toast(`已加入当前列表：${u.name}`);
}

async function deleteUploads(ids) {
  if (!ids.length) return;
  const res = await fetch("/api/uploads/delete", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!res.ok) { alert("删除失败: HTTP " + res.status); return; }
  const { removed, skipped } = await res.json();
  if (skipped.length) toast(`跳过 ${skipped.length} 个正被任务使用的文件：${skipped[0]}${skipped.length > 1 ? " 等" : ""}`);
  else if (removed) toast(`已删除 ${removed} 个文件`);
  refreshUploadsLibrary();
}

function wireUploadsLibrary() {
  $("up-del-selected").onclick = () => {
    const ids = [...document.querySelectorAll("#uploads-list input.up-pick:checked")]
      .map((cb) => cb.dataset.upid);
    if (!ids.length) { alert("请先勾选要删除的文件"); return; }
    deleteUploads(ids);
  };
  $("up-del-all").onclick = () => {
    const deletable = state.uploadsAll.filter((u) => !isReferenced(u) &&
      !(u.info && u.info.kind === "cover")).map((u) => u.id);
    if (!deletable.length) { alert("没有可删除的文件（正被任务使用的为只读）"); return; }
    if (!confirm(`确定删除 ${deletable.length} 个未被任务使用的文件？此操作不可恢复`)) return;
    deleteUploads(deletable);
  };
  $("up-add-selected").onclick = () => {
    const ids = [...document.querySelectorAll("#uploads-list input.up-pick:checked")]
      .map((cb) => cb.dataset.upid).filter((id) => {
        const u = state.uploadsAll.find((x) => x.id === id);
        return u && !(u.info && u.info.kind === "cover");
      });
    if (!ids.length) { alert("请先勾选要加入的音频文件"); return; }
    let added = 0;
    for (const id of ids) {
      if (state.uploads.some((u) => u.id === id)) continue;
      const u = state.uploadsAll.find((x) => x.id === id);
      state.uploads.push({ ...u, kind: "upload", order: state.uploads.length });
      added++;
    }
    renderFiles();
    saveSession();
    toast(`已加入 ${added} 个文件到当前列表`);
  };
}

/* ============ 桌面通知 ============ */

const notify = { enabled: false };

async function wireNotify() {
  const btn = $("btn-notify");
  if (!btn) return;
  // 服务端持久化开关（依赖 settings KV）
  try {
    const rows = await (await fetch("/api/settings")).json();
    const row = rows.find((x) => x.key === "settings.notifications");
    notify.enabled = row ? JSON.parse(row.value) === true : false;
  } catch (e) { /* DB 不可用时默认关 */ }
  paintNotifyBtn();
  btn.onclick = async () => {
    if (notify.enabled) {
      notify.enabled = false;
    } else {
      if (!("Notification" in window)) { toast("此浏览器不支持桌面通知"); return; }
      let perm = Notification.permission;
      if (perm === "default") perm = await Notification.requestPermission();
      if (perm !== "granted") { toast("通知权限被拒绝"); return; }
      notify.enabled = true;
    }
    paintNotifyBtn();
    try {
      await fetch("/api/settings", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: "settings.notifications",
                               value: JSON.stringify(notify.enabled) }),
      });
    } catch (e) { /* offline */ }
  };
}

function paintNotifyBtn() {
  const btn = $("btn-notify");
  btn.classList.toggle("btn-notify-on", notify.enabled);
  btn.setAttribute("aria-pressed", String(notify.enabled));
}

function maybeNotify(job) {
  if (!notify.enabled || !document.hidden) return;
  if (!["done", "failed"].includes(job.status)) return;
  const isDone = job.status === "done";
  const n = new Notification(isDone ? "转换完成" : "转换失败", {
    body: job.output_filename + (isDone ? "" : `\n${(job.error || "").slice(0, 140)}`),
    tag: job.id,
  });
  n.onclick = () => { window.focus(); n.close(); };
}

/* ============ 播放：mini 试听条 + A/B 对比 ============ */

function fmtTime(sec) {
  if (!isFinite(sec)) return "0:00";
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
           : `${m}:${String(s).padStart(2, "0")}`;
}

const mini = { audio: null };

function miniShow(name, url) {
  const audio = $("mp-audio");
  mini.audio = audio;
  audio.src = url;
  audio.playbackRate = parseFloat($("mp-rate").value) || 1;
  $("mp-name").textContent = name;
  $("mini-player").classList.remove("hidden");
  $("mp-toggle").textContent = "⏸";
  audio.play().catch(() => {});
}

function miniStop() {
  const audio = $("mp-audio");
  if (audio) { audio.pause(); audio.src = ""; }
  $("mini-player").classList.add("hidden");
}

function wirePlayButtons() {
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-play]");
    if (!btn) return;
    playUpload(btn.dataset.pid, btn.getAttribute("aria-label")?.replace("试听 ", "") || btn.dataset.pid);
  });
}

function wireMiniPlayer() {
  const audio = $("mp-audio");
  $("mp-toggle").onclick = () => {
    if (audio.paused) { audio.play(); $("mp-toggle").textContent = "⏸"; }
    else { audio.pause(); $("mp-toggle").textContent = "▶"; }
  };
  $("mp-close").onclick = miniStop;
  $("mp-seek").oninput = (e) => {
    if (audio.duration) audio.currentTime = (e.target.value / 1000) * audio.duration;
  };
  $("mp-rate").onchange = (e) => { audio.playbackRate = parseFloat(e.target.value) || 1; };
  $("mp-vol").oninput = (e) => { audio.volume = e.target.value / 100; };
  audio.addEventListener("timeupdate", () => {
    if (!audio.duration) return;
    $("mp-seek").value = Math.round((audio.currentTime / audio.duration) * 1000);
    $("mp-cur").textContent = fmtTime(audio.currentTime);
    $("mp-dur").textContent = fmtTime(audio.duration);
  });
  audio.addEventListener("ended", () => { $("mp-toggle").textContent = "▶"; });
}

// 播放入口：stream url 便捷构造
function streamUrl(kind, id) { return `/api/stream/${kind}/${encodeURIComponent(id)}`; }

function playUpload(uid, name) {
  miniShow(name || uid, streamUrl("upload", uid));
}
function playJob(jobId, name) {
  miniShow(name || jobId, streamUrl("job", jobId));
}

/* ---- A/B 对比 ---- */

const ab = { syncing: false, chapterSync: true };

function abMirror(sourceSide, action) {
  // 以「最近操作者」为准：把 sourceSide 的状态镜像到另一侧
  const a = $("ab-audio-a"), b = $("ab-audio-b");
  const src = sourceSide === "a" ? a : b;
  const dst = sourceSide === "a" ? b : a;
  ab.syncing = true;
  try {
    if (action === "play") dst.play().catch(() => {});
    if (action === "pause") dst.pause();
    if (action === "seek") dst.currentTime = src.currentTime;
    if (action === "rate") dst.playbackRate = src.playbackRate;
  } finally {
    setTimeout(() => { ab.syncing = false; }, 50);
  }
}

function wireAbPlayer() {
  const a = $("ab-audio-a"), b = $("ab-audio-b");
  for (const side of ["a", "b"]) {
    const el = side === "a" ? a : b;
    el.addEventListener("play", () => {
      if (ab.syncing) return;
      abMirror(side, "play");
      document.querySelector(`[data-ab="${side}"]`).textContent = "⏸";
      $(`#ab-side-${side}`).classList.add("ab-playing");
    });
    el.addEventListener("pause", () => {
      if (ab.syncing) return;
      abMirror(side, "pause");
      document.querySelector(`[data-ab="${side}"]`).textContent = "▶";
      $(`#ab-side-${side}`).classList.remove("ab-playing");
    });
    el.addEventListener("seeked", () => {
      if (ab.syncing) return;
      abMirror(side, "seek");
    });
    el.addEventListener("ratechange", () => {
      if (ab.syncing) return;
      abMirror(side, "rate");
    });
    el.addEventListener("timeupdate", () => {
      document.querySelector(`[data-ab-cur="${side}"]`).textContent = fmtTime(el.currentTime);
      document.querySelector(`[data-ab-dur="${side}"]`).textContent = fmtTime(el.duration);
      const seek = document.querySelector(`[data-ab-seek="${side}"]`);
      if (el.duration && document.activeElement !== seek)
        seek.value = Math.round((el.currentTime / el.duration) * 1000);
      // 漂移校正（播放中，>0.3s 才校正）
      const other = side === "a" ? b : a;
      if (!el.paused && !other.paused && !ab.syncing &&
          Math.abs(el.currentTime - other.currentTime) > 0.3) {
        ab.syncing = true;
        other.currentTime = el.currentTime;
        setTimeout(() => { ab.syncing = false; }, 50);
      }
    });
    document.querySelector(`[data-ab="${side}"]`).onclick = () => {
      if (el.paused) el.play(); else el.pause();
    };
    document.querySelector(`[data-ab-seek="${side}"]`).oninput = (e) => {
      if (el.duration) el.currentTime = (e.target.value / 1000) * el.duration;
    };
    document.querySelector(`[data-ab-vol="${side}"]`).oninput = (e) => {
      el.volume = e.target.value / 100;
    };
  }
  $("ab-close").onclick = () => {
    a.pause(); b.pause();
    $("ab-drawer").classList.add("hidden");
  };
  $("ab-drawer").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { $("ab-close").onclick(); return; }
    if (e.key === " " && $("ab-drawer").contains(document.activeElement)) {
      e.preventDefault();
      if (a.paused) { a.play(); } else { a.pause(); }
    }
    if (e.key === "ArrowLeft") { a.currentTime = Math.max(0, a.currentTime - 5); }
    if (e.key === "ArrowRight") { a.currentTime = a.currentTime + 5; }
  });
}

function abOpen(jobId) {
  const j = state.jobs[jobId];
  if (!j || !j.source_ids || !j.source_ids.length) return;
  const sid = j.source_ids[0];
  const srcKind = sid.startsWith("lib:") ? "lib" : "upload";
  const srcId = sid.startsWith("lib:") ? sid.slice(4) : sid;
  $("ab-audio-a").src = streamUrl(srcKind, srcId);
  $("ab-audio-b").src = streamUrl("job", jobId);
  $("ab-sub").textContent = j.output_filename || "";
  $("ab-drawer").classList.remove("hidden");
  // 章节 chips（以产物为准）
  fetch(streamUrl("job", jobId) + "/info").then((r) => r.json()).then((d) => {
    const wrap = $("ab-chapters");
    wrap.innerHTML = "";
    for (const ch of d.chapters || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip";
      btn.textContent = `${fmtTime(ch.start)} ${ch.title || ""}`;
      btn.onclick = () => {
        $("ab-audio-a").currentTime = ch.start;
        $("ab-audio-b").currentTime = ch.start;
      };
      wrap.appendChild(btn);
    }
  }).catch(() => {});
}

/* ============ 批量处理（模板重命名/写 tag） ============ */

const BATCH_FIELDS = [
  ["TrackNum", "编号"], ["TrackTitle", "标题"], ["Artist", "作者"],
  ["Album", "专辑"], ["Year", "年份"], ["Genre", "流派"],
  ["DiscNum", "盘号"], ["Composer", "演播者"],
];
const TAG_FIELD_MAP = {
  title: "TrackTitle", artist: "Artist", album: "Album", track: "TrackNum",
  year: "Year", genre: "Genre", disc: "DiscNum", composer: "Composer",
};
const batch = { pool: "uploads", ids: [], timer: null, lastPreview: null };

function batchOpen(pool, ids) {
  batch.pool = pool;
  batch.ids = ids;
  batch.lastPreview = null;
  $("batch-pool-info").textContent =
    pool === "uploads" ? `已选 ${ids.length} 个文件` : `产物 ${ids.length} 个`;
  const drawer = $("batch-drawer");
  drawer.classList.remove("hidden");
  $("batch-template").value = "";
  $("batch-tpl-err").textContent = "";
  $("batch-preview").innerHTML = "";
  $("batch-report").textContent = "";
  $("batch-run").disabled = true;
  $("batch-writetags").checked = false;
  renderBatchTagChips();
  $("batch-template").focus();
}

function batchClose() { $("batch-drawer").classList.add("hidden"); }

function renderBatchTagChips() {
  const wrap = $("batch-tagfields");
  wrap.innerHTML = "";
  wrap.style.display = $("batch-writetags").checked ? "flex" : "none";
  for (const [key, label] of Object.entries(TAG_FIELD_MAP)) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip on";
    b.textContent = label;
    b.dataset.key = key;
    b.onclick = () => b.classList.toggle("on");
    wrap.appendChild(b);
  }
}

function batchSelectedTagFields() {
  return [...document.querySelectorAll("#batch-tagfields .chip.on")]
    .map((b) => b.dataset.key);
}

function batchSchedulePreview() {
  clearTimeout(batch.timer);
  batch.timer = setTimeout(batchPreview, 300);
}

async function batchPreview() {
  const tpl = $("batch-template").value.trim();
  const errEl = $("batch-tpl-err");
  errEl.textContent = "";
  $("batch-preview").innerHTML = "";
  $("batch-run").disabled = true;
  batch.lastPreview = null;
  if (!tpl) return;
  const r = await fetch("/api/batch/preview", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pool: batch.pool, ids: batch.ids, template: tpl,
      filenames: batchFilenames(), track_total: batch.ids.length,
    }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    errEl.textContent = d.detail || `HTTP ${r.status}`;
    return;
  }
  const rows = await r.json();
  batch.lastPreview = rows;
  const tb = $("batch-preview");
  for (const row of rows) {
    const cls = row.status === "ok" ? "" : "bad";
    const fieldsTxt = Object.entries(row.fields || {})
      .map(([k, v]) => `${k}=${v}`).join(" · ") || "—";
    tb.insertAdjacentHTML("beforeend", `<tr class="${cls}">` +
      `<td title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</td>` +
      `<td class="fields-cell">${escapeHtml(fieldsTxt)}` +
      (row.status !== "ok" ? ` <b>✗ ${escapeHtml(row.reason || row.status)}</b>` : "") +
      `</td>` +
      `<td class="${cls}">${escapeHtml(row.new_name || "")}</td></tr>`);
  }
  const okN = rows.filter((r) => r.status === "ok").length;
  $("batch-run").disabled = okN === 0;
}

function batchFilenames() {
  if (batch.pool === "uploads") {
    const m = {};
    for (const uid of batch.ids) {
      const u = (state.uploadsAll || state.uploadsAllRaw || [])
        .find((x) => x.id === uid);
      if (u) m[uid] = u.name;
    }
    return m;
  }
  const m = {};
  for (const jid of batch.ids) {
    const j = state.jobs[jid];
    if (j) m[jid] = j.output_filename;
  }
  return m;
}

async function batchRun() {
  const tpl = $("batch-template").value.trim();
  const writeFields = $("batch-writetags").checked ? batchSelectedTagFields() : [];
  const r = await fetch("/api/batch/execute", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pool: batch.pool, ids: batch.ids, template: tpl, write_fields: writeFields,
      filenames: batchFilenames(), track_total: batch.ids.length,
    }),
  });
  const d = await r.json().catch(() => ({}));
  $("batch-report").textContent =
    `完成：成功 ${d.ok || 0} · 跳过 ${d.skipped || 0} · 失败 ${d.failed || 0}`;
  await batchPreview();
  if (batch.pool === "uploads") refreshUploadsLibrary();
  else renderJobs();
}

function wireBatch() {
  $("btn-batch").onclick = () => {
    const ids = [...document.querySelectorAll("#uploads-list input.up-pick:checked")]
      .map((cb) => cb.dataset.upid)
      .filter((id) => {
        const u = (state.uploadsAll || []).find((x) => x.id === id);
        return u && !(u.info && u.info.kind === "cover");
      });
    if (!ids.length) return;
    batchOpen("uploads", ids);
  };
  $("batch-close").onclick = batchClose;
  $("batch-drawer").addEventListener("keydown", (e) => {
    if (e.key === "Escape") batchClose();
  });
  $("batch-drawer").addEventListener("click", (e) => {
    if (e.target === $("batch-drawer")) batchClose();
  });
  $("batch-template").addEventListener("input", batchSchedulePreview);
  $("batch-writetags").addEventListener("change", renderBatchTagChips);
  $("batch-run").onclick = batchRun;
  // chips：点击插入 ${Field}
  const chipWrap = $("batch-chips");
  for (const [key, label] of BATCH_FIELDS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = label;
    b.title = `\${${key}}`;
    b.onclick = () => {
      const inp = $("batch-template");
      inp.value += `\${${key}}`;
      inp.dispatchEvent(new Event("input"));
    };
    chipWrap.appendChild(b);
  }
}

/* ============ toast ============ */

function toast(msg, ms = 3500) {
  let t = $("toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    t.setAttribute("role", "status");
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove("show"), ms);
}

function wireTabs() {
  document.querySelectorAll(".tab").forEach((t) => {
    t.onclick = () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
      $("pane-upload").classList.toggle("hidden", t.dataset.tab !== "upload");
      $("panel-library").classList.toggle("hidden", t.dataset.tab !== "library");
      $("panel-uploads").classList.toggle("hidden", t.dataset.tab !== "uploads");
      if (t.dataset.tab === "library") loadRoots();
      if (t.dataset.tab === "uploads") refreshUploadsLibrary();
    };
  });
}

function displayLibPath(abs) {
  // 只展示书库名 + 相对路径，不暴露服务器文件系统结构
  for (const r of state.libRoots) {
    if (abs === r.path) return r.name;
    if (abs.startsWith(r.path + "/"))
      return r.name + "/" + abs.slice(r.path.length + 1);
  }
  return abs.split("/").pop() || abs;
}

async function libLoad(path) {
  const ul = $("lib-list");
  try {
    if (!path && state.libRoots.length > 1) {
      // 顶层：把每个书库根显示为一个虚拟文件夹
      state.libPath = "";
      $("lib-path").textContent = "选择书库";
      $("lib-head").innerHTML = "";
      ul.innerHTML = "";
      for (const r of state.libRoots) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="${LIB_COLUMNS.length + 1}" class="name-cell lib-root">${icon("library")} ${escapeHtml(r.name)}/</td>`;
        tr.onclick = () => libLoad(r.path);
        ul.appendChild(tr);
      }
      return;
    }
    const res = await fetch("/api/library/list?path=" + encodeURIComponent(path || ""));
    if (res.status === 403) {
      ul.innerHTML = `<tr><td colspan="${LIB_COLUMNS.length + 1}" class="empty">⛔ 无权访问（不在书库范围内）</td></tr>`;
      $("lib-head").innerHTML = "";
      return;
    }
    if (!res.ok) { ul.innerHTML = `<tr><td colspan="${LIB_COLUMNS.length + 1}" class="empty">HTTP ${res.status}</td></tr>`; $("lib-head").innerHTML = ""; return; }
    const data = await res.json();
    state.libPath = data.path;
    $("lib-path").textContent = displayLibPath(data.path);
    renderLibTable(data);
  } catch (e) {
    $("lib-path").textContent = "加载失败: " + e;
  }
}

function renderLibTable(data) {
  const head = $("lib-head");
  const tbody = $("lib-list");

  const libVis = LIB_COLUMNS.filter((c) => c.key === "name" || c.key === "ext" ||
    !(c.key in state.columns) || state.columns[c.key]);
  head.innerHTML = `<th class="nosort"></th><th class="nosort"></th>` +
    libVis.map((c) => {
      let arrow = "", as = "";
      if (state.libSort.key === c.key) {
        arrow = state.libSort.dir === 1 ? " ▲" : " ▼";
        as = ` aria-sort="${state.libSort.dir === 1 ? "ascending" : "descending"}"`;
      }
      return `<th data-lkey="${c.key}"${as}>${c.label}${arrow}</th>`;
    }).join("") + `<th class="nosort"></th>`;

  head.querySelectorAll("th[data-lkey]").forEach((th) => {
    th.onclick = () => {
      const k = th.dataset.lkey;
      if (state.libSort.key === k) {
        if (state.libSort.dir === 1) state.libSort.dir = -1;
        else state.libSort = { key: null, dir: 1 };
      } else state.libSort = { key: k, dir: 1 };
      libLoad(state.libPath);
    };
  });

  tbody.innerHTML = "";
  for (const d of data.dirs) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td></td>` +
      `<td class="name-cell lib-dir" title="${escapeHtml(d.name)}" colspan="${libVis.length}">${icon("folder")} ${escapeHtml(d.name)}/</td>` +
      `<td class="up-acts"></td>`;
    tr.querySelector(".name-cell").onclick = () => libLoad(d.path);
    tbody.appendChild(tr);
  }
  if (!data.dirs.length && !data.files.length) {
    tbody.innerHTML = `<tr><td colspan="${LIB_COLUMNS.length + 1}" class="empty">空目录（无音频文件）</td></tr>`;
    return;
  }
  // probe metadata for sorting/display (cached in libMeta)
  const missing = data.files.filter((f) => !(f.id in state.libMeta)).map((f) => f.id.slice(4));
  if (missing.length) {
    fetch("/api/library/probe", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: missing }),
    }).then((r) => r.ok ? r.json() : {}).then((meta) => {
      for (const [p, v] of Object.entries(meta)) state.libMeta[`lib:${p}`] = v;
      renderLibTable(data);   // re-render with metadata
    }).catch(() => {});
  }
  const sorted = sortLibFiles(data.files);
  for (const f of sorted) {
    const m = libRowMeta(f);
    const inList = state.uploads.some((u) => u.id === f.id);
    const tr = document.createElement("tr");
    const libCell = (key) => {
      if (key === "name")
        return `<td class="name-cell" title="${escapeHtml(f.name)}">${icon("music")} ${escapeHtml(f.name)}</td>`;
      if (key === "ext") return `<td>${escapeHtml(m.ext)}</td>`;
      if (key === "codec") return `<td class="mono">${escapeHtml(m.codec ?? "")}</td>`;
      if (key === "bitrate") return `<td>${fmtKbps(m.bitrate)}</td>`;
      if (key === "srate") return `<td>${fmtHz(m.srate)}</td>`;
      if (key === "channels") return `<td>${m.channels ? (m.channels === 1 ? "单" : m.channels === 2 ? "双" : m.channels) : ""}</td>`;
      if (key === "duration") return `<td>${fmtDur(m.duration)}</td>`;
      if (key === "size") return `<td>${fmtSize(f.size)}</td>`;
      return `<td></td>`;
    };
    tr.innerHTML =
      `<td><input type="checkbox" class="libpick" data-libid="${escapeHtml(f.id)}" ` +
      `data-libname="${escapeHtml(f.name)}" ${inList ? "checked" : ""} aria-label="选择 ${escapeHtml(f.name)}"></td>` +
      `<td><button class="del play-btn" title="试听" aria-label="试听 ${escapeHtml(f.name)}" data-play="lib" data-pid="${escapeHtml(f.id.slice(4))}">${icon("play")}</button></td>` +
      libVis.map((c) => libCell(c.key)).join("") +
      `<td class="up-acts"></td>`;
    tr.querySelector("input").addEventListener("change", (e) => {
      toggleLibFile({ id: f.id, name: f.name, size: f.size }, e.target.checked);
    });
    tbody.appendChild(tr);
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
    // 兼容旧格式（字符串数组）：显示名取根目录 basename，不暴露真实路径
    state.libRoots = res.roots.map((r) =>
      typeof r === "string" ? { path: r, name: r.split("/").filter(Boolean).pop() || r } : r);
    $("lib-roots").textContent = state.libRoots.map((r) => r.name).join(" ; ");
  } catch (e) { /* ignore */ }
  libLoad("");
}

/* ============ merge helpers ============ */

function updateMergeHint() {
  const n = state.uploads.length;
  const mergeOn = $("merge-on").checked;
  const errCount = renderMergeHints();
  let copyErr = false;
  if (mergeOn && $("audio-copy").checked) {
    for (const u of state.uploads) {
      const codec = (u.info || {}).codec;
      if (!codec || codec !== "aac") { copyErr = true; break; }
    }
  }
  const splitOn = mergeOn && $("split-on").checked;
  const splitN = parseInt($("merge-split").value, 10);
  const splitInvalid = splitOn && !(splitN > 0);
  $("btn-start").disabled =
    n === 0 || (mergeOn && n < 2 && !splitOn) || (mergeOn && errCount > 0) ||
    copyErr || splitInvalid;
  if (!mergeOn) {
    $("merge-hint").textContent = `将为 ${n} 个文件各创建一个转码任务`;
    return;
  }
  const nVols = splitOn && splitN > 0 ? Math.ceil(n / splitN) : 1;
  const head = $("audio-copy").checked
    ? `直通合并：不重编码，音频流原样拼接（速度接近复制）`
    : `将按列表顺序合并 ${n} 个文件（采用以上编码设置）`;
  const volTxt = splitOn && splitN > 0
    ? `拆分为 ${nVols} 卷 · 每卷 ≤${splitN} 章 · 命名 ${$("merge-title").value || "书名"}_01…`
    : `输出单个 .m4b`;
  $("merge-hint").textContent =
    `${head}；${volTxt}；章节名取各文件标题标签，缺省用文件名` +
    (n < 2 && !splitOn ? "（⚠ 至少 2 个文件）" : "");
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

function paramSummary(j) {
  const st = j.settings || {};
  const bits = [];
  if (j.preset_id) {
    const p = state.presets.find((x) => x.id === j.preset_id);
    if (p) bits.push(p.name.replace(/^有声书 · /, ""));
  }
  if (!j.preset_id && st.format) bits.push(String(st.format).toUpperCase());
  if (st.profile) bits.push(st.profile);
  if (st.bitrate) bits.push(st.bitrate);
  if (st.samplerate) bits.push(st.samplerate + "Hz");
  if (st.channels) bits.push(st.channels + "ch");
  if (j.normalize) bits.push("loudnorm");
  return bits.join(" · ") || "默认参数";
}

function jobSourceMissing(j) {
  // failed 且全部源都不在注册表/书库 → 重试必 404
  if (j.status !== "failed") return false;
  const known = new Set([...(state.uploadsAllRaw || []).map((u) => u.id),
                         ...state.uploads.map((u) => u.id)]);
  return j.source_ids.every((sid) =>
    sid.startsWith("lib:") ? false : !known.has(sid));
}

function jobCardHTML(j) {
  const p = (j.progress || 0).toFixed(1);
  let html =
    `<div class="job-top">` +
      `<span class="job-name" title="${escapeHtml(j.output_filename)}">` +
      `${j.mode === "merge" ? icon("music") + " " : ""}${escapeHtml(j.output_filename)}</span>` +
      `<span class="badge ${j.status}">${STATUS_TXT[j.status] || j.status}</span>` +
    `</div>` +
    `<div class="pbar"><div style="width:${p}%"></div></div>` +
    `<div class="small pct-text" style="color:var(--dim)">${p}% · ${escapeHtml(paramSummary(j))}</div>`;
  if (j.verify) {
    const v = j.verify;
    html += `<div class="verify">${icon("check")} <b>${escapeHtml(v.codec)}</b> · <b>${Math.round((v.bitrate || 0) / 1000)}k</b>` +
      ` · ${v.sample_rate}Hz · ${v.channels}ch` +
      (v.savings_pct != null ? ` · 体积省 <b>${v.savings_pct}%</b>（${fmtSize(v.output_size)} / 源 ${fmtSize(v.source_size)}）` : "") +
      `</div>`;
  }
  if (j.error) html += `<div class="joberr" role="alert">${icon("alert")} ${escapeHtml(j.error)}</div>`;

  // 源文件清单（默认折叠）+ 显式删除源文件
  const srcNames = (j.source_names && j.source_names.length)
    ? j.source_names
    : j.source_ids.map((sid) => sid.startsWith("lib:") ? sid.slice(4).split("/").pop() : sid);
  const canDelSources = ["done", "failed", "cancelled"].includes(j.status)
    && !j._srcDeleted
    && j.source_ids.some((sid) => !sid.startsWith("lib:"));
  html += `<div class="job-src">` +
    `<button class="linklike" data-act="togglesrc" data-id="${j.id}">${icon("chevron-down")} 源文件（${srcNames.length}）</button>` +
    (canDelSources ? `<button class="linklike danger" data-act="delsrc" data-id="${j.id}">${icon("trash")} 删除源文件</button>` : "") +
    `</div>` +
    `<ul class="job-src-list hidden" id="src-${j.id}">` +
    srcNames.map((n) => `<li>${icon("music")} ${escapeHtml(n)}</li>`).join("") +
    `</ul>`;

  const acts = [];
  const cleaned = !!j.output_deleted_at;
  if (j.status === "done" && !cleaned) acts.push(`<button class="btn small" data-act="dl" data-id="${j.id}">${icon("download")} 下载</button>`);
  if (j.status === "done" && !cleaned && j.mode === "single")
    acts.push(`<button class="btn small subtle" data-act="batchout" data-id="${j.id}">${icon("settings")} 批量处理</button>`);
  if (j.status === "done" && !cleaned)
    acts.push(`<button class="btn small subtle" data-act="listen" data-id="${j.id}">▶ 试听</button>`);
  if (j.status === "done" && !cleaned && j.source_ids.length)
    acts.push(`<button class="btn small subtle" data-act="abcmp" data-id="${j.id}">A/B 对比</button>`);
  if (j.status === "failed" || j.status === "cancelled") {
    const missing = jobSourceMissing(j);
    acts.push(`<button class="btn small" data-act="retry" data-id="${j.id}" ${missing ? "disabled title=\"源文件已删除，可在已上传文件重新加入后再试\"" : ""}>↻ 重试</button>`);
    if (missing)
      acts.push(`<span class="hint warn-hint-inline">源文件已删除，可重新加入后再试</span>`);
  }
  if (ACTIVE.has(j.status))
    acts.push(`<button class="btn small subtle" data-act="cancel" data-id="${j.id}">${icon("x")} 取消</button>`);
  html += `<div class="job-actions">${acts.join("")}</div>`;
  const cleanedBadge = cleaned
    ? `<span class="badge cleaned">产物已清理</span>` : "";
  return `<li data-job="${j.id}" data-status="${j.status}">${html}${cleanedBadge}</li>`;
}

function bindJobActions(scope) {
  scope.querySelectorAll("[data-act]").forEach((b) => {
    b.onclick = async () => {
      const { act, id } = b.dataset;
      if (act === "dl") location.href = `/api/jobs/${id}/download`;
      else if (act === "batchout") batchOpen("outputs", [id]);
      else if (act === "listen") playJob(id, (state.jobs[id] || {}).output_filename);
      else if (act === "abcmp") abOpen(id);
      else if (act === "retry") await fetch(`/api/jobs/${id}/retry`, { method: "POST" });
      else if (act === "cancel") await fetch(`/api/jobs/${id}`, { method: "DELETE" });
      else if (act === "togglesrc") {
        const list = document.getElementById(`src-${id}`);
        if (list) list.classList.toggle("hidden");
      } else if (act === "delsrc") {
        const j = state.jobs[id];
        if (!j) return;
        const ids = j.source_ids.filter((sid) => !sid.startsWith("lib:"));
        if (!ids.length) return;
        if (!confirm(`删除该任务的 ${ids.length} 个源文件？转换结果不受影响，此操作不可恢复`)) return;
        const res = await fetch("/api/uploads/delete", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids }),
        });
        if (res.ok) {
          const { removed, skipped } = await res.json();
          toast(`已删除 ${removed} 个源文件` +
            (skipped.length ? `；跳过 ${skipped.length} 个正被其他任务使用的文件` : ""));
          if (removed > 0) state.jobs[id]._srcDeleted = true;
          renderJobs();
        }
      }
    };
  });
}

const JOBS_RENDER_CAP = 50;
let _jobsRenderLimit = JOBS_RENDER_CAP;

function updateJobsProgress() {
  const jobs = Object.values(state.jobs);
  const el = $("jobs-progress");
  if (!el) return;
  if (!jobs.length) {
    el.textContent = "";
    document.title = "Audiobook Converter";
    return;
  }
  const done = jobs.filter((j) => j.status === "done").length;
  const active = jobs.filter((j) => ACTIVE.has(j.status));
  const wsum = active.reduce((acc, j) => acc + (j.progress || 0) / 100, 0);
  const pct = Math.round(((done + wsum) / jobs.length) * 100);
  el.textContent = `${done}/${jobs.length} 完成 · 总体 ${pct}%`;
  document.title = `(${pct}%) Audiobook Converter`;
}

function renderJobs() {
  const ul = $("job-list");
  const jobs = Object.values(state.jobs)
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  ul.innerHTML = "";
  if (!jobs.length) {
    _jobsRenderLimit = JOBS_RENDER_CAP;
    updateJobsProgress();
    ul.innerHTML = `<li class="empty empty-jobs">${icon("play")}
      <p>暂无任务 — 选择文件后点「开始转换」</p></li>`;
    return;
  }
  const shown = jobs.slice(0, _jobsRenderLimit);
  updateJobsProgress();
  for (const j of shown) ul.insertAdjacentHTML("beforeend", jobCardHTML(j));
  if (jobs.length > shown.length) {
    ul.insertAdjacentHTML("beforeend",
      `<li class="load-more"><button class="btn small" id="btn-load-more">
        加载更多（还有 ${jobs.length - shown.length} 条）</button></li>`);
    ul.querySelector("#btn-load-more").onclick = () => {
      _jobsRenderLimit += JOBS_RENDER_CAP;
      renderJobs();
    };
  }
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
  updateJobsProgress();   // 单卡更新也驱动全局总览
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
    if (prev) {
      updateJobCard(j, prev);
      if (prev.status !== j.status) maybeNotify(j);
    } else {
      renderJobs();
    }
  });
  es.addEventListener("uploads.changed", (e) => {
    // 文件被删除（已上传 tab / 任务卡片删除源文件）：工作集剔除 + 相关任务标记
    let removed = [];
    try { removed = JSON.parse(e.data).removed || []; } catch (err) {}
    const gone = new Set(removed);
    state.uploads = state.uploads.filter((u) => !gone.has(u.id));
    for (const j of Object.values(state.jobs)) {
      if (j.source_ids.some((sid) => gone.has(sid))) j._srcDeleted = true;
    }
    renderFiles();
    renderJobs();
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
    output_pattern: mergeOn ? null : ($("output-pattern").value.trim() || null),
    merge_split: (mergeOn && $("split-on").checked)
      ? (parseInt($("merge-split").value, 10) || null) : null,
    merge_copy: mergeOn && $("audio-copy").checked,
  };

  if (mergeOn) {
    const body = {
      ...base, mode: "merge", source_ids: sources,
      merge: {
        book_title: $("merge-title").value || null,
        book_artist: $("merge-artist").value || null,
        composer: $("merge-composer").value || null,
        cover_upload_id: state.coverUploadId,
        copy_audio: $("audio-copy").checked,
      },
    };
    const r = await fetch("/api/jobs", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      let detail = "HTTP " + r.status;
      try { detail = (await r.json()).detail; } catch (e) {}
      alert("创建任务失败: " + detail);
      return;
    }
    const d = await r.json();
    if ((d.job_ids || []).length > 1) toast(`已创建 ${d.job_ids.length} 个分卷任务`);
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
  $("btn-clear-finished").onclick = async () => {
    await fetch("/api/jobs/clear-finished", { method: "POST" });
    toast("产物已清理，历史记录保留");
  };
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
  $("preset").onchange = (e) => {
    applyPreset(e.target.value);
    const adv = $("adv-box");
    if (adv) adv.open = e.target.value === "";
    updateMergeHint(); saveSession();
  };
  ["format", "codec", "bitrate", "samplerate", "channels"].forEach((id) =>
    $(id).addEventListener("change", () => {
      $("preset").value = "";
      updateMergeHint();
      saveSession();
    }));
  ["split-off", "split-on", "audio-enc", "audio-copy"].forEach((id) => {
    $(id).addEventListener("change", () => {
      syncMergeModeUi();
      updateMergeHint();
      saveSession();
    });
  });
  $("merge-split").addEventListener("input", () => {
    updateMergeHint();
    saveSession();
  });
  $("merge-on").onchange = (e) => {
    $("merge-fields").classList.toggle("hidden", !e.target.checked);
    document.querySelectorAll(".meta-dup").forEach((el) =>
      el.classList.toggle("hidden", e.target.checked));
    updateMergeHint();
    saveSession();
  };
  // text inputs: save on every keystroke (debounced) so a crash/refresh
  // never loses what the user typed
  ["merge-title", "merge-artist", "merge-composer", "meta-title", "meta-artist",
   "meta-album", "meta-composer", "title-pattern", "output-pattern"].forEach((id) => {
    $(id).addEventListener("input", saveSession);
    $(id).addEventListener("change", saveSession);
  });
  $("normalize").addEventListener("change", saveSession);
  $("merge-cover").addEventListener("change", (e) => {
    const f = e.target.files[0];
    $("cover-name").textContent = f ? f.name : "未选择（可自动提取内嵌封面）";
  });
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

function restoreWorkingSetFromSession() {
  const saved = state.sessionWorkingSet || [];
  if (!saved.length) return;
  fetch("/api/uploads").then((r) => r.json()).then((reg) => {
    const live = new Set(reg.map((u) => u.id));
    for (const x of saved) {
      if (x.kind !== "lib" && !live.has(x.id)) continue;   // 文件已删除 → 丢弃
      if (state.uploads.some((u) => u.id === x.id)) continue;
      state.uploads.push(x.kind === "lib"
        ? { ...x, kind: "lib", order: state.uploads.length }
        : { ...byIdReg(reg, x.id), kind: "upload", lastModified: x.lastModified,
            order: state.uploads.length });
    }
    renderFiles();
    updateMergeHint();
  }).catch(() => {});
}

function byIdReg(reg, id) {
  return reg.find((u) => u.id === id) || { id, name: id, size: 0 };
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
  wireUploadsLibrary();
  wireHeaderButtons();
  wireBatch();
  wireMiniPlayer();
  wireAbPlayer();
  wirePlayButtons();
  wireNotify();
  connectSSE();
  restoreSessionFromServer();
  restoreWorkingSetFromSession();
  renderFiles();
  updateMergeHint();
}

// flush pending session on tab close / hide
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flushSessionBeacon();
});
window.addEventListener("pagehide", flushSessionBeacon);

document.addEventListener("DOMContentLoaded", init);
