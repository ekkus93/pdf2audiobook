//! Typed CLI requests and the argument vectors they become (spec D3.b).
//!
//! Every value the user can influence becomes exactly one argument. Root flags come first
//! (`--no-progress`), then the command, its options as `--name=value`, `--json`, and finally
//! `--` followed by positional paths, so a path that starts with `-` can't be read as an option.

use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

/// Why a request can't be turned into arguments. Messages never include user values.
#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error, Serialize)]
pub enum RequestError {
    #[error("{0} is out of range")]
    OutOfRange(&'static str),
    #[error("{0} must not be empty")]
    Empty(&'static str),
    #[error("{0} contains a character that can't be passed to the engine")]
    InvalidText(&'static str),
    #[error("A PDF password must be given as the name of an environment variable")]
    InvalidEnvVarName,
}

/// The name of an environment variable that holds a PDF password; never the password itself.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct EnvVarName(String);

impl EnvVarName {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl TryFrom<String> for EnvVarName {
    type Error = RequestError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        let mut chars = value.chars();
        let valid = value.len() <= 128
            && chars
                .next()
                .is_some_and(|first| first == '_' || first.is_ascii_alphabetic())
            && chars.all(|rest| rest == '_' || rest.is_ascii_alphanumeric());
        if valid {
            Ok(Self(value))
        } else {
            Err(RequestError::InvalidEnvVarName)
        }
    }
}

impl From<EnvVarName> for String {
    fn from(value: EnvVarName) -> Self {
        value.0
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum OcrMode {
    Auto,
    Always,
    Never,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum LlmProvider {
    Ollama,
    Openai,
    LlamaServer,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum TtsProvider {
    Kitten,
    Piper,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReviewReason {
    DamagedSource,
    AmbiguousPageNumbers,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EditStatus {
    Pending,
    Accepted,
    Rejected,
    All,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FootnotePolicy {
    Warn,
    Inline,
    End,
    Omit,
}

/// Which chapters to convert.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ChapterSelection {
    One { chapter: u32 },
    Range { first: u32, last: u32 },
}

/// Which edits an `edits accept` or `edits reject` applies to.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum EditSelection {
    All,
    Blocks { ids: Vec<String> },
}

/// Which chapters `regenerate-chapter` regenerates.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Regenerate {
    Chapter { chapter: u32 },
    AllConflicts,
}

/// Options shared by `analyze` and `convert`. `None` leaves the CLI's own setting in force.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct BookOptions {
    pub output: Option<PathBuf>,
    pub ocr: Option<OcrMode>,
    pub pdf_password_env: Option<EnvVarName>,
    pub llm: Option<bool>,
    pub llm_provider: Option<LlmProvider>,
    pub llm_model: Option<String>,
    pub llm_url: Option<String>,
    pub llm_context_tokens: Option<u32>,
    pub llm_output_tokens: Option<u32>,
    pub process_citations: Option<bool>,
    pub process_equations: Option<bool>,
    pub allow_remote_content: Option<bool>,
    pub vision: Option<bool>,
    pub allow_single_chapter: Option<bool>,
    pub resume: Option<bool>,
}

/// Options only `convert` takes.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ConvertOptions {
    pub tts_provider: Option<TtsProvider>,
    pub tts_model: Option<String>,
    pub voice: Option<String>,
    pub bitrate: Option<String>,
    pub chapters: Option<ChapterSelection>,
    pub dry_run: bool,
    pub speed: Option<f64>,
    pub sample_rate: Option<u32>,
    pub cover: Option<PathBuf>,
    pub accept_review: Vec<ReviewReason>,
    pub force: bool,
}

/// Every CLI command the app runs.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "command", rename_all = "snake_case")]
pub enum Request {
    Doctor,
    ConfigShow,
    Inspect {
        source: PathBuf,
        pdf_password_env: Option<EnvVarName>,
    },
    Workspace {
        book: PathBuf,
        output: Option<PathBuf>,
    },
    Voices {
        tts_provider: Option<TtsProvider>,
        tts_model: Option<String>,
    },
    Thumbnail {
        book: PathBuf,
        output: PathBuf,
        width: u32,
        pdf_password_env: Option<EnvVarName>,
    },
    Analyze {
        book: PathBuf,
        options: BookOptions,
    },
    Convert {
        book: PathBuf,
        options: BookOptions,
        convert: ConvertOptions,
    },
    Review {
        manifest: PathBuf,
        port: u16,
    },
    EditsList {
        manifest: PathBuf,
        status: EditStatus,
    },
    EditsAccept {
        manifest: PathBuf,
        which: EditSelection,
    },
    EditsReject {
        manifest: PathBuf,
        which: EditSelection,
    },
    PackM4b {
        manifest: PathBuf,
        output: PathBuf,
        bitrate: Option<String>,
        cover: Option<PathBuf>,
    },
    RegenerateChapter {
        manifest: PathBuf,
        which: Regenerate,
        footnotes: Option<FootnotePolicy>,
    },
    Recover {
        manifest: PathBuf,
        back_up_changed: bool,
    },
    BudgetShow {
        workspace: PathBuf,
    },
}

impl Request {
    /// Whether the command can change a workspace (spec D3.d).
    pub fn is_write(&self) -> bool {
        matches!(
            self,
            Request::Analyze { .. }
                | Request::Convert { .. }
                | Request::Review { .. }
                | Request::EditsAccept { .. }
                | Request::EditsReject { .. }
                | Request::PackM4b { .. }
                | Request::RegenerateChapter { .. }
                | Request::Recover { .. }
        )
    }

    /// The argument vector, after the CLI program and any fixed prefix.
    pub fn args(&self) -> Result<Vec<OsString>, RequestError> {
        let mut args = Args::default();
        match self {
            Request::Doctor => args.command(&["doctor"]),
            Request::ConfigShow => {
                args.command(&["config", "show"]);
                args.flag("--sources");
            }
            Request::Inspect {
                source,
                pdf_password_env,
            } => {
                args.command(&["inspect"]);
                args.env_name("--pdf-password-env", pdf_password_env.as_ref());
                args.positional(source, "The book")?;
            }
            Request::Workspace { book, output } => {
                args.command(&["workspace"]);
                args.path("--output", output.as_deref(), "The output folder")?;
                args.positional(book, "The book")?;
            }
            Request::Voices {
                tts_provider,
                tts_model,
            } => {
                args.command(&["voices"]);
                args.text(
                    "--tts-provider",
                    tts_provider.map(tts_name),
                    "The TTS provider",
                )?;
                args.text("--tts-model", tts_model.as_deref(), "The TTS model")?;
            }
            Request::Thumbnail {
                book,
                output,
                width,
                pdf_password_env,
            } => {
                args.command(&["thumbnail"]);
                args.path("--output", Some(output), "The thumbnail file")?;
                args.number("--width", Some(*width), 16, 2048, "The thumbnail width")?;
                args.env_name("--pdf-password-env", pdf_password_env.as_ref());
                args.positional(book, "The book")?;
            }
            Request::Analyze { book, options } => {
                args.command(&["analyze"]);
                book_options(&mut args, options)?;
                args.positional(book, "The book")?;
            }
            Request::Convert {
                book,
                options,
                convert,
            } => {
                args.command(&["convert"]);
                book_options(&mut args, options)?;
                convert_options(&mut args, convert)?;
                args.positional(book, "The book")?;
            }
            Request::Review { manifest, port } => {
                args.command(&["review"]);
                args.value("--port", port.to_string());
                args.positional(manifest, "The manifest")?;
            }
            Request::EditsList { manifest, status } => {
                args.command(&["edits", "list"]);
                args.value("--status", edit_status_name(*status));
                args.positional(manifest, "The manifest")?;
            }
            Request::EditsAccept { manifest, which } | Request::EditsReject { manifest, which } => {
                let verb = if matches!(self, Request::EditsAccept { .. }) {
                    "accept"
                } else {
                    "reject"
                };
                args.command(&["edits", verb]);
                if matches!(which, EditSelection::All) {
                    args.flag("--all");
                }
                args.positional(manifest, "The manifest")?;
                if let EditSelection::Blocks { ids } = which {
                    if ids.is_empty() {
                        return Err(RequestError::Empty("The edit list"));
                    }
                    for id in ids {
                        args.positional_text(id, "An edit ID")?;
                    }
                }
            }
            Request::PackM4b {
                manifest,
                output,
                bitrate,
                cover,
            } => {
                args.command(&["pack-m4b"]);
                args.path("--output", Some(output), "The M4B file")?;
                args.text("--bitrate", bitrate.as_deref(), "The bitrate")?;
                args.path("--cover", cover.as_deref(), "The cover image")?;
                args.positional(manifest, "The manifest")?;
            }
            Request::RegenerateChapter {
                manifest,
                which,
                footnotes,
            } => {
                args.command(&["regenerate-chapter"]);
                match which {
                    Regenerate::Chapter { chapter } => {
                        args.number("--chapter", Some(*chapter), 1, u32::MAX, "The chapter")?
                    }
                    Regenerate::AllConflicts => args.flag("--all-conflicts"),
                }
                args.text(
                    "--footnotes",
                    footnotes.map(footnote_name),
                    "The footnote policy",
                )?;
                args.positional(manifest, "The manifest")?;
            }
            Request::Recover {
                manifest,
                back_up_changed,
            } => {
                args.command(&["recover"]);
                if *back_up_changed {
                    args.flag("--back-up-changed");
                }
                args.positional(manifest, "The manifest")?;
            }
            Request::BudgetShow { workspace } => {
                args.command(&["budget", "show"]);
                args.path("--output", Some(workspace), "The workspace")?;
            }
        }
        Ok(args.finish())
    }
}

fn book_options(args: &mut Args, options: &BookOptions) -> Result<(), RequestError> {
    args.path("--output", options.output.as_deref(), "The output folder")?;
    args.text("--ocr", options.ocr.map(ocr_name), "The OCR mode")?;
    args.env_name("--pdf-password-env", options.pdf_password_env.as_ref());
    args.switch("llm", options.llm);
    args.text(
        "--llm-provider",
        options.llm_provider.map(llm_name),
        "The LLM provider",
    )?;
    args.text("--llm-model", options.llm_model.as_deref(), "The LLM model")?;
    args.text("--llm-url", options.llm_url.as_deref(), "The LLM address")?;
    args.number(
        "--llm-context-tokens",
        options.llm_context_tokens,
        512,
        u32::MAX,
        "The context size",
    )?;
    args.number(
        "--llm-output-tokens",
        options.llm_output_tokens,
        1,
        u32::MAX,
        "The output cap",
    )?;
    args.switch("process-citations", options.process_citations);
    args.switch("process-equations", options.process_equations);
    args.switch("allow-remote-content", options.allow_remote_content);
    args.switch("vision", options.vision);
    args.switch("allow-single-chapter", options.allow_single_chapter);
    args.switch("resume", options.resume);
    Ok(())
}

fn convert_options(args: &mut Args, convert: &ConvertOptions) -> Result<(), RequestError> {
    args.text(
        "--tts-provider",
        convert.tts_provider.map(tts_name),
        "The TTS provider",
    )?;
    args.text("--tts-model", convert.tts_model.as_deref(), "The TTS model")?;
    args.text("--voice", convert.voice.as_deref(), "The voice")?;
    args.text("--bitrate", convert.bitrate.as_deref(), "The bitrate")?;
    match convert.chapters {
        Some(ChapterSelection::One { chapter }) => {
            args.number("--chapter", Some(chapter), 1, u32::MAX, "The chapter")?
        }
        Some(ChapterSelection::Range { first, last }) => {
            if first < 1 || last < first {
                return Err(RequestError::OutOfRange("The chapter range"));
            }
            args.value("--chapter-range", format!("{first}:{last}"));
        }
        None => {}
    }
    if convert.dry_run {
        args.flag("--dry-run");
    }
    if let Some(speed) = convert.speed {
        if !speed.is_finite() || !(0.1..=3.0).contains(&speed) {
            return Err(RequestError::OutOfRange("The speed"));
        }
        args.value("--speed", speed.to_string());
    }
    args.number(
        "--sample-rate",
        convert.sample_rate,
        8000,
        96000,
        "The sample rate",
    )?;
    args.path("--cover", convert.cover.as_deref(), "The cover image")?;
    for reason in &convert.accept_review {
        args.value("--accept-review", review_reason_name(*reason));
    }
    if convert.force {
        args.flag("--force");
    }
    Ok(())
}

fn ocr_name(value: OcrMode) -> &'static str {
    match value {
        OcrMode::Auto => "auto",
        OcrMode::Always => "always",
        OcrMode::Never => "never",
    }
}

fn llm_name(value: LlmProvider) -> &'static str {
    match value {
        LlmProvider::Ollama => "ollama",
        LlmProvider::Openai => "openai",
        LlmProvider::LlamaServer => "llama-server",
    }
}

fn tts_name(value: TtsProvider) -> &'static str {
    match value {
        TtsProvider::Kitten => "kitten",
        TtsProvider::Piper => "piper",
    }
}

fn review_reason_name(value: ReviewReason) -> &'static str {
    match value {
        ReviewReason::DamagedSource => "damaged_source",
        ReviewReason::AmbiguousPageNumbers => "ambiguous_page_numbers",
    }
}

fn edit_status_name(value: EditStatus) -> &'static str {
    match value {
        EditStatus::Pending => "pending",
        EditStatus::Accepted => "accepted",
        EditStatus::Rejected => "rejected",
        EditStatus::All => "all",
    }
}

