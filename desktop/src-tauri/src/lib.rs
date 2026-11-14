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

/// The main window's origins: the release build's and `tauri dev`'s. Only they may read the
/// `chapter:` protocol's answers from script.
const APP_ORIGINS: [&str; 3] = [
    "tauri://localhost",
    "http://tauri.localhost",
    "http://localhost:1420",
];

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(commands::Engine::default())
        // Chapter audio for the player, from the open book's audio folder only (spec D7.a, D8.a).
        .register_asynchronous_uri_scheme_protocol(audio::SCHEME, |context, request, responder| {
            let main = context.webview_label() == "main";
            let folder = context
                .app_handle()
                .state::<commands::Engine>()
                .audio
                .folder();
            let origin = request
                .headers()
                .get("Origin")
                .and_then(|value| value.to_str().ok())
                .filter(|origin| APP_ORIGINS.contains(origin))
                .map(str::to_owned);
            let path = request.uri().path().to_owned();
            std::thread::spawn(move || {
                let (status, body) = if main {
                    audio::serve(folder.as_deref(), &path)
                } else {
                    (403, Vec::new())
                };
                let mut response = tauri::http::Response::builder().status(status);
                if status == 200 {
                    response = response.header("Content-Type", "audio/mpeg");
                }
                if let Some(origin) = origin {
                    response = response.header("Access-Control-Allow-Origin", origin);
                }
                if let Ok(response) = response.body(body) {
                    responder.respond(response);
                }
            });
        })
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
            commands::play_book_audio,
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
