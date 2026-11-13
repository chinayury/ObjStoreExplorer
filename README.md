# ObjStoreExplorer

> MinIO / S3 兼容对象存储管理工具 · **正式稳定版**（桌面版与 Web 容器版版本归一）
> 桌面版：纯 Python 3.13 + Tkinter · Windows / macOS / Linux
> Web 版：FastAPI + uvicorn · Docker 容器部署（见 [docs/02-环境部署教程](docs/02-环境部署教程.md) §2.3）

一个对象存储管理工具，提供两种交付形态：

| 形态 | 技术 | 定位 | 入口 |
|---|---|---|---|
| **桌面版** | Tkinter | 单人本地使用，含本地↔远端**同步**、反馈等独有能力 | `python -m objstoreexplorer` |
| **Web 容器版** | FastAPI + Docker | 浏览器多人访问，viewer/admin 两角色，桶/对象/用户/策略管理 | `docker compose up -d --build` |

两个形态复用同一套 `core/`（S3 客户端/加密/管理器）、`services/`（传输/剪贴板/检索）、
`config/` 业务层（均位于 `src/objstoreexplorer/` 包内），数据目录互通（连接历史/操作日志共享）。
桌面版**不监听任何网络端口**，Web 版默认监听容器内 8000（compose 映射宿主 6083）。

> **版本口径**：桌面版与 Web 容器版已归一为同一版本号，唯一真源为
> `src/objstoreexplorer/config/settings.py` 的 `APP_VERSION`，
> `webapp/__init__.py` 与 compose 镜像标签同号。完整线索见
> [CHANGELOG](CHANGELOG.md) 与 [docs/05-开发日志](docs/05-开发日志.md)。

---

## 功能

| 分组 | 模块 | 能力 |
|---|---|---|
| **数据资产** | 存储总览 | 并发统计全部桶的对象数、文件夹数与容量占用（含占比可视化） |
| | 存储桶空间 | 建桶、删桶（含强制清空）、统计、**桶访问策略**（公共读 / 防盗链）、**CORS 配置**、**未完成分片清理** |
| | 对象资源管理 | 上传（**文件夹结构上传 / 拖拽**）、下载、**在线预览**（图片/文本，编码自动识别）、重命名、复制/剪切/粘贴、批量删除、递归搜索（上限如实提示）、表头排序、Shift/Ctrl 多选与快捷键、**元数据与标签**、**公开性检查** |
| | 同步管理 | 本地 ↔ 远端双向同步，推送 / 拉取 / 镜像三种方向，冲突逐个确认（桌面独有） |
| **访问控制** | MinIO 用户 | 建用户、启停用、重置 Secret Key、查看所属策略、一键创建（失败自动回滚） |
| | 访问策略 | 策略 JSON 增删改查、**附加/分离到指定用户** |
| **存储治理** | 版本控制 | 桶级版本化开关 + 对象历史版本浏览 / 恢复 / 删除 |
| | 生命周期规则 | 按前缀设置过期，支持非当前版本过期 / 存储层级转换 / 中止未完成分片 |
| **系统运维** | 操作审计 | 全量操作日志，支持查询与导出 |
| | 系统设置 | 上传上限、缓存上限与有效期 |
| | 关于本工具 | 版本、依赖、一键自检、反馈提交 |

> 界面体系: 桌面版与 Web 版共用「**暮橙 Emberline**」设计系统（第五轮视觉重构，
> 陶土暖橙主色 + 橙赭渐变品牌 + 奶油暖白画布 + 大圆角几何 + 浅色分层侧栏 + 胶囊选中导航 +
> 业务域分组导航 + 圆头线性 SVG 图标 + 「短线 + 眉题 + 大标题 + 描述」四层页头；仅亮色主题）。

---

## 快速开始

### Web 容器版（推荐服务器部署）

```bash
./deploy.sh          # 或 docker compose up -d --build
# 浏览器打开 http://服务器IP:6083, 初始账号 admin, 密码见 docker logs
```

详细部署/备份/反向代理说明见 [docs/02-环境部署教程](docs/02-环境部署教程.md) §2.3，功能使用见
[docs/03-功能使用说明](docs/03-功能使用说明.md)（viewer/admin 两角色）。

