# ObjStoreExplorer Web 容器版
#
# 一键部署:
#     docker compose up -d --build
#     浏览器打开 http://localhost:6083 (compose 映射宿主端口, 见 docker-compose.yml)
#
# Web 版是标准 HTTP 服务 (FastAPI + uvicorn), 镜像内无任何 GUI/X11 组件。
# 源码采用 src 布局: 包 objstoreexplorer 位于 src/objstoreexplorer/, 经 pip 安装后
# 以 objstoreexplorer.webapp.main:app 作为 uvicorn 入口。
# v0.1.0 第二轮起会话/连接/任务状态外置 SQLite, 支持多 worker:
#     WEB_WORKERS 环境变量控制进程数 (默认 1, 调大前提见 README "多 worker 说明")。
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app

# 可选: 构建时指定 pip 镜像源 (国内服务器 compose build args 已传清华源, 海外留空走默认)
ARG PIP_INDEX_URL=""
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

# 先装依赖再拷代码, 利用层缓存 (pywin32 带 win32 marker, Linux 下自动跳过)
COPY requirements-web.txt requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-web.txt

# 拷源码并安装包 (--no-deps: 依赖已由 requirements 安装, 避免重复解析版本)
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

# 容器内端口 (compose 映射宿主 6083 -> 容器 8000)
EXPOSE 8000

# OSE_DATA_DIR: 数据目录 (账号库/加密连接/日志/上传临时目录), compose 挂载 ./data:/app/data
# WEB_ADMIN_PASSWORD: 可选, 首次启动的 admin 初始密码 (未设置则随机生成, 见 docker logs)
# WEB_WORKERS: uvicorn worker 进程数 (默认 1; 会话/连接/任务已外置 SQLite, 可调大)
ENV OSE_DATA_DIR=/app/data \
    WEB_ADMIN_PASSWORD="" \
    WEB_WORKERS="1"

# sh -c + exec: 环境变量生效且 uvicorn 替换为 1 号进程 (信号正确透传, 容器可干净停止)
CMD ["sh", "-c", "exec uvicorn objstoreexplorer.webapp.main:app --host 0.0.0.0 --port 8000 --workers \"${WEB_WORKERS:-1}\""]

# 健康检查: /api/health 返回 200 即视为健康 (HTTPError/URLError 会以非零码退出)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
