"""Dataset-specific adapters: raw source files -> shared FeatureSample sequences.

Adapters absorb everything peculiar to a dataset — column layouts, units, axis
conventions, sample rates — so that `app.core.features` stays dataset-agnostic
and has exactly one implementation (ADR 0004).
"""

from pipelines.adapters.uah import (
    AxisDetection,
    AxisMapping,
    RecordingMeta,
    UahParseError,
    UahRecording,
    detect_axis_mapping,
    find_recordings,
    load_recording,
    load_recordings,
)

__all__ = [
    "AxisDetection",
    "AxisMapping",
    "RecordingMeta",
    "UahParseError",
    "UahRecording",
    "detect_axis_mapping",
    "find_recordings",
    "load_recording",
    "load_recordings",
]
