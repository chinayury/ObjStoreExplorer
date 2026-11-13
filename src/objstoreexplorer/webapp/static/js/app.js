/*
Project: ObjStoreExplorer 对象存储管理工具
Copyright (c) 2026 智维工作室 All Rights Reserved.
著作权由智维工作室对应的自然人主体持有。
本源码受著作权法保护，仅获得许可方可使用。
禁止未经许可分发、转售、开源。
*/

/* ObjStoreExplorer Web - 公共运行时
   依赖: window.OSE 由 base.html 注入 (user/connected/endpoint/isAdmin) */
"use strict";

/* ==================== 图标助手 (暮橙 Emberline 设计系统 SVG sprite) ==================== */

/* 用法: OSE.icon("bucket") → <svg class="ic">…</svg>。
   动态插入的 <use> 引用 base.html 里的 sprite symbol, 同文档内即刻生效。 */
OSE.icon = function (name, cls) {
  return '<svg class="ic' + (cls ? " " + cls : "") + '"><use href="#i-' + name + '"/></svg>';
};

/* 导航高亮: 旧版用模板 block 在循环内输出 active, Jinja 会对每次迭代
   重复渲染同一 override, 导致所有导航项同时高亮 (存量 BUG)。
   改为按 body[data-page] 精确点亮。 */
(function () {
  const page = document.body.dataset.page;
  if (!page) return;
  document.querySelectorAll(".sidebar nav a[data-nav]").forEach((a) => {
    a.classList.toggle("active", a.dataset.nav === page);
  });
})();

/* ==================== API 封装 ==================== */

OSE.api = async function (method, url, body, opts) {
  opts = opts || {};
  const init = { method, headers: {}, credentials: "same-origin" };
  if (body !== undefined && body !== null) {
    if (body instanceof FormData) {
      init.body = body; // 浏览器自动 multipart
    } else {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
  }
  let resp;
  try {
    resp = await fetch(url, init);
  } catch (e) {
    OSE.toast("网络错误: " + e.message, "error");
    throw e;
  }
  if (resp.status === 401) {
    /* v0.1.0: 带过期标记跳登录页, 登录页显示"登录已过期"提示而不是无声消失 */
    location.href = "/login?expired=1";
    throw new Error("未登录");
  }
  let data = null;
  try { data = await resp.json(); } catch (e) { /* 非 JSON (文件流等) */ }
  if (!resp.ok && !opts.allowError) {
    const msg = (data && data.message) || ("HTTP " + resp.status);
    OSE.toast(msg, "error");
    const err = new Error(msg); err.data = data; err.status = resp.status;
    throw err;
  }
  return { ok: resp.ok, status: resp.status, data };
};

OSE.get = (u, o) => OSE.api("GET", u, null, o);
OSE.post = (u, b, o) => OSE.api("POST", u, b, o);
OSE.put = (u, b, o) => OSE.api("PUT", u, b, o);
OSE.patch = (u, b, o) => OSE.api("PATCH", u, b, o);
/* v0.1.0: del 增加可选 body —— DELETE /api/versions/{bucket} 需要带
   {key, version_id}; 不传 body 时行为与旧版完全一致。 */
OSE.del = (u, b, o) => OSE.api("DELETE", u, b, o);

/* ==================== Toast / 对话框 ==================== */

OSE.toast = function (msg, kind) {
  const box = document.getElementById("toast-box");
  const el = document.createElement("div");
  el.className = "toast " + (kind || "info");
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), kind === "error" ? 6000 : 3200);
};

OSE.openModal = (id) => document.getElementById(id).classList.add("open");
OSE.closeModal = (id) => document.getElementById(id).classList.remove("open");
document.querySelectorAll(".modal-mask").forEach((m) =>
  m.addEventListener("mousedown", (e) => { if (e.target === m) m.classList.remove("open"); }));

OSE.confirm = function (title, text) {
  return new Promise((resolve) => {
    document.getElementById("confirm-title").textContent = title;
    document.getElementById("confirm-text").textContent = text;
    const ok = document.getElementById("confirm-ok");
    const clone = ok.cloneNode(true);
    ok.parentNode.replaceChild(clone, ok);
    document.getElementById("confirm-modal").classList.add("open");
    clone.addEventListener("click", () => {
      document.getElementById("confirm-modal").classList.remove("open");
      resolve(true);
    });
    document.getElementById("confirm-modal").addEventListener("mousedown", function h(e) {
      if (e.target.id === "confirm-modal") { resolve(false); this.removeEventListener("mousedown", h); }
    });
  });
};

