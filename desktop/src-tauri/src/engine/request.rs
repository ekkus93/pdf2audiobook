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

/// A speech recognizer that audio verification can use.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AsrModel {
    Whisper,
    Wav2vec2,
    Vosk,
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

/// Local reference selection. Typed drafts are materialized by the bridge, never argv.
#[derive(Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct CloneOptions {
    pub clone_voice: Option<bool>,
    pub reference_audio: Option<PathBuf>,
    pub reference_text_file: Option<PathBuf>,
    pub reference_text: Option<String>,
}

impl std::fmt::Debug for CloneOptions {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("CloneOptions")
            .field("clone_voice", &self.clone_voice)
            .finish_non_exhaustive()
    }
}

/// Options only `convert` takes.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ConvertOptions {
    #[serde(flatten)]
    pub voice_clone: CloneOptions,
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
    /// Check the converted chapters with the speech recognizers afterwards (opt-in).
    pub verify_audio: bool,
}

/// Every CLI command the app runs.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "command", rename_all = "snake_case")]
pub enum Request {
    Doctor {
        #[serde(default)]
        check_llm: bool,
    },
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
        /// Include each edit's original and proposed text (`--with-text`).
        #[serde(default)]
        with_text: bool,
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
    /// Which speech recognizers are installed and downloaded; loads none of them.
    AsrList,
    TtsModels,
    TtsFetch,
    /// Downloads the pinned weights; the app has already shown what is fetched and asked.
    AsrFetch {
        models: Vec<AsrModel>,
    },
    /// Listens to chapter MP3s; no chapters means all of them, no models means every model.
    VerifyAudio {
        manifest: PathBuf,
        #[serde(default)]
        chapters: Vec<u32>,
        #[serde(default)]
        models: Vec<AsrModel>,
    },
    /// The saved verification report and which results are stale; loads no model.
    AudioReport {
        manifest: PathBuf,
    },
    /// Marks one flagged passage reviewed (or not); changes no audio or text.
    AudioDismiss {
        manifest: PathBuf,
        chapter: u32,
        flag: u32,
        #[serde(default)]
        undo: bool,
    },
    /// Speaks chosen chapters again, keeping the previous audio as a backup.
    Resynthesize {
        #[serde(flatten)]
        voice_clone: CloneOptions,
        tts_provider: Option<TtsProvider>,
        tts_model: Option<String>,
        manifest: PathBuf,
        chapters: Vec<u32>,
        voice: Option<String>,
        speed: Option<f64>,
        /// `None` re-verifies only chapters verified before.
        verify_audio: Option<bool>,
    },
}

