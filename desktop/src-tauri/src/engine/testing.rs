//! Test helpers: fake CLI scripts, and a runner that tolerates a test-only spawn race.

use std::ffi::OsString;
use std::fs;
use std::io;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::thread;
use std::time::Duration;

use super::process::{CliCommand, Finished, Runner, SystemRunner};

/// How many spawns hit `ETXTBSY` and were retried, across all tests.
pub static BUSY_RETRIES: AtomicUsize = AtomicUsize::new(0);

/// Writes an executable shell script.
pub fn write_script(folder: &Path, name: &str, body: &str) -> PathBuf {
    fs::create_dir_all(folder).unwrap();
    let path = folder.join(name);
    fs::write(&path, body).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

/// [`SystemRunner`] that retries a spawn failing with `ETXTBSY` (errno 26).
///
/// Tests write fake CLI scripts while other test threads fork children. A child forked in that
/// moment briefly holds the script open for writing, and running the script then fails with
/// "text file busy". The app never writes the programs it runs, so only tests need this.
pub struct TestRunner;

const ETXTBSY: i32 = 26;

impl Runner for TestRunner {
    fn run(&self, cli: &CliCommand, args: &[OsString]) -> io::Result<Finished> {
        for _ in 0..100 {
            match SystemRunner.run(cli, args) {
                Err(error) if error.raw_os_error() == Some(ETXTBSY) => {
                    BUSY_RETRIES.fetch_add(1, Ordering::Relaxed);
                    thread::sleep(Duration::from_millis(5));
                }
                result => return result,
            }
        }
        SystemRunner.run(cli, args)
    }
}
