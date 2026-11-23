export type Operator =
  | "eq"
  | "ne"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "in"
  | "not_in"
  | "is_null"
  | "not_null";

export interface WorkspaceSummary {
  id: string;
  slug: string;
  name: string;
  role: string | null;
  permissions: string[];
}

export interface Me {
  id: string;
  subject: string;
  email: string | null;
  display_name: string | null;
  is_org_admin: boolean;
  workspaces: WorkspaceSummary[];
}

export interface DevIdentity {
  subject: string;
  label: string;
  description: string;
}

export interface AuthConfig {
  mode: "dev" | "oidc" | "unconfigured";
  dev_identities: DevIdentity[];
  model_configured: boolean;
}

export interface MetricInfo {
  name: string;
  label: string;
  description: string | null;
  unit: string | null;
  aggregation: string;
  synonyms: string[];
}

export interface DimensionInfo {
  name: string;
  label: string;
  is_time: boolean;
  synonyms: string[];
}

export interface DatasetInfo {
  name: string;
  label: string;
  description: string | null;
  version: string;
  metrics: MetricInfo[];
  dimensions: DimensionInfo[];
}

export interface DimensionValues {
  dimension: string;
  values: string[];
  truncated: boolean;
}

export interface FilterSpec {
  field: string;
  operator: Operator;
  values: (string | number | boolean)[];
}

export interface QuerySpec {
  dataset: string;
  metrics: { name: string }[];
  dimensions: { name: string }[];
  filters: FilterSpec[];
  order_by: { field: string; direction: "asc" | "desc" }[];
  limit: number;
}

export interface ResultColumn {
  name: string;
  label: string;
  role: "dimension" | "metric";
  unit: string | null;
}

export interface ChartSpec {
  kind: "stat" | "line" | "bar" | "table";
  category: string | null;
  series_dimension: string | null;
  metrics: string[];
  horizontal: boolean;
  reason: string;
}

export interface Evidence {
  dataset: string;
  dataset_label: string;
  semantic_version: string;
  source: "natural_language" | "structured";
  sql: string;
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
  filters: string[];
}

export type CellValue = string | number | boolean | null;

export interface AskResponse {
  status: "ok" | "clarify" | "unsupported";
  message: string | null;
  summary: string | null;
  assumptions: string[];
  query: QuerySpec | null;
  columns: ResultColumn[];
  rows: CellValue[][];
  chart: ChartSpec | null;
  evidence: Evidence | null;
}

export type AskBody = { question: string; dataset?: string } | { query: QuerySpec };
