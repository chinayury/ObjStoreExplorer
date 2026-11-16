# Changelog — ObjStoreExplorer 本地桌面版

本文件记录**本地桌面版**的变更，格式参照
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [v0.4.1 · 每周维护第四轮] — 2026-11-16 · 下载先校验再替换

> 每周维护循环第四轮。开放 Issues 巡检：0 条待处置；与第三轮间隔不足一天，调研增量复核
> 跳过（无信息增量，如实记录，详见 [docs/06](docs/06-同类项目调研与借鉴.md) §四）。

### 🐛 Fixed

- **下载不再产生半截文件**（Pail 借鉴 #4 后半「下载先校验再替换」）：新增 core 层共用
  `download_verified()`——先下到 `.part` 暂存，再经 `stat_object` 校验文件大小，
  通过后 `os.replace` 原子替换到位。桌面 `TransferService` 两条下载路径与 Web 打包下载
  共用同一实现（不复制粘贴）。此前下载失败 / 中断会在目标位置留下半截文件。

### 🔄 Changed

- 下载失败消息区分「下载失败」与「校验失败」；校验失败时**保留旧目标文件**并明确提示字节数差异。
- stat 不可用时退化为「暂存 + 原子替换」，不因校验不可用而拒绝下载（可用性优先，如实降级）。
- 冒烟测试 +4（成功替换 / 校验失败保留旧文件 / 下载失败清理暂存 / 无 stat 降级），共 26 项全绿。

---

## [v0.4.0 · 每周维护第三轮] — 2026-11-15 · 同步传输暂停 / 恢复

> 每周维护循环第三轮。开放 Issues 巡检：0 条待处置；调研对 6 个深读对象 + 观察名单做增量复核
> （仅 star 微涨，无新增可借鉴要点，详见 [docs/06](docs/06-同类项目调研与借鉴.md) §四）。

### 🆕 Added

- **同步进度窗口「暂停 / 恢复」**（Pail 借鉴 #1 第二批）：同步执行期间可在进度窗口随时
  暂停 / 恢复 / 取消——暂停在文件与分片边界生效（已建连接不拆，大文件停在当前分片边界），
  恢复后继续；与取消可随时切换，取消优先。
  - `TransferService.pause_all() / resume_all()`：与 `cancel_all` 同粒度（只作用于未完成任务）。
  - 桌面端冒烟测试 +1（`pause_all` 排除已完成任务、取消优先于暂停），共 22 项全绿。

### 🔄 Changed

- `docs/03` §5.2 补充同步暂停/恢复说明；`docs/06` 要点 #1 状态更新为「前两批已落地」。

---

## [v0.3.0 · 每周维护第二轮] — 2026-11-14 · 传输任务暂停 / 恢复 / 限速

> 同日第二轮维护循环（调研 → Issues 巡检 → 优化 → 发布 → 清理验证）。开放 Issues 巡检：0 条待处置；
> 同日调研与 [docs/06](docs/06-同类项目调研与借鉴.md) 去重基线内无新增借鉴点。
> 本轮落地「Pail 借鉴 #1 传输队列」第一批：桌面核心层 + Web 全链路。

### 🆕 Added

- **传输任务暂停 / 恢复 / 全局限速**（借鉴 Pail）：
  - 桌面核心层：`TransferTask.pause() / resume()`——分片上传在**分片边界**暂停等待（已建连接
    不拆；取消优先于暂停，暂停中取消立即中断并回收分片）；`TransferService.set_rate_limit()`
    全局限速（平滑漏桶按累计字节补眠，取消可即时打断，改动即时生效）。
  - Web 端：`WebTaskManager.pause / resume` + `POST /api/tasks/{id}/pause | resume`
    （归属校验与取消一致），任务面板对进行中任务新增「暂停 / 恢复」按钮与「已暂停」标记。
  - 冒烟测试 +5（reader 暂停/取消、限速 pacer、服务 API、WebTask 集成、路由鉴权与降级），
    共 21 项全绿。

### 🔄 Changed

- `docs/06`：要点 #1 更新为「第一批已落地」；要点 #2（对象列表按需分页）复核后暂缓——
  minio-py 公开 API 未暴露 continuation token / max_keys，真分页需下探 S3 原始调用并配
  真实 MinIO 集成测试，自动维护轮不盲改。
- `docs/03`：补充任务面板暂停/恢复用法与多 worker 已知限制。
- 已知限制（如实）：暂停状态保存在执行节点内存，多 worker 跨节点暂停如实返回「不支持」
  （**取消**已落库跨节点生效）；限速只约束自管分片上传路径；桌面 UI 暂停/恢复按钮待下一批。

---

## [v0.2.0 · 每周维护第一轮] — 2026-11-14 · 版本单一来源收敛 · 容器加固 · 检查更新

> 本轮为每周自动维护循环首轮（调研借鉴 → Issues 巡检 → 优化 → 发布 → 清理验证）。
> GitHub 开放 Issues 巡检：0 条待处置。同类项目调研与借鉴清单见 [docs/06-同类项目调研与借鉴.md](docs/06-同类项目调研与借鉴.md)。

### 🆕 Added

- **检查更新（只查询，不自更新）**：桌面版「关于」页与 Web 端 `/about` 新增「检查更新」入口，
  匿名查询 GitHub Releases 最新版本并与当前版本比对；新增 `utils/update_checker.py`
  （统一结果、永不抛异常）与 `GET /api/update-check`（登录用户可用，服务端代理查询），
  网络失败优雅降级、不误报「已是最新」。借鉴 Pail 的保守升级口径：不做静默自动下载替换
  （产物未签名，避免供应链风险），只提示新版本号、下载页与 `SHA256SUMS.txt` 校验指引。
- **[docs/06-同类项目调研与借鉴.md](docs/06-同类项目调研与借鉴.md)**：每轮维护的同类项目
  候选总表（本轮 30+ 候选、深读 6 个）、借鉴要点与落地状态（8 条）、未采纳及理由（11 条）。

### 🔄 Changed

- **版本号单一来源彻底收敛**：`webapp/__init__.py` 不再保存字面量，改为从
  `config.settings.APP_VERSION` 转发（与包级 `__init__` 同模式）；`docker-compose.yml`
  镜像标签参数化为 `${OSE_IMAGE_TAG:-latest}`，发版不再需要改 compose；
  冒烟测试同步改为「不得硬编码」断言防回归。
- **容器安全加固**（借鉴 filestash / SFTPGo 镜像实践）：镜像以专用系统用户
  `ose`（uid 10001）运行；compose 开启只读根文件系统（`read_only: true`）、
  `cap_drop: [ALL]` 最小能力集与 `no-new-privileges`；运行期可写位置收敛为
  `data` 卷与 tmpfs `/tmp`；`deploy.sh` 自动修正 data 卷属主
  （从旧版 root 容器迁移须先 `chown -R 10001:10001 data`，见 docs/02 §2.3）。
- 文档版本口径同步：`docs/` 头部改为「依据当前源码编写」，产物名改用 `<version>` 占位，
  避免每轮发版翻改历史文档；`docs/README.md` 文档索引新增 06 条目。

### 🐛 Fixed

- `build.py` 版本读取失败提示中的硬编码示例版本号泛化为 `x.y.z`（消除下一版发版时的误导）。

---

## [许可与署名更正] — 2026-11-13 · 署名统一为「智维ITMSKY」

> 版本号保持 v0.1.0 不变；只更正署名与许可声明，不改业务逻辑。

### 🔄 Changed

