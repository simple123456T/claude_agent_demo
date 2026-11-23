# DataAgent 企业智能问数

面向企业内网的可治理智能问数平台。后端使用 Python/FastAPI，前端使用 React/TypeScript，模型通过企业已有的 OpenAI 兼容接口接入 DeepSeek、Qwen 等内网模型。

> 当前已经有一条**可操作的问数链路**（登录 → 提问或手动构建查询 → 图表 / 表格 / 查询依据），但仍不是可投入生产的完整版本：真实企业数据源、SSO 登录、语义管理、仪表盘与报表尚未完成。详细范围与验收门槛见 [实施计划](docs/implementation-plan.md)。

## 核心设计

- 模型生成受限 QuerySpec，不直接生成可执行 SQL。
- 后端根据版本化语义模型确定性地编译 PostgreSQL、MySQL、ClickHouse SQL。
- 行权限在 JOIN/聚合前注入；列权限覆盖查询的所有引用位置。
- PostgreSQL 为控制面事实源，Milvus 提供可选语义检索，Redis 用于短期协调与缓存。
- 所有模型与数据流量保持在内网，仓库不保存真实凭据和业务数据。

## 当前已实现

**可以直接用的（在浏览器里）**

- 开发身份登录（管理员 / 分析师 / 查看者，权限各不相同；仅限本机，接入 SSO 后自动停用）。
- **智能问数页**：快捷查询、手动构建（指标 / 维度 / 过滤 / 排序 / 行数，过滤值读取真实取值）、自然语言提问（需配置内网模型）。
- 结果以**摘要 + 图表 + 表格 + 查询依据**呈现：折线 / 柱状 / 数字卡自动选择，多指标分图绘制（不做双轴），导出 CSV（含公式注入防护），依据里可看口径、过滤条件、假设和对应 SQL。
- 摘要只由返回的数据生成，不经过模型；是否被截断由数据库实际判断（多取 1 行），不靠猜。

**后端能力**

- 受限 QuerySpec → 权限优先的确定性编译 → 独立只读校验 → 只读事务 + 语句超时执行；未配置模型时手动查询照常可用。
- 内网 OpenAI 兼容模型客户端与规划器：输出必须通过结构化校验，无效时只修复一次，仍无效就明确报错而不是猜测。
- 控制面：Alembic 迁移、OIDC Bearer 令牌校验、工作区 RBAC、只能追加的审计日志（含每次查询的问题、结构化查询、行数与耗时，**不含结果数据**）。
- 演示数据：`python -m app.demo.seed` 生成 6000+ 条销售订单和演示工作区。

**尚未实现 / 未验证**：真实企业数据源接入、浏览器端 SSO 登录（授权码 + PKCE）、语义管理界面、多轮对话、仪表盘与报表、定时任务。**自然语言提问尚未用真实内网模型验证**，只用模拟模型测试过完整流程。进度见 [开发状态](docs/development-status.md)。

## 本地启动

前置条件：Python 3.12+、Node.js 20+，以及可访问的 PostgreSQL、Redis、Milvus。

```bash
cp .env.example .env
# 编辑 .env，填入本机服务配置

python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -e "./backend[dev]"
alembic -c backend/alembic.ini upgrade head

# 本机开发：在 .env 中设置 DEV_AUTH_ENABLED=true，然后生成演示数据和演示工作区
python -m app.demo.seed          # 在 backend/ 下执行，或设置 PYTHONPATH=backend
uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8001
```

另开终端：

```bash
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`，选择一个开发身份登录即可提问。开发登录的令牌签名密钥保存在后端进程内存中，**重启后端会让已登录的令牌失效**，页面会回到登录页。

要启用自然语言提问，在 `.env` 中填写 `MODEL_BASE_URL`（内网 OpenAI 兼容地址，如 `http://llm.internal/v1`）、`MODEL_NAME` 和 `MODEL_API_KEY`，然后重启后端。

后端 OpenAPI 文档位于 `http://127.0.0.1:8001/docs`。本机开发默认使用 8001，避免与其他本地服务冲突；容器内后端仍使用 8000。

## 测试

```bash
pytest backend/tests          # 含 PostgreSQL 集成测试（临时 schema，结束后删除）
cd frontend && npm run build  # TypeScript 检查 + 生产构建
```

数据库不可达时，集成测试会被明确标记为 skipped，而不是假装通过。Docker/真实三方言数据库集成测试需在具备 Docker 的 Linux 环境执行；当前机器未安装 Docker。

## 版本管理

远程仓库：`https://github.com/simple123456T/claude_agent_demo.git`。只使用 `main` 一个分支，提交前先跑通测试；`.env`、上传数据、导出文件与密钥不会进入版本库。
