"""Domain exceptions and stable process exit codes."""


class AudiobookError(Exception):
    exit_code = 1


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


class ChapterConflictError(ExtractionError):
    """A chapter file conflicts with generated text; carries only its number."""

    def __init__(self, chapter: int):
        super().__init__(
            f"Chapter {chapter} text conflicts with generated content; back up the chapter file "
            "and restore generated text or use a fresh output directory"
        )
        self.chapter = chapter


class LLMError(AudiobookError):
    exit_code = 5

    def __init__(self, message: str, *, unbilled: bool = False):
        super().__init__(message)
        # Only transport failures that prove the request was never sent set this.
        self.unbilled = unbilled


class AudioError(AudiobookError):
    exit_code = 6


class TTSError(AudioError):
    """Text-to-speech provider metadata or synthesis operation failed."""


class WorkspaceLockedError(AudioError):
    """A workspace is currently owned by another analysis or conversion."""


class PartialConversionError(AudiobookError):
    exit_code = 7
