//! The app's own log (spec D8.c): event names, CLI command names, exit codes and durations,
//! one JSON object per line, like the CLI's events. It never holds a path, a title, a message
//! or any other text from a book or the engine's output, so there is nothing private to leak.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, PoisonError};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::Serialize;

use crate::engine::result::Outcome;

/// The log file's name in the app's log folder.
pub const FILE: &str = "pdf2audiobook-desktop.log";
/// Past this size the log is moved to `<FILE>.1` (replacing any older one) and started again.
const MAX_BYTES: u64 = 512 * 1024;

/// One line of the log. Every field is a fixed name, a number or a validated code.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Event {
    /// Seconds since the Unix epoch.
    pub at: u64,
    pub event: &'static str,
    /// The CLI command, such as `convert` (`Request::name`).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub command: Option<&'static str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exit_code: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub seconds: Option<f64>,
    /// `success`, `failed`, `unreadable` or `cancelled`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub outcome: Option<&'static str>,
    /// The engine's error `reason` code (spec D2.b), kept only if it looks like one.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

impl Event {
    pub fn new(event: &'static str) -> Self {
        Self {
            at: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_or(0, |elapsed| elapsed.as_secs()),
            event,
            command: None,
            exit_code: None,
            seconds: None,
            outcome: None,
            reason: None,
        }
    }

    pub fn command(mut self, command: &'static str) -> Self {
        self.command = Some(command);
        self
    }

    /// The exit code, duration, outcome and reason of a finished engine command.
    pub fn finished(
        mut self,
        code: Option<i32>,
        elapsed: Duration,
        outcome: &Outcome,
        cancelled: bool,
    ) -> Self {
        self.exit_code = code;
        // Milliseconds are plenty, and keep the log readable.
        self.seconds = Some((elapsed.as_secs_f64() * 1000.0).round() / 1000.0);
        self.outcome = Some(match outcome {
            _ if cancelled => "cancelled",
            Outcome::Success { .. } => "success",
            Outcome::Failed { .. } => "failed",
            Outcome::Unreadable { .. } => "unreadable",
        });
        if let Outcome::Failed { error, .. } = outcome {
            self.reason = error
                .reason
                .as_deref()
                .filter(|reason| is_code(reason))
                .map(str::to_owned);
        }
        self
    }
}

/// A reason code: a short run of lowercase letters and underscores, like `review_required`.
fn is_code(text: &str) -> bool {
    !text.is_empty()
        && text.len() <= 40
        && text
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte == b'_')
}

/// Appends events to the log file once its folder is known; until then (and in tests that
/// don't set one) events are dropped. Writing never fails a command.
#[derive(Debug, Default)]
pub struct AppLog {
    file: Mutex<Option<PathBuf>>,
}

impl AppLog {
    /// Writes to `FILE` in `folder` from now on.
    pub fn set_folder(&self, folder: &Path) {
        *self.file.lock().unwrap_or_else(PoisonError::into_inner) = Some(folder.join(FILE));
    }

    pub fn record(&self, event: Event) {
        let file = self.file.lock().unwrap_or_else(PoisonError::into_inner);
        let Some(path) = file.as_ref() else {
            return;
        };
        let Ok(mut line) = serde_json::to_string(&event) else {
            return;
        };
        line.push('\n');
        if let Some(folder) = path.parent() {
            let _ = fs::create_dir_all(folder);
        }
        if fs::metadata(path).is_ok_and(|meta| meta.len() > MAX_BYTES) {
            let _ = fs::rename(path, path.with_extension("log.1"));
        }
        if let Ok(mut out) = OpenOptions::new().create(true).append(true).open(path) {
            let _ = out.write_all(line.as_bytes());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::result::EngineError;
    use tempfile::TempDir;

    fn failed(reason: Option<&str>) -> Outcome {
        Outcome::Failed {
            error: EngineError {
                kind: "AudioError".into(),
                code: 6,
                message: "Chapter 1 MARKER_TEXT".into(),
                reason: reason.map(str::to_owned),
            },
            warnings: vec!["MARKER_WARNING".into()],
        }
    }

    #[test]
    fn events_are_json_lines_of_names_codes_and_durations() {
        let temp = TempDir::new().unwrap();
        let log = AppLog::default();
        log.set_folder(temp.path());
        log.record(Event::new("run_started").command("convert"));
        log.record(Event::new("run_finished").command("convert").finished(
            Some(6),
            Duration::from_millis(2_345),
            &failed(Some("review_required")),
            false,
        ));
        let text = fs::read_to_string(temp.path().join(FILE)).unwrap();
        let lines: Vec<serde_json::Value> = text
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect();
        assert_eq!(lines.len(), 2);
        assert_eq!(lines[0]["event"], "run_started");
        assert_eq!(lines[0]["command"], "convert");
        assert_eq!(lines[1]["exit_code"], 6);
        assert_eq!(lines[1]["seconds"], 2.345);
        assert_eq!(lines[1]["outcome"], "failed");
        assert_eq!(lines[1]["reason"], "review_required");
        let keys: std::collections::BTreeSet<&str> = lines[1]
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();
        assert_eq!(
            keys,
            [
                "at",
                "command",
                "event",
                "exit_code",
                "outcome",
                "reason",
                "seconds"
            ]
            .into_iter()
            .collect()
        );
        assert!(!text.contains("MARKER"));
    }

    #[test]
    fn a_reason_that_isnt_a_code_is_left_out() {
        for reason in ["MARKER reason", "Chapter 1: MARKER", "", &"x".repeat(41)] {
            let event =
                Event::new("e").finished(None, Duration::ZERO, &failed(Some(reason)), false);
            assert_eq!(event.reason, None, "{reason}");
        }
    }

    #[test]
    fn a_stopped_run_is_logged_as_cancelled() {
        let event = Event::new("e").finished(Some(130), Duration::ZERO, &failed(None), true);
        assert_eq!(event.outcome, Some("cancelled"));
    }

    #[test]
    fn without_a_folder_nothing_is_written() {
        AppLog::default().record(Event::new("e"));
    }

    #[test]
    fn a_full_log_is_moved_aside_once() {
        let temp = TempDir::new().unwrap();
        fs::write(temp.path().join(FILE), vec![b'x'; MAX_BYTES as usize + 1]).unwrap();
        let log = AppLog::default();
        log.set_folder(temp.path());
        log.record(Event::new("after"));
        assert!(
            fs::read_to_string(temp.path().join(FILE))
                .unwrap()
                .contains("\"after\"")
        );
        assert_eq!(
            fs::metadata(temp.path().join(format!("{FILE}.1")))
                .unwrap()
                .len(),
            MAX_BYTES + 1
        );
    }
}
