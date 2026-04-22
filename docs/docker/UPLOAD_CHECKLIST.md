# ============================================================

# 上传到服务器的文件清单

# ============================================================

## 本地准备完成的文件

```text
hyself_server/
├── .env.docker
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── docker/
│   ├── mysql/
│   │   ├── Dockerfile
│   │   └── my.cnf
│   └── redis/
│       ├── Dockerfile
│       └── redis.conf
├── nginx.server.conf
├── hyself_backend_src.tar.gz
└── docs/docker/
    ├── DOCKER_DEPLOY.md
    └── BUILD_COMMANDS.md
```

## 上传步骤

```bash
scp hyself_backend_src.tar.gz user@www.hyself.top:/srv/www.hyself.top/
scp .env.docker user@www.hyself.top:/srv/www.hyself.top/
scp nginx.server.conf user@www.hyself.top:/etc/nginx/conf.d/hyself.conf
```

## 服务器执行步骤

```bash
ssh user@www.hyself.top
cd /srv/www.hyself.top
tar -xzf hyself_backend_src.tar.gz
docker compose build --no-cache
docker compose up -d
nginx -t && nginx -s reload
```

如果是上传已导出的镜像包 `hyself_images.tar.gz`，则执行：

```bash
ssh user@www.hyself.top
cd /srv/www.hyself.top
tar -xzf hyself_images.tar.gz
docker load -i hyself_images.tar
docker compose up -d
nginx -t && nginx -s reload
```
