"use strict";

// ===== 全局状态 =====
const files = new Map(); // file_id -> 配置对象
let moreEditingId = null; // 「更多设置」弹窗当前编辑的文件
let pollTimer = null;

const $ = (id) => document.getElementById(id);

// 统一请求封装：登录失效（401）时自动跳回登录页
async function req(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) {
    location.href = "/login";
    throw new Error("未登录");
  }
  return r;
}

// ===== 工具 =====
function toast(msg, type = "") {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast " + type;
  setTimeout(() => el.classList.add("hidden"), 3200);
}
const show = (el) => el.classList.remove("hidden");
const hide = (el) => el.classList.add("hidden");

function fmtSize(b) {
  if (!b) return "";
  return b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB";
}
function iconFor(ext) {
  ext = (ext || "").toLowerCase();
  if (["jpg", "jpeg", "png", "bmp", "gif", "webp", "tif", "tiff"].includes(ext)) return "🖼️";
  if (ext === "pdf") return "📕";
  if (["doc", "docx", "rtf"].includes(ext)) return "📘";
  if (["xls", "xlsx", "csv"].includes(ext)) return "📗";
  if (["ppt", "pptx"].includes(ext)) return "📙";
  return "📄";
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}
function setSeg(segId, val) {
  document.querySelectorAll(`#${segId} .seg-btn`).forEach((b) =>
    b.classList.toggle("active", b.dataset.val === val)
  );
}
function getSeg(segId) {
  const a = document.querySelector(`#${segId} .seg-btn.active`);
  return a ? a.dataset.val : "";
}

// ===== 打印机列表 =====
async function loadPrinters() {
  const sel = $("printer");
  try {
    const r = await req("/api/printers");
    const data = await r.json();
    sel.innerHTML = "";
    if (!data.printers || data.printers.length === 0) {
      sel.innerHTML = '<option value="">系统默认打印机</option>';
    } else {
      data.printers.forEach((name) => {
        const o = document.createElement("option");
        o.value = name; o.textContent = name;
        if (name === data.default) o.selected = true;
        sel.appendChild(o);
      });
    }
  } catch (e) {
    sel.innerHTML = '<option value="">系统默认打印机</option>';
  }
}

// ===== 上传（多文件） =====
async function uploadFiles(list) {
  for (const f of list) {
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await req("/api/upload", { method: "POST", body: fd });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "上传失败");
      addCard(d);
    } catch (e) {
      toast(`「${f.name}」上传失败：` + e.message, "err");
    }
  }
}

function defaultConfig(meta) {
  return {
    file_id: meta.file_id, filename: meta.filename, ext: meta.ext || "", size: meta.size || 0,
    copies: 1, color: "monochrome", page_range: "", duplex: "simplex",
    paper: "", pages_per_sheet: 1, scaling: "shrink", pages: null,
  };
}

function addCard(meta) {
  const cfg = defaultConfig(meta);
  files.set(cfg.file_id, cfg);

  const li = document.createElement("li");
  li.className = "file-card";
  li.dataset.id = cfg.file_id;
  li.innerHTML = `
    <span class="fc-icon">${iconFor(cfg.ext)}</span>
    <div class="fc-info">
      <div class="fc-name">${escapeHtml(cfg.filename)}</div>
      <div class="fc-meta">${(cfg.ext || "文件").toUpperCase()} · ${fmtSize(cfg.size)}</div>
    </div>
    <div class="fc-basic">
      <label>份数 <input type="number" class="fc-copies" min="1" max="99" value="1"></label>
      <div class="seg fc-color">
        <button data-val="monochrome" class="seg-btn active">⚫ 黑白</button>
        <button data-val="color" class="seg-btn">🌈 彩色</button>
      </div>
    </div>
    <div class="fc-actions">
      <button class="btn btn-ghost btn-sm act-preview">👁 预览</button>
      <button class="btn btn-ghost btn-sm act-more">⚙ 更多</button>
      <button class="btn btn-primary btn-sm act-print">🖨️ 打印</button>
      <button class="btn btn-ghost btn-sm act-del">✕</button>
    </div>`;

  li.querySelector(".fc-copies").addEventListener("change", (e) => {
    cfg.copies = Math.max(1, Math.min(99, parseInt(e.target.value || "1", 10)));
    e.target.value = cfg.copies;
  });
  li.querySelector(".fc-color").addEventListener("click", (e) => {
    const b = e.target.closest(".seg-btn");
    if (!b) return;
    li.querySelectorAll(".fc-color .seg-btn").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    cfg.color = b.dataset.val;
  });
  li.querySelector(".act-preview").addEventListener("click", () => doPreview(cfg.file_id));
  li.querySelector(".act-more").addEventListener("click", () => openMore(cfg.file_id));
  li.querySelector(".act-print").addEventListener("click", () => doPrint(cfg.file_id));
  li.querySelector(".act-del").addEventListener("click", () => removeCard(cfg.file_id));

  $("fileList").appendChild(li);
  updateToolbar();
}

