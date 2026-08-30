/* Audiobook Converter — Vanilla JS frontend */
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  uploads: [],        // [{id,name,size,info}] from /api/upload
  libPath: "",
  libRoots: [],
  presets: [],
  jobs: {},           // id -> job (SSE)
  coverUploadId: null,
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
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.round(s % 60);
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${String(sec).padStart(2, "0")}` : `${m}分${String(sec).padStart(2, "0")}秒`;
};

/* ============ health & presets ============ */

async function loadHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    const el = $("health-badge");
    const disabled = h.presets_disabled || 0;
    el.textContent = `ffmpeg ✓ · ${h.encoders.length} 编码器` + (disabled ? ` · ${disabled} 预设停用` : "");
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

async function uploadFiles(fileList) {
  // sequential uploads keep state.uploads order == the user's file order,
  // which defines the chapter order for M4B merging
  for (const f of fileList) {
    await new Promise((resolve) => {
      const row = document.createElement("div");
      row.className = "uprow";
      row.innerHTML =
        `<div class="uprow-top"><span>${escapeHtml(f.name)}</span><span class="pct">0%</span></div>` +
        `<div class="upbar"><div></div></div>`;
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
          state.uploads.push(...uploads);
          scheduleRender();
          bar.style.width = "100%";
          pct.textContent = "✓ 已加入";
        } else {
          let msg = "HTTP " + xhr.status;
          try { msg = JSON.parse(xhr.responseText).detail; } catch (e) {}
          pct.textContent = "✗ " + msg;
        }
        setTimeout(() => { row.remove(); resolve(); }, 400);
      };
      xhr.onerror = () => { pct.textContent = "✗ 网络错误"; resolve(); };
      xhr.send(fd);
    });
  }
}

/* ============ file list ============ */

let _renderQueued = false;
function scheduleRender() {
  // debounced full-list render — folder drops can add thousands of files,
  // re-rendering per upload would be O(n²)
  if (_renderQueued) return;
  _renderQueued = true;
  setTimeout(() => { _renderQueued = false; renderFiles(); }, 120);
}

function renderFiles() {
  const ul = $("file-list");
  ul.innerHTML = "";
  if (!state.uploads.length) {
    ul.innerHTML = `<li class="empty">尚未上传文件</li>`;
  }
  for (const u of state.uploads) {
    const li = document.createElement("li");
    const dur = u.info && u.info.duration ? " · " + fmtDur(u.info.duration) : "";
    li.innerHTML = `<span class="name">🎵 ${escapeHtml(u.name)}</span>` +
      `<span class="meta">${fmtSize(u.size)}${dur}</span>` +
      `<button class="del" title="移除">✕</button>`;
    li.querySelector(".del").onclick = () => {
      state.uploads = state.uploads.filter((x) => x.id !== u.id);
      if (state.coverUploadId === u.id) state.coverUploadId = null;
      renderFiles();
    };
    ul.appendChild(li);
  }
  updateMergeHint();
}

/* ============ library browser ============ */

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
      const li = document.createElement("li");
      li.innerHTML = `<input type="checkbox" class="libpick" data-libid="${escapeHtml(f.id)}" data-libname="${escapeHtml(f.name)}">` +
        `<span class="name">🎵 ${escapeHtml(f.name)}</span><span class="meta">${fmtSize(f.size)}</span>`;
      li.querySelector("input").addEventListener("change", updateMergeHint);
      ul.appendChild(li);
    }
  } catch (e) {
    $("lib-path").textContent = "加载失败: " + e;
  }
}

async function loadRoots() {
  try {
    const res = await (await fetch("/api/library/roots")).json();
    $("lib-roots").textContent = res.roots.join(" ; ");
  } catch (e) { /* ignore */ }
  libLoad("");
}

function libSelection() {
  return [...document.querySelectorAll("#lib-list input.libpick:checked")]
    .map((cb) => ({ id: cb.dataset.libid, name: cb.dataset.libname || cb.dataset.libname }));
}

/* ============ merge helpers ============ */

function totalSources() {
  return state.uploads.length + libSelection().length;
}

function updateMergeHint() {
  const n = totalSources();
  const mergeOn = $("merge-on").checked;
  const errCount = renderMergeHints();
  $("merge-hint").textContent = mergeOn
    ? `将按顺序合并 ${n} 个文件为一个 .m4b（采用下方编码设置）；章节名取各文件标题标签，缺省用文件名` +
      (n < 2 ? "（⚠ 至少 2 个文件）" : "")
    : `将为 ${n} 个文件各创建一个转码任务`;
  $("btn-start").disabled =
    n === 0 || (mergeOn && n < 2) || (mergeOn && errCount > 0);
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
  if (j.status === "done") acts.push(`<button class="btn" data-act="dl" data-id="${j.id}">⬇ 下载</button>`);
  if (j.status === "failed" || j.status === "cancelled")
    acts.push(`<button class="btn" data-act="retry" data-id="${j.id}">↻ 重试</button>`);
  if (ACTIVE.has(j.status))
    acts.push(`<button class="btn subtle" data-act="cancel" data-id="${j.id}">✕ 取消</button>`);
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
    ul.innerHTML = `<li class="empty">暂无任务 — 上传/勾选文件后点「开始转换」</li>`;
    return;
  }
  for (const j of jobs) {
    ul.insertAdjacentHTML("beforeend", jobCardHTML(j));
  }
  bindJobActions(ul);
}

/* incremental update: progress tweaks bar width in place (keeps buttons
   clickable during high-frequency SSE), full card rebuild only on status change */
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
  const lib = libSelection();
  const sources = [...state.uploads.map((u) => u.id), ...lib.map((f) => f.id)];
  if (!sources.length) { alert("请先在左侧选择文件"); return; }
  const mergeOn = $("merge-on").checked;
  if (mergeOn && sources.length < 2) { alert("合并模式至少需要 2 个文件"); return; }

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
  };

  if (mergeOn) {
    const body = {
      ...base, mode: "merge", source_ids: sources,
      merge: {
        book_title: $("merge-title").value || null,
        book_artist: $("merge-artist").value || null,
        cover_upload_id: state.coverUploadId,
      },
    };
    if (!(await postJob(body)).ok) return;
  } else {
    for (const sid of sources) {
      const ok = await postJob({ ...base, mode: "single", source_ids: [sid] });
      if (!ok) return;
    }
  }
}

function currentSettings() {
  // active preset provides the base (carries profile / compression_level that
  // have no dedicated field), explicit field values act as overrides
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

/* ---- merge compatibility hints (per-parameter, Apple/m4b rules) ---- */

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

function currentMetadata() {
  return {
    title: $("meta-title").value || null,
    artist: $("meta-artist").value || null,
    album: $("meta-album").value || null,
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

/* ============ folder collection (drag & drop + picker) ============ */

const hasAudioExt = (name) => AUDIO_EXT.has(name.slice(name.lastIndexOf(".")).toLowerCase());

function readEntriesAll(reader) {
  // readEntries returns at most 100 entries per call — loop until empty batch
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

function wireDropzone() {
  const dz = $("dropzone");
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", async (e) => {
    e.preventDefault();
    dz.classList.remove("drag");
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
  };
}

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

function wireSettings() {
  $("preset").onchange = (e) => { applyPreset(e.target.value); updateMergeHint(); };
  ["format", "codec", "bitrate", "samplerate", "channels"].forEach((id) =>
    $(id).addEventListener("change", () => {
      $("preset").value = "";
      updateMergeHint();   // re-render per-parameter compatibility hints
    }));
  $("merge-on").onchange = (e) => {
    $("merge-fields").classList.toggle("hidden", !e.target.checked);
    updateMergeHint();
  };
  $("btn-start").onclick = startConversion;
}

function wireLibrary() {
  $("lib-up").onclick = () => {
    const p = state.libPath || "";
    const parent = p.split("/").slice(0, -1).join("/");
    libLoad(parent || "/");
  };
}

const FORMAT_OPTIONS = [
  ["opus", "Opus (.opus)"], ["m4a", "AAC/M4A (.m4a)"], ["m4b", "M4B 有声书 (.m4b)"],
  ["mp3", "MP3 (.mp3)"], ["ogg", "Ogg Vorbis (.ogg)"], ["flac", "FLAC 无损 (.flac)"], ["wav", "WAV (.wav)"],
];
const CODEC_OPTIONS = [
  ["", "自动"], ["libopus", "libopus"], ["aac", "aac（原生）"],
  ["libfdk_aac", "libfdk_aac（HE-AAC）"], ["libmp3lame", "libmp3lame"],
  ["libvorbis", "libvorbis"], ["flac", "flac"], ["pcm_s16le", "pcm_s16le"],
];

const DEFAULT_CODEC = {
  mp3: "libmp3lame", m4a: "aac", m4b: "aac", opus: "libopus",
  ogg: "libvorbis", flac: "flac", wav: "pcm_s16le",
};
const AUDIO_EXT = new Set([".mp3", ".m4a", ".m4b", ".aac", ".flac", ".ogg",
                           ".opus", ".wav", ".wma", ".aiff", ".mka"]);
const M4B_CODECS = new Set(["aac", "libfdk_aac"]);

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
  $("format").value = "m4a";   // audiobook-friendly default
}

function init() {
  populateFormatCodec();
  loadPresets();
  loadHealth();
  wireDropzone();
  wireTabs();
  wireSettings();
  wireLibrary();
  wireHeaderButtons();
  connectSSE();
  renderFiles();
  updateMergeHint();
}

document.addEventListener("DOMContentLoaded", init);
