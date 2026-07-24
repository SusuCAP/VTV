import { API_BASE, controlHeaders } from "./api";

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
  };
};

export async function probeMediaPath(path: string): Promise<MediaProbe> {
  const tauri = (window as TauriWindow).__TAURI__;
  if (!tauri) {
    throw new Error("本地媒体探测仅在 VTV Tauri 客户端中可用");
  }
  return tauri.core.invoke<MediaProbe>("probe_media", { path });
}

/** 浏览器端：用 <input type="file"> 选文件，分片上传到 VTV 控制 API */
export async function uploadEpisodeFromDialog(
  projectId: string,
  episodeNo: number | null,
  onProgress: (progress: UploadProgress) => void,
): Promise<UploadResult | null> {
  // 1. 弹出文件选择框
  const file = await pickFile();
  if (!file) return null;

  const PART_SIZE = 32 * 1024 * 1024; // 32 MiB
  const totalParts = Math.ceil(file.size / PART_SIZE);
  const objectSha256 = await sha256Hex(file);

  // 2. 初始化分片上传
  const initResp = await fetch(`${API_BASE}/v1/uploads/multipart-init`, {
    method: "POST",
    headers: controlHeaders(),
    body: JSON.stringify({
      project_id: projectId,
      episode_no: episodeNo,
      filename: file.name,
      size_bytes: file.size,
      part_size_bytes: PART_SIZE,
      sha256: objectSha256,
      content_type: file.type || "video/mp4",
    }),
  });
  if (!initResp.ok) throw new Error(`multipart-init failed: ${initResp.status}`);
  const { upload_id, parts } = await initResp.json() as {
    upload_id: string;
    parts: { part_number: number; url: string }[];
  };

  // 3. 最多 4 个并发分片直接上传对象存储，不由控制 API 代理媒体字节。
  const completedParts: {
    part_number: number;
    etag: string;
    size_bytes: number;
    checksum_sha256: string;
  }[] = [];
  let uploadedBytes = 0;

  const uploadPart = async (i: number) => {
    const start = i * PART_SIZE;
    const chunk = file.slice(start, start + PART_SIZE);
    const partNo = i + 1;
    const url = parts.find(p => p.part_number === partNo)?.url;
    if (!url) throw new Error(`missing presigned URL for part ${partNo}`);
    const checksum = await sha256Base64(chunk);
    const putResp = await fetch(url, {
      method: "PUT",
      body: chunk,
      headers: { "x-amz-checksum-sha256": checksum },
    });
    if (!putResp.ok) throw new Error(`part ${partNo} upload failed: ${putResp.status}`);
    const etag = putResp.headers.get("ETag");
    if (!etag) throw new Error(`part ${partNo} response did not include ETag`);
    completedParts.push({
      part_number: partNo,
      etag,
      size_bytes: chunk.size,
      checksum_sha256: checksum,
    });
    uploadedBytes += chunk.size;
    onProgress({ uploadId: upload_id, uploadedBytes, totalBytes: file.size, partNumber: partNo });
  };
  const pending = Array.from({ length: totalParts }, (_, index) => index);
  await Promise.all(
    Array.from({ length: Math.min(4, totalParts) }, async () => {
      while (pending.length > 0) {
        const index = pending.shift();
        if (index !== undefined) await uploadPart(index);
      }
    }),
  );

  // 4. 完成上传
  const completeResp = await fetch(`${API_BASE}/v1/uploads/${upload_id}/multipart-complete`, {
    method: "POST",
    headers: controlHeaders(),
    body: JSON.stringify({
      parts: completedParts.sort((a, b) => a.part_number - b.part_number),
      object_checksum_sha256: objectSha256,
    }),
  });
  if (!completeResp.ok) throw new Error(`multipart-complete failed: ${completeResp.status}`);
  const result = await completeResp.json();

  return {
    uploadId: upload_id,
    episodeId: result.episode_id ?? null,
    mediaAssetId: result.media_asset_id ?? null,
    ingestJobId: result.ingest_job_id ?? null,
    sha256: objectSha256,
  };
}

async function sha256Hex(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

async function sha256Base64(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  const bytes = new Uint8Array(digest);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function pickFile(): Promise<File | null> {
  return new Promise(resolve => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "video/mp4,video/quicktime,video/x-matroska,video/webm,.mp4,.mov,.mkv,.webm";
    input.onchange = () => resolve(input.files?.[0] ?? null);
    input.oncancel = () => resolve(null);
    input.click();
  });
}
