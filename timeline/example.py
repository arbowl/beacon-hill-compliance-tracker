"""Simple example demonstrating timeline extraction usage.

This file shows basic usage patterns for the timeline system.
"""

from timeline import extract_timeline

# Example 1: Extract and query timeline
def example_basic():
    """Basic timeline extraction and querying."""
    bill_url = "https://malegislature.gov/Bills/194/H56"
    bill_id = "H56"
    
    # Extract timeline
    timeline = extract_timeline(bill_url, bill_id)
    
    # Query timeline
    print(f"Total actions: {len(timeline)}")
    print(f"First action: {timeline.actions[0].date}")
    print(f"Last action: {timeline.actions[-1].date}")
    
    # Committee-specific queries
    committee_id = "J10"
    referred_date = timeline.get_referred_date(committee_id)
    reported_date = timeline.get_reported_date(committee_id)
    
    print(f"\nCommittee {committee_id}:")
    print(f"  Referred: {referred_date}")
    print(f"  Reported: {reported_date}")
    
    # Hearing queries
    hearings = timeline.get_hearings(committee_id)
    print(f"  Hearings: {len(hearings)}")
    
    return timeline


# Example 2: Iterate over actions
def example_iteration():
    """Demonstrate iterating over actions."""
    timeline = extract_timeline("https://malegislature.gov/Bills/194/H56", "H56")
    
    # Print all actions
    for action in timeline:
        print(f"{action.date} [{action.branch}] {action.action_type}")
        if action.extracted_data:
            print(f"  Data: {action.extracted_data}")


# Example 3: Filter actions
def example_filtering():
    """Demonstrate filtering actions."""
    timeline = extract_timeline("https://malegislature.gov/Bills/194/H56", "H56")
    
    # Get all referral actions
    referrals = timeline.get_actions_by_type("REFERRED")
    print(f"Referral actions: {len(referrals)}")
    
    # Get all committee-passage category actions
    committee_actions = timeline.get_actions_by_category("committee-passage")
    print(f"Committee passage actions: {len(committee_actions)}")
    
    # Get actions in date range
    from datetime import date
    start = date(2025, 7, 1)
    end = date(2025, 8, 1)
    july_actions = timeline.get_actions_in_range(start, end)
    print(f"Actions in July 2025: {len(july_actions)}")


# Example 4: Integration with existing code
def example_integration(bill_url: str, committee_id: str):
    """Example of how to integrate with existing code."""
    timeline = extract_timeline(bill_url)
    
    # Replace old _reported_out_from_bill_page()
    reported = timeline.has_reported(committee_id)
    reported_date = timeline.get_reported_date(committee_id)
    
    # NEW: Also get referred date
    referred_date = timeline.get_referred_date(committee_id)
    
    # NEW: Get extension deadline
    extension_date = timeline.get_latest_deadline_extension()
    
    return {
        "reported": reported,
        "reported_date": reported_date,
        "referred_date": referred_date,
        "extension_date": extension_date,
    }


