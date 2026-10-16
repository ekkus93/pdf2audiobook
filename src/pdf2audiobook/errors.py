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


class AudioError(AudiobookError):
    exit_code = 6


class PartialConversionError(AudiobookError):
    exit_code = 7
