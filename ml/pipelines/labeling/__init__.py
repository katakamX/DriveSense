"""Training-label rubric: feature window -> weak-supervision class.

See docs/adr/0006-training-label-rubric.md for why this exists as a rule-based
rubric rather than trained labels, and rubric.py for the rules themselves.
"""

from pipelines.labeling.rubric import RUBRIC_VERSION, Label, label_window_with_reason

__all__ = ["RUBRIC_VERSION", "Label", "label_window_with_reason"]
