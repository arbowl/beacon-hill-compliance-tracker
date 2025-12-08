# Unit Tests for Beacon Hill Compliance Tracker

This directory contains comprehensive unit tests for the compliance tracking system.

## Structure

```
unit/
├── conftest.py                    # Pytest fixtures and configuration
├── fixtures/
│   ├── __init__.py                # Test enums (Requirement, Committee, etc.)
│   ├── bill_factory.py            # Factory for creating test bills
│   ├── timeline_factory.py        # Factory for creating test timelines
│   ├── date_helpers.py            # Date utilities for testing
│   └── real_bills.yaml            # Real bill URLs for integration tests
├── test_compliance_rules.py       # Individual rule tests
├── test_compliance_integration.py # End-to-end compliance tests
├── test_timeline.py               # Timeline parsing tests
├── test_deadline_calculation.py   # Deadline computation tests
├── test_notice_requirements.py    # Notice gap edge cases
└── test_real_bills.py             # Tests against live URLs
```

## Running Tests

### Run all tests
```bash
pytest unit/
```

### Run specific test file
```bash
pytest unit/test_compliance_rules.py
```

### Run specific test class
```bash
pytest unit/test_compliance_rules.py::TestNoticeRequirementRule
```

### Run specific test
```bash
pytest unit/test_compliance_rules.py::TestNoticeRequirementRule::test_adequate_notice_joint_committee
```

### Run with verbose output
```bash
pytest unit/ -v
```

### Skip slow integration tests
```bash
pytest unit/ -m "not slow"
```

### Run only integration tests
```bash
pytest unit/ -m integration
```

### Run with coverage
```bash
pytest unit/ --cov=components --cov=timeline --cov=collectors
```

## Using the Factories

### Creating Test Bills

```python
from unit.fixtures.bill_factory import BillFactory
from unit.fixtures import Requirement

# Create a fully compliant bill
status, summary, votes = BillFactory.create_complete_compliant_bill(
    bill_id="H100",
    committee_id="J33"
)

# Create a non-compliant bill with specific missing requirements
status, summary, votes = BillFactory.create_noncompliant_bill(
    bill_id="H100",
    missing=[Requirement.VOTES, Requirement.SUMMARY]
)

# Create custom bill status
status = BillFactory.create_status(
    bill_id="H100",
    committee_id="J33",
    hearing_date=date(2025, 7, 15),
    reported_date=date(2025, 9, 1),
    announcement_date=date(2025, 7, 1),
)
```

### Creating Test Timelines

```python
from unit.fixtures.timeline_factory import TimelineFactory
from timeline.models import ActionType

# Create a simple timeline
timeline = TimelineFactory.create_simple_timeline(
    bill_id="H100",
    committee_id="J33"
)

# Create a complex timeline with multiple committees
timeline = TimelineFactory.create_complex_timeline(
    bill_id="H100",
    committee_transitions=[
        ("J33", date(2025, 1, 1), date(2025, 3, 1)),
        ("J10", date(2025, 3, 1), date(2025, 5, 1)),
    ]
)

# Create individual actions
action = TimelineFactory.create_action(
    date(2025, 1, 15),
    ActionType.REPORTED,
    committee_id="J33"
)
```

### Using Date Scenarios

```python
from unit.fixtures.date_helpers import DateScenarios

# Get pre-configured date scenarios
announcement, hearing = DateScenarios.adequate_joint_notice()  # 10+ days
announcement, hearing = DateScenarios.inadequate_joint_notice()  # <10 days
announcement, hearing = DateScenarios.before_notice_requirement()  # Exempt
```

## Test Markers

Tests are marked with pytest markers for selective execution:

- `@pytest.mark.integration` - Tests that hit external services
- `@pytest.mark.slow` - Tests that take significant time
- `@pytest.mark.unit` - Fast unit tests (default)

## Fixtures

### bill_factory
Provides `BillFactory` instance for creating test bills.

### timeline_factory
Provides `TimelineFactory` instance for creating test timelines.

### date_scenarios
Provides `DateScenarios` instance with pre-configured date scenarios.

### real_bills
Loads real bill test cases from `real_bills.yaml`.

### mock_today
Allows tests to control the "current date" for deadline calculations.

## Writing New Tests

1. Import the appropriate factories and enums
2. Use factories to create test data
3. Call the function/class being tested
4. Assert expected results

Example:

```python
from unit.fixtures import Requirement, Committee
from components.ruleset import classify
from components.compliance import ComplianceState

def test_my_scenario(bill_factory):
    # Create test data
    status, summary, votes = bill_factory.create_noncompliant_bill(
        missing=[Requirement.VOTES]
    )
    
    # Test the function
    result = classify("H100", Committee.JOINT.value, status, summary, votes)
    
    # Assert results
    assert result.state == ComplianceState.INCOMPLETE
    assert "no votes" in result.reason.lower()
```