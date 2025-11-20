# Changelog

All notable changes to the Beacon Hill Compliance Tracker will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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




