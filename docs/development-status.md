# 开发状态

## 阶段 0–1a：工程基线（已合入 main）

- [x] 产品与实施计划纳入版本库，本地秘密与示例配置分离
- [x] PostgreSQL / Redis / Milvus 实际连接验证
- [x] QuerySpec 编译、权限优先行过滤、只读 SQL 复核
- [x] 前端构建、Chrome 桌面/移动视口验证

## 阶段 1b：企业控制面（本分支）

- [x] Alembic 迁移：`users`、`workspaces`、`workspace_members`、`audit_events`
- [x] 审计表仅可追加：数据库触发器拒绝 UPDATE / DELETE / TRUNCATE
- [x] OIDC 访问令牌校验：签名（JWKS）、issuer、audience、过期；拒绝 `alg=none` 与 HS256 算法混淆
- [x] 未配置 OIDC 时受保护接口返回 503（fail closed），不会退化为匿名访问
- [x] 首次请求自动建档用户；`OIDC_BOOTSTRAP_ADMIN_SUBJECTS` 引导组织管理员
- [x] 工作区 RBAC：查看者 < 分析师 < Steward < 工作区管理员；组织管理员只有治理权限，不自动获得数据权限
- [x] 不可见工作区返回 404，所有越权尝试写入审计
- [x] 保护最后一名工作区管理员；成员变更按工作区加行锁串行化
- [x] 请求 ID 贯穿响应头与审计记录
- [x] 66 个测试通过，其中 16 个在真实 PostgreSQL 的临时 schema 中运行并在结束后删除
- [x] 已在开发库执行迁移，`datagent` schema 版本为 `0001_control_plane`

## 尚未完成（阶段 1 剩余）

- 浏览器登录流程：OIDC Authorization Code + PKCE、HttpOnly 会话 Cookie、CSRF 防护、登出。当前只校验 API 的 Bearer 令牌，**前端还没有登录界面**。
- OIDC 用户组 → 角色映射、用户停用接口。
- 控制面 PostgreSQL RLS（第二道隔离）、应用使用非表所有者的受限数据库角色。
- 任务事实源（状态机、幂等键、租约、outbox）、MinIO 私有存储、可观测性。
- 真实企业 IdP 联调：需要你提供测试环境的 issuer、client 和测试账号。

## 后续顺序

1. 完成阶段 1 剩余项（登录会话、RLS、任务事实源）。
2. 扩展多关系语义模型、真实数据连接与查询执行。
3. 接入内网模型、证据卡、多轮分析。
4. 完成报表、评测运营和生产验收。
