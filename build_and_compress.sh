#!/bin/bash
# ============================================================
# Docker 镜像本地构建 & 压缩脚本（Bash）
# 用途：构建所有镜像，压缩后上传到服务器
# ============================================================

set -e

IMAGE_TAG="${IMAGE_TAG:-1.0.0}"

echo "========================================"
echo "Hyself Docker 镜像构建 & 压缩"
echo "========================================"
echo "Using image tag: ${IMAGE_TAG}"

# 1. 进入项目目录
PROJECT_DIR="/path/to/hyself_server"  # 修改为实际路径
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ 项目目录不存在: $PROJECT_DIR"
    exit 1
fi
cd "$PROJECT_DIR"
echo "✓ 进入项目目录: $PROJECT_DIR"

# 2. 检查 docker compose
echo ""
echo "正在检查 docker compose..."
docker compose version > /dev/null 2>&1 || {
    echo "❌ Docker Compose 不可用"
    exit 1
}
echo "✓ Docker Compose 已就绪"

# 3. 构建镜像
echo ""
echo "正在构建镜像（可能需要几分钟）..."
docker compose build --no-cache || {
    echo "❌ 构建失败，请检查网络连接或错误信息"
    exit 1
}
echo "✓ 镜像构建成功"

# 4. 列出镜像
echo ""
echo "已构建的镜像："
docker images | grep hyself_server

# 5. 保存镜像为 tar
echo ""
echo "正在保存镜像到 tar 文件..."
docker save hyself_server-backend:${IMAGE_TAG} hyself_server-celery:${IMAGE_TAG} hyself_server-db:${IMAGE_TAG} hyself_server-redis:${IMAGE_TAG} -o hyself_images.tar
echo "✓ 镜像已保存到 hyself_images.tar"

# 6. 压缩
echo ""
echo "正在压缩（gzip）..."
gzip -f hyself_images.tar
echo "✓ 压缩完成"

# 7. 显示最终文件信息
echo ""
echo "========================================"
echo "构建 & 压缩完成！"
echo "========================================"
ls -lh hyself_images.tar.gz | awk '{print "文件大小: " $5}'
echo ""
echo "后续步骤："
echo "1. 上传到服务器:"
echo "   scp hyself_images.tar.gz user@www.hyself.top:/srv/www.hyself.top/"
echo ""
echo "2. 服务器上加载镜像:"
echo "   docker load -i hyself_images.tar.gz"
echo ""
echo "3. 启动服务:"
echo "   cd /srv/www.hyself.top"
echo "   docker compose up -d"
echo ""
