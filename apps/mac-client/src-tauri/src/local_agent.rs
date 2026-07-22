use std::{
    collections::HashMap,
    fs::File,
    io::{BufReader, Read},
    path::{Path, PathBuf},
    process::Command,
};

use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter};
use tokio::io::AsyncReadExt;

const HASH_BUFFER_SIZE: usize = 4 * 1024 * 1024;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UploadEpisodeRequest {
    pub api_base: String,
    pub project_id: String,
    pub episode_no: Option<u32>,
    pub path: PathBuf,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UploadEpisodeResult {
    pub upload_id: String,
    pub episode_id: Option<String>,
    pub media_asset_id: Option<String>,
    pub ingest_job_id: Option<String>,
    pub sha256: String,
    pub probe: serde_json::Value,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct UploadProgress {
    upload_id: String,
    uploaded_bytes: u64,
    total_bytes: u64,
    part_number: u32,
}

#[derive(Debug, Serialize)]
struct MultipartInitRequest<'a> {
    project_id: &'a str,
    filename: &'a str,
    content_type: &'a str,
    size_bytes: u64,
    episode_no: Option<u32>,
    sha256: &'a str,
}

#[derive(Debug, Deserialize)]
struct PresignedPart {
    part_number: u32,
    url: String,
}

#[derive(Debug, Deserialize)]
struct MultipartInitResponse {
    upload_id: String,
    part_size_bytes: u64,
    parts: Vec<PresignedPart>,
    completed_parts: Vec<CompletedPart>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct CompletedPart {
    part_number: u32,
    size_bytes: usize,
    etag: String,
    checksum_sha256: String,
}

#[derive(Debug, Serialize)]
struct MultipartCompleteRequest<'a> {
    parts: &'a [CompletedPart],
    object_checksum_sha256: &'a str,
}

#[derive(Debug, Deserialize)]
struct MultipartCompleteResponse {
    upload_id: String,
    episode_id: Option<String>,
    media_asset_id: Option<String>,
    ingest_job_id: Option<String>,
}

pub fn probe_media(path: &Path) -> Result<serde_json::Value, String> {
    let output = Command::new("ffprobe")
        .args([
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
        ])
        .arg(path)
        .output()
        .map_err(|error| format!("failed to launch ffprobe: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "ffprobe rejected media: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    let probe: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("invalid ffprobe JSON: {error}"))?;
    let streams = probe
        .get("streams")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| "ffprobe result does not contain streams".to_string())?;
    if streams.is_empty() {
        return Err("media has no readable streams".to_string());
    }
    Ok(probe)
}

pub fn sha256_file(path: &Path) -> Result<String, String> {
    let file = File::open(path).map_err(|error| format!("failed to open media: {error}"))?;
    let mut reader = BufReader::with_capacity(HASH_BUFFER_SIZE, file);
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; HASH_BUFFER_SIZE];
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|error| format!("failed to hash media: {error}"))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn content_type(path: &Path) -> &'static str {
    match path.extension().and_then(|extension| extension.to_str()) {
        Some("mov") => "video/quicktime",
        Some("mkv") => "video/x-matroska",
        Some("webm") => "video/webm",
        _ => "video/mp4",
    }
}

#[tauri::command]
pub async fn inspect_media(path: PathBuf) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || probe_media(&path))
        .await
        .map_err(|error| format!("media probe task failed: {error}"))?
}

