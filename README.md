Beacon Hill Compliance Tracker

A Python tool for tracking compliance of Massachusetts legislative committees with their reporting deadlines. Designed to be simple, maintainable, and accessible for students or hobbyists to extend.

The tool uses an API key to submit recorded data to a dashboard at https://beaconhilltracker.org/.

I chose a web-scraping approach rather than using the official API because the purpose of this tool is to track compliance
based on a what-you-see-is-what-you-get mindset. The primary way the public interfaces with the Legislature's outputs is via
the website, not via backend interfaces and scripts. Although this approach is more brittle, I believe that the advantages gained by having the code
see exactly what an activist would see outweigh the benefits of using unified data structures.

## Purpose

Massachusetts House and Joint committees are required to:
1. **Announce hearings at least 10 days in advance**
2. **Take action on bills within 60 days of a hearing**, with at most one 30-day extension (capped at 90 days)
3. **Post summaries and vote records** of their decisions

This project automates the collection of that information and classifies each bill as **compliant**, **non-compliant**, **incomplete**, or **unknown**:
- **Compliant:** All requirements satisfied.
- **Incomplete:** Exactly one requirement missing.
- **Non-compliant:** Two or more requirements missing.
- **Unknown:** No disqualifying factors present, but not fully compliant (yet).

The purpose of having an "incomplete" status is to highlight nearly-compliant bills for developers to hone in on potential errors stopping a bill from being recognized as compliant. However, it's trivial for dashboards to reinterpret the information gathered by this tool as is appropriate.

## Quick Start

### Setup

```bash
git clone https://github.com/arbowl/beacon-hill-compliance-tracker
cd beacon-hill-compliance-tracker
python -m venv venv
venv\Scripts\activate  # Windows
# or: source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### Running

```bash
python app.py
```

### The Cache

This is the "sourdough starter" of this project; if you run it, you'll want a cache from a trusted user. The "cache" is a JSON file aptly named
"cache.json" which contains metadata about bills and committees that make the algorithm run faster over time. The code will generate it on its
own, but using a trusted user's version will get you up and running much sooner.

## Outputs

The tool generates two types of reports:

### HTML Report (`out/basic_J33.html`)
A human-readable report containing:

**Committee Contact Information:**
- Senate and House contact details (address, phone)
- Chair and Vice-Chair names and email addresses

**Compliance Table:**
- Bill ID and hearing date
- 60-day and effective deadlines
- Notice gap (days between announcement and hearing)
- Whether the bill was "reported out"
- Summary and vote availability
- Compliance status and reason

### JSON Data (`out/basic_J33.json`)
Machine-readable data for each bill including:
- All compliance information
- Notice gap data (announcement date, hearing date, gap days, status)
- Source URLs for summaries and votes
- Parser modules used
- Timestamps and metadata

## Architecture

The design is deliberately modular and straightforward:

### Components

The `components/` folder contains the unique actions in the processing pipeline. Each one has a different task. When a new task needs to be added to the project flow, add it here for organization.

- **`committees.py`**: Retrieves data related to ALL committees.
- **`compliance.py`**: Rule engine that classifies bills based on deadlines, reported-out status, and document availability.
- **`interfaces.py`**: Provides abstract base classes for other elements of the project to implement concrete versions of.
- **`llm.py`**: Coordinates integration with local LLMs for more automatic review.
- **`models.py`**: Think of this as "bundles of information", e.g. contact details, bill details, vote details, etc. The calculations and compliance checks are compiled using sets of this information. This file handles structure, not so much logic.
- **`options.py`**: Allows the user to access an options menu (if enabled in config) and toggle various features at runtime
- **`pipeline.py`**: Orchestrates discovery of summaries and votes using cost-ordered parsers. We rate each method based on how "expensive" it is so we can attempt the least "costly" methods first on unknown data sources, then cache the method which worked.
- **`report.py`**: Handles saving completed datasets to disk in various formats (human-readable, machine-readable, etc.)
- **`review.py`**: Batch review manager for handling low-confidence captures at the end of a run.
- **`runner.py`**: Performs a full scan of a single committee start to finish.
- **`sender.py`**: Sends collected info to the dashboard's API.
- **`utils.py`**: Cache management, configuration loading, and UI helpers.

### Data Flow

1. **Parse extension orders** (Optional, computationally expensive)
2. **Collect committee info** (House/Joint only, ignoring Senate)
2. **Get hearings and bills** for the target committee
3. **Compute deadlines** and check "reported out" status
4. **Discover summaries** using cost-ordered parsers
5. **Discover votes** using cost-ordered parsers
6. **Classify compliance** for each bill
7. **Generate outputs** (console logs, JSON data, HTML report)
8. **Send to dashboard** via the API

## Folder Structure

```
beacon-hill-compliance-tracker/
├── app.py                 # Main entry point
├── config.yaml           # Configuration file
├── cache.json            # Parser cache (auto-generated)
├── components/           # Core application logic
│   ├── models.py         # Data models
│   ├── pipeline.py       # Summary/vote discovery pipeline
│   ├── compliance.py     # Compliance classification
│   ├── report.py         # HTML/JSON report generation
│   └── utils.py          # Utilities and cache management
├── collectors/           # Pluggable data collection modules--add to this as needed
│   ├── bills_from_hearing.py
│   ├── bill_status_basic.py
│   └── committee_contact_info.py
├── parsers/              # Pluggable parsers for different formats--add to this as needed
│   ├── summary_hearing_docs_pdf.py
│   ├── summary_bill_tab_text.py
│   ├── votes_bill_embedded.py
│   └── votes_bill_pdf.py
├── tests/                # Test scripts
└── out/                  # Generated reports
```

## Adding Parsers

Parsers are small, pluggable modules that discover and extract summaries or votes from specific locations. Each parser must inherit the `ParserInterface` class:

### Parser Interface

```python

