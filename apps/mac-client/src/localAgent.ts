import { API_BASE } from "./api";

type UploadProgress = {
  uploadId: string;
  uploadedBytes: number;
  totalBytes: number;
  partNumber: number;
};

export type UploadResult = {
  uploadId: string;
  episodeId: string | null;
  mediaAssetId: string | null;
  ingestJobId: string | null;
  sha256: string;
  proxyPath: string;
};

export type MediaProbe = {
  filename: string;
  durationSeconds: number | null;
  width: number | null;
  height: number | null;
  frameRate: string | null;
  videoCodec: string | null;
  audioCodec: string | null;
  audioStreams: number;
};

type TauriWindow = Window & {
  __TAURI__?: {
    core: {
      invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>;
    };
    event: {
      listen<T>(
        event: string,
        handler: (event: { payload: T }) => void,
      ): Promise<() => void>;
    };
  };
};

export async function probeMediaPath(path: string): Promise<MediaProbe> {
  const tauri = (window as TauriWindow).__TAURI__;
  if (!tauri) {
    throw new Error("本地媒体探测仅在 VTV Tauri 客户端中可用");
  }
  return tauri.core.invoke<MediaProbe>("probe_media", { path });
}

type PendingUpload = {
  uploadId: string;
  sourcePath: string;
  projectId: string;
  episodeNo: number | null;
  sourceSize: number;
  sha256: string;
  completedParts: number;
  updatedAt: number;
};

function nativeControlConfig() {
  const workspaceId = import.meta.env.VITE_WORKSPACE_ID;
  if (!workspaceId) throw new Error("VITE_WORKSPACE_ID is required");
  return {
    apiBase: API_BASE,
    workspaceId,
    apiKey: import.meta.env.VITE_CONTROL_API_KEY || null,
  };
}

/** 原生 Agent：路径选择、流式哈希、SQLite 断点和直传对象存储均在 Rust 层完成。 */
export async function uploadEpisodeFromDialog(
  projectId: string,
  episodeNo: number | null,
  onProgress: (progress: UploadProgress) => void,
): Promise<UploadResult | null> {
  const tauri = (window as TauriWindow).__TAURI__;
  if (!tauri) {
    throw new Error("剧集上传仅在 VTV Tauri 客户端中可用");
  }
  const config = nativeControlConfig();
  const pending = await tauri.core.invoke<PendingUpload[]>("list_pending_uploads");
  const resumable = pending.find(item => item.projectId === projectId);
  const unlisten = await tauri.event.listen<UploadProgress>(
    "upload-progress",
    event => onProgress(event.payload),
  );
  try {
    if (
      resumable
      && window.confirm(
        `检测到未完成上传（已完成 ${resumable.completedParts} 个分片），是否继续？`,
      )
    ) {
      return await tauri.core.invoke<UploadResult>("resume_upload", {
        request: {
          uploadId: resumable.uploadId,
          ...config,
        },
      });
    }

    const paths = await tauri.core.invoke<string[]>("pick_media_files");
    const sourcePath = paths[0];
    if (!sourcePath) return null;
    return await tauri.core.invoke<UploadResult>("upload_episode", {
      request: {
        sourcePath,
        projectId,
        episodeNo,
        ...config,
      },
    });
  } finally {
    unlisten();
  }
}
