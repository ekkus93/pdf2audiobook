"""Domain exceptions and stable process exit codes."""


class AudiobookError(Exception):
    exit_code = 1
    # Stable code in --json errors for failures a caller can act on, e.g. "review_required".
    # Set on a subclass or per raise; None leaves the JSON error without a "reason" key.
    error_reason: str | None = None

    def __init__(self, *args: object, error_reason: str | None = None) -> None:
        super().__init__(*args)
        if error_reason is not None:
            self.error_reason = error_reason


class ConfigError(AudiobookError):
    exit_code = 2


class InputError(AudiobookError):
    exit_code = 3


class ExtractionError(AudiobookError):
    exit_code = 4


class WorkspaceError(ExtractionError):
    """The application could not create or update an output workspace."""


class PendingRecoveryError(WorkspaceError):
    """A committed workspace update is pending and must be recovered first."""

    error_reason = "pending_recovery"

    def __init__(self, message: str, *, labels: tuple[str, ...] | list[str] = ()):
        super().__init__(message)
        # Safe target labels such as "chapter 1"; never paths, digests or text.
        self.labels = tuple(labels)


class ChapterConflictError(ExtractionError):
    """A chapter file conflicts with generated text; carries only its number."""

    error_reason = "chapter_conflict"

    def __init__(self, chapter: int):
        super().__init__(
            f"Chapter {chapter} text conflicts with generated content; run pdf2audiobook "
            f"regenerate-chapter on the manifest with --chapter {chapter} to keep a backup of "
            "the file and regenerate it, or use a fresh output directory"
        )
        self.chapter = chapter


class FootnotePolicyUnknownError(ExtractionError):
    """A workspace has no recorded footnote policy and none can be safely inferred."""

    def __init__(self) -> None:
        super().__init__(
            "This workspace has no recorded footnote policy that can be determined from its "
            "chapter files; run analyze with the original pdf.footnotes setting, or pass "
            "--footnotes to regenerate-chapter"
        )


class LLMError(AudiobookError):
    exit_code = 5

    def __init__(
        self,
        message: str,
        *,
        unbilled: bool = False,
        reason: str | None = None,
        error_reason: str | None = None,
    ):
        super().__init__(message, error_reason=error_reason)
        # Stable, content-free tag for logs, e.g. "output_cap".
        self.reason = reason
        # Only transport failures that prove the request was never sent set this.
        self.unbilled = unbilled


class AudioError(AudiobookError):
    exit_code = 6


class TTSError(AudioError):
    """Text-to-speech provider metadata or synthesis operation failed."""


class WorkspaceLockedError(AudioError):
    """A workspace is currently owned by another analysis or conversion."""

    error_reason = "workspace_locked"


class PartialConversionError(AudiobookError):
    exit_code = 7
