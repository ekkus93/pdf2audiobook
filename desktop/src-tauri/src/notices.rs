//! Licence notices for the installed app (self-contained app spec C9).
//!
//! Two lists, in one format: the engine build writes `share/licenses/components.json` inside
//! the engine, and `package_engine.py` puts the app's own (the app as distributed, its Rust crates
//! and npm packages) at `licenses/components.json` in the app's resources. Each entry has a
//! component's name, version, licence, where its source is, and its licence texts as paths
//! inside the list's folder. The About screen lists them and shows one component's texts on
//! request. Only files under that folder are read, whatever the list says.

use std::fs;
use std::io::Read;
use std::path::{Component, Path};

use serde::{Deserialize, Serialize};

/// The engine's list, inside the engine folder.
pub const ENGINE_LIST: &str = "share/licenses/components.json";
/// The app's list, inside its `licenses` resource folder.
pub const APP_LIST: &str = "components.json";
/// The lists are about 30 KB (engine) and 100 KB (app); anything far larger is not ours.
const LIST_LIMIT: u64 = 1 << 20;
/// One component's texts (NumPy's are the longest, about 100 KB).
const TEXT_LIMIT: u64 = 4 << 20;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Notice {
    pub name: String,
    pub version: String,
    pub license: String,
    pub source: String,
    pub files: Vec<String>,
}

#[derive(Deserialize)]
struct List {
    components: Vec<Notice>,
}

fn read_limited(path: &Path, limit: u64) -> Option<String> {
    let mut text = String::new();
    fs::File::open(path)
        .ok()?
        .take(limit + 1)
        .read_to_string(&mut text)
        .ok()?;
    (text.len() as u64 <= limit).then_some(text)
}

/// The components listed at `list` inside `root`, or None when there is no such list (a
/// development build has neither).
pub fn notices(root: &Path, list: &str) -> Option<Vec<Notice>> {
    let text = read_limited(&root.join(list), LIST_LIMIT)?;
    serde_json::from_str::<List>(&text)
        .ok()
        .map(|list| list.components)
}

/// A relative path that stays inside `root`, symbolic links included.
fn inside(root: &Path, relative: &str) -> Option<std::path::PathBuf> {
    let path = Path::new(relative);
    if relative.is_empty()
        || !path
            .components()
            .all(|part| matches!(part, Component::Normal(_)))
    {
        return None;
    }
    let base = root.canonicalize().ok()?;
    let full = root.join(path).canonicalize().ok()?;
    full.starts_with(&base).then_some(full)
}

/// One component's licence texts, each headed by its path inside `root`.
pub fn notice_text(root: &Path, list: &str, index: usize) -> Option<String> {
    let notice = notices(root, list)?.into_iter().nth(index)?;
    let mut text = String::new();
    for relative in &notice.files {
        let path = inside(root, relative)?;
        let body = read_limited(&path, TEXT_LIMIT)?;
        text.push_str(&format!("==> {relative} <==\n{body}\n"));
        if text.len() as u64 > TEXT_LIMIT {
            return None;
        }
    }
    Some(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn engine() -> tempfile::TempDir {
        let dir = tempfile::tempdir().unwrap();
        fs::create_dir_all(dir.path().join("share/licenses/ffmpeg")).unwrap();
        fs::write(
            dir.path().join("share/licenses/ffmpeg/COPYING"),
            "LGPL text",
        )
        .unwrap();
        fs::write(dir.path().join("share/licenses/ffmpeg/BUILD.txt"), "how").unwrap();
        fs::write(
            dir.path().join(ENGINE_LIST),
            serde_json::json!({"components": [
                {"name": "FFmpeg", "version": "8.1.3", "license": "LGPL-2.1-or-later",
                 "source": "https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz",
                 "files": ["share/licenses/ffmpeg/COPYING", "share/licenses/ffmpeg/BUILD.txt"]},
                {"name": "Escape", "version": "1", "license": "MIT", "source": "x",
                 "files": ["../outside.txt"]},
                {"name": "Absolute", "version": "1", "license": "MIT", "source": "x",
                 "files": ["/etc/hostname"]},
            ]})
            .to_string(),
        )
        .unwrap();
        dir
    }

    #[test]
    fn lists_the_components() {
        let dir = engine();
        let list = notices(dir.path(), ENGINE_LIST).unwrap();
        assert_eq!(list.len(), 3);
        assert_eq!(list[0].name, "FFmpeg");
        assert_eq!(list[0].license, "LGPL-2.1-or-later");
    }

    #[test]
    fn no_list_outside_a_built_in_engine() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(notices(dir.path(), ENGINE_LIST), None);
        fs::create_dir_all(dir.path().join("share/licenses")).unwrap();
        fs::write(dir.path().join(ENGINE_LIST), "not json").unwrap();
        assert_eq!(notices(dir.path(), ENGINE_LIST), None);
    }

    #[test]
    fn shows_each_text_under_its_path() {
        let dir = engine();
        let text = notice_text(dir.path(), ENGINE_LIST, 0).unwrap();
        assert!(text.contains("==> share/licenses/ffmpeg/COPYING <==\nLGPL text"));
        assert!(text.contains("==> share/licenses/ffmpeg/BUILD.txt <==\nhow"));
        assert_eq!(notice_text(dir.path(), ENGINE_LIST, 9), None);
    }

    #[test]
    fn reads_nothing_outside_the_engine() {
        let dir = engine();
        fs::write(dir.path().parent().unwrap().join("outside.txt"), "secret").ok();
        assert_eq!(notice_text(dir.path(), ENGINE_LIST, 1), None);
        assert_eq!(notice_text(dir.path(), ENGINE_LIST, 2), None);
    }

    #[test]
    fn reads_the_app_list_from_its_own_folder() {
        let dir = tempfile::tempdir().unwrap();
        fs::create_dir_all(dir.path().join("texts")).unwrap();
        fs::write(dir.path().join("AGPL-3.0.txt"), "GNU AFFERO").unwrap();
        fs::write(dir.path().join("texts/abc.txt"), "MIT text").unwrap();
        fs::write(
            dir.path().join(APP_LIST),
            serde_json::json!({"components": [
                {"name": "pdf2audiobook (this app)", "version": "0.1.0",
                 "license": "AGPL-3.0-only as distributed", "source": "x",
                 "files": ["AGPL-3.0.txt"]},
                {"name": "serde", "version": "1.0.0", "license": "MIT OR Apache-2.0",
                 "source": "y", "files": ["texts/abc.txt"]},
            ]})
            .to_string(),
        )
        .unwrap();
        assert_eq!(notices(dir.path(), APP_LIST).unwrap()[1].name, "serde");
        assert_eq!(notices(dir.path(), ENGINE_LIST), None);
        let text = notice_text(dir.path(), APP_LIST, 0).unwrap();
        assert_eq!(text, "==> AGPL-3.0.txt <==\nGNU AFFERO\n");
    }

    #[cfg(unix)]
    #[test]
    fn follows_no_link_out_of_the_engine() {
        let dir = engine();
        let outside = tempfile::tempdir().unwrap();
        fs::write(outside.path().join("secret.txt"), "secret").unwrap();
        let licence = dir.path().join("share/licenses/ffmpeg/COPYING");
        fs::remove_file(&licence).unwrap();
        std::os::unix::fs::symlink(outside.path().join("secret.txt"), &licence).unwrap();
        assert_eq!(notice_text(dir.path(), ENGINE_LIST, 0), None);
    }
}
