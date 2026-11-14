//! Long runs (analyze, convert): start, watch, cancel, and never leave a process behind
//! (spec D5).

use std::collections::HashMap;
use std::ffi::OsString;
use std::io::Read;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, PoisonError};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;

use super::process::{CliCommand, Finished, use_host_environment};
use super::result::{Outcome, parse};
use super::runs::RunGuard;
use crate::library;

/// How long a cancelled run gets to stop cleanly before its process group is killed.
pub const CANCEL_GRACE: Duration = Duration::from_secs(30);

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum Progress {
    /// Still running; `status` is the workspace's `run_status.json`, if written yet.
    Running {
        status: Option<serde_json::Value>,
        cancelling: bool,
    },
    /// The child exited. A `run_status.json` left at `running` is reported as `stopped`.
    Finished {
        status: Option<serde_json::Value>,
        outcome: Outcome,
        cancelled: bool,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error, Serialize)]
pub enum LiveError {
    #[error("That task is no longer known")]
    UnknownRun,
    #[error("The engine could not be started")]
    Start,
}

struct Live {
    pid: u32,
    workspace: PathBuf,
    cancelling: bool,
    done: Option<Outcome>,
    cancelled: bool,
    _guard: Option<RunGuard>,
}

/// How a live run ended, for the app's log.
pub struct Exit<'a> {
    pub code: Option<i32>,
    pub elapsed: Duration,
    pub outcome: &'a Outcome,
    pub cancelled: bool,
}