/* 通用输入对话框: returns {v1, v2} 或 null (取消) */
OSE.prompt = function (title, label, opts) {
  opts = opts || {};
  return new Promise((resolve) => {
    document.getElementById("prompt-title").textContent = title;
    document.getElementById("prompt-label").textContent = label;
    const inp = document.getElementById("prompt-input");
    inp.value = opts.value || "";
    const extraWrap = document.getElementById("prompt-extra-wrap");
    if (opts.extraLabel !== undefined) {
      extraWrap.style.display = "";
      document.getElementById("prompt-extra-label").textContent = opts.extraLabel;
      document.getElementById("prompt-extra").value = opts.extraValue || "";
    } else extraWrap.style.display = "none";
    document.getElementById("prompt-hint").textContent = opts.hint || "";
    const ok = document.getElementById("prompt-ok");
    const clone = ok.cloneNode(true);
    ok.parentNode.replaceChild(clone, ok);
    document.getElementById("prompt-modal").classList.add("open");
    inp.focus();
    const finish = (val) => {
      document.getElementById("prompt-modal").classList.remove("open");
      resolve(val === null ? null : { v1: inp.value.trim(), v2: (document.getElementById("prompt-extra").value || "").trim() });
    };
    clone.addEventListener("click", () => finish(1));
    inp.addEventListener("keydown", function k(e) {
      if (e.key === "Enter") { inp.removeEventListener("keydown", k); finish(1); }
    });
  });
};

/* ==================== 连接状态 / 连接对话框 ==================== */

OSE.updateBadge = function (connected, endpoint) {
  const badge = document.getElementById("conn-badge");
  const text = document.getElementById("conn-text");
  if (connected) {
    badge.classList.add("on");
    text.textContent = "已连接 · " + (endpoint || "");
  } else {
    badge.classList.remove("on");
    text.textContent = "未连接";
  }
  document.getElementById("btn-disconnect").disabled = !connected;
};

OSE.showConnect = async function () {
  OSE.openModal("connect-modal");
  document.getElementById("conn-error").textContent = "";
  try {
    const { data } = await OSE.get("/api/history");
    const sel = document.getElementById("conn-history");
    sel.innerHTML = '<option value="">— 选择历史连接 —</option>';
    (data.data || []).forEach((h) => {
      const opt = document.createElement("option");
      opt.value = h.name;
      opt.textContent = `${h.name} (${h.ssl ? "HTTPS" : "HTTP"})`;
      opt.dataset.endpoint = h.endpoint;
      opt.dataset.ssl = h.ssl ? "1" : "";
      sel.appendChild(opt);
    });
  } catch (e) { /* 未连接也能填表单 */ }
};

OSE.fillHistory = function (name) {
  const sel = document.getElementById("conn-history");
  const opt = sel.selectedOptions[0];
  if (!name || !opt) return;
  document.getElementById("conn-endpoint").value = opt.dataset.endpoint || "";
  document.getElementById("conn-ssl").checked = !!opt.dataset.ssl;
  document.getElementById("conn-ak").value = "";
  document.getElementById("conn-sk").value = "";
};

OSE.doConnect = async function (opts) {
  /* v0.1.0: opts.testOnly = 只验证可达性与凭据 (不保存历史, 成功后立即断开) */
  opts = opts || {};
  const btn = document.getElementById(opts.testOnly ? "conn-test" : "conn-submit");
  const err = document.getElementById("conn-error");
  err.textContent = "";
  const body = {
    endpoint: document.getElementById("conn-endpoint").value.trim(),
    access_key: document.getElementById("conn-ak").value,
    secret_key: document.getElementById("conn-sk").value,
    ssl: document.getElementById("conn-ssl").checked,
    save: opts.testOnly ? false : document.getElementById("conn-save").checked,
    external_host: document.getElementById("conn-external-host").value.trim(),
  };
  if (!body.endpoint) { err.textContent = "Endpoint 不能为空"; return; }
  if (!body.access_key || !body.secret_key) {
    err.textContent = opts.testOnly ? "测试连接也需要填写 Access Key / Secret Key" : "Access Key / Secret Key 不能为空";
    return;
  }
  btn.disabled = true; btn.textContent = opts.testOnly ? "测试中…" : "连接中…";
  try {
    const { data } = await OSE.post("/api/connect", body);
    if (data.success) {
      if (opts.testOnly) {
        /* 测试成功: 立即断开, 不占用会话连接位 */
        try { await OSE.post("/api/disconnect", {}); } catch (e) { /* ignore */ }
        err.style.color = "var(--success, #1F9D6C)";
        err.textContent = `连接测试成功: ${body.endpoint}` +
          (data.data && data.data.server_version ? ` (服务端 ${data.data.server_version})` : "");
        OSE.toast("连接测试成功, 凭据可用", "success");
        setTimeout(() => { err.textContent = ""; err.style.color = "var(--danger)"; }, 8000);
      } else {
        OSE.closeModal("connect-modal");
        OSE.toast("连接成功: " + body.endpoint, "success");
        OSE.updateBadge(true, body.endpoint);
        OSE.onConnectionChanged && OSE.onConnectionChanged(true);
        OSE.refreshPage();
      }
    } else {
      err.textContent = data.message || (opts.testOnly ? "测试失败" : "连接失败");
    }
  } catch (e) {
    err.textContent = e.message;
  } finally {
    btn.disabled = false; btn.textContent = opts.testOnly ? "测试连接" : "连接";
  }
};

