//! The shared CLI configuration: Python chooses the path and validates every edit.

use std::ffi::OsString;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::engine::process::{CliCommand, Runner};
use crate::engine::result::{Outcome, parse};

const MAX_BYTES: u64 = 1024 * 1024;

#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("The configuration command could not be run")]
    Engine,
    #[error("{0}")]
    Invalid(String),
    #[error("The configuration file could not be read; check its permissions")]
    Read,
    #[error("The configuration file is too large to edit here")]
    TooLarge,
    #[error("Edit linked configuration files in your text editor")]
    Linked,
    #[error("The configuration changed outside this editor. Reload it before saving.")]
    Changed,
    #[error("The configuration could not be saved; the previous file was kept")]
    Save,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ConfigFile {
    pub path: PathBuf,
    pub text: String,
}

fn run(
    cli: &CliCommand,
    runner: &dyn Runner,
    args: &[OsString],
) -> Result<serde_json::Value, ConfigError> {
    let done = runner.run(cli, args).map_err(|_| ConfigError::Engine)?;
    match parse(&done) {
        Outcome::Success { result } => Ok(result),
        Outcome::Failed { error, .. } => Err(ConfigError::Invalid(error.message)),
        Outcome::Unreadable { .. } => Err(ConfigError::Engine),
    }
}

/// Idempotent: initialization never replaces even a malformed existing file.
pub fn initialize(cli: &CliCommand, runner: &dyn Runner) -> Result<PathBuf, ConfigError> {
    let result = run(
        cli,
        runner,
        &["config".into(), "init".into(), "--json".into()],
    )?;
    result["path"]
        .as_str()
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or(ConfigError::Engine)
}

