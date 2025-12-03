"""Data normalization utilities for standardizing extracted fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from components.utils import Cache


class CommitteeChamber(str, Enum):
    """Chamber type for committees."""

    HOUSE = "House"
    SENATE = "Senate"
    JOINT = "Joint"


@dataclass(frozen=True)
class CommitteeAlias:
    """Represents a legislative committee with normalized data.

    Attributes:
        id: Committee ID (e.g., "J10", "H33", "S29")
        canonical_name: Full official committee name
        chamber: Chamber type (House, Senate, or Joint)
        short_names: List of name variations for matching
    """
    id: str
    canonical_name: str
    chamber: CommitteeChamber
    short_names: list[str]

    def matches(self, text: str) -> bool:
        """Check if text matches any variant of this committee name.

        Args:
            text: Committee name text to match

        Returns:
            True if text matches any variant
        """
        if not text:
            return False
        cleaned = text.strip().lower()
        for variant in self.short_names:
            if variant.lower() == cleaned:
                return True
        for variant in self.short_names:
            if variant.lower() in cleaned or cleaned in variant.lower():
                return True
        return False


# Committee registry: List of all MA Legislature committees
# Built from the official committee list
_COMMITTEES: list[CommitteeAlias] = [
    # House Committees
    CommitteeAlias("H33", "House Committee on Rules", CommitteeChamber.HOUSE,
              ["Rules", "House Committee on Rules", "House Rules"]),
    CommitteeAlias("H34", "House Committee on Ways and Means", CommitteeChamber.HOUSE,
              ["Ways and Means", "House Committee on Ways and Means", "House Ways and Means"]),
    CommitteeAlias("H36", "House Committee on Bills in the Third Reading", CommitteeChamber.HOUSE,
              ["Bills in the Third Reading", "House Committee on Bills in the Third Reading"]),
    CommitteeAlias("H38", "House Committee on Ethics", CommitteeChamber.HOUSE,
              ["Ethics", "House Committee on Ethics", "House Ethics"]),
    CommitteeAlias("H45", "House Committee on Human Resources and Employee Engagement", CommitteeChamber.HOUSE,
              ["Human Resources and Employee Engagement", "House Committee on Human Resources and Employee Engagement"]),
    CommitteeAlias("H46", "House Committee on Post Audit and Oversight", CommitteeChamber.HOUSE,
              ["Post Audit and Oversight", "House Committee on Post Audit and Oversight", "House Post Audit and Oversight"]),
    CommitteeAlias("H51", "House Committee on Climate Action and Sustainability", CommitteeChamber.HOUSE,
              ["Climate Action and Sustainability", "House Committee on Climate Action and Sustainability"]),
    CommitteeAlias("H52", "House Committee on Steering, Policy and Scheduling", CommitteeChamber.HOUSE,
              ["Steering, Policy and Scheduling", "House Committee on Steering, Policy and Scheduling", "House Steering, Policy and Scheduling"]),
    CommitteeAlias("H53", "House Committee on Operations, Facilities and Security", CommitteeChamber.HOUSE,
              ["Operations, Facilities and Security", "House Committee on Operations, Facilities and Security"]),
    CommitteeAlias("H54", "House Committee on Federal Funding, Policy and Accountability", CommitteeChamber.HOUSE,
              ["Federal Funding, Policy and Accountability", "House Committee on Federal Funding, Policy and Accountability"]),

    # Joint Committees
    CommitteeAlias("J10", "Joint Committee on Municipalities and Regional Government", CommitteeChamber.JOINT,
              ["Municipalities and Regional Government", "Joint Committee on Municipalities and Regional Government"]),
    CommitteeAlias("J11", "Joint Committee on Financial Services", CommitteeChamber.JOINT,
              ["Financial Services", "Joint Committee on Financial Services"]),
    CommitteeAlias("J12", "Joint Committee on Economic Development and Emerging Technologies", CommitteeChamber.JOINT,
              ["Economic Development and Emerging Technologies", "Joint Committee on Economic Development and Emerging Technologies"]),
    CommitteeAlias("J13", "Joint Committee on Children, Families and Persons with Disabilities", CommitteeChamber.JOINT,
              ["Children, Families and Persons with Disabilities", "Joint Committee on Children, Families and Persons with Disabilities"]),
    CommitteeAlias("J14", "Joint Committee on Education", CommitteeChamber.JOINT,
              ["Education", "Joint Committee on Education"]),
    CommitteeAlias("J15", "Joint Committee on Election Laws", CommitteeChamber.JOINT,
              ["Election Laws", "Joint Committee on Election Laws"]),
    CommitteeAlias("J16", "Joint Committee on Public Health", CommitteeChamber.JOINT,
              ["Public Health", "Joint Committee on Public Health"]),
    CommitteeAlias("J17", "Joint Committee on Consumer Protection and Professional Licensure", CommitteeChamber.JOINT,
              ["Consumer Protection and Professional Licensure", "Joint Committee on Consumer Protection and Professional Licensure"]),
    CommitteeAlias("J18", "Joint Committee on Mental Health, Substance Use and Recovery", CommitteeChamber.JOINT,
              ["Mental Health, Substance Use and Recovery", "Joint Committee on Mental Health, Substance Use and Recovery"]),
    CommitteeAlias("J19", "Joint Committee on the Judiciary", CommitteeChamber.JOINT,
              ["the Judiciary", "Judiciary", "Joint Committee on the Judiciary"]),
    CommitteeAlias("J21", "Joint Committee on Environment and Natural Resources", CommitteeChamber.JOINT,
              ["Environment and Natural Resources", "Joint Committee on Environment and Natural Resources"]),
    CommitteeAlias("J22", "Joint Committee on Public Safety and Homeland Security", CommitteeChamber.JOINT,
              ["Public Safety and Homeland Security", "Joint Committee on Public Safety and Homeland Security"]),
    CommitteeAlias("J23", "Joint Committee on Public Service", CommitteeChamber.JOINT,
              ["Public Service", "Joint Committee on Public Service"]),
    CommitteeAlias("J24", "Joint Committee on Health Care Financing", CommitteeChamber.JOINT,
              ["Health Care Financing", "Joint Committee on Health Care Financing"]),
    CommitteeAlias("J25", "Joint Committee on State Administration and Regulatory Oversight", CommitteeChamber.JOINT,
              ["State Administration and Regulatory Oversight", "Joint Committee on State Administration and Regulatory Oversight"]),
    CommitteeAlias("J26", "Joint Committee on Revenue", CommitteeChamber.JOINT,
              ["Revenue", "Joint Committee on Revenue"]),
    CommitteeAlias("J27", "Joint Committee on Transportation", CommitteeChamber.JOINT,
              ["Transportation", "Joint Committee on Transportation"]),
    CommitteeAlias("J28", "Joint Committee on Housing", CommitteeChamber.JOINT,
              ["Housing", "Joint Committee on Housing"]),
    CommitteeAlias("J29", "Joint Committee on Higher Education", CommitteeChamber.JOINT,
              ["Higher Education", "Joint Committee on Higher Education"]),
    CommitteeAlias("J30", "Joint Committee on Tourism, Arts and Cultural Development", CommitteeChamber.JOINT,
              ["Tourism, Arts and Cultural Development", "Joint Committee on Tourism, Arts and Cultural Development"]),
    CommitteeAlias("J31", "Joint Committee on Veterans and Federal Affairs", CommitteeChamber.JOINT,
              ["Veterans and Federal Affairs", "Joint Committee on Veterans and Federal Affairs"]),
    CommitteeAlias("J32", "Joint Committee on Bonding, Capital Expenditures and State Assets", CommitteeChamber.JOINT,
              ["Bonding, Capital Expenditures and State Assets", "Joint Committee on Bonding, Capital Expenditures and State Assets"]),
    CommitteeAlias("J33", "Joint Committee on Advanced Information Technology, the Internet and Cybersecurity", CommitteeChamber.JOINT,
              ["Advanced Information Technology, the Internet and Cybersecurity", "Advanced Information Technology", "Joint Committee on Advanced Information Technology, the Internet and Cybersecurity"]),
    CommitteeAlias("J34", "Joint Committee on Racial Equity, Civil Rights, and Inclusion", CommitteeChamber.JOINT,
              ["Racial Equity, Civil Rights, and Inclusion", "Joint Committee on Racial Equity, Civil Rights, and Inclusion"]),
    CommitteeAlias("J37", "Joint Committee on Telecommunications, Utilities and Energy", CommitteeChamber.JOINT,
              ["Telecommunications, Utilities and Energy", "Joint Committee on Telecommunications, Utilities and Energy"]),
    CommitteeAlias("J39", "Joint Committee on Ways and Means", CommitteeChamber.JOINT,
              ["Ways and Means", "Joint Committee on Ways and Means", "Joint Ways and Means"]),
    CommitteeAlias("J40", "Joint Committee on Rules", CommitteeChamber.JOINT,
              ["Rules", "Joint Committee on Rules", "Joint Rules"]),
    CommitteeAlias("J43", "Joint Committee on Labor and Workforce Development", CommitteeChamber.JOINT,
              ["Labor and Workforce Development", "Joint Committee on Labor and Workforce Development"]),
    CommitteeAlias("J45", "Joint Committee on Agriculture and Fisheries", CommitteeChamber.JOINT,
              ["Agriculture and Fisheries", "Joint Committee on Agriculture and Fisheries"]),
    CommitteeAlias("J46", "Joint Committee on Aging and Independence", CommitteeChamber.JOINT,
              ["Aging and Independence", "Joint Committee on Aging and Independence"]),
    CommitteeAlias("J47", "Joint Committee on Community Development and Small Businesses", CommitteeChamber.JOINT,
              ["Community Development and Small Businesses", "Joint Committee on Community Development and Small Businesses"]),
    CommitteeAlias("J50", "Joint Committee on Cannabis Policy", CommitteeChamber.JOINT,
              ["Cannabis Policy", "Joint Committee on Cannabis Policy"]),
    CommitteeAlias("J52", "Joint Committee on Emergency Preparedness and Management", CommitteeChamber.JOINT,
              ["Emergency Preparedness and Management", "Joint Committee on Emergency Preparedness and Management"]),

    # Senate Committees
    CommitteeAlias("S29", "Senate Committee on Rules", CommitteeChamber.SENATE,
              ["Rules", "Senate Committee on Rules", "Senate Rules"]),
    CommitteeAlias("S30", "Senate Committee on Ways and Means", CommitteeChamber.SENATE,
              ["Ways and Means", "Senate Committee on Ways and Means", "Senate Ways and Means"]),
    CommitteeAlias("S31", "Senate Committee on Bills in the Third Reading", CommitteeChamber.SENATE,
              ["Bills in the Third Reading", "Senate Committee on Bills in the Third Reading", "Senate Bills in the Third Reading"]),
    CommitteeAlias("S48", "Senate Committee on Post Audit and Oversight", CommitteeChamber.SENATE,
              ["Post Audit and Oversight", "Senate Committee on Post Audit and Oversight", "Senate Post Audit and Oversight"]),
    CommitteeAlias("S50", "Senate Committee on Steering and Policy", CommitteeChamber.SENATE,
              ["Steering and Policy", "Senate Committee on Steering and Policy", "Senate Steering and Policy"]),
    CommitteeAlias("S51", "Senate Committee on Climate Change and Global Warming", CommitteeChamber.SENATE,
              ["Climate Change and Global Warming", "Senate Committee on Climate Change and Global Warming"]),
    CommitteeAlias("S53", "Senate Committee on Personnel and Administration", CommitteeChamber.SENATE,
              ["Personnel and Administration", "Senate Committee on Personnel and Administration"]),
    CommitteeAlias("S55", "Senate Committee on Intergovernmental Affairs", CommitteeChamber.SENATE,
              ["Intergovernmental Affairs", "Senate Committee on Intergovernmental Affairs"]),
    CommitteeAlias("S56", "Senate Committee on Ethics", CommitteeChamber.SENATE,
              ["Ethics", "Senate Committee on Ethics", "Senate Ethics"]),
    CommitteeAlias("S65", "Senate Committee on the Census", CommitteeChamber.SENATE,
              ["the Census", "Census", "Senate Committee on the Census"]),
    CommitteeAlias("S66", "Senate Committee on Juvenile and Emerging Adult Justice", CommitteeChamber.SENATE,
              ["Juvenile and Emerging Adult Justice", "Senate Committee on Juvenile and Emerging Adult Justice"]),
]

# Create lookup dictionary for fast access by ID
COMMITTEE_REGISTRY: dict[str, CommitteeAlias] = {c.id: c for c in _COMMITTEES}


def normalize_committee_name(raw_name: str) -> Optional[str]:
    """Normalize a committee name to its committee ID.

    Args:
        raw_name: Raw committee name from action text

    Returns:
        Committee ID (e.g., "J10"), or None if not found
    """
    if not raw_name:
        return None
    for committee in _COMMITTEES:
        if committee.matches(raw_name):
            return committee.id
    return None


def normalize_branch_name(raw_branch: str) -> str:
    """Normalize branch name to standard format.

    Args:
        raw_branch: Raw branch text

    Returns:
        Standardized branch name: "House", "Senate", "Joint", or "Executive"
    """
    cleaned = raw_branch.strip().lower()
    if "house" in cleaned:
        return "House"
    if "senate" in cleaned:
        return "Senate"
    if "joint" in cleaned:
        return "Joint"
    if "executive" in cleaned or "governor" in cleaned:
        return "Executive"
    return raw_branch.strip()


def normalize_location(raw_location: str) -> str:
    """Normalize hearing location.

    Args:
        raw_location: Raw location text

    Returns:
        Cleaned location string
    """
    location = raw_location.strip()
    location = re.sub(r"\s+and\s+", " and ", location, flags=re.I)
    location = re.sub(r"\s+", " ", location)
    return location


def load_committee_registry_from_cache(cache: Cache) -> None:
    """Load committee registry from Cache object.

    This augments the COMMITTEE_REGISTRY with committees found in cache.

    Args:
        cache: Cache object containing committee contact information
    """
    try:
        committee_contacts: dict[str, dict] = cache.data.get(
            "committee_contacts", {}
        )
        for committee_id, info in committee_contacts.items():
            if committee_id not in COMMITTEE_REGISTRY:
                name: str = info.get("name", "")
                if not name:
                    continue
                chamber_str = info.get("chamber", "Joint")
                try:
                    chamber = CommitteeChamber(chamber_str)
                except ValueError:
                    chamber = CommitteeChamber.JOINT
                short_name = (
                    name
                    .replace("Joint Committee on ", "")
                    .replace("House Committee on ", "")
                    .replace("Senate Committee on ", "")
                )
                variants = [short_name, name]
                committee = CommitteeAlias(
                    committee_id, name, chamber, variants
                )
                _COMMITTEES.append(committee)
                COMMITTEE_REGISTRY[committee_id] = committee
    except Exception:  # pylint: disable=broad-exception-caught
        pass


def get_committee_name(committee_id: str) -> Optional[str]:
    """Get canonical committee name from ID.

    Args:
        committee_id: Committee ID (e.g., "J10")

    Returns:
        Canonical committee name, or None if not found
    """
    committee = COMMITTEE_REGISTRY.get(committee_id)
    return committee.canonical_name if committee else None


def get_committee(committee_id: str) -> Optional[CommitteeAlias]:
    """Get Committee object by ID.

    Args:
        committee_id: Committee ID (e.g., "J10")

    Returns:
        Committee object, or None if not found
    """
    return COMMITTEE_REGISTRY.get(committee_id)