fn footnote_name(value: FootnotePolicy) -> &'static str {
    match value {
        FootnotePolicy::Warn => "warn",
        FootnotePolicy::Inline => "inline",
        FootnotePolicy::End => "end",
        FootnotePolicy::Omit => "omit",
    }
}

/// Builds `--no-progress COMMAND [--name=value ...] --json -- [POSITIONAL ...]`.
#[derive(Default)]
struct Args {
    command: Vec<OsString>,
    options: Vec<OsString>,
    positionals: Vec<OsString>,
}

impl Args {
    fn command(&mut self, words: &[&str]) {
        self.command = words.iter().map(OsString::from).collect();
    }

    fn flag(&mut self, name: &str) {
        self.options.push(OsString::from(name));
    }

    /// `--name` or `--no-name` for a paired boolean option; nothing when unset.
    fn switch(&mut self, name: &str, value: Option<bool>) {
        match value {
            Some(true) => self.flag(&format!("--{name}")),
            Some(false) => self.flag(&format!("--no-{name}")),
            None => {}
        }
    }

    fn value(&mut self, name: &str, value: impl AsRef<OsStr>) {
        let mut joined = OsString::from(name);
        joined.push("=");
        joined.push(value);
        self.options.push(joined);
    }

    fn text(
        &mut self,
        name: &str,
        value: Option<&str>,
        label: &'static str,
    ) -> Result<(), RequestError> {
        if let Some(value) = value {
            check_text(value, label)?;
            self.value(name, value);
        }
        Ok(())
    }

