# ============================================================

# Docker 镜像构建与压缩命令

# ============================================================

## PowerShell

```powershell
cd D:\work\SolBot\hyself_server

# 指定镜像版本（推荐统一在 .env.docker 里维护同一个值）
$env:IMAGE_TAG = "1.0.0"

docker compose build --no-cache

docker images | Select-String "hyself_server"

docker save hyself_server-backend:$env:IMAGE_TAG hyself_server-celery:$env:IMAGE_TAG hyself_server-db:$env:IMAGE_TAG hyself_server-redis:$env:IMAGE_TAG -o hyself_images.tar

# 有 7-Zip 时优先输出 .tar.gz
& 'C:\Program Files\7-Zip\7z.exe' a -tgzip hyself_images.tar.gz hyself_images.tar

# 没有 7-Zip 时改用 zip
Compress-Archive -Path hyself_images.tar -DestinationPath hyself_images.tar.zip -Force
```

## 服务器加载

```bash
# 如需临时切版本
export IMAGE_TAG=1.0.0

tar -xzf hyself_images.tar.gz
docker load -i hyself_images.tar
docker compose up -d
```