- **署名**：源码头版权声明由「智维工作室 All Rights Reserved.」统一为
  `Copyright (C) 2026 智维ITMSKY`，并补充 SPDX、开发者、官网、许可证四行；
  覆盖 `src/` 下 Python / Jinja 模板 / JS / CSS、根目录 `main.py`、`build.py`、`build.spec` 及 `tests/`。
- **SPDX**：所有受版本控制的源码文件头新增 `SPDX-License-Identifier: AGPL-3.0-or-later`，
  便于许可证扫描工具识别。
- **许可声明**：删除与 AGPL-3.0 冲突的「禁止未经许可分发、转售、开源」表述，
  明确本项目以 AGPL-3.0-or-later 发布；README 与两处关于页补充 AGPL 四段中文声明
  （自由软件、无担保、网络服务源码义务、许可证副本获取方式）。
- **README / LICENSE.md / NOTICE**：许可章节改为「许可与信息」，列出开发者、版权、官网、许可证与 SPDX；
  新增 `NOTICE` 承载项目版权与 SPDX 声明；`LICENSE.md` 恢复为纯 AGPL 原文，确保 GitHub 正确识别许可证类型。
- **pyproject.toml**：`authors.name` 改为「智维ITMSKY」，`[project.urls]` 增加 Homepage。
- **关于页面**：桌面版「关于」页与 Web 版 `/about` 增加开发者、官网、版权、许可证、SPDX 与声明文本；
  `__author__` 同步为「智维ITMSKY <41469858@qq.com>」。

### 🐛 Fixed

- **PowerShell 5.1 批量替换中文乱码**：无 BOM 的 `.ps1` 被按 ANSI 解析，
  中文模式串变成乱码导致语法错误；给脚本补 UTF-8 BOM 后执行成功。

---

## [发布工程化] — 2026-11-13 · 开源发布 / CI / 冒烟测试 / 健康检查

> 版本号保持 v0.1.0 不变；本次只补发布基础设施与许可证，不改业务功能。
> 目标：代码可公开托管、按 tag 一键产出四类产物、部署可健康检查。

### 🆕 Added（发布与测试）

- **`.github/workflows/ci.yml`**：Ubuntu / Windows / macOS × Python 3.13，
  安装依赖 → 11 项冒烟测试 → wheel + sdist → Docker 构建与 `/api/health` 探活。
- **`.github/workflows/release.yml`**：推送 `v*` tag 触发，校验 tag 与 `APP_VERSION`
  一致 → 测试 → wheel/sdist + Windows onedir zip + GHCR 镜像 → GitHub Release，
  并清理旧 Release 附件、旧 GHCR 镜像版本、历史 Actions artifacts。
- **`tests/`**：`conftest.py` + `test_smoke.py` 共 11 项（版本一致性、健康检查、
  未登录跳转、登录成功/失败、API 401、安全响应头、静态资源、OpenAPI、Fernet 往返）；
  `requirements-dev.txt` 与 `pytest.ini` 配套。
- **`GET /api/health`**：只读健康检查端点（name / status / version / core_version），
  Dockerfile 增加 `HEALTHCHECK` 调用该端点。
- **`.gitignore`**：排除 `data/`、构建产物、缓存、`.env`、日志；保留 `build.spec`。

### 🔄 Changed

- **许可证**：`LICENSE.md` 由专有 SCLA 改为 **AGPL-3.0-or-later**；
  `pyproject.toml` 的 license 与 classifier、README 许可章节同步更新。
- **README**：移除具体版本号，产物名统一为 `ObjStoreExplorer-<version>-win-x64.zip`；
  目录结构补充 `tests/`、`requirements-dev.txt`、`.github/workflows/`。

### 🐛 Fixed

- **`python -m build` 被根目录 `build.py` 遮蔽**：CI 改为在临时目录执行
  `python -m build <项目根> --outdir <项目根>/dist`，避免把打包脚本当模块运行。
- `build.py` 文档中的版本占位符补全为 `ObjStoreExplorer-v<version>-win-x64.zip`。

### ✅ Verified

- 本地 Python 3.13.14 实跑 `pytest`：11 passed。
- 本地构建 wheel/sdist 成功（`objstoreexplorer-0.1.0-py3-none-any.whl` /
  `objstoreexplorer-0.1.0.tar.gz`），wheel 元数据 `License: AGPL-3.0-or-later`。

---

## [源码布局重组] — 2026-11-13 · 扁平布局 → 标准 src 布局

> 将项目整理为「纯代码 + 文档」的初始版本：源码由根目录扁平布局重构为标准
> `src/objstoreexplorer/` 包布局，包目录名与发行名一致；内部绝对导入统一转为包内相对导入；
> 新建 `pyproject.toml` 使包可安装、入口点自洽；清理 Git / CI / 开发工具类冗余与敏感文件；
> 重写 `docs/` 为 5 篇编号文档。版本号保持 v0.1.0 不变，功能无增减。

### 🔧 Changed（结构调整）

- **源码布局**：`config/` `core/` `services/` `ui/` `utils/` `webapp/` `resources/`
  `main.py` `__init__.py` `__main__.py` 全部移入 `src/objstoreexplorer/`，包目录名 = 发行名
  `objstoreexplorer`；根 `main.py` 改为启动引导壳（PyInstaller 入口 + 源码直跑，自动把 `src/`
  加入搜索路径）。
- **导入转换**：295 处内部绝对导入（`from config.x` / `from core.x` 等）统一转为**包内相对导入**，
  按文件所在目录深度计算相对前缀，包内可解析；无残留绝对导入。
- **路径敏感修复**：
  - `config/settings.py:_get_executable_dir()` 改为向上回溯含 `pyproject.toml` 的项目根
    （原 `parent.parent` 在 src 布局下会把 `data/` 建进包目录）；
  - `utils/icons.py:_icon_dir()` 增加 `_MEIPASS` 候选（打包后图标落位 `_MEIPASS/resources/icons`）；
  - `utils/feedback_client.py:_resolve_config_path()` 将用户可编辑 `feedback.yaml` 定位改为
    `data/config/feedback.yaml`（数据目录内，不污染源码树）；
  - `__main__.py` 的 `from main import main` 改为 `from .main import main`。

### 🆕 Added（构建与部署配置）

- **`pyproject.toml`**：新建构建配置——包名 `objstoreexplorer`、`package-dir = { "" = "src" }`、
  控制台入口 `objstoreexplorer = "objstoreexplorer.__main__:main"`、包数据含图标与模板、
  动态版本取自 `objstoreexplorer.__version__`（单一真源 `config/settings.py:APP_VERSION`）。
- **依赖管理**：依赖仍由 `requirements.txt` / `requirements-web.txt` 管理（含 CVE 上界注释），
  `pyproject.toml` 不重复声明，避免漂移。

### 🔄 Updated（部署配置）

- `build.py` / `build.spec`：资源与反馈模板路径改为 `src/objstoreexplorer/...`，`pathex` 指向 `src/`。
- `Dockerfile`：改为 `COPY src ./src` + `pip install --no-deps .`，CMD 入口改为
  `objstoreexplorer.webapp.main:app`，设 `OSE_DATA_DIR=/app/data`。
- `.dockerignore`：桌面 GUI 排除路径改为 `src/objstoreexplorer/ui/`。

### 🗑️ Removed（清理）

- 移除 Git / CI / 开发工具类冗余：`.gitignore`、`.gitlab-ci.yml`、`ci/`、`scripts/`、`docs-archive/`。
- 移除敏感的真实 `config/feedback.yaml`（含反馈平台 app_key 凭据，安全红线绝不保留），
  仅保留 `config/feedback.yaml.example` 模板。

