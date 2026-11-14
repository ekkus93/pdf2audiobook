//! Tauri commands: the frontend's only way to reach the engine (spec D3, D8.a).

use std::ffi::{OsStr, OsString};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, PoisonError};

use base64::Engine as _;
use serde::Serialize;
use tauri::{AppHandle, Manager, State};

use crate::engine::locate::{CliSource, LocateError, LocateOptions, LocatedCli, locate};
use crate::engine::process::{CliCommand, Runner, SystemRunner};
use crate::engine::request::Request;
use crate::engine::result::{Outcome, parse};
use crate::engine::runs::WorkspaceRuns;
use crate::library;
use crate::settings::AppSettings;

/// Shared bridge state.
pub struct Engine {
    pub runner: Arc<dyn Runner>,
    pub cli: Mutex<Option<LocatedCli>>,
    pub runs: Arc<WorkspaceRuns>,
}

impl Default for Engine {
    fn default() -> Self {
        Self {
            runner: Arc::new(SystemRunner),
            cli: Mutex::new(None),
            runs: WorkspaceRuns::new(),
        }
    }
}

/// Errors the frontend can tell apart. Messages hold no paths or book content.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, thiserror::Error)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum BridgeError {
    #[error("{message}")]
    Locate { error: LocateError, message: String },
    #[error("{message}")]
    Request { message: String },
    #[error("{message}")]
    Busy { message: String },
    #[error("The engine could not be started")]
    Start,
}

impl From<LocateError> for BridgeError {
    fn from(error: LocateError) -> Self {
        let message = error.to_string();
        BridgeError::Locate { error, message }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct EngineInfo {
    pub version: String,
    pub source: CliSource,
    /// How the CLI is started, for the "Details" disclosure.
    pub command: String,
}

/// Finds the CLI using the app's settings and the `PATH`.
pub fn locate_with(
    settings: &AppSettings,
    path_env: Option<&OsStr>,
    runner: &dyn Runner,
) -> Result<LocatedCli, LocateError> {
    locate(
        &LocateOptions {
            configured: settings.cli_path.as_deref(),
            uv_project: settings.uv_project.as_deref(),
            path_env,
            app_version: env!("CARGO_PKG_VERSION"),
        },
        runner,
    )
}

/// A readable command line for "Details". Display only: commands never run through a shell.
pub fn display_command(cli: &CliCommand, args: &[OsString]) -> String {
    let program = cli
        .program
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| cli.program.to_string_lossy().into_owned());
    std::iter::once(program)
        .chain(
            cli.argv(args)
                .iter()
                .map(|arg| quote(&arg.to_string_lossy())),
        )
        .collect::<Vec<_>>()
        .join(" ")
}

fn quote(word: &str) -> String {
    let plain = !word.is_empty()
        && word
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "-_./=:,@%+".contains(c));
    if plain {
        word.to_owned()
    } else {
        format!("'{}'", word.replace('\'', r"'\''"))
    }
}

fn settings_dir(app: &AppHandle) -> Result<PathBuf, BridgeError> {
    app.path().app_config_dir().map_err(|_| BridgeError::Start)
}

fn located(engine: &Engine, app: &AppHandle) -> Result<LocatedCli, BridgeError> {
    if let Some(cli) = engine
        .cli
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .clone()
    {
        return Ok(cli);
    }
    let settings = AppSettings::load(&settings_dir(app)?);
    let path_env = std::env::var_os("PATH");
    let cli = locate_with(&settings, path_env.as_deref(), engine.runner.as_ref())?;
    *engine.cli.lock().unwrap_or_else(PoisonError::into_inner) = Some(cli.clone());
    Ok(cli)
}

