import { useCallback, useEffect, useState } from "react";
import { SyncOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Row, Statistic, Tag, Timeline, Typography, message } from "antd";
import { fetchReadiness } from "../api/health";
import type { ReadinessResponse } from "../api/health";
import { ServiceHealthTable } from "../components/ServiceHealth";

const readinessLabels = {
  ready: { text: "核心服务就绪", color: "green" },
  degraded: { text: "核心可用，增强服务降级", color: "gold" },
  not_ready: { text: "核心服务未就绪", color: "red" },
};

export function OverviewPage() {
  const [health, setHealth] = useState<ReadinessResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [messageApi, contextHolder] = message.useMessage();

  const loadHealth = useCallback(
    async (showSuccess = false) => {
      setLoading(true);
      setLoadError(null);
      try {
        setHealth(await fetchReadiness());
        if (showSuccess) messageApi.success("基础设施状态已刷新");
      } catch (error) {
        setLoadError(error instanceof Error ? error.message : "无法连接后端服务");
      } finally {
        setLoading(false);
      }
    },
    [messageApi],
  );

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
    <>
      {contextHolder}
      <section className="page-heading">
        <div>
          <Typography.Title level={2}>系统概览</Typography.Title>
          <Typography.Paragraph>基础设施的实时状态，来自后端健康检查，非静态演示数据。</Typography.Paragraph>
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
        <Col xs={24} sm={8}>
          <Card>
            <Statistic title="在线基础设施" value={upCount} suffix={`/ ${services.length || 3}`} />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic title="当前交付阶段" value="01" suffix="/ 05" />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card className="status-card">
            <span className="stat-label">平台状态</span>
            <Tag color={statusMeta.color}>{statusMeta.text}</Tag>
          </Card>
        </Col>
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
                { color: "blue", children: <><b>控制面与问数链路</b><p>登录、权限、审计、受限查询、图表与证据（进行中）</p></> },
                { color: "gray", children: <><b>数据与语义层</b><p>真实数据源、语义管理、数据质量规则</p></> },
                { color: "gray", children: <><b>内网模型与分析</b><p>DeepSeek / Qwen、多轮问数、归因分析</p></> },
                { color: "gray", children: <><b>报表与质量运营</b><p>仪表盘、订阅、评测与 badcase 闭环</p></> },
                { color: "gray", children: <><b>生产准入</b><p>安全、负载、故障恢复与部署验收</p></> },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </>
  );
}
