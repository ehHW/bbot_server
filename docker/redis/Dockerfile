# ── Redis 7 独立镜像 ──────────────────────────────────────────
FROM redis:7-alpine

# 注入自定义配置
COPY redis.conf /usr/local/etc/redis/redis.conf

CMD ["redis-server", "/usr/local/etc/redis/redis.conf"]