from components.interfaces import ParserInterface

class ExampleParser(ParserInterface):

    parser_type: str = "SUMMARY"  # or "VOTES" (or any future nth type)
    location: str = "Where you manually found this content"
    cost: int = 1  # How "expensive" it is to run this operation, relative to the others

    @classmethod
    def discover(
      cls, base_url: str, bill: BillAtHearing
    ) -> Optional[ParserInterface.ParserType]:
        """Find a candidate document/source for this bill.
        Returns None if not found, or a dict with:
        - preview: Short description for user confirmation
        - source_url: Direct link to the document
        - confidence: Float 0.0-1.0 (optional)
        - full_text: Full text content for preview (optional)
        """

    @staticmethod
    def parse(
      base_url: str, candidate: Optional[ParserInterface.Parsertype]
    ) -> dict:
        """Extract structured data from the candidate.
        Returns a dict with:
        - source_url: Confirmed URL
        - location: Human-readable location name
        - Additional fields as needed
        """
```

### Registering Parser

When you make a new parser, insert it in `pipeline.py` so that it can be imported at startup and accessed at runtime:

```python
# components/pipeline.py
...
from parsers.example_parser import ExampleParser

PARSER_REGISTRY: dict[str, ParserInterface] = {
    module.__module__: module for module in [
      ...
      ExampleParser,
    ]
}
```

## Adding Collectors

Collectors fetch data from the Massachusetts Legislature website. They follow a simple pattern:

```python
# collectors/custom_data.py
from typing import List
from components.models import YourModel

def fetch_custom_data(base_url: str, params: dict) -> List[YourModel]:
    """Fetch and return a list of YourModel objects."""
    # Your collection logic here
    return results
