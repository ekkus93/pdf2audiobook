//! At most one write-capable command per workspace (spec D3.d).
//!
//! The CLI's own workspace lock stays the authority. This check only stops the app from
//! starting a command the CLI would refuse with `workspace_locked`.

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, PoisonError};

use serde::Serialize;

use super::request::Request;

#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error, Serialize)]
#[error("Another task is already changing this book; wait for it to finish")]
pub struct WorkspaceBusy;

#[derive(Debug, Default)]
pub struct WorkspaceRuns {
    active: Mutex<HashSet<PathBuf>>,
}

impl WorkspaceRuns {
    pub fn new() -> Arc<Self> {
        Arc::new(Self::default())
    }

    /// Claims `workspace` for a write-capable `request` until the returned guard is dropped.
    /// Read-only requests always start and claim nothing.
    pub fn try_start(
        self: &Arc<Self>,
        workspace: &Path,
        request: &Request,
    ) -> Result<RunGuard, WorkspaceBusy> {
        if !request.is_write() {
            return Ok(RunGuard {
                runs: None,
                key: None,
            });
        }
        let key = workspace
            .canonicalize()
            .unwrap_or_else(|_| workspace.to_path_buf());
        let mut active = self.active.lock().unwrap_or_else(PoisonError::into_inner);
        if !active.insert(key.clone()) {
            return Err(WorkspaceBusy);
        }
        Ok(RunGuard {
            runs: Some(Arc::clone(self)),
            key: Some(key),
        })
    }

    pub fn is_busy(&self, workspace: &Path) -> bool {
        let key = workspace
            .canonicalize()
            .unwrap_or_else(|_| workspace.to_path_buf());
        self.active
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .contains(&key)
    }
}

/// Holds a workspace for one run; dropping it frees the workspace.
#[derive(Debug)]
pub struct RunGuard {
    runs: Option<Arc<WorkspaceRuns>>,
    key: Option<PathBuf>,
}

impl Drop for RunGuard {
    fn drop(&mut self) {
        if let (Some(runs), Some(key)) = (&self.runs, &self.key) {
            runs.active
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .remove(key);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::request::{BookOptions, EditStatus};
    use std::sync::Barrier;
    use std::thread;
    use tempfile::TempDir;

    fn convert(book: &str) -> Request {
        Request::Convert {
            book: book.into(),
            options: BookOptions::default(),
            convert: Default::default(),
        }
    }

    fn list(manifest: &Path) -> Request {
        Request::EditsList {
            manifest: manifest.join("manifest.json"),
            status: EditStatus::Pending,
        }
    }

    #[test]
    fn a_second_write_is_refused_while_the_first_runs() {
        let temp = TempDir::new().unwrap();
        let runs = WorkspaceRuns::new();

        let first = runs.try_start(temp.path(), &convert("/b.pdf")).unwrap();
        let second = runs.try_start(
            temp.path(),
            &Request::Recover {
                manifest: temp.path().join("manifest.json"),
                back_up_changed: false,
            },
        );

        assert_eq!(second.unwrap_err(), WorkspaceBusy);
        assert!(runs.is_busy(temp.path()));
        drop(first);
        assert!(!runs.is_busy(temp.path()));
        assert!(runs.try_start(temp.path(), &convert("/b.pdf")).is_ok());
    }

    #[test]
    fn read_only_commands_are_not_blocked() {
        let temp = TempDir::new().unwrap();
        let runs = WorkspaceRuns::new();
        let _write = runs.try_start(temp.path(), &convert("/b.pdf")).unwrap();

        for request in [
            list(temp.path()),
            Request::Doctor { check_llm: false },
            Request::BudgetShow {
                workspace: temp.path().into(),
            },
        ] {
            assert!(runs.try_start(temp.path(), &request).is_ok(), "{request:?}");
        }
    }

    #[test]
    fn read_only_runs_do_not_hold_the_workspace() {
        let temp = TempDir::new().unwrap();
        let runs = WorkspaceRuns::new();
        let _read = runs.try_start(temp.path(), &list(temp.path())).unwrap();

        assert!(!runs.is_busy(temp.path()));
        assert!(runs.try_start(temp.path(), &convert("/b.pdf")).is_ok());
    }

    #[test]
    fn different_workspaces_run_independently() {
        let temp = TempDir::new().unwrap();
        let (a, b) = (temp.path().join("a"), temp.path().join("b"));
        std::fs::create_dir_all(&a).unwrap();
        std::fs::create_dir_all(&b).unwrap();
        let runs = WorkspaceRuns::new();

        let _a = runs.try_start(&a, &convert("/a.pdf")).unwrap();

        assert!(runs.try_start(&b, &convert("/b.pdf")).is_ok());
    }

    #[test]
    fn another_spelling_of_the_same_folder_is_the_same_workspace() {
        let temp = TempDir::new().unwrap();
        let real = temp.path().join("book");
        std::fs::create_dir_all(&real).unwrap();
        let link = temp.path().join("link");
        std::os::unix::fs::symlink(&real, &link).unwrap();
        let runs = WorkspaceRuns::new();

        let _held = runs.try_start(&real, &convert("/b.pdf")).unwrap();

        assert_eq!(
            runs.try_start(&link, &convert("/b.pdf")).unwrap_err(),
            WorkspaceBusy
        );
        let dotted = temp.path().join("book/../book");
        assert_eq!(
            runs.try_start(&dotted, &convert("/b.pdf")).unwrap_err(),
            WorkspaceBusy
        );
    }

    #[test]
    fn only_one_of_many_simultaneous_starts_wins() {
        let temp = TempDir::new().unwrap();
        let runs = WorkspaceRuns::new();
        let barrier = Arc::new(Barrier::new(16));
        let workers: Vec<_> = (0..16)
            .map(|_| {
                let (runs, barrier, path) = (
                    Arc::clone(&runs),
                    Arc::clone(&barrier),
                    temp.path().to_path_buf(),
                );
                thread::spawn(move || {
                    barrier.wait();
                    runs.try_start(&path, &convert("/b.pdf")).ok()
                })
            })
            .collect();

        let guards: Vec<_> = workers
            .into_iter()
            .filter_map(|worker| worker.join().unwrap())
            .collect();

        assert_eq!(guards.len(), 1);
    }

    #[test]
    fn the_busy_message_has_no_path() {
        assert_eq!(
            WorkspaceBusy.to_string(),
            "Another task is already changing this book; wait for it to finish"
        );
    }
}
