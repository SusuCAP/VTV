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

export type ApiDelivery = {
  id: string;
  project_id: string;
  episode_id: string | null;
  status: string;
  created_at: string;
  approved_at: string | null;
  state_version: number;
};

export type ApiJobProgress = {
  job_id: string;
  status: string;
  total_stages: number;
  completed_stages: number;
  failed_stages: number;
  running_stages: number;
  progress: number;
};

export type ApiCreateProject = {
  name: string;
  target_market: string;
  locale: string;
  quality_profile: string;
  budget: { currency: string; warning_at: number; hard_limit: number };
  output: {
    aspect_ratio: string;
    width: number;
    height: number;
    fps: number;
    video_codec: string;
    audio_codec: string;
  };
};

export type ApiSnapshot = {
  project: ApiProject;
  episodes: ApiEpisode[];
  jobs: ApiJob[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const workspaceId = import.meta.env.VITE_WORKSPACE_ID;
  if (!workspaceId) throw new Error("VITE_WORKSPACE_ID is required");
  const apiKey = import.meta.env.VITE_CONTROL_API_KEY;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Workspace-Id": workspaceId,
      ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
      ...init?.headers,
    },
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

export async function loadAllProjects(): Promise<ApiProject[]> {
  return request<ApiProject[]>("/v1/projects");
}

export async function createProject(payload: ApiCreateProject): Promise<ApiProject> {
  return request<ApiProject>("/v1/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function startProjectAnalysis(projectId: string): Promise<string> {
  const accepted = await request<{ job_id: string }>(
    `/v1/projects/${projectId}/analysis-jobs`,
    { method: "POST" },
  );
  return accepted.job_id;
}

export async function pauseProject(projectId: string, reason: string): Promise<ApiProject> {
  return request<ApiProject>(`/v1/projects/${projectId}:pause`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function resumeProject(projectId: string): Promise<ApiProject> {
  return request<ApiProject>(`/v1/projects/${projectId}:resume`, { method: "POST" });
}

export async function cancelProject(projectId: string, reason: string): Promise<ApiProject> {
  return request<ApiProject>(`/v1/projects/${projectId}:cancel`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function getJobProgress(projectId: string, jobId: string): Promise<ApiJobProgress> {
  return request<ApiJobProgress>(`/v1/projects/${projectId}/jobs/${jobId}/progress`);
}

export async function listDeliveries(projectId: string): Promise<ApiDelivery[]> {
  return request<ApiDelivery[]>(`/v1/projects/${projectId}/deliveries`);
}

export async function approveDelivery(
  deliveryId: string,
  expectedStateVersion: number,
  actorId = "mac-client",
): Promise<ApiDelivery> {
  return request<ApiDelivery>(`/v1/deliveries/${deliveryId}/approve`, {
    method: "POST",
    body: JSON.stringify({ expected_state_version: expectedStateVersion, actor_id: actorId }),
  });
}

export async function getDeliveryPackage(deliveryId: string): Promise<{
  download_url: string;
  manifest_url: string;
  sha256: string;
}> {
  return request(`/v1/deliveries/${deliveryId}/package`);
}
