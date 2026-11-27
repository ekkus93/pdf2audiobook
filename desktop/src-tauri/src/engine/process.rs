//! Starting the CLI as a child process: never through a shell, always with an argument vector.

use std::ffi::{OsStr, OsString};
use std::io;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// How to start the CLI: a program plus fixed leading arguments (for `uv run --project`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CliCommand {
    pub program: PathBuf,
    pub prefix: Vec<OsString>,
}

impl CliCommand {
    pub fn direct(program: impl Into<PathBuf>) -> Self {
        Self {
            program: program.into(),
            prefix: Vec::new(),
        }
    }

    /// The full argument vector after the program: the fixed prefix, then `args`.
    pub fn argv(&self, args: &[OsString]) -> Vec<OsString> {
        self.prefix.iter().chain(args).cloned().collect()
    }
}

/// What a finished command left behind.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Finished {
    /// `None` when the process was ended by a signal.
    pub code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
}

/// Runs a command to completion. Tests substitute their own.
pub trait Runner: Send + Sync {
    fn run(&self, cli: &CliCommand, args: &[OsString]) -> io::Result<Finished>;
}

/// Variables an AppImage's launcher sets for itself; a child process has no use for them.
const APPIMAGE_OWN: [&str; 4] = ["APPDIR", "APPIMAGE", "ARGV0", "OWD"];

/// How to give a child process the host's environment back when the app runs from an AppImage.
///
/// The AppImage launcher points `PATH`, `PYTHONHOME`, `PYTHONPATH`, `LD_LIBRARY_PATH`,
/// `XDG_DATA_DIRS` and GTK/GIO settings into the image (`$APPDIR`). A child inheriting them runs
/// the image's libraries, and the CLI's Python can't even start. Each variable whose value
/// points into the image keeps only its entries outside it, or is removed if none are left; the
/// launcher's own variables are removed. Everything else, such as `PDF2AUDIOBOOK_*` and password
/// variables, is passed on unchanged (spec D3.e). Outside an AppImage nothing changes.
pub fn host_environment(vars: &[(OsString, OsString)]) -> Vec<(OsString, Option<OsString>)> {
    let Some(appdir) = vars
        .iter()
        .find(|(key, _)| key == "APPDIR")
        .and_then(|(_, value)| value.to_str())
        .map(|value| value.trim_end_matches('/').to_owned())
        .filter(|value| !value.is_empty())
    else {
        return Vec::new();
    };
    let inside = |entry: &str| entry == appdir || entry.starts_with(&format!("{appdir}/"));
    let mut changes = Vec::new();
    for (key, value) in vars {
        if APPIMAGE_OWN.iter().any(|own| key == own) {
            changes.push((key.clone(), None));
            continue;
        }
        let Some(text) = value.to_str() else { continue };
        if !text.split(':').any(inside) {
            continue;
        }
        let kept: Vec<&str> = text
            .split(':')
            .filter(|entry| !entry.is_empty() && !inside(entry))
            .collect();
        let restored = (!kept.is_empty()).then(|| OsString::from(kept.join(":")));
        changes.push((key.clone(), restored));
    }
    changes
}

/// The folder child processes run in: `HOME`, if it is an existing absolute folder.
///
/// The CLI resolves its default output folder (`./audiobooks`) against the folder it runs in,
/// and the app's own folder depends on how it was started (`/` from some launchers, the
/// download folder from a file manager). Running from home keeps books in `~/audiobooks`.
pub fn home_folder(vars: &[(OsString, OsString)]) -> Option<std::path::PathBuf> {
    vars.iter()
        .find(|(key, _)| key == "HOME")
        .map(|(_, value)| std::path::PathBuf::from(value))
        .filter(|home| home.is_absolute() && home.is_dir())
}

/// Applies [`host_environment`] for this process's environment to `command`, and runs it from
/// the home folder ([`home_folder`]).
pub fn use_host_environment(command: &mut Command) -> &mut Command {
    let vars: Vec<(OsString, OsString)> = std::env::vars_os().collect();
    for (key, value) in host_environment(&vars) {
        match value {
            Some(value) => command.env(key, value),
            None => command.env_remove(key),
        };
    }
    if let Some(home) = home_folder(&vars) {
        command.current_dir(home);
    }
    command
}