```

## Caching System

The tool uses a JSON-based cache (`cache.json`) to remember which parsers worked for each bill:

- **First run**: Shows confirmation dialogs for new parsers
- **Subsequent runs**: Skips confirmed parsers automatically
- **Headless mode**: Set `review_mode: "off"` in config to auto-accept parsers

### Cache Structure

The cache stores bill parser information, hearing announcements, and committee contact details:

```json
{
  "bill_parsers": {
    "H73": {
      "bill_url": "https://malegislature.gov/Bills/194/H73",
      "summary": {
        "module": "parsers.summary_hearing_docs_pdf",
        "confirmed": true,
        "updated_at": "2025-01-10T17:34:29Z"
      },
      "hearing_announcement": {
        "announcement_date": "2025-04-07",
        "scheduled_hearing_date": "2025-04-14",
        "updated_at": "2025-09-28T21:15:00Z"
      }
    }
  },
  "committee_contacts": {
    "J33": {
      "committee_id": "J33",
      "name": "Joint Committee on Advanced Information Technology, the Internet and Cybersecurity",
      "chamber": "Joint",
      "url": "https://malegislature.gov/Committees/Detail/J33",
      "house_room": "Room 274",
      "house_address": "24 Beacon St. Room 274 Boston, MA 02133",
      "house_phone": "(617) 722-2676",
      "senate_room": "Room 109-B",
      "senate_address": "24 Beacon St. Room 109-B Boston, MA 02133",
      "senate_phone": "(617) 722-1485",
      "senate_chair_name": "Michael O. Moore",
      "senate_chair_email": "Michael.Moore@masenate.gov",
      "senate_vice_chair_name": "Pavel M. Payano",
      "senate_vice_chair_email": "Pavel.Payano@masenate.gov",
      "house_chair_name": "Tricia Farley-Bouvier",
      "house_chair_email": "Tricia.Farley-Bouvier@mahouse.gov",
      "house_vice_chair_name": "James K. Hawkins",
      "house_vice_chair_email": "James.Hawkins@mahouse.gov",
      "updated_at": "2025-09-28T20:38:46Z"
    }
  }
}
```

#### Committee Contact Fields

Each committee entry includes:

**Basic Information:**
- `committee_id`: Committee identifier (e.g., "J33")
- `name`: Full committee name
- `chamber`: "Joint", "House", or "Senate"
- `url`: Link to committee detail page

**Contact Information:**
- `house_room`, `house_address`, `house_phone`: House contact details
- `senate_room`, `senate_address`, `senate_phone`: Senate contact details

**Chair and Vice-Chair Information (New):**
- `senate_chair_name`, `senate_chair_email`: Senate Chair details
- `senate_vice_chair_name`, `senate_vice_chair_email`: Senate Vice Chair details
- `house_chair_name`, `house_chair_email`: House Chair details
- `house_vice_chair_name`, `house_vice_chair_email`: House Vice Chair details

All chair/vice-chair fields default to empty strings if not found or not applicable.

#### Bill Cache Fields (New)

Each bill entry can include additional cached data:

**Top-level fields:**
- `bill_url`: URL of the bill page (e.g., "https://malegislature.gov/Bills/194/H73")

**Hearing announcement data:**
- `hearing_announcement.announcement_date`: Date when the hearing was announced (YYYY-MM-DD format)
- `hearing_announcement.scheduled_hearing_date`: Date when the hearing was scheduled (YYYY-MM-DD format)
- `hearing_announcement.updated_at`: Timestamp when this data was cached

This cache improves performance by avoiding re-scraping bill pages for hearing notice data and preserves historical announcement information even if the source pages change.

## LLM Integration

The system includes optional LLM (Large Language Model) integration to automatically determine whether discovered documents match the requirements (summary, vote record, etc.) without requiring human intervention. This significantly speeds up the review process by reducing manual confirmation dialogs.

### LLM Setup

The system is designed to work with Ollama, a local LLM server. Follow these steps to set up LLM integration:

1. **Install Ollama** (if not already installed):
   - Visit [ollama.ai](https://ollama.ai) and download for your platform
   - Install and ensure Ollama is in your PATH

2. **Start Ollama server**:
   ```bash
   OLLAMA_HOST=0.0.0.0 ollama serve
   ```

   ```cmd
   set OLLAMA_HOST=0.0.0.0 & ollama serve
   ```

3. **Pull a model** (choose one based on your hardware):

  I use `qwen3:4b` for less powerful machines; reasoning models work best.

  Example commands:
   ```bash
   # For faster, smaller models (recommended for most users)
   ollama pull llama3.2:3b
   ollama pull mistral:7b-instruct
   
   # For better accuracy (requires more resources)
   ollama pull llama3.1:8b
   ollama pull codellama:7b
   ```

4. **Test the model**:
   ```bash
   ollama run qwen3:4b
   ```

### LLM Configuration

Edit the `llm` section in `config.yaml` to configure LLM integration:

```yaml
llm:
  enabled: true                   # Enable/disable LLM integration
  host: "192.168.0.111"           # Ollama server host
  port: 11434                     # Ollama server port
  model: "qwen3:4b"               # Model name (must match what you pulled)
  prompt: |                       # Custom prompt template
    bill_id: {bill_id}
    doc_type: {doc_type}
    content: """{content}"""

    Answer one word (yes/no/unsure) using these rules:
    - Bill id must appear (H or S + number, with/without dot/space).
    - summary → must have bill id AND either:
        • "Summary" near it, OR
        • a malegislature.gov link whose filename/title has bill id + "Summary", OR
        • policy/topic-style prose (not navigation, login, or site boilerplate).
    - vote record → needs bill id AND ("vote"|"yea"|"nay"|"favorable"|"recommendation"|"committee") AND either named member positions or an explicit committee recommendation.
    - Ignore boilerplate.
    Output exactly: yes|no|unsure.
  timeout: 30                     # Request timeout in seconds
  audit_log:                      # Audit logging configuration
    enabled: true                 # Enable audit logging
    file: "out/llm_audit.log"    # Log file location
    include_timestamps: true      # Include timestamps in logs
    include_model_info: true      # Include model/host info in logs
