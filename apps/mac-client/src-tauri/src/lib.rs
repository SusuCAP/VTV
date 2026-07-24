use serde::Serialize;
use std::path::Path;
use std::process::Command;

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
fn probe_media(path: String) -> Result<MediaProbe, String> {
    let source = Path::new(&path);
    if !source.is_file() {
        return Err(format!("media file does not exist: {path}"));
    }

    let output = Command::new("ffprobe")
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![probe_media])
        .run(tauri::generate_context!())
        .expect("error while running VTV Mac client");
}
