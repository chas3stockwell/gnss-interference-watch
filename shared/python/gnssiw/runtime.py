"""Process-wide switches read from the Lambda environment."""

import os

from gnssiw.detection import MIN_HISTORY_DAYS, SUGGESTED_WINDOW_DAYS


def stub_mode() -> bool:
    """True unless ``GNSSIW_STUB`` is exactly ``0``.

    Stub mode is the skeleton default: handlers return the right shapes and
    do not call AWS or the public data hosts. Set the SAM parameter
    ``StubMode`` to ``0`` only after the TODO in that function is implemented.
    """
    return os.environ.get("GNSSIW_STUB", "1") != "0"


def trailing_window_days() -> int:
    """How many prior days the Detector should score against."""
    raw = os.environ.get("Z_WINDOW_DAYS", str(SUGGESTED_WINDOW_DAYS))
    try:
        window = int(raw)
    except ValueError as exc:
        raise ValueError("Z_WINDOW_DAYS must be an integer") from exc
    if window < MIN_HISTORY_DAYS:
        raise ValueError(f"Z_WINDOW_DAYS must be >= {MIN_HISTORY_DAYS}")
    return window


def bedrock_enabled() -> bool:
    """Optional plain-English summaries. Off until Part 3 turns it on."""
    return os.environ.get("ENABLE_BEDROCK", "0") == "1"
