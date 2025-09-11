"""Test the committee contact info."""

from collectors.committee_contact_info import get_committee_contact

from components.committees import get_committees
from components.utils import load_config


def test_contacts_j33_house_only() -> None:
    """Test the committee contact info."""
    cfg = load_config()
    base_url = cfg["base_url"]
    committees = get_committees(base_url, ["Joint"])
    j33 = next((c for c in committees if c.id == "J33"), None)
    if not j33:
        print("J33 not found")
        return
    contact = get_committee_contact(base_url, j33)
    print(f"{contact.name}")
    print(f"  Room:    {contact.room}")
    print(f"  Address: {contact.address}")
    print(f"  Phone:   {contact.phone}")