#[tauri::command]
pub async fn locate_engine(
    app: AppHandle,
    engine: State<'_, Engine>,
) -> Result<EngineInfo, BridgeError> {
    *engine.cli.lock().unwrap_or_else(PoisonError::into_inner) = None;
    let runner = Arc::clone(&engine.runner);
    let settings = AppSettings::load(&settings_dir(&app)?);
    let cli = tauri::async_runtime::spawn_blocking(move || {
        let path_env = std::env::var_os("PATH");
        locate_with(&settings, path_env.as_deref(), runner.as_ref())
    })
    .await
    .map_err(|_| BridgeError::Start)??;
    *engine.cli.lock().unwrap_or_else(PoisonError::into_inner) = Some(cli.clone());
    Ok(EngineInfo {
        version: cli.version.clone(),
        source: cli.source,
        command: display_command(&cli.command, &[]),
    })
}

#[tauri::command]
pub fn describe_request(
    app: AppHandle,
    engine: State<'_, Engine>,
    request: Request,
) -> Result<String, BridgeError> {
    let args = request.args().map_err(|error| BridgeError::Request {
        message: error.to_string(),
    })?;
    let cli = located(&engine, &app)?;
    Ok(display_command(&cli.command, &args))
}

/// Runs one request. A write-capable request must name its workspace (spec D3.d).
#[tauri::command]
pub async fn run_engine(
    app: AppHandle,
    engine: State<'_, Engine>,
    request: Request,
    workspace: Option<PathBuf>,
) -> Result<Outcome, BridgeError> {
    let args = request.args().map_err(|error| BridgeError::Request {
        message: error.to_string(),
    })?;
    let cli = located(&engine, &app)?;
    let guard = match (&workspace, request.is_write()) {
        (Some(path), _) => {
            Some(
                engine
                    .runs
                    .try_start(path, &request)
                    .map_err(|busy| BridgeError::Busy {
                        message: busy.to_string(),
                    })?,
            )
        }
        (None, false) => None,
        (None, true) => {
            return Err(BridgeError::Request {
                message: "A task that changes a book must name its workspace".into(),
            });
        }
    };
    let runner = Arc::clone(&engine.runner);
    let done = tauri::async_runtime::spawn_blocking(move || {
        let _guard = guard;
        runner.run(&cli.command, &args)
    })
    .await
    .map_err(|_| BridgeError::Start)?
    .map_err(|_| BridgeError::Start)?;
    Ok(parse(&done))
}

#[tauri::command]
pub fn get_settings(app: AppHandle) -> Result<AppSettings, BridgeError> {
    Ok(AppSettings::load(&settings_dir(&app)?))
}

#[tauri::command]
pub fn save_settings(
    app: AppHandle,
    engine: State<'_, Engine>,
    settings: AppSettings,
) -> Result<(), BridgeError> {
    settings
        .save(&settings_dir(&app)?)
        .map_err(|_| BridgeError::Request {
            message: "The settings could not be saved".into(),
        })?;
    // A new CLI location takes effect on the next request.
    *engine.cli.lock().unwrap_or_else(PoisonError::into_inner) = None;
    Ok(())
}

/// One book on the Library screen.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct LibraryBook {
    pub workspace: PathBuf,
    pub manifest: PathBuf,
    /// False for a book added in the app whose workspace doesn't exist yet.
    pub analyzed: bool,
    /// The book file, for a book that isn't analyzed yet.
    pub source: Option<PathBuf>,
    /// `inspect MANIFEST --json`, or `None` when it failed (see `error`).
    pub inspect: Option<serde_json::Value>,
    pub error: Option<String>,
    pub run_status: Option<serde_json::Value>,
    /// A `data:image/png;base64,...` thumbnail of the source book, when it can be made.
    pub thumbnail: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Library {
    pub output_dir: PathBuf,
    /// `chapters.min_boundary_confidence` from the CLI's configuration.
    pub min_boundary_confidence: f64,
    pub books: Vec<LibraryBook>,
}