fn read_file(path: &Path) -> Result<String, ConfigError> {
    if fs::symlink_metadata(path)
        .map_err(|_| ConfigError::Read)?
        .file_type()
        .is_symlink()
    {
        return Err(ConfigError::Linked);
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    let file = options.open(path).map_err(|_| ConfigError::Read)?;
    let metadata = file.metadata().map_err(|_| ConfigError::Read)?;
    if !metadata.is_file() {
        return Err(ConfigError::Read);
    }
    if metadata.len() > MAX_BYTES {
        return Err(ConfigError::TooLarge);
    }
    let mut text = String::new();
    file.take(MAX_BYTES + 1)
        .read_to_string(&mut text)
        .map_err(|_| ConfigError::Read)?;
    if text.len() as u64 > MAX_BYTES {
        return Err(ConfigError::TooLarge);
    }
    Ok(text)
}

pub fn read(cli: &CliCommand, runner: &dyn Runner) -> Result<ConfigFile, ConfigError> {
    let path = initialize(cli, runner)?;
    let text = read_file(&path)?;
    Ok(ConfigFile { path, text })
}

/// Preserve comments and unknown text while rejecting invalid settings and stale edits.
/// The draft is passed as a private file, never as command-line text or a log event.
pub fn save(
    cli: &CliCommand,
    runner: &dyn Runner,
    text: &str,
    expected: &str,
) -> Result<ConfigFile, ConfigError> {
    if text.len() as u64 > MAX_BYTES || expected.len() as u64 > MAX_BYTES {
        return Err(ConfigError::TooLarge);
    }
    let path = initialize(cli, runner)?;
    if read_file(&path)? != expected {
        return Err(ConfigError::Changed);
    }
    let parent = path.parent().ok_or(ConfigError::Save)?;
    let mut draft = tempfile::NamedTempFile::new_in(parent).map_err(|_| ConfigError::Save)?;
    draft
        .write_all(text.as_bytes())
        .and_then(|_| draft.as_file().sync_all())
        .map_err(|_| ConfigError::Save)?;
    let validation = run(
        cli,
        runner,
        &[
            "config".into(),
            "validate".into(),
            "--config".into(),
            draft.path().as_os_str().into(),
            "--json".into(),
        ],
    )?;
    if validation["valid"].as_bool() != Some(true) {
        return Err(ConfigError::Engine);
    }
    // Validation may take time. Check again immediately before publishing.
    if read_file(&path)? != expected {
        return Err(ConfigError::Changed);
    }
    let permissions = fs::metadata(&path)
        .map_err(|_| ConfigError::Save)?
        .permissions();
    draft
        .as_file()
        .set_permissions(permissions)
        .map_err(|_| ConfigError::Save)?;
    draft.persist(&path).map_err(|_| ConfigError::Save)?;
    Ok(ConfigFile {
        path,
        text: text.into(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::process::Finished;
    use serde_json::json;
    use std::io;

    struct ConfigRunner {
        path: PathBuf,
        valid: bool,
        change_during_validation: bool,
    }

    impl Runner for ConfigRunner {
        fn run(&self, _: &CliCommand, args: &[OsString]) -> io::Result<Finished> {
            if args[1] == "init" {
                return Ok(Finished {
                    code: Some(0),
                    stdout: json!({"path": self.path, "created": false}).to_string(),
                    stderr: String::new(),
                });
            }
            assert_eq!(args[1], "validate");
            // The contents are in the private draft, never the argument vector.
            assert_eq!(args.len(), 5);
            assert!(Path::new(&args[3]).is_file());
            assert!(
                !args
                    .iter()
                    .any(|arg| arg.to_string_lossy().contains("enabled="))
            );
            if self.change_during_validation {
                fs::write(&self.path, "# externally changed")?;
            }
            Ok(if self.valid {
                Finished {
                    code: Some(0),
                    stdout: "{\"valid\": true}".into(),
                    stderr: String::new(),
                }
            } else {
                Finished {
                    code: Some(2),
                    stdout: String::new(),
                    stderr: json!({"ok": false, "error": {
                        "type": "ConfigError", "code": 2,
                        "message": "invalid TOML configuration syntax"
                    }})
                    .to_string(),
                }
            })
        }
    }

    fn runner(path: &Path) -> ConfigRunner {
        ConfigRunner {
            path: path.into(),
            valid: true,
            change_during_validation: false,
        }
    }

    #[test]
    fn saves_the_validated_file_and_preserves_comments() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("config.toml");
        fs::write(&path, "# old").unwrap();
        let cli = CliCommand::direct("cli");
        let runner = runner(&path);
        let file = read(&cli, &runner).unwrap();
        let next = "# keep my comments\n[llm]\nenabled=false\n";
        let saved = save(&cli, &runner, next, &file.text).unwrap();
        assert_eq!(saved.text, next);
        assert_eq!(fs::read_to_string(&path).unwrap(), next);
        assert_eq!(fs::read_dir(temp.path()).unwrap().count(), 1);
    }

    #[test]
    fn invalid_settings_keep_the_previous_file_and_remove_the_draft() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("config.toml");
        fs::write(&path, "# old").unwrap();
        let mut runner = runner(&path);
        runner.valid = false;
        let error = save(&CliCommand::direct("cli"), &runner, "invalid", "# old").unwrap_err();
        assert!(matches!(error, ConfigError::Invalid(_)));
        assert_eq!(fs::read_to_string(&path).unwrap(), "# old");
        assert_eq!(fs::read_dir(temp.path()).unwrap().count(), 1);
    }

    #[test]
    fn rejects_external_changes_before_or_during_validation() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("config.toml");
        fs::write(&path, "# current").unwrap();
        let mut runner = runner(&path);
        let cli = CliCommand::direct("cli");
        assert!(matches!(
            save(&cli, &runner, "next", "# stale"),
            Err(ConfigError::Changed)
        ));
        runner.change_during_validation = true;
        assert!(matches!(
            save(&cli, &runner, "next", "# current"),
            Err(ConfigError::Changed)
        ));
        assert_eq!(fs::read_to_string(&path).unwrap(), "# externally changed");
    }

    #[test]
    fn refuses_oversized_or_linked_files_without_changing_the_target() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("config.toml");
        fs::write(&path, "x".repeat(MAX_BYTES as usize + 1)).unwrap();
        let runner = runner(&path);
        let cli = CliCommand::direct("cli");
        assert!(matches!(read(&cli, &runner), Err(ConfigError::TooLarge)));
        #[cfg(unix)]
        {
            use std::os::unix::fs::symlink;
            let link = temp.path().join("linked.toml");
            symlink(&path, &link).unwrap();
            assert!(matches!(read_file(&link), Err(ConfigError::Linked)));
            assert_eq!(fs::metadata(&path).unwrap().len(), MAX_BYTES + 1);
        }
    }

    #[test]
    #[ignore = "needs uv and the Python CLI"]
    fn real_cli_initializes_and_validates_shared_configuration() {
        use crate::engine::testing::TestRunner;

        struct RoutedRunner(PathBuf);
        impl Runner for RoutedRunner {
            fn run(&self, cli: &CliCommand, args: &[OsString]) -> io::Result<Finished> {
                let mut args = args.to_vec();
                if args[1] == "init" {
                    args.extend(["--config".into(), self.0.as_os_str().into()]);
                }
                TestRunner.run(cli, &args)
            }
        }

        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let cli = CliCommand {
            program: "uv".into(),
            prefix: vec![
                "run".into(),
                "--no-sync".into(),
                "--project".into(),
                root.into_os_string(),
                "pdf2audiobook".into(),
            ],
        };
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("nested/config.toml");
        let runner = RoutedRunner(path.clone());
        let file = read(&cli, &runner).unwrap();
        assert!(path.is_file());
        assert!(file.text.contains("voice = \"Jasper\""));
        let next = file.text.replace("voice = \"Jasper\"", "voice = \"Luna\"");
        save(&cli, &runner, &next, &file.text).unwrap();
        assert_eq!(read(&cli, &runner).unwrap().text, next);
        assert!(matches!(
            save(&cli, &runner, "[tts.kitten]\nvoice=123\n", &next),
            Err(ConfigError::Invalid(_))
        ));
        assert_eq!(fs::read_to_string(path).unwrap(), next);
    }
}
