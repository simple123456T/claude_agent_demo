import { apiFetch, jsonBody } from "./client";
import type {
  AskBody,
  AskResponse,
  AuthConfig,
  DatasetInfo,
  DimensionValues,
  Me,
} from "./types";

export const fetchAuthConfig = () => apiFetch<AuthConfig>("/auth/config");

export const devLogin = (subject: string) =>
  apiFetch<{ access_token: string; subject: string }>("/auth/dev-login", jsonBody({ subject }));

export const fetchMe = () => apiFetch<Me>("/me");

export const fetchDatasets = (workspaceId: string) =>
  apiFetch<DatasetInfo[]>(`/workspaces/${workspaceId}/datasets`);

export const fetchDimensionValues = (workspaceId: string, dataset: string, dimension: string) =>
  apiFetch<DimensionValues>(
    `/workspaces/${workspaceId}/datasets/${encodeURIComponent(dataset)}/dimensions/${encodeURIComponent(dimension)}/values`,
  );

export const ask = (workspaceId: string, body: AskBody) =>
  apiFetch<AskResponse>(`/workspaces/${workspaceId}/ask`, jsonBody(body));
