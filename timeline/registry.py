"""Committee registry management utilities."""

from __future__ import annotations

import json
from typing import Optional, TYPE_CHECKING
from pathlib import Path
from timeline.normalizers import (
    CommitteeAlias,
    COMMITTEE_REGISTRY,
    load_committee_registry_from_cache,
)

if TYPE_CHECKING:
    from components.utils import Cache
    from timeline.normalizers import CommitteeChamber


def build_registry_from_cache(cache: Cache) -> dict[str, CommitteeAlias]:
    """Build committee registry from cache file.

    Args:
        cache_path: Path to cache.json file

    Returns:
        Dictionary of committee ID -> info
    """
    load_committee_registry_from_cache(cache)
    return COMMITTEE_REGISTRY


def get_committee_info(committee_id: str) -> Optional[CommitteeAlias]:
    """Get information about a committee.

    Args:
        committee_id: Committee ID (e.g., "J10")

    Returns:
        Dictionary with committee info, or None if not found
    """
    return COMMITTEE_REGISTRY.get(committee_id)


def list_committees() -> dict[str, str]:
    """List all known committees.

    Returns:
        Dictionary mapping committee IDs to canonical names
    """
    return {
        committee_id: info.canonical_name
        for committee_id, info in COMMITTEE_REGISTRY.items()
    }


def add_committee(
    committee_id: str,
    canonical_name: str,
    chamber: CommitteeChamber,
    short_names: list[str],
) -> None:
    """Add a committee to the registry.

    Args:
        committee_id: Committee ID (e.g., "J10")
        canonical_name: Full official committee name
        variants: List of name variations to recognize
    """
    COMMITTEE_REGISTRY[committee_id] = CommitteeAlias(
        committee_id, canonical_name, chamber, short_names
    )


def save_registry(
    output_path: Path = Path("cache/timeline_committee_registry.json"),
) -> None:
    """Save committee registry to a JSON file.

    Args:
        output_path: Path to save registry
    """
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(COMMITTEE_REGISTRY, f, indent=2)


def load_registry(input_path: Path) -> None:
    """Load committee registry from a JSON file.

    Args:
        input_path: Path to load registry from
    """
    with open(input_path, "r", encoding="utf-8") as f:
        registry: dict[str, CommitteeAlias] = json.load(f)
        COMMITTEE_REGISTRY.clear()
        COMMITTEE_REGISTRY.update(registry)
