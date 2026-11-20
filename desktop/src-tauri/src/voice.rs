//! Private transcript drafts live until the CLI child exits. No transcript in argv/logs.
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

const MARKER: &str = "pdf2audiobook-desktop-voice-v1\n";
fn root() -> PathBuf {
    let base = std::env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .filter(|p| p.is_absolute())
        .unwrap_or_else(|| {
            PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".cache")
        });
    base.join("pdf2audiobook/desktop-voice")
}
fn locked(file: &File) -> bool {
    // SAFETY: valid open descriptor; advisory nonblocking lock, held until file is dropped.
    unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) == 0 }
}
pub fn cleanup() {
    cleanup_in(&root());
}
fn cleanup_in(root: &Path) {
    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    for entry in entries.flatten() {
        if !entry.file_name().to_string_lossy().starts_with("draft-") {
            continue;
        }
        if !entry.file_type().is_ok_and(|t| t.is_dir()) {
            continue;
        }
        let path = entry.path();
        let owner = path.join(".owner");
        let Ok(mut file) = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NOFOLLOW)
            .open(owner)
        else {
            continue;
        };
        if !locked(&file) {
            continue;
        }
        let mut text = String::new();
        if (&mut file).take(128).read_to_string(&mut text).is_ok() && text == MARKER {
            let _ = fs::remove_dir_all(path);
        }
    }
}

pub struct PrivateTranscript {
    folder: tempfile::TempDir,
    _lock: File,
}
impl PrivateTranscript {
    pub fn create(text: &str) -> std::io::Result<Self> {
        Self::create_in(&root(), text)
    }
    fn create_in(root: &Path, text: &str) -> std::io::Result<Self> {
        if text.trim().is_empty() || text.len() > 65536 || text.contains('\0') {
            return Err(std::io::ErrorKind::InvalidInput.into());
        }
        fs::create_dir_all(root)?;
        if fs::symlink_metadata(root)?.file_type().is_symlink() {
            return Err(std::io::ErrorKind::PermissionDenied.into());
        }
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
        cleanup_in(root);
        let folder = tempfile::Builder::new().prefix("draft-").tempdir_in(root)?;
        let mut lock = OpenOptions::new()
            .write(true)
            .read(true)
            .create_new(true)
            .mode(0o600)
            .open(folder.path().join(".owner"))?;
        if !locked(&lock) {
            return Err(std::io::ErrorKind::WouldBlock.into());
        }
        lock.write_all(MARKER.as_bytes())?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(folder.path().join("transcript.txt"))?;
        file.write_all(text.replace("\r\n", "\n").replace('\r', "\n").as_bytes())?;
        file.sync_all()?;
        Ok(Self {
            folder,
            _lock: lock,
        })
    }
    pub fn path(&self) -> PathBuf {
        self.folder.path().join("transcript.txt")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn draft_lifetime_permissions_and_crash_cleanup() {
        let root = tempfile::tempdir().unwrap();
        let draft = PrivateTranscript::create_in(root.path(), "PRIVATE WORDS\r\n").unwrap();
        let path = draft.path();
        assert_eq!(fs::read_to_string(&path).unwrap(), "PRIVATE WORDS\n");
        assert_eq!(
            fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
        cleanup_in(root.path());
        assert!(path.exists());
        drop(draft);
        assert!(!path.exists());
        let crash = root.path().join("draft-crashed");
        fs::create_dir(&crash).unwrap();
        fs::write(crash.join(".owner"), MARKER).unwrap();
        let unrelated = root.path().join("draft-user");
        fs::create_dir(&unrelated).unwrap();
        fs::write(unrelated.join(".owner"), "other").unwrap();
        cleanup_in(root.path());
        assert!(!crash.exists());
        assert!(unrelated.exists());
    }
}

#[cfg(test)]
mod lifecycle_tests {
    use super::*;
    use crate::engine::live::{LiveRuns, Progress};
    use crate::engine::process::CliCommand;
    use std::sync::Arc;
    use std::time::{Duration, Instant};
    #[test]
    fn child_exit_failure_cancel_and_shutdown_release_private_drafts() {
        for mode in ["success", "failure", "cancel", "shutdown"] {
            let root = tempfile::tempdir().unwrap();
            let draft = PrivateTranscript::create_in(root.path(), "PRIVATE DRAFT").unwrap();
            let path = draft.path();
            let runs = Arc::new(LiveRuns::default());
            let script = match mode {
                "success" => "sleep 0.15; printf '{}'",
                "failure" => "sleep 0.15; exit 2",
                _ => "sleep 30",
            };
            let id = runs
                .start_with_hook(
                    &CliCommand::direct("/bin/sh"),
                    &["-c".into(), script.into()],
                    root.path(),
                    None,
                    Box::new(move |_| drop(draft)),
                )
                .unwrap();
            assert!(path.is_file());
            if mode == "cancel" {
                runs.cancel(id, Duration::from_millis(50)).unwrap();
            }
            if mode == "shutdown" {
                runs.shutdown(Duration::from_millis(50));
            }
            let deadline = Instant::now() + Duration::from_secs(5);
            loop {
                if matches!(runs.progress(id).unwrap(), Progress::Finished { .. }) && !path.exists()
                {
                    break;
                }
                assert!(Instant::now() < deadline, "{mode} did not clean the draft");
                std::thread::sleep(Duration::from_millis(10));
            }
        }
    }
}
