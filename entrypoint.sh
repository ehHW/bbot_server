#!/bin/sh
# 容器启动入口：先执行数据库迁移，再运行主进程
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
	echo ">>> [entrypoint] 正在执行数据库迁移 ..."
	# 对已有初始表场景更稳健，避免首次接管旧库时触发 table already exists
	uv run python manage.py migrate --noinput --fake-initial
	echo ">>> [entrypoint] 迁移完成，启动应用 ..."
else
	echo ">>> [entrypoint] 跳过数据库迁移（RUN_MIGRATIONS=${RUN_MIGRATIONS:-0}）"
fi

exec "$@"
