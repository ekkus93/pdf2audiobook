//! Spec D8.c: a book whose title, file name and text carry marker strings leaves none of them in
//! the app's log or in any error the bridge shows, even when the engine echoes them.

use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use tempfile::TempDir;

use crate::applog::{self, AppLog, Event};
use crate::audio;
use crate::engine::live::{LiveRuns, Progress};
use crate::engine::process::{CliCommand, Runner};
use crate::engine::request::{EnvVarName, Request};
use crate::engine::result::parse;
use crate::engine::runs::WorkspaceRuns;
use crate::engine::testing::{TestRunner, write_script};

const TITLE: &str = "TITLEMARKER4471";
const FILE_NAME: &str = "FILEMARKER9083";
const TEXT: &str = "TEXTMARKER2265";
const MARKERS: [&str; 3] = [TITLE, FILE_NAME, TEXT];

fn assert_clean(what: &str, text: &str) {
    for marker in MARKERS {
        assert!(!text.contains(marker), "{what} contains {marker}: {text}");
    }
}

/// A fake CLI that echoes every marker on stdout and stderr, and fails with them in its
/// message, its warnings and a reason that isn't a code.
fn noisy_cli(folder: &std::path::Path) -> CliCommand {
    let error = format!(
        r#"{{"ok": false, "error": {{"type": "AudioError", "code": 6, "message": "{TITLE} {TEXT}", "reason": "{FILE_NAME} x"}}, "warnings": ["{TEXT}"]}}"#
    );
    let script =
        format!("#!/bin/sh\necho '{TITLE} {FILE_NAME} {TEXT}'\necho '{error}' >&2\nexit 6\n");
    CliCommand::direct(write_script(folder, "cli", &script))
}

/// A workspace, manifest and book whose names carry the markers.
fn book(temp: &TempDir) -> (PathBuf, PathBuf, PathBuf) {
    let workspace = temp.path().join(format!("{TITLE}-workspace"));
    fs::create_dir_all(workspace.join("reports")).unwrap();
    let manifest = workspace.join("manifest.json");
    fs::write(
        &manifest,
        format!(r#"{{"title": "{TITLE}", "text": "{TEXT}"}}"#),
    )
    .unwrap();
    let source = temp.path().join(format!("{FILE_NAME}.pdf"));
    fs::write(&source, TEXT).unwrap();
    (workspace, manifest, source)
}

#[test]
fn the_app_log_holds_no_marker_from_requests_or_engine_output() {
    let temp = TempDir::new().unwrap();
    let (workspace, manifest, source) = book(&temp);
    let cli = noisy_cli(temp.path());
    let log = Arc::new(AppLog::default());
    log.set_folder(&temp.path().join("logs"));

    // A one-shot command, as run_engine logs it.
    let request = Request::Inspect {
        source: source.clone(),
        pdf_password_env: None,
    };
    let started = Instant::now();
    let done = TestRunner.run(&cli, &request.args().unwrap()).unwrap();
    let outcome = parse(&done);
    log.record(
        Event::new("engine_command")
            .command(request.name())
            .finished(done.code, started.elapsed(), &outcome, false),
    );

    // A live run, as start_run logs it.
    let request = Request::Recover {
        manifest: manifest.clone(),
        back_up_changed: true,
    };
    let runs = LiveRuns::default();
    let guard = WorkspaceRuns::new()
        .try_start(&workspace, &request)
        .unwrap();
    let hook_log = Arc::clone(&log);
    let name = request.name();
    let id = loop {
        let hook_log = Arc::clone(&hook_log);
        match runs.start_with_hook(
            &cli,
            &request.args().unwrap(),
            &workspace,
            None,
            Box::new(move |exit| {
                hook_log.record(Event::new("run_finished").command(name).finished(
                    exit.code,
                    exit.elapsed,
                    exit.outcome,
                    exit.cancelled,
                ))
            }),
        ) {
            Ok(id) => break id,
            Err(_) => thread::sleep(Duration::from_millis(5)),
        }
    };
    drop(guard);
    log.record(Event::new("run_started").command(name));
    let deadline = Instant::now() + Duration::from_secs(10);
    while !matches!(runs.progress(id).unwrap(), Progress::Finished { .. }) {
        assert!(Instant::now() < deadline, "timed out");
        thread::sleep(Duration::from_millis(20));
    }
    // The hook runs right after the result is stored.
    let path = temp.path().join("logs").join(applog::FILE);
    let deadline = Instant::now() + Duration::from_secs(5);
    while fs::read_to_string(&path)
        .unwrap_or_default()
        .lines()
        .count()
        < 3
    {
        assert!(Instant::now() < deadline, "the run's exit was not logged");
        thread::sleep(Duration::from_millis(20));
    }

    let text = fs::read_to_string(&path).unwrap();
    assert_clean("the app log", &text);
    assert!(
        !text.contains(&*temp.path().to_string_lossy()),
        "the log holds a path"
    );
    let events: Vec<serde_json::Value> = text
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(events.len(), 3);
    assert!(
        events.iter().all(|event| event.get("reason").is_none()),
        "a non-code reason was kept"
    );
    assert_eq!(events[0]["command"], "inspect");
    assert_eq!(events[0]["exit_code"], 6);
}

#[test]
fn bridge_errors_hold_no_marker() {
    let temp = TempDir::new().unwrap();
    let (workspace, manifest, source) = book(&temp);
    let mut messages: Vec<String> = Vec::new();

    // Requests the bridge refuses before running anything.
    let bad_path = PathBuf::from(format!("/books/{FILE_NAME}\0{TITLE}.pdf"));
    for request in [
        Request::Inspect {
            source: bad_path.clone(),
            pdf_password_env: None,
        },
        Request::Recover {
            manifest: PathBuf::new(),
            back_up_changed: false,
        },
    ] {
        messages.push(request.args().unwrap_err().to_string());
    }
    messages.push(
        serde_json::from_str::<EnvVarName>(&format!("\"{TEXT} x\""))
            .unwrap_err()
            .to_string(),
    );

    // Another task holds the book.
    let runs = WorkspaceRuns::new();
    let convert = Request::Recover {
        manifest: manifest.clone(),
        back_up_changed: false,
    };
    let _held = runs.try_start(&workspace, &convert).unwrap();
    messages.push(
        runs.try_start(&workspace, &convert)
            .unwrap_err()
            .to_string(),
    );

    // Audio and export refusals.
    messages.push(audio::chapter_files(&workspace).unwrap_err().to_string());
    fs::create_dir_all(workspace.join("audio")).unwrap();
    fs::write(
        workspace.join("audio").join(format!("001 - {TITLE}.mp3")),
        TEXT,
    )
    .unwrap();
    messages.push(
        audio::export_zip(
            &workspace,
            &workspace.join(format!("{FILE_NAME}.zip")),
            TITLE,
            Some(&source),
        )
        .unwrap_err()
        .to_string(),
    );
    messages.push(
        audio::export_zip(
            &workspace,
            &temp.path().join("missing").join("x.zip"),
            TITLE,
            None,
        )
        .unwrap_err()
        .to_string(),
    );

    // An engine run that can't start.
    let missing = CliCommand::direct(temp.path().join(format!("{FILE_NAME}-cli")));
    messages.push(
        LiveRuns::default()
            .start(&missing, &[], &workspace, None)
            .unwrap_err()
            .to_string(),
    );

    assert!(messages.len() >= 8);
    for message in &messages {
        assert_clean("a bridge error", message);
        assert!(
            !message.contains(&*temp.path().to_string_lossy()),
            "{message}"
        );
    }
}

/// Verification results hold book text (expected and heard excerpts): they reach the
/// frontend, but never the app's log (audio verification spec §7).
#[test]
fn verification_excerpts_never_reach_the_app_log() {
    let temp = TempDir::new().unwrap();
    let (workspace, manifest, _) = book(&temp);
    let report = format!(
        r#"{{"schema_version": 1, "report": {{"chapters": [{{"number": 1, "flags": [{{"expected": "{TEXT}", "heard": {{"vosk": "{TITLE}"}}, "before": "{FILE_NAME}"}}]}}]}}, "stale": [], "warnings": []}}"#
    );
    let cli = CliCommand::direct(write_script(
        temp.path(),
        "cli",
        &format!("#!/bin/sh\necho '{report}'\n"),
    ));
    let log = AppLog::default();
    log.set_folder(&temp.path().join("logs"));
    for request in [
        Request::AudioReport {
            manifest: manifest.clone(),
        },
        Request::VerifyAudio {
            manifest: manifest.clone(),
            chapters: vec![1],
            models: vec![],
        },
        Request::Resynthesize {
            voice_clone: Default::default(),
            tts_provider: None,
            tts_model: None,
            manifest: manifest.clone(),
            chapters: vec![1],
            voice: Some("Jasper".into()),
            speed: None,
            temperature: None,
            verify_audio: Some(true),
        },
    ] {
        let done = TestRunner.run(&cli, &request.args().unwrap()).unwrap();
        let outcome = parse(&done);
        assert!(
            matches!(&outcome, crate::engine::result::Outcome::Success { result } if result.to_string().contains(TEXT)),
            "the excerpt reaches the frontend"
        );
        log.record(
            Event::new("engine_command")
                .command(request.name())
                .finished(done.code, Duration::from_millis(5), &outcome, false),
        );
    }
    let text = fs::read_to_string(temp.path().join("logs").join(applog::FILE)).unwrap();
    assert_eq!(text.lines().count(), 3);
    assert_clean("the app log", &text);
    assert!(!text.contains(&*workspace.to_string_lossy()));
}

/// Reference markers never enter Details/Debug/events, on successful or failed clone repair.
#[test]
fn clone_reference_markers_stay_out_of_details_errors_and_event_logs() {
    use crate::commands::display_command;
    use crate::engine::request::{CloneOptions, TtsProvider};

    let temp = TempDir::new().unwrap();
    let manifest = temp.path().join("manifest.json");
    let log = AppLog::default();
    log.set_folder(&temp.path().join("logs"));
    for mode in ["success", "structured_error", "unreadable"] {
        let mut request = Request::Resynthesize {
            voice_clone: CloneOptions {
                clone_voice: Some(true),
                reference_audio: Some(temp.path().join(format!("{FILE_NAME}.wav"))),
                reference_text: Some(TEXT.into()),
                ..Default::default()
            },
            tts_provider: Some(TtsProvider::Kitten),
            tts_model: Some("kitten2".into()),
            manifest: manifest.clone(),
            chapters: vec![1],
            voice: None,
            speed: None,
            temperature: None,
            verify_audio: None,
        };
        assert_clean("request debug", &format!("{request:?}"));
        let draft = request.prepare_transcript().unwrap().unwrap();
        let args = request.args().unwrap();
        assert_clean(
            "command Details",
            &display_command(&CliCommand::direct("pdf2audiobook"), &args),
        );
        assert!(!args.iter().any(|a| a.to_string_lossy().contains(TEXT)));
        let cli = match mode {
            "success" => CliCommand::direct(write_script(
                temp.path(),
                "success-cli",
                "#!/bin/sh\nprintf '{}'\n",
            )),
            "structured_error" => noisy_cli(temp.path()),
            _ => CliCommand::direct(write_script(
                temp.path(),
                "unreadable-cli",
                &format!("#!/bin/sh\necho '{FILE_NAME} {TEXT}' >&2\nexit 6\n"),
            )),
        };
        let done = TestRunner.run(&cli, &args).unwrap();
        let outcome = parse(&done);
        // Structured errors come from the trusted CLI protocol; unstructured stderr
        // becomes a generic unreadable result and must never reach the frontend.
        if mode == "unreadable" {
            assert!(matches!(
                outcome,
                crate::engine::result::Outcome::Unreadable { .. }
            ));
            assert_clean("generic result", &serde_json::to_string(&outcome).unwrap());
        }
        log.record(
            Event::new("engine_command")
                .command(request.name())
                .finished(done.code, Duration::from_millis(1), &outcome, false),
        );
        drop(draft);
    }
    let text = fs::read_to_string(temp.path().join("logs").join(applog::FILE)).unwrap();
    assert_clean("clone event log", &text);
    assert_eq!(text.lines().count(), 3);
    assert!(!text.contains(&*temp.path().to_string_lossy()));
}