### 📚 Documentation

- 重写 `docs/` 为 5 篇编号文档：`01-项目介绍与架构`、`02-环境部署教程`、`03-功能使用说明`、
  `04-安全设计说明`、`05-开发日志`，并新建 `docs/README.md` 索引；所有路径、命令、模块名
  与磁盘一致。
- 重写根 `README.md`（src 布局、`python -m objstoreexplorer` 入口、文档索引）。

### ✅ 验证

- `import objstoreexplorer` 成功，`__version__` = 0.1.0（动态版本正确读取）。
- `from objstoreexplorer.main import main` 可导入；`from objstoreexplorer.webapp.main import app`
  可导入并成功创建 FastAPI 应用（14 条路由，实跑初始化账号库与加密库）。
- `python -m objstoreexplorer` 成功启动桌面版 GUI，无 stderr 报错。
- 图标路径解析正确（189 个图标 + logo.ico 就位）；无残留缓存 / 构建产物。

## [v0.1.0 第五轮迭代] — 2026-11-12 · 竞品借鉴第三轮 · 视觉体系换代「暮橙 Emberline」

> 本轮依据《docs/竞品借鉴清单-V3.0-20261112.md》（GitHub 63 仓库实测 + Gitee 19 候选、
> 12 个入围深析）落地 13 条借鉴; 视觉体系由「曜蓝 Azureline」换代为「暮橙 Emberline」
> （陶土暖橙 + 奶油暖白 + 大圆角），桌面 + Web 双形态归一; 版本号保持 v0.1.0 不升号。
> 全量测试 **344 passed / 1 skipped / 0 failed**；依赖扫描 **No known vulnerabilities found**；
> 全仓 pyflakes 生产代码 **0 告警**。

### 🆕 Added（竞品借鉴 · 13 项落地）

- **S3 错误码人话映射**（借鉴 bucketdock / Evil_Pig-CloudStore, D1）: 新增
  `core/error_hints.py`（16 条规则，未命中原样透传），接入桌面连接对话框与 Web 连接 API，
  错误提示带「可能原因 + 建议动作」。
- **下载原子性**（借鉴 Pail, D2）: `S3ClientV1.download` 改同目录临时文件 +
  完成后 `os.replace`；失败/取消不留半截文件、不覆盖本地旧文件。
- **文本预览编码自动识别**（借鉴 CloudStore, D3）: 新增 `utils/text_codec.py`
  （BOM → UTF-8 → GB18030 → Big5 → Shift-JIS → Latin-1 兜底），Web 预览接口接入，
  响应带 `X-Preview-Encoding` 头标注实际编码。
- **递归搜索三上限**（借鉴 brows3, D4）: `services/search_service.py` 显式约束
  扫描 50000 对象 / 返回 1000 条，截断状态与扫描上限随结果回传，前端明示「结果可能不完整」。
- **文件夹移动逐源语义**（借鉴 bucketdock, D5）: `FileManager.rename_folder` 改为
  每条 copy 成功后立即删该条旧 key；copy 成功但删除失败的 key 如实报告（新旧各一份）。
- **桶 CORS 配置**（借鉴 medical_equ/s3 / sairo, D6）: 新增 `core/bucket_ext.py`
  （minio-py `_url_open` REST 实现）+ `BucketManager` 包装 + Web「跨域配置」卡片
  （读取/保存/删除，admin only）。
- **未完成分片清理**（借鉴 medical_equ/s3 / s3manager / Pail, D7）: 列举/中止桶内
  未完成分段上传，Web「分片清理」卡片；中断上传不再 invisible 计费。
- **对象公开性检查**（借鉴 s3manager, D8）: 对象属性接口附带匿名 HEAD 探测，
  Web 对象卡片展示「公开/私有」标记，误公开变可见信号。
- **预签名外链 Host**（借鉴 s3manager, D9）: 连接配置新增可选「外链 Host」，
  预签名按外部主机名重新签名（孪生客户端，字符串改写会破坏签名）；容器内网部署必备。
- **能力感知追踪**（借鉴 cagnard, D21）: `S3ClientBase` 运行时记录「服务端明确
  不支持的操作」，`/api/status` 透出，Web 侧栏对应入口虚线降级标记。
- **搜索 Unicode NFC 归一化**（借鉴 flask-s3-viewer, D26）: 关键词与对象名匹配前
  统一 NFC，修复 macOS NFD 上传「明明有却搜不到」。
- **反馈提交前清单**（借鉴 dickwu/r2, D29）: 桌面反馈提交前弹出发送内容清单
  （标题/正文/截图/日志/设备信息），用户过目才外发。
- **相对时间列**（借鉴 bucketdock, D33）: Web 对象列表时间列「N 分钟前」+ 悬停全量时间戳。

### 🎨 Changed（视觉体系换代）

- **「暮橙 Emberline」**: Web `app.css` 全量重写、桌面 `ui/styles.py` token 全套换值
  （主色 #1D4ED8 → #C2410C，画布 #F4F6FB → #FAF7F2，圆角 6/6/10 → 8/8/14）；
  Web 40 个 SVG symbol 整套重绘（圆头 stroke 2.0，ID 全保留）；桌面 127 个 Lucide PNG
  基色重着色为暖褐（`scripts/recolor_icons.py`，幂等可复跑）；侧栏改渐变品牌面板 +
  胶囊选中；页头改四层结构；全站标题文案刷新（语义不变）。仅亮色主题。

### 🐛 Fixed

- **测试基建 GC 崩溃**（BUG-R5-01）: Windows + Python 3.14 全量跑必崩
  （anyio portal 线程 cyclic GC C 层致命错误，非产品缺陷）——conftest 会话级 GC 管控根除。
- **截图测试环境跳过**（BUG-R5-02）: 无交互桌面环境 OSError 改 skip。
- **编码识别误判**（BUG-R5-03）: 无 BOM 字节不再被误判 UTF-16。
- **外链 Host 校验过严**（BUG-R5-04）: 主机:端口合法输入不再被拒。
- **`Optional` 注解未导入**（BUG-R5-05）: `policies_page` 补导入（`get_type_hints` 隐患）。
- **`field` 循环变量遮蔽**（BUG-R5-06）: `feedback_client` 三处改名 `cfg_field`。
- **颜色常量作用域错位**（BUG-R5-07）: `sync_dialog` SUB 两处按作用域修正。
- **全仓 lint 清洁**: 生产代码 pyflakes 告警 165 → 0。
- **桌面图标资源缺口**（存量体验缺陷）: 空状态一直请求 48px 图标但资源只有 16/24
  （图标静默缺失）——批量生成 63 个 @48 变体；品牌块请求不存在的 @22 改 24。

### 🧪 测试与质量

- 新增 `tests/test_v0_1_0_round5_borrowed.py`（50 项：错误映射 / 编码识别 / 搜索上限与 NFC /
  能力追踪 / 外链 Host / CORS 与分片 XML / 公开性探测 / 下载原子性）。
- `tests/test_v0_1_0_round2_fixes.py` 按 D5 新契约更新（逐源删除断言 + 新增双份报告用例）。

---

## [v0.1.0 第三轮迭代] — 2026-11-08 · 竞品借鉴落地 · Web 端「青瓷」视觉重构

> 本轮依据《docs/竞品借鉴清单-V0.1.0-20261108.md》（GitHub/Gitee 两阶段筛选 15 个候选、
> 6 个深度入围）逐项落地; 视觉重构覆盖 Web 端全部 10 页 + 登录/找回/重置 3 独立页,
> 桌面版沿用首轮「靛蓝引擎」体系不动（避免回归）。版本号保持 v0.1.0 不升号。

