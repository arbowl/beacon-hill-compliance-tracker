# Changelog

All notable changes to the Beacon Hill Compliance Tracker will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.2] - 2025-11-05

### Added
- Fast-fail when Legislature document server is down

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



