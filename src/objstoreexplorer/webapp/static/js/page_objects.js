/*
Project: ObjStoreExplorer 对象存储管理工具
Copyright (C) 2026 智维ITMSKY
SPDX-License-Identifier: AGPL-3.0-or-later
开发者：智维ITMSKY  |  官网：http://www.itmsky.com
许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)
*/

/* 对象管理页: 列表/导航/选择/右键/上传/下载/剪贴板/搜索/预览/排序/快捷键
   状态保存在 location.hash, 刷新/分享链接不丢位置

   v0.1.0 视觉重构新增 (借鉴 filebrowser / MinIO Console, 详见 docs/竞品借鉴清单):
   - 文件类型线性图标 (B7) / 表头点击排序 (B3) / 在线预览 (B1)
   - Shift 范围多选 + Ctrl 加选 + Ctrl+A 全选 + Delete/F2 快捷键 (B4/B5)
   - 拖拽上传, 含文件夹递归结构与目录选择器上传 (B2, 后端 paths 字段) */

(function () {
  "use strict";
  const canWrite = OSE.isAdmin;
  const S = { bucket: "", prefix: "", items: [], selected: new Set(), searching: false, keyword: "",
              sortKey: "", sortDir: 1, anchorIdx: null };

  /* ==================== 状态 (hash) ==================== */

  function parseHash() {
    const h = new URLSearchParams((location.hash || "").replace(/^#/, ""));
    S.bucket = h.get("bucket") || "";
    S.prefix = h.get("prefix") || "";
  }
  function writeHash() {
    const p = new URLSearchParams();
    if (S.bucket) p.set("bucket", S.bucket);
    if (S.prefix) p.set("prefix", S.prefix);
    const newHash = p.toString() ? "#" + p.toString() : "";
    history.replaceState(null, "", newHash || location.pathname);
  }

  /* ==================== 类型图标 (B7) ==================== */

  function typeIcon(it) {
    if (it.is_dir) return OSE.icon("folder", "obj-ic dir");
    const m = it.name.match(/\.([a-z0-9]+)$/i);
    const ext = m ? m[1].toLowerCase() : "";
    let icon = "doc";
    if (["png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "svg"].includes(ext)) icon = "image";
    else if (["mp4", "mkv", "mov", "avi", "webm", "flv"].includes(ext)) icon = "video";
    else if (["mp3", "wav", "flac", "aac", "ogg", "m4a"].includes(ext)) icon = "audio";
    else if (["zip", "rar", "7z", "tar", "gz", "bz2", "xz"].includes(ext)) icon = "zip";
    else if (["js", "ts", "py", "java", "go", "rs", "c", "cpp", "h", "hpp", "php", "rb", "kt",
              "swift", "sh", "bat", "ps1", "html", "css", "xml", "json", "yml", "yaml", "sql"].includes(ext)) icon = "code";
    else if (["csv", "tsv", "xlsx", "xls", "db", "sqlite", "parquet"].includes(ext)) icon = "data";
    return OSE.icon(icon, "obj-ic");
  }

  /* ==================== 桶下拉 ==================== */

  async function loadBuckets() {
    const sel = document.getElementById("obj-bucket");
    try {
      const { data } = await OSE.get("/api/buckets");
      const buckets = data.success ? data.data || [] : [];
      sel.innerHTML = '<option value="">— 选择桶 —</option>' +
        buckets.map((b) => `<option value="${OSE.escapeHtml(b)}" ${b === S.bucket ? "selected" : ""}>${OSE.escapeHtml(b)}</option>`).join("");
      if (S.bucket && !buckets.includes(S.bucket)) { S.bucket = ""; writeHash(); }
    } catch (e) { sel.innerHTML = '<option value="">— 加载失败 —</option>'; }
  }

  window.ObjPage_onBucketChange = function () {
    S.bucket = document.getElementById("obj-bucket").value;
    S.prefix = "";
    S.searching = false;
    S.sortKey = "";
    writeHash();
    load();
  };

  /* ==================== 排序 (B3) ==================== */

  function sortedItems() {
    if (S.searching || !S.sortKey) return S.items;
    const dir = S.sortDir;
    return [...S.items].sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1; /* 目录恒在前, 与列表语义一致 */
      let cmp = 0;
      if (S.sortKey === "name")
        cmp = String(a.display_name || a.name).localeCompare(String(b.display_name || b.name), "zh");
      else if (S.sortKey === "size") cmp = (a.size || 0) - (b.size || 0);
      else cmp = String(a.last_modified || "").localeCompare(String(b.last_modified || ""));
      return cmp * dir;
    });
  }

  function bindSort(thead) {
    thead.querySelectorAll("th.sortable").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (S.sortKey === key) S.sortDir = -S.sortDir;
        else { S.sortKey = key; S.sortDir = 1; }
        renderTable();
      });
    });
  }

  /* ==================== 列表 ==================== */

  async function load() {
    const box = document.getElementById("obj-table");
    document.getElementById("btn-clear-search").style.display = S.searching ? "" : "none";
    renderCrumbs();
    S.selected.clear();
    S.anchorIdx = null;
    if (!S.bucket) {
      box.innerHTML = `<div class="empty-state"><div class="big">${OSE.icon("unplug")}</div>请先连接 S3 服务并选择桶</div>`;
      return;
    }
    box.innerHTML = '<div class="loading-tip">加载中…</div>';
    try {
      let data;
      if (S.searching) {
        data = (await OSE.get(`/api/search?bucket=${encodeURIComponent(S.bucket)}&kw=${encodeURIComponent(S.keyword)}&prefix=${encodeURIComponent(S.prefix)}`)).data;
      } else {
        data = (await OSE.get(`/api/objects?bucket=${encodeURIComponent(S.bucket)}&prefix=${encodeURIComponent(S.prefix)}`)).data;
      }
      if (!data.success) { box.innerHTML = `<div class="empty-state">${OSE.escapeHtml(data.message || "加载失败")}</div>`; return; }
      S.items = data.data || [];
      if (!S.items.length) {
        box.innerHTML = `<div class="empty-state"><div class="big">${OSE.icon("folder")}</div>${S.searching ? "没有匹配的对象" : "此目录为空"}</div>`;
        return;
      }
      renderTable();
    } catch (e) { box.innerHTML = ""; }
  }

  function renderTable() {
    const box = document.getElementById("obj-table");
    const sortMark = (key) =>
      S.sortKey === key ? `<span class="sort-mark">${S.sortDir === 1 ? "▲" : "▼"}</span>` : "";
    const view = sortedItems();
    /* 渲染行时用 view 的下标, 选择/操作回调按同一 view 取项 */
    S.view = view;
    box.innerHTML = `<table class="grid"><thead><tr>
      <th style="width:34px"><input type="checkbox" id="obj-sel-all"></th>
      <th class="sortable" data-sort="name">名称${sortMark("name")}</th>
      <th class="sortable" data-sort="size" style="width:110px">大小${sortMark("size")}</th>
      <th class="sortable" data-sort="time" style="width:170px">修改时间${sortMark("time")}</th>
      <th style="width:220px">操作</th>
    </tr></thead><tbody>` +
      view.map((it, idx) => {
        const disp = OSE.escapeHtml(it.display_name || it.name);
        const size = it.is_dir ? "" : OSE.fmtBytes(it.size);
        const time = it.is_dir ? "" : OSE.timeCell(it.last_modified);
        return `<tr data-idx="${idx}" id="obj-row-${idx}">
          <td><input type="checkbox" class="obj-sel" data-idx="${idx}"></td>
          <td class="obj-name" data-idx="${idx}" style="cursor:pointer">
            <span class="cell-name">${typeIcon(it)} <span class="name-txt">${disp}${it.is_dir ? "/" : ""}</span></span>
          </td>
          <td>${size}</td><td>${time}</td>
          <td>
            ${!it.is_dir ? `<button class="btn sm" onclick="ObjPage_preview(${idx})">${OSE.icon("eye")}预览</button>
            <button class="btn sm" onclick="ObjPage_downloadOne(${idx})">${OSE.icon("download")}下载</button>
            <button class="btn sm" onclick="ObjPage_share(${idx})">${OSE.icon("share")}分享</button>` : ""}
            ${canWrite ? `<button class="btn sm" onclick="ObjPage_rename(${idx})">${OSE.icon("edit")}重命名</button>` : ""}
          </td></tr>`;
      }).join("") + "</tbody></table>";

    bindSort(box.querySelector("thead"));
    document.getElementById("obj-sel-all").addEventListener("change", function () {
      document.querySelectorAll(".obj-sel").forEach((c) => { c.checked = this.checked; });
      syncSelection();
    });
    /* 多选增强 (B4): click 捕获 shift/ctrl; change 负责普通切换后的同步 */
    document.querySelectorAll(".obj-sel").forEach((c) => {
      c.addEventListener("click", onSelClick);
      c.addEventListener("change", syncSelection);
    });
    document.querySelectorAll(".obj-name").forEach((el) => {
      el.addEventListener("dblclick", () => openItem(+el.dataset.idx));
      el.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        const idx = +el.dataset.idx;
        selectOnly(idx);
        ctxFor(idx, e);
      });
    });
  }

  function openItem(idx) {
    const it = (S.view || S.items)[idx];
    if (!it) return;
    if (it.is_dir) {
      S.prefix = it.name;      // 目录 name 以 / 结尾
      S.searching = false;
      writeHash();
      load();
    } else {
      downloadOne((S.view || S.items)[idx]);
    }
  }

  /* ==================== 面包屑 ==================== */

  function renderCrumbs() {
    const el = document.getElementById("obj-crumbs");
    if (!S.bucket) { el.innerHTML = ""; return; }
    /* v0.1.0 XSS 加固: 目录名来自 S3 key (可含引号/尖括号), 不能再拼进
       内联 onclick 的 JS 字符串 (escapeHtml 的 &#39; 在属性里会被解码回
       单引号导致逃逸)。改为 data-prefix 属性 + 事件委托。 */
    let html = `<a href="javascript:void(0)" class="crumb-root" data-prefix="">${OSE.icon("bucket", "xs")} ${OSE.escapeHtml(S.bucket)}</a>`;
    if (S.searching) html += `<span class="sep">›</span><span>搜索: ${OSE.escapeHtml(S.keyword)}</span>`;
    else {
      const parts = S.prefix ? S.prefix.replace(/\/$/, "").split("/") : [];
      let acc = "";
      parts.forEach((p) => {
        acc += p + "/";
        html += `<span class="sep">›</span><a href="javascript:void(0)" class="crumb-link" data-prefix="${OSE.escapeHtml(acc)}">${OSE.escapeHtml(p)}</a>`;
      });
    }
    el.innerHTML = html;
  }

  /* 面包屑事件委托 (替代内联 onclick) */
  document.getElementById("obj-crumbs").addEventListener("click", (e) => {
    const a = e.target.closest("a[data-prefix]");
    if (a) ObjPage_nav(a.dataset.prefix || "");
  });

  window.ObjPage_nav = function (prefix) {
    S.prefix = prefix;
    S.searching = false;
    writeHash();
    load();
  };

  /* ==================== 选择 (B4: Shift 范围 / Ctrl 加选) ==================== */

  function syncSelection() {
    S.selected.clear();
    document.querySelectorAll(".obj-sel").forEach((c) => {
      if (c.checked) S.selected.add(+c.dataset.idx);
      c.closest("tr").classList.toggle("selected", c.checked);
    });
  }
  function onSelClick(e) {
    const idx = +e.target.dataset.idx;
    if (e.shiftKey && S.anchorIdx != null) {
      /* 阻止默认: shift+click 不会触发 change, 由这里手动置勾 */
      e.preventDefault();
      const lo = Math.min(S.anchorIdx, idx), hi = Math.max(S.anchorIdx, idx);
      document.querySelectorAll(".obj-sel").forEach((c) => {
        const i = +c.dataset.idx;
        if (i >= lo && i <= hi) c.checked = true;
      });
      syncSelection();
    } else {
      /* 普通点击/Ctrl 点击: checkbox 原生切换, change 事件已同步 */
      S.anchorIdx = idx;
    }
  }
  function selectOnly(idx) {
    document.querySelectorAll(".obj-sel").forEach((c) => { c.checked = +c.dataset.idx === idx; });
    syncSelection();
  }
  function selectAll() {
    document.querySelectorAll(".obj-sel").forEach((c) => { c.checked = true; });
    syncSelection();
  }
  function selectedItems() { return [...S.selected].map((i) => (S.view || S.items)[i]).filter(Boolean); }

  /* 键盘快捷键 (B5): Ctrl+A 全选 / Delete 删除选中 / F2 重命名首个选中。
     焦点在输入框/下拉时不拦截; 写操作仅 admin 生效。 */
  document.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName || "").toLowerCase();
    if (["input", "textarea", "select"].includes(tag)) return;
    if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A")) {
      if (!S.bucket) return;
      e.preventDefault();
      selectAll();
    } else if (e.key === "Delete" && canWrite) {
      ObjPage_deleteSelected();
    } else if (e.key === "F2" && canWrite) {
      const items = selectedItems();
      if (items.length === 1) rename(items[0]);
    }
  });

  /* ==================== 右键菜单 ==================== */

  function ctxFor(idx, event) {
    const it = (S.view || S.items)[idx];
    const items = [
      { label: it.is_dir ? `${OSE.icon("folder")} 打开` : `${OSE.icon("download")} 下载`, action: () => openItem(idx) },
      { label: `${OSE.icon("info")} 属性`, action: () => showStat(idx) },
    ];
    if (!it.is_dir) {
      items.push({ label: `${OSE.icon("eye")} 预览`, action: () => preview(it) });
      items.push({ label: `${OSE.icon("share")} 分享`, action: () => share(it) });
    }
    items.push("-");
    if (canWrite) {
      items.push(
        { label: `${OSE.icon("edit")} 重命名`, action: () => rename(it) },
        { label: `${OSE.icon("copy")} 复制`, action: () => clip("copy", [it]) },
        { label: `${OSE.icon("cut")} 剪切`, action: () => clip("cut", [it]) },
        { label: `${OSE.icon("trash")} 删除`, danger: true, action: () => del([it]) },
      );
    }
    if (S.clipboardCount > 0 && canWrite) {
      items.push("-", { label: `${OSE.icon("paste")} 粘贴到这里`, action: () => paste() });
    }
    OSE.ctxMenu(event, items);
  }

  /* ==================== 上传 (B2: 拖拽 + 文件夹结构) ==================== */

  window.ObjPage_pickUpload = function () {
    if (!requireBucket()) return;
    document.getElementById("obj-file-input").click();
  };

  /* 目录选择器 (webkitdirectory): 相对路径含根目录名, 与 MinIO Console 行为一致 */
  window.ObjPage_pickFolder = function () {
    if (!requireBucket()) return;
    document.getElementById("obj-folder-input").click();
  };

  /* 把 dataTransfer 里的拖拽项收集为 [{file, rel}] (rel 为相对路径, 文件为空串)。
     注意: DataTransfer.items 在事件循环后失效, 必须先同步收集 entry 再异步遍历。 */
  async function collectDropItems(dataTransfer) {
    const out = [];
    const entries = [];
    for (const item of dataTransfer.items) {
      const e = item.webkitGetAsEntry && item.webkitGetAsEntry();
      if (e) entries.push(e);
      else {
        const f = item.getAsFile && item.getAsFile();
        if (f) out.push({ file: f, rel: "" });
      }
    }
    async function walk(entry, prefix) {
      if (entry.isFile) {
        const f = await new Promise((res, rej) => entry.file(res, rej));
        out.push({ file: f, rel: prefix + entry.name });
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        /* readEntries 每次最多返回 100 条, 循环读到空为止 */
        for (;;) {
          const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
          if (!batch.length) break;
          for (const sub of batch) await walk(sub, prefix + entry.name + "/");
        }
      }
    }
    for (const e of entries) await walk(e, "");
    return out;
  }

  function buildUploadForm(items) {
    const fd = new FormData();
    fd.append("bucket", S.bucket);
    fd.append("prefix", S.prefix);
    // 同名冲突策略 (v0.5.0): 覆盖(默认, 与旧行为一致) / 跳过 / 重命名
    const conflictSel = document.getElementById("obj-conflict-select");
    fd.append("conflict", conflictSel ? conflictSel.value : "overwrite");
    const rels = [];
    let structured = false;
    for (const it of items) {
      const f = it.file || it;
      const rel = it.rel || "";
      if (rel) structured = true;
      rels.push(rel);
      fd.append("files", f, f.name);
    }
    if (structured) rels.forEach((p) => fd.append("paths", p));
    return fd;
  }

  async function upload(items) {
    if (!items || !items.length) return;
    const fd = buildUploadForm(items);
    try {
      const { data } = await OSE.post("/api/objects/upload", fd);
      OSE.toast(data.message, "success");
      OSE.showTasks();
    } catch (e) {}
    document.getElementById("obj-file-input").value = "";
    const folderInput = document.getElementById("obj-folder-input");
    if (folderInput) folderInput.value = "";
  }
  window.ObjPage_uploadFiles = upload;

  /* 拖拽区: 挂在表格卡片上, 仅 admin 提示/接收 (viewer 不出现覆盖层) */
  (function initDropzone() {
    const dz = document.getElementById("obj-dropzone");
    if (!dz || !canWrite) return;
    let depth = 0;
    dz.addEventListener("dragenter", (e) => {
      e.preventDefault();
      depth += 1;
      dz.classList.add("drag-over");
    });
    dz.addEventListener("dragover", (e) => e.preventDefault());
    dz.addEventListener("dragleave", () => {
      depth = Math.max(0, depth - 1);
      if (!depth) dz.classList.remove("drag-over");
    });
    dz.addEventListener("drop", async (e) => {
      e.preventDefault();
      depth = 0;
      dz.classList.remove("drag-over");
      if (!requireBucket()) return;
      try {
        const items = await collectDropItems(e.dataTransfer);
        if (items.length) upload(items);
      } catch (err) {
        OSE.toast("读取拖拽内容失败: " + (err.message || err), "error");
      }
    });
  })();

  /* 文件选择 input */
  document.getElementById("obj-file-input").addEventListener("change", function () {
    upload([...this.files]);
  });
  const folderInput = document.getElementById("obj-folder-input");
  if (folderInput) folderInput.addEventListener("change", function () {
    const items = [...this.files].map((f) => ({
      file: f,
      rel: f.webkitRelativePath || f.name,
    }));
    upload(items);
  });

  /* ==================== 下载 ==================== */

  window.ObjPage_downloadOne = function (idx) { const it = (S.view || S.items)[idx]; if (it) downloadOne(it); };

  function downloadOne(it) {
    if (!it) return;
    if (it.is_dir) { zipDownload([it.name]); return; }
    window.open(`/api/objects/download?bucket=${encodeURIComponent(S.bucket)}&key=${encodeURIComponent(it.name)}`, "_blank");
  }

  function zipDownload(keys) {
    OSE.post("/api/objects/download-zip", { bucket: S.bucket, keys }).then(({ data }) => {
      OSE.toast(data.message, "success");
      OSE.showTasks();
    }).catch(() => {});
  }

  window.ObjPage_downloadSelected = function () {
    const items = selectedItems();
    if (!requireBucket() || !items.length) { OSE.toast("请先勾选要下载的对象", "warn"); return; }
    const keys = items.map((i) => i.name);
    if (keys.length === 1 && !items[0].is_dir)
      window.open(`/api/objects/download?bucket=${encodeURIComponent(S.bucket)}&key=${encodeURIComponent(keys[0])}`, "_blank");
    else zipDownload(keys);
  };

  /* ==================== 在线预览 (B1) ==================== */

  window.ObjPage_preview = function (idx) { preview((S.view || S.items)[idx]); };

  function preview(it) {
    if (!it) return;
    if (it.is_dir) { OSE.toast("文件夹不支持预览, 请进入目录查看", "warn"); return; }
    document.getElementById("preview-title").textContent = "预览 · " + (it.display_name || it.name);
    const body = document.getElementById("preview-body");
    body.innerHTML = '<div class="loading-tip">加载中…</div>';
    OSE.openModal("preview-modal");
    const url = `/api/objects/preview?bucket=${encodeURIComponent(S.bucket)}&key=${encodeURIComponent(it.name)}`;
    fetch(url, { credentials: "same-origin" }).then(async (resp) => {
      if (resp.status === 401) { location.href = "/login?expired=1"; return; }
      if (!resp.ok) {
        let msg = "预览失败";
        try { const j = await resp.json(); msg = j.message || msg; } catch (e) { /* 非 JSON */ }
        body.innerHTML = `<div class="empty-state">${OSE.escapeHtml(msg)}</div>`;
        return;
      }
      const ct = resp.headers.get("content-type") || "";
      if (ct.startsWith("image/")) {
        body.innerHTML = `<img class="preview-img" src="${url}" alt="预览">`;
      } else {
        const text = await resp.text();
        const truncated = resp.headers.get("X-Preview-Truncated") === "1";
        body.innerHTML =
          `<div class="preview-text">${OSE.escapeHtml(text)}</div>` +
          (truncated ? '<div class="hint" style="margin-top:8px;text-align:center">内容超过 2MB 预览上限, 仅显示前段; 完整内容请下载查看</div>' : "");
      }
    }).catch((e) => {
      body.innerHTML = `<div class="empty-state">网络错误: ${OSE.escapeHtml(e.message || "")}</div>`;
    });
  }

  /* ==================== 分享 (预签名 URL) ==================== */

  window.ObjPage_share = function (idx) { share((S.view || S.items)[idx]); };

  function share(it) {
    if (!it) return;
    if (it.is_dir) { OSE.toast("文件夹不支持分享, 请选择具体文件", "warn"); return; }
    if (!requireBucket()) return;
    /* 每次打开重置为表单态 */
    document.getElementById("share-key").value = it.name;
    document.getElementById("share-expire-field").style.display = "";
    document.getElementById("share-result-wrap").style.display = "none";
    document.getElementById("share-copy").style.display = "none";
    document.getElementById("share-error").textContent = "";
    document.getElementById("share-submit").style.display = "";
    OSE.openModal("share-modal");
  }

  async function doShare() {
    const err = document.getElementById("share-error");
    err.textContent = "";
    const btn = document.getElementById("share-submit");
    btn.disabled = true; btn.textContent = "生成中…";
    try {
      const { data } = await OSE.post("/api/objects/share", {
        bucket: S.bucket,
        key: document.getElementById("share-key").value,
        expires: parseInt(document.getElementById("share-expires").value, 10),
      });
      if (!data.success) { err.textContent = data.message || "生成失败"; return; }
      document.getElementById("share-url").value = data.data.url;
      document.getElementById("share-result-hint").textContent =
        `有效期 ${data.data.expires_label}, 到期自动失效; 签发后无法单独吊销, 泄露请轮换 Access Key`;
      document.getElementById("share-expire-field").style.display = "none";
      document.getElementById("share-result-wrap").style.display = "";
      document.getElementById("share-copy").style.display = "";
      document.getElementById("share-submit").style.display = "none";
    } catch (e) {
      err.textContent = e.message || "生成失败, 请稍后重试";
    } finally {
      btn.disabled = false; btn.textContent = "生成链接";
    }
  }

  async function copyShareUrl() {
    const input = document.getElementById("share-url");
    if (!input.value) return;
    try {
      await navigator.clipboard.writeText(input.value);
      OSE.toast("分享链接已复制", "success");
    } catch (e) {
      /* 非 HTTPS 环境没有 navigator.clipboard, 回落选中 + execCommand */
      input.focus(); input.select();
      if (document.execCommand && document.execCommand("copy")) OSE.toast("分享链接已复制", "success");
      else OSE.toast("自动复制失败, 请手动选中链接复制", "warn");
    }
  }

  /* ==================== 删除 / 重命名 / 新建文件夹 ==================== */

  window.ObjPage_deleteSelected = function () {
    const items = selectedItems();
    if (items.length) del(items);
    else OSE.toast("请先勾选要删除的对象", "warn");
  };

  async function del(items) {
    if (!items.length) return;
    const names = items.map((i) => i.display_name).join(", ");
    if (!(await OSE.confirm("删除确认", `确定删除 ${items.length} 项?\n${names}\n\n(文件夹将递归删除其下全部对象)`))) return;
    // 文件夹: 其子对象随文件夹 key 前缀删除, 直接把文件夹 key 一并提交
    const { data } = await OSE.post("/api/objects/delete", { bucket: S.bucket, keys: items.map((i) => i.name) });
    OSE.toast(data.message, "success");
    OSE.showTasks();
    watchTaskThenReload(data.data && data.data.task_id);
  }

  function watchTaskThenReload(taskId) {
    if (!taskId) { setTimeout(load, 800); return; }
    const timer = setInterval(async () => {
      try {
        const { data } = await OSE.get(`/api/tasks/${taskId}`);
        if (data.data && data.data.status !== "running") { clearInterval(timer); load(); }
      } catch (e) { clearInterval(timer); load(); }
    }, 1200);
  }

  window.ObjPage_rename = function (idx) { rename((S.view || S.items)[idx]); };

  async function rename(it) {
    if (!it) { OSE.toast("请先勾选对象", "warn"); return; }
    const isDir = it.is_dir;
    const base = it.display_name || it.name;
    const r = await OSE.prompt("重命名", "新名称", {
      value: base,
      hint: isDir ? "将重命名文件夹及其下全部对象 (复制+删除)" : "保留原扩展名以正确识别文件类型",
    });
    if (!r || !r.v1 || r.v1 === base) return;
    /* v0.1.0 修复: 父路径不再用 oldKey.length - display_name.length 反推 ——
       display_name 经过后端 URL unquote, key 含 %XX 时长度不对应会算错父目录。
       重命名总发生在当前目录, 父路径就是 S.prefix。 */
    const oldKey = it.name;
    const parent = S.prefix || "";
    const newKey = parent + r.v1 + (isDir ? "/" : "");
    const { data } = await OSE.post("/api/objects/rename", { bucket: S.bucket, old_key: oldKey, new_key: newKey });
    OSE.toast(data.message, data.success ? "success" : "error");
    if (data.success) load();
  }

  window.ObjPage_newFolder = async function () {
    if (!requireBucket()) return;
    const r = await OSE.prompt("新建文件夹", "文件夹名称", { hint: "不能包含 / \\ 等路径分隔符" });
    if (!r || !r.v1) return;
    const { data } = await OSE.post("/api/objects/folder", { bucket: S.bucket, parent: S.prefix, name: r.v1 });
    OSE.toast(data.message, data.success ? "success" : "error");
    if (data.success) load();
  };

  /* ==================== 剪贴板 ==================== */

  S.clipboardCount = 0;
  S.clipboardOp = "none";

  window.ObjPage_clip = function (op, items) {
    items = items || selectedItems();
    if (!requireBucket() || !items.length) { OSE.toast("请先勾选对象", "warn"); return; }
    OSE.post("/api/clipboard", {
      op,
      items: items.map((i) => ({ bucket: S.bucket, key: i.name, name: i.display_name, is_dir: i.is_dir })),
    }).then(({ data }) => {
      OSE.toast(data.message, "success");
      refreshClipBadge();
    }).catch(() => {});
  };

  window.ObjPage_clipPaste = function () { paste(); };

  async function paste() {
    const { data } = await OSE.post("/api/clipboard/paste", { bucket: S.bucket, prefix: S.prefix });
    OSE.toast(data.message, data.success ? "success" : "warn");
    refreshClipBadge();
    load();
  }

  async function refreshClipBadge() {
    try {
      const { data } = await OSE.get("/api/clipboard");
      const cb = data.data || {};
      S.clipboardCount = cb.count || 0;
      S.clipboardOp = cb.operation || "none";
      const el = document.getElementById("clip-count");
      if (S.clipboardCount) {
        el.style.display = "";
        el.textContent = (S.clipboardOp === "cut" ? "剪切 " : "复制 ") + S.clipboardCount;
      } else el.style.display = "none";
    } catch (e) { /* 未登录等 */ }
  }

  /* ==================== 搜索 ==================== */

  document.getElementById("obj-search").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const kw = e.target.value.trim();
    if (!S.bucket) { OSE.toast("请先选择桶", "warn"); return; }
    if (!kw) { clearSearch(); return; }
    S.searching = true;
    S.keyword = kw;
    load();
  });

  window.ObjPage_clearSearch = function () { clearSearch(); };
  function clearSearch() {
    S.searching = false;
    S.keyword = "";
    document.getElementById("obj-search").value = "";
    load();
  }

  /* ==================== 属性 ==================== */

  async function showStat(idx) {
    const it = (S.view || S.items)[idx];
    if (!it || it.is_dir) { OSE.toast("文件夹无属性详情", "info"); return; }
    try {
      const { data } = await OSE.get(`/api/objects/stat?bucket=${encodeURIComponent(S.bucket)}&key=${encodeURIComponent(it.name)}`);
      if (!data.success) { OSE.toast(data.message || "获取失败", "error"); return; }
      const info = data.data || {};
      const rows = [
        ["Key", it.name], ["大小", OSE.fmtBytes(info.size ?? it.size)],
        ["ETag", info.etag || "-"], ["Content-Type", info.content_type || "-"],
        ["修改时间", OSE.fmtTime(info.last_modified || it.last_modified)],
      ];
      document.getElementById("stat-body").innerHTML = rows.map(([k, v]) =>
        `<dt>${k}</dt><dd>${OSE.escapeHtml(v == null ? "-" : String(v))}</dd>`).join("");
      OSE.openModal("stat-modal");
    } catch (e) {}
  }
  window.ObjPage_showStat = showStat;

  /* ==================== 工具 ==================== */

  function requireBucket() {
    if (!S.bucket) { OSE.toast("请先选择桶", "warn"); return false; }
    return true;
  }

  /* ==================== 对外 & 启动 ==================== */

  window.OSE.refresh = load;
  OSE.onConnectionChanged = async function () {
    await loadBuckets();
    load();
  };

  window.addEventListener("hashchange", () => { parseHash(); loadBuckets().then(load); });

  /* 模板 onclick 使用的命名空间 */
  window.Objects = {
    onBucketChange: ObjPage_onBucketChange,
    pickUpload: ObjPage_pickUpload,
    pickFolder: ObjPage_pickFolder,
    newFolder: ObjPage_newFolder,
    clip: ObjPage_clip,
    clipPaste: ObjPage_clipPaste,
    downloadSelected: ObjPage_downloadSelected,
    deleteSelected: ObjPage_deleteSelected,
    clearSearch: ObjPage_clearSearch,
    doShare: doShare,
    copyShareUrl: copyShareUrl,
  };

  (async function init() {
    parseHash();
    await loadBuckets();
    await refreshClipBadge();
    if (OSE.state && OSE.state.connected) load();
    else {
      document.getElementById("obj-table").innerHTML =
        `<div class="empty-state"><div class="big">${OSE.icon("unplug")}</div>请先点击右上角「连接」建立 S3 连接</div>`;
    }
  })();
})();
