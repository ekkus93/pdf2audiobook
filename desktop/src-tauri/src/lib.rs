pub mod commands;
pub mod engine;
pub mod library;
pub mod settings;

use std::time::Duration;

use tauri::{Emitter, Manager, RunEvent, WindowEvent};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(commands::Engine::default())
        .on_window_event(|window, event| {
            // Closing during a run asks first; the frontend confirms, then calls quit_app.
            if let WindowEvent::CloseRequested { api, .. } = event {
                let engine = window.state::<commands::Engine>();
                if engine.live.any_running() {
                    api.prevent_close();
                    let _ = window.emit("close-requested", ());
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::locate_engine,
            commands::describe_request,
            commands::run_engine,
            commands::get_settings,
            commands::save_settings,
            commands::library,
            commands::add_book,
            commands::start_run,
            commands::run_progress,
            commands::cancel_run,
            commands::quit_app,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            // However the app ends, no run outlives it.
            if let RunEvent::Exit = event {
                app.state::<commands::Engine>()
                    .live
                    .shutdown(Duration::from_secs(5));
            }
        });
}