### 🆕 Added（竞品借鉴 · 7 项落地）

- **对象在线预览**（借鉴 MinIO Console / filebrowser, B1）: 新增
  `GET /api/objects/preview`（`webapp/routes/objects.py`）——按**扩展名白名单**
  判型（图片 7 类 + 文本 30+ 类, 上限 2MB）, 底层走
  `S3ClientV1.read_object_bytes()` 定长读取（`core/s3_client_v1.py`, V2 继承）
  + `FileManager.preview_object()`（`core/file_manager.py`, 不落盘）。安全设计:
  文本类一律降级 `text/plain` 输出（桶里存 .html/.js 也只做纯文本展示, 堵死
  同源内联执行的存储型 XSS）、全响应 `X-Content-Type-Options: nosniff`、
  svg 明确排除（可内嵌脚本）、图片超限直接拒绝。对象页新增「预览」入口与
  预览弹窗（图片直显 / 文本 <pre> 截断提示）, viewer 可用。
- **文件夹结构上传**（借鉴 filebrowser 拖拽递归, B2）: `POST /api/objects/upload`
  新增可选 `paths` 表单字段（与 files 逐位对应）——每段路径 `sanitize_filename`
  清洗 + 拒绝 `.`/`..` 段 + 落盘前 `is_relative_to` 双重防穿越;
  `WebTaskManager.run_upload()` 新增 `rel_paths` 参数按相对路径入桶
  （`webapp/tasks.py`）。前端支持三种入口: 按钮选文件 / 目录选择器
  （`webkitdirectory`, 保留根目录层级）/ 表格区整片拖拽
  （`webkitGetAsEntry` 递归遍历, DataTransfer.items 同步收集防失效）。
  不传 `paths` 时保持旧平铺语义, 桌面版与既有调用零影响。
- **表头点击排序**（B3）: 对象列表名称/大小/修改时间三列可排序
  （前端完成, 目录恒排最前与列表语义一致）, 搜索结果保持服务端顺序。
- **多选增强**（B4）: 复选框支持 Shift 范围选择（锚点记忆）、Ctrl/Cmd 加选;
  键盘 `Ctrl+A` 全选本页。
- **键盘快捷键**（B5）: `Delete` 删除选中、`F2` 重命名首个选中
  （仅 admin 写权限生效, 焦点在输入框/下拉时不拦截）。
- **桶容量占比条**（借鉴 MinIO Console 指标可视化, B6）: 数据总览页桶分布表
  新增纯 CSS 占比条（无图表库依赖）, 异常桶红色标示。
- **文件类型线性图标**（B7）: 目录/图片/视频/音频/压缩包/代码/数据/文档八类
  SVG 图标按扩展名自动区分, 替换原 📁/📄 emoji。

### 🎨 Changed（Web 端视觉重构 · 全页面）

- **全新「青瓷 Celadon」设计系统**（`webapp/static/css/app.css` 全量重写）:
  青瓷绿主色（#0E8074）替换亮蓝（#165DFF）、浅色分区侧栏替换深藏青侧栏、
  大圆角（14px）软阴影卡片、「域标签 + 大标题」双层页头（kicker）、
  白底彩边 toast、浅色代码块、登录页无背景装饰纯卡片。全部历史类名与
  元素 ID 保持兼容, 页面功能不受影响。
- **导航重组**: 侧栏按业务域分组（数据资产 / 访问控制 / 存储治理 / 系统运维）,
  base.html 内联 40+ 枚线性 SVG sprite 图标, 全站 emoji 图标清零
  （导航/按钮/表格/空态/弹窗/独立页）。
- **页面标题文案更新**（语义不变, 表述对齐新视觉）: 概览→数据总览、
  存储桶→存储桶空间、对象管理→对象资源管理、用户管理→MinIO 用户管理、
  策略管理→访问策略管理、版本控制→数据版本控制、生命周期→生命周期规则、
  操作日志→审计日志、系统设置→系统与账号、关于→关于本系统;
  各卡片区块标题同步更新（存储桶详情→桶容量分布、应用设置→传输与上传限制等）。

### 🐛 Fixed

- **侧栏导航全项高亮**（存量 UI BUG, 本轮重构审查中发现）: 旧 base.html 把
  `{% block nav_active %}` 放在页面循环内, Jinja 对块内循环每次迭代重复渲染
  同一 override, 导致**所有**导航项同时获得 active 高亮。改为 JS 按
  `body[data-page]` 精确点亮（`webapp/static/js/app.js`）。

### 🧪 Tests

- 新增 `tests/test_web_v0_1_0_borrowed.py` **13 项**: 预览白名单/文本强制
  text/plain + nosniff/图片直通/文件夹拒绝/未登录 401; 上传 paths 数量不匹配/
  `..` 段拒绝/结构化 key 落桶断言/平铺语义不变; core 层定长读取 offset/length
  断言 + close/release_conn 连接释放断言 + FileManager 截断标记。
- `tests/conftest.py` Web 前置分组并入新文件（规避 Windows Py3.14 桌面测试
  后跑 TestClient 的 STATUS_BREAKPOINT 崩溃）。
- `tests/test_web_app.py` 1 处页面标题断言同步（概览→数据总览）。

### ✅ Verified

- `python -m pytest tests/ -q --basetemp=.pytest-tmp`（Windows 10 / Py3.14）:
  **263 通过 / 8 失败**——8 个均为基线已知 Qt 桌面环境性失败（与本轮无关,
  基线即如此）; 较上一轮 248+8 净增 15 通过（13 新增 + 2 处相关断言调整）。
- `node --check` 2 个 JS 通过; Jinja2 全模板编译通过（含子模板多余 block
  兼容性验证）。
- 版本号三处同号核验: `webapp/__init__.py` / `config/settings.py` /
  `docker-compose.yml` = 0.1.0 / v0.1.0。

### 📚 Docs

- 新增《docs/竞品借鉴清单-V0.1.0-20261108.md》（并归档
  `docs-archive/03-竞品调研/`）: 15 候选池 → 6 深度入围 → 20 条借鉴点
  （7 落地 / 3 暂缓 / 1 明确不采纳 / 9 随视觉重构落地）。
- 《BUG修复清单-v0.1.0》追加 BUG-13; 《功能优化与新增-v0.1.0》《版本迭代说明
  -v0.1.0》《安全审查报告-v0.1.0》《使用说明-v0.1.0》同步本轮内容;
  README 功能表补预览/文件夹上传/新界面体系。

---

## [v0.1.0 第二轮迭代] — 2026-10-28 · 会话外置化 · 多 worker 可用

> Web 容器版专项迭代（桌面版仅 1 处同步语义修复）。版本号保持 v0.1.0 不升号；
> 完整设计依据（竞品调研）与逐项验证见
> [docs/版本迭代说明-v0.1.0.md](docs/版本迭代说明-v0.1.0.md) 第二轮章节。

### 🆕 Added（会话外置化 · O1）

- **无状态签名会话令牌**（`webapp/token_session.py`）：stdlib `hmac` + `base64`
  自实现 HMAC-SHA256 两段式令牌（body.sig），显式 `exp` 过期、常数时间签名比较
  （`hmac.compare_digest`）、验签失败一律视为未登录（fail closed）；配套 ASGI
  中间件 `TokenSessionMiddleware` 取代 starlette `SessionMiddleware`
  （后者摘要算法 SHA1 且不可选）。cookie 保持 HttpOnly + SameSite=Lax + Max-Age。
  零新增第三方依赖（`requirements-web.txt` 未变）。