# Example 5: Committee compliance metrics for H56
def example_h56_committee_analysis():
    """Analyze H56 for the three committees it was referred to.
    
    Committees:
    - J10: Municipalities and Regional Government
    - J23: Public Service  
    - J26: Revenue
    
    For each committee, calculate:
    - Hearing announcement notice (days between announcement and hearing)
    - Report-out gap after hearing (days from hearing to report-out)
    - Report-out gap after referral (days from referral to report-out)
    """
    from datetime import date, timedelta
    
    bill_url = "https://malegislature.gov/Bills/194/H56"
    bill_id = "H56"
    
    print(f"\n{'='*80}")
    print(f"H56 Committee Compliance Analysis")
    print(f"{'='*80}")
    
    # Extract timeline
    timeline = extract_timeline(bill_url, bill_id)
    
    # Committees from H56
    committees = {
        "J10": "Municipalities and Regional Government",
        "J23": "Public Service",  # J23 is correct (J14 is Education)
        "J26": "Revenue",
    }
    
    # Reference date (when we're checking - use last action date)
    check_date = timeline.actions[-1].date if timeline.actions else date.today()
    
    for committee_id, committee_name in committees.items():
        print(f"\n{'-'*80}")
        print(f"Committee {committee_id}: {committee_name}")
        print(f"{'-'*80}")
        
        # 1. Find referral date
        referred_date = timeline.get_referred_date(committee_id)
        print(f"Referred date: {referred_date or 'NOT FOUND'}")
        
        if not referred_date:
            print("  [WARNING] No referral found for this committee")
            continue
        
        # 2. Find hearing information
        hearings = timeline.get_hearings(committee_id)
        
        if not hearings:
            print(f"Hearings: NONE")
            print(f"  [WARNING] No hearing scheduled yet")
            print(f"  Days since referral: {(check_date - referred_date).days}")
            continue
        
        print(f"Hearings: {len(hearings)}")
        
        # Find the announcement and actual hearing dates
        # Look for the first scheduled hearing and any reschedules
        scheduled_hearings = [h for h in hearings if h.action_type == "HEARING_SCHEDULED"]
        rescheduled_hearings = [h for h in hearings if h.action_type == "HEARING_RESCHEDULED"]
        
        # The actual hearing date is from the latest scheduled/rescheduled action
        all_hearing_actions = scheduled_hearings + rescheduled_hearings
        all_hearing_actions.sort(key=lambda h: h.date)
        
        if not all_hearing_actions:
            print("  [WARNING] Hearing actions found but no dates extracted")
            continue
        
        # First announcement
        first_announcement = all_hearing_actions[0]
        first_announcement_date = first_announcement.date
        first_hearing_date_str = first_announcement.extracted_data.get("hearing_date")
        
        if first_hearing_date_str:
            try:
                first_hearing_date = date.fromisoformat(first_hearing_date_str)
                notice_days_initial = (first_hearing_date - first_announcement_date).days
                print(f"\nInitial hearing announcement:")
                print(f"  Announced: {first_announcement_date}")
                print(f"  Scheduled for: {first_hearing_date}")
                compliant = "[OK]" if notice_days_initial >= 10 else "[NON-COMPLIANT]"
                print(f"  Notice: {notice_days_initial} days {compliant}")
            except (ValueError, TypeError):
                print(f"  [WARNING] Could not parse hearing date: {first_hearing_date_str}")
        
        # Final hearing date (after any reschedules)
        final_hearing_action = all_hearing_actions[-1]
        final_announcement_date = final_hearing_action.date
        final_hearing_date_str = final_hearing_action.extracted_data.get("hearing_date")
        
        if final_hearing_date_str:
            try:
                final_hearing_date = date.fromisoformat(final_hearing_date_str)
                
                if len(all_hearing_actions) > 1:
                    notice_days_final = (final_hearing_date - final_announcement_date).days
                    print(f"\nRescheduled hearing:")
                    print(f"  Announced: {final_announcement_date}")
                    print(f"  Scheduled for: {final_hearing_date}")
                    compliant = "[OK]" if notice_days_final >= 10 else "[NON-COMPLIANT]"
                    print(f"  Notice: {notice_days_final} days {compliant}")
                
                # 3. Check for report-out
                reported_date = timeline.get_reported_date(committee_id)
                
                if reported_date:
                    # Calculate gaps
                    report_gap_after_hearing = (reported_date - final_hearing_date).days
                    report_gap_after_referral = (reported_date - referred_date).days
                    
                    print(f"\nReport-out:")
                    print(f"  Reported date: {reported_date}")
                    compliant = "[OK]" if report_gap_after_hearing <= 60 else "[NON-COMPLIANT]"
                    print(f"  Gap after hearing: {report_gap_after_hearing} days {compliant}")
                    print(f"  Gap after referral: {report_gap_after_referral} days (not used for House bills)")
                else:
                    # No report-out yet
                    days_since_hearing = (check_date - final_hearing_date).days
                    days_since_referral = (check_date - referred_date).days
                    
                    print(f"\nReport-out: NOT YET")
                    print(f"  Days since hearing: {days_since_hearing} (deadline: 60 days)")
                    status = "Within deadline" if days_since_hearing <= 60 else "[WARNING] PAST DEADLINE"
                    print(f"  Status: {status}")
                    print(f"  Days since referral: {days_since_referral}")
                    
            except (ValueError, TypeError):
                print(f"  [WARNING] Could not parse final hearing date: {final_hearing_date_str}")
    
    print(f"\n{'='*80}")


