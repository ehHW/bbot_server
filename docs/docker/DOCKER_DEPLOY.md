# ============================================================

# Hyself 后端 Docker 部署指南（服务器端）

# ============================================================

## 前置条件

- 服务器已安装 Docker 和 docker compose
- Nginx 已配置（/etc/nginx/conf.d/hyself.conf）
- SSL 证书已放在 /certs/hyself.top_nginx/

## 1. 解压源码包

```bash
cd /srv/www.hyself.top
tar -xzf hyself_backend_src.tar.gz
```

## 2. 创建环境配置

```bash
cat .env.docker
nano .env.docker
```

当前默认数据库密码已改为 `www.hyself.top.db.030827`。

## 3. 构建 Docker 镜像

这三个基础镜像你已经单独拉取过：

- mysql:8.4
- python:3.14-slim
- redis:7-alpine

因此现在构建主要消耗在 Python 依赖安装，不会再重复拉这三个基础镜像。

```bash
docker compose build --no-cache
docker images | grep hyself_server
```

## 4. 一键启动所有服务

```bash
docker compose up -d
docker compose logs -f
docker ps
```

`Dockerfile` 不需要因为服务器宿主机目录改成 `/srv/www.hyself.top` 而修改。

原因是：

- `/srv/www.hyself.top` 是宿主机目录
- `/app` 是容器内工作目录

两者互不冲突。真正依赖宿主机路径的是 `docker-compose.yml` 的卷挂载和 `nginx.server.conf` 的 `alias`。

上传文件目录统一使用 `/srv/www.hyself.top/hyself_server/uploads`。

## 5. 验证服务

```bash
docker exec hyself_redis redis-cli ping
docker exec hyself_db mysql -u hyself -p hyself_db
```

## 6. 初始化数据库

服务启动后，backend 容器会自动执行数据库迁移（通过 entrypoint.sh 和 `RUN_MIGRATIONS=1` 环境变量）。接下来需要手动初始化权限、角色和默认用户。

### 步骤 1：进入 backend 容器

```bash
docker compose exec backend bash
```

### 步骤 2：运行初始化脚本

```bash
python init_db.py
```

该脚本会创建：

- **权限集合**：同步项目中定义的所有权限（来自 user.signals）
- **角色**：
  - 超级管理员（所有权限）
  - 系统管理员（除了 review_all_messages）
  - 普通用户（基础权限）
- **默认用户**：
  - `superadmin` / `sa0000`（超级管理员）
  - `admin` / `admin1111`（系统管理员）
  - `user01` ~ `user05` / `111u111` ~ `555u555`（普通用户）

**重要**：init_db.py 是幂等脚本，可以安全地重复运行，既有用户会被更新而不会产生重复。

### 步骤 3：验证初始化结果

```bash
python manage.py shell
```

在 Django shell 中查询：

```python
from user.models import User, Role, Permission

# 查看所有用户
User.objects.all()

# 查看所有角色
Role.objects.all()

# 查看权限总数
Permission.objects.count()

# 查看特定用户的角色和权限
user = User.objects.get(username='superadmin')
user.roles.all()
user.permissions.all()
```

完成后退出 shell：

```python
exit()
```

## 7. 常用命令

```bash
docker compose logs -f backend
docker compose logs -f celery
docker compose logs -f db
docker compose down
docker compose restart backend
docker exec -it hyself_backend bash
uv run python manage.py createsuperuser
```

## 8. 故障排查

| 问题           | 解决方案                                           |
| -------------- | -------------------------------------------------- |
| uv sync 很慢   | Dockerfile 已改为阿里云镜像，并补充了 UV_INDEX_URL |
| 端口冲突       | 修改 docker-compose.yml 的 ports 映射              |
| 数据库连接失败 | 查看 `docker compose logs db`，等待健康检查通过    |
