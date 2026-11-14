//! A book's chapter audio: listing it, scoping playback to it, and exporting it (spec D7).

use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use serde::Serialize;

#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error, Serialize)]
pub enum AudioError {
    #[error("This book has no audio folder yet")]
    NoAudio,
    #[error("Choose a place outside the book's own folder")]
    InsideWorkspace,
    #[error("The zip file could not be written")]
    Write,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct AudioFile {
    pub path: PathBuf,
    pub name: String,
    pub bytes: u64,
}

/// The book's `audio` folder, canonical, and only if it really lies inside the workspace (a
/// symlink pointing elsewhere is refused). This is the only folder playback may read.
pub fn audio_dir(workspace: &Path) -> Result<PathBuf, AudioError> {
    let root = workspace.canonicalize().map_err(|_| AudioError::NoAudio)?;
    let folder = root.join("audio");
    let meta = fs::symlink_metadata(&folder).map_err(|_| AudioError::NoAudio)?;
    if !meta.is_dir() {
        return Err(AudioError::NoAudio);
    }
    let canonical = folder.canonicalize().map_err(|_| AudioError::NoAudio)?;
    if canonical.parent() != Some(root.as_path()) {
        return Err(AudioError::NoAudio);
    }
    Ok(canonical)
}

/// The chapter MP3s in the audio folder, in file-name order (`001 - ...`). Symlinks are skipped.
pub fn chapter_files(workspace: &Path) -> Result<Vec<AudioFile>, AudioError> {
    let folder = audio_dir(workspace)?;
    let mut files: Vec<AudioFile> = fs::read_dir(&folder)
        .map_err(|_| AudioError::NoAudio)?
        .filter_map(Result::ok)
        .filter_map(|entry| {
            let meta = fs::symlink_metadata(entry.path()).ok()?;
            let name = entry.file_name().into_string().ok()?;
            (meta.is_file() && name.to_lowercase().ends_with(".mp3")).then(|| AudioFile {
                path: entry.path(),
                name,
                bytes: meta.len(),
            })
        })
        .collect();
    files.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(files)
}

/// Writes `destination` (a .zip) with the chapter MP3s under `<title>/audio/`, and the source
/// book at `<title>/` when given. Refuses a destination inside the workspace. Returns the number
/// of files written.
pub fn export_zip(
    workspace: &Path,
    destination: &Path,
    title: &str,
    source: Option<&Path>,
) -> Result<usize, AudioError> {
    let root = workspace.canonicalize().map_err(|_| AudioError::NoAudio)?;
    let parent = destination
        .parent()
        .and_then(|folder| folder.canonicalize().ok())
        .ok_or(AudioError::Write)?;
    if parent.starts_with(&root) {
        return Err(AudioError::InsideWorkspace);
    }
    let files = chapter_files(workspace)?;
    if files.is_empty() {
        return Err(AudioError::NoAudio);
    }
    let folder = safe_name(title);
    let temp = tempfile::NamedTempFile::new_in(&parent).map_err(|_| AudioError::Write)?;
    let mut zip = zip::ZipWriter::new(temp.as_file());
    // MP3 and PDF are already compressed; store them as they are.
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Stored)
        .large_file(true);
    let mut add = |name: String, path: &Path| -> Result<(), AudioError> {
        zip.start_file(name, options)
            .map_err(|_| AudioError::Write)?;
        let mut input = fs::File::open(path).map_err(|_| AudioError::Write)?;
        let mut buffer = vec![0; 1 << 20];
        loop {
            let read = input.read(&mut buffer).map_err(|_| AudioError::Write)?;
            if read == 0 {
                return Ok(());
            }
            zip.write_all(&buffer[..read])
                .map_err(|_| AudioError::Write)?;
        }
    };
    if let Some(book) = source {
        let name = book.file_name().ok_or(AudioError::Write)?.to_string_lossy();
        add(format!("{folder}/{name}"), book)?;
    }
    for file in &files {
        add(format!("{folder}/audio/{}", file.name), &file.path)?;
    }
    zip.finish().map_err(|_| AudioError::Write)?;
    // The temporary file is private (0600); the export is an ordinary file for other apps.
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o644))
        .map_err(|_| AudioError::Write)?;
    temp.as_file().sync_all().map_err(|_| AudioError::Write)?;
    temp.persist(destination).map_err(|_| AudioError::Write)?;
    Ok(files.len() + usize::from(source.is_some()))
}

