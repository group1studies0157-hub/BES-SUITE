"""
Core data model for borehole logs.

Every parser (Excel, PDF, ...) must produce a list of `BoreholeRecord`
objects. The DXF builder only depends on this model, so adding a new
input format later only means writing a new parser - the drawing logic
never changes.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class SoilLayer:
    """One stratigraphic layer inside a borehole, in metres below E.G.L."""
    from_depth: float
    to_depth: float
    description: str = ""

    @property
    def thickness(self) -> float:
        return self.to_depth - self.from_depth


@dataclass
class TestRecord:
    """One SPT / rock-core test at a given depth."""
    depth: float
    note: str = ""              # e.g. "N=43", "Rock Core Recovery 60cm, RQD 51%"
    density: str = ""           # e.g. "V.Dense", "Hard"
    sample_type: str = ""       # e.g. "DS", "CS"


@dataclass
class BoreholeRecord:
    location: str
    project: str = ""
    br_no: str = ""
    dates: str = ""
    gwt: float | None = None            # ground water table depth (m), None if not struck
    layers: list[SoilLayer] = field(default_factory=list)
    tests: list[TestRecord] = field(default_factory=list)
    termination_note: str = ""
    figure_ref: str = ""
    source_sheet: str = ""              # sheet name / page number, for traceability

    @property
    def total_depth(self) -> float:
        if self.layers:
            return max(l.to_depth for l in self.layers)
        if self.tests:
            return max(t.depth for t in self.tests)
        return 0.0

    def validate(self) -> list[str]:
        """Return a list of human-readable warnings (not exceptions) about
        gaps, overlaps or missing data, so a GUI can show them before the
        DXF is generated."""
        warnings = []
        if not self.location:
            warnings.append("Missing location/borehole ID")
        if not self.layers:
            warnings.append(f"[{self.location}] No soil layers parsed")
        prev_to = 0.0
        for l in sorted(self.layers, key=lambda x: x.from_depth):
            if abs(l.from_depth - prev_to) > 0.01:
                warnings.append(
                    f"[{self.location}] Gap/overlap between {prev_to:.2f}m and {l.from_depth:.2f}m")
            prev_to = l.to_depth
        if not self.tests:
            warnings.append(f"[{self.location}] No SPT/RQD test rows parsed")
        return warnings
