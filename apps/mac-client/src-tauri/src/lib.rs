mod local_agent;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            local_agent::inspect_media,
            local_agent::upload_episode
        ])
        .run(tauri::generate_context!())
        .expect("error while running VTV");
}
