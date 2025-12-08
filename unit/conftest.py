"""Pytest configuration and shared fixtures."""

import pytest
import yaml
from pathlib import Path
from datetime import date
from unittest.mock import patch

from unit.fixtures.bill_factory import BillFactory
from unit.fixtures.timeline_factory import TimelineFactory
from unit.fixtures.date_helpers import DateScenarios


@pytest.fixture
def bill_factory():
    """Provide BillFactory instance."""
    return BillFactory()


@pytest.fixture
def timeline_factory():
    """Provide TimelineFactory instance."""
    return TimelineFactory()


@pytest.fixture
def date_scenarios():
    """Provide DateScenarios instance."""
    return DateScenarios()


@pytest.fixture
def real_bills():
    """Load real bill test cases from YAML."""
    yaml_path = Path(__file__).parent / "fixtures" / "real_bills.yaml"
    if yaml_path.exists():
        with open(yaml_path) as f:
            return yaml.safe_load(f)
    return {}


@pytest.fixture
def mock_today():
    """Allow tests to control the 'current date'."""
    def _mock_today(target_date: date):
        """Mock date.today() to return target_date."""
        with patch('components.ruleset.date') as mock_date:
            mock_date.today.return_value = target_date
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            return mock_date
    return _mock_today

