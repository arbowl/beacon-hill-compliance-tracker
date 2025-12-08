"""Tests for suspicious hearing notices detection and review system."""

import json
from datetime import date, timedelta
from pathlib import Path
import tempfile

import pytest

from components.suspicious_notices import (
    SuspiciousHearingNotice,
    SuspiciousNoticeLogger,
    ClericalPattern,
    compute_signature,
    should_whitelist_as_clerical,
)


class TestSuspiciousHearingNotice:
    """Tests for SuspiciousHearingNotice data model."""
    
    def test_create_basic_notice(self):
        """Test creating a basic suspicious notice."""
        notice = SuspiciousHearingNotice(
            bill_id="S1249",
            committee_id="J19",
            session="194",
            bill_url="https://malegislature.gov/Bills/194/S1249",
            announcement_date=date(2025, 11, 26),
            scheduled_hearing_date=date(2025, 11, 25),
            notice_days=-1,
            action_type="HEARING_RESCHEDULED",
            raw_action_text="Hearing rescheduled to 11/25/2025",
        )
        
        assert notice.bill_id == "S1249"
        assert notice.notice_days == -1
        assert notice.action_type == "HEARING_RESCHEDULED"
    
    def test_to_dict_and_from_dict(self):
        """Test serialization round-trip."""
        notice = SuspiciousHearingNotice(
            bill_id="H2391",
            committee_id="J33",
            session="194",
            bill_url="https://malegislature.gov/Bills/194/H2391",
            announcement_date=date(2025, 11, 26),
            scheduled_hearing_date=date(2025, 11, 25),
            notice_days=-1,
            action_type="HEARING_RESCHEDULED",
            raw_action_text="Hearing rescheduled",
            had_prior_announcement=True,
            prior_best_notice_days=11,
        )
        
        # Convert to dict
        data = notice.to_dict()
        assert data["bill_id"] == "H2391"
        assert data["notice_days"] == -1
        assert isinstance(data["announcement_date"], str)
        
        # Convert back
        restored = SuspiciousHearingNotice.from_dict(data)
        assert restored.bill_id == notice.bill_id
        assert restored.notice_days == notice.notice_days
        assert restored.announcement_date == notice.announcement_date


class TestSuspiciousNoticeLogger:
    """Tests for logging suspicious notices."""
    
    def test_log_and_load(self):
        """Test logging and loading notices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test_notices.jsonl"
            logger = SuspiciousNoticeLogger(str(log_path))
            
            # Create and log a notice
            notice = SuspiciousHearingNotice(
                bill_id="S1249",
                committee_id="J19",
                session="194",
                bill_url="https://example.com",
                announcement_date=date(2025, 11, 26),
                scheduled_hearing_date=date(2025, 11, 25),
                notice_days=-1,
                action_type="HEARING_RESCHEDULED",
                raw_action_text="Test",
            )
            
            logger.log(notice)
            
            # Verify file exists
            assert log_path.exists()
            
            # Load and verify
            loaded = logger.load_all()
            assert len(loaded) == 1
            assert loaded[0].bill_id == "S1249"
            assert loaded[0].notice_days == -1
    
    def test_multiple_logs(self):
        """Test logging multiple notices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test_notices.jsonl"
            logger = SuspiciousNoticeLogger(str(log_path))
            
            # Log multiple notices
            for i in range(5):
                notice = SuspiciousHearingNotice(
                    bill_id=f"H{i}",
                    committee_id="J19",
                    session="194",
                    bill_url=f"https://example.com/H{i}",
                    announcement_date=date(2025, 11, 26),
                    scheduled_hearing_date=date(2025, 11, 25),
                    notice_days=-1,
                    action_type="HEARING_RESCHEDULED",
                    raw_action_text="Test",
                )
                logger.log(notice)
            
            # Load and verify
            loaded = logger.load_all()
            assert len(loaded) == 5
            assert loaded[0].bill_id == "H0"
            assert loaded[4].bill_id == "H4"


