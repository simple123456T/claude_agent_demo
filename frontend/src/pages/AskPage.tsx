import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { SendOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, Input, Segmented, Select, Skeleton, Space, Spin, Tag } from "antd";
import { ApiError } from "../api/client";
import { ask, fetchAuthConfig, fetchDatasets } from "../api/query";
import type { AskBody, AskResponse, DatasetInfo, QuerySpec } from "../api/types";
import { useAuth } from "../auth";
import { QueryBuilder } from "../components/QueryBuilder";
import { ResultView } from "../components/ResultView";
import { roleLabel } from "../utils/roles";

type Mode = "ask" | "build";

interface Turn {
  id: number;
  title: string;
  source: Mode;
  status: "loading" | "done" | "error";
  response?: AskResponse;
  error?: { code: string | null; message: string };
}

interface QuickStart {
  title: string;
  hint: string;
  query: QuerySpec;
}

const baseQuery = (dataset: DatasetInfo): QuerySpec => ({
  dataset: dataset.name,
  metrics: [],
  dimensions: [],
  filters: [],
  order_by: [],
  limit: 100,
});

/** One-click questions generated from the dataset's own metrics and dimensions. */
function quickStarts(dataset: DatasetInfo): QuickStart[] {
  const metric = dataset.metrics[0];
  const category = dataset.dimensions.filter((d) => !d.is_time);
  const time = dataset.dimensions.find((d) => d.is_time);
  const items: QuickStart[] = [];
  if (dataset.metrics.length > 0) {
    const shown = dataset.metrics.slice(0, 4);
    items.push({
      title: `${shown.map((m) => m.label).join("、")}总览`,
      hint: "全部数据的合计",
      query: { ...baseQuery(dataset), metrics: shown.map((m) => ({ name: m.name })) },
    });
  }
  if (metric && category[0]) {
    items.push({
      title: `各${category[0].label}的${metric.label}`,
      hint: "按类别比较",
      query: {
        ...baseQuery(dataset),
        metrics: [{ name: metric.name }],
        dimensions: [{ name: category[0].name }],
      },
    });
  }
  if (metric && time) {
    items.push({
      title: `每月${metric.label}趋势`,
      hint: "随时间变化",
      query: {
        ...baseQuery(dataset),
        metrics: [{ name: metric.name }],
        dimensions: [{ name: time.name }],
      },
    });
  }
  const ranked = category[1] ?? category[0];
  if (metric && ranked) {
    items.push({
      title: `${metric.label}最高的 5 个${ranked.label}`,
      hint: "排行榜",
      query: {
        ...baseQuery(dataset),
        metrics: [{ name: metric.name }],
        dimensions: [{ name: ranked.name }],
        order_by: [{ field: metric.name, direction: "desc" }],
        limit: 5,
      },
    });
  }
  return items;
}

function exampleQuestions(dataset: DatasetInfo): string[] {
  const metric = dataset.metrics[0];
  const category = dataset.dimensions.filter((d) => !d.is_time);
  const time = dataset.dimensions.find((d) => d.is_time);
  if (!metric) return [];
  const examples: string[] = [];
  if (category[0]) examples.push(`各${category[0].label}的${metric.label}是多少？`);
  if (time) examples.push(`今年每个月的${metric.label}趋势如何？`);
  if (category[1]) examples.push(`${metric.label}最高的 5 个${category[1].label}是哪些？`);
  return examples;
}

