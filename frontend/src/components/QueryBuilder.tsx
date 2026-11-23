import { useCallback, useRef, useState } from "react";
import { DeleteOutlined, PlayCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { Alert, Button, InputNumber, Segmented, Select, Space } from "antd";
import { fetchDimensionValues } from "../api/query";
import type { DatasetInfo, FilterSpec, Operator, QuerySpec } from "../api/types";

const CATEGORY_OPERATORS: { value: Operator; label: string }[] = [
  { value: "eq", label: "等于" },
  { value: "ne", label: "不等于" },
  { value: "in", label: "属于" },
  { value: "not_in", label: "不属于" },
];
const TIME_OPERATORS: { value: Operator; label: string }[] = [
  { value: "eq", label: "等于" },
  { value: "gte", label: "不早于" },
  { value: "lte", label: "不晚于" },
  { value: "gt", label: "晚于" },
  { value: "lt", label: "早于" },
  { value: "in", label: "属于" },
];
const MULTI: Operator[] = ["in", "not_in"];
// Same symbols as the evidence panel, so a question's title never misstates its condition.
const OPERATOR_SYMBOL: Partial<Record<Operator, string>> = {
  eq: "=",
  ne: "≠",
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  in: "属于",
  not_in: "不属于",
};

interface FilterRow {
  key: number;
  field?: string;
  operator: Operator;
  values: string[];
}

interface Props {
  dataset: DatasetInfo;
  workspaceId: string;
  running: boolean;
  onRun: (query: QuerySpec, title: string) => void;
}

export function QueryBuilder({ dataset, workspaceId, running, onRun }: Props) {
  const [metrics, setMetrics] = useState<string[]>([]);
  const [dimensions, setDimensions] = useState<string[]>([]);
  const [filters, setFilters] = useState<FilterRow[]>([]);
  const [orderField, setOrderField] = useState<string | undefined>();
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [limit, setLimit] = useState(100);
  const [valueOptions, setValueOptions] = useState<Record<string, string[]>>({});
  const [loadingValues, setLoadingValues] = useState<Record<string, boolean>>({});
  const [valueError, setValueError] = useState<string | null>(null);
  const nextKey = useRef(1);
  const requested = useRef(new Set<string>());

  const dimensionByName = new Map(dataset.dimensions.map((d) => [d.name, d]));
  const metricLabel = (name: string) => dataset.metrics.find((m) => m.name === name)?.label ?? name;
  const dimensionLabel = (name: string) => dimensionByName.get(name)?.label ?? name;

  const loadValues = useCallback(
    async (dimension: string) => {
      if (requested.current.has(dimension)) return;
      requested.current.add(dimension);
      setLoadingValues((state) => ({ ...state, [dimension]: true }));
      try {
        const result = await fetchDimensionValues(workspaceId, dataset.name, dimension);
        setValueOptions((state) => ({ ...state, [dimension]: result.values }));
      } catch {
        requested.current.delete(dimension);
        setValueError("读取可选值失败，请稍后重试");
      } finally {
        setLoadingValues((state) => ({ ...state, [dimension]: false }));
      }
    },
    [dataset.name, workspaceId],
  );

  const updateFilter = (key: number, patch: Partial<FilterRow>) =>
    setFilters((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)));

  const addFilter = () =>
    setFilters((rows) => [...rows, { key: nextKey.current++, operator: "eq", values: [] }]);

  const selectedFields = [
    ...metrics.map((name) => ({ value: name, label: metricLabel(name) })),
    ...dimensions.map((name) => ({ value: name, label: dimensionLabel(name) })),
  ];
  const effectiveOrder = selectedFields.some((f) => f.value === orderField) ? orderField : undefined;

  const incompleteFilter = filters.some((row) => !row.field || row.values.length === 0);
  const empty = metrics.length === 0 && dimensions.length === 0;
  const problem = empty
    ? "请至少选择一个指标或维度"
    : incompleteFilter
      ? "有过滤条件还没填完整"
      : null;

  const run = () => {
    if (problem) return;
    const specFilters: FilterSpec[] = filters.map((row) => ({
      field: row.field!,
      operator: row.operator,
      values: row.values,
    }));
    const query: QuerySpec = {
      dataset: dataset.name,
      metrics: metrics.map((name) => ({ name })),
      dimensions: dimensions.map((name) => ({ name })),
      filters: specFilters,
      order_by: effectiveOrder ? [{ field: effectiveOrder, direction }] : [],
      limit,
    };
    const parts = [metrics.map(metricLabel).join("、") || dimensions.map(dimensionLabel).join("、")];
    if (metrics.length > 0 && dimensions.length > 0) {
      parts.push(`按${dimensions.map(dimensionLabel).join("、")}`);
    }
    for (const row of filters) {
      parts.push(
        `${dimensionLabel(row.field!)} ${OPERATOR_SYMBOL[row.operator] ?? row.operator} ${row.values.join("、")}`,
      );
    }
    onRun(query, parts.join(" · "));
  };

  return (
    <div className="builder">
      <div className="builder-grid">
        <label className="builder-field">
          <span>指标（要算什么）</span>
          <Select
            mode="multiple"
            allowClear
            placeholder="选择一个或多个指标"
            value={metrics}
            onChange={setMetrics}
            options={dataset.metrics.map((m) => ({
              value: m.name,
              label: m.unit ? `${m.label}（${m.unit}）` : m.label,
              title: m.description ?? undefined,
            }))}
            maxTagCount="responsive"
          />
        </label>
        <label className="builder-field">
          <span>维度（按什么拆分）</span>
          <Select
            mode="multiple"
            allowClear
            placeholder="不选则只看合计"
            value={dimensions}
            onChange={setDimensions}
            options={dataset.dimensions.map((d) => ({
              value: d.name,
              label: d.is_time ? `${d.label}（时间）` : d.label,
            }))}
            maxTagCount="responsive"
          />
        </label>
      </div>

      <div className="builder-filters">
        <div className="builder-filters-head">
          <span>过滤条件</span>
          <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addFilter}>
            添加条件
          </Button>
        </div>
        {valueError && <Alert type="warning" showIcon message={valueError} closable onClose={() => setValueError(null)} />}
        {filters.map((row) => {
          const time = row.field ? dimensionByName.get(row.field)?.is_time : false;
          const multiple = MULTI.includes(row.operator);
          return (
            <Space key={row.key} wrap className="filter-row">
              <Select
                style={{ width: 130 }}
                placeholder="选择维度"
                value={row.field}
                onChange={(field: string) => {
                  updateFilter(row.key, { field, values: [], operator: "eq" });
                  void loadValues(field);
                }}
                options={dataset.dimensions.map((d) => ({ value: d.name, label: d.label }))}
              />
              <Select
                style={{ width: 110 }}
                value={row.operator}
                onChange={(operator: Operator) =>
                  updateFilter(row.key, {
                    operator,
                    values: MULTI.includes(operator) ? row.values : row.values.slice(0, 1),
                  })
                }
                options={time ? TIME_OPERATORS : CATEGORY_OPERATORS}
                disabled={!row.field}
              />
              <Select
                style={{ minWidth: 220 }}
                mode={multiple ? "multiple" : undefined}
                showSearch
                allowClear
                placeholder={row.field ? "选择取值" : "先选择维度"}
                disabled={!row.field}
                loading={row.field ? loadingValues[row.field] : false}
                value={multiple ? row.values : (row.values[0] ?? undefined)}
                onChange={(value: string | string[] | undefined) =>
                  updateFilter(row.key, {
                    values: Array.isArray(value) ? value : value ? [value] : [],
                  })
                }
                options={(row.field ? (valueOptions[row.field] ?? []) : []).map((v) => ({
                  value: v,
                  label: v,
                }))}
              />
              <Button
                type="text"
                aria-label="删除条件"
                icon={<DeleteOutlined />}
                onClick={() => setFilters((rows) => rows.filter((r) => r.key !== row.key))}
              />
            </Space>
          );
        })}
      </div>

      <div className="builder-foot">
        <Space wrap size="middle">
          <Space>
            <span className="builder-inline-label">排序</span>
            <Select
              style={{ width: 130 }}
              allowClear
              placeholder="自动"
              value={effectiveOrder}
              onChange={setOrderField}
              options={selectedFields}
            />
            <Segmented
              value={direction}
              onChange={(value) => setDirection(value as "asc" | "desc")}
              options={[
                { value: "desc", label: "从高到低" },
                { value: "asc", label: "从低到高" },
              ]}
              disabled={!effectiveOrder}
            />
          </Space>
          <Space>
            <span className="builder-inline-label">最多返回</span>
            <InputNumber min={1} max={500} value={limit} onChange={(v) => setLimit(v ?? 100)} suffix="行" />
          </Space>
        </Space>
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          loading={running}
          disabled={problem !== null}
          onClick={run}
          title={problem ?? undefined}
        >
          运行查询
        </Button>
      </div>
      {problem && !empty && <p className="builder-hint">{problem}</p>}
    </div>
  );
}
