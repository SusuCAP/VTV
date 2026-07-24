use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use base64::Engine;
use futures_util::{stream, StreamExt};
use reqwest::{Client, Method, RequestBuilder, Response};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::UNIX_EPOCH;
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncReadExt, AsyncSeekExt};

const PART_SIZE: u64 = 32 * 1024 * 1024;
const MAX_CONCURRENT_PARTS: usize = 4;

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UploadRequest {
    pub source_path: String,
    pub api_base: String,
    pub workspace_id: String,
    pub api_key: Option<String>,
    pub project_id: String,
    pub episode_no: Option<u32>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResumeUploadRequest {
    pub upload_id: String,
    pub api_base: String,
    pub workspace_id: String,
    pub api_key: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UploadProgress {
    pub upload_id: String,
    pub uploaded_bytes: u64,
    pub total_bytes: u64,
    pub part_number: u32,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeUploadResult {
    pub upload_id: String,
    pub episode_id: Option<String>,
    pub media_asset_id: Option<String>,
    pub ingest_job_id: Option<String>,
    pub sha256: String,
    pub proxy_path: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PendingUpload {
    pub upload_id: String,
    pub source_path: String,
    pub project_id: String,
    pub episode_no: Option<u32>,
    pub source_size: u64,
    pub sha256: String,
    pub completed_parts: usize,
    pub updated_at: i64,
}

#[derive(Debug, Clone, Deserialize)]
struct MultipartInitResponse {
    upload_id: String,
    part_size_bytes: u64,
    parts: Vec<PresignedPart>,
    #[serde(default)]
    completed_parts: Vec<UploadPart>,
}

#[derive(Debug, Clone, Deserialize)]
struct PresignedPart {
    part_number: u32,
    url: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct UploadPart {
    part_number: u32,
    etag: String,
    size_bytes: u64,
    checksum_sha256: String,
}

#[derive(Debug, Deserialize)]
struct UploadCompleteResponse {
    upload_id: String,
    episode_id: Option<String>,
    media_asset_id: Option<String>,
    ingest_job_id: Option<String>,
}

#[derive(Debug)]
struct StoredCheckpoint {
    source_path: String,
    project_id: String,
    episode_no: Option<u32>,
    source_size: u64,
    source_modified_at: i64,
}

#[derive(Debug)]
struct SourceIdentity {
    size_bytes: u64,
    modified_at: i64,
}

#[tauri::command]
pub fn pick_media_files() -> Vec<String> {
    rfd::FileDialog::new()
        .add_filter("Video", &["mp4", "mov", "mkv", "webm"])
        .pick_files()
        .unwrap_or_default()
        .into_iter()
        .map(|path| path.to_string_lossy().into_owned())
        .collect()
}

#[tauri::command]
pub fn list_pending_uploads(app: AppHandle) -> Result<Vec<PendingUpload>, String> {
    let connection = open_checkpoint_db(&app)?;
    let mut statement = connection
        .prepare(
            "SELECT upload_id, source_path, project_id, episode_no, source_size, sha256, \
             completed_parts_json, updated_at \
             FROM upload_checkpoints WHERE status = 'UPLOADING' ORDER BY updated_at DESC",
        )
        .map_err(|error| format!("failed to query upload checkpoints: {error}"))?;
    let rows = statement
        .query_map([], |row| {
            let completed_json: String = row.get(6)?;
            let completed: Vec<UploadPart> =
                serde_json::from_str(&completed_json).unwrap_or_default();
            Ok(PendingUpload {
                upload_id: row.get(0)?,
                source_path: row.get(1)?,
                project_id: row.get(2)?,
                episode_no: row.get::<_, Option<i64>>(3)?.map(|value| value as u32),
                source_size: row.get::<_, i64>(4)? as u64,
                sha256: row.get(5)?,
                completed_parts: completed.len(),
                updated_at: row.get(7)?,
            })
        })
        .map_err(|error| format!("failed to read upload checkpoints: {error}"))?;

    let mut pending = Vec::new();
    for row in rows {
        let checkpoint = row.map_err(|error| format!("invalid upload checkpoint row: {error}"))?;
        if Path::new(&checkpoint.source_path).is_file() {
            pending.push(checkpoint);
        }
    }
    Ok(pending)
}

#[tauri::command]
pub async fn upload_episode(
    app: AppHandle,
    request: UploadRequest,
) -> Result<NativeUploadResult, String> {
    upload_path(app, request).await
}

#[tauri::command]
pub async fn resume_upload(
    app: AppHandle,
    request: ResumeUploadRequest,
) -> Result<NativeUploadResult, String> {
    let checkpoint = load_checkpoint(&app, &request.upload_id)?;
    let current = source_identity(Path::new(&checkpoint.source_path))?;
    if current.size_bytes != checkpoint.source_size
        || current.modified_at != checkpoint.source_modified_at
    {
        return Err("source file changed since the upload checkpoint was created".to_string());
    }
    upload_path(
        app,
        UploadRequest {
            source_path: checkpoint.source_path,
            api_base: request.api_base,
            workspace_id: request.workspace_id,
            api_key: request.api_key,
            project_id: checkpoint.project_id,
            episode_no: checkpoint.episode_no,
        },
    )
    .await
}

async fn upload_path(app: AppHandle, request: UploadRequest) -> Result<NativeUploadResult, String> {
    validate_control_config(&request)?;
    let source = PathBuf::from(&request.source_path);
    let initial_identity = source_identity(&source)?;
    super::probe_media(app.clone(), request.source_path.clone())?;
    let source_for_hash = source.clone();
    let sha256 = tauri::async_runtime::spawn_blocking(move || hash_file(&source_for_hash))
        .await
        .map_err(|error| format!("file hash task failed: {error}"))??;
    let proxy_path = generate_proxy(&app, &source, &sha256).await?;

    let filename = source
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| "source filename is not valid UTF-8".to_string())?;
    let client = Client::builder()
        .build()
        .map_err(|error| format!("failed to create upload client: {error}"))?;
    let init_url = api_url(&request.api_base, "/v1/uploads/multipart-init");
    let init_response = control_request(
        &client,
        Method::POST,
        &init_url,
        &request.workspace_id,
        request.api_key.as_deref(),
    )
    .json(&serde_json::json!({
        "project_id": request.project_id,
        "episode_no": request.episode_no,
        "filename": filename,
        "size_bytes": initial_identity.size_bytes,
        "part_size_bytes": PART_SIZE,
        "sha256": sha256,
        "content_type": media_type(&source),
    }))
    .send()
    .await
    .map_err(|error| format!("multipart-init request failed: {error}"))?;
    let init: MultipartInitResponse = json_response(init_response, "multipart-init").await?;

    let mut completed: BTreeMap<u32, UploadPart> = init
        .completed_parts
        .into_iter()
        .map(|part| (part.part_number, part))
        .collect();
    save_checkpoint(
        &app,
        &init.upload_id,
        &request,
        &initial_identity,
        &sha256,
        init.part_size_bytes,
        completed.values().cloned().collect(),
        "UPLOADING",
    )?;

    let total_parts = initial_identity.size_bytes.div_ceil(init.part_size_bytes) as u32;
    let urls: BTreeMap<u32, String> = init
        .parts
        .into_iter()
        .map(|part| (part.part_number, part.url))
        .collect();
    let missing: Vec<u32> = (1..=total_parts)
        .filter(|part_number| !completed.contains_key(part_number))
        .collect();
    let api_base = request.api_base.clone();
    let workspace_id = request.workspace_id.clone();
    let api_key = request.api_key.clone();
    let upload_id = init.upload_id.clone();
    let source_path = source.clone();
    let part_size = init.part_size_bytes;
    let total_size = initial_identity.size_bytes;

    let mut uploads = stream::iter(missing.into_iter().map(|part_number| {
        let client = client.clone();
        let source_path = source_path.clone();
        let upload_url = urls.get(&part_number).cloned();
        let api_base = api_base.clone();
        let workspace_id = workspace_id.clone();
        let api_key = api_key.clone();
        let upload_id = upload_id.clone();
        async move {
            let upload_url =
                upload_url.ok_or_else(|| format!("missing URL for part {part_number}"))?;
            upload_one_part(
                &client,
                &source_path,
                total_size,
                part_size,
                part_number,
                &upload_url,
                &api_base,
                &workspace_id,
                api_key.as_deref(),
                &upload_id,
            )
            .await
        }
    }))
    .buffer_unordered(MAX_CONCURRENT_PARTS);

    while let Some(result) = uploads.next().await {
        let part = result?;
        completed.insert(part.part_number, part.clone());
        let completed_parts: Vec<UploadPart> = completed.values().cloned().collect();
        save_checkpoint(
            &app,
            &init.upload_id,
            &request,
            &initial_identity,
            &sha256,
            init.part_size_bytes,
            completed_parts,
            "UPLOADING",
        )?;
        let uploaded_bytes = completed
            .values()
            .map(|completed_part| completed_part.size_bytes)
            .sum();
        app.emit(
            "upload-progress",
            UploadProgress {
                upload_id: init.upload_id.clone(),
                uploaded_bytes,
                total_bytes: initial_identity.size_bytes,
                part_number: part.part_number,
            },
        )
        .map_err(|error| format!("failed to emit upload progress: {error}"))?;
    }

    let final_identity = source_identity(&source)?;
    if final_identity.size_bytes != initial_identity.size_bytes
        || final_identity.modified_at != initial_identity.modified_at
    {
        return Err("source file changed while it was being uploaded".to_string());
    }
    if completed.len() != total_parts as usize {
        return Err("multipart upload is missing one or more completed parts".to_string());
    }

    let completed_parts: Vec<UploadPart> = completed.into_values().collect();
    let complete_url = api_url(
        &request.api_base,
        &format!("/v1/uploads/{}/multipart-complete", init.upload_id),
    );
    let complete_response = control_request(
        &client,
        Method::POST,
        &complete_url,
        &request.workspace_id,
        request.api_key.as_deref(),
    )
    .json(&serde_json::json!({
        "parts": completed_parts,
        "object_checksum_sha256": sha256,
    }))
    .send()
    .await
    .map_err(|error| format!("multipart-complete request failed: {error}"))?;
    let complete: UploadCompleteResponse =
        json_response(complete_response, "multipart-complete").await?;
    if complete.upload_id != init.upload_id {
        return Err("multipart-complete returned a different upload ID".to_string());
    }
    mark_checkpoint_completed(&app, &init.upload_id)?;

    Ok(NativeUploadResult {
        upload_id: complete.upload_id,
        episode_id: complete.episode_id,
        media_asset_id: complete.media_asset_id,
        ingest_job_id: complete.ingest_job_id,
        sha256,
        proxy_path: proxy_path.to_string_lossy().into_owned(),
    })
}

#[allow(clippy::too_many_arguments)]
async fn upload_one_part(
    client: &Client,
    source: &Path,
    total_size: u64,
    part_size: u64,
    part_number: u32,
    upload_url: &str,
    api_base: &str,
    workspace_id: &str,
    api_key: Option<&str>,
    upload_id: &str,
) -> Result<UploadPart, String> {
    let offset = (u64::from(part_number) - 1) * part_size;
    let expected_size = part_size.min(total_size.saturating_sub(offset));
    if expected_size == 0 {
        return Err(format!("part {part_number} is outside the source file"));
    }
    let mut file = tokio::fs::File::open(source)
        .await
        .map_err(|error| format!("failed to open source for part {part_number}: {error}"))?;
    file.seek(std::io::SeekFrom::Start(offset))
        .await
        .map_err(|error| format!("failed to seek to part {part_number}: {error}"))?;
    let mut bytes = vec![0_u8; expected_size as usize];
    file.read_exact(&mut bytes)
        .await
        .map_err(|error| format!("failed to read part {part_number}: {error}"))?;

    let checksum = BASE64_STANDARD.encode(Sha256::digest(&bytes));
    let response = client
        .put(upload_url)
        .header("x-amz-checksum-sha256", &checksum)
        .body(bytes)
        .send()
        .await
        .map_err(|error| format!("part {part_number} upload failed: {error}"))?;
    let response = successful_response(response, &format!("part {part_number} upload")).await?;
    let etag = response
        .headers()
        .get(reqwest::header::ETAG)
        .and_then(|value| value.to_str().ok())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| format!("part {part_number} response did not include ETag"))?
        .to_string();
    let part = UploadPart {
        part_number,
        etag,
        size_bytes: expected_size,
        checksum_sha256: checksum,
    };

    let checkpoint_url = api_url(
        api_base,
        &format!("/v1/uploads/{upload_id}/parts/{part_number}"),
    );
    let checkpoint_response =
        control_request(client, Method::PUT, &checkpoint_url, workspace_id, api_key)
            .json(&part)
            .send()
            .await
            .map_err(|error| format!("part {part_number} checkpoint failed: {error}"))?;
    successful_response(
        checkpoint_response,
        &format!("part {part_number} checkpoint"),
    )
    .await?;
    Ok(part)
}

async fn generate_proxy(app: &AppHandle, source: &Path, sha256: &str) -> Result<PathBuf, String> {
    let proxy_root = app
        .path()
        .app_cache_dir()
        .map_err(|error| format!("failed to resolve app cache directory: {error}"))?
        .join("proxies");
    fs::create_dir_all(&proxy_root)
        .map_err(|error| format!("failed to create proxy cache: {error}"))?;
    prune_proxy_cache(&proxy_root)?;
    let destination = proxy_root.join(format!("{sha256}.mp4"));
    if destination.is_file() {
        return Ok(destination);
    }
    let temporary = proxy_root.join(format!("{sha256}.partial.mp4"));
    let source = source.to_owned();
    let temporary_for_task = temporary.clone();
    let ffmpeg = super::media_tool(app, "ffmpeg");
    tauri::async_runtime::spawn_blocking(move || {
        let output = Command::new(ffmpeg)
            .args(["-v", "error", "-y", "-i"])
            .arg(&source)
            .args([
                "-vf",
                "scale=-2:540:force_original_aspect_ratio=decrease",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
            ])
            .arg(&temporary_for_task)
            .output()
            .map_err(|error| format!("failed to start ffmpeg: {error}"))?;
        if !output.status.success() {
            return Err(format!(
                "ffmpeg proxy generation failed: {}",
                String::from_utf8_lossy(&output.stderr).trim()
            ));
        }
        Ok::<(), String>(())
    })
    .await
    .map_err(|error| format!("proxy generation task failed: {error}"))??;
    fs::rename(&temporary, &destination)
        .map_err(|error| format!("failed to commit proxy cache file: {error}"))?;
    Ok(destination)
}

fn hash_file(path: &Path) -> Result<String, String> {
    let mut file =
        fs::File::open(path).map_err(|error| format!("failed to open source file: {error}"))?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 4 * 1024 * 1024];
    loop {
        let count = std::io::Read::read(&mut file, &mut buffer)
            .map_err(|error| format!("failed to hash source file: {error}"))?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn source_identity(path: &Path) -> Result<SourceIdentity, String> {
    let metadata =
        fs::metadata(path).map_err(|error| format!("failed to read source metadata: {error}"))?;
    if !metadata.is_file() || metadata.len() == 0 {
        return Err("selected media source is missing or empty".to_string());
    }
    let modified_at = metadata
        .modified()
        .map_err(|error| format!("failed to read source modification time: {error}"))?
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "source modification time predates UNIX epoch".to_string())?
        .as_secs() as i64;
    Ok(SourceIdentity {
        size_bytes: metadata.len(),
        modified_at,
    })
}

fn validate_control_config(request: &UploadRequest) -> Result<(), String> {
    if request.api_base.trim().is_empty()
        || request.workspace_id.trim().is_empty()
        || request.project_id.trim().is_empty()
    {
        return Err("control API base, workspace ID, and project ID are required".to_string());
    }
    if !request.api_base.starts_with("http://") && !request.api_base.starts_with("https://") {
        return Err("control API base must use HTTP or HTTPS".to_string());
    }
    Ok(())
}

fn control_request(
    client: &Client,
    method: Method,
    url: &str,
    workspace_id: &str,
    api_key: Option<&str>,
) -> RequestBuilder {
    let request = client
        .request(method, url)
        .header(reqwest::header::CONTENT_TYPE, "application/json")
        .header("X-Workspace-Id", workspace_id);
    match api_key.filter(|value| !value.is_empty()) {
        Some(value) => request.bearer_auth(value),
        None => request,
    }
}

async fn json_response<T: for<'de> Deserialize<'de>>(
    response: Response,
    operation: &str,
) -> Result<T, String> {
    successful_response(response, operation)
        .await?
        .json()
        .await
        .map_err(|error| format!("{operation} returned invalid JSON: {error}"))
}

async fn successful_response(response: Response, operation: &str) -> Result<Response, String> {
    if response.status().is_success() {
        return Ok(response);
    }
    let status = response.status();
    let detail = response.text().await.unwrap_or_default();
    Err(format!("{operation} failed with {status}: {detail}"))
}

fn api_url(base: &str, path: &str) -> String {
    format!("{}{}", base.trim_end_matches('/'), path)
}

fn media_type(path: &Path) -> &'static str {
    match path
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase()
        .as_str()
    {
        "mov" => "video/quicktime",
        "mkv" => "video/x-matroska",
        "webm" => "video/webm",
        _ => "video/mp4",
    }
}

fn open_checkpoint_db(app: &AppHandle) -> Result<Connection, String> {
    let data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("failed to resolve app data directory: {error}"))?;
    fs::create_dir_all(&data_dir)
        .map_err(|error| format!("failed to create app data directory: {error}"))?;
    let connection = Connection::open(data_dir.join("upload-cache.sqlite3"))
        .map_err(|error| format!("failed to open upload checkpoint cache: {error}"))?;
    connection
        .execute_batch(
            "PRAGMA journal_mode = WAL;
             CREATE TABLE IF NOT EXISTS upload_checkpoints (
               upload_id TEXT PRIMARY KEY,
               source_path TEXT NOT NULL,
               source_size INTEGER NOT NULL,
               source_modified_at INTEGER NOT NULL,
               sha256 TEXT NOT NULL,
               project_id TEXT NOT NULL,
               episode_no INTEGER,
               part_size INTEGER NOT NULL,
               completed_parts_json TEXT NOT NULL,
               status TEXT NOT NULL,
               updated_at INTEGER NOT NULL
             );
             CREATE INDEX IF NOT EXISTS ix_upload_checkpoints_status
               ON upload_checkpoints(status, updated_at);
             DELETE FROM upload_checkpoints
               WHERE status = 'COMPLETED'
                  OR updated_at < unixepoch() - 604800;",
        )
        .map_err(|error| format!("failed to initialize upload checkpoint cache: {error}"))?;
    Ok(connection)
}

#[allow(clippy::too_many_arguments)]
fn save_checkpoint(
    app: &AppHandle,
    upload_id: &str,
    request: &UploadRequest,
    identity: &SourceIdentity,
    sha256: &str,
    part_size: u64,
    completed_parts: Vec<UploadPart>,
    status: &str,
) -> Result<(), String> {
    let connection = open_checkpoint_db(app)?;
    let completed_json = serde_json::to_string(&completed_parts)
        .map_err(|error| format!("failed to serialize upload checkpoint: {error}"))?;
    connection
        .execute(
            "INSERT INTO upload_checkpoints (
               upload_id, source_path, source_size, source_modified_at, sha256,
               project_id, episode_no, part_size, completed_parts_json, status, updated_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, unixepoch())
             ON CONFLICT(upload_id) DO UPDATE SET
               source_path = excluded.source_path,
               source_size = excluded.source_size,
               source_modified_at = excluded.source_modified_at,
               sha256 = excluded.sha256,
               project_id = excluded.project_id,
               episode_no = excluded.episode_no,
               part_size = excluded.part_size,
               completed_parts_json = excluded.completed_parts_json,
               status = excluded.status,
               updated_at = excluded.updated_at",
            params![
                upload_id,
                request.source_path,
                identity.size_bytes as i64,
                identity.modified_at,
                sha256,
                request.project_id,
                request.episode_no.map(i64::from),
                part_size as i64,
                completed_json,
                status,
            ],
        )
        .map_err(|error| format!("failed to persist upload checkpoint: {error}"))?;
    Ok(())
}

