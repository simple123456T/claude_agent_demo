import { useCallback, useEffect, useState } from "react";
import {
  ApiOutlined,
  DatabaseOutlined,
  LineChartOutlined,
  SafetyCertificateOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Layout,
  Menu,
  Row,
  Space,
  Statistic,
  Tag,
  Timeline,
  Typography,
  message,
} from "antd";
import { fetchReadiness } from "./api/health";
import type { ReadinessResponse } from "./api/health";
import { ServiceHealthTable } from "./components/ServiceHealth";

const { Header, Sider, Content } = Layout;

const readinessLabels = {
  ready: { text: "核心服务就绪", color: "green" },
  degraded: { text: "核心可用，增强服务降级", color: "gold" },
  not_ready: { text: "核心服务未就绪", color: "red" },
};

export default function App() {
  const [health, setHealth] = useState<ReadinessResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [messageApi, contextHolder] = message.useMessage();

  const loadHealth = useCallback(async (showSuccess = false) => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await fetchReadiness();
      setHealth(result);
      if (showSuccess) messageApi.success("基础设施状态已刷新");
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "无法连接后端服务");
    } finally {
      setLoading(false);
    }
  }, [messageApi]);

  useEffect(() => {
    const controller = new AbortController();
    fetchReadiness(controller.signal)
      .then(setHealth)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(error instanceof Error ? error.message : "无法连接后端服务");
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const services = Object.values(health?.services ?? {});
  const upCount = services.filter((service) => service.status === "up").length;
  const statusMeta = readinessLabels[health?.status ?? "not_ready"];

  return (
    <Layout className="app-shell">
      {contextHolder}
      <Sider breakpoint="lg" collapsedWidth="0" width={248} className="app-sider">
        <div className="brand">
          <div className="brand-mark"><LineChartOutlined /></div>
          <div><strong>DataAgent</strong><span>企业智能问数</span></div>
        </div>
        <div className="workspace-label">默认工作区</div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={["overview"]}
          items={[
            { key: "overview", icon: <ApiOutlined />, label: "系统概览" },
            { key: "semantic", icon: <DatabaseOutlined />, label: "语义内核 · 建设中", disabled: true },
            { key: "governance", icon: <SafetyCertificateOutlined />, label: "权限治理 · 待接入", disabled: true },
          ]}
        />
        <div className="sider-foot">内网部署 · 数据不出域<br />v0.1.0 工程基线</div>
      </Sider>
      <Layout>
        <Header className="app-header">
          <div><Typography.Text strong>系统概览</Typography.Text><span className="header-divider" />企业数据智能平台</div>
          <Tag color="blue">开发环境</Tag>
        </Header>
        <Content className="app-content">
          <section className="page-heading">
            <div>
              <Typography.Title level={2}>可信问数，从治理开始</Typography.Title>
              <Typography.Paragraph>
                统一指标口径、权限策略与数据证据，让每一次分析都可解释、可复现、可审计。
              </Typography.Paragraph>
            </div>
            <Button icon={<SyncOutlined spin={loading} />} onClick={() => void loadHealth(true)} loading={loading}>
              刷新状态
            </Button>
          </section>

          {loadError && (
            <Alert
              className="status-alert"
              type="error"
              showIcon
              message="后端暂不可用"
              description={`${loadError}。请确认 FastAPI 已在 127.0.0.1:8001 启动。`}
            />
          )}

          <Row gutter={[20, 20]} className="metric-row">
            <Col xs={24} sm={8}><Card><Statistic title="在线基础设施" value={upCount} suffix={`/ ${services.length || 3}`} /></Card></Col>
            <Col xs={24} sm={8}><Card><Statistic title="当前交付阶段" value="01" suffix="/ 05" /></Card></Col>
            <Col xs={24} sm={8}><Card className="status-card"><span className="stat-label">平台状态</span><Tag color={statusMeta.color}>{statusMeta.text}</Tag><p>状态来自实时后端检查，非静态演示数据</p></Card></Col>
          </Row>

          <Row gutter={[20, 20]}>
            <Col xs={24} xl={15}>
              <Card title="基础设施健康" extra={<Typography.Text type="secondary">实时探测</Typography.Text>}>
                {health ? <ServiceHealthTable services={health.services} /> : <Alert type="info" showIcon message="等待后端健康数据" />}
              </Card>
            </Col>
            <Col xs={24} xl={9}>
              <Card title="产品建设路线">
                <Timeline
                  items={[
                    { color: "blue", children: <><b>控制面与语义内核</b><p>配置、健康检查、QuerySpec、权限编译</p></> },
                    { color: "gray", children: <><b>数据与语义层</b><p>四类数据源、质量规则、真实方言验证</p></> },
                    { color: "gray", children: <><b>内网模型与分析</b><p>DeepSeek / Qwen、多轮问数、答案证据卡</p></> },
                    { color: "gray", children: <><b>报表与质量运营</b><p>仪表盘、订阅、评测与 badcase 闭环</p></> },
                    { color: "gray", children: <><b>生产准入</b><p>安全、负载、故障恢复与部署验收</p></> },
                  ]}
                />
              </Card>
            </Col>
          </Row>

          <Card className="principle-card">
            <Space align="start" size={16}>
              <SafetyCertificateOutlined className="principle-icon" />
              <div><Typography.Title level={4}>核心安全边界</Typography.Title><Typography.Paragraph>模型只生成受限 QuerySpec，不能直接提交 SQL。权限在查询编译前生效，最终 SQL 还需经过独立只读复核。数据库只读账号是第二道防线，而不是权限系统的替代品。</Typography.Paragraph></div>
            </Space>
          </Card>
        </Content>
      </Layout>
    </Layout>
  );
}