- **会话/连接/任务持久化层**（`webapp/persist.py`，新表落 `data/web/web.db`，
  WAL + busy_timeout=5000 + synchronous=NORMAL）：
  - `web_sessions`：登录会话行（sid/username/expires_at/revoked）+ 连接快照
    （endpoint + Fernet 加密 AK/SK + ssl，沿用 `explorer.key` 密钥体系）+
    剪贴板 JSON + 跨 worker 活跃时间戳；
  - `web_tasks`：任务注册表（状态/进度/明细/取消标志/结果 zip 路径）。
- **多 worker 会话重建**（`webapp/context.py`）：内存会话退化为缓存，worker
  重启或请求落到其他 worker 时按快照静默重连 S3、恢复剪贴板；闲置回收按
  **持久层全局活跃度**裁决，其他 worker 正在用的会话不会被本地定时器误杀。
- **跨 worker 任务可见**（`webapp/tasks.py`）：本 worker 内存副本 + 其他 worker
  只读 `TaskView`；取消经 `cancel_requested` DB 标志传递（执行方 2s 节流轮询）；
  结果 zip 在共享卷上路径全局有效。
- **`WEB_WORKERS` 可配置**：Dockerfile CMD 改 `sh -c exec uvicorn ... --workers
  ${WEB_WORKERS}`（默认 1），compose `environment` 注释示例与 README/DOCKER.md
  「多 worker 说明」（调大前提/仍按进程独立的状态/升级需重新登录一次）同步。
- **测试**：新增 `tests/test_web_session_ext.py` 22 项——令牌签发/过期/篡改/
  错误密钥/畸形输入、cookie 属性、多请求登录态保持、登出重放旧 cookie 失效、
  worker 重启连接重建（含 AK/SK 密文落库断言）、剪贴板二次重启保持、跨 worker
  闲置保护与真闲置清快照、任务跨 worker 轮询/取消/结果路径、停用账号即吊销、
  `WebStateStore` 有效性裁决与行清理。

### 🐛 Fixed

- **`test_compute_plan_mirror` Windows 失败**（现象：断言 `to_delete_local == 0`
  实得 1）：根因**不是** mtime 粒度，而是 `services/sync_service.py` MIRROR 分支
  把"仅本地"文件登记进 `to_delete_local` 的**死代码**——这些文件必然同时在
  `to_upload`，`execute_plan` 的删本地护栏（上传队列内不删）会全部跳过；登记
  还使桌面同步预览显示永远不会执行的"× 删本地"。删除该登记，预览/执行/测试
  三方语义对齐。
- **登出后旧 cookie 仍可用**（安全）：旧实现登出只清浏览器 cookie + 本进程
  内存，被偷的 cookie 到 7 天到期前一直可登录。现登录落 `web_sessions` 行，
  登出/停用/删除账号即置 `revoked=1`，鉴权依赖每请求查行校验，全 worker 即时失效。
- **会话密钥多 worker 竞写**：旧实现 read→generate→write 三步无原子性，N 个
  worker 同时首启会互相覆盖出不同密钥（令牌跨 worker 全失效）。改
  `O_CREAT|O_EXCL` 原子创建 + 失败者轮询等待（与 `Encryptor` 同纪律）。
- **首次启动 admin 创建竞态**：多 worker 同时"查无 admin→各自 INSERT"，后到者
  撞唯一约束炸掉启动；捕获唯一冲突后复核，admin 已存在即跳过。
- **强制改密标记滞后**：`must_change` 原存签名 cookie，管理员重置口令后在线
  会话仍带旧标记/反向漏拦；改由 `web_users.must_change_password` 每请求推导。
- **剪贴板 cut/copy 落库错序**：通知回调在 `_operation` 赋值前触发，复制被
  记成 `none`；调整为状态完整后通知（桌面版不传回调，行为不变）。
- **设置页上传上限显示口径**：GET `/api/settings` 默认回 0（不限制），而实际
  生效默认 100MB，两处口径不一致；统一回退 `MAX_UPLOAD_SIZE`。
- **SMTP 端口脏值 500**：库内 `smtp_port` 非数字时 `int()` 直接抛错；容忍回退 465。
- **断开连接日志丢 endpoint**：`disconnect()` 后 `current_endpoint` 已为 None，
  日志目标变空串；改为断开前先取。

### ✅ Verified

- `python -m pytest tests/ -q --basetemp=.pytest-tmp`（Windows 10 / Py3.14）：
  **248 通过 + 8 失败**——8 个均为基线已知的 Qt 桌面环境性失败
  （`test_v0_1_10`×2 / `test_v0_1_12`×4 / `test_v0_1_16`×2，与本轮改动无关，
  基线时同样失败）；sync mirror 修复后较基线（225+9）净减 1 失败、净增 23 通过
  （22 新增 + 1 修复）。
- 针对性场景验证（脚本实跑）：登出后重放旧 cookie → 303/401；worker 状态重置后
  `/api/status` 连接自动重建（新客户端实例已连接、SK 明文不落库）；剪贴板跨
  两次重启保持；被停用账号下一请求 401。
- 测试基建：`conftest.py` 把 `test_web_session_ext.py` 并入 web 测试前置分组
  （规避 Windows+Py3.14 TestClient 的 STATUS_BREAKPOINT 崩溃）；新测试文件加
  模块级 admin 口令归一化（隔离 `test_web_app.py` 改密后的共享库串扰）。

---

## [v0.1.0] — 2026-10-12 · 桌面版与 Web 容器版版本归一 · Web 正式稳定版

> **版本口径说明（重要）**：本项目存在两条版本线索——
> ① 桌面版（Tkinter）自 **0.1.0** 起家（2026-10-04 首个正式版）；
> ② Web 容器版（FastAPI + Docker）在桌面版 0.1.0 基础上孵化，内部迭代号走了
> **2.0 → 2.1 → 2.2 → 2.3 → 2.4**（用户管理增强、忘记密码、预签名分享等，
> 见下方历史条目 `web-2.x`）。
> 本版起两条线索**归一为 v0.1.0 正式稳定版**：Web 版 `webapp/__init__.py`
> 的 `__version__`、桌面版 `config/settings.py` 的 `APP_VERSION`、docker-compose
> 镜像标签 `objstoreexplorer-web:v0.1.0` 三处同号；后续两条产品线同版本号共同演进。
> 历史条目保留原名（`web-2.x` / `0.1.0`）不改写，仅新增本归一说明。

### 🔒 安全加固

- **存储型 XSS 修复**：S3 目录名/MinIO Access Key/Web 用户名/策略名此前拼进
  内联 `onclick` 的 JS 字符串（`escapeHtml` 的实体在属性中会被解码回引号导致
  字符串逃逸）。对象页面包屑、用户管理、系统设置-Web 账号、策略列表、桶列表
  全部改为 `data-*` 属性 + 事件委托，值不再经过 JS 字符串解析。
- **路径穿越修复**：打包下载的 zip 文件名此前直接拼接未校验的 bucket 参数，
  恶意桶名（`../`）可写出临时目录；现经 `sanitize_filename` 清洗。
- **信息泄露收敛**：未处理异常 500 响应不再回显异常原文（详情只进服务端日志）；
  422 参数校验错误剥离 pydantic v2 的 `input` 原始输入（不再回显请求体）。
- **安全响应头**：新增中间件统一附加 `X-Content-Type-Options` / `X-Frame-Options` /
  `Referrer-Policy` / 基础 `Content-Security-Policy`。
