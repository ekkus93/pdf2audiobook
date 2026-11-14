//! The chapter review server (`review --json --port 0`) behind the review window (spec D6).

use std::ffi::OsString;
use std::io::{BufRead, BufReader, Read};
use std::os::unix::process::CommandExt;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use super::process::{CliCommand, Finished};
use super::result::{EngineError, Outcome, parse};
use super::runs::RunGuard;

#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ReviewError {
    #[error("{}", error.message)]
    Failed { error: EngineError },
    #[error("The review page did not start")]
    NoAddress,
    #[error("The engine could not be started")]
    Start,
}

#[derive(Deserialize)]
struct Address {
    url: String,
    port: u16,
}

/// A running review server; stop it with [`ReviewServer::stop`].
pub struct ReviewServer {
    pub url: String,
    pub port: u16,
    child: Child,
    _guard: Option<RunGuard>,
}

impl ReviewServer {
    /// Starts the server and waits up to `timeout` for its address line.
    pub fn start(
        cli: &CliCommand,
        args: &[OsString],
        guard: Option<RunGuard>,
        timeout: Duration,
    ) -> Result<Self, ReviewError> {
        let mut child = Command::new(&cli.program)
            .args(cli.argv(args))
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .process_group(0)
            .spawn()
            .map_err(|_| ReviewError::Start)?;
        let stdout = child.stdout.take().ok_or(ReviewError::Start)?;
        let mut stderr = child.stderr.take().ok_or(ReviewError::Start)?;
        let (sender, lines) = mpsc::channel();
        thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else { break };
                if sender.send(line).is_err() {
                    break;
                }
            }
        });
        let stderr_text = thread::spawn(move || {
            let mut text = String::new();
            let _ = stderr.read_to_string(&mut text);
            text
        });
        let deadline = Instant::now() + timeout;
        loop {
            let left = deadline.saturating_duration_since(Instant::now());
            match lines.recv_timeout(left.min(Duration::from_millis(100))) {
                Ok(line) => {
                    if let Ok(address) = serde_json::from_str::<Address>(line.trim()) {
                        return Ok(Self {
                            url: address.url,
                            port: address.port,
                            child,
                            _guard: guard,
                        });
                    }
                }
                // Stdout closed without an address: the server is exiting; report why.
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    let exited = wait_until(&mut child, deadline);
                    return Err(match exited {
                        Some(code) => failure(code, stderr_text.join().unwrap_or_default()),
                        None => {
                            kill_group(&mut child);
                            ReviewError::NoAddress
                        }
                    });
                }
                Err(mpsc::RecvTimeoutError::Timeout) if Instant::now() < deadline => {
                    if let Ok(Some(status)) = child.try_wait() {
                        return Err(failure(
                            status.code(),
                            stderr_text.join().unwrap_or_default(),
                        ));
                    }
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    kill_group(&mut child);
                    return Err(ReviewError::NoAddress);
                }
            }
        }
    }

    pub fn pid(&self) -> u32 {
        self.child.id()
    }

    /// Stops the server (SIGTERM, which ends `review` like Ctrl+C); after `grace`, kills its
    /// process group. Waits until it has exited.
    pub fn stop(mut self, grace: Duration) {
        if let Ok(pid) = i32::try_from(self.child.id()) {
            // SAFETY: kill() only sends a signal; a stale pid fails harmlessly.
            unsafe {
                libc::kill(pid, libc::SIGTERM);
            }
        }
        let deadline = Instant::now() + grace;
        while Instant::now() < deadline {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(20));
        }
        kill_group(&mut self.child);
    }
}

/// Waits for the child to exit until `deadline`; its exit code, if it did (`None` inside means
/// it was ended by a signal).
fn wait_until(child: &mut Child, deadline: Instant) -> Option<Option<i32>> {
    loop {
        if let Ok(Some(status)) = child.try_wait() {
            return Some(status.code());
        }
        if Instant::now() >= deadline {
            return None;
        }
        thread::sleep(Duration::from_millis(20));
    }
}

fn failure(code: Option<i32>, stderr: String) -> ReviewError {
    let finished = Finished {
        code,
        stdout: String::new(),
        stderr,
    };
    match parse(&finished) {
        Outcome::Failed { error, .. } => ReviewError::Failed { error },
        _ => ReviewError::NoAddress,
    }
}

fn kill_group(child: &mut Child) {
    if let Ok(pid) = i32::try_from(child.id()) {
        // SAFETY: a negative pid addresses the process group the server leads.
        unsafe {
            libc::kill(-pid, libc::SIGKILL);
        }
    }
    let _ = child.wait();
}

