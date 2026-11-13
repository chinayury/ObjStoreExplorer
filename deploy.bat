@echo off
rem ============================================================
rem ObjStoreExplorer (MinIO/S3 对象存储管理) · 独立 Docker 部署脚本 (Windows)
rem 端口: 宿主 6083 -> 容器 8000
rem ============================================================
cd /d %~dp0
if not exist data mkdir data
docker compose up -d --build
echo.
echo ObjStoreExplorer: http://127.0.0.1:6083
echo 初始 admin 口令: docker compose logs objstoreexplorer-web (搜 "初始管理员")