### 桌面版 · 从源码运行

源码采用 src 布局，推荐先以可编辑模式安装包，再用模块入口启动：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
python -m objstoreexplorer
```

也可直接跑根目录引导壳（自动把 `src/` 加入搜索路径，无需先安装）：

```powershell
python main.py
```

需要 **Python 3.13**（实测 3.14.6 亦可）与**含 tkinter 的 Python**（`python.org` 官方版含，Microsoft Store 版不含）。

检查 tkinter：
```powershell
python -c "import tkinter; print(tkinter.TkVersion)"
```

### 桌面版 · 用打包好的 exe

1. 下载 `ObjStoreExplorer-<version>-win-x64.zip`
2. 解压到**有写入权限**的目录（如 `D:\Tools\ObjStoreExplorer\`）
3. 双击 `ObjStoreExplorer.exe`
4. 顶部点「连接」，填 Endpoint / AK / SK

> ⚠ 不要解压到 `C:\Program Files\`——程序要在自己的目录下建 `data/`。
> ⚠ **立刻备份 `data/explorer.key`**：它丢失 = 库中所有已保存的 AK/SK 永久不可解密。

---

## 打包

```powershell
python -m pip install pyinstaller
python build.py
```

产物在 `dist/`：`ObjStoreExplorer/` 目录 + `ObjStoreExplorer-<version>-win-x64.zip` + `SHA256SUMS.txt`。

用 **onedir 而非 onefile**：单文件自解压壳是 360 / 火绒 / Defender 的高误报特征。**不要开 UPX**，压缩壳同样是杀软启发式的高触发特征。

版本号唯一真源是 `src/objstoreexplorer/config/settings.py` 的 `APP_VERSION`。

---

## 目录结构

```
.
├── src/objstoreexplorer/          # 包目录 = 发行名 objstoreexplorer
│   ├── __init__.py __main__.py main.py
│   ├── config/                    # 配置常量 + 异常体系 + 反馈配置模板
│   ├── core/                      # 业务核心（S3 客户端 / 加密 / 存储 / 管理器）
│   ├── services/                  # 服务编排（传输 / 同步 / 缓存 / 剪贴板 / 检索）
│   ├── ui/                        # 桌面版界面层（pages / widgets / windows）
│   ├── utils/                     # 工具层
│   ├── webapp/                    # Web 容器版（FastAPI 路由/模板/静态资源/账号库）
│   └── resources/icons/           # 189 个图标
├── main.py                        # 桌面版启动引导壳（PyInstaller 入口 / 源码直跑）
├── pyproject.toml                 # 构建配置（包名 / 入口点 / 包数据 / 动态版本）
├── requirements.txt               # 桌面版依赖清单（含 CVE 上界注释）
├── requirements-web.txt           # Web 版依赖（在桌面版之上追加）
├── requirements-dev.txt           # 测试依赖（pytest / httpx）
├── tests/                         # 冒烟测试（pytest）
├── .github/workflows/             # CI / Release 流水线
├── Dockerfile / docker-compose.yml / deploy.sh / deploy.bat   Web 版部署
├── build.py / build.spec          # 打包脚本与 PyInstaller 配置
├── docs/                          # 交付文档（5 篇编号文档 + 截图）
├── AGENTS.md                      # 开发流程规范
├── CHANGELOG.md                   # 变更记录
├── README.md
└── LICENSE.md                     # 许可协议
```

运行时数据落在程序目录下的 `data/`（自动创建，不入库、不进交付包）。

---

## 配置

| 环境变量 | 作用 |
|---|---|
| `OSE_DATA_DIR` | 重定向数据目录（多实例 / 便携 / 源码目录只读时用） |
| `WEB_ADMIN_PASSWORD` | Web 容器版：首次启动 admin 初始口令（不设则随机生成看日志） |
| `WEB_WORKERS` | Web 容器版：uvicorn worker 进程数（默认 1；会话/连接/任务已外置 SQLite，可调大，见 [docs/02-环境部署教程](docs/02-环境部署教程.md) §4.3） |

反馈平台配置：模板见 [`src/objstoreexplorer/config/feedback.yaml.example`](src/objstoreexplorer/config/feedback.yaml.example)，
需在线反馈时复制到 **`data/config/feedback.yaml`** 并填写真实值。未配置时反馈走离线模式，生成 zip 供手动导入。

---

## 安全

- 连接凭据（AK/SK）用 **Fernet 加密**后落盘，不存明文；Web 版口令 bcrypt 哈希、
  密钥文件原子创建与轮换，损坏时明确报错并给出修复步骤
- 端点校验拦下 CRLF 注入、shell 元字符、非 http(s) 协议
- 下载文件名做清洗（路径穿越 / Windows 非法字符 / 保留名 / NUL 截断）
- Web 版：viewer/admin 两角色权限矩阵逐路由校验、登录双层防爆破（IP 限速 +
  账号锁定）、防用户枚举、会话过期强制改密、安全响应头
- Web 版会话：HMAC-SHA256 签名 cookie（HttpOnly/SameSite，显式过期 + 常数时间比较）
  + SQLite 会话表**服务端吊销**——登出/停用/删除账号后旧 cookie 立即失效；
  S3 连接快照 AK/SK Fernet 加密落库
- 依赖全部声明版本上界并经 CVE 核查（见 [docs/04-安全设计说明](docs/04-安全设计说明.md) §7）

> 桌面版是纯本地应用，不监听端口；Web 版暴露 HTTP 端口，生产环境建议置于
> 反向代理 + HTTPS 之后。完整的风险评估、已修漏洞与攻击面实测见
> [docs/04-安全设计说明](docs/04-安全设计说明.md)（双形态统一口径）。

---

## 文档

完整文档在 [`docs/`](docs/README.md)，按 5 篇编号文档组织：

- [01 项目介绍与架构](docs/01-项目介绍与架构.md) — 双形态架构、功能总览、模块结构、技术栈、设计决策
- [02 环境部署教程](docs/02-环境部署教程.md) — 桌面版 exe/源码/打包、Web 版 Docker 部署、配置、故障排查
- [03 功能使用说明](docs/03-功能使用说明.md) — 桌面版与 Web 版各功能页面逐个讲
- [04 安全设计说明](docs/04-安全设计说明.md) — 桌面版本地攻击面 + Web 版服务端安全、依赖 CVE、权限矩阵
- [05 开发日志](docs/05-开发日志.md) — 版本迭代、缺陷修复、功能新增、架构改进、验证结论

文档索引与「按问题找文档」见 [docs/README.md](docs/README.md)。

---

## 常见问题

**双击 exe 没反应**
程序目录不可写。移到有写权限的位置，或设 `OSE_DATA_DIR`。源码运行可直接看报错。

**提示"无法解密：当前密钥与密文不匹配"**
`explorer.key` 与数据库不匹配。三种可能见 [docs/02-环境部署教程 §6.3](docs/02-环境部署教程.md)。

**连不上服务器 / 提示"端口必须是数字"**
Endpoint 要写 `主机:端口`。不写端口且不写协议时按 MinIO 默认补 **9000**（不是 80）。

**界面卡住**
看 `data/logs/app.log`。概览页会对每个桶做全量统计，桶多时首次加载确实需要时间。

---

## 许可与信息

- **开发者**：智维ITMSKY
- **版权**：Copyright (C) 2026 智维ITMSKY
- **官网**：http://www.itmsky.com
- **许可证**：[GNU Affero General Public License v3.0 or later](LICENSE.md)（AGPL-3.0-or-later）
- **SPDX-License-Identifier**：`AGPL-3.0-or-later`

> 本程序是自由软件：你可以遵照 GNU Affero 通用公共许可证第 3 版或后续版本的规定，重新分发和/或修改它。
>
> 本程序旨在广泛共享，但不提供任何担保；甚至不包含适销性和特定用途适用性的默示保证。详情请参阅 GNU Affero General Public License。
>
> 如果你修改本程序并通过网络向公众提供服务（SaaS、Web、API 等在线服务），你必须向该服务的使用者提供对应修改后的完整源代码。
>
> 你应当随本程序一同收到 GNU Affero General Public License 的副本；如未收到，详见 <https://www.gnu.org/licenses/>。
