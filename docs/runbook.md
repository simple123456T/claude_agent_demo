# 开发与运维手册（初始版）

## 本地检查

```bash
pytest backend/tests
curl http://127.0.0.1:8001/api/v1/health/live
curl http://127.0.0.1:8001/api/v1/health/ready
```

就绪检查中 PostgreSQL、Redis 为必需服务；Milvus 故障时状态为 `degraded`，用于提醒语义检索不可用。响应只包含服务状态、延迟和异常类别，不包含连接串。

## 配置与秘密

本地使用根目录 `.env`，该文件被 Git 忽略。`.env.example` 仅保留占位符。生产主密钥、OIDC secret、数据库密码和模型凭据应通过 Docker secret 或企业密钥系统注入，并制定轮换与备份分离方案。

## 服务故障

- PostgreSQL 不可用：停止接受依赖控制面的请求，检查连接、账号和磁盘。
- Redis 不可用：任务协调与缓存降级，不能把 Redis 中状态当作最终事实。
- Milvus 不可用：关闭向量增强，保留核心语义注册与确定性查询。
- 模型不可用：问数进入明确降级状态，不回退到自由 SQL 或外部公共模型。

## 尚待补充

OIDC 故障处理、数据库迁移回滚、PostgreSQL/MinIO 备份恢复、worker 卡死、Milvus 重建索引、告警阈值及目标 Linux Compose 演练。完成演练前本文不是正式生产 runbook。
