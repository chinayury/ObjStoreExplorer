#!/usr/bin/env bash
# ============================================================
# ObjStoreExplorer (MinIO/S3 对象存储管理) · 独立 Docker 部署脚本
# 用法:  ./deploy.sh
#        docker compose logs -f objstoreexplorer-web   跟踪日志
#        docker compose down                           停止
# 端口:  宿主 6083 -> 容器 8000 (改 docker-compose.yml ports 左半边)
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p data
# 非 root 容器 (uid 10001) 写 data 卷: 首次部署或从 root 容器迁移时修正属主
chown -R 10001:10001 data 2>/dev/null || true
docker compose up -d --build

echo
echo "=============================================="
echo " ObjStoreExplorer 已启动:  http://127.0.0.1:6083"
echo " 初始 admin 口令:  docker compose logs objstoreexplorer-web | grep -A2 '初始管理员'"
echo "                   (未设 WEB_ADMIN_PASSWORD 时随机生成;"
echo "                    也可在 compose 的 environment 里指定后重建)"
echo " 数据目录: ./data (账号库/加密连接/日志) — 备份即打包"
echo "=============================================="
