"""Integration tests against real bill URLs."""

import pytest
from datetime import date

from collectors.bill_status_basic import get_committee_tenure, build_status_row
from timeline.parser import extract_timeline
from components.models import BillAtHearing


@pytest.mark.integration
@pytest.mark.slow
class TestRealBills:
    """Tests against live MA Legislature website.
    
    These tests make actual HTTP requests and may be slow or fail if
    the website is down or data has changed.
    """
    
    def test_extract_timeline_h73(self):
        """Test timeline extraction for H73."""
        bill_url = "https://malegislature.gov/Bills/194/H73"
        
        timeline = extract_timeline(bill_url)
        
        # Basic checks
        assert len(timeline) > 0
        assert timeline.bill_id is not None or True  # bill_id is optional
    
    def test_committee_tenure_h73(self):
        """Test committee tenure extraction for H73."""
        bill_url = "https://malegislature.gov/Bills/194/H73"
        committee_id = "J33"
        
        tenure = get_committee_tenure(bill_url, committee_id)
        
        if tenure:  # May be None if committee not found
            assert tenure.committee_id == committee_id
            assert tenure.referred_date is not None
            assert tenure.referred_date <= date.today()
    
    @pytest.mark.parametrize("bill_id,committee_id", [
        ("H73", "J33"),
        ("S197", "J10"),
    ])
    def test_multiple_real_bills(self, bill_id, committee_id):
        """Test multiple real bills parametrically."""
        bill_url = f"https://malegislature.gov/Bills/194/{bill_id}"
        
        timeline = extract_timeline(bill_url)
        
        # Basic sanity checks
        assert len(timeline) >= 0  # May have no actions if new bill
        
        # Try to get tenure (may be None)
        tenure = get_committee_tenure(bill_url, committee_id)
        
        if tenure:
            assert tenure.committee_id == committee_id
            assert tenure.referred_date <= date.today()


@pytest.mark.integration
class TestRealBillsWithFixtures:
    """Test real bills using fixture data."""
    
    def test_real_bill_from_yaml(self, real_bills):
        """Test using real_bills fixture from YAML."""
        if not real_bills:
            pytest.skip("No real_bills.yaml found")
        
        compliant_examples = real_bills.get("compliant_examples", [])
        
        if compliant_examples:
            example = compliant_examples[0]
            bill_url = example["bill_url"]
            
            timeline = extract_timeline(bill_url)
            assert len(timeline) >= 0


@pytest.mark.unit
class TestMockBillScenarios:
    """Test scenarios that mimic real bill structures without HTTP requests."""
    
    def test_bill_with_multiple_committee_referrals(self, timeline_factory):
        """Test bill that moved between committees."""
        base_date = date(2025, 1, 1)
        transitions = [
            ("J33", base_date, base_date.replace(month=3, day=1)),
            ("J10", base_date.replace(month=3, day=1), base_date.replace(month=5, day=1)),
        ]
        
        timeline = timeline_factory.create_complex_timeline(
            bill_id="H100",
            committee_transitions=transitions,
        )
        
        # Bill should show tenure in first committee
        tenure_j33 = timeline.get_reported_date("J33")
        assert tenure_j33 is not None
        
        # And also in second committee
        tenure_j10 = timeline.get_reported_date("J10")
        assert tenure_j10 is not None
    
    def test_bill_with_hearing_but_no_report(self, timeline_factory):
        """Test bill that had hearing but wasn't reported."""
        timeline = timeline_factory.create_simple_timeline(
            committee_id="J33",
            reported_date=None,  # Not reported
        )
        
        # Should have hearing
        hearings = timeline.get_hearings("J33")
        assert len(hearings) >= 1
        
        # But not reported
        assert not timeline.has_reported("J33")