OSE.disconnect = async function () {
  if (!OSE.state || !OSE.state.connected) return;
  if (!(await OSE.confirm("断开连接", "确定断开当前 S3 连接?"))) return;
  try {
    await OSE.post("/api/disconnect", {});
    OSE.toast("已断开连接", "info");
    OSE.updateBadge(false, "");
    OSE.onConnectionChanged && OSE.onConnectionChanged(false);
    OSE.refreshPage();
  } catch (e) { /* toast 已提示 */ }
};

/* ==================== 任务面板 / 轮询 ==================== */

OSE._taskTimer = null;

OSE.showTasks = function () {
  OSE.openModal("tasks-modal");
  OSE._renderTasks();
};

OSE._renderTasks = async function () {
  const box = document.getElementById("tasks-list");
  if (!document.getElementById("tasks-modal").classList.contains("open")) return;
  try {
    const { data } = await OSE.get("/api/tasks");
    const tasks = data.data || [];
    const running = tasks.filter((t) => t.status === "running").length;
    const cnt = document.getElementById("task-count");
    cnt.style.display = running ? "block" : "none";
    cnt.textContent = running;
    if (!tasks.length) { box.innerHTML = '<div class="loading-tip">暂无任务</div>'; return; }
    box.innerHTML = tasks.map((t) => {
      const pct = Math.round((t.progress || 0) * 100);
      let badge = "";
      if (t.status === "running") badge = '<span class="tag info task-badge">进行中</span>';
      else if (t.status === "done") badge = '<span class="tag ok task-badge">完成</span>';
      else if (t.status === "failed") badge = '<span class="tag err task-badge">失败</span>';
      else badge = '<span class="tag off task-badge">已取消</span>';
      let actions = "";
      if (t.status === "running")
        actions = `<button class="btn sm" onclick="OSE.cancelTask('${t.id}')">取消</button>`;
      else if (t.kind === "download_zip" && t.status === "done" && t.result_ready)
        actions = `<a class="btn sm primary" href="/api/tasks/${t.id}/result">下载 ZIP</a>`;
      let detail = "";
      if (t.error) detail += `! ${OSE.escapeHtml(t.error)}\n`;
      const failures = (t.details || []).filter((d) => !d.success);
      if (failures.length)
        detail += failures.slice(0, 10).map((d) =>
          `x ${OSE.escapeHtml(d.key || d.file || "")}: ${OSE.escapeHtml(d.message || "")}`).join("\n");
      return `<div class="task-row">
        <div class="info">
          <div class="name">${OSE.escapeHtml(t.label)} ${badge}</div>
          <div class="progress"><div class="bar" style="width:${t.status === "running" ? pct : 100}%"></div></div>
          ${t.status === "running" ? `<div class="task-details">${t.current}/${t.total} ${OSE.escapeHtml(t.current_name || "")}</div>` : ""}
          ${detail ? `<div class="task-details">${detail}</div>` : ""}
        </div>${actions}</div>`;
    }).join("");
  } catch (e) { /* ignore */ }
};

OSE.cancelTask = async function (id) {
  try { await OSE.post(`/api/tasks/${id}/cancel`, {}); OSE.toast("已请求取消", "info"); } catch (e) {}
};

OSE._startTaskPolling = function () {
  if (OSE._taskTimer) return;
  OSE._taskTimer = setInterval(() => OSE._renderTasks(), 1500);
};

