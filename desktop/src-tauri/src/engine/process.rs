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

/// Runs real processes. The child inherits the app's environment unchanged (spec D3.e), so
/// `PDF2AUDIOBOOK_*` settings, the config file and password variables keep working.
#[derive(Clone, Copy, Debug, Default)]
pub struct SystemRunner;

impl Runner for SystemRunner {
    fn run(&self, cli: &CliCommand, args: &[OsString]) -> io::Result<Finished> {
        let output = Command::new(&cli.program)
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
