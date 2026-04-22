# ── MySQL 8.4 独立镜像 ────────────────────────────────────────
FROM mysql:8.4

# 注入自定义配置（utf8mb4 + 时区 + 连接数等）
COPY my.cnf /etc/mysql/conf.d/custom.cnf
