//! Finding the pdf2audiobook CLI and confirming it is a version this app can drive (spec D3.a).

use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};

use serde::Serialize;

use super::process::{CliCommand, Runner, find_on_path, is_executable};

/// Where the CLI was found.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CliSource {
    /// The path saved in the app's settings.
    Configured,
    /// `pdf2audiobook` on `PATH`.
    OnPath,
    /// `uv run --project <checkout> pdf2audiobook`.
    UvProject,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LocatedCli {
    pub command: CliCommand,
    pub version: String,
    pub source: CliSource,
}

/// Why no usable CLI was found. Messages never include paths.
#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum LocateError {
    #[error("The pdf2audiobook command-line tool was not found")]
    NotFound,
    #[error("The pdf2audiobook command-line tool did not respond as expected")]
    Unresponsive,
    #[error(
        "pdf2audiobook {cli} can't be used with this app ({app}); install a {app_series}.x version"
    )]
    VersionMismatch {
        cli: String,
        app: String,
        app_series: String,
    },
}

impl LocateError {
    /// Which failure to report when every candidate fails: the most specific one.
    fn rank(&self) -> u8 {
        match self {
            LocateError::NotFound => 0,
            LocateError::Unresponsive => 1,
            LocateError::VersionMismatch { .. } => 2,
        }
    }
}

pub struct LocateOptions<'a> {
    /// The CLI path saved in the app's settings, if any.
    pub configured: Option<&'a Path>,
    /// A source checkout to run with `uv run --project`, if the user chose one.
    pub uv_project: Option<&'a Path>,
    /// The `PATH` to search.
    pub path_env: Option<&'a OsStr>,
    /// This app's version, e.g. `env!("CARGO_PKG_VERSION")`.
    pub app_version: &'a str,
}

/// Try the configured path, then `PATH`, then `uv run --project`, and return the first CLI
/// whose `--version` and `doctor --json` agree and whose major and minor version match the app.
pub fn locate(options: &LocateOptions<'_>, runner: &dyn Runner) -> Result<LocatedCli, LocateError> {
    let mut candidates: Vec<(CliSource, CliCommand)> = Vec::new();
    if let Some(path) = options.configured.filter(|path| is_executable(path)) {
        candidates.push((CliSource::Configured, CliCommand::direct(path)));
    }
    if let Some(path) = find_on_path("pdf2audiobook", options.path_env) {
        candidates.push((CliSource::OnPath, CliCommand::direct(path)));
    }
    if let (Some(project), Some(uv)) = (options.uv_project, find_on_path("uv", options.path_env)) {
        candidates.push((CliSource::UvProject, uv_command(uv, project)));
    }
    let mut failure = LocateError::NotFound;
    for (source, command) in candidates {
        match confirm(&command, runner, options.app_version) {
            Ok(version) => {
                return Ok(LocatedCli {
                    command,
                    version,
                    source,
                });
            }
            Err(error) if error.rank() > failure.rank() => failure = error,
            Err(_) => {}
        }
    }
    Err(failure)
}

fn uv_command(uv: PathBuf, project: &Path) -> CliCommand {
    CliCommand {
        program: uv,
        prefix: vec![
            OsString::from("run"),
            OsString::from("--project"),
            project.as_os_str().to_owned(),
            OsString::from("pdf2audiobook"),
        ],
    }
}

fn confirm(
    command: &CliCommand,
    runner: &dyn Runner,
    app_version: &str,
) -> Result<String, LocateError> {
    let version = runner
        .run(command, &[OsString::from("--version")])
        .ok()
        .filter(|done| done.code == Some(0))
        .map(|done| done.stdout.trim().to_owned())
        .filter(|text| series(text).is_some())
        .ok_or(LocateError::Unresponsive)?;
    let doctor = runner
        .run(
            command,
            &[OsString::from("doctor"), OsString::from("--json")],
        )
        .ok()
        .filter(|done| done.code == Some(0))
        .and_then(|done| serde_json::from_str::<serde_json::Value>(&done.stdout).ok())
        .ok_or(LocateError::Unresponsive)?;
    if doctor.get("version").and_then(|value| value.as_str()) != Some(version.as_str()) {
        return Err(LocateError::Unresponsive);
    }
    let app_series = series(app_version).ok_or(LocateError::Unresponsive)?;
    if series(&version) != Some(app_series.clone()) {
        return Err(LocateError::VersionMismatch {
            cli: version,
            app: app_version.to_owned(),
            app_series,
        });
    }
    Ok(version)
}