/// A folder name for the zip: the title without path separators or control characters.
fn safe_name(title: &str) -> String {
    let cleaned: String = title
        .chars()
        .map(|c| {
            if c == '/' || c == '\\' || c.is_control() {
                '_'
            } else {
                c
            }
        })
        .collect();
    let trimmed = cleaned.trim().trim_matches('.').trim();
    if trimmed.is_empty() {
        "Audiobook".into()
    } else {
        trimmed.to_owned()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn book(temp: &TempDir) -> PathBuf {
        let workspace = temp.path().join("book-1");
        fs::create_dir_all(workspace.join("audio")).unwrap();
        for name in [
            "002 - Two.mp3",
            "001 - One.mp3",
            "001 - One.cache.json",
            "notes.txt",
        ] {
            fs::write(workspace.join("audio").join(name), name).unwrap();
        }
        workspace
    }

    #[test]
    fn chapter_files_are_the_mp3s_in_order() {
        let temp = TempDir::new().unwrap();
        let workspace = book(&temp);
        std::os::unix::fs::symlink(
            temp.path().join("elsewhere.mp3"),
            workspace.join("audio/003 - Link.mp3"),
        )
        .unwrap();
        let names: Vec<String> = chapter_files(&workspace)
            .unwrap()
            .into_iter()
            .map(|file| file.name)
            .collect();
        assert_eq!(names, ["001 - One.mp3", "002 - Two.mp3"]);
    }

    #[test]
    fn a_book_without_audio_has_none() {
        let temp = TempDir::new().unwrap();
        fs::create_dir_all(temp.path().join("book")).unwrap();
        assert_eq!(
            chapter_files(&temp.path().join("book")),
            Err(AudioError::NoAudio)
        );
    }

    #[test]
    fn an_audio_folder_that_points_elsewhere_is_refused() {
        let temp = TempDir::new().unwrap();
        let outside = temp.path().join("outside");
        fs::create_dir_all(&outside).unwrap();
        let workspace = temp.path().join("book");
        fs::create_dir_all(&workspace).unwrap();
        std::os::unix::fs::symlink(&outside, workspace.join("audio")).unwrap();
        assert_eq!(audio_dir(&workspace), Err(AudioError::NoAudio));
    }

    #[test]
    fn the_zip_holds_the_chapters_and_optionally_the_book() {
        let temp = TempDir::new().unwrap();
        let workspace = book(&temp);
        let source = temp.path().join("My Book.pdf");
        fs::write(&source, "pdf bytes").unwrap();
        let out = temp.path().join("export");
        fs::create_dir_all(&out).unwrap();

        let written = export_zip(
            &workspace,
            &out.join("book.zip"),
            "My Book: A/B",
            Some(&source),
        )
        .unwrap();

        assert_eq!(written, 3);
        let mut archive =
            zip::ZipArchive::new(fs::File::open(out.join("book.zip")).unwrap()).unwrap();
        let mut names: Vec<String> = (0..archive.len())
            .map(|i| archive.by_index(i).unwrap().name().to_owned())
            .collect();
        names.sort();
        assert_eq!(
            names,
            [
                "My Book: A_B/My Book.pdf",
                "My Book: A_B/audio/001 - One.mp3",
                "My Book: A_B/audio/002 - Two.mp3"
            ]
        );
        let mut text = String::new();
        archive
            .by_name("My Book: A_B/audio/002 - Two.mp3")
            .unwrap()
            .read_to_string(&mut text)
            .unwrap();
        assert_eq!(text, "002 - Two.mp3");

        use std::os::unix::fs::PermissionsExt;
        let mode = fs::metadata(out.join("book.zip"))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o644);
        assert_eq!(
            fs::read_dir(&out).unwrap().count(),
            1,
            "no temporary file is left"
        );

        export_zip(&workspace, &out.join("audio-only.zip"), "My Book", None).unwrap();
        let archive =
            zip::ZipArchive::new(fs::File::open(out.join("audio-only.zip")).unwrap()).unwrap();
        assert_eq!(archive.len(), 2);
    }

    #[test]
    fn a_zip_inside_the_workspace_is_refused_and_nothing_is_written() {
        let temp = TempDir::new().unwrap();
        let workspace = book(&temp);
        let inside = workspace.join("audio/book.zip");
        assert_eq!(
            export_zip(&workspace, &inside, "Book", None),
            Err(AudioError::InsideWorkspace)
        );
        assert!(!inside.exists());
        assert_eq!(
            export_zip(&workspace, &workspace.join("book.zip"), "Book", None),
            Err(AudioError::InsideWorkspace)
        );
    }

    #[test]
    fn a_book_with_no_mp3_has_nothing_to_export() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path().join("book");
        fs::create_dir_all(workspace.join("audio")).unwrap();
        assert_eq!(
            export_zip(&workspace, &temp.path().join("x.zip"), "Book", None),
            Err(AudioError::NoAudio)
        );
        assert!(!temp.path().join("x.zip").exists());
    }

    #[test]
    fn the_asset_scope_allows_only_the_opened_books_audio_folder() {
        use tauri::Manager;
        let temp = TempDir::new().unwrap();
        let workspace = book(&temp);
        fs::write(workspace.join("manifest.json"), "{}").unwrap();
        let app = tauri::test::mock_builder()
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .unwrap();
        let scope = app.asset_protocol_scope();
        let chapter = workspace.join("audio/001 - One.mp3");
        assert!(
            !scope.is_allowed(&chapter),
            "nothing is allowed before a book is opened"
        );

        scope
            .allow_directory(audio_dir(&workspace).unwrap(), false)
            .unwrap();

        assert!(scope.is_allowed(chapter.canonicalize().unwrap()));
        assert!(!scope.is_allowed(workspace.join("manifest.json").canonicalize().unwrap()));
        assert!(!scope.is_allowed(temp.path().join("book-1")));
    }
}
