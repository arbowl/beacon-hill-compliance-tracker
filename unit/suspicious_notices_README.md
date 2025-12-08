# Suspicious Hearing Notices Detection & Review System

## Overview

This system addresses a critical ambiguity in compliance tracking: **same-day and retroactive hearing reschedules** that may be either:

1. **Clerical corrections** - Staff updating records after-the-fact to reflect what actually happened (NOT a violation)
2. **Actual violations** - Committee genuinely rescheduling without proper notice (IS a violation)

The system cannot algorithmically distinguish between these cases because they look identical in the public-facing data. Therefore, we:

- **Detect and log** all suspicious cases
- **Provide tools** for domain experts to review and classify them
- **Learn patterns** from expert decisions
- **Auto-whitelist** high-confidence clerical patterns in future runs

## Architecture

### 1. Detection & Logging (`components/suspicious_notices.py`)

**Detection happens in `collectors/bill_status_basic.py`** when processing bill timelines:

```python
if notice_days < MINIMUM_ACCEPTABLE_NOTICE:  # < 3 days
    detect_and_log_suspicious_notice(...)
```

**Each suspicious case is logged to** `out/suspicious_notices.jsonl` with:
- Bill and committee identifiers
- The problematic hearing action (0 or negative days notice)
- Prior announcement context (if exists)
- Full timeline of hearing actions
- Computed signature for pattern matching
- Whitelist status (if matched a known pattern)

### 2. Dataset Aggregation (`tools/aggregate_suspicious_notices.py`)

Groups logged cases by signature patterns for efficient batch review:

```bash
python tools/aggregate_suspicious_notices.py --summary
```

**Output:** `review/pending_notices.json` - Cases organized by similar characteristics

### 3. Interactive Review (`tools/review_suspicious_notices.py`)

Terminal-based UI for domain experts to quickly classify cases:

```bash
python tools/review_suspicious_notices.py --reviewer "analyst_name"
```

**Features:**
- Visual timeline showing hearing actions
- Context highlighting (prior valid notices)
- Batch operations (apply decision to all similar cases)
- Immediate export (no need to complete in one sitting)
- Resume support

**Output:** `review/completed_reviews.jsonl` - One line per reviewed case

### 4. Pattern Analysis (`tools/analyze_clerical_patterns.py`)

Learns patterns from expert reviews and generates whitelist:

```bash
python tools/analyze_clerical_patterns.py --min-confidence 0.85 --summary
```

**Output:** `config/clerical_patterns.json` - Patterns with ≥85% confidence

### 5. Whitelisting (Automatic)

When processing bills, the system automatically:
1. Detects suspicious notice
2. Computes signature
3. Checks against whitelist patterns
4. If matched with high confidence, uses prior valid notice instead
5. Still logs the case for audit trail

## Workflow

### Initial Setup (One-Time)

1. Run the compliance tracker normally
2. Suspicious cases are automatically logged to `out/suspicious_notices.jsonl`
3. Aggregate the logs:
   ```bash
   python tools/aggregate_suspicious_notices.py --summary
   ```

### Review Session

1. Start the review tool:
   ```bash
   python tools/review_suspicious_notices.py --reviewer "your_name"
   ```

2. For each case, decide:
   - **[C]lerical** - Not a violation, just a record correction
   - **[V]iolation** - Actual compliance violation
   - **[G]roup** - Apply decision to all similar cases
   - **[S]kip** - Come back later
   - **[Q]uit** - Save and exit

3. Reviews are saved immediately to `review/completed_reviews.jsonl`

### Pattern Generation

After reviewing a substantial batch (50+ cases recommended):

```bash
python tools/analyze_clerical_patterns.py --min-confidence 0.85 --summary
```

This creates/updates `config/clerical_patterns.json`

### Ongoing Operations

Future compliance runs will:
- Automatically detect suspicious cases
- Check against patterns in `config/clerical_patterns.json`
- Auto-whitelist high-confidence matches
- Log everything for audit trail
- Only flag genuinely ambiguous cases for review

## Data Files

### Logs
- `out/suspicious_notices.jsonl` - All detected cases (append-only)

### Review Queue
- `review/pending_notices.json` - Aggregated dataset for review (regenerated)
- `review/completed_reviews.jsonl` - Expert decisions (append-only)

### Configuration
- `config/clerical_patterns.json` - Learned whitelist patterns

## Pattern Structure

A clerical pattern includes:

```json
{
  "id": "pattern_001",
  "name": "Retroactive time-shortened same-day correction",
  "confidence": 0.95,
  "sample_size": 42,
  "enabled": true,
  "criteria": {
    "notice_days": {"min": -2, "max": 0},
    "had_prior_valid_notice": true,
    "prior_notice_days": {"min": 10},
    "had_same_day_time_change": true
  },
  "example_bills": ["S1249", "H2391"]
}
```