/// The review window may only show pages from the review server itself (spec D8.b).
pub fn allowed(url: &tauri::Url, server: &tauri::Url) -> bool {
    url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && url.port_or_known_default() == server.port_or_known_default()
        && server.host_str() == Some("127.0.0.1")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::live::group_alive;
    use crate::engine::testing::write_script;
    use tempfile::TempDir;

    fn server(temp: &TempDir, body: &str, grace: Duration) -> Result<ReviewServer, ReviewError> {
        let cli = CliCommand::direct(write_script(
            temp.path(),
            "cli",
            &format!("#!/bin/sh\n{body}"),
        ));
        // Retry a spawn that hits ETXTBSY (see testing.rs).
        for _ in 0..100 {
            match ReviewServer::start(&cli, &[], None, grace) {
                Err(ReviewError::Start) => thread::sleep(Duration::from_millis(5)),
                result => return result,
            }
        }
        ReviewServer::start(&cli, &[], None, grace)
    }

    #[test]
    fn the_address_line_is_read_and_stop_ends_the_server() {
        let temp = TempDir::new().unwrap();
        let started = server(
            &temp,
            "echo 'Starting'\necho '{\"url\": \"http://127.0.0.1:41234/\", \"port\": 41234}'\ntrap 'exit 0' TERM\nwhile true; do sleep 0.05; done\n",
            Duration::from_secs(10),
        )
        .unwrap();
        assert_eq!(started.url, "http://127.0.0.1:41234/");
        assert_eq!(started.port, 41234);
        let pid = started.pid();
        assert!(group_alive(pid));

        let stopping = Instant::now();
        started.stop(Duration::from_secs(30));

        assert!(stopping.elapsed() < Duration::from_secs(5));
        assert!(!group_alive(pid));
    }

    #[test]
    fn a_server_that_ignores_sigterm_is_killed_after_the_grace_period() {
        let temp = TempDir::new().unwrap();
        let started = server(
            &temp,
            "echo '{\"url\": \"http://127.0.0.1:41235/\", \"port\": 41235}'\ntrap '' TERM\nsleep 600 &\nwhile true; do sleep 0.05; done\n",
            Duration::from_secs(10),
        )
        .unwrap();
        let pid = started.pid();
        started.stop(Duration::from_millis(300));
        assert!(!group_alive(pid), "the server or its child outlived stop()");
    }

    #[test]
    fn an_engine_error_before_the_address_is_reported() {
        let temp = TempDir::new().unwrap();
        let error = server(
            &temp,
            "echo '{\"ok\": false, \"error\": {\"type\": \"WorkspaceLockedError\", \"code\": 6, \"message\": \"Another conversion is already running\", \"reason\": \"workspace_locked\"}, \"warnings\": []}' >&2\nexit 6\n",
            Duration::from_secs(10),
        )
        .err()
        .unwrap();
        let ReviewError::Failed { error } = error else {
            panic!("expected the engine's error")
        };
        assert_eq!(error.reason.as_deref(), Some("workspace_locked"));
    }

    #[test]
    fn no_address_in_time_is_refused_and_the_server_is_stopped() {
        let temp = TempDir::new().unwrap();
        let marker = temp.path().join("pid");
        let error = server(
            &temp,
            &format!(
                "echo $$ > '{}'\nwhile true; do sleep 0.05; done\n",
                marker.display()
            ),
            Duration::from_millis(500),
        )
        .err()
        .unwrap();
        assert_eq!(error, ReviewError::NoAddress);
        let pid: u32 = std::fs::read_to_string(&marker)
            .unwrap()
            .trim()
            .parse()
            .unwrap();
        assert!(!group_alive(pid));
    }

    #[test]
    fn the_window_may_only_load_the_review_server() {
        let server: tauri::Url = "http://127.0.0.1:41234/".parse().unwrap();
        let ok = |url: &str| allowed(&url.parse().unwrap(), &server);
        assert!(ok("http://127.0.0.1:41234/"));
        assert!(ok("http://127.0.0.1:41234/api/manifest"));
        assert!(!ok("http://127.0.0.1:41235/"));
        assert!(!ok("https://127.0.0.1:41234/"));
        assert!(!ok("http://localhost:41234/"));
        assert!(!ok("https://example.com/"));
        assert!(!ok("file:///etc/passwd"));
    }
}
