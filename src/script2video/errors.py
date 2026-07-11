"""Exception hierarchy for script2video."""


class Script2VideoError(Exception):
    """Base class for all script2video errors."""


class ScriptError(Script2VideoError):
    """The markdown script is malformed.

    Carries an optional 1-based line number so CLI output can point at the
    offending line.
    """

    def __init__(self, message: str, line: int | None = None) -> None:
        self.line = line
        if line is not None:
            message = f"line {line}: {message}"
        super().__init__(message)


class NarrationError(Script2VideoError):
    """Text-to-speech synthesis failed (usually a network problem)."""


class MediaError(Script2VideoError):
    """ffmpeg execution or media probing failed."""