/// Called once when a live run's child has exited.
pub type ExitHook = Box<dyn FnOnce(Exit<'_>) + Send>;

/// Every run this app started, by ID.
#[derive(Default)]
pub struct LiveRuns {
    next: AtomicU64,
    runs: Mutex<HashMap<u64, Arc<Mutex<Live>>>>,
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

impl LiveRuns {
    /// Starts `cli args` in its own process group and returns at once with the run's ID.
    /// `guard` (from `WorkspaceRuns::try_start`) is held until the child exits.
    pub fn start(
        &self,
        cli: &CliCommand,
        args: &[OsString],
        workspace: &Path,
        guard: Option<RunGuard>,
    ) -> Result<u64, LiveError> {
        self.start_with_hook(cli, args, workspace, guard, Box::new(|_| {}))
    }

    /// [`LiveRuns::start`], calling `on_exit` once the child has exited and its result is known.
    pub fn start_with_hook(
        &self,
        cli: &CliCommand,
        args: &[OsString],
        workspace: &Path,
        guard: Option<RunGuard>,
        on_exit: ExitHook,
    ) -> Result<u64, LiveError> {
        let started = Instant::now();
        let mut child = use_host_environment(&mut Command::new(&cli.program))
            .args(cli.argv(args))
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .process_group(0)
            .spawn()
            .map_err(|_| LiveError::Start)?;
        let id = self.next.fetch_add(1, Ordering::Relaxed) + 1;
        let live = Arc::new(Mutex::new(Live {
            pid: child.id(),
            workspace: workspace.to_path_buf(),
            cancelling: false,
            done: None,
            cancelled: false,
            _guard: guard,
        }));
        lock(&self.runs).insert(id, Arc::clone(&live));
        let stdout = child.stdout.take().map(drain);
        let stderr = child.stderr.take().map(drain);
        thread::spawn(move || {
            let code = child.wait().ok().and_then(|status| status.code());
            let finished = Finished {
                code,
                stdout: stdout
                    .map(|reader| reader.join().unwrap_or_default())
                    .unwrap_or_default(),
                stderr: stderr
                    .map(|reader| reader.join().unwrap_or_default())
                    .unwrap_or_default(),
            };
            let outcome = parse(&finished);
            let cancelled = {
                let mut live = lock(&live);
                live.done = Some(outcome.clone());
                live._guard = None;
                live.cancelled
            };
            on_exit(Exit {
                code,
                elapsed: started.elapsed(),
                outcome: &outcome,
                cancelled,
            });
        });
        Ok(id)
    }

    pub fn progress(&self, id: u64) -> Result<Progress, LiveError> {
        let live = Arc::clone(lock(&self.runs).get(&id).ok_or(LiveError::UnknownRun)?);
        let live = lock(&live);
        let mut status = library::run_status(&live.workspace);
        Ok(match &live.done {
            None => Progress::Running {
                status,
                cancelling: live.cancelling,
            },
            Some(outcome) => {
                if let Some(object) = status.as_mut().and_then(|value| value.as_object_mut())
                    && object.get("state").and_then(|state| state.as_str()) == Some("running")
                {
                    object.insert("state".into(), "stopped".into());
                }
                Progress::Finished {
                    status,
                    outcome: outcome.clone(),
                    cancelled: live.cancelled,
                }
            }
        })
    }

    /// Whether a run this app started is still working on `workspace`.
    pub fn is_live(&self, workspace: &Path) -> bool {
        let key = workspace
            .canonicalize()
            .unwrap_or_else(|_| workspace.to_path_buf());
        lock(&self.runs).values().any(|live| {
            let live = lock(live);
            live.done.is_none()
                && live
                    .workspace
                    .canonicalize()
                    .unwrap_or_else(|_| live.workspace.clone())
                    == key
        })
    }

    pub fn any_running(&self) -> bool {
        lock(&self.runs)
            .values()
            .any(|live| lock(live).done.is_none())
    }

    /// Asks the run to stop (SIGTERM, which the CLI treats like Ctrl+C); after `grace`, kills its
    /// whole process group. Returns at once.
    pub fn cancel(self: &Arc<Self>, id: u64, grace: Duration) -> Result<(), LiveError> {
        let live = Arc::clone(lock(&self.runs).get(&id).ok_or(LiveError::UnknownRun)?);
        let pid = {
            let mut state = lock(&live);
            if state.done.is_some() || state.cancelling {
                return Ok(());
            }
            state.cancelling = true;
            state.cancelled = true;
            state.pid
        };
        signal(pid, libc::SIGTERM);
        thread::spawn(move || {
            let deadline = Instant::now() + grace;
            while Instant::now() < deadline {
                if lock(&live).done.is_some() {
                    return;
                }
                thread::sleep(Duration::from_millis(50));
            }
            if lock(&live).done.is_none() {
                signal_group(pid, libc::SIGKILL);
            }
        });
        Ok(())
    }

    /// Stops every run: SIGTERM, then after `grace` the process groups are killed, and waits
    /// until they are gone. Used when the app closes (spec D5.d).
    pub fn shutdown(&self, grace: Duration) {
        let runs: Vec<_> = lock(&self.runs).values().cloned().collect();
        let pids: Vec<u32> = runs
            .iter()
            .filter_map(|live| {
                let mut state = lock(live);
                (state.done.is_none()).then(|| {
                    state.cancelling = true;
                    state.cancelled = true;
                    state.pid
                })
            })
            .collect();
        for pid in &pids {
            signal(*pid, libc::SIGTERM);
        }
        let deadline = Instant::now() + grace;
        while Instant::now() < deadline && runs.iter().any(|live| lock(live).done.is_none()) {
            thread::sleep(Duration::from_millis(50));
        }
        for pid in &pids {
            signal_group(*pid, libc::SIGKILL);
        }
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline && runs.iter().any(|live| lock(live).done.is_none()) {
            thread::sleep(Duration::from_millis(20));
        }
    }
}

fn drain(mut stream: impl Read + Send + 'static) -> thread::JoinHandle<String> {
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let _ = stream.read_to_end(&mut bytes);
        String::from_utf8_lossy(&bytes).into_owned()
    })
}

fn signal(pid: u32, signal: i32) {
    if let Ok(pid) = i32::try_from(pid) {
        // SAFETY: kill() only sends a signal; a stale pid fails harmlessly with ESRCH.
        unsafe {
            libc::kill(pid, signal);
        }
    }
}

/// Signals the process group the run leads (it was started with `process_group(0)`).
fn signal_group(pid: u32, signal: i32) {
    if let Ok(pid) = i32::try_from(pid) {
        // SAFETY: as above; a negative pid addresses the whole process group.
        unsafe {
            libc::kill(-pid, signal);
        }
    }
}

/// Whether any process in the group led by `pid` is still running. Zombies don't count: they
/// have stopped and only wait for a parent to reap them (in containers whose init doesn't reap,
/// they can linger indefinitely).
pub fn group_alive(pid: u32) -> bool {
    let Ok(entries) = std::fs::read_dir("/proc") else {
        return false;
    };
    entries.filter_map(Result::ok).any(|entry| {
        let Ok(stat) = std::fs::read_to_string(entry.path().join("stat")) else {
            return false;
        };
        // After the command name in parentheses come: state, ppid, pgrp, ...
        let Some((_, rest)) = stat.rsplit_once(')') else {
            return false;
        };
        let fields: Vec<&str> = rest.split_whitespace().collect();
        matches!(fields.as_slice(), [state, _ppid, pgrp, ..] if *state != "Z" && pgrp.parse() == Ok(pid))
    })
}

