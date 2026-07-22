import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
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
};

function isTauri(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

export async function uploadEpisodeFromDialog(
  projectId: string,
  episodeNo: number | null,
  onProgress: (progress: UploadProgress) => void,
): Promise<UploadResult | null> {
  if (!isTauri()) {
    throw new Error("媒体上传仅在 Tauri macOS 客户端中可用；浏览器模式用于界面联调。 ");
  }
  const selected = await open({
    multiple: false,
    directory: false,
    filters: [{ name: "视频", extensions: ["mp4", "mov", "mkv", "webm"] }],
  });
  if (!selected) return null;
  const unlisten = await listen<UploadProgress>("upload-progress", (event) => {
    onProgress(event.payload);
  });
  try {
    return await invoke<UploadResult>("upload_episode", {
      request: {
        apiBase: API_BASE,
        projectId,
        episodeNo,
        path: selected,
      },
    });
  } finally {
    unlisten();
  }
}