- **依赖最小升级**（GitHub Advisory Database 核查，2026-10-12）：
  `starlette` 显式下界 `>=1.3.1`（旧传递区间含 CVE-2025-62727 FileResponse
  Range DoS——本项目下载接口正在用 FileResponse）、`python-multipart>=0.0.31`、
  `jinja2>=3.1.6`、`cryptography>=50.0.0,<51.0.0`（清除 CVE-2026-69247/69249 等）。

### 🐛 缺陷修复（详见 docs/BUG修复清单-v0.1.0.md，共 12 项）

- **测试容器环境适配**：`tests/conftest.py` 的 `WEB_ADMIN_PASSWORD` 由
  `setdefault` 改为强制覆盖——镜像内 Dockerfile 自带 `ENV WEB_ADMIN_PASSWORD=""`（空串），
  setdefault 不覆盖已存在变量 → 容器内跑 Web 测试套件登录全挂
  （v0.1.0 服务器实测发现，本机无该变量时行为不变）。

- **会话销毁线程泄漏**：过期/登出会话不关闭 TransferService 自有 12 线程执行器，
  常驻线程随会话轮换持续累积——销毁时补 `transfer.cleanup()`。
- **事件循环阻塞（workers=1 关键项）**：Admin/登录/改密/发码/SMTP 测试等 30 个
  处理器此前为 `async def` 但函数体是阻塞的 MinIO 网络调用、bcrypt 哈希、SMTP
  收发（最长 15s）——慢 MinIO 会卡住所有用户的所有请求。全部改为同步 `def`，
  由 FastAPI 线程池执行。
- **上传临时文件句柄未关**：新版 Starlette 的 `UploadFile.close()` 是协程，
  同步调用不生效（never-awaited 警告 + Windows 下妨碍目录清理），改关底层文件。
- **磁盘泄漏兜底**：会话销毁真正调用 `cleanup_session_files`（此前零调用）；
  清理循环每分钟扫描并删除超过 2 小时的陈旧 `web_*` 临时目录（覆盖客户端
  中途断开导致 `BackgroundTask` 未执行的场景）。
- **上传大小预检**：超限文件此前先完整落盘再被后台任务拒绝，现按
  `max_upload_size_mb` 在落盘前拒绝（400 + 中文提示）。
- **重命名父目录计算错误**：对象 key 含 `%` 编码序列时因 display_name 经过
  URL unquote 导致反推父路径错乱；改为直接取当前目录前缀。
- **zip 桶名穿越**（同安全项）、**参数校验补齐**（空桶/key/首斜杠 key 返回
  友好 400）、**viewer 清空剪贴板 403 不对称**、**上传落盘 OSError 友好报错**。

### ✨ 新增（小而实用，3 项）

- **会话过期友好提示**：API 会话过期（401）跳转 `/login?expired=1`，登录页
  显示「登录已过期，请重新登录」，不再无声消失。
- **连接测试按钮**：连接对话框新增「测试连接」——验证 Endpoint/AK/SK 可达
  可用，不保存历史、成功后立即断开不占用会话连接位。
- **陈旧临时目录自动清理**（同缺陷修复项，运行期兜底）。

### 🔧 变更

- docker-compose 镜像标签 `objstoreexplorer-web:2.4.0` → `v0.1.0`（版本归一）。
- `tests/`：修正 3 个与实现/文档相悖的过期断言（`parse_endpoint` 无协议默认
  端口按 MinIO 补 **9000**，README 与 validators docstring 均已明确）；
  其余 9 个桌面版 mock 断言漂移（sync/delete_bucket/策略更新/反馈窗标题）
  如实记录于 docs/audit-v0.1.0-排查清单.md，不影响 Web 功能，待桌面版专项回归。
- 新增文档：`docs/audit-v0.1.0-排查清单.md`、`docs/BUG修复清单-v0.1.0.md`、
  `docs/功能优化与新增-v0.1.0.md`、`docs/版本迭代说明-v0.1.0.md`、
  `docs/安全审查报告-v0.1.0.md`、`docs/使用说明-v0.1.0.md`；README/DOCKER.md 同步。

### ⏪ 回滚说明

- 数据结构零变更（无表结构/迁移），回滚 = compose 镜像标签改回
  `objstoreexplorer-web:2.4.0` 重新 `up -d --build`，`./data` 原样保留。
- 代码回滚还原本轮涉及文件（`webapp/` 与 `requirements*.txt`、compose）即可；
  已归一的版本号不影响运行时行为。

### ✅ 验证

- `python -m py_compile` 全部改动 .py 通过；`node --check` 两个 JS 通过。
- `pytest tests/test_web_app.py tests/test_web_users_um.py` 32/32 通过；
  针对本轮修复的 22 条冒烟断言全部通过（权限矩阵/安全头/上传预检/路径清洗/
  陈旧目录清理/执行器关闭等，见 docs/BUG修复清单-v0.1.0.md 附录）。
- 全量套件 225 通过 / 9 存量失败（均为桌面版 mock 断言漂移，先于本轮存在并逐一说明）。
- 依赖 CVE 核查：GitHub Advisory Database（api.github.com/advisories）实测查询，
  升级后锁定区间内无已知高危未修复项。

---

## [web-2.4.0] — 2026-10-12 · 对象预签名 URL 分享 (O2)

### ✨ 新增

- 对象管理页新增**预签名分享**：文件行操作列与右键菜单新增「分享」，
  弹窗选择有效期（1 小时 / 24 小时 / 7 天，服务端白名单校验，上限 604800 秒），
  生成带签名的对象 GET 下载链接并支持一键复制（非 HTTPS 环境自动回落选中复制）。
- 新增 `POST /api/objects/share` 接口：复用现有会话鉴权（未登录 401）与
  下载接口同一套权限逻辑（viewer 可用），通过该会话连接的 S3 客户端
  （`core` 预签名能力）生成链接；分享动作写入操作日志
  （操作人 / 时间 / 对象 / 有效期，失败同样留痕）。
- 边界处理：对象不存在、连接失效、生成失败均返回友好中文提示；
  文件夹与空白 key 拒绝分享。

### 🔧 变更

- 对象列表「操作」列宽 130px → 170px，容纳第三个行按钮；
  只读账号工具栏提示同步为「可浏览 / 搜索 / 下载 / 分享」。
- docker-compose.yml 镜像标签 `objstoreexplorer-web:2.3.0` → `2.4.0`；
  DOCKER.md 补充预签名分享用法与安全提示
  （**签发后无法单独吊销，泄露请轮换 Access Key**）。

### ⏪ 回滚说明

- 本版不涉及数据结构与存储格式：回滚 = 将 docker-compose.yml 镜像标签改回
  `objstoreexplorer-web:2.3.0` 后 `docker compose up -d --build`
  （`./data` 数据目录原样保留，无需迁移）；代码回滚还原
  `webapp/routes/objects.py`、`webapp/templates/objects.html`、
  `webapp/static/js/page_objects.js` 三个文件即可。
- 已签发的外链由对象存储侧签名保证有效期，与应用回滚无关：
  到期自动失效，轮换该连接的 Access Key 可使其立即全部失效。

---

## [web-2.3.0] — 2026-10-11 · Web 容器版拆分为独立 Docker 项目

### ✨ 新增

- 新增 `deploy.sh` / `deploy.bat` 独立一键部署脚本（建数据目录并 `docker compose up -d --build`）。

### 🔧 变更