**Key Criteria:**
- `notice_days` - Range of notice days
- `had_prior_valid_notice` - Requires valid earlier announcement
- `prior_notice_days` - Minimum prior notice required
- `had_same_day_time_change` - Pattern includes time change
- `text_contains_virtual` - Virtual option mentioned
- `time_between_hearing_and_action` - For retroactive cases

## Safety & Guidelines

### Conservative Approach
> "It's better to fail a bill due to clerical errors than to miscalculate non-compliant bills."

- Patterns require ≥85% confidence (30+ cases at ≥90% recommended)
- All patterns require prior valid notice
- Everything is logged for audit trail
- Patterns can be disabled without deletion
- Periodic re-validation recommended

### Pattern Validation

**Monitor:**
- Pattern application frequency
- New violations matching "clerical" patterns
- Changes in committee behavior

**Re-validate:**
- Quarterly review of pattern effectiveness
- After significant committee policy changes
- If new violation cases match clerical patterns

### Audit Trail

Every application of a pattern is logged:
```python
logger.info(f"Bill {bill_id}: Applying clerical whitelist pattern {pattern_id}")
```

All suspicious cases are logged regardless of whitelist status:
```python
notice.whitelist_pattern_id = pattern_id  # If matched
notice_logger.log(notice)  # Always logged
```

## Example Patterns

### Pattern 1: Retroactive Time Adjustment
**Scenario:** Hearing had valid 11-day notice. On day of hearing, time shortened from 5PM to 4PM. Next day, retroactive "reschedule" action added to correct the record.

**Criteria:**
- -2 to 0 days notice
- Had prior notice ≥10 days
- Same-day time change
- Retroactive within 3 days

**Expert Note:** "Consistently seen with hearings that ran shorter than planned."

### Pattern 2: Virtual Option Added
**Scenario:** Hearing had valid notice for in-person attendance. Same-day or day-after, "reschedule" action adds virtual option without changing time/location.

**Criteria:**
- 0 to -1 days notice
- Had prior notice ≥10 days
- Text contains "virtual"
- No location change

**Expert Note:** "Committee enabled virtual attendance on short notice and updated record."

### Pattern 3: Room Change Correction
**Scenario:** Hearing announced for Room A-1. Actually held in Room A-2. Retroactive correction to match what happened.

**Criteria:**
- -1 to 0 days notice
- Had prior notice ≥10 days
- Text mentions room/location
- No time change

## Command Reference

### Aggregate for Review
```bash
# Basic aggregation
python tools/aggregate_suspicious_notices.py

# With summary
python tools/aggregate_suspicious_notices.py --summary

# Custom paths
python tools/aggregate_suspicious_notices.py \
  --log out/suspicious_notices.jsonl \
  --output review/pending.json
```

### Interactive Review
```bash
# Start review
python tools/review_suspicious_notices.py --reviewer "analyst_name"

# Custom paths
python tools/review_suspicious_notices.py \
  --dataset review/pending_notices.json \
  --output review/completed_reviews.jsonl \
  --reviewer "expert1"
```

### Analyze Patterns
```bash
# Standard analysis
python tools/analyze_clerical_patterns.py --summary

# Strict criteria
python tools/analyze_clerical_patterns.py \
  --min-confidence 0.90 \
  --min-sample-size 10 \
  --summary

# Replace existing patterns (don't merge)
python tools/analyze_clerical_patterns.py --no-merge
```

## Troubleshooting

### No cases detected
- Check `out/suspicious_notices.jsonl` exists
- Verify compliance tracker is running normally
- Confirm threshold: `MINIMUM_ACCEPTABLE_NOTICE = 3` in `collectors/bill_status_basic.py`

### Patterns not applying
- Check `config/clerical_patterns.json` exists
- Verify patterns are `"enabled": true`
- Confirm confidence meets threshold (≥0.85 default)
- Check logs for pattern match attempts

### Review tool issues
- Install rich library: `pip install rich`
- Falls back to basic interface if rich unavailable
- Progress always saved to JSONL, can resume anytime

## Future Enhancements

Potential improvements:

1. **Enhanced signature computation** - More sophisticated pattern matching
2. **Committee-specific patterns** - Different patterns per committee
3. **Temporal analysis** - Seasonal or legislative session patterns
4. **Confidence scoring** - More nuanced confidence calculations
5. **Web interface** - Browser-based review tool
6. **Pattern versioning** - Track pattern evolution over time
7. **Automated alerts** - Flag when violations match "clerical" patterns

## Questions & Support

For questions about:
- **Detection logic**: See `collectors/bill_status_basic.py` (lines 143-173)
- **Signature computation**: See `components/suspicious_notices.py` (`compute_signature` function)
- **Pattern matching**: See `components/suspicious_notices.py` (`should_whitelist_as_clerical` function)
- **Review workflow**: See `tools/review_suspicious_notices.py`

## Credits

Developed as part of the Beacon Hill Compliance Tracker to address the ambiguity between clerical corrections and actual compliance violations in Massachusetts legislative hearing notices.