impl Request {
    /// The CLI command, as the app's log names it: a fixed word, never a path or value.
    pub fn name(&self) -> &'static str {
        match self {
            Request::Doctor { .. } => "doctor",
            Request::ConfigShow => "config show",
            Request::Inspect { .. } => "inspect",
            Request::Workspace { .. } => "workspace",
            Request::Voices { .. } => "voices",
            Request::Thumbnail { .. } => "thumbnail",
            Request::Analyze { .. } => "analyze",
            Request::Convert { .. } => "convert",
            Request::Review { .. } => "review",
            Request::EditsList { .. } => "edits list",
            Request::EditsAccept { .. } => "edits accept",
            Request::EditsReject { .. } => "edits reject",
            Request::PackM4b { .. } => "pack-m4b",
            Request::RegenerateChapter { .. } => "regenerate-chapter",
            Request::Recover { .. } => "recover",
            Request::BudgetShow { .. } => "budget show",
            Request::AsrList => "asr list",
            Request::TtsModels => "tts models",
            Request::TtsFetch => "tts fetch",
            Request::AsrFetch { .. } => "asr fetch",
            Request::VerifyAudio { .. } => "verify-audio",
            Request::AudioReport { .. } => "audio-report show",
            Request::AudioDismiss { .. } => "audio-report dismiss",
            Request::Resynthesize { .. } => "resynthesize",
        }
    }

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
                // Holds the book's lock and writes its report; changes no audio or text.
                | Request::VerifyAudio { .. }
                | Request::AudioDismiss { .. }
                | Request::Resynthesize { .. }
        )
    }

    /// The argument vector, after the CLI program and any fixed prefix.
    pub fn args(&self) -> Result<Vec<OsString>, RequestError> {
        let mut args = Args::default();
        match self {
            Request::Doctor { check_llm } => {
                args.command(&["doctor"]);
                if *check_llm {
                    args.flag("--check-llm");
                }
            }
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
            Request::EditsList {
                manifest,
                status,
                with_text,
            } => {
                args.command(&["edits", "list"]);
                args.value("--status", edit_status_name(*status));
                if *with_text {
                    args.flag("--with-text");
                }
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
            Request::AsrList => args.command(&["asr", "list"]),
            Request::TtsModels => args.command(&["tts", "models"]),
            Request::TtsFetch => {
                args.command(&["tts", "fetch"]);
                args.flag("--yes");
                args.positional_text("kitten2", "The model")?;
            }
            Request::AsrFetch { models } => {
                args.command(&["asr", "fetch"]);
                args.flag("--yes");
                if models.is_empty() {
                    return Err(RequestError::Empty("The model list"));
                }
                for model in models {
                    args.positional_text(asr_name(*model), "A model")?;
                }
            }
            Request::VerifyAudio {
                manifest,
                chapters,
                models,
            } => {
                args.command(&["verify-audio"]);
                chapter_list(&mut args, chapters)?;
                if !models.is_empty() {
                    let names: Vec<&str> = models.iter().map(|m| asr_name(*m)).collect();
                    args.value("--models", names.join(","));
                }
                args.positional(manifest, "The manifest")?;
            }
            Request::AudioReport { manifest } => {
                args.command(&["audio-report", "show"]);
                args.positional(manifest, "The manifest")?;
            }
            Request::AudioDismiss {
                manifest,
                chapter,
                flag,
                undo,
            } => {
                args.command(&["audio-report", "dismiss"]);
                args.number("--chapter", Some(*chapter), 1, u32::MAX, "The chapter")?;
                args.number("--flag", Some(*flag), 0, u32::MAX, "The flag")?;
                if *undo {
                    args.flag("--undo");
                }
                args.positional(manifest, "The manifest")?;
            }
            Request::Resynthesize {
                voice_clone,
                tts_provider,
                tts_model,
                manifest,
                chapters,
                voice,
                speed,
                verify_audio,
            } => {
                args.command(&["resynthesize"]);
                clone_options(&mut args, voice_clone)?;
                args.text(
                    "--tts-provider",
                    tts_provider.map(tts_name),
                    "The TTS provider",
                )?;
                args.text("--tts-model", tts_model.as_deref(), "The TTS model")?;
                if chapters.is_empty() {
                    return Err(RequestError::Empty("The chapter list"));
                }
                chapter_list(&mut args, chapters)?;
                args.text("--voice", voice.as_deref(), "The voice")?;
                speed_option(&mut args, *speed)?;
                args.switch("verify-audio", *verify_audio);
                args.positional(manifest, "The manifest")?;
            }
        }
        Ok(args.finish())
    }
}

fn clone_options(args: &mut Args, options: &CloneOptions) -> Result<(), RequestError> {
    if options.clone_voice == Some(true)
        && options
            .reference_audio
            .as_ref()
            .is_some_and(|p| p.as_os_str().is_empty())
    {
        return Err(RequestError::Empty("The reference recording"));
    }
    args.switch("clone-voice", options.clone_voice);
    args.path(
        "--reference-audio",
        options.reference_audio.as_deref(),
        "The reference recording",
    )?;
    args.path(
        "--reference-text-file",
        options.reference_text_file.as_deref(),
        "The reference transcript",
    )?;
    if let Some(text) = &options.reference_text {
        if text.trim().is_empty()
            || text.len() > 65536
            || text.contains('\0')
            || options.reference_text_file.is_some()
        {
            return Err(RequestError::InvalidText("The reference transcript"));
        }
        // Display-only placeholder. Execution first replaces drafts with a private file.
        args.value("--reference-text-file", "[private transcript]");
    }
    Ok(())
}