/// Runs real processes. The child inherits the app's environment (spec D3.e), so
/// `PDF2AUDIOBOOK_*` settings, the config file and password variables keep working; only what
/// an AppImage's launcher pointed into the image is undone ([`host_environment`]).
#[derive(Clone, Copy, Debug, Default)]
pub struct SystemRunner;

impl Runner for SystemRunner {
    fn run(&self, cli: &CliCommand, args: &[OsString]) -> io::Result<Finished> {
        let output = use_host_environment(&mut Command::new(&cli.program))
            .args(cli.argv(args))
            .stdin(Stdio::null())
            .output()?;
        Ok(Finished {
            code: output.status.code(),
            stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        })
    }
}

/// Finds an executable named `name` in a `PATH`-style list of folders.
pub fn find_on_path(name: &str, path_env: Option<&OsStr>) -> Option<PathBuf> {
    let path_env = path_env?;
    std::env::split_paths(path_env)
        .map(|folder| folder.join(name))
        .find(|candidate| is_executable(candidate))
}

pub fn is_executable(path: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        path.metadata()
            .map(|meta| meta.is_file() && meta.permissions().mode() & 0o111 != 0)
            .unwrap_or(false)
    }
    #[cfg(not(unix))]
    {
        path.is_file()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::testing::{TestRunner, write_script};
    use tempfile::TempDir;

    #[test]
    fn the_child_inherits_the_app_environment() {
        let temp = TempDir::new().unwrap();
        let cli = write_script(
            temp.path(),
            "env-echo",
            "#!/bin/sh\nprintf '%s\\n%s' \"$HOME\" \"$PATH\"\n",
        );

        let done = TestRunner.run(&CliCommand::direct(cli), &[]).unwrap();

        let expected = format!(
            "{}\n{}",
            std::env::var("HOME").unwrap(),
            std::env::var("PATH").unwrap()
        );
        assert_eq!(done.stdout, expected);
    }

    #[test]
    fn the_child_runs_in_the_home_folder() {
        // The CLI's default output folder is relative ("./audiobooks"); however the app was
        // started (a launcher in `/`, a file manager in Downloads), books go to ~/audiobooks.
        let Some(home) = home_folder(&std::env::vars_os().collect::<Vec<_>>()) else {
            return; // No usable HOME in this test environment.
        };
        let temp = TempDir::new().unwrap();
        let cli = write_script(temp.path(), "where", "#!/bin/sh\npwd -P\n");

        let done = TestRunner.run(&CliCommand::direct(cli), &[]).unwrap();

        assert_eq!(
            done.stdout.trim(),
            home.canonicalize().unwrap().to_str().unwrap()
        );
    }

    #[test]
    fn the_home_folder_must_be_an_absolute_folder() {
        let temp = TempDir::new().unwrap();
        let vars = |home: &str| vec![(OsString::from("HOME"), OsString::from(home))];
        assert_eq!(
            home_folder(&vars(temp.path().to_str().unwrap())),
            Some(temp.path().to_path_buf())
        );
        assert_eq!(home_folder(&vars("relative/home")), None);
        assert_eq!(home_folder(&vars("")), None);
        assert_eq!(home_folder(&vars("/no/such/folder/here")), None);
        assert_eq!(home_folder(&[]), None);
    }

    #[test]
    fn the_child_gets_no_input_and_its_output_is_captured() {
        let temp = TempDir::new().unwrap();
        let cli = write_script(
            temp.path(),
            "io",
            "#!/bin/sh\nread line || echo no-input\necho err >&2\nexit 7\n",
        );

        let done = TestRunner.run(&CliCommand::direct(cli), &[]).unwrap();

        assert_eq!(
            done,
            Finished {
                code: Some(7),
                stdout: "no-input\n".into(),
                stderr: "err\n".into()
            }
        );
    }

    #[test]
    fn find_on_path_needs_an_executable_file() {
        let temp = TempDir::new().unwrap();
        write_script(&temp.path().join("bin"), "tool", "#!/bin/sh\n");
        std::fs::create_dir_all(temp.path().join("dir/tool")).unwrap();
        let path_env =
            std::env::join_paths([temp.path().join("dir"), temp.path().join("bin")]).unwrap();

        assert_eq!(
            find_on_path("tool", Some(&path_env)),
            Some(temp.path().join("bin/tool"))
        );
        assert_eq!(find_on_path("missing", Some(&path_env)), None);
        assert_eq!(find_on_path("tool", None), None);
    }
}

