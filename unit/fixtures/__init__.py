"""Test fixtures and enums for unit testing."""

from enum import Enum


class Requirement(str, Enum):
    """Bill requirements for compliance."""

    REPORTED = "reported"
    SUMMARY = "summary"
    VOTES = "votes"


class Committee(str, Enum):
    """Common committee IDs for testing."""

    JOINT = "J33"
    HOUSE = "H33"
    SENATE = "S33"
    HEALTH_CARE_FINANCING = "J24"  # Special rules committee


class BillPrefix(str, Enum):
    """Bill prefixes for test bills."""

    HOUSE = "H"
    SENATE = "S"