export function AskPage() {
  const { me } = useAuth();
  const workspaces = useMemo(
    () => (me?.workspaces ?? []).filter((w) => w.permissions.includes("query:run")),
    [me],
  );
  const [workspaceId, setWorkspaceId] = useState<string | undefined>(workspaces[0]?.id);
  const workspace = workspaces.find((w) => w.id === workspaceId);

  const [datasets, setDatasets] = useState<DatasetInfo[] | null>(null);
  const [datasetError, setDatasetError] = useState<string | null>(null);
  const [modelConfigured, setModelConfigured] = useState<boolean | null>(null);
  const [mode, setMode] = useState<Mode>("build");
  const [modeChosen, setModeChosen] = useState(false);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const counter = useRef(0);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchAuthConfig()
      .then((config) => setModelConfigured(config.model_configured))
      .catch(() => setModelConfigured(false));
  }, []);

  useEffect(() => {
    if (modelConfigured !== null && !modeChosen) setMode(modelConfigured ? "ask" : "build");
  }, [modelConfigured, modeChosen]);

  useEffect(() => {
    if (!workspaceId) return;
    let cancelled = false;
    setDatasets(null);
    setDatasetError(null);
    setTurns([]);
    fetchDatasets(workspaceId)
      .then((result) => !cancelled && setDatasets(result))
      .catch((error: unknown) => {
        if (!cancelled) setDatasetError(error instanceof ApiError ? error.message : "加载数据集失败");
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  const dataset = datasets?.[0];
  const running = turns.some((turn) => turn.status === "loading");

  const run = useCallback(
    async (title: string, body: AskBody, source: Mode) => {
      if (!workspaceId) return;
      const id = ++counter.current;
      setTurns((list) => [...list, { id, title, source, status: "loading" }]);
      const patch = (update: Partial<Turn>) =>
        setTurns((list) => list.map((turn) => (turn.id === id ? { ...turn, ...update } : turn)));
      try {
        patch({ status: "done", response: await ask(workspaceId, body) });
      } catch (error) {
        patch({
          status: "error",
          error:
            error instanceof ApiError
              ? { code: error.code, message: error.message }
              : { code: null, message: "请求失败，请稍后重试" },
        });
      }
    },
    [workspaceId],
  );

  const submitQuestion = () => {
    const text = question.trim();
    if (!text || running || !dataset) return;
    setQuestion("");
    void run(text, { question: text, dataset: dataset.name }, "ask");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter confirms an IME candidate while composing Chinese; only a plain Enter sends.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    submitQuestion();
  };

  const switchToBuilder = () => {
    setModeChosen(true);
    setMode("build");
  };

  if (!me) return null;
  if (me.workspaces.length === 0) {
    return (
      <Empty
        className="ask-empty"
        description="你还没有加入任何工作区。请联系管理员把你加入工作区后再来提问。"
      />
    );
  }
  if (workspaces.length === 0) {
    const roles = me.workspaces.map((w) => `${w.name}（${roleLabel(w.role)}）`).join("、");
    return (
      <Alert
        type="warning"
        showIcon
        message="当前身份没有提问权限"
        description={`你在 ${roles} 中的角色只能查看，不能提问。需要提问请联系工作区管理员调整角色。`}
      />
    );
  }

  const canExport = workspace?.permissions.includes("export:create") ?? false;
  const starts = dataset ? quickStarts(dataset) : [];
  const examples = dataset ? exampleQuestions(dataset) : [];

  return (
    <div className="ask-page">
      <div className="ask-top">
        <Space wrap>
          {workspaces.length > 1 ? (
            <Select
              value={workspaceId}
              onChange={setWorkspaceId}
              style={{ minWidth: 180 }}
              options={workspaces.map((w) => ({ value: w.id, label: w.name }))}
            />
          ) : (
            <Tag color="blue">{workspace?.name}</Tag>
          )}
          {dataset && (
            <span className="dataset-line">
              数据集：<strong>{dataset.label}</strong>
              <span className="muted">（语义版本 {dataset.version}）</span>
            </span>
          )}
        </Space>
        {dataset?.description && <p className="dataset-desc">{dataset.description}</p>}
      </div>

      {datasetError && <Alert type="error" showIcon message={datasetError} />}
      {!dataset && !datasetError && <Skeleton active paragraph={{ rows: 3 }} />}

      <div className="conversation" aria-live="polite">
        {dataset && turns.length === 0 && (
          <section className="welcome">
            <h2>想了解什么数据？</h2>
            <p>
              直接提问，或点下面的快捷查询。每个结果都会附上口径、过滤条件和执行的 SQL，方便核对。
            </p>
            <div className="quick-grid">
              {starts.map((item) => (
                <button
                  key={item.title}
                  type="button"
                  className="quick-card"
                  disabled={running}
                  onClick={() => void run(item.title, { query: item.query }, "build")}
                >
                  <ThunderboltOutlined />
                  <strong>{item.title}</strong>
                  <span>{item.hint}</span>
                </button>
              ))}
            </div>
            <details className="catalog">
              <summary>可以问哪些指标和维度？</summary>
              <div className="catalog-grid">
                <div>
                  <h4>指标</h4>
                  <Space size={[6, 6]} wrap>
                    {dataset.metrics.map((m) => (
                      <Tag key={m.name} title={m.description ?? undefined}>
                        {m.label}
                        {m.unit ? `（${m.unit}）` : ""}
                      </Tag>
                    ))}
                  </Space>
                </div>
                <div>
                  <h4>维度</h4>
                  <Space size={[6, 6]} wrap>
                    {dataset.dimensions.map((d) => (
                      <Tag key={d.name}>{d.is_time ? `${d.label}（时间）` : d.label}</Tag>
                    ))}
                  </Space>
                </div>
              </div>
            </details>
          </section>
        )}

        {turns.map((turn) => (
          <article className="turn" key={turn.id}>
            <div className="turn-question">
              <span>{turn.title}</span>
              {turn.source === "build" && <Tag>手动查询</Tag>}
            </div>
            <div className="turn-answer">
              {turn.status === "loading" && (
                <div className="loading">
                  <Spin size="small" />
                  <span>{turn.source === "ask" ? "正在理解问题并查询…" : "正在查询…"}</span>
                </div>
              )}
              {turn.status === "error" && turn.error && (
                <Alert
                  type="error"
                  showIcon
                  message={turn.error.message}
                  action={
                    turn.error.code === "model_not_configured" ||
                    turn.error.code === "model_unavailable" ||
                    turn.error.code === "plan_failed" ? (
                      <Button size="small" onClick={switchToBuilder}>
                        改用手动构建
                      </Button>
                    ) : undefined
                  }
                />
              )}
              {turn.status === "done" && turn.response && (
                <ResultView response={turn.response} title={turn.title} canExport={canExport} />
              )}
            </div>
          </article>
        ))}
        <div ref={bottom} />
      </div>

      {dataset && (
        <div className={`composer${mode === "ask" ? " composer-sticky" : ""}`}>
          <Segmented
            value={mode}
            onChange={(value) => {
              setModeChosen(true);
              setMode(value as Mode);
            }}
            options={[
              { value: "ask", label: "自然语言提问" },
              { value: "build", label: "手动构建" },
            ]}
          />
          {turns.length > 0 && starts.length > 0 && (
            <Space size={[6, 6]} wrap className="quick-chips">
              <span className="muted">快捷查询：</span>
              {starts.map((item) => (
                <Tag
                  key={item.title}
                  className={`example-tag quick-chip${running ? " disabled" : ""}`}
                  onClick={() => !running && void run(item.title, { query: item.query }, "build")}
                >
                  {item.title}
                </Tag>
              ))}
            </Space>
          )}
          {mode === "ask" ? (
            <>
              {modelConfigured === false && (
                <Alert
                  className="composer-alert"
                  type="warning"
                  showIcon
                  message="尚未配置内网模型，暂时无法用自然语言提问"
                  description={
                    <>
                      请在 <code>.env</code> 中填写 <code>MODEL_BASE_URL</code> 和{" "}
                      <code>MODEL_NAME</code> 后重启后端。在此之前可以使用「手动构建」，同样走权限校验。
                      <Button type="link" size="small" onClick={switchToBuilder}>
                        改用手动构建
                      </Button>
                    </>
                  }
                />
              )}
              <div className="composer-row">
                <Input.TextArea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  onKeyDown={onKeyDown}
                  autoSize={{ minRows: 1, maxRows: 4 }}
                  maxLength={500}
                  disabled={modelConfigured === false}
                  placeholder={examples[0] ? `例如：${examples[0]}` : "输入你的问题"}
                  aria-label="输入问题"
                />
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  disabled={!question.trim() || running || modelConfigured === false}
                  onClick={submitQuestion}
                >
                  提问
                </Button>
              </div>
              {modelConfigured && examples.length > 0 && (
                <Space size={[6, 6]} wrap className="examples">
                  <span className="muted">试试：</span>
                  {examples.map((text) => (
                    <Tag key={text} className="example-tag" onClick={() => setQuestion(text)}>
                      {text}
                    </Tag>
                  ))}
                </Space>
              )}
            </>
          ) : (
            workspaceId && (
              <QueryBuilder
                dataset={dataset}
                workspaceId={workspaceId}
                running={running}
                onRun={(query, title) => void run(title, { query }, "build")}
              />
            )
          )}
        </div>
      )}
    </div>
  );
}
