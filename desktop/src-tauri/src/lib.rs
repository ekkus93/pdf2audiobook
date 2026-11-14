pub mod applog;
pub mod audio;
pub mod commands;
pub mod engine;
pub mod library;
#[cfg(test)]
mod privacy;
pub mod settings;

use std::time::Duration;

use tauri::{Emitter, Manager, RunEvent, WindowEvent};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(commands::Engine::default())
        .setup(|app| {
            // The app's own, content-free log (spec D8.c), next to Tauri's other app data.
            if let Ok(folder) = app.path().app_log_dir() {
                app.state::<commands::Engine>().log.set_folder(&folder);
            }
            app.state::<commands::Engine>()
                .log
                .record(applog::Event::new("app_started"));
            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing during a run asks first; the frontend confirms, then calls quit_app.
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == commands::REVIEW_WINDOW {
                    return;
                }
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
            commands::open_review,
            commands::book_audio,
            commands::open_audio_folder,
            commands::export_zip,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            // However the app ends, no run outlives it.
            if let RunEvent::Exit = event {
                let engine = app.state::<commands::Engine>();
                engine.live.shutdown(Duration::from_secs(5));
                let review = engine
                    .review
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .take();
                if let Some(server) = review {
                    server.stop(Duration::from_secs(5));
                }
            }
        });
}