- DOCKER.md 重写为自包含部署文档：修正宿主端口为 6083（原文误写 18080），
  补齐初始账号获取方式、强制改密说明与备份指引。
- 本目录自此可独立交付部署，不依赖上级目录的 deploy.sh / README.md。

---

## [0.1.0] — 2026-10-04

首个正式版本。Tkinter 桌面客户端，跨平台（Windows / macOS / Linux）。

### ✨ 新增

- **概览页** — 后台线程池并发统计全部存储桶的对象数、文件夹数与容量占比
- **存储桶管理** — 列出 / 创建 / 强制删除（先清空再删）/ 递归统计
- **对象管理** — 面包屑导航、批量上传下载、复制 / 剪切 / 粘贴、重命名、删除、属性查看
- **搜索** — 当前桶 / 目录下按名称模糊匹配，支持递归
- **同步** — 本地 ↔ 远端推送 / 拉取 / 镜像，冲突逐项确认，支持「完成后删源端」
  与「删除目标端多余」两个开关
- **剪贴板** — 跨目录复制与剪切，粘贴时可选择目标目录
- **MinIO 用户** — 创建 / 启用 / 禁用 / 重置 Secret Key / 附加策略（需 Admin API）
- **访问策略** — JSON 语句编辑，附 readonly 模板起步
- **一键创建整套** — 桶 → 用户 → 策略 → 附加 四步向导
- **版本控制** — 桶级启用 / 暂停版本化
- **生命周期** — 桶级单条过期规则（覆盖式）
- **操作日志** — 全量留痕，支持级别筛选与关键字本地过滤
- **系统设置** — 上传大小限制、口令修改
- **反馈** — 在线提交 / 离线打包 zip，内置一键自检（网络、进程、平台、事件日志）
- **S3 客户端工厂** — 自动适配 minio-py V1 / V2 两套 API
- **Fernet 加密存储** — Access Key / Secret Key 对称加密落盘，SK 不回显
- **后台线程池** — 上传下载、并发统计、批量删除均不阻塞 UI，长任务可取消
- **PyInstaller 打包** — onedir 模式，产物 `ObjStoreExplorer-v0.1.0-win-x64.zip`

### 🎨 视觉体系

- 「靛蓝引擎」设计系统：冷灰蓝画布 `#F1F3FA` + 靛青主色 `#4F46E5` + 大圆角卡片
  + 30px 巨型页标题（英文 kicker + 中文标题 + 副标题 + 右侧操作区）
- 侧栏由深蓝改为浅色并分 4 组（数据资产 / 访问控制 / 存储治理 / 系统运维）
- 新增可复用组件：`PageHeader`（页眉）、`StatCard`（统计卡）、`DialogChrome`（对话框外壳）、
  `scrollarea`（画布滚轮安全绑定）
- 126 个 Lucide 线性图标，**清除全部 Emoji 图标**
- 侧栏 / 顶栏 / 卡片 / 按钮 / 徽章 / 徽章态 / 表格 / 空状态全量重做

### 🔧 修复

- **侧栏所有菜单项同时高亮** — `{% block %}` 等价写法在循环内对每项都生效，
  改为按当前页 id 逐项比对
- **PhotoImage 缓存未按 Tk 解释器隔离** — 同一进程内换 `tk.Tk()` 后缓存的
  `pyimage` 失效，报 `image "pyimage1" doesn't exist`
- **图标缓存 key 漏了 tint** — 同一图标不同颜色共用首个 PhotoImage，
  导致侧栏 hover / 选中态换色不生效
- **关闭子对话框后滚轮必崩** — 5 处 `bind_all("<MouseWheel>")` 挂在应用级 bindtag，
  弹窗销毁后残留 handler 引用已销毁的 canvas，任意一次滚轮即
  `TclError: invalid command name`
- **Ctrl+V 全局残留** — 反馈窗口关闭后在别处按 Ctrl+V 仍触发已销毁回调
- **联网探测误判** — 用 HEAD 请求探测 PHP 接口返回 405，而 `HTTPError` 是
  `URLError` 子类被一并吞掉，导致「明明有网却提示无网络」。
  改为：拿到任何 HTTP 状态码即视为网络可达（DNS + TCP + TLS 已全部成功）
- **窗口尺寸装不下新布局** — 默认尺寸从 1200×750 调整为 1440×900，最小 1100×700
- **所有带图标的按钮图标被裁掉 4px** — `tk.Button` 的 `-width` 是**双语义**选项：
  没有 `-image` 时它是「文本区宽度，单位=字体字符宽」；有 `-image` 时它是
  **「图片区宽度，单位=像素」**。按钮工厂统一默认 `width=12` 而图标是 16px，
  于是 Tk 把图标裁到 12px。影响 **45 处、16 个文件**，顶栏「连接 / 断开 / 刷新 /
  一键创建 / 反馈」五个全中。改为带图标时不下发 `width`（按内容自适应），
  等宽需求只由纯文字按钮承担

  > 这个缺陷的来历值得记一笔：`width` 此前是**死参数**（工厂声明了却从不使用），
  > 后来为修「对话框按钮参差不齐」把它真正接上——**修好了旧的，引入了新的**。
  > 带图标的按钮原本是自然宽度（图标完整），接上 `width` 反而被挤窄。
  > 该缺陷在实机使用中发现并已并入本版，`v0.1.0` tag 已重推至含此修复的提交。

### 🧹 移除

- `lifecycle_dialog.py` — 已被 `LifecyclePage` 就地渲染取代
- `version_control_dialog.py` — 已被 `VersioningPage` 就地渲染取代
- `TOOLBAR_HEIGHT` / `SIDEBAR_COLLAPSED_WIDTH` — 零引用的配置常量
- **Web 容器版（Docker）** — `objstoreexplorer-docker/` 全部 259 个文件，
  收敛为单一桌面形态。连带清理代码与文档中 12 处 docker / Web 引用
  （含一处用户可见界面文案）、`.env.example` 中失效的 `WEB_ADMIN_PASSWORD`

### 🐛 缺陷清理（v0.1.0 发布前的全面审计）

四路并行逐行审计（core+config / services+utils / ui / 入口与打包），
共 201 条发现，全部处理。其中 **4 条属于"会真的破坏生产环境"级别**：

- **修改桶策略会抹掉用户的其他策略与组身份** — MinIO 的
  `attach/detach_policy` 底层是 `SetPolicy`（设置完整列表），
  按增量语义调用等于抹掉其余策略。改为 detach 前快照、整体写回、失败回滚
- **重置用户密码失败会永久销毁该用户** — 原实现是 `remove` + `add`，
  `add` 失败则用户消失且组身份丢失。改为提前校验密钥 + 快照还原
- **一键创建整套会对已存在用户返回从未提交的随机密码**，
  却提示「创建成功」
- **同步功能在"两端有相同文件"时必崩** — `SyncPlan.skipped` 属性根本不存在

其余高危项：跨线程直接调用 Tk 共 11 处（新增 `ui/threading_bridge.py`）、
同步对话框 `destroy()` 后再 `after()` 导致的永久死锁、4 个对话框关闭后回调
写入已销毁控件导致凭据/反馈结果丢失。

完整清单见《BUG 修复清单》。

### 🛡 安全加固