/* ==================== 工具 ==================== */

OSE.escapeHtml = function (s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
};

OSE.fmtBytes = function (n) {
  if (n == null || n < 0) return "-";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return i === 0 ? v + " B" : v.toFixed(2) + " " + u[i];
};

OSE.fmtTime = function (s) { return s ? String(s).replace("T", " ") : "-"; };

/* D33 相对时间 (借鉴 bucketdock): 表格时间列显示「3 分钟前」这类
   相对时间, 鼠标悬停 (title) 展示完整时间戳 —— 扫一眼知新旧,
   要精确值时悬停即可, 不用去猜格式。 */
OSE.relTime = function (s) {
  if (!s) return "-";
  const d = new Date(String(s).replace(" ", "T"));
  if (isNaN(d.getTime())) return OSE.fmtTime(s);
  const diff = Date.now() - d.getTime();
  if (diff < 0) return OSE.fmtTime(s);           // 时钟偏差: 退回原值
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return min + " 分钟前";
  const h = Math.floor(min / 60);
  if (h < 24) return h + " 小时前";
  const day = Math.floor(h / 24);
  if (day < 30) return day + " 天前";
  const mon = Math.floor(day / 30);
  if (mon < 12) return mon + " 个月前";
  return Math.floor(day / 365) + " 年前";
};

/* 表格时间单元格: 相对时间 + title 全量时间戳 */
OSE.timeCell = function (s) {
  if (!s) return "<span style='color:var(--text-3)'>-</span>";
  return `<span title="${OSE.escapeHtml(OSE.fmtTime(s))}">${OSE.relTime(s)}</span>`;
};

OSE.refreshPage = function () {
  /* 各页面注册 window.OSE.refresh 覆盖此默认行为 */
  if (window.OSE.refresh) window.OSE.refresh();
  else location.reload();
};

OSE.logout = async function () {
  try { await OSE.post("/logout", {}); } catch (e) {}
  location.href = "/login";
};

/* 右键菜单 */
OSE.ctxMenu = function (event, items) {
  const menu = document.getElementById("ctx-menu");
  menu.innerHTML = items.map((it, i) =>
    it === "-" ? "<hr>" :
    `<button data-i="${i}" class="${it.danger ? "danger" : ""}">${it.label}</button>`).join("");
  menu.style.display = "block";
  const mw = menu.offsetWidth, mh = menu.offsetHeight;
  menu.style.left = Math.min(event.clientX, innerWidth - mw - 8) + "px";
  menu.style.top = Math.min(event.clientY, innerHeight - mh - 8) + "px";
  menu.onclick = (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    menu.style.display = "none";
    items[+btn.dataset.i].action();
  };
};
document.addEventListener("mousedown", (e) => {
  if (!e.target.closest("#ctx-menu")) document.getElementById("ctx-menu").style.display = "none";
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") document.getElementById("ctx-menu").style.display = "none";
});

/* ==================== 初始化 ==================== */

OSE.state = { connected: OSE.connected, endpoint: OSE.endpoint };

/* D21 能力感知: 服务端明确不支持的操作 → 对应导航入口降级标记
   (op → 导航页映射与 core.s3_client_base.OP_NAV_MAP 一致) */
OSE.OP_NAV = {
  versioning: "versioning", lifecycle: "lifecycle", cors: "policies",
  policy: "policies", users: "users", object_lock: "versioning", multipart: "buckets",
};
OSE.applyUnsupported = function (ops) {
  document.querySelectorAll(".nav-group a.degraded").forEach((a) => {
    a.classList.remove("degraded");
    a.removeAttribute("title");
  });
  (ops || []).forEach((op) => {
    const page = OSE.OP_NAV[op];
    if (!page) return;
    const a = document.querySelector(`.nav-group a[data-nav="${page}"]`);
    if (a) {
      a.classList.add("degraded");
      a.title = "当前服务端不支持此功能, 入口已降级";
    }
  });
};

(async function init() {
  // 以服务端为准刷新连接状态
  try {
    const { data } = await OSE.get("/api/status");
    if (data.success) {
      OSE.state.connected = data.data.connected;
      OSE.state.endpoint = data.data.endpoint;
      OSE.updateBadge(data.data.connected, data.data.endpoint);
      OSE.applyUnsupported(data.data.unsupported);
    }
  } catch (e) { /* 401 已跳登录 */ }
  OSE._startTaskPolling();
})();
