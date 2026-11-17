"""Value provenance: every number carries where it came from.

The AI layer must never confuse an assumption with a measurement, so every
parameter used by the calculation engine is stored as a Param with a Source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Source(str, Enum):
    MEASURED = "measured"          # instrument / BMS data
    USDZ = "usdz"                  # extracted from the 3D model
    ENGINEER = "engineer"          # supplied by an engineer
    HYPOTHETICAL = "hypothetical"  # illustrative value from the brief
    ASSUMED = "assumed"            # engineering assumption (typical value)
    CONSTANT = "constant"          # physical constant / unit conversion
    PREDICTED = "predicted"        # computed by the model
    VALIDATED = "validated"        # prediction confirmed against data
    UNKNOWN = "unknown"            # needed but not available


@dataclass
class Param:
    name: str
    value: object
    unit: str
    source: Source
    note: str = ""


@dataclass
class Issue:
    priority: str   # HIGH / MEDIUM / LOW  (impact on accuracy, safety, optimisation)
    topic: str
    message: str
    options: list[str] = field(default_factory=list)


class Registry:
    """Named parameters with provenance plus a log of open issues."""

    def __init__(self) -> None:
        self.params: dict[str, Param] = {}
        self.issues: list[Issue] = []

    def set(self, name, value, unit, source, note=""):
        self.params[name] = Param(name, value, unit, Source(source), note)
        return value

    def __getitem__(self, name):
        return self.params[name].value

    def __contains__(self, name):
        return name in self.params

    def flag(self, priority, topic, message, options=None):
        self.issues.append(Issue(priority, topic, message, options or []))

    def by_source(self, source: Source):
        return [p for p in self.params.values() if p.source == source]