function updateToolbar() {
  const has = files.size > 0;
  $("printAllBtn").disabled = !has;
  $("clearAllBtn").disabled = !has;
}

// ===== 更多设置 弹窗 =====
function openMore(fid) {
  const cfg = files.get(fid);
  if (!cfg) return;
  moreEditingId = fid;
  $("moreFileName").textContent = cfg.filename;
  $("morePageRange").value = cfg.page_range;
  $("morePageTotal").textContent = cfg.pages ? `（共 ${cfg.pages} 页）` : "（预览后显示总页数）";
  $("morePageRange").placeholder = cfg.pages ? `留空=全部（1-${cfg.pages}）` : "留空=全部，如 1-5,8";
  $("moreDuplex").value = cfg.duplex;
  $("morePaper").value = cfg.paper;
  $("morePps").value = String(cfg.pages_per_sheet);
  setSeg("moreScaling", cfg.scaling);
  show($("moreModal"));
}
$("moreScaling").addEventListener("click", (e) => {
  const b = e.target.closest(".seg-btn");
  if (b) setSeg("moreScaling", b.dataset.val);
});
$("moreSaveBtn").addEventListener("click", () => {
  const cfg = files.get(moreEditingId);
  if (!cfg) return;
  cfg.page_range = $("morePageRange").value.trim();
  cfg.duplex = $("moreDuplex").value;
  cfg.paper = $("morePaper").value;
  cfg.pages_per_sheet = parseInt($("morePps").value || "1", 10);
  cfg.scaling = getSeg("moreScaling") || "noscale";
  hide($("moreModal"));
  toast("设置已保存 ✓", "ok");
});

// ===== 预览 弹窗（按需转换） =====
async function doPreview(fid) {
  const cfg = files.get(fid);
  if (!cfg) return;
  $("previewName").textContent = cfg.filename;
  hide($("previewFrame"));
  show($("previewLoading"));
  show($("previewModal"));
  try {
    const r = await req("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_id: fid }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "转换失败");
    cfg.pages = d.pages || cfg.pages;
    $("previewFrame").src = d.preview_url;
    hide($("previewLoading"));
    show($("previewFrame"));
  } catch (e) {
    hide($("previewModal"));
    toast("预览失败：" + e.message, "err");
  }
}

// ===== 打印 =====
async function doPrint(fid) {
  const cfg = files.get(fid);
  if (!cfg) return;
  const payload = {
    file_id: fid, printer: $("printer").value, color: cfg.color, copies: cfg.copies,
    page_range: cfg.page_range, duplex: cfg.duplex, paper: cfg.paper,
    pages_per_sheet: cfg.pages_per_sheet, scaling: cfg.scaling,
  };
  try {
    const r = await req("/api/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "提交失败");
    toast(`已提交打印：${cfg.filename}`, "ok");
    startPolling();
  } catch (e) {
    toast(`「${cfg.filename}」打印失败：` + e.message, "err");
  }
}
async function printAll() {
  if (files.size === 0) return;
  for (const fid of files.keys()) await doPrint(fid);
}

// ===== 删除 / 清空 =====
async function removeCard(fid) {
  // 先调后端删，如果后端拒绝（文件正在打印中），恢复卡片
  try {
    const r = await req("/api/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_id: fid }),
    });
    const d = await r.json();
    if (d.ok === false) {
      toast(d.reason || "文件正在使用中，无法删除", "err");
      return;  // 不移除卡片
    }
  } catch (e) {
    toast("删除失败：" + e.message, "err");
    return;
  }
  files.delete(fid);
  const li = document.querySelector(`.file-card[data-id="${fid}"]`);
  if (li) li.remove();
  updateToolbar();
}
function clearAll() {
  Array.from(files.keys()).forEach(removeCard);
}

// ===== 任务状态轮询 =====
function renderJobs(jobs) {
  const jobList = $("jobList");
  if (!jobs || jobs.length === 0) {
    jobList.innerHTML = '<li class="job-empty">还没有打印任务</li>';
    return;
  }
  jobList.innerHTML = "";
  jobs.forEach((j) => {
    const li = document.createElement("li");
    li.className = "job-item";

    const left = document.createElement("div");
    left.className = "job-left";
    const name = document.createElement("div");
    name.className = "job-name";
    name.textContent = j.copies > 1 ? `${j.filename} ×${j.copies}` : j.filename;
    left.appendChild(name);
    // 等待打印机时的提示文字（如"打印机休眠，请按唤醒键"）
    const hint = j.status === "failed" ? j.error : j.note;
    if (hint && (j.status === "waiting" || j.status === "waiting_flip"
        || j.status === "failed" || j.status === "canceled")) {
      const note = document.createElement("div");
      note.className = "job-note";
      note.textContent = hint;
      left.appendChild(note);
    }

    const actions = document.createElement("div");
    actions.className = "job-actions";
    if (j.resumable) {
      const resumeBtn = document.createElement("button");
      resumeBtn.className = "job-continue";
      resumeBtn.textContent = "继续打印";
      resumeBtn.title = "翻面后继续打印第二面";
      resumeBtn.addEventListener("click", () => resumeJob(j, resumeBtn));
      actions.appendChild(resumeBtn);
    }
    if (j.cancellable) {
      const cancelBtn = document.createElement("button");
      cancelBtn.className = "job-cancel";
      cancelBtn.textContent = "取消";
      cancelBtn.title = "取消这个打印任务";
      cancelBtn.addEventListener("click", () => cancelJob(j, cancelBtn));
      actions.appendChild(cancelBtn);
    }

    const badge = document.createElement("span");
    badge.className = "badge " + j.status;
    badge.textContent = j.status_label;
    if (j.error) badge.title = j.error;
    actions.appendChild(badge);

    li.appendChild(left);
    li.appendChild(actions);
    jobList.appendChild(li);
  });
}
async function resumeJob(j, btn) {
  btn.disabled = true;
  btn.textContent = "继续中…";
  try {
    const r = await req(`/api/jobs/${encodeURIComponent(j.id)}/resume`, { method: "POST" });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "继续失败");
    const msg = d.message || (d.ok ? "已继续打印" : d.reason || "继续失败");
    toast(msg, d.ok ? "ok" : "err");
    if (!d.ok) {
      btn.disabled = false;
      btn.textContent = "继续打印";
    }
    startPolling();
  } catch (e) {
    toast("继续失败：" + e.message, "err");
    btn.disabled = false;
    btn.textContent = "继续打印";
  }
}

