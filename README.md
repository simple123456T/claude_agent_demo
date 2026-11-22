# DataAgent 企业智能问数

面向企业内网的可治理智能问数平台。后端使用 Python/FastAPI，前端使用 React/TypeScript，模型通过企业已有的 OpenAI 兼容接口接入 DeepSeek、Qwen 等内网模型。

> 当前处于企业控制面与语义查询内核建设阶段，尚不是可投入生产的完整版本。详细范围与验收门槛见 [实施计划](docs/implementation-plan.md)。

## 核心设计

- 模型生成受限 QuerySpec，不直接生成可执行 SQL。
- 后端根据版本化语义模型确定性地编译 PostgreSQL、MySQL、ClickHouse SQL。
- 行权限在 JOIN/聚合前注入；列权限覆盖查询的所有引用位置。
- PostgreSQL 为控制面事实源，Milvus 提供可选语义检索，Redis 用于短期协调与缓存。
- 所有模型与数据流量保持在内网，仓库不保存真实凭据和业务数据。

## 当前已实现

- 本地配置加载与秘密字段封装。
- FastAPI 存活/就绪检查，分别检查 PostgreSQL、Redis、Milvus。
- QuerySpec、单数据集语义注册表、权限优先的 SQLGlot 编译基础；编译后 SQL 只读安全复核。
- 控制面：Alembic 迁移、OIDC Bearer 令牌校验、用户自动建档、工作区与成员 RBAC、只能追加的审计日志。
- React 工程与基础设施状态页面。

尚未实现浏览器登录会话、真实数据源执行、模型调用、语义管理、仪表盘和报表；不得据此宣称产品已经上线。进度见 [开发状态](docs/development-status.md)。

## 本地启动

前置条件：Python 3.12+、Node.js 20+，以及可访问的 PostgreSQL、Redis、Milvus。

```bash
cp .env.example .env
# 编辑 .env，填入本机服务配置

python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -e "./backend[dev]"
alembic -c backend/alembic.ini upgrade head
uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8001
```

另开终端：

```bash
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`。后端 OpenAPI 文档位于 `http://127.0.0.1:8001/docs`。本机开发默认使用 8001，避免与其他本地服务冲突；容器内后端仍使用 8000。

## 测试

```bash
pytest backend/tests          # 含 PostgreSQL 集成测试（临时 schema，结束后删除）
cd frontend && npm run build
```

数据库不可达时，集成测试会被明确标记为 skipped，而不是假装通过。Docker/真实三方言数据库集成测试需在具备 Docker 的 Linux 环境执行；当前机器未安装 Docker。

## 版本管理

远程仓库：`https://github.com/simple123456T/claude_agent_demo.git`。日常开发使用功能分支，验证后提交；`.env`、上传数据、导出文件与密钥不会进入版本库。