impl LiveRuns {
    /// The process group leader of a run, for tests and diagnostics.
    pub fn pid(&self, id: u64) -> Option<u32> {
        lock(&self.runs).get(&id).map(|live| lock(live).pid)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::request::{BookOptions, Request};
    use crate::engine::runs::WorkspaceRuns;
    use crate::engine::testing::write_script;
    use std::fs;
    use tempfile::TempDir;

    fn wait_for(mut done: impl FnMut() -> bool, seconds: u64) {
        let deadline = Instant::now() + Duration::from_secs(seconds);
        while !done() {
            assert!(Instant::now() < deadline, "timed out");
            thread::sleep(Duration::from_millis(20));
        }
    }

    fn start_script(runs: &Arc<LiveRuns>, temp: &TempDir, body: &str) -> (u64, PathBuf) {
        let workspace = temp.path().join("workspace");
        fs::create_dir_all(workspace.join("reports")).unwrap();
        let script = format!("#!/bin/sh\nWS='{}'\n{body}", workspace.display());
        // Retry the spawn on ETXTBSY, as TestRunner does (see testing.rs).
        let cli = CliCommand::direct(write_script(temp.path(), "cli", &script));
        let mut attempt = 0;
        loop {
            match runs.start(&cli, &[], &workspace, None) {
                Ok(id) => return (id, workspace),
                Err(_) if attempt < 100 => {
                    attempt += 1;
                    thread::sleep(Duration::from_millis(5));
                }
                Err(error) => panic!("{error}"),
            }
        }
    }

    fn finished(runs: &LiveRuns, id: u64) -> Progress {
        let mut last = None;
        wait_for(
            || {
                last = Some(runs.progress(id).unwrap());
                matches!(last, Some(Progress::Finished { .. }))
            },
            30,
        );
        last.unwrap()
    }

    #[test]
    fn progress_follows_run_status_until_the_result() {
        let temp = TempDir::new().unwrap();
        let runs = Arc::new(LiveRuns::default());
        let (id, _) = start_script(
            &runs,
            &temp,
            r#"echo '{"state": "running", "stage": {"name": "Synthesizing speech", "done": 1, "total": 4}}' > "$WS/reports/run_status.json"
while [ ! -e "$WS/go" ]; do sleep 0.02; done
echo '{"state": "completed", "stage": null}' > "$WS/reports/run_status.json"
echo '{"mp3_files": [], "warnings": []}'
"#,
        );
        wait_for(
            || {
                matches!(
                    runs.progress(id),
                    Ok(Progress::Running {
                        status: Some(_),
                        ..
                    })
                )
            },
            10,
        );
        let Progress::Running {
            status: Some(status),
            cancelling,
        } = runs.progress(id).unwrap()
        else {
            panic!("expected a running stage")
        };
        assert_eq!(status["stage"]["done"], 1);
        assert!(!cancelling);
        assert!(runs.any_running());

        fs::write(temp.path().join("workspace/go"), "").unwrap();

        let Progress::Finished {
            status,
            outcome,
            cancelled,
        } = finished(&runs, id)
        else {
            unreachable!()
        };
        assert_eq!(status.unwrap()["state"], "completed");
        assert!(matches!(outcome, Outcome::Success { .. }));
        assert!(!cancelled);
        assert!(!runs.any_running());
    }

    #[test]
    fn a_run_left_running_in_run_status_is_reported_stopped_once_the_child_exits() {
        let temp = TempDir::new().unwrap();
        let runs = Arc::new(LiveRuns::default());
        let (id, _) = start_script(
            &runs,
            &temp,
            "echo '{\"state\": \"running\"}' > \"$WS/reports/run_status.json\"\nexit 9\n",
        );
        let Progress::Finished {
            status, outcome, ..
        } = finished(&runs, id)
        else {
            unreachable!()
        };
        assert_eq!(status.unwrap()["state"], "stopped");
        assert_eq!(outcome, Outcome::Unreadable { exit_code: Some(9) });
    }

    #[test]
    fn cancel_stops_a_cooperative_run_with_its_own_result() {
        let temp = TempDir::new().unwrap();
        let runs = Arc::new(LiveRuns::default());
        let (id, _) = start_script(
            &runs,
            &temp,
            r#"trap 'echo "{\"ok\": false, \"error\": {\"type\": \"Interrupted\", \"code\": 130, \"message\": \"Interrupted\"}, \"warnings\": []}" >&2; exit 130' TERM
echo started > "$WS/started"
while true; do sleep 0.05; done
"#,
        );
        wait_for(|| temp.path().join("workspace/started").exists(), 10);

        let started = Instant::now();
        runs.cancel(id, CANCEL_GRACE).unwrap();
        assert!(matches!(
            runs.progress(id).unwrap(),
            Progress::Running {
                cancelling: true,
                ..
            } | Progress::Finished { .. }
        ));

        let Progress::Finished {
            outcome, cancelled, ..
        } = finished(&runs, id)
        else {
            unreachable!()
        };
        assert!(
            started.elapsed() < Duration::from_secs(10),
            "a clean stop doesn't wait for the grace period"
        );
        assert!(cancelled);
        let Outcome::Failed { error, .. } = outcome else {
            panic!("expected the Interrupted error")
        };
        assert_eq!((error.kind.as_str(), error.code), ("Interrupted", 130));
    }

    #[test]
    fn cancel_kills_a_run_that_ignores_the_signal_after_the_grace_period() {
        let temp = TempDir::new().unwrap();
        let runs = Arc::new(LiveRuns::default());
        let (id, _) = start_script(
            &runs,
            &temp,
            "trap '' TERM\necho started > \"$WS/started\"\nwhile true; do sleep 0.05; done\n",
        );
        wait_for(|| temp.path().join("workspace/started").exists(), 10);
        let pid = runs.pid(id).unwrap();

        runs.cancel(id, Duration::from_millis(500)).unwrap();
        thread::sleep(Duration::from_millis(200));
        assert!(matches!(
            runs.progress(id).unwrap(),
            Progress::Running {
                cancelling: true,
                ..
            }
        ));

        let Progress::Finished {
            outcome, cancelled, ..
        } = finished(&runs, id)
        else {
            unreachable!()
        };
        assert_eq!(outcome, Outcome::Unreadable { exit_code: None });
        assert!(cancelled);
        wait_for(|| !group_alive(pid), 5);
    }

    #[test]
    fn shutdown_leaves_no_process_behind() {
        let temp = TempDir::new().unwrap();
        let runs = Arc::new(LiveRuns::default());
        // A run that ignores SIGTERM and has started a grandchild of its own.
        let (id, _) = start_script(
            &runs,
            &temp,
            "trap '' TERM\nsleep 600 &\necho $! > \"$WS/grandchild\"\nwhile true; do sleep 0.05; done\n",
        );
        let marker = temp.path().join("workspace/grandchild");
        wait_for(
            || fs::read_to_string(&marker).is_ok_and(|text| text.ends_with('\n')),
            10,
        );
        let pid = runs.pid(id).unwrap();
        assert!(group_alive(pid));

        runs.shutdown(Duration::from_millis(300));

        assert!(!group_alive(pid), "a process of the run outlived shutdown");
        assert!(!runs.any_running());
    }

    #[test]
    fn a_write_guard_is_held_until_the_run_ends() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path().join("workspace");
        fs::create_dir_all(&workspace).unwrap();
        let claims = WorkspaceRuns::new();
        let request = Request::Analyze {
            book: "/b.pdf".into(),
            options: BookOptions::default(),
        };
        let runs = Arc::new(LiveRuns::default());
        let cli = CliCommand::direct(write_script(
            temp.path(),
            "cli",
            "#!/bin/sh\nwhile [ ! -e \"$0.go\" ]; do sleep 0.02; done\n",
        ));
        let mut started = None;
        for _ in 0..100 {
            // A failed spawn (ETXTBSY, see testing.rs) drops its guard, so claim again each time.
            let guard = claims.try_start(&workspace, &request).unwrap();
            if let Ok(id) = runs.start(&cli, &[], &workspace, Some(guard)) {
                started = Some(id);
                break;
            }
            thread::sleep(Duration::from_millis(5));
        }
        let id = started.unwrap();
        assert!(claims.is_busy(&workspace));
        assert!(runs.is_live(&workspace));
        fs::write(format!("{}.go", temp.path().join("cli").display()), "").unwrap();
        finished(&runs, id);
        assert!(!claims.is_busy(&workspace));
        assert!(!runs.is_live(&workspace));
    }

    #[test]
    fn an_unknown_run_is_refused() {
        let runs = Arc::new(LiveRuns::default());
        assert_eq!(runs.progress(7), Err(LiveError::UnknownRun));
        assert_eq!(runs.cancel(7, CANCEL_GRACE), Err(LiveError::UnknownRun));
    }
}
