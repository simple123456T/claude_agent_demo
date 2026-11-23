# 开发与运维手册（初始版）

## 本地检查

```bash
pytest backend/tests
curl http://127.0.0.1:8001/api/v1/health/live
curl http://127.0.0.1:8001/api/v1/health/ready
```

就绪检查中 PostgreSQL、Redis 为必需服务；Milvus 故障时状态为 `degraded`，用于提醒语义检索不可用。响应只包含服务状态、延迟和异常类别，不包含连接串。

## 控制面数据库迁移

```bash
alembic -c backend/alembic.ini upgrade head     # 创建/升级 CONTROL_PLANE_SCHEMA（默认 datagent）
alembic -c backend/alembic.ini current          # 查看当前版本
alembic -c backend/alembic.ini downgrade -1     # 回滚一个版本（会删除该版本的表和数据）
```

连接信息来自 `.env` 中的 `DATABASE_URL`。集成测试使用 `datagent_test_<随机>` 临时 schema，结束后自动删除，不会触碰 `datagent`。

`audit_events` 由触发器保证只能追加。超级用户或表所有者仍可禁用触发器，所以生产环境应用必须使用**非表所有者**的数据库角色连接，迁移使用单独的所有者角色执行。

## 身份认证

受保护接口要求 `Authorization: Bearer <access_token>`。配置项：

| 变量 | 说明 |
|---|---|
| `OIDC_ISSUER` | IdP issuer，必须与令牌 `iss` 完全一致 |
| `OIDC_AUDIENCE` | 令牌 `aud`；为空时使用 `OIDC_CLIENT_ID` |
| `OIDC_JWKS_URL` | 可选；为空时从 issuer 的 openid-configuration 发现，且必须与 issuer 同主机 |
| `OIDC_BOOTSTRAP_ADMIN_SUBJECTS` | 首次登录即成为组织管理员的 `sub` 列表，用于初始化 |

未配置时接口返回 503。IdP 不可达时返回 503「Identity provider unavailable」；令牌无效返回 401，响应不包含具体失败原因（原因记录在服务端日志）。生产环境（`APP_ENV=production`）只接受 HTTPS 的 IdP 地址。

## 配置与秘密

本地使用根目录 `.env`，该文件被 Git 忽略。`.env.example` 仅保留占位符。生产主密钥、OIDC secret、数据库密码和模型凭据应通过 Docker secret 或企业密钥系统注入，并制定轮换与备份分离方案。

## 演示数据与开发登录

仅用于本机开发。`APP_ENV=production` 时 `python -m app.demo.seed` 会拒绝运行，应用也会拒绝带着 `DEV_AUTH_ENABLED=true` 启动。

```bash
# .env: DEV_AUTH_ENABLED=true
PYTHONPATH=backend python -m app.demo.seed     # 重建演示数据（可重复执行）
```

开发登录只在三个条件同时满足时生效：`APP_ENV` 不是 production、请求来自本机回环地址、**没有配置** `OIDC_ISSUER`。配置真实 SSO 后自动停用。只允许 `dev-admin` / `dev-analyst` / `dev-viewer` 三个预设身份，每次登录写入审计。

## 模型接入

在 `.env` 中设置 `MODEL_BASE_URL`、`MODEL_NAME`、`MODEL_API_KEY` 后重启后端。接口需兼容 OpenAI `chat/completions`。

- 请求使用 `temperature=0` 和 JSON 模式；如果端点不支持 `response_format`，客户端会自动退回普通模式重试一次。仍想关闭可设 `MODEL_JSON_MODE=false`。
- 模型输出必须通过结构化校验；无效时带着具体错误让模型重试**一次**，仍无效返回 `plan_failed`，**不会**回退到自由 SQL。
- 模型不可用返回 502（`model_unavailable`）；未配置返回 503（`model_not_configured`），手动构建不受影响。
- 发给模型的内容：问题、该用户**有权看到**的指标 / 维度清单，以及低基数维度的取值（如区域名称）。**不会**发送查询结果。

## 查询执行

- 每条查询在只读事务内执行，语句超时由 `QUERY_TIMEOUT_MS` 控制（默认 15 秒），超时返回 504。
- 最多返回 500 行。实际多取 1 行来判断数据库是否还有更多数据；页面展示的 SQL 是不含这 1 行探测的版本。
- 审计事件 `query.run` 记录问题、结构化查询、行数、耗时和语义版本，**不记录结果数据**；失败（超时、模型错误等）以 `outcome=failure` 单独留痕。

## 服务故障

- PostgreSQL 不可用：停止接受依赖控制面的请求，检查连接、账号和磁盘。
- Redis 不可用：任务协调与缓存降级，不能把 Redis 中状态当作最终事实。
- Milvus 不可用：关闭向量增强，保留核心语义注册与确定性查询。
- 模型不可用：问数进入明确降级状态，不回退到自由 SQL 或外部公共模型。

## 尚待补充

OIDC 浏览器会话与故障处理、PostgreSQL/MinIO 备份恢复、worker 卡死、Milvus 重建索引、告警阈值及目标 Linux Compose 演练。完成演练前本文不是正式生产 runbook。
