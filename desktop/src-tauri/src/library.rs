//! Finding the books in the output folder (spec D4.2).

use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;

/// A book workspace: a folder in the output folder that holds a `manifest.json`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct WorkspaceDir {
    pub workspace: PathBuf,
    pub manifest: PathBuf,
}

/// Workspaces directly inside `output_dir`, sorted by folder name. Symlinks are skipped.
pub fn workspaces(output_dir: &Path) -> Vec<WorkspaceDir> {
    let Ok(entries) = fs::read_dir(output_dir) else {
        return Vec::new();
    };
    let mut found: Vec<WorkspaceDir> = entries
        .filter_map(Result::ok)
        .filter(|entry| entry.file_type().is_ok_and(|kind| kind.is_dir()))
        .map(|entry| entry.path())
        .filter_map(|workspace| {
            let manifest = workspace.join("manifest.json");
            let is_file = fs::symlink_metadata(&manifest).is_ok_and(|meta| meta.is_file());
            is_file.then_some(WorkspaceDir {
                workspace,
                manifest,
            })
        })
        .collect();
    found.sort_by(|a, b| a.workspace.file_name().cmp(&b.workspace.file_name()));
    found
}

const RUN_STATUS_MAX_BYTES: u64 = 256 * 1024;

/// The workspace's `reports/run_status.json`, if present, small and valid JSON.
pub fn run_status(workspace: &Path) -> Option<serde_json::Value> {
    let path = workspace.join("reports").join("run_status.json");
    let meta = fs::symlink_metadata(&path).ok()?;
    if !meta.is_file() || meta.len() > RUN_STATUS_MAX_BYTES {
        return None;
    }
    serde_json::from_str(&fs::read_to_string(path).ok()?).ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn book(root: &Path, name: &str) -> PathBuf {
        let folder = root.join(name);
        fs::create_dir_all(&folder).unwrap();
        fs::write(folder.join("manifest.json"), "{}").unwrap();
        folder
    }

    #[test]
    fn workspaces_are_folders_with_a_manifest() {
        let temp = TempDir::new().unwrap();
        let b = book(temp.path(), "b-book-2222");
        let a = book(temp.path(), "a-book-1111");
        fs::create_dir_all(temp.path().join("not-a-book")).unwrap();
        fs::write(temp.path().join("stray.json"), "{}").unwrap();
        std::os::unix::fs::symlink(&a, temp.path().join("c-link")).unwrap();
        let fake = temp.path().join("d-fake");
        fs::create_dir_all(fake.join("manifest.json")).unwrap();

        let found = workspaces(temp.path());

        assert_eq!(
            found,
            vec![
                WorkspaceDir {
                    manifest: a.join("manifest.json"),
                    workspace: a
                },
                WorkspaceDir {
                    manifest: b.join("manifest.json"),
                    workspace: b
                },
            ]
        );
    }

    #[test]
    fn a_missing_output_folder_has_no_books() {
        let temp = TempDir::new().unwrap();
        assert!(workspaces(&temp.path().join("missing")).is_empty());
    }

    #[test]
    fn run_status_is_read_when_valid_and_small() {
        let temp = TempDir::new().unwrap();
        let folder = book(temp.path(), "a");
        assert_eq!(run_status(&folder), None);
        fs::create_dir_all(folder.join("reports")).unwrap();
        fs::write(
            folder.join("reports/run_status.json"),
            r#"{"state": "completed"}"#,
        )
        .unwrap();
        assert_eq!(
            run_status(&folder),
            Some(serde_json::json!({"state": "completed"}))
        );
        fs::write(folder.join("reports/run_status.json"), "{broken").unwrap();
        assert_eq!(run_status(&folder), None);
        fs::write(
            folder.join("reports/run_status.json"),
            " ".repeat(300 * 1024),
        )
        .unwrap();
        assert_eq!(run_status(&folder), None);
    }
}
