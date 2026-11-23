import type { AskResponse, CellValue, ChartSpec, ResultColumn } from "../api/types";

export interface Panel {
  key: string;
  title: string;
  unit: string | null;
  categories: string[];
  series: { name: string; data: (number | null)[] }[];
}

const asNumber = (value: CellValue): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

/**
 * One panel per metric: metrics of different scale never share an axis (no dual axis).
 * With a series dimension, each panel holds one line per category of that dimension.
 */
export function buildPanels(
  columns: ResultColumn[],
  rows: AskResponse["rows"],
  chart: ChartSpec,
): Panel[] {
  const index = (name: string | null) => columns.findIndex((column) => column.name === name);
  const categoryIndex = index(chart.category);
  if (categoryIndex < 0) return [];
  const seriesIndex = index(chart.series_dimension);

  return chart.metrics.flatMap((metricName) => {
    const metricIndex = index(metricName);
    if (metricIndex < 0) return [];
    const metric = columns[metricIndex];

    const categories: string[] = [];
    const seen = new Set<string>();
    const lines = new Map<string, Map<string, number | null>>();

    for (const row of rows) {
      const category = String(row[categoryIndex]);
      if (!seen.has(category)) {
        seen.add(category);
        categories.push(category);
      }
      const lineName = seriesIndex >= 0 ? String(row[seriesIndex]) : metric.label;
      if (!lines.has(lineName)) lines.set(lineName, new Map());
      lines.get(lineName)!.set(category, asNumber(row[metricIndex]));
    }

    return [
      {
        key: metricName,
        title: metric.label,
        unit: metric.unit,
        categories,
        series: [...lines].map(([name, values]) => ({
          name,
          data: categories.map((category) => values.get(category) ?? null),
        })),
      },
    ];
  });
}
