import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import type { EChartsCoreOption } from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { ChartSpec } from "../api/types";
import type { Panel } from "../utils/chartData";
import { formatCompact, formatNumber } from "../utils/format";

echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

// Categorical slots in their fixed order (validated palette); one series uses slot 1 only.
const SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];
const SURFACE = "#ffffff";
const INK_SECONDARY = "#52514e";
const INK_MUTED = "#898781";
const GRID = "#e1e0d9";
const AXIS = "#c3c2b7";
const MAX_END_LABELS = 4;
const MAX_BAR_LABELS = 12;

interface TipParam {
  name?: string;
  seriesName?: string;
  value?: unknown;
  color?: unknown;
  axisValueLabel?: string;
}

// Category and series names come from the database: escape everything placed in tooltip HTML.
const escape = (text: string) => echarts.format.encodeHTML(text);

function tooltipRow(param: TipParam, unit: string | null, showSeries: boolean): string {
  const value = typeof param.value === "number" ? formatNumber(param.value) : "—";
  const color = typeof param.color === "string" ? param.color : SERIES_COLORS[0];
  const label = showSeries && param.seriesName ? escape(param.seriesName) : "";
  return (
    `<div style="display:flex;align-items:center;gap:8px;margin-top:4px">` +
    `<span style="display:inline-block;width:12px;height:2px;background:${escape(color)}"></span>` +
    `<strong style="color:#0b0b0b">${escape(value)}${unit ? ` ${escape(unit)}` : ""}</strong>` +
    (label ? `<span style="color:${INK_SECONDARY}">${label}</span>` : "") +
    `</div>`
  );
}

export function buildOption(panel: Panel, chart: ChartSpec): EChartsCoreOption {
  const multi = panel.series.length > 1;
  const horizontal = chart.kind === "bar" && chart.horizontal;
  const endLabels = chart.kind === "line" && multi && panel.series.length <= MAX_END_LABELS;

  const categoryAxis = {
    type: "category" as const,
    data: panel.categories,
    inverse: horizontal,
    axisTick: { show: false },
    axisLine: { lineStyle: { color: AXIS } },
    axisLabel: { color: INK_MUTED, fontSize: 12, hideOverlap: true },
  };
  const valueAxis = {
    type: "value" as const,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: INK_MUTED, fontSize: 12, formatter: (v: number) => formatCompact(v) },
    splitLine: { lineStyle: { color: GRID, width: 1, type: "solid" as const } },
  };

  const series = panel.series.map((line, position) => {
    const color = SERIES_COLORS[position % SERIES_COLORS.length];
    if (chart.kind === "line") {
      return {
        name: line.name,
        type: "line" as const,
        data: line.data,
        color,
        showSymbol: false,
        symbol: "circle",
        symbolSize: 8,
        lineStyle: { width: 2, color, cap: "round" as const, join: "round" as const },
        itemStyle: { color, borderColor: SURFACE, borderWidth: 2 },
        emphasis: { focus: "series" as const },
        connectNulls: false,
        endLabel: endLabels
          ? { show: true, formatter: line.name, color: INK_SECONDARY, fontSize: 12 }
          : undefined,
      };
    }
    return {
      name: line.name,
      type: "bar" as const,
      data: line.data,
      color,
      barMaxWidth: 24,
      itemStyle: {
        color,
        borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
      },
      emphasis: { itemStyle: { shadowBlur: 0, borderColor: INK_SECONDARY, borderWidth: 1 } },
      label: {
        show: panel.categories.length <= MAX_BAR_LABELS,
        position: horizontal ? ("right" as const) : ("top" as const),
        color: INK_SECONDARY,
        fontSize: 12,
        formatter: (p: TipParam) => (typeof p.value === "number" ? formatCompact(p.value) : ""),
      },
    };
  });

  return {
    animationDuration: 250,
    textStyle: { fontFamily: "inherit" },
    grid: {
      left: 8,
      right: endLabels ? 72 : horizontal ? 56 : 16,
      top: multi && !endLabels ? 36 : 24,
      bottom: 8,
      containLabel: true,
    },
    legend: multi
      ? {
          top: 0,
          left: 0,
          icon: chart.kind === "line" ? "roundRect" : "rect",
          itemWidth: chart.kind === "line" ? 16 : 10,
          itemHeight: chart.kind === "line" ? 3 : 10,
          textStyle: { color: INK_SECONDARY, fontSize: 12 },
        }
      : undefined,
    tooltip:
      chart.kind === "line"
        ? {
            trigger: "axis",
            axisPointer: { type: "line", lineStyle: { color: AXIS, width: 1 } },
            confine: true,
            borderColor: GRID,
            textStyle: { color: INK_SECONDARY, fontSize: 12 },
            formatter: (raw: unknown) => {
              const params = (Array.isArray(raw) ? raw : [raw]) as TipParam[];
              const head = escape(String(params[0]?.axisValueLabel ?? params[0]?.name ?? ""));
              return (
                `<div style="color:${INK_SECONDARY}">${head}</div>` +
                params.map((p) => tooltipRow(p, panel.unit, multi)).join("")
              );
            },
          }
        : {
            trigger: "item",
            confine: true,
            borderColor: GRID,
            textStyle: { color: INK_SECONDARY, fontSize: 12 },
            formatter: (raw: unknown) => {
              const p = raw as TipParam;
              return (
                `<div style="color:${INK_SECONDARY}">${escape(String(p.name ?? ""))}</div>` +
                tooltipRow(p, panel.unit, multi)
              );
            },
          },
    xAxis: horizontal ? valueAxis : categoryAxis,
    yAxis: horizontal ? categoryAxis : valueAxis,
    series,
  };
}

export function chartHeight(panel: Panel, chart: ChartSpec): number {
  if (chart.kind === "bar" && chart.horizontal) {
    return Math.max(220, panel.categories.length * 34 + 48);
  }
  return panel.series.length > 1 ? 320 : 280;
}

export function ResultChart({ panel, chart }: { panel: Panel; chart: ChartSpec }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const instance = echarts.init(element, undefined, { renderer: "canvas" });
    instance.setOption(buildOption(panel, chart));
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      instance.dispose();
    };
  }, [panel, chart]);

  return (
    <div
      ref={container}
      className="chart-canvas"
      style={{ height: chartHeight(panel, chart) }}
      role="img"
      aria-label={`${panel.title}${panel.unit ? `（${panel.unit}）` : ""}图表，数据见「表格」`}
    />
  );
}