    fn path(
        &mut self,
        name: &str,
        value: Option<&Path>,
        label: &'static str,
    ) -> Result<(), RequestError> {
        if let Some(path) = value {
            check_path(path, label)?;
            self.value(name, path.as_os_str());
        }
        Ok(())
    }

    fn number(
        &mut self,
        name: &str,
        value: Option<u32>,
        min: u32,
        max: u32,
        label: &'static str,
    ) -> Result<(), RequestError> {
        if let Some(value) = value {
            if !(min..=max).contains(&value) {
                return Err(RequestError::OutOfRange(label));
            }
            self.value(name, value.to_string());
        }
        Ok(())
    }

    fn env_name(&mut self, name: &str, value: Option<&EnvVarName>) {
        if let Some(variable) = value {
            self.value(name, variable.as_str());
        }
    }

    fn positional(&mut self, path: &Path, label: &'static str) -> Result<(), RequestError> {
        check_path(path, label)?;
        self.positionals.push(path.as_os_str().to_owned());
        Ok(())
    }

    fn positional_text(&mut self, text: &str, label: &'static str) -> Result<(), RequestError> {
        check_text(text, label)?;
        self.positionals.push(OsString::from(text));
        Ok(())
    }

    fn finish(self) -> Vec<OsString> {
        let mut args = vec![OsString::from("--no-progress")];
        args.extend(self.command);
        args.extend(self.options);
        args.push(OsString::from("--json"));
        if !self.positionals.is_empty() {
            args.push(OsString::from("--"));
            args.extend(self.positionals);
        }
        args
    }
}