/// Builds the library: the CLI's configuration, then `inspect` and a cached thumbnail per book,
/// then any added book whose workspace doesn't exist yet.
pub fn build_library(
    cli: &CliCommand,
    runner: &dyn Runner,
    configured_output: Option<&Path>,
    added_books: &[PathBuf],
    thumbnails: &Path,
) -> Result<Library, BridgeError> {
    let config = run_success(cli, runner, &Request::ConfigShow)?;
    let output_dir = match configured_output {
        Some(path) => path.to_path_buf(),
        None => config["general"]["output_dir"]
            .as_str()
            .map(PathBuf::from)
            .ok_or(BridgeError::Request {
                message: "The engine reported no output folder".into(),
            })?,
    };
    let min_boundary_confidence = config["chapters"]["min_boundary_confidence"]
        .as_f64()
        .unwrap_or(0.75);
    let books = library::workspaces(&output_dir)
        .into_iter()
        .map(|dir| {
            let inspected = run_success(
                cli,
                runner,
                &Request::Inspect {
                    source: dir.manifest.clone(),
                    pdf_password_env: None,
                },
            );
            let (inspect, error) = match inspected {
                Ok(value) => (Some(value), None),
                Err(problem) => (None, Some(problem.to_string())),
            };
            let thumbnail = inspect
                .as_ref()
                .and_then(|value| value["source_path"].as_str())
                .and_then(|source| {
                    thumbnail(cli, runner, Path::new(source), &dir.workspace, thumbnails)
                });
            LibraryBook {
                run_status: library::run_status(&dir.workspace),
                workspace: dir.workspace,
                manifest: dir.manifest,
                analyzed: true,
                source: None,
                inspect,
                error,
                thumbnail,
            }
        })
        .collect::<Vec<_>>();
    let mut books = books;
    for book in added_books {
        let request = Request::Workspace {
            book: book.clone(),
            output: Some(output_dir.clone()),
        };
        let Ok(found) = run_success(cli, runner, &request) else {
            continue;
        };
        let Some(workspace) = found["workspace"].as_str().map(PathBuf::from) else {
            continue;
        };
        if books.iter().any(|known| known.workspace == workspace) {
            continue;
        }
        books.push(LibraryBook {
            manifest: workspace.join("manifest.json"),
            thumbnail: thumbnail(cli, runner, book, &workspace, thumbnails),
            workspace,
            analyzed: false,
            source: Some(book.clone()),
            inspect: None,
            error: None,
            run_status: None,
        });
    }
    Ok(Library {
        output_dir,
        min_boundary_confidence,
        books,
    })
}

fn run_success(
    cli: &CliCommand,
    runner: &dyn Runner,
    request: &Request,
) -> Result<serde_json::Value, BridgeError> {
    let args = request.args().map_err(|error| BridgeError::Request {
        message: error.to_string(),
    })?;
    let done = runner.run(cli, &args).map_err(|_| BridgeError::Start)?;
    match parse(&done) {
        Outcome::Success { result } => Ok(result),
        Outcome::Failed { error, .. } => Err(BridgeError::Request {
            message: error.message,
        }),
        Outcome::Unreadable { .. } => Err(BridgeError::Request {
            message: crate::engine::result::UNREADABLE_MESSAGE.into(),
        }),
    }
}

/// A cached PNG of the book's first page, made with `thumbnail` when missing or older than the book.
fn thumbnail(
    cli: &CliCommand,
    runner: &dyn Runner,
    source: &Path,
    workspace: &Path,
    cache: &Path,
) -> Option<String> {
    let name = workspace.file_name()?.to_string_lossy().into_owned();
    let png = cache.join(format!("{name}.png"));
    let modified = |path: &Path| fs::metadata(path).and_then(|meta| meta.modified()).ok();
    let fresh =
        matches!((modified(&png), modified(source)), (Some(made), Some(book)) if made >= book);
    if !fresh {
        fs::create_dir_all(cache).ok()?;
        let request = Request::Thumbnail {
            book: source.to_path_buf(),
            output: png.clone(),
            width: 320,
            pdf_password_env: None,
        };
        run_success(cli, runner, &request).ok()?;
    }
    let bytes = fs::read(&png).ok()?;
    Some(format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(bytes)
    ))
}

