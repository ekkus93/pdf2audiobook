pub mod commands;
pub mod engine;
pub mod library;
pub mod settings;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(commands::Engine::default())
        .invoke_handler(tauri::generate_handler![
            commands::locate_engine,
            commands::describe_request,
            commands::run_engine,
            commands::get_settings,
            commands::save_settings,
            commands::library,
            commands::add_book,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