```

### How LLM Integration Works

1. **Document Discovery**: When parsers discover potential documents (summaries or vote records), the system first tries to use the LLM to determine if they match the requirements.

2. **LLM Decision**: The LLM analyzes the document content and returns:
   - `"yes"` - Document matches requirements, automatically accept
   - `"no"` - Document doesn't match, skip this parser
   - `"unsure"` - LLM is uncertain, fall back to human dialog

3. **Fallback Behavior**: If the LLM is unavailable, disabled, or returns "unsure", the system falls back to the traditional human confirmation dialog.

4. **Audit Logging**: All LLM interactions are logged to `out/llm_audit.log` for transparency and debugging.

### Benefits

- **Faster Processing**: Reduces manual confirmation dialogs by ~80-90%
- **Consistent Decisions**: LLM applies the same criteria consistently
- **Audit Trail**: Complete log of all LLM decisions for review
- **Fallback Safety**: Always falls back to human review when uncertain

### Troubleshooting

- **LLM Not Responding**: Check that Ollama is running and the model is pulled
- **Wrong Decisions**: Review the audit log and adjust the prompt template
- **Performance Issues**: Try a smaller model or increase timeout settings
- **Network Issues**: Ensure the host/port settings match your Ollama server

## Console Review Mode

For headless environments, SSH sessions, or users who prefer terminal-based workflows, you can use console-based confirmation dialogs instead of Tkinter popups.

### Setup

Set `popup_review` to `false` in your configuration:

```yaml
# config.yaml
popup_review: false  # Use console instead of Tkinter popups
```

### Features

- **Clean formatting**: Well-structured prompts with clear visual separation
- **Text preview**: Long documents are wrapped and truncated for readability
- **URL display**: Source URLs are clearly shown for reference
- **Input validation**: Accepts y/yes/n/no with retry on invalid input
- **Keyboard interrupt handling**: Graceful exit with Ctrl+C

### Example Console Output

```
================================================================
PARSER CONFIRMATION - Bill H2391
================================================================
Looking for: Summary

Use this summary for H2391?

URL: https://malegislature.gov/Bills/194/H2391/Documents/Committee

