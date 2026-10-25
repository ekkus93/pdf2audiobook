"""Domain exceptions and stable process exit codes."""


class AudiobookError(Exception):
    exit_code = 1


class ConfigError(AudiobookError):
    exit_code = 2


class InputError(AudiobookError):
    exit_code = 3


class ExtractionError(AudiobookError):
    exit_code = 4


class LLMError(AudiobookError):
    exit_code = 5

    def __init__(self, message: str, *, unbilled: bool = False):
        super().__init__(message)
        # Only transport failures that prove the request was never sent set this.
        self.unbilled = unbilled


class AudioError(AudiobookError):
    exit_code = 6


class PartialConversionError(AudiobookError):
    exit_code = 7