impl Request {
    pub fn prepare_transcript(
        &mut self,
    ) -> Result<Option<crate::voice::PrivateTranscript>, RequestError> {
        let options = match self {
            Self::Convert { convert, .. } => &mut convert.voice_clone,
            Self::Resynthesize { voice_clone, .. } => voice_clone,
            _ => return Ok(None),
        };
        let Some(text) = options.reference_text.take() else {
            return Ok(None);
        };
        if options.reference_text_file.is_some() {
            return Err(RequestError::InvalidText("The reference transcript"));
        }
        let file = crate::voice::PrivateTranscript::create(&text)
            .map_err(|_| RequestError::InvalidText("The reference transcript"))?;
        options.reference_text_file = Some(file.path().to_path_buf());
        Ok(Some(file))
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
    clone_options(args, &convert.voice_clone)?;
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
    speed_option(args, convert.speed)?;
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
    if convert.verify_audio {
        if convert.dry_run {
            return Err(RequestError::OutOfRange("Verifying a dry run"));
        }
        args.flag("--verify-audio");
    }
    Ok(())
}

fn speed_option(args: &mut Args, speed: Option<f64>) -> Result<(), RequestError> {
    if let Some(speed) = speed {
        if !speed.is_finite() || !(0.1..=3.0).contains(&speed) {
            return Err(RequestError::OutOfRange("The speed"));
        }
        args.value("--speed", speed.to_string());
    }
    Ok(())
}

fn chapter_list(args: &mut Args, chapters: &[u32]) -> Result<(), RequestError> {
    for chapter in chapters {
        args.number("--chapter", Some(*chapter), 1, u32::MAX, "The chapter")?;
    }
    Ok(())
}

fn asr_name(value: AsrModel) -> &'static str {
    match value {
        AsrModel::Whisper => "whisper",
        AsrModel::Wav2vec2 => "wav2vec2",
        AsrModel::Vosk => "vosk",
    }
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
    fn doctor_with_the_llm_check() {
        assert_eq!(
            args_of(Request::Doctor { check_llm: true }),
            ["--no-progress", "doctor", "--check-llm", "--json"]
        );
        let request: Request = serde_json::from_str(r#"{"command": "doctor"}"#).unwrap();
        assert_eq!(request, Request::Doctor { check_llm: false });
    }

    #[test]
    fn doctor() {
        assert_eq!(
            args_of(Request::Doctor { check_llm: false }),
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
            voice_clone: CloneOptions::default(),
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
            verify_audio: false,
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
            with_text: true,
        };
        assert_eq!(
            args_of(request),
            [
                "--no-progress",
                "edits",
                "list",
                "--status=all",
                "--with-text",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
        let request: Request = serde_json::from_str(
            r#"{"command": "edits_list", "manifest": "/m.json", "status": "pending"}"#,
        )
        .unwrap();
        assert!(!args_of(request).contains(&"--with-text".to_string()));
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
    fn audio_verification_requests() {
        let manifest = PathBuf::from("/w/manifest.json");
        assert_eq!(
            args_of(Request::AsrList),
            ["--no-progress", "asr", "list", "--json"]
        );
        assert_eq!(
            args_of(Request::AsrFetch {
                models: vec![AsrModel::Whisper, AsrModel::Vosk]
            }),
            [
                "--no-progress",
                "asr",
                "fetch",
                "--yes",
                "--json",
                "--",
                "whisper",
                "vosk"
            ]
        );
        assert_eq!(
            args_of(Request::VerifyAudio {
                manifest: manifest.clone(),
                chapters: vec![2, 5],
                models: vec![AsrModel::Wav2vec2, AsrModel::Vosk],
            }),
            [
                "--no-progress",
                "verify-audio",
                "--chapter=2",
                "--chapter=5",
                "--models=wav2vec2,vosk",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
        assert_eq!(
            args_of(Request::VerifyAudio {
                manifest: manifest.clone(),
                chapters: vec![],
                models: vec![],
            }),
            [
                "--no-progress",
                "verify-audio",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
        assert_eq!(
            args_of(Request::AudioReport {
                manifest: manifest.clone()
            }),
            [
                "--no-progress",
                "audio-report",
                "show",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
        assert_eq!(
            args_of(Request::AudioDismiss {
                manifest: manifest.clone(),
                chapter: 3,
                flag: 0,
                undo: true,
            }),
            [
                "--no-progress",
                "audio-report",
                "dismiss",
                "--chapter=3",
                "--flag=0",
                "--undo",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
        assert_eq!(
            args_of(Request::Resynthesize {
                voice_clone: CloneOptions::default(),
                tts_provider: None,
                tts_model: None,
                manifest,
                chapters: vec![3],
                voice: Some("Luna".into()),
                speed: Some(0.95),
                verify_audio: Some(false),
            }),
            [
                "--no-progress",
                "resynthesize",
                "--chapter=3",
                "--voice=Luna",
                "--speed=0.95",
                "--no-verify-audio",
                "--json",
                "--",
                "/w/manifest.json"
            ]
        );
    }

    #[test]
    fn conversion_verifies_audio_only_when_asked() {
        let convert = |verify_audio, dry_run| Request::Convert {
            book: "/books/a.pdf".into(),
            options: BookOptions::default(),
            convert: ConvertOptions {
                verify_audio,
                dry_run,
                ..ConvertOptions::default()
            },
        };
        assert!(!args_of(convert(false, false)).contains(&"--verify-audio".to_owned()));
        assert!(args_of(convert(true, false)).contains(&"--verify-audio".to_owned()));
        assert_eq!(
            convert(true, true).args(),
            Err(RequestError::OutOfRange("Verifying a dry run"))
        );
        let default: ConvertOptions = serde_json::from_str("{}").unwrap();
        assert!(!default.verify_audio);
    }

    #[test]
    fn audio_requests_refuse_empty_or_bad_values() {
        let manifest = PathBuf::from("/w/manifest.json");
        assert_eq!(
            Request::AsrFetch { models: vec![] }.args(),
            Err(RequestError::Empty("The model list"))
        );
        let resynthesize = |chapters: Vec<u32>, speed| Request::Resynthesize {
            voice_clone: CloneOptions::default(),
            tts_provider: None,
            tts_model: None,
            manifest: manifest.clone(),
            chapters,
            voice: None,
            speed,
            verify_audio: None,
        };
        assert_eq!(
            resynthesize(vec![], None).args(),
            Err(RequestError::Empty("The chapter list"))
        );
        assert_eq!(
            resynthesize(vec![0], None).args(),
            Err(RequestError::OutOfRange("The chapter"))
        );
        assert_eq!(
            resynthesize(vec![1], Some(f64::NAN)).args(),
            Err(RequestError::OutOfRange("The speed"))
        );
        let request: Request = serde_json::from_str(
            r#"{"command": "verify_audio", "manifest": "/w/manifest.json", "models": ["wav2vec2"]}"#,
        )
        .unwrap();
        assert_eq!(
            request,
            Request::VerifyAudio {
                manifest: manifest.clone(),
                chapters: vec![],
                models: vec![AsrModel::Wav2vec2],
            }
        );
        assert!(
            serde_json::from_str::<Request>(
                r#"{"command": "verify_audio", "manifest": "/m", "models": ["hosted"]}"#
            )
            .is_err()
        );
    }

    #[test]
    fn audio_verification_writes_only_through_the_book_lock() {
        let manifest = PathBuf::from("/w/manifest.json");
        assert!(!Request::AsrList.is_write());
        assert!(
            !Request::AsrFetch {
                models: vec![AsrModel::Vosk]
            }
            .is_write()
        );
        assert!(
            !Request::AudioReport {
                manifest: manifest.clone()
            }
            .is_write()
        );
        assert!(
            Request::VerifyAudio {
                manifest: manifest.clone(),
                chapters: vec![],
                models: vec![],
            }
            .is_write()
        );
        assert!(
            Request::AudioDismiss {
                manifest: manifest.clone(),
                chapter: 1,
                flag: 0,
                undo: false,
            }
            .is_write()
        );
        assert!(
            Request::Resynthesize {
                voice_clone: CloneOptions::default(),
                tts_provider: None,
                tts_model: None,
                manifest,
                chapters: vec![1],
                voice: None,
                speed: None,
                verify_audio: None,
            }
            .is_write()
        );
    }

    #[test]
    fn json_and_no_progress_are_always_present() {
        let requests = [
            Request::Doctor { check_llm: false },
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
        assert!(!Request::Doctor { check_llm: true }.is_write());
        assert!(
            !Request::EditsList {
                manifest: manifest.clone(),
                status: EditStatus::Pending,
                with_text: false,
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
    fn a_pdf_password_is_only_ever_an_environment_variable_name() {
        let name = env("BOOK_PDF_PASSWORD");
        let options = BookOptions {
            pdf_password_env: Some(name.clone()),
            ..BookOptions::default()
        };
        let requests = [
            Request::Inspect {
                source: "/b.pdf".into(),
                pdf_password_env: Some(name.clone()),
            },
            Request::Thumbnail {
                book: "/b.pdf".into(),
                output: "/t.png".into(),
                width: 320,
                pdf_password_env: Some(name.clone()),
            },
            Request::Analyze {
                book: "/b.pdf".into(),
                options: options.clone(),
            },
            Request::Convert {
                book: "/b.pdf".into(),
                options,
                convert: ConvertOptions::default(),
            },
        ];
        for request in requests {
            let args = args_of(request);
            let password_args: Vec<_> =
                args.iter().filter(|arg| arg.contains("password")).collect();
            assert_eq!(password_args, ["--pdf-password-env=BOOK_PDF_PASSWORD"]);
        }
    }

    #[test]
    fn a_password_typed_where_a_variable_name_belongs_is_refused() {
        for value in [
            "hunter2!",
            "my secret",
            "p@ssw0rd",
            "",
            "1BOOK",
            "BOOK-PW",
            "PW=secret",
        ] {
            assert_eq!(
                EnvVarName::try_from(value.to_owned()),
                Err(RequestError::InvalidEnvVarName),
                "{value}"
            );
        }
        assert!(EnvVarName::try_from("A".repeat(129)).is_err());
        for value in ["BOOK_PDF_PASSWORD", "_pw", "pw2"] {
            assert!(EnvVarName::try_from(value.to_owned()).is_ok(), "{value}");
        }
        let json = r#"{"command": "inspect", "source": "/b.pdf", "pdf_password_env": "hunter2!"}"#;
        let error = serde_json::from_str::<Request>(json)
            .unwrap_err()
            .to_string();
        assert!(!error.contains("hunter2"), "{error}");
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
            Request::Doctor { check_llm: false },
            Request::ConfigShow,
            Request::AsrList,
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
            assert!(matches!(
                crate::engine::result::parse(&done),
                crate::engine::result::Outcome::Success { .. }
            ));
        }
        let missing = Request::Workspace {
            book: temp.path().join("missing.pdf"),
            output: None,
        };
        let done = SystemRunner.run(&cli, &missing.args().unwrap()).unwrap();
        let crate::engine::result::Outcome::Failed { error, .. } =
            crate::engine::result::parse(&done)
        else {
            panic!("expected a failure: {}", done.stderr)
        };
        assert_eq!((error.kind.as_str(), error.code), ("InputError", 3));
        assert_eq!(error.reason, None);
    }
}

#[cfg(test)]
mod clone_tests {
    use super::*;
    #[test]
    fn private_paths_are_single_args_and_details_are_redacted() {
        let request: Request = serde_json::from_value(serde_json::json!({
            "command":"convert", "book":"book.pdf", "options":{},
            "convert":{"clone_voice":true,"tts_model":"kitten2", "reference_audio":"/PRIVATE/a ' ; $(no).wav", "reference_text_file":"/PRIVATE/words.txt"}
        })).unwrap();
        let args = request.args().unwrap();
        assert!(args.contains(&OsString::from(
            "--reference-audio=/PRIVATE/a ' ; $(no).wav"
        )));
        let shown = crate::commands::display_command(
            &crate::engine::process::CliCommand::direct("cli"),
            &args,
        );
        assert!(!shown.contains("PRIVATE"));
        assert!(shown.contains("--reference-audio=[private]"));
    }
    #[test]
    fn drafts_do_not_enter_argv_or_debug_and_are_kept_until_drop() {
        let mut request: Request = serde_json::from_value(serde_json::json!({
            "command":"resynthesize", "manifest":"manifest.json", "chapters":[1],
            "clone_voice":true,"reference_text":"PRIVATE WORDS", "reference_audio":"/PRIVATE/ref.wav"
        })).unwrap();
        assert!(!format!("{request:?}").contains("PRIVATE"));
        assert!(!format!("{:?}", request.args().unwrap()).contains("PRIVATE WORDS"));
        let draft = request.prepare_transcript().unwrap().unwrap();
        let path = draft.path();
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "PRIVATE WORDS");
        assert!(
            request
                .args()
                .unwrap()
                .iter()
                .any(|arg| arg.to_string_lossy().contains("--reference-text-file="))
        );
        drop(draft);
        assert!(!path.exists());
    }
}

#[cfg(test)]
mod real_clone_cli {
    use super::*;
    use crate::engine::process::{CliCommand, Runner, SystemRunner};
    #[test]
    #[ignore = "needs uv, Python CLI and FFmpeg; explicit synthetic backend"]
    fn real_cli_clone_bridge_converts_resumes_and_repairs() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let folder = tempfile::tempdir().unwrap();
        let state = folder.path().join("state");
        let launcher = root.join("desktop/e2e/fake_clone.py");
        let prefix = vec![
            "run".into(),
            "--project".into(),
            root.clone().into_os_string(),
            "python".into(),
            launcher.into_os_string(),
            state.clone().into_os_string(),
        ];
        let cli = CliCommand {
            program: "uv".into(),
            prefix,
        };
        assert_eq!(
            SystemRunner.run(&cli, &["--prepare".into()]).unwrap().code,
            Some(0)
        );
        let book = folder.path().join("book.pdf");
        let code = "import fitz,sys; d=fitz.open(); [(lambda p,n:(p.insert_text((80,60),f'Chapter {n}'),p.insert_text((80,115),'The keeper opened the door.')))(d.new_page(),n) for n in (1,2)]; d.save(sys.argv[1])";
        let python = CliCommand {
            program: "uv".into(),
            prefix: vec![
                "run".into(),
                "--project".into(),
                root.into_os_string(),
                "python".into(),
                "-c".into(),
                code.into(),
            ],
        };
        assert_eq!(
            SystemRunner
                .run(&python, &[book.clone().into_os_string()])
                .unwrap()
                .code,
            Some(0)
        );
        let convert = ConvertOptions {
            tts_model: Some("kitten2".into()),
            voice_clone: CloneOptions {
                clone_voice: Some(true),
                reference_audio: Some(state.join("reference.wav")),
                reference_text: Some("PRIVATE_WORDS".into()),
                ..Default::default()
            },
            ..Default::default()
        };
        let mut request = Request::Convert {
            book,
            options: BookOptions {
                llm: Some(false),
                ocr: Some(OcrMode::Never),
                output: Some(folder.path().join("out")),
                ..Default::default()
            },
            convert,
        };
        let draft = request.prepare_transcript().unwrap().unwrap();
        let path = draft.path();
        for _ in 0..2 {
            let done = SystemRunner.run(&cli, &request.args().unwrap()).unwrap();
            assert_eq!(done.code, Some(0), "{}", done.stderr);
            assert!(!done.stdout.contains("PRIVATE_WORDS"));
        }
        let before = std::fs::read(state.join("generation.jsonl")).unwrap();
        let done = SystemRunner.run(&cli, &request.args().unwrap()).unwrap();
        assert_eq!(done.code, Some(0));
        assert_eq!(
            std::fs::read(state.join("generation.jsonl")).unwrap(),
            before
        );
        let workspace = std::fs::read_dir(folder.path().join("out"))
            .unwrap()
            .next()
            .unwrap()
            .unwrap()
            .path();
        let mut repair: Request = serde_json::from_value(serde_json::json!({"command":"resynthesize","manifest":workspace.join("manifest.json"),"chapters":[2],"tts_model":"kitten2","clone_voice":true,"reference_audio":state.join("reference.wav"),"reference_text":"PRIVATE_WORDS"})).unwrap();
        let repair_draft = repair.prepare_transcript().unwrap().unwrap();
        let done = SystemRunner.run(&cli, &repair.args().unwrap()).unwrap();
        assert_eq!(done.code, Some(0), "{}", done.stderr);
        assert!(workspace.join("audio/.backup").is_dir());
        drop(repair_draft);
        drop(draft);
        assert!(!path.exists());
    }
}

/// Opt-in real model contract, using a CLI environment that already has weights/dependencies.
#[cfg(test)]
mod real_clone_model {
    use super::*;
    use crate::engine::process::{CliCommand, Runner, SystemRunner};

    #[test]
    #[ignore = "needs an authorized reference and a prepared KittenTTS 2 CLI environment"]
    fn clone_bridge_real_model() {
        let reference = std::env::var_os("PDF2AUDIOBOOK_TEST_CLONE_REFERENCE")
            .expect("Set PDF2AUDIOBOOK_TEST_CLONE_REFERENCE to an authorized local recording");
        let program = std::env::var_os("PDF2AUDIOBOOK_TEST_CLONE_CLI")
            .expect("Set PDF2AUDIOBOOK_TEST_CLONE_CLI to the prepared CLI executable");
        let cli = CliCommand::direct(PathBuf::from(program));
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let folder = tempfile::tempdir().unwrap();
        let source = folder.path().join("book.pdf");
        // outlined_text.pdf is intentionally empty; create actual narration for this check.
        let python = CliCommand {
            program: "uv".into(),
            prefix: vec![
                "run".into(),
                "--project".into(),
                root.into_os_string(),
                "python".into(),
            ],
        };
        let code = "import pymupdf,sys; d=pymupdf.open(); p=d.new_page(); p.insert_text((80,60),'Chapter 1'); p.insert_text((80,115),'The lighthouse keeper opened the door.'); d.save(sys.argv[1])";
        let made = SystemRunner
            .run(
                &python,
                &["-c".into(), code.into(), source.clone().into_os_string()],
            )
            .unwrap();
        assert_eq!(made.code, Some(0), "{}", made.stderr);
        let request = Request::Convert {
            book: source,
            options: BookOptions {
                llm: Some(false),
                ocr: Some(OcrMode::Never),
                output: Some(folder.path().join("out")),
                ..Default::default()
            },
            convert: ConvertOptions {
                tts_provider: Some(TtsProvider::Kitten),
                tts_model: Some("kitten2".into()),
                voice_clone: CloneOptions {
                    clone_voice: Some(true),
                    reference_audio: Some(reference.into()),
                    reference_text_file: std::env::var_os("PDF2AUDIOBOOK_TEST_CLONE_TRANSCRIPT")
                        .map(PathBuf::from),
                    ..Default::default()
                },
                ..Default::default()
            },
        };
        let args = request.args().unwrap();
        let first = SystemRunner.run(&cli, &args).unwrap();
        assert_eq!(first.code, Some(0), "{}", first.stderr);
        let result: serde_json::Value = serde_json::from_str(&first.stdout).unwrap();
        let files: Vec<PathBuf> = serde_json::from_value(result["mp3_files"].clone()).unwrap();
        assert!(!files.is_empty());
        let modified: Vec<_> = files
            .iter()
            .map(|p| p.metadata().unwrap().modified().unwrap())
            .collect();
        let resumed = SystemRunner.run(&cli, &args).unwrap();
        assert_eq!(resumed.code, Some(0), "{}", resumed.stderr);
        assert_eq!(
            files
                .iter()
                .map(|p| p.metadata().unwrap().modified().unwrap())
                .collect::<Vec<_>>(),
            modified
        );
    }
}