| 项 | 变更 |
|---|---|
| 依赖 CVE | `pip-audit` 实测查出 **21 个漏洞**（Pillow 18 个含 PSD 越界写与 FITS 解压炸弹、urllib3 3 个含流式 DoS）。升级后复扫 `No known vulnerabilities found` |
| 端点校验 | 拦下 CRLF 注入、shell 元字符、非 http(s) 协议；40 项实测，合法输入零误杀 |
| 下载落盘 | `sanitize_filename` 接入下载路径 + 同名去重；16 个恶意 key 实测无一逃逸 |
| 反馈凭据 | app_key 移出源码与版本控制，强制 https，改走 `X-App-Key` 请求头；日志打包前正则脱敏 |
| 数据一致性 | 强删桶、策略修改、用户重置等操作补快照与回滚 |
| 密钥管理 | 损坏检测、原子创建、原子轮换、失败回滚 |
| SQL | 全参数化，无字符串拼接 |

> ⚠ 一个值得记下的教训：加固依赖时给 Pillow 写了上界 `<12.0.0`，
> 而**所有修复版本都在 12.x** —— 上界本身把安全补丁挡在了门外。
> 靠人眼看 `requirements.txt` 发现不了，只能靠机器扫。

详见《安全审查报告》。

### 🚦 质量门禁

- **`test:deps` 依赖漏洞作业** — `pip-audit` 扫运行时闭包（15 个包）。
  检出漏洞即阻断；**漏洞库不可达时同样判失败**，不让安全门禁变成
  "看起来在跑其实没跑"
- **版本号单一真源** — `config/settings.py` 的 `APP_VERSION`，
  移除 `OSE_VERSION` 覆盖机制（此前 tag 流水线会改写版本号，
  同一 commit 能打出两个版本的产物）
- **`requirements.txt` 首行的 PEP263 编码声明不可删** — pip-audit 通过
  `pip_requirements_parser` 读该文件，其 `auto_decode` 只认 BOM 与编码声明，
  否则回落到系统 locale，中文 Windows 上必定崩溃。**此故障只打
  `test:deps`，`pip install -r` 与 build 作业均正常**，极易误判成网络抖动

### 📦 交付形态

- 目录扁平化：`objstoreexplorer-local/` 内容上提仓库根，源码直接位于根目录
- 新建 GitLab 项目并推送，`main` 推送即自动构建 exe 并发布滚动版 release
- 全部依赖补版本上界（PyInstaller 打包时依赖即冻结，只写 `>=` 会静默引入
  未验证的大版本）
- **打包不再依赖版本控制外的文件** —— 原来打的是开发者本机的
  `config/feedback.yaml`（被 `.gitignore` 排除，因为含真实 `app_key`），
  CI 全新 checkout 上必然构建失败；现在打的是 `feedback.yaml.example` 的内容、
  落位名 `feedback.yaml`。顺带堵上一个凭据随产物外泄的口子

---

[0.1.0]: #010--2026-10-04


---

## [0.1.0] 第四轮再定版（2026-11-10 · 正式稳定版）

> 版本号仍为 **0.1.0**（单一真源机制未动，本轮为同号再定版：全量审计 + 修复 + 视觉重构 + 文档对齐）。
> 全量测试 **294 通过 / 0 失败**；依赖扫描 **No known vulnerabilities found**。

### 🐛 BUG 修复（数据完整性族，全部有测试锁定）

- **Web 删文件夹只删占位对象** — S3 文件夹只是 `/` 结尾 0 字节占位对象，旧实现把它当普通 key 删，
  子对象全部残留而界面报"删除成功"。改为文件夹走 `FileManager.delete_folder`（list 展开 + 批量删），
  文件走线程池，每批 200 条且批间检查取消
- **Web 文件夹重命名/移动只挪占位对象** — 新增 `rename_folder`/`copy_folder`（展开→逐条 copy→全部成功后
  才批量删旧；任一步失败即中止并如实报告已迁移数量，旧数据不动）
- **Web 文件夹打包下载只有 1 个空文件** — 下载前先把文件夹 key 展开成子 key 并修正任务总数
- **剪贴板复制/剪切文件夹只操作占位对象** — 按 `is_dir` 分流到整棵子树操作；任一项失败保留剪贴板以便重试
- **删除任务"取消"实际无效** — 分批 + 批间取消检查点；取消后未处理条目如实记"已取消"，不再谎报 success
- **Windows 密钥文件被授予 Everyone 读写** — `CreateWellKnownSid(1)` 是 WinWorldSid 而非当前用户，
  且 DACL 被整体替换。改为取当前进程用户 SID 仅授 READ，保留继承 ACE 后追加强化 ACE

### 🔒 安全加固

- 初始 admin 随机口令不再写入轮转日志文件（原会落盘 644 并随 `data/` 备份外流），唯一出口为 stdout
- bcrypt 72 字节硬限制统一预校验，友好中文提示替代英文库错误直出
- 桶名/AK 校验控制字符闸 + `re.fullmatch`，堵住尾随换行绕过（CRLF 注入面）
- `sanitize_filename` 处理 Windows 保留设备名（CON/PRN/NUL/COM1-9/LPT1-9），避免落盘写到设备
- 登录等耗时（不存在用户也跑一次 dummy hash 校验），堵住用户名枚举时序侧信道
- 登录限速 key 截断用户名 + LRU 上限，防超长用户名内存放大
- 创建用户失败不再回传从未提交给服务端的随机 secret_key
- **Pillow 39 条 CVE 修复**（升级 13.0.0）—— 上界 `<13.0.0` 恰好挡住修复版，第二次踩同一个坑，
  已在 requirements 注释中固化"告警先核对修复版本号 vs 上界"的检查项

### ✨ 新增

- **Web 端对象历史版本浏览 / 恢复 / 删除**（3 个接口 + 版本控制页卡片）：误覆盖/误删后用户可在 Web 自助
  恢复任意历史版本；删除标记与当前版本均有前置拦截；写操作记审计日志
- `OSE.del` 增加可选 body 参数（不传时行为与旧版完全一致）

### 🎨 视觉重构「曜蓝 Azureline」（桌面 + Web 双形态归一）

- Web：`app.css` 全量重写、`base.html` 图标库整套重绘（symbol ID 全保留，JS 零改动）、
  14 个模板页头升级为「眉题 + 大标题 + 描述」三层、登录/找回/重置三页重设计为
  「左渐变品牌面板 + 右表单」分栏；主色青瓷绿 → 钴蓝，新增蓝紫渐变品牌，圆角全面收锐
- 桌面：`ui/styles.py` token 全套切换为同值体系，卡片 1px 边框 + 左侧 3px 主色 accent 条
- 文案：各页按钮/标题/描述同步更新（语义不变），全站 emoji 清零

### 🧪 测试与工程

- 新增 `tests/test_v0_1_0_round2_fixes.py`（11 项：文件夹语义族 + M 系列加固）
- 新增 `tests/test_web_versions.py`（11 项：版本 API 全路径含 viewer 403）
- 修正 5 项过期测试基线（删桶批量语义、策略摘除快照写回语义）
- 修复测试隔离缺陷：conftest 新增 autouse fixture（清登录限速表 + admin 口令归一），
  消除跨测试文件串扰造成的假失败（原仅在特定组合下暴露）
- 清理死代码：无效 `nonlocal`、死赋值、无占位符 f-string、双重否定、模块中段 import

### 📚 文档

- 新增《竞品借鉴清单-V2.0-20261110》（23 条：已落地 14 / 暂缓 8 / 不采纳 1）
- BUG 修复清单 / 功能优化与新增 / 版本迭代说明 / 安全审查报告追加第四轮记录
- 重写《项目介绍》对齐当前双形态与新视觉；使用说明补充历史版本能力与权限矩阵
- README 更新视觉体系与借鉴清单链接

[0.1.0]: #010--2026-10-04
