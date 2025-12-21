# Changelog

All notable changes to the Beacon Hill Compliance Tracker will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.2] - 2025-12-13

### Added
- New logic for differentiating between "hearing announced", "hearing rescheduled", "hearing time changed", and "hearing location changed" with sub-conditions for evaluating a bill's chain of custody within a committee tenure window.

### Changed
- Clerical timeline updates (such as retroactive end-time adjustments to reflect the record as it happened) will not count as hearing reannouncements that reset the hearing notice timer. Reschedules without original announcements will count as non-compliant.
- Per a functional reading of the Joint Rules, changes to the hearing location and/or time (but not the date) are allowed outside of a 72-hour window prior to the hearing; material changes to the format of a hearing within that window will count as non-compliant.


## [1.2.1] - 2025-12-07

### Changed
- The reason audit log for individual bill non-compliance will now list all valid non-compliance factors within the given deadline window, rather than just deal-breakers (such as hearing notice). This only affects display text, not compliance logic or user-facing presence checks.


## [1.2.0] - 2025-12-05

### Added
- New timeline engine for stricter report-out, hearing, and referral parsing.
- Smarter deadline compliance inference and calculation.
- Report-out compliance logic now bundles the reported-out date alongside the binary presence check, which will enrich datasets, unlock additional insights, and allow for future UI elements.
- Expanding report-out logic to be conscious of rules-based deadlines beyond basic 60/90 day compliance by incorporating October, December, January, and March deadlines as prescribed in Joint Rules for 2026 preparedness.
- Added support for vote date detection, allowing further compliance granularity checking (not yet counted for compliance)

### Deprecated
- Old bill action parser which handled report-outs, hearing announcements, and hearing date anchors.

### Fixed
- Carved out report-out deadline exception for the Joint Committee on Health Care Financing based on Joint Rule 19.


## [1.1.10] - 2025-11-21

### Changed
- Hearing notice compliance calculations will only revolve around announcements, rather than using known hearing dates as a fallback, to better align with the principle of citizens' being properly alerted of hearings.

### Fixed
- Improved reported-out parsing in cases where bills were reported out of many committees and heard multiple times (addressess some edge cases, but negligible overall impact on compliance percentage).
- Improved hearing notice assignments when bills have had multiple hearings and hearing reschedules.


## [1.1.9] - 2025-11-20

### Added
- I added a RULESET194.md file to the GitHub repo for plain-English auditiability of the current Session's ruleset. Binary compliance checks aren't subjective, but categorization of ambiguous or incomplete data demands a common, transparent rationale.

### Changed
- Reported-out logic didn't change, but the dictintion between "no action", "on-time action", "late action", and "date-uncertain action" did not properly propogate to the final non-compliance reasoning.
- Vote records embedded in bill page tabs will now link directly to the tab (as with summaries) rather than just to the bill page.

### Fixed
- Bills which have been reported out in the past but which are currently handled by a committee that has not yet posted a hearing may have misleadingly registered as "reported out" when technically they have not yet been acted upon by the current committee. Reflecting this on the dashboard is purely a visual change which doesn't impact compliance or violation count, but will more closely align with the intent of the tracker.


## [1.1.8] - 2025-11-19

### Added
- Votes can now be parsed from House and Senate Journal PDFs and attributed to the proper bills (may raise compliance in some cases).
- Self-tests rolled in for several document parsers to ensure functionality across updates.
- Created an internal "ruleset engine" module to improve algorithmic transparency, improve alignment with the Legislature ruleset, and track rules changes session-to-session.

### Changed
- "Hearing rescheduled" will now count as a hearing date even if "hearing scheduled" is not present (may boost compliance if a bill was previously marked as missing a hearing date, or it may drop compliance if all other requirements were met but the hearing is revealed to be non-compliant--see "Fixes").

### Fixed
- Bills which posted all requirements but never announced a hearing will be considered non-compliant with the notice gap requirement (may drop compliance for some committees).


## [1.1.7] - 2025-11-14

### Fixed
- Reported-out deadline tracking is now more aggressive, catching more instances of non-compliance. This may cause some committees to drop in compliance.


## [1.1.6] - 2025-11-13

### Added
- Caching for documentation to preserve historical Legislature records
- Legislative session tracking; will automatically reset for the 195th session and archive the 194th session data.
- Now tracking Senate with included Senate rules.

### Changed
- Tightened summary detection rules out of an abundance of caution (no change in compliance recorded)


## [1.1.5] - 2025-11-12

### Fixed
- Deduplicate bill lists when computing compliance deltas to better align the change percentage with that which is reported by the dashboard

### Added
- Retroactive deduplication for historical compliance deltas to correct percentage gains for accurate future trend analysis


## [1.1.4] - 2025-11-08

### Fixed
- Bills will not report a hearing notice number if they got reported out prior to a future committee's hearing (purely visual, no impact on compliance)


## [1.1.3] - 2025-11-06

### Added
- Implemented support for more date formats (e.g. 11/04/2025 vs. 11/4/2025 vs. 11-4-2025, etc.)

### Changed
- Bills which have announcements but aren't linked in a hearing docket yet will be considered "announced"
- Increased confidence level for on-page summaries with unusual formatting

### Fixed
- Tweaked user-facing language when a hearing gap was computed but a date was not listed


## [1.1.2] - 2025-11-05

### Added
- Fast-fail when Legislature document server is down
- Track votes in the trend analysis

### Changed
- Auto-generated analysis tweaked for grammar and verbosity
  
### Fixed
- Bills with hearings added not always updating compliance
- Trend percentage now absolute, rather than multiplicative


## [1.1.1] - 2025-10-31

### Fixed
- Streamlined auto-generated analysis blurb creation
- Reduced uncertainty in analysis and tracking


## [1.1.0] - 2025-10-30

### Added
- Day-by-day tracking of committees
- Auto-generated summary of new compliance developments
- Optional LLM-boosted analysis
- New API fields for daily tracking


## [1.0.0] - 2025-10-28

### Added
- Initial release of Beacon Hill Compliance Tracker
- Committee compliance tracking and monitoring
- Bill status collection from Massachusetts Legislature website
- Extension order tracking and management
- Hearing information collection
- Committee contact information gathering
- Automated compliance deadline calculations
- Document caching system for improved performance
- LLM-powered document parsing assistance
- Interactive and console-based review interfaces
- Comprehensive parser system for various document formats
- JSON export functionality for compliance reports
- Email notification system for compliance updates
- Version tracking and changelog system
- API endpoint for changelog distribution

### Security
- Implemented document content hashing for cache validation
- Added secure configuration management via YAML








