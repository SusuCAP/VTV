export const API_BASE = import.meta.env.VITE_CONTROL_API_BASE_URL ?? "http://127.0.0.1:8000";

export type ApiProject = {
  id: string;
  name: string;
  target_market: string;
  locale: string;
  quality_profile: string;
  status: string;
  state_version: number;
  budget: { currency: string; warning_at: string; hard_limit: string };
};

export type ApiEpisode = {
  id: string;
  project_id: string;
  episode_no: number;
  title: string | null;
  duration_ms: number | null;
  upload_status: string;
  processing_status: string;
};

export type ApiJob = {
  id: string;
  project_id: string;
  kind: string;
  status: string;
  progress: number;
  total_stages: number;
  completed_stages: number;
};

export type ApiSnapshot = {
  project: ApiProject;
  episodes: ApiEpisode[];
  jobs: ApiJob[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${detail}`);
  }
  return response.json() as Promise<T>;
}

export async function loadLatestProject(): Promise<ApiSnapshot | null> {
  const projects = await request<ApiProject[]>("/v1/projects");
  if (projects.length === 0) return null;
  const project = projects[0];
  const [episodes, jobs] = await Promise.all([
    request<ApiEpisode[]>(`/v1/projects/${project.id}/episodes`),
    request<ApiJob[]>(`/v1/projects/${project.id}/jobs`),
  ]);
  return { project, episodes, jobs };
}

export async function startProjectAnalysis(projectId: string): Promise<string> {
  const accepted = await request<{ job_id: string }>(
    `/v1/projects/${projectId}/analysis-jobs`,
    { method: "POST" },
  );
  return accepted.job_id;
}