fn load_checkpoint(app: &AppHandle, upload_id: &str) -> Result<StoredCheckpoint, String> {
    let connection = open_checkpoint_db(app)?;
    connection
        .query_row(
            "SELECT source_path, project_id, episode_no, source_size, source_modified_at
             FROM upload_checkpoints
             WHERE upload_id = ?1 AND status = 'UPLOADING'",
            [upload_id],
            |row| {
                Ok(StoredCheckpoint {
                    source_path: row.get(0)?,
                    project_id: row.get(1)?,
                    episode_no: row.get::<_, Option<i64>>(2)?.map(|value| value as u32),
                    source_size: row.get::<_, i64>(3)? as u64,
                    source_modified_at: row.get(4)?,
                })
            },
        )
        .map_err(|error| format!("pending upload checkpoint was not found: {error}"))
}

fn mark_checkpoint_completed(app: &AppHandle, upload_id: &str) -> Result<(), String> {
    let connection = open_checkpoint_db(app)?;
    connection
        .execute(
            "DELETE FROM upload_checkpoints WHERE upload_id = ?1",
            [upload_id],
        )
        .map_err(|error| format!("failed to clear completed upload checkpoint: {error}"))?;
    Ok(())
}

fn prune_proxy_cache(proxy_root: &Path) -> Result<(), String> {
    const MAX_PROXY_AGE_SECONDS: u64 = 30 * 24 * 60 * 60;
    let now = std::time::SystemTime::now();
    for entry in
        fs::read_dir(proxy_root).map_err(|error| format!("failed to scan proxy cache: {error}"))?
    {
        let entry = entry.map_err(|error| format!("invalid proxy cache entry: {error}"))?;
        let metadata = entry
            .metadata()
            .map_err(|error| format!("failed to read proxy cache metadata: {error}"))?;
        if !metadata.is_file() {
            continue;
        }
        let expired = metadata
            .modified()
            .ok()
            .and_then(|modified| now.duration_since(modified).ok())
            .is_some_and(|age| age.as_secs() > MAX_PROXY_AGE_SECONDS);
        if expired {
            fs::remove_file(entry.path())
                .map_err(|error| format!("failed to remove expired proxy: {error}"))?;
        }
    }
    Ok(())
}
