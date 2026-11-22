export type ServiceState = "up" | "down";
export type ReadinessState = "ready" | "degraded" | "not_ready";

export interface ServiceHealth {
  status: ServiceState;
  required: boolean;
  latency_ms: number | null;
  error: string | null;
}

export interface ReadinessResponse {
  status: ReadinessState;
  services: Record<string, ServiceHealth>;
}

export async function fetchReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  const response = await fetch("/api/v1/health/ready", {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok && response.status !== 503) {
    throw new Error(`健康检查请求失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<ReadinessResponse>;
}
