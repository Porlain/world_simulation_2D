export type Coordinate = readonly [number, number];

export interface FlowTypeConfig {
  id: string;
  unit: string;
  label: string;
}

export interface DemandRange {
  min: number;
  max: number;
}

export interface LocationConfig {
  id: string;
  name: string;
  position: Coordinate;
  initial_counts: Record<string, number>;
}

export interface ConnectionConfig {
  id: string;
  from_location_id: string;
  to_location_id: string;
  path: Coordinate[];
  travel_time_ticks: number;
  capacity_per_tick: Record<string, number>;
  demand_per_tick: Record<string, DemandRange>;
}

export interface ScenarioConfig {
  schema_version: 1;
  scenario_id: string;
  name: string;
  scale: "city";
  tick_seconds: 1;
  coordinate_system: "local_xy";
  axis_orientation: "x_right_y_up";
  coordinate_unit: "scene_unit";
  flow_types: FlowTypeConfig[];
  locations: LocationConfig[];
  connections: ConnectionConfig[];
}

export interface ScenarioBundle {
  config: ScenarioConfig;
  checksum: string;
}

export interface ConnectionActivity {
  departed: number;
  arrived: number;
}

export interface SnapshotState {
  schema_version: 1;
  tick: number;
  location_counts: Record<string, Record<string, number>>;
  transit_buckets: Record<string, Record<string, number[]>>;
  connection_activity: Record<string, Record<string, ConnectionActivity>>;
  totals: Record<string, number>;
}

export type RunStatus = "running" | "paused" | "ended" | "failed";
export type RunRate = 0.5 | 1 | 2 | 4;

export interface RunRecord {
  id: string;
  scenario_id: string;
  scenario_schema_version: number;
  scenario_checksum: string;
  seed: number;
  status: RunStatus;
  rate: RunRate;
  current_tick: number;
  started_at: string;
  ended_at: string | null;
  error_code: string | null;
  error_message: string | null;
}

export interface SnapshotResponse {
  run_id: string;
  tick: number;
  state: SnapshotState;
}

export interface RunDetail {
  run: RunRecord;
  scenario: ScenarioBundle | null;
  tick_range: { min: number; max: number };
  latest_snapshot: SnapshotResponse;
}

export interface ApiErrorPayload {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  };
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T extends object>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, "network_error", "无法连接到模拟后端。");
  }

  const body = (await response.json().catch(() => null)) as T | ApiErrorPayload | null;
  if (!response.ok) {
    const error = body && "error" in body ? body.error : undefined;
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? `HTTP ${response.status}`,
      error?.details ?? {},
    );
  }
  return body as T;
}

export async function listScenarios(signal?: AbortSignal): Promise<{ items: ScenarioBundle[] }> {
  return request("/api/scenarios", { signal });
}

export async function createRun(
  scenarioId: string,
  seed?: number,
  signal?: AbortSignal,
): Promise<RunDetail> {
  return request("/api/runs", {
    method: "POST",
    body: JSON.stringify({ scenario_id: scenarioId, ...(seed === undefined ? {} : { seed }) }),
    signal,
  });
}

export async function listRuns(signal?: AbortSignal): Promise<{ items: RunRecord[] }> {
  return request("/api/runs?limit=20", { signal });
}

export async function getRun(runId: string, includeScenario: boolean, signal?: AbortSignal): Promise<RunDetail> {
  return request(`/api/runs/${encodeURIComponent(runId)}?include_scenario=${includeScenario}`, { signal });
}

export async function sendCommand(
  runId: string,
  action: "pause" | "resume" | "end" | "set_rate",
  rate?: RunRate,
  signal?: AbortSignal,
): Promise<{ run: RunRecord }> {
  return request(`/api/runs/${encodeURIComponent(runId)}/commands`, {
    method: "POST",
    body: JSON.stringify({ action, ...(action === "set_rate" ? { rate } : {}) }),
    signal,
  });
}

export async function getSnapshot(runId: string, tick: number, signal?: AbortSignal): Promise<SnapshotResponse> {
  return request(`/api/runs/${encodeURIComponent(runId)}/snapshots/${tick}`, { signal });
}
