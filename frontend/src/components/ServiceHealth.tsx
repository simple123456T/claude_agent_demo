import { Badge, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { ServiceHealth } from "../api/health";

const serviceNames: Record<string, string> = {
  postgresql: "PostgreSQL",
  redis: "Redis",
  milvus: "Milvus",
};

interface ServiceRow extends ServiceHealth {
  name: string;
}

export function ServiceHealthTable({ services }: { services: Record<string, ServiceHealth> }) {
  const rows: ServiceRow[] = Object.entries(services).map(([name, health]) => ({
    ...health,
    name,
  }));
  const columns: ColumnsType<ServiceRow> = [
    {
      title: "基础设施",
      dataIndex: "name",
      render: (name: string) => <Typography.Text strong>{serviceNames[name] ?? name}</Typography.Text>,
    },
    {
      title: "状态",
      dataIndex: "status",
      render: (status: string, row) => (
        <Badge
          status={status === "up" ? "success" : "error"}
          text={status === "up" ? "连接正常" : `连接失败${row.error ? ` · ${row.error}` : ""}`}
        />
      ),
    },
    {
      title: "角色",
      dataIndex: "required",
      render: (required: boolean) => (
        <Tag color={required ? "blue" : "default"}>{required ? "必需服务" : "可选增强"}</Tag>
      ),
    },
    {
      title: "延迟",
      dataIndex: "latency_ms",
      align: "right",
      render: (latency: number | null) => (latency === null ? "—" : `${latency} ms`),
    },
  ];

  return (
    <Table
      rowKey="name"
      columns={columns}
      dataSource={rows}
      pagination={false}
      size="middle"
      scroll={{ x: 620 }}
    />
  );
}
