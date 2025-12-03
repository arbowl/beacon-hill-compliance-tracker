"""Timeline-based bill action extraction system.

This package provides a structured approach to extracting and analyzing
bill action histories from the Massachusetts Legislature website.

Main components:
- models: Core data structures (BillAction, BillActionTimeline)
- parser: Action extraction from bill pages
- extractors: Field extraction utilities (dates, committees, etc.)
- normalizers: Data standardization (committee names, etc.)
- nodes: Action type definitions and pattern matching
- registry: Committee name registry and lookup
"""

from timeline.models import BillAction, BillActionTimeline, ActionNode
from timeline.parser import extract_timeline, ActionExtractor

__all__ = [
    "BillAction",
    "BillActionTimeline",
    "ActionNode",
    "extract_timeline",
    "ActionExtractor",
]

__version__ = "0.1.0"