#[tauri::command]
pub async fn upload_episode(
    app: AppHandle,
    request: UploadEpisodeRequest,
) -> Result<UploadEpisodeResult, String> {
    let path_for_probe = request.path.clone();
    let probe_task = tauri::async_runtime::spawn_blocking(move || probe_media(&path_for_probe));
    let path_for_hash = request.path.clone();
    let hash_task = tauri::async_runtime::spawn_blocking(move || sha256_file(&path_for_hash));
    let probe = probe_task
        .await
        .map_err(|error| format!("media probe task failed: {error}"))??;
    let sha256 = hash_task
        .await
        .map_err(|error| format!("media hash task failed: {error}"))??;
    let metadata = std::fs::metadata(&request.path)
        .map_err(|error| format!("failed to read media metadata: {error}"))?;
    if metadata.len() == 0 {
        return Err("media file is empty".to_string());
    }
    let filename = request
        .path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| "media filename is not valid UTF-8".to_string())?;
    let client = Client::new();
    let api_base = request.api_base.trim_end_matches('/');
    let init = client
        .post(format!("{api_base}/v1/uploads/multipart-init"))
        .json(&MultipartInitRequest {
            project_id: &request.project_id,
            filename,
            content_type: content_type(&request.path),
            size_bytes: metadata.len(),
            episode_no: request.episode_no,
            sha256: &sha256,
        })
        .send()
        .await
        .map_err(|error| format!("multipart init request failed: {error}"))?
        .error_for_status()
        .map_err(|error| format!("multipart init rejected: {error}"))?
        .json::<MultipartInitResponse>()
        .await
        .map_err(|error| format!("invalid multipart init response: {error}"))?;

    let mut file = tokio::fs::File::open(&request.path)
        .await
        .map_err(|error| format!("failed to reopen media for upload: {error}"))?;
    let mut uploaded_bytes = 0_u64;
    let mut completed = Vec::with_capacity(init.parts.len());
    let checkpointed: HashMap<u32, CompletedPart> = init
        .completed_parts
        .into_iter()
        .map(|part| (part.part_number, part))
        .collect();
    for part in &init.parts {
        let remaining = metadata.len().saturating_sub(uploaded_bytes);
        let part_len = remaining.min(init.part_size_bytes) as usize;
        if part_len == 0 {
            return Err("object store requested more parts than the file contains".to_string());
        }
        let mut bytes = vec![0_u8; part_len];
        file.read_exact(&mut bytes)
            .await
            .map_err(|error| format!("failed reading upload part {}: {error}", part.part_number))?;
        if let Some(previous) = checkpointed.get(&part.part_number) {
            if previous.size_bytes != part_len {
                return Err(format!(
                    "checkpointed part {} size does not match local file",
                    part.part_number
                ));
            }
            uploaded_bytes += part_len as u64;
            completed.push(previous.clone());
            app.emit(
                "upload-progress",
                UploadProgress {
                    upload_id: init.upload_id.clone(),
                    uploaded_bytes,
                    total_bytes: metadata.len(),
                    part_number: part.part_number,
                },
            )
            .map_err(|error| format!("failed to emit upload progress: {error}"))?;
            continue;
        }
        let checksum = BASE64.encode(Sha256::digest(&bytes));
        let response = client
            .put(&part.url)
            .header("x-amz-checksum-sha256", &checksum)
            .body(bytes)
            .send()
            .await
            .map_err(|error| format!("upload part {} failed: {error}", part.part_number))?
            .error_for_status()
            .map_err(|error| format!("upload part {} rejected: {error}", part.part_number))?;
        let etag = response
            .headers()
            .get("etag")
            .and_then(|value| value.to_str().ok())
            .ok_or_else(|| format!("upload part {} response has no ETag", part.part_number))?
            .to_string();
        uploaded_bytes += part_len as u64;
        let completed_part = CompletedPart {
            part_number: part.part_number,
            size_bytes: part_len,
            etag,
            checksum_sha256: checksum,
        };
        client
            .put(format!(
                "{api_base}/v1/uploads/{}/parts/{}",
                init.upload_id, part.part_number
            ))
            .json(&completed_part)
            .send()
            .await
            .map_err(|error| format!("part checkpoint {} failed: {error}", part.part_number))?
            .error_for_status()
            .map_err(|error| format!("part checkpoint {} rejected: {error}", part.part_number))?;
        completed.push(completed_part);
        app.emit(
            "upload-progress",
            UploadProgress {
                upload_id: init.upload_id.clone(),
                uploaded_bytes,
                total_bytes: metadata.len(),
                part_number: part.part_number,
            },
        )
        .map_err(|error| format!("failed to emit upload progress: {error}"))?;
    }
    if uploaded_bytes != metadata.len() {
        return Err("uploaded byte count does not match file size".to_string());
    }
    let result = client
        .post(format!(
            "{api_base}/v1/uploads/{}/multipart-complete",
            init.upload_id
        ))
        .json(&MultipartCompleteRequest {
            parts: &completed,
            object_checksum_sha256: &sha256,
        })
        .send()
        .await
        .map_err(|error| format!("multipart complete request failed: {error}"))?
        .error_for_status()
        .map_err(|error| format!("multipart complete rejected: {error}"))?
        .json::<MultipartCompleteResponse>()
        .await
        .map_err(|error| format!("invalid multipart complete response: {error}"))?;
    Ok(UploadEpisodeResult {
        upload_id: result.upload_id,
        episode_id: result.episode_id,
        media_asset_id: result.media_asset_id,
        ingest_job_id: result.ingest_job_id,
        sha256,
        probe,
    })
}

#[cfg(test)]
mod tests {
    use std::{fs, time::SystemTime};

    use super::sha256_file;

    #[test]
    fn hashes_file_as_stream() {
        let unique = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let path = std::env::temp_dir().join(format!("vtv-sha-test-{unique}.txt"));
        fs::write(&path, b"VTV").expect("write fixture");
        let digest = sha256_file(&path).expect("hash file");
        fs::remove_file(path).expect("remove fixture");
        assert_eq!(
            digest,
            "1042ec1d8a31c4418bdc91636418677861119a37e1224a084488500bc6bd0271"
        );
    }
}