# Example 6: My predictions vs actual extraction
def example_h56_validation():
    """Compare my LLM predictions against what the code extracts."""
    from datetime import date
    
    print(f"\n{'='*80}")
    print(f"H56 Analysis: Predictions vs Extraction")
    print(f"{'='*80}")
    
    # My predictions from analyzing the screenshot
    predictions = {
        "J10": {
            "referred": date(2025, 7, 17),
            "hearing_announcement": date(2025, 8, 1),
            "hearing_date_initial": date(2025, 9, 9),
            "notice_days_initial": 39,
            "reschedule_announcement": date(2025, 8, 21),
            "hearing_date_final": date(2025, 10, 28),
            "notice_days_final": 68,
            "days_since_hearing": 29,  # As of 11/26/2025
            "reported": None,
        },
        "J23": {  # J23 is correct (J14 is Education)
            "referred": date(2025, 7, 17),
            "hearing_announcement": date(2025, 9, 11),
            "hearing_date_initial": date(2025, 9, 22),
            "notice_days_initial": 11,
            "days_since_hearing": 65,  # As of 11/26/2025 - OVER 60 day limit!
            "reported": None,
        },
        "J26": {
            "referred": date(2025, 7, 17),
            "hearing": None,
            "reported": None,
        },
    }
    
    # Extract actual data
    timeline = extract_timeline("https://malegislature.gov/Bills/194/H56", "H56")
    check_date = timeline.actions[-1].date
    
    for committee_id, expected in predictions.items():
        print(f"\n{'-'*80}")
        print(f"Committee {committee_id}")
        print(f"{'-'*80}")
        
        # Extract actual values
        actual_referred = timeline.get_referred_date(committee_id)
        actual_reported = timeline.get_reported_date(committee_id)
        hearings = timeline.get_hearings(committee_id)
        
        # Compare referral date
        print(f"Referred date:")
        print(f"  Expected: {expected['referred']}")
        print(f"  Actual:   {actual_referred}")
        match_symbol = "[MATCH]" if actual_referred == expected['referred'] else "[MISMATCH]"
        print(f"  Match:    {match_symbol}")
        
        if not hearings and expected.get("hearing") is None:
            print(f"Hearings:")
            print(f"  Expected: None")
            print(f"  Actual:   None")
            print(f"  Match:    [MATCH]")
            continue
        
        if hearings:
            # Get hearing dates
            all_hearing_actions = [h for h in hearings if h.action_type in ["HEARING_SCHEDULED", "HEARING_RESCHEDULED"]]
            all_hearing_actions.sort(key=lambda h: h.date)
            
            if all_hearing_actions:
                first_action = all_hearing_actions[0]
                first_announcement = first_action.date
                first_hearing_str = first_action.extracted_data.get("hearing_date")
                first_hearing = date.fromisoformat(first_hearing_str) if first_hearing_str else None
                
                print(f"\nInitial hearing:")
                print(f"  Expected announcement: {expected.get('hearing_announcement')}")
                print(f"  Actual announcement:   {first_announcement}")
                match_symbol = "[MATCH]" if first_announcement == expected.get('hearing_announcement') else "[MISMATCH]"
                print(f"  Match: {match_symbol}")
                
                if first_hearing:
                    print(f"  Expected hearing date: {expected.get('hearing_date_initial')}")
                    print(f"  Actual hearing date:   {first_hearing}")
                    match_symbol = "[MATCH]" if first_hearing == expected.get('hearing_date_initial') else "[MISMATCH]"
                    print(f"  Match: {match_symbol}")
                    
                    notice_days = (first_hearing - first_announcement).days
                    print(f"  Expected notice: {expected.get('notice_days_initial')} days")
                    print(f"  Actual notice:   {notice_days} days")
                    match_symbol = "[MATCH]" if notice_days == expected.get('notice_days_initial') else "[MISMATCH]"
                    print(f"  Match: {match_symbol}")
                
                # Check for reschedule
                if len(all_hearing_actions) > 1:
                    final_action = all_hearing_actions[-1]
                    final_announcement = final_action.date
                    final_hearing_str = final_action.extracted_data.get("hearing_date")
                    final_hearing = date.fromisoformat(final_hearing_str) if final_hearing_str else None
                    
                    print(f"\nFinal hearing (rescheduled):")
                    print(f"  Expected announcement: {expected.get('reschedule_announcement')}")
                    print(f"  Actual announcement:   {final_announcement}")
                    match_symbol = "[MATCH]" if final_announcement == expected.get('reschedule_announcement') else "[MISMATCH]"
                    print(f"  Match: {match_symbol}")
                    
                    if final_hearing:
                        print(f"  Expected hearing date: {expected.get('hearing_date_final')}")
                        print(f"  Actual hearing date:   {final_hearing}")
                        match_symbol = "[MATCH]" if final_hearing == expected.get('hearing_date_final') else "[MISMATCH]"
                        print(f"  Match: {match_symbol}")
                        
                        if expected.get('notice_days_final'):
                            notice_days = (final_hearing - final_announcement).days
                            print(f"  Expected notice: {expected.get('notice_days_final')} days")
                            print(f"  Actual notice:   {notice_days} days")
                            match_symbol = "[MATCH]" if notice_days == expected.get('notice_days_final') else "[MISMATCH]"
                            print(f"  Match: {match_symbol}")
                        
                        # Days since hearing
                        days_since = (check_date - final_hearing).days
                        print(f"\nDays since hearing (as of {check_date}):")
                        print(f"  Expected: {expected.get('days_since_hearing')} days")
                        print(f"  Actual:   {days_since} days")
                        match_symbol = "[MATCH]" if days_since == expected.get('days_since_hearing') else "[MISMATCH]"
                        print(f"  Match: {match_symbol}")
    
    print(f"\n{'='*80}")
    print("Analysis Summary:")
    print("  - If matches are [MATCH], the extraction is working correctly")
    print("  - If matches are [MISMATCH], either:")
    print("    1. My prediction was wrong (screenshot interpretation error)")
    print("    2. The extraction has a bug (pattern matching issue)")
    print("    3. Date parsing is incorrect (format issue)")
    print(f"{'='*80}")


if __name__ == "__main__":
    print("Timeline System Examples")
    print("=" * 60)
    
    print("\nExample 1: Basic Usage")
    print("-" * 60)
    example_basic()
    
    print("\n\nExample 2: Iteration")
    print("-" * 60)
    example_iteration()
    
    print("\n\nExample 3: Filtering")
    print("-" * 60)
    example_filtering()
    
    print("\n\nExample 4: Integration")
    print("-" * 60)
    result = example_integration(
        "https://malegislature.gov/Bills/194/H56",
        "J10"
    )
    print(f"Integration result: {result}")
    
    print("\n\nExample 5: H56 Committee Analysis")
    print("-" * 60)
    example_h56_committee_analysis()
    
    print("\n\nExample 6: H56 Predictions vs Extraction")
    print("-" * 60)
    example_h56_validation()