/// `"major.minor"` of a `major.minor.patch` version, or `None` if it isn't one.
fn series(version: &str) -> Option<String> {
    let mut parts = version.split('.');
    let (major, minor, patch) = (parts.next()?, parts.next()?, parts.next()?);
    let numeric = |part: &str| !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit());
    let patch_number: String = patch.chars().take_while(char::is_ascii_digit).collect();
    (numeric(major) && numeric(minor) && !patch_number.is_empty())
        .then(|| format!("{major}.{minor}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::testing::{TestRunner, write_script};
    use std::fs;
    use std::os::unix::fs::PermissionsExt;
    use tempfile::TempDir;

    const APP: &str = "0.1.0";

    /// A fake `pdf2audiobook` whose `--version` and `doctor --json` report `version`.
    fn fake_cli(folder: &Path, name: &str, version: &str, doctor_version: &str) -> PathBuf {
        let script = format!(
            "#!/bin/sh\ncase \"$*\" in\n  \"--version\") echo '{version}' ;;\n  \"doctor --json\") echo '{{\"version\": \"{doctor_version}\", \"ffmpeg\": true}}' ;;\n  *) exit 2 ;;\nesac\n"
        );
        write_script(folder, name, &script)
    }

    /// A fake `uv` that answers only for `run --project <project> pdf2audiobook ...`.
    fn fake_uv(folder: &Path, project: &Path, version: &str) -> PathBuf {
        let prefix = format!("run --project {} pdf2audiobook", project.display());
        let script = format!(
            "#!/bin/sh\ncase \"$*\" in\n  \"{prefix} --version\") echo '{version}' ;;\n  \"{prefix} doctor --json\") echo '{{\"version\": \"{version}\"}}' ;;\n  *) exit 2 ;;\nesac\n"
        );
        write_script(folder, "uv", &script)
    }

    fn options<'a>(
        configured: Option<&'a Path>,
        uv_project: Option<&'a Path>,
        path_env: Option<&'a OsStr>,
    ) -> LocateOptions<'a> {
        LocateOptions {
            configured,
            uv_project,
            path_env,
            app_version: APP,
        }
    }

    #[test]
    fn configured_path_is_used_first() {
        let temp = TempDir::new().unwrap();
        let configured = fake_cli(&temp.path().join("custom"), "my-cli", "0.1.7", "0.1.7");
        fake_cli(&temp.path().join("bin"), "pdf2audiobook", "0.1.2", "0.1.2");
        let path_env = temp.path().join("bin").into_os_string();

        let found = locate(
            &options(Some(&configured), None, Some(&path_env)),
            &TestRunner,
        )
        .unwrap();

        assert_eq!(found.source, CliSource::Configured);
        assert_eq!(found.command, CliCommand::direct(&configured));
        assert_eq!(found.version, "0.1.7");
    }

    #[test]
    fn cli_on_path_is_found() {
        let temp = TempDir::new().unwrap();
        let cli = fake_cli(&temp.path().join("bin"), "pdf2audiobook", "0.1.0", "0.1.0");
        let path_env =
            std::env::join_paths([temp.path().join("empty"), temp.path().join("bin")]).unwrap();

        let found = locate(&options(None, None, Some(&path_env)), &TestRunner).unwrap();

        assert_eq!(found.source, CliSource::OnPath);
        assert_eq!(found.command, CliCommand::direct(cli));
    }

    #[test]
    fn source_checkout_runs_through_uv() {
        let temp = TempDir::new().unwrap();
        let project = temp.path().join("checkout with spaces");
        fs::create_dir_all(&project).unwrap();
        let uv = fake_uv(&temp.path().join("bin"), &project, "0.1.4");
        let path_env = temp.path().join("bin").into_os_string();

        let found = locate(&options(None, Some(&project), Some(&path_env)), &TestRunner).unwrap();

        assert_eq!(found.source, CliSource::UvProject);
        assert_eq!(found.command.program, uv);
        assert_eq!(
            found.command.prefix,
            vec![
                OsString::from("run"),
                OsString::from("--project"),
                project.into_os_string(),
                OsString::from("pdf2audiobook"),
            ]
        );
        assert_eq!(found.version, "0.1.4");
    }

    #[test]
    fn a_different_minor_version_is_refused() {
        let temp = TempDir::new().unwrap();
        fake_cli(&temp.path().join("bin"), "pdf2audiobook", "0.2.0", "0.2.0");
        let path_env = temp.path().join("bin").into_os_string();

        let error = locate(&options(None, None, Some(&path_env)), &TestRunner).unwrap_err();

        assert_eq!(
            error,
            LocateError::VersionMismatch {
                cli: "0.2.0".into(),
                app: APP.into(),
                app_series: "0.1".into()
            }
        );
        assert_eq!(
            error.to_string(),
            "pdf2audiobook 0.2.0 can't be used with this app (0.1.0); install a 0.1.x version"
        );
    }

    #[test]
    fn a_different_major_version_is_refused() {
        let temp = TempDir::new().unwrap();
        fake_cli(&temp.path().join("bin"), "pdf2audiobook", "1.1.0", "1.1.0");
        let path_env = temp.path().join("bin").into_os_string();

        let error = locate(&options(None, None, Some(&path_env)), &TestRunner).unwrap_err();

        assert!(matches!(error, LocateError::VersionMismatch { .. }));
    }

    #[test]
    fn a_mismatched_configured_cli_falls_back_to_a_matching_one_on_path() {
        let temp = TempDir::new().unwrap();
        let configured = fake_cli(&temp.path().join("old"), "pdf2audiobook", "0.0.9", "0.0.9");
        fake_cli(&temp.path().join("bin"), "pdf2audiobook", "0.1.1", "0.1.1");
        let path_env = temp.path().join("bin").into_os_string();

        let found = locate(
            &options(Some(&configured), None, Some(&path_env)),
            &TestRunner,
        )
        .unwrap();

        assert_eq!(found.source, CliSource::OnPath);
        assert_eq!(found.version, "0.1.1");
    }

    #[test]
    fn doctor_disagreeing_with_version_is_unresponsive() {
        let temp = TempDir::new().unwrap();
        fake_cli(&temp.path().join("bin"), "pdf2audiobook", "0.1.0", "0.1.5");
        let path_env = temp.path().join("bin").into_os_string();

        let error = locate(&options(None, None, Some(&path_env)), &TestRunner).unwrap_err();

        assert_eq!(error, LocateError::Unresponsive);
    }

    #[test]
    fn something_else_called_pdf2audiobook_is_unresponsive() {
        let temp = TempDir::new().unwrap();
        write_script(
            &temp.path().join("bin"),
            "pdf2audiobook",
            "#!/bin/sh\necho hello\n",
        );
        let path_env = temp.path().join("bin").into_os_string();

        let error = locate(&options(None, None, Some(&path_env)), &TestRunner).unwrap_err();

        assert_eq!(error, LocateError::Unresponsive);
    }

    #[test]
    fn nothing_found_reports_not_found_without_paths() {
        let temp = TempDir::new().unwrap();
        let private = temp.path().join("private-folder");
        let path_env = private.clone().into_os_string();

        let error = locate(
            &options(Some(&private.join("cli")), None, Some(&path_env)),
            &TestRunner,
        )
        .unwrap_err();

        assert_eq!(error, LocateError::NotFound);
        assert!(!error.to_string().contains("private-folder"));
    }

    #[test]
    fn a_file_that_is_not_executable_is_skipped() {
        let temp = TempDir::new().unwrap();
        let bin = temp.path().join("bin");
        let cli = fake_cli(&bin, "pdf2audiobook", "0.1.0", "0.1.0");
        fs::set_permissions(&cli, fs::Permissions::from_mode(0o644)).unwrap();
        let path_env = bin.into_os_string();

        let error = locate(&options(None, None, Some(&path_env)), &TestRunner).unwrap_err();

        assert_eq!(error, LocateError::NotFound);
    }

    #[test]
    fn series_reads_major_and_minor() {
        assert_eq!(series("0.1.0").as_deref(), Some("0.1"));
        assert_eq!(series("12.34.5rc1").as_deref(), Some("12.34"));
        assert_eq!(series("0.1"), None);
        assert_eq!(series("a.b.c"), None);
        assert_eq!(series(""), None);
    }
}
