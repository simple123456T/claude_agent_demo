# 容器部署骨架

`compose.yaml` 固定 PostgreSQL 19、Redis 7、Milvus 3.0.5，并提供后端与前端镜像。基础设施使用 `infra` profile。

```bash
# 在干净 Linux Docker 主机上，先配置根目录 .env，然后：
docker compose --profile infra config
docker compose --profile infra up --build -d
```

访问 `http://127.0.0.1:8080`。Compose 内部会覆盖本地回环地址，将后端连接到容器网络中的 postgres、redis、milvus。

当前开发机已经运行独立 PostgreSQL/Redis/Milvus 时，不要同时启动 `infra` profile；使用本地虚拟环境和 Vite 开发服务器即可。

本配置尚未在本机运行（未安装 Docker）。生产前还需完成 HTTPS、容器资源限额、离线镜像、秘密管理、备份恢复、监控和故障演练。