#[tauri::command]
pub async fn library(app: AppHandle, engine: State<'_, Engine>) -> Result<Library, BridgeError> {
    let cli = located(&engine, &app)?;
    let settings = AppSettings::load(&settings_dir(&app)?);
    let thumbnails = app
        .path()
        .app_cache_dir()
        .map_err(|_| BridgeError::Start)?
        .join("thumbnails");
    let runner = Arc::clone(&engine.runner);
    tauri::async_runtime::spawn_blocking(move || {
        build_library(
            &cli.command,
            runner.as_ref(),
            settings.output_dir.as_deref(),
            &settings.added_books,
            &thumbnails,
        )
    })
    .await
    .map_err(|_| BridgeError::Start)?
}

/// Remembers a book the user picked, so the library shows it before it is analyzed.
#[tauri::command]
pub fn add_book(app: AppHandle, book: PathBuf) -> Result<(), BridgeError> {
    let folder = settings_dir(&app)?;
    let mut settings = AppSettings::load(&folder);
    settings.add_book(book);
    settings.save(&folder).map_err(|_| BridgeError::Request {
        message: "The book could not be added".into(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::testing::{TestRunner, write_script};
    use tempfile::TempDir;

    #[test]
    fn display_command_quotes_only_when_needed() {
        let cli = CliCommand {
            program: "/home/me/.local/bin/uv".into(),
            prefix: vec![
                "run".into(),
                "--project".into(),
                "/src/my checkout".into(),
                "pdf2audiobook".into(),
            ],
        };
        let args: Vec<OsString> = vec![
            "--no-progress".into(),
            "inspect".into(),
            "--json".into(),
            "--".into(),
            "/b/it's.pdf".into(),
        ];
        assert_eq!(
            display_command(&cli, &args),
            r"uv run --project '/src/my checkout' pdf2audiobook --no-progress inspect --json -- '/b/it'\''s.pdf'"
        );
    }

    #[test]
    fn locate_with_uses_the_settings_first() {
        let temp = TempDir::new().unwrap();
        let cli = write_script(
            temp.path(),
            "cli",
            &format!(
                "#!/bin/sh\ncase \"$*\" in\n  \"--version\") echo '{v}' ;;\n  \"doctor --json\") echo '{{\"version\": \"{v}\"}}' ;;\nesac\n",
                v = env!("CARGO_PKG_VERSION")
            ),
        );
        let settings = AppSettings {
            cli_path: Some(cli.clone()),
            ..AppSettings::default()
        };

        let found = locate_with(&settings, None, &TestRunner).unwrap();

        assert_eq!(found.source, CliSource::Configured);
        assert_eq!(found.command, CliCommand::direct(cli));
    }

    #[test]
    fn locate_errors_carry_their_message() {
        let error = BridgeError::from(LocateError::NotFound);
        let json = serde_json::to_value(&error).unwrap();
        assert_eq!(json["kind"], "locate");
        assert_eq!(json["error"]["kind"], "not_found");
        assert_eq!(
            json["message"],
            "The pdf2audiobook command-line tool was not found"
        );
    }

    /// A fake CLI for `config show`, `inspect` and `thumbnail`, run against `output`.
    fn fake_library_cli(folder: &Path, output: &Path, source: &Path) -> CliCommand {
        let script = format!(
            r#"#!/bin/sh
case "$*" in
  *"config show"*) printf '{{"general": {{"output_dir": "{out}"}}, "chapters": {{"min_boundary_confidence": 0.8}}, "warnings": []}}' ;;
  *"inspect"*"broken"*) printf '{{"ok": false, "error": {{"type": "ExtractionError", "code": 4, "message": "Cannot read or validate audiobook manifest"}}, "warnings": []}}' >&2; exit 4 ;;
  *"inspect"*) printf '{{"title": "Book", "source_path": "{src}", "chapters": [], "warnings": []}}' ;;
  *"workspace"*"new.pdf") printf '{{"workspace": "{out}/new-3", "exists": false, "warnings": []}}' ;;
  *"workspace"*"good.pdf") printf '{{"workspace": "{out}/good-1", "exists": true, "warnings": []}}' ;;
  *"thumbnail"*) for a in "$@"; do case "$a" in --output=*) printf 'PNG' > "${{a#--output=}}" ;; esac; done; printf '{{"thumbnail": "x", "width": 1, "height": 1, "warnings": []}}' ;;