async function cancelJob(j, btn) {
  if (!confirm(`确定取消「${j.filename}」的打印任务吗？`)) return;
  btn.disabled = true;
  btn.textContent = "取消中…";
  try {
    const r = await req(`/api/jobs/${encodeURIComponent(j.id)}/cancel`, { method: "POST" });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "取消失败");
    const msg = d.message || (d.ok ? "已取消" : d.reason || "取消失败");
    toast(msg, d.ok ? "ok" : "err");
    if (!d.ok) {
      btn.disabled = false;
      btn.textContent = "取消";
    }
    startPolling();
  } catch (e) {
    toast("取消失败：" + e.message, "err");
    btn.disabled = false;
    btn.textContent = "取消";
  }
}

async function refreshJobs() {
  try {
    const r = await req("/api/jobs");
    const data = await r.json();
    renderJobs(data.jobs);
    const active = (data.jobs || []).some((j) =>
      ["queued", "converting", "printing", "waiting", "waiting_flip"].includes(j.status)
    );
    if (!active && pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  } catch (e) { /* 忽略瞬时网络错误 */ }
}
function startPolling() {
  refreshJobs();
  if (!pollTimer) pollTimer = setInterval(refreshJobs, 2000);
}

// ===== 绑定 =====
$("dropzone").addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", (e) => {
  if (e.target.files.length) uploadFiles(e.target.files);
  e.target.value = "";
});
["dragover", "dragenter"].forEach((ev) =>
  $("dropzone").addEventListener(ev, (e) => {
    e.preventDefault();
    $("dropzone").classList.add("drag");
  })
);
["dragleave", "drop"].forEach((ev) =>
  $("dropzone").addEventListener(ev, (e) => {
    e.preventDefault();
    $("dropzone").classList.remove("drag");
  })
);
$("dropzone").addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
});
$("printAllBtn").addEventListener("click", printAll);
$("clearAllBtn").addEventListener("click", clearAll);
$("logoutBtn").addEventListener("click", async () => {
  try { await fetch("/api/logout", { method: "POST" }); } catch (e) { /* 忽略 */ }
  location.href = "/login";
});
document.querySelectorAll("[data-close]").forEach((b) =>
  b.addEventListener("click", () => hide($(b.dataset.close)))
);
["moreModal", "previewModal"].forEach((id) =>
  $(id).addEventListener("click", (e) => {
    if (e.target === $(id)) hide($(id));
  })
);

// ===== 启动 =====
loadPrinters();
refreshJobs();
