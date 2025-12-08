# Suspicious Hearing Notices - Quick Start Guide

## The Problem

Your screenshot shows Bill S1249 with these actions:
- **11/14/2025**: Hearing scheduled for 11/25 (11 days notice ✓)
- **11/25/2025**: Hearing time changed (0 days notice ⚠️)
- **11/26/2025**: Hearing rescheduled to 11/25 (-1 days notice ⚠️)

**Question:** Is this a clerical correction or a violation?

**Answer:** We can't know algorithmically. That's why we built this system.

## Quick Setup (5 minutes)

### 1. Install Dependencies (if needed)

```bash
pip install rich  # For better terminal UI (optional but recommended)
```

### 2. Run Compliance Tracker Normally

The detection system is now integrated. Just run your normal compliance checks:

```bash
python app.py --one-run
```

Suspicious cases are automatically logged to `out/suspicious_notices.jsonl`

### 3. Check What Was Detected

```bash
python tools/aggregate_suspicious_notices.py --summary
```

This shows how many cases were found and groups them by pattern.

## First Review Session (20-30 minutes)

### 1. Start the Review Tool

```bash
python tools/review_suspicious_notices.py --reviewer "your_name"
```

### 2. Review Cases

For each case, you'll see:
- Bill details
- Timeline of hearing actions
- Prior valid notice (if exists)
- The problematic action highlighted

**Your job:** Decide if it's clerical or a violation

**Example Decision Tree:**

```
Did the committee provide valid notice initially (10+ days)?
├─ YES
│  └─ Is the suspicious action updating time/location/virtual?
│     ├─ YES → Probably CLERICAL ✓
│     └─ NO → Review more carefully
└─ NO → Probably VIOLATION ✗
```

### 3. Use Batch Operations

After reviewing 3-5 similar cases:
- Press **[G]** to apply the same decision to all similar cases
- This speeds up review dramatically

### 4. Save and Exit Anytime

Press **[Q]** to quit. Progress is saved automatically.

## After Reviewing ~50 Cases

### Generate Patterns

```bash
python tools/analyze_clerical_patterns.py --summary
```

This creates `config/clerical_patterns.json` with patterns that have ≥85% confidence.

### Next Run

Future compliance runs will automatically:
- Detect suspicious cases (as before)
- Check against your patterns
- Auto-whitelist high-confidence matches
- Only flag truly ambiguous cases

## Real-World Example

### Case: Bill S1249 (from your screenshot)

**Timeline:**
1. **11/14/2025**: Hearing scheduled for 11/25, 10:00 AM-05:00 PM, Room A-2
2. **11/25/2025**: "Hearing updated to New End Time" (same day)
3. **11/26/2025**: "Hearing rescheduled to 11/25/2025 from 10:00 AM-04:00 PM in A-2 and Virtual"

**Analysis:**
- ✓ Had prior valid notice (11 days)
- ✓ Same-day time change (likely hearing finished early)
- ✓ Retroactive "reschedule" added next day
- ✓ Just updated end time (5PM → 4PM) and added "Virtual"

**Expert Decision:** CLERICAL

**Reasoning:** Committee provided proper 11-day notice. Hearing ran shorter than expected (finished at 4PM instead of 5PM). Staff updated the record the next day to reflect what actually happened.

**Pattern:** This would contribute to "Retroactive time-shortened same-day correction" pattern.

## Common Patterns You'll See

### Pattern 1: Time Shortened
- **Signal:** Hearing scheduled for X hours, actually ran shorter
- **Evidence:** Same-day time change, retroactive reschedule 0-2 days later
- **Decision:** Usually CLERICAL

### Pattern 2: Virtual Added
- **Signal:** In-person hearing announced, virtual option added same-day
- **Evidence:** Text contains "virtual", no time/location change
- **Decision:** Usually CLERICAL (especially post-COVID)

### Pattern 3: Room Changed
- **Signal:** Announced for Room A-1, held in Room A-2
- **Evidence:** Location text changed, no time change
- **Decision:** Usually CLERICAL

### Pattern 4: No Prior Notice
- **Signal:** First hearing action is same-day or retroactive
- **Evidence:** No earlier announcement in timeline
- **Decision:** Usually VIOLATION

## Tips for Effective Review

### 1. Start with High-Volume Groups
The aggregation tool sorts by frequency. Review the most common patterns first.

### 2. Look for Prior Valid Notice
This is the #1 indicator of clerical vs. violation:
- **Prior valid notice → likely clerical**
- **No prior notice → likely violation**

### 3. Use Pattern Recognition
After 3-5 similar cases, use [G] to apply to the whole group.

### 4. Add Notes for Ambiguous Cases
Press [N] to add a note before deciding. This helps when generating patterns later.

### 5. Don't Rush
It's better to skip ([S]) and come back than to make hasty decisions.

## Maintenance

### Quarterly Review
Every 3 months:
1. Check pattern effectiveness
2. Review any violations that matched "clerical" patterns
3. Adjust confidence thresholds if needed

### Disable Problematic Patterns
If a pattern starts matching violations:

```json
{
  "id": "pattern_003",
  "enabled": false,  // ← Set to false
  "confidence": 0.92,
  ...
}
```

### Re-run Analysis
After more reviews:

```bash
python tools/analyze_clerical_patterns.py --min-confidence 0.90 --summary
```

Higher confidence = stricter patterns = fewer false negatives

## Troubleshooting

### "No suspicious notices found"
✓ Run compliance tracker first: `python app.py --one-run`
✓ Check `out/suspicious_notices.jsonl` exists

### "Rich module not found"
✓ Install: `pip install rich`
✓ Or: Tool works without it (basic interface)

### Patterns not applying
✓ Check `config/clerical_patterns.json` exists
✓ Verify patterns are `"enabled": true`
✓ Check logs for pattern matching attempts

## Command Cheat Sheet

```bash
# 1. Run compliance tracker (detects cases automatically)
python app.py --one-run

# 2. See what was detected
python tools/aggregate_suspicious_notices.py --summary

# 3. Review cases
python tools/review_suspicious_notices.py --reviewer "your_name"

# 4. Generate patterns (after ~50 reviews)
python tools/analyze_clerical_patterns.py --summary

# 5. Check patterns
cat config/clerical_patterns.json
```

## Success Metrics

After implementing this system, you should see:

1. **Fewer false positives**: Bills with valid prior notice won't be flagged for clerical updates
2. **Audit trail**: Complete log of all suspicious cases and decisions
3. **Expert efficiency**: Review 100+ cases in 30 minutes (vs. hours manually)
4. **Pattern learning**: System gets smarter as you review more cases
5. **Transparency**: Every auto-whitelist is logged and auditable

## Next Steps

1. Run your first compliance check
2. Review the first 20 cases to get a feel for patterns
3. After 50 reviews, generate initial patterns
4. Monitor pattern effectiveness over next few runs
5. Adjust confidence thresholds as needed

## Questions?

See the full documentation: `unit/suspicious_notices_README.md`

Or check the code:
- Detection: `collectors/bill_status_basic.py` (lines 143-173)
- Models: `components/suspicious_notices.py`
- Tools: `tools/*.py`