Preview:
----------------------------------------------------------------
HOUSE DOCKET, NO. 2391        FILED ON: 1/20/2023

The Commonwealth of Massachusetts
_______________

PRESENTED BY:

Mr. Donato of Medford
...
----------------------------------------------------------------
================================================================
Use this? (y/n): 
```

### When to Use Console Review

- **SSH/Remote sessions**: No GUI available
- **Headless servers**: Running in automated environments
- **Terminal preference**: Users who prefer command-line workflows
- **Screen readers**: Better accessibility in some cases

## Deferred Review Mode

For faster processing and better workflow, you can defer all manual confirmations to a batch review session at the end instead of interrupting the processing flow.

### Setup

Set `review_mode` to `"deferred"` in your configuration:

```yaml
# config.yaml
review_mode: "deferred"  # Collect confirmations, review at end
popup_review: false      # Use console for batch review (recommended)
```

### How It Works

1. **Continuous Processing**: Bills are processed without interruption
2. **Confirmation Collection**: Parser candidates are collected for later review
3. **Auto-Accept High Confidence**: Parsers with high confidence scores are automatically accepted
4. **Batch Review Session**: All remaining confirmations presented together at the end
5. **Cache Updates**: Confirmed parsers are saved for future runs

### Batch Review Interface

```
================================================================
BATCH REVIEW SESSION - Committee J33
================================================================
Found 12 parser confirmations requiring review:
  - 8 summaries (5 bills)
  - 4 vote records (3 bills)

Press Enter to begin review, or 'q' to quit...

================================================================
CONFIRMATION 1 of 12 - Bill H2391 (Summary)
================================================================
Parser: parsers.summary_hearing_docs_pdf
Confidence: High (85%)
URL: https://malegislature.gov/Bills/194/H2391/Documents/Committee

Preview:
----------------------------------------------------------------
HOUSE DOCKET, NO. 2391        FILED ON: 1/20/2023
The Commonwealth of Massachusetts
...
----------------------------------------------------------------
================================================================
Options:
  [y] Accept this parser
  [n] Reject this parser
  [s] Skip (decide later)
  [a] Accept all remaining for this bill
  [q] Quit review session

Choice (y/n/s/a/q): 
```

### Configuration Options

```yaml
# Deferred review settings (only used when review_mode: "deferred")
deferred_review:
  reprocess_after_review: true     # Re-run processing after confirmation
  show_confidence: true            # Display parser confidence scores
  group_by_bill: false            # Group confirmations by bill vs chronological
  auto_accept_high_confidence: 0.9 # Auto-accept if confidence > threshold (0.0-1.0)
```

### Benefits

- **Faster Processing**: No interruptions during bill collection (3-5x faster)
- **Better Focus**: Dedicated review session with full context
- **Batch Decisions**: Accept/reject multiple parsers efficiently
- **Progress Visibility**: See all bills processed before making decisions
- **Smart Auto-Accept**: High-confidence parsers accepted automatically
- **Consistent Experience**: Works with both console and popup review modes

### When to Use Deferred Review

- **Large Committees**: Processing many bills (20+)
- **Initial Runs**: First time processing a committee (many confirmations needed)
- **Batch Operations**: Processing multiple committees in sequence
- **Focus Workflows**: Prefer dedicated review time vs scattered interruptions

## Design Philosophy

- **Keep it boring**: Avoid frameworks and over-engineering
- **Modular**: Easy to add new parsers and collectors
- **Transparent**: Clear data flow and simple UI
- **Accessible**: Designed for non-specialists to understand and extend
- **Robust**: Handles the quirks of the Legislature's website gracefully

## Contributing

1. Add new parsers in the `parsers/` directory
2. Add new collectors in the `collectors/` directory
3. Update `config.yaml` to register new parsers
4. Test with `python app.py`
5. Submit a pull request

The codebase is designed to be easily understood and extended by students, hobbyists, and grassroots organizations tracking legislative compliance.