class TestSignatureComputation:
    """Tests for signature computation."""
    
    def test_retroactive_signature(self):
        """Test signature for retroactive case."""
        notice = SuspiciousHearingNotice(
            bill_id="S1249",
            committee_id="J19",
            session="194",
            bill_url="https://example.com",
            announcement_date=date(2025, 11, 26),
            scheduled_hearing_date=date(2025, 11, 25),
            notice_days=-1,
            action_type="HEARING_RESCHEDULED",
            raw_action_text="Hearing rescheduled",
            had_prior_announcement=True,
            prior_best_notice_days=11,
            all_hearing_actions=[],
        )
        
        sig = compute_signature(notice)
        
        assert sig["is_retroactive"] is True
        assert sig["is_same_day"] is False
        assert sig["notice_category"] == "retroactive_1_day"
        assert sig["had_prior_valid_notice"] is True
        assert sig["prior_notice_days"] == 11
    
    def test_same_day_signature(self):
        """Test signature for same-day case."""
        notice = SuspiciousHearingNotice(
            bill_id="H2391",
            committee_id="J33",
            session="194",
            bill_url="https://example.com",
            announcement_date=date(2025, 11, 25),
            scheduled_hearing_date=date(2025, 11, 25),
            notice_days=0,
            action_type="HEARING_RESCHEDULED",
            raw_action_text="Hearing rescheduled with virtual option",
            had_prior_announcement=True,
            prior_best_notice_days=15,
            all_hearing_actions=[],
        )
        
        sig = compute_signature(notice)
        
        assert sig["is_same_day"] is True
        assert sig["is_retroactive"] is False
        assert sig["notice_category"] == "same_day"
        assert sig["text_contains_virtual"] is True


class TestClericalPattern:
    """Tests for clerical pattern matching."""
    
    def test_pattern_matches_exact(self):
        """Test exact pattern matching."""
        pattern = ClericalPattern(
            id="test_001",
            name="Test Pattern",
            confidence=0.90,
            sample_size=20,
            criteria={
                "notice_days": -1,
                "action_type": "HEARING_RESCHEDULED",
                "had_prior_valid_notice": True,
            }
        )
        
        # Matching signature
        sig = {
            "notice_days": -1,
            "action_type": "HEARING_RESCHEDULED",
            "had_prior_valid_notice": True,
        }
        assert pattern.matches(sig) is True
        
        # Non-matching signature
        sig2 = {
            "notice_days": -1,
            "action_type": "HEARING_SCHEDULED",
            "had_prior_valid_notice": True,
        }
        assert pattern.matches(sig2) is False
    
    def test_pattern_matches_range(self):
        """Test pattern matching with ranges."""
        pattern = ClericalPattern(
            id="test_002",
            name="Range Pattern",
            confidence=0.85,
            sample_size=15,
            criteria={
                "notice_days": {"min": -2, "max": 0},
                "prior_notice_days": {"min": 10},
            }
        )
        
        # In range
        assert pattern.matches({"notice_days": -1, "prior_notice_days": 11}) is True
        assert pattern.matches({"notice_days": 0, "prior_notice_days": 10}) is True
        
        # Out of range
        assert pattern.matches({"notice_days": -3, "prior_notice_days": 11}) is False
        assert pattern.matches({"notice_days": -1, "prior_notice_days": 9}) is False
    
    def test_pattern_matches_list(self):
        """Test pattern matching with list criteria."""
        pattern = ClericalPattern(
            id="test_003",
            name="List Pattern",
            confidence=0.88,
            sample_size=25,
            criteria={
                "action_type": ["HEARING_RESCHEDULED", "HEARING_TIME_CHANGED"],
            }
        )
        
        assert pattern.matches({"action_type": "HEARING_RESCHEDULED"}) is True
        assert pattern.matches({"action_type": "HEARING_TIME_CHANGED"}) is True
        assert pattern.matches({"action_type": "HEARING_SCHEDULED"}) is False


