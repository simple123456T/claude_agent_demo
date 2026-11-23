import type { CellValue, ResultColumn } from "../api/types";

const integer = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const compact = new Intl.NumberFormat("zh-CN", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** Exact figure with thousands separators; never rounded to a different magnitude. */
export function formatNumber(value: CellValue): string {
  if (value === null || value === undefined) return "—";
  if (typeof value !== "number") return String(value);
  return Number.isInteger(value) ? integer.format(value) : decimal.format(value);
}

export function formatWithUnit(value: CellValue, unit: string | null): string {
  const text = formatNumber(value);
  return unit && typeof value === "number" ? `${text} ${unit}` : text;
}

/** Short form for axis ticks and bar tips, where the exact figure lives in the tooltip. */
export function formatCompact(value: number): string {
  return Math.abs(value) < 10000 ? integer.format(value) : compact.format(value);
}

/** Cells that start with these characters are executed as formulas by spreadsheet software. */
const FORMULA_PREFIX = /^[=+\-@\t\r]/;

function csvCell(value: CellValue): string {
  if (value === null) return "";
  let text = String(value);
  if (typeof value === "string" && FORMULA_PREFIX.test(text)) text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(columns: ResultColumn[], rows: CellValue[][]): string {
  const header = columns.map((c) => csvCell(c.unit ? `${c.label}（${c.unit}）` : c.label));
  const body = rows.map((row) => row.map(csvCell).join(","));
  // BOM so Excel opens the Chinese text as UTF-8.
  return `﻿${[header.join(","), ...body].join("\r\n")}`;
}

export function downloadCsv(filename: string, csv: string): void {
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
