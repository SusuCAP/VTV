mod local_agent;

use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::Manager;

use local_agent::{list_pending_uploads, pick_media_files, resume_upload, upload_episode};

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct MediaProbe {
    filename: String,
    duration_seconds: Option<f64>,
    width: Option<u32>,
    height: Option<u32>,
    frame_rate: Option<String>,
    video_codec: Option<String>,
    audio_codec: Option<String>,
    audio_streams: u32,
}

#[tauri::command]
fn probe_media(app: tauri::AppHandle, path: String) -> Result<MediaProbe, String> {
    let source = Path::new(&path);
    if !source.is_file() {
        return Err(format!("media file does not exist: {path}"));
    }

    let output = Command::new(media_tool(&app, "ffprobe"))
        .args([
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            &path,
        ])
        .output()
        .map_err(|error| format!("failed to start ffprobe: {error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }

    let value: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("invalid ffprobe JSON: {error}"))?;
    let streams = value
        .get("streams")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| "ffprobe did not return streams".to_string())?;
    let video = streams
        .iter()
        .find(|stream| stream["codec_type"] == "video");
    let audio_streams = streams
        .iter()
        .filter(|stream| stream["codec_type"] == "audio")
        .count() as u32;

    Ok(MediaProbe {
        filename: source
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or_default()
            .to_string(),
        duration_seconds: value["format"]["duration"]
            .as_str()
            .and_then(|duration| duration.parse().ok()),
        width: video
            .and_then(|stream| stream["width"].as_u64())
            .map(|width| width as u32),
        height: video
            .and_then(|stream| stream["height"].as_u64())
            .map(|height| height as u32),
        frame_rate: video
            .and_then(|stream| stream["r_frame_rate"].as_str())
            .map(str::to_owned),
        video_codec: video
            .and_then(|stream| stream["codec_name"].as_str())
            .map(str::to_owned),
        audio_codec: streams
            .iter()
            .find(|stream| stream["codec_type"] == "audio")
            .and_then(|stream| stream["codec_name"].as_str())
            .map(str::to_owned),
        audio_streams,
    })
}

fn media_tool(app: &tauri::AppHandle, name: &str) -> PathBuf {
    let env_name = format!("VTV_{}_PATH", name.to_ascii_uppercase());
    if let Some(configured) = std::env::var_os(env_name) {
        let path = PathBuf::from(configured);
        if path.is_file() {
            return path;
        }
    }
    if let Ok(resource_dir) = app.path().resource_dir() {
        let bundled = resource_dir.join("bin").join(name);
        if bundled.is_file() {
            return bundled;
        }
    }
    for directory in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"] {
        let candidate = Path::new(directory).join(name);
        if candidate.is_file() {
            return candidate;
        }
    }
    PathBuf::from(name)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            probe_media,
            pick_media_files,
            list_pending_uploads,
            upload_episode,
            resume_upload
        ])
        .run(tauri::generate_context!())
        .expect("error while running VTV Mac client");
}