esac
"#,
            out = output.display(),
            src = source.display()
        );
        CliCommand::direct(write_script(folder, "cli", &script))
    }

    #[test]
    fn the_library_lists_books_with_their_inspection_and_thumbnail() {
        let temp = TempDir::new().unwrap();
        let output = temp.path().join("out");
        for name in ["good-1", "broken-2"] {
            fs::create_dir_all(output.join(name)).unwrap();
            fs::write(output.join(name).join("manifest.json"), "{}").unwrap();
        }
        let source = temp.path().join("book.pdf");
        fs::write(&source, "pdf").unwrap();
        let cli = fake_library_cli(&temp.path().join("bin"), &output, &source);
        let cache = temp.path().join("cache");

        let library = build_library(&cli, &TestRunner, None, &[], &cache).unwrap();

        assert_eq!(library.output_dir, output);
        assert_eq!(library.min_boundary_confidence, 0.8);
        let [broken, good] = library.books.as_slice() else {
            panic!("two books expected")
        };
        assert_eq!(broken.inspect, None);
        assert_eq!(
            broken.error.as_deref(),
            Some("Cannot read or validate audiobook manifest")
        );
        assert_eq!(broken.thumbnail, None);
        assert_eq!(good.inspect.as_ref().unwrap()["title"], "Book");
        assert_eq!(
            good.thumbnail.as_deref(),
            Some("data:image/png;base64,UE5H")
        );
        assert!(cache.join("good-1.png").exists());
    }

    #[test]
    fn a_configured_output_folder_overrides_the_cli_setting() {
        let temp = TempDir::new().unwrap();
        let elsewhere = temp.path().join("elsewhere");
        let cli = fake_library_cli(
            &temp.path().join("bin"),
            &temp.path().join("unused"),
            Path::new("/x.pdf"),
        );

        let library = build_library(
            &cli,
            &TestRunner,
            Some(&elsewhere),
            &[],
            &temp.path().join("c"),
        )
        .unwrap();

        assert_eq!(library.output_dir, elsewhere);
        assert!(library.books.is_empty());
    }

    #[test]
    fn added_books_appear_until_they_are_analyzed() {
        let temp = TempDir::new().unwrap();
        let output = temp.path().join("out");
        fs::create_dir_all(output.join("good-1")).unwrap();
        fs::write(output.join("good-1/manifest.json"), "{}").unwrap();
        let source = temp.path().join("good.pdf");
        fs::write(&source, "pdf").unwrap();
        let fresh = temp.path().join("new.pdf");
        fs::write(&fresh, "pdf").unwrap();
        let cli = fake_library_cli(&temp.path().join("bin"), &output, &source);
        let added = [source.clone(), fresh.clone()];

        let library =
            build_library(&cli, &TestRunner, None, &added, &temp.path().join("cache")).unwrap();

        let [analyzed, pending] = library.books.as_slice() else {
            panic!("two books expected")
        };
        assert!(analyzed.analyzed);
        assert_eq!(analyzed.workspace, output.join("good-1"));
        assert!(!pending.analyzed);
        assert_eq!(pending.source.as_deref(), Some(fresh.as_path()));
        assert_eq!(pending.workspace, output.join("new-3"));
        assert_eq!(pending.inspect, None);
        assert!(pending.thumbnail.is_some());
    }
}
