# ── 后端镜像 ────────────────────────────────────────────────
# 基于已预拉取的 Python 3.14 slim 构建，避免再依赖 ghcr 拉取 uv 镜像
FROM python:3.14-slim

WORKDIR /app

# 国内镜像加速。uv 使用 UV_INDEX_URL，pip 安装 uv 时使用 PIP_INDEX_URL。
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
     UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
     UV_LINK_MODE=copy \
     PATH="/app/.venv/bin:$PATH"

# 直接通过 pip 安装 uv，避免 COPY --from=ghcr.io/... 额外访问 ghcr
RUN pip install --no-cache-dir uv

# 先只复制依赖描述文件，利用 Docker 层缓存
COPY pyproject.toml uv.lock ./

# 安装生产依赖（不含 dev），--frozen 保证与 lock 文件一致
RUN uv sync --frozen --no-dev

# 复制项目源码
COPY . .

# 复制并设置启动入口
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# uvicorn 监听端口
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

# 默认命令：启动 ASGI 服务（docker-compose 中 celery 服务会覆盖此命令）
CMD ["uv", "run", "uvicorn", "hyself_server.asgi:application", \
     "--lifespan", "off", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
