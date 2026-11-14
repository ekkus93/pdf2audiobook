//! The app's own settings, kept apart from the CLI's configuration (spec D4.8).

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Theme {
    #[default]
    Dark,
    Light,
    System,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct AppSettings {
    /// A CLI chosen by the user; tried before `PATH` (spec D3.a).
    pub cli_path: Option<PathBuf>,
    /// A source checkout to run with `uv run --project`.
    pub uv_project: Option<PathBuf>,
    /// The folder holding book workspaces; `None` uses the CLI's `general.output_dir`.
    pub output_dir: Option<PathBuf>,
    pub theme: Theme,
    /// Books the user added that may not be analyzed yet, in the order added.
    pub added_books: Vec<PathBuf>,
}

impl AppSettings {
    /// Remembers `book`; adding the same file twice keeps one entry.
    pub fn add_book(&mut self, book: PathBuf) {
        if !self.added_books.contains(&book) {
            self.added_books.push(book);
        }
    }
}

const FILE: &str = "settings.json";
const MAX_BYTES: u64 = 64 * 1024;

impl AppSettings {
    /// Reads the settings in `folder`; a missing, oversized or unreadable file gives defaults.
    pub fn load(folder: &Path) -> Self {
        let path = folder.join(FILE);
        match fs::metadata(&path) {
            Ok(meta) if meta.is_file() && meta.len() <= MAX_BYTES => fs::read_to_string(&path)
                .ok()
                .and_then(|text| serde_json::from_str(&text).ok())
                .unwrap_or_default(),
            _ => Self::default(),
        }
    }

    /// Writes the settings atomically: a temporary file in `folder`, then a rename.
    pub fn save(&self, folder: &Path) -> std::io::Result<()> {
        fs::create_dir_all(folder)?;
        let mut temp = tempfile::NamedTempFile::new_in(folder)?;
        temp.write_all(serde_json::to_string_pretty(self)?.as_bytes())?;
        temp.as_file().sync_all()?;
        temp.persist(folder.join(FILE))
            .map_err(|error| error.error)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn missing_settings_are_the_defaults() {
        let temp = TempDir::new().unwrap();
        assert_eq!(AppSettings::load(temp.path()), AppSettings::default());
        assert_eq!(AppSettings::default().theme, Theme::Dark);
    }

    #[test]
    fn settings_round_trip() {
        let temp = TempDir::new().unwrap();
        let settings = AppSettings {
            cli_path: Some("/opt/cli".into()),
            uv_project: Some("/src/checkout".into()),
            output_dir: Some("/books/out".into()),
            theme: Theme::System,
            added_books: vec!["/books/a.pdf".into()],
        };
        settings.save(&temp.path().join("nested")).unwrap();
        assert_eq!(AppSettings::load(&temp.path().join("nested")), settings);
    }

    #[test]
    fn a_corrupt_or_huge_file_gives_defaults() {
        let temp = TempDir::new().unwrap();
        fs::write(temp.path().join(FILE), "{not json").unwrap();
        assert_eq!(AppSettings::load(temp.path()), AppSettings::default());
        fs::write(temp.path().join(FILE), " ".repeat(MAX_BYTES as usize + 1)).unwrap();
        assert_eq!(AppSettings::load(temp.path()), AppSettings::default());
    }

    #[test]
    fn adding_a_book_twice_keeps_one_entry() {
        let mut settings = AppSettings::default();
        settings.add_book("/b/one.pdf".into());
        settings.add_book("/b/two.epub".into());
        settings.add_book("/b/one.pdf".into());
        assert_eq!(
            settings.added_books,
            [PathBuf::from("/b/one.pdf"), PathBuf::from("/b/two.epub")]
        );
    }

    #[test]
    fn unknown_fields_are_ignored_and_missing_ones_default() {
        let temp = TempDir::new().unwrap();
        fs::write(temp.path().join(FILE), r#"{"theme": "light", "future": 1}"#).unwrap();
        let loaded = AppSettings::load(temp.path());
        assert_eq!(loaded.theme, Theme::Light);
        assert_eq!(loaded.cli_path, None);
    }
}