class TestWhitelisting:
    """Tests for whitelist matching."""
    
    def test_should_whitelist_high_confidence(self):
        """Test whitelisting with high confidence pattern."""
        notice = SuspiciousHearingNotice(
            bill_id="S1249",
            committee_id="J19",
            session="194",
            bill_url="https://example.com",
            announcement_date=date(2025, 11, 26),
            scheduled_hearing_date=date(2025, 11, 25),
            notice_days=-1,
            action_type="HEARING_RESCHEDULED",
            raw_action_text="Hearing rescheduled",
            had_prior_announcement=True,
            prior_best_notice_days=11,
            all_hearing_actions=[],
        )
        
        # Create a matching pattern
        patterns = [
            ClericalPattern(
                id="pattern_001",
                name="Retroactive correction",
                confidence=0.95,
                sample_size=50,
                criteria={
                    "notice_days": {"min": -2, "max": 0},
                    "action_type": ["HEARING_RESCHEDULED"],
                    "had_prior_valid_notice": True,
                    "prior_notice_days": {"min": 10},
                }
            )
        ]
        
        should_whitelist, pattern_id = should_whitelist_as_clerical(
            notice, patterns, min_confidence=0.85
        )
        
        assert should_whitelist is True
        assert pattern_id == "pattern_001"
    
    def test_should_not_whitelist_low_confidence(self):
        """Test not whitelisting with low confidence."""
        notice = SuspiciousHearingNotice(
            bill_id="H2391",
            committee_id="J33",
            session="194",
            bill_url="https://example.com",
            announcement_date=date(2025, 11, 25),
            scheduled_hearing_date=date(2025, 11, 25),
            notice_days=0,
            action_type="HEARING_RESCHEDULED",
            raw_action_text="Test",
            had_prior_announcement=False,
            all_hearing_actions=[],
        )
        
        # Pattern doesn't match (no prior notice)
        patterns = [
            ClericalPattern(
                id="pattern_001",
                name="Requires prior notice",
                confidence=0.95,
                sample_size=50,
                criteria={
                    "had_prior_valid_notice": True,
                }
            )
        ]
        
        should_whitelist, pattern_id = should_whitelist_as_clerical(
            notice, patterns, min_confidence=0.85
        )
        
        assert should_whitelist is False
    
    def test_disabled_pattern_not_applied(self):
        """Test that disabled patterns are not applied."""
        notice = SuspiciousHearingNotice(
            bill_id="S1249",
            committee_id="J19",
            session="194",
            bill_url="https://example.com",
            announcement_date=date(2025, 11, 26),
            scheduled_hearing_date=date(2025, 11, 25),
            notice_days=-1,
            action_type="HEARING_RESCHEDULED",
            raw_action_text="Test",
            had_prior_announcement=True,
            all_hearing_actions=[],
        )
        
        # Matching but disabled pattern
        patterns = [
            ClericalPattern(
                id="pattern_001",
                name="Disabled pattern",
                confidence=0.95,
                sample_size=50,
                enabled=False,  # Disabled
                criteria={
                    "notice_days": {"min": -2, "max": 0},
                }
            )
        ]
        
        should_whitelist, pattern_id = should_whitelist_as_clerical(
            notice, patterns, min_confidence=0.85
        )
        
        assert should_whitelist is False


class TestIntegration:
    """Integration tests for the full workflow."""
    
    def test_full_workflow(self):
        """Test complete workflow: detect → log → load → match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "notices.jsonl"
            logger = SuspiciousNoticeLogger(str(log_path))
            
            # 1. Create and log a suspicious notice
            notice = SuspiciousHearingNotice(
                bill_id="S1249",
                committee_id="J19",
                session="194",
                bill_url="https://malegislature.gov/Bills/194/S1249",
                announcement_date=date(2025, 11, 26),
                scheduled_hearing_date=date(2025, 11, 25),
                notice_days=-1,
                action_type="HEARING_RESCHEDULED",
                raw_action_text="Hearing rescheduled to 11/25/2025",
                had_prior_announcement=True,
                prior_best_notice_days=11,
                all_hearing_actions=[
                    {
                        "announcement_date": "2025-11-14",
                        "hearing_date": "2025-11-25",
                        "action_type": "HEARING_SCHEDULED",
                        "notice_days": 11,
                    },
                    {
                        "announcement_date": "2025-11-26",
                        "hearing_date": "2025-11-25",
                        "action_type": "HEARING_RESCHEDULED",
                        "notice_days": -1,
                    },
                ],
            )
            
            logger.log(notice)
            
            # 2. Load and verify
            loaded_notices = logger.load_all()
            assert len(loaded_notices) == 1
            loaded = loaded_notices[0]
            
            # 3. Compute signature
            sig = compute_signature(loaded)
            assert sig["is_retroactive"] is True
            assert sig["had_prior_valid_notice"] is True
            
            # 4. Check against pattern
            patterns = [
                ClericalPattern(
                    id="pattern_001",
                    name="Retroactive correction with prior notice",
                    confidence=0.95,
                    sample_size=42,
                    criteria={
                        "is_retroactive": True,
                        "had_prior_valid_notice": True,
                        "prior_notice_days": {"min": 10},
                    }
                )
            ]
            
            should_whitelist, pattern_id = should_whitelist_as_clerical(
                loaded, patterns, min_confidence=0.85
            )
            
            assert should_whitelist is True
            assert pattern_id == "pattern_001"

