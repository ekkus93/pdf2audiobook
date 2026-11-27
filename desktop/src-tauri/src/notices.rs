//! Licence notices for the components inside the built-in engine (self-contained app spec C9).
//!
//! The engine build writes `share/licenses/components.json`: each component's name, version,
//! licence, where its source is, and its licence texts as paths inside the engine. The About
//! screen lists them and shows one component's texts on request. Only files under the engine
//! folder are read, whatever the list says.

use std::fs;
use std::io::Read;
use std::path::{Component, Path};

use serde::{Deserialize, Serialize};

const LIST: &str = "share/licenses/components.json";
/// The list is about 30 KB; anything far larger is not ours.
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

/// The engine's components, or None when there is no built-in engine (a development build).
pub fn notices(engine: &Path) -> Option<Vec<Notice>> {
    let text = read_limited(&engine.join(LIST), LIST_LIMIT)?;
    serde_json::from_str::<List>(&text)
        .ok()
        .map(|list| list.components)
}

/// A relative path that stays inside the engine folder, symbolic links included.
fn inside(engine: &Path, relative: &str) -> Option<std::path::PathBuf> {
    let path = Path::new(relative);
    if relative.is_empty()
        || !path
            .components()
            .all(|part| matches!(part, Component::Normal(_)))
    {
        return None;
    }
    let root = engine.canonicalize().ok()?;
    let full = engine.join(path).canonicalize().ok()?;
    full.starts_with(&root).then_some(full)
}

/// One component's licence texts, each headed by its path inside the engine.
pub fn notice_text(engine: &Path, index: usize) -> Option<String> {
    let notice = notices(engine)?.into_iter().nth(index)?;
    let mut text = String::new();
    for relative in &notice.files {
        let path = inside(engine, relative)?;
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
            dir.path().join(LIST),
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
        let list = notices(dir.path()).unwrap();
        assert_eq!(list.len(), 3);
        assert_eq!(list[0].name, "FFmpeg");
        assert_eq!(list[0].license, "LGPL-2.1-or-later");
    }

    #[test]
    fn no_list_outside_a_built_in_engine() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(notices(dir.path()), None);
        fs::create_dir_all(dir.path().join("share/licenses")).unwrap();
        fs::write(dir.path().join(LIST), "not json").unwrap();
        assert_eq!(notices(dir.path()), None);
    }

    #[test]
    fn shows_each_text_under_its_path() {
        let dir = engine();
        let text = notice_text(dir.path(), 0).unwrap();
        assert!(text.contains("==> share/licenses/ffmpeg/COPYING <==\nLGPL text"));
        assert!(text.contains("==> share/licenses/ffmpeg/BUILD.txt <==\nhow"));
        assert_eq!(notice_text(dir.path(), 9), None);
    }

    #[test]
    fn reads_nothing_outside_the_engine() {
        let dir = engine();
        fs::write(dir.path().parent().unwrap().join("outside.txt"), "secret").ok();
        assert_eq!(notice_text(dir.path(), 1), None);
        assert_eq!(notice_text(dir.path(), 2), None);
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
        assert_eq!(notice_text(dir.path(), 0), None);
    }
}