fn check_text(value: &str, label: &'static str) -> Result<(), RequestError> {
    if value.trim().is_empty() {
        Err(RequestError::Empty(label))
    } else if value.contains('\0') {
        Err(RequestError::InvalidText(label))
    } else {
        Ok(())
    }
}

fn check_path(path: &Path, label: &'static str) -> Result<(), RequestError> {
    if path.as_os_str().is_empty() {
        Err(RequestError::Empty(label))
    } else if path.as_os_str().as_encoded_bytes().contains(&0) {
        Err(RequestError::InvalidText(label))
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::process::{CliCommand, Runner};
    use crate::engine::testing::{TestRunner, write_script};
    use tempfile::TempDir;

    fn strings(args: Vec<OsString>) -> Vec<String> {
        args.into_iter()
            .map(|arg| arg.into_string().unwrap())
            .collect()
    }

    fn args_of(request: Request) -> Vec<String> {
        strings(request.args().unwrap())
    }

    fn env(name: &str) -> EnvVarName {
        EnvVarName::try_from(name.to_owned()).unwrap()
    }

    #[test]
    fn doctor() {
        assert_eq!(
            args_of(Request::Doctor),
            ["--no-progress", "doctor", "--json"]
        );
    }

    #[test]
    fn config_show() {
        assert_eq!(
            args_of(Request::ConfigShow),
            ["--no-progress", "config", "show", "--sources", "--json"]
        );
    }

    #[test]
    fn inspect() {
        let request = Request::Inspect {
            source: "/books/a.pdf".into(),
            pdf_password_env: Some(env("BOOK_PW")),
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "inspect",
                "--pdf-password-env=BOOK_PW",
                "--json",
                "--",
                "/books/a.pdf"
            ]
        );
    }

    #[test]
    fn workspace() {
        let request = Request::Workspace {
            book: "/books/a.pdf".into(),
            output: Some("/out".into()),
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "workspace",
                "--output=/out",
                "--json",
                "--",
                "/books/a.pdf"
            ]
        );
    }

    #[test]
    fn voices() {
        let request = Request::Voices {
            tts_provider: Some(TtsProvider::Kitten),
            tts_model: Some("nano".into()),
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "voices",
                "--tts-provider=kitten",
                "--tts-model=nano",
                "--json"
            ]
        );
        let default = Request::Voices {
            tts_provider: None,
            tts_model: None,
        };
        assert_eq!(args_of(default), ["--no-progress", "voices", "--json"]);
    }

    #[test]
    fn thumbnail() {
        let request = Request::Thumbnail {
            book: "/books/a.epub".into(),
            output: "/cache/a.png".into(),
            width: 320,
            pdf_password_env: None,
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "thumbnail",
                "--output=/cache/a.png",
                "--width=320",
                "--json",
                "--",
                "/books/a.epub"
            ]
        );
    }

    #[test]
    fn analyze_with_every_option() {
        let options = BookOptions {
            output: Some("/out".into()),
            ocr: Some(OcrMode::Never),
            pdf_password_env: Some(env("PW")),
            llm: Some(true),
            llm_provider: Some(LlmProvider::LlamaServer),
            llm_model: Some("qwen35-256k:latest".into()),
            llm_url: Some("http://127.0.0.1:8080/v1".into()),
            llm_context_tokens: Some(262_144),
            llm_output_tokens: Some(32_768),
            process_citations: Some(false),
            process_equations: Some(true),
            allow_remote_content: Some(false),
            vision: Some(false),
            allow_single_chapter: Some(true),
            resume: Some(false),
        };
        let request = Request::Analyze {
            book: "/books/a.pdf".into(),
            options,
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "analyze",
                "--output=/out",
                "--ocr=never",
                "--pdf-password-env=PW",
                "--llm",
                "--llm-provider=llama-server",
                "--llm-model=qwen35-256k:latest",
                "--llm-url=http://127.0.0.1:8080/v1",
                "--llm-context-tokens=262144",
                "--llm-output-tokens=32768",
                "--no-process-citations",
                "--process-equations",
                "--no-allow-remote-content",
                "--no-vision",
                "--allow-single-chapter",
                "--no-resume",
                "--json",
                "--",
                "/books/a.pdf"
            ]
        );
    }

    #[test]
    fn analyze_with_defaults_passes_no_options() {
        let request = Request::Analyze {
            book: "/books/a.pdf".into(),
            options: BookOptions::default(),
        };
        assert_eq!(
            args_of(request),
            ["--no-progress", "analyze", "--json", "--", "/books/a.pdf"]
        );
    }

    #[test]
    fn convert_with_every_option() {
        let convert = ConvertOptions {
            tts_provider: Some(TtsProvider::Kitten),
            tts_model: Some("mini".into()),
            voice: Some("Luna".into()),
            bitrate: Some("96k".into()),
            chapters: Some(ChapterSelection::Range { first: 2, last: 5 }),
            dry_run: true,
            speed: Some(1.15),
            sample_rate: Some(24000),
            cover: Some("/art/cover.jpg".into()),
            accept_review: vec![
                ReviewReason::DamagedSource,
                ReviewReason::AmbiguousPageNumbers,
            ],
            force: true,
        };
        let request = Request::Convert {
            book: "/books/a.pdf".into(),
            options: BookOptions {
                llm: Some(false),
                ..BookOptions::default()
            },
            convert,
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "convert",
                "--no-llm",
                "--tts-provider=kitten",
                "--tts-model=mini",
                "--voice=Luna",
                "--bitrate=96k",
                "--chapter-range=2:5",
                "--dry-run",
                "--speed=1.15",
                "--sample-rate=24000",
                "--cover=/art/cover.jpg",
                "--accept-review=damaged_source",
                "--accept-review=ambiguous_page_numbers",
                "--force",
                "--json",
                "--",
                "/books/a.pdf"
            ]
        );
    }

    #[test]
    fn convert_one_chapter() {
        let request = Request::Convert {
            book: "/books/a.pdf".into(),
            options: BookOptions::default(),
            convert: ConvertOptions {
                chapters: Some(ChapterSelection::One { chapter: 3 }),
                ..ConvertOptions::default()
            },
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "convert",
                "--chapter=3",
                "--json",
                "--",
                "/books/a.pdf"
            ]
        );
    }

    #[test]
    fn review() {
        let request = Request::Review {
            manifest: "/w/manifest.json".into(),
            port: 0,
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "review",
                "--port=0",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
    }

    #[test]
    fn edits_list() {
        let request = Request::EditsList {
            manifest: "/w/manifest.json".into(),
            status: EditStatus::All,
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "edits",
                "list",
                "--status=all",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
    }

    #[test]
    fn edits_accept_all() {
        let request = Request::EditsAccept {
            manifest: "/w/manifest.json".into(),
            which: EditSelection::All,
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "edits",
                "accept",
                "--all",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
    }

    #[test]
    fn edits_reject_some() {
        let request = Request::EditsReject {
            manifest: "/w/manifest.json".into(),
            which: EditSelection::Blocks {
                ids: vec!["p00003-l00012".into(), "-p9".into()],
            },
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "edits",
                "reject",
                "--json",
                "--",
                "/w/manifest.json",
                "p00003-l00012",
                "-p9"
            ]
        );
    }

    #[test]
    fn pack_m4b() {
        let request = Request::PackM4b {
            manifest: "/w/manifest.json".into(),
            output: "/out/book.m4b".into(),
            bitrate: Some("64k".into()),
            cover: Some("/art/c.png".into()),
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "pack-m4b",
                "--output=/out/book.m4b",
                "--bitrate=64k",
                "--cover=/art/c.png",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
    }

    #[test]
    fn regenerate_chapter() {
        let one = Request::RegenerateChapter {
            manifest: "/w/manifest.json".into(),
            which: Regenerate::Chapter { chapter: 3 },
            footnotes: Some(FootnotePolicy::End),
        };
        assert_eq!(
            args_of(one),
            [
                "--no-progress",
                "regenerate-chapter",
                "--chapter=3",
                "--footnotes=end",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
        let conflicts = Request::RegenerateChapter {
            manifest: "/w/manifest.json".into(),
            which: Regenerate::AllConflicts,
            footnotes: None,
        };
        assert_eq!(
            args_of(conflicts),
            [
                "--no-progress",
                "regenerate-chapter",
                "--all-conflicts",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
    }

    #[test]
    fn recover() {
        let request = Request::Recover {
            manifest: "/w/manifest.json".into(),
            back_up_changed: true,
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "recover",
                "--back-up-changed",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
    }

    #[test]
    fn budget_show() {
        let request = Request::BudgetShow {
            workspace: "/w".into(),
        };
        assert_eq!(
            args_of(request),
            ["--no-progress", "budget", "show", "--output=/w", "--json"]
        );
    }

    #[test]
    fn json_and_no_progress_are_always_present() {
        let requests = [
            Request::Doctor,
            Request::BudgetShow {
                workspace: "/w".into(),
            },
            Request::Recover {
                manifest: "/m.json".into(),
                back_up_changed: false,
            },
        ];
        for request in requests {
            let args = args_of(request);
            assert_eq!(args[0], "--no-progress");
            assert_eq!(args.iter().filter(|arg| *arg == "--json").count(), 1);
        }
    }

    #[test]
    fn write_capable_commands_are_marked() {
        let manifest = PathBuf::from("/w/manifest.json");
        assert!(!Request::Doctor.is_write());
        assert!(
            !Request::EditsList {
                manifest: manifest.clone(),
                status: EditStatus::Pending
            }
            .is_write()
        );
        assert!(
            Request::Recover {
                manifest: manifest.clone(),
                back_up_changed: false
            }
            .is_write()
        );
        assert!(Request::Review { manifest, port: 0 }.is_write());
    }

    #[test]
    fn invalid_values_are_refused_without_echoing_them() {
        let bad = [
            (
                Request::Convert {
                    book: "/b.pdf".into(),
                    options: BookOptions::default(),
                    convert: ConvertOptions {
                        speed: Some(f64::NAN),
                        ..ConvertOptions::default()
                    },
                },
                RequestError::OutOfRange("The speed"),
            ),
            (
                Request::Convert {
                    book: "/b.pdf".into(),
                    options: BookOptions::default(),
                    convert: ConvertOptions {
                        chapters: Some(ChapterSelection::Range { first: 5, last: 2 }),
                        ..ConvertOptions::default()
                    },
                },
                RequestError::OutOfRange("The chapter range"),
            ),
            (
                Request::Thumbnail {
                    book: "/b.pdf".into(),
                    output: "/t.png".into(),
                    width: 9000,
                    pdf_password_env: None,
                },
                RequestError::OutOfRange("The thumbnail width"),
            ),
            (
                Request::Analyze {
                    book: "/b.pdf".into(),
                    options: BookOptions {
                        llm_model: Some("  ".into()),
                        ..BookOptions::default()
                    },
                },
                RequestError::Empty("The LLM model"),
            ),
            (
                Request::Voices {
                    tts_provider: None,
                    tts_model: Some("a\0b".into()),
                },
                RequestError::InvalidText("The TTS model"),
            ),
            (
                Request::EditsAccept {
                    manifest: "/m.json".into(),
                    which: EditSelection::Blocks { ids: vec![] },
                },
                RequestError::Empty("The edit list"),
            ),
            (
                Request::Workspace {
                    book: "".into(),
                    output: None,
                },
                RequestError::Empty("The book"),
            ),
        ];
        for (request, expected) in bad {
            assert_eq!(request.args(), Err(expected));
        }
    }

    #[test]
    fn requests_deserialize_from_the_frontend_shape() {
        let json = r#"{"command": "convert", "book": "/b.pdf",
            "options": {"llm": false},
            "convert": {"voice": "Leo", "chapters": {"kind": "one", "chapter": 2}}}"#;
        let request: Request = serde_json::from_str(json).unwrap();
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "convert",
                "--no-llm",
                "--voice=Leo",
                "--chapter=2",
                "--json",
                "--",
                "/b.pdf"
            ]
        );
    }

    #[test]
    fn an_awkward_book_path_stays_one_argument() {
        let path = "/books/-x my \"quoted\" 'book'; rm -rf $HOME.pdf";
        let request = Request::Workspace {
            book: path.into(),
            output: None,
        };

        let args = args_of(request.clone());

        assert_eq!(args.last().map(String::as_str), Some(path));
        assert_eq!(args[args.len() - 2], "--");

        // A real child process receives it unchanged, as one argument after `--`.
        let temp = TempDir::new().unwrap();
        let cli = write_script(
            temp.path(),
            "argcount",
            "#!/bin/sh\necho \"$#\"\nfor arg in \"$@\"; do last=\"$arg\"; done\nprintf '%s' \"$last\"\n",
        );
        let done = TestRunner
            .run(&CliCommand::direct(cli), &request.args().unwrap())
            .unwrap();
        let (count, last) = done.stdout.split_once('\n').unwrap();
        assert_eq!(count, args.len().to_string());
        assert_eq!(last, path);
    }
}

/// Runs read-only requests against the real CLI from this checkout. Opt-in, because it needs
/// Python and uv: `cargo test -- --ignored real_cli`.
#[cfg(test)]
mod real_cli {
    use super::*;
    use crate::engine::process::{CliCommand, Runner, SystemRunner};
    use std::path::Path;

    fn checkout() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap()
    }

    #[test]
    #[ignore = "needs uv and the Python CLI"]
    fn real_cli_accepts_the_read_only_requests() {
        let root = checkout();
        let cli = CliCommand {
            program: "uv".into(),
            prefix: vec![
                "run".into(),
                "--project".into(),
                root.clone().into_os_string(),
                "pdf2audiobook".into(),
            ],
        };
        let book = root.join("tests/fixtures/outlined_text.pdf");
        let temp = tempfile::TempDir::new().unwrap();
        let requests = [
            Request::Doctor,
            Request::ConfigShow,
            Request::Inspect {
                source: book.clone(),
                pdf_password_env: None,
            },
            Request::Workspace {
                book: book.clone(),
                output: Some(temp.path().into()),
            },
            Request::Thumbnail {
                book,
                output: temp.path().join("t.png"),
                width: 64,
                pdf_password_env: None,
            },
        ];
        for request in requests {
            let done = SystemRunner.run(&cli, &request.args().unwrap()).unwrap();
            assert_eq!(done.code, Some(0), "{request:?}: {}", done.stderr);
            let payload: serde_json::Value = serde_json::from_str(&done.stdout).unwrap();
            assert!(payload.is_object(), "{request:?}");
        }
    }
}