#[cfg(test)]
mod environment_tests {
    use super::*;

    fn vars(pairs: &[(&str, &str)]) -> Vec<(OsString, OsString)> {
        pairs
            .iter()
            .map(|(key, value)| (OsString::from(key), OsString::from(value)))
            .collect()
    }

    fn changes(pairs: &[(&str, &str)]) -> Vec<(String, Option<String>)> {
        let mut changed: Vec<(String, Option<String>)> = host_environment(&vars(pairs))
            .into_iter()
            .map(|(key, value)| {
                (
                    key.into_string().unwrap(),
                    value.map(|value| value.into_string().unwrap()),
                )
            })
            .collect();
        changed.sort();
        changed
    }

    #[test]
    fn outside_an_appimage_nothing_changes() {
        assert!(changes(&[("PATH", "/usr/bin:/bin"), ("PYTHONHOME", "/opt/py")]).is_empty());
    }

    #[test]
    fn variables_pointing_into_the_image_are_given_back_to_the_host() {
        let image = "/tmp/appimage_extracted_c991";
        let changed = changes(&[
            ("APPDIR", image),
            ("APPIMAGE", "/home/me/Apps/pdf2audiobook.AppImage"),
            ("ARGV0", "pdf2audiobook.AppImage"),
            ("OWD", "/home/me"),
            (
                "PATH",
                &format!("{image}/usr/bin/:{image}/usr/sbin/:/usr/local/bin:/usr/bin"),
            ),
            ("PYTHONHOME", &format!("{image}/usr/")),
            ("PYTHONPATH", &format!("{image}/usr/share/pyshared/:")),
            (
                "LD_LIBRARY_PATH",
                &format!("{image}/usr/lib/:/usr/local/nvidia/lib"),
            ),
            (
                "XDG_DATA_DIRS",
                &format!("{image}/usr/share:/usr/share:/usr/local/share"),
            ),
            ("GTK_PATH", &format!("{image}//usr/lib/gtk-3.0")),
            ("GTK_THEME", "Adwaita:dark"),
            ("HOME", "/home/me"),
            ("PDF2AUDIOBOOK_LLM_PROVIDER", "ollama"),
            ("BOOK_PASSWORD", "secret"),
            ("OTHER", "/tmp/appimage_extracted_c9912/usr/lib"),
        ]);
        assert_eq!(
            changed,
            [
                ("APPDIR".into(), None),
                ("APPIMAGE".into(), None),
                ("ARGV0".into(), None),
                ("GTK_PATH".into(), None),
                (
                    "LD_LIBRARY_PATH".into(),
                    Some("/usr/local/nvidia/lib".into())
                ),
                ("OWD".into(), None),
                ("PATH".into(), Some("/usr/local/bin:/usr/bin".into())),
                ("PYTHONHOME".into(), None),
                ("PYTHONPATH".into(), None),
                (
                    "XDG_DATA_DIRS".into(),
                    Some("/usr/share:/usr/local/share".into())
                ),
            ]
        );
    }

    #[test]
    fn a_child_started_from_an_appimage_sees_the_host_environment() {
        let image = "/tmp/appimage_extracted_test";
        let mut command = Command::new("/bin/sh");
        command.args([
            "-c",
            "printf '%s|%s|%s' \"$PYTHONHOME\" \"$PATH\" \"$KEEP\"",
        ]);
        command
            .env("APPDIR", image)
            .env("PYTHONHOME", format!("{image}/usr/"));
        command
            .env("PATH", format!("{image}/usr/bin:/usr/bin:/bin"))
            .env("KEEP", "kept");
        // The child's environment is what the command would pass on; apply the same rules to it.
        let given: Vec<(OsString, OsString)> = command
            .get_envs()
            .filter_map(|(key, value)| Some((key.to_owned(), value?.to_owned())))
            .collect();
        for (key, value) in host_environment(&given) {
            match value {
                Some(value) => command.env(key, value),
                None => command.env_remove(key),
            };
        }
        let output = command.output().unwrap();
        assert_eq!(
            String::from_utf8(output.stdout).unwrap(),
            "|/usr/bin:/bin|kept"
        );
    }
}
