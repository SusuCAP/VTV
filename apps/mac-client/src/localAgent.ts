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

  // 2. 初始化分片上传
  const initResp = await fetch(`${API_BASE}/v1/uploads/multipart-init`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      episode_no: episodeNo,
      filename: file.name,
      total_size: file.size,
      total_parts: totalParts,
      content_type: file.type || "video/mp4",
    }),
  });
  if (!initResp.ok) throw new Error(`multipart-init failed: ${initResp.status}`);
  const { upload_id, presigned_parts } = await initResp.json() as {
    upload_id: string;
    presigned_parts: { part_number: number; upload_url: string }[];
  };

  // 3. 逐分片上传
  const completedParts: { partNumber: number; etag: string; sizeBytes: number }[] = [];
  let uploadedBytes = 0;

  for (let i = 0; i < totalParts; i++) {
    const start = i * PART_SIZE;
    const chunk = file.slice(start, start + PART_SIZE);
    const partNo = i + 1;
    const url = presigned_parts?.find(p => p.part_number === partNo)?.upload_url;

    if (url) {
      // 真实 presigned URL 上传
      const putResp = await fetch(url, { method: "PUT", body: chunk });
      const etag = putResp.headers.get("ETag") ?? `part-${partNo}`;
      completedParts.push({ partNumber: partNo, etag, sizeBytes: chunk.size });
    } else {
      // fallback：通过控制 API 上传分片
      const formData = new FormData();
      formData.append("file", chunk);
      const putResp = await fetch(`${API_BASE}/v1/uploads/${upload_id}/parts/${partNo}`, {
        method: "PUT",
        body: formData,
      });
      if (!putResp.ok) throw new Error(`part ${partNo} upload failed: ${putResp.status}`);
      completedParts.push({ partNumber: partNo, etag: `part-${partNo}`, sizeBytes: chunk.size });
    }

    uploadedBytes += chunk.size;
    onProgress({ uploadId: upload_id, uploadedBytes, totalBytes: file.size, partNumber: partNo });
  }

  // 4. 完成上传
  const completeResp = await fetch(`${API_BASE}/v1/uploads/${upload_id}/multipart-complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ completed_parts: completedParts }),
  });
  if (!completeResp.ok) throw new Error(`multipart-complete failed: ${completeResp.status}`);
  const result = await completeResp.json();

  return {
    uploadId: upload_id,
    episodeId: result.episode_id ?? null,
    mediaAssetId: result.media_asset_id ?? null,
    ingestJobId: result.ingest_job_id ?? null,
    sha256: result.sha256 ?? "",
  };
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
