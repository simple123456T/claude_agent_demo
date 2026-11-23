import { Suspense, lazy, useMemo } from "react";
import { CopyOutlined } from "@ant-design/icons";
import { Alert, Button, Collapse, Descriptions, Empty, Space, Table, Tabs, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { AskResponse, CellValue } from "../api/types";
import { buildPanels } from "../utils/chartData";
import { downloadCsv, formatNumber, formatWithUnit, toCsv } from "../utils/format";

const ResultChart = lazy(() =>
  import("./ResultChart").then((module) => ({ default: module.ResultChart })),
);

function StatTiles({ response }: { response: AskResponse }) {
  const metrics = response.chart?.metrics ?? [];
  return (
    <div className="stat-tiles">
      {metrics.map((name) => {
        const position = response.columns.findIndex((column) => column.name === name);
        const column = response.columns[position];
        return (
          <div className="stat-tile" key={name}>
            <span className="stat-tile-label">{column.label}</span>
            <span className="stat-tile-value">
              {formatNumber(response.rows[0][position])}
              {column.unit && <small>{column.unit}</small>}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ResultTable({ response }: { response: AskResponse }) {
  type Row = Record<string, CellValue> & { __key: number };
  const columns: ColumnsType<Row> = response.columns.map((column, position) => ({
    title: column.unit ? `${column.label}（${column.unit}）` : column.label,
    dataIndex: column.name,
    align: column.role === "metric" ? "right" : "left",
    render: (value: CellValue) => (
      <span className={column.role === "metric" ? "tabular" : undefined}>
        {formatWithUnit(value, null)}
      </span>
    ),
    sorter: (a, b) => {
      const left = a[column.name];
      const right = b[column.name];
      if (typeof left === "number" && typeof right === "number") return left - right;
      return String(left ?? "").localeCompare(String(right ?? ""), "zh-CN");
    },
    key: `${column.name}-${position}`,
  }));
  const data: Row[] = response.rows.map((row, rowIndex) => {
    const record: Record<string, CellValue> = {};
    response.columns.forEach((column, position) => {
      record[column.name] = row[position];
    });
    return { ...record, __key: rowIndex };
  });
  return (
    <Table<Row>
      size="small"
      rowKey="__key"
      columns={columns}
      dataSource={data}
      pagination={data.length > 15 ? { pageSize: 15, showSizeChanger: false } : false}
      scroll={{ x: "max-content" }}
      locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有数据" /> }}
    />
  );
}

function EvidencePanel({ response }: { response: AskResponse }) {
  const [messageApi, holder] = message.useMessage();
  const evidence = response.evidence;
  if (!evidence) return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(evidence.sql);
      messageApi.success("SQL 已复制");
    } catch {
      messageApi.error("复制失败，请手动选择文本");
    }
  };

  return (
    <Collapse
      ghost
      size="small"
      className="evidence"
      items={[
        {
          key: "evidence",
          label: <span className="evidence-title">查询依据</span>,
          children: (
            <>
              {holder}
              <Descriptions size="small" column={{ xs: 1, md: 2 }} colon={false}>
                <Descriptions.Item label="数据集">
                  {evidence.dataset_label}（语义版本 {evidence.semantic_version}）
                </Descriptions.Item>
                <Descriptions.Item label="来源">
                  {evidence.source === "natural_language" ? "自然语言 → 结构化查询" : "手动构建"}
                </Descriptions.Item>
                <Descriptions.Item label="返回">
                  {evidence.row_count} 行 · {evidence.elapsed_ms} ms
                  {evidence.truncated && <Tag color="gold">还有更多数据未显示</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="过滤条件">
                  {evidence.filters.length === 0 ? (
                    "无"
                  ) : (
                    <Space size={[4, 4]} wrap>
                      {evidence.filters.map((text) => (
                        <Tag key={text}>{text}</Tag>
                      ))}
                    </Space>
                  )}
                </Descriptions.Item>
              </Descriptions>
              {response.assumptions.length > 0 && (
                <Alert
                  className="assumptions"
                  type="info"
                  showIcon
                  message="系统做了这些假设"
                  description={
                    <ul>
                      {response.assumptions.map((text) => (
                        <li key={text}>{text}</li>
                      ))}
                    </ul>
                  }
                />
              )}
              <div className="sql-head">
                <span>对应的 SQL（由结构化查询确定性生成，已通过只读校验）</span>
                <Button size="small" icon={<CopyOutlined />} onClick={() => void copy()}>
                  复制
                </Button>
              </div>
              <pre className="sql-block">{evidence.sql}</pre>
            </>
          ),
        },
      ]}
    />
  );
}

export function ResultView({
  response,
  title,
  canExport,
}: {
  response: AskResponse;
  title: string;
  canExport: boolean;
}) {
  const chart = response.chart;
  const panels = useMemo(
    () => (chart && (chart.kind === "line" || chart.kind === "bar") ? buildPanels(response.columns, response.rows, chart) : []),
    [response, chart],
  );

  if (response.status !== "ok") {
    return (
      <Alert
        type={response.status === "clarify" ? "info" : "warning"}
        showIcon
        message={response.status === "clarify" ? "需要你补充一点信息" : "这个问题暂时回答不了"}
        description={response.message}
      />
    );
  }

  const exportCsv = () =>
    downloadCsv(`${title.slice(0, 30) || "查询结果"}.csv`, toCsv(response.columns, response.rows));

  const chartView = (
    <div className="panels">
      {panels.map((panel) => (
        <section key={panel.key} className="panel">
          {panels.length > 1 && (
            <h4 className="panel-title">
              {panel.title}
              {panel.unit && <small>（{panel.unit}）</small>}
            </h4>
          )}
          {chart && (
            <Suspense fallback={<div className="chart-loading">图表加载中…</div>}>
              <ResultChart panel={panel} chart={chart} />
            </Suspense>
          )}
        </section>
      ))}
      {chart && <p className="chart-reason">{chart.reason}</p>}
    </div>
  );

  const showTabs = panels.length > 0;
  return (
    <div className="result">
      {response.summary && <p className="summary">{response.summary}</p>}
      {chart?.kind === "stat" && <StatTiles response={response} />}
      {chart?.kind !== "stat" &&
        (showTabs ? (
          <Tabs
            size="small"
            defaultActiveKey="chart"
            tabBarExtraContent={
              canExport && response.rows.length > 0 ? (
                <Button size="small" onClick={exportCsv}>
                  导出 CSV
                </Button>
              ) : null
            }
            items={[
              { key: "chart", label: "图表", children: chartView },
              { key: "table", label: "表格", children: <ResultTable response={response} /> },
            ]}
          />
        ) : (
          <>
            <ResultTable response={response} />
            {canExport && response.rows.length > 0 && (
              <div className="table-actions">
                <Button size="small" onClick={exportCsv}>
                  导出 CSV
                </Button>
              </div>
            )}
          </>
        ))}
      <EvidencePanel response={response} />
    </div>
  );
}
