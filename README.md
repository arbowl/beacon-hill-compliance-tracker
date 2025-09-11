# MA Rules - Massachusetts Legislative Committee Compliance Tracker

A Python tool for tracking compliance of Massachusetts legislative committees with their reporting deadlines. Designed to be simple, maintainable, and accessible for students or hobbyists to extend.

## Purpose

Massachusetts House and Joint committees are required to take action on bills within 60 days of a hearing, with at most one 30-day extension (capped at 90 days). Committees must also post summaries and vote records. This project automates the collection of that information and classifies each bill as **compliant**, **non-compliant**, or **unknown**.

## Quick Start

### Setup

1. **Clone and install dependencies:**
   ```bash
   git clone https://github.com/arbowl/beacon-hill-compliance-tracker
   cd ma-rules
   python -m venv venv
   venv\Scripts\activate  # Windows
   # or: source venv/bin/activate  # Linux/Mac
   pip install -r requirements.txt
   ```

2. **Configure the target committee:**
   Edit `config.yaml` to change the committee ID or other settings:
   ```yaml
   runner:
     committee_id: "J33"     # Change to your target committee
     limit_hearings: 1       # Start small for testing
   ```

### Running

```bash
python app.py
```

This will:
- Fetch committee data and hearings
- Collect bills from the first hearing
- Check compliance for each bill
- Generate HTML and JSON reports in the `out/` folder

## Outputs

The tool generates two types of reports:

### HTML Report (`out/basic_J33.html`)
A human-readable table showing:
- Bill ID and hearing date
- 60-day and effective deadlines
- Whether the bill was "reported out"
- Summary and vote availability
- Compliance status and reason

### JSON Data (`out/basic_J33.json`)
Machine-readable data for each bill including:
- All compliance information
- Source URLs for summaries and votes
- Parser modules used
- Timestamps and metadata

## Architecture

The design is deliberately modular and straightforward:

### Core Components

- **`components/models.py`**: Think of this as "bundles of information", e.g. contact details, bill details, vote details, etc. The calculations and compliance checks are compiled using sets of this information. This file handles structure, not so much logic.
- **`components/pipeline.py`**: Orchestrates discovery of summaries and votes using cost-ordered parsers. We rate each method based on how "expensive" it is so we can attempt the least "costly" methods first on unknown data sources, then cache the method which worked.
- **`components/compliance.py`**: Rule engine that classifies bills based on deadlines, reported-out status, and document availability.
- **`components/report.py`**: Generates HTML and JSON outputs.
- **`components/utils.py`**: Cache management, configuration loading, and UI helpers.

### Data Flow

1. **Collect committees** (House/Joint only, ignoring Senate)
2. **Get hearings and bills** for the target committee
3. **Compute deadlines** and check "reported out" status
4. **Discover summaries** using cost-ordered parsers
5. **Discover votes** using cost-ordered parsers
6. **Classify compliance** for each bill
7. **Generate outputs** (console logs, JSON data, HTML report)

## Folder Structure

```
ma-rules/
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

Parsers are small, pluggable modules that discover and extract summaries or votes from specific locations. Each parser must implement two functions:

### Parser Interface

```python
def discover(base_url: str, bill: BillAtHearing) -> Optional[dict]:
    """Find a candidate document/source for this bill.
    Returns None if not found, or a dict with:
    - preview: Short description for user confirmation
    - source_url: Direct link to the document
    - confidence: Float 0.0-1.0 (optional)
    - full_text: Full text content for preview (optional)
    """

def parse(base_url: str, candidate: dict) -> dict:
    """Extract structured data from the candidate.
    Returns a dict with:
    - source_url: Confirmed URL
    - location: Human-readable location name
    - Additional fields as needed
    """
```

### Example Parser

```python
# parsers/summary_custom_format.py
from typing import Optional
from components.models import BillAtHearing

def discover(base_url: str, bill: BillAtHearing) -> Optional[dict]:
    # Your discovery logic here
    if found_something:
        return {
            "preview": "Found summary in custom location",
            "source_url": "https://example.com/summary.pdf",
            "confidence": 0.9
        }
    return None

def parse(base_url: str, candidate: dict) -> dict:
    # Your parsing logic here
    return {
        "source_url": candidate["source_url"],
        "location": "custom_format"
    }
```

### Registering Parsers

Add your parser to `config.yaml`:

```yaml
parsers:
  summary:
    - module: "parsers.summary_custom_format"
      cost: 5  # Higher cost = tried later
  votes:
    - module: "parsers.votes_custom_format"
      cost: 3
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

```json
{
  "bill_parsers": {
    "H73": {
      "summary": {
        "module": "parsers.summary_hearing_docs_pdf",
        "confirmed": true,
        "updated_at": "2025-01-10T17:34:29Z"
      }
    }
  }
}
```

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

3. **Pull a model** (choose one based on your hardware):
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
   ollama run mistral:7b-instruct
   ```

### LLM Configuration

Edit the `llm` section in `config.yaml` to configure LLM integration:

```yaml
llm:
  enabled: true                   # Enable/disable LLM integration
  host: "localhost"               # Ollama server host (use 0.0.0.0 for remote access)
  port: 11434                     # Ollama server port
  model: "mistral:7b-instruct"    # Model name (must match what you pulled)
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

## Configuration

Edit `config.yaml` to customize behavior:

```yaml
base_url: "https://malegislature.gov"
filters:
  include_chambers: ["House", "Joint"]  # Ignore Senate committees
runner:
  committee_id: "J33"                   # Target committee
  limit_hearings: 1                     # Number of hearings to process
parsers:
  summary:                              # Summary parsers (cost-ordered)
    - module: "parsers.summary_hearing_docs_pdf"
      cost: 1
  votes:                                # Vote parsers (cost-ordered)
    - module: "parsers.votes_bill_embedded"
      cost: 1
review_mode: "on"                       # Show confirmation dialogs
llm:                                    # LLM integration settings
  enabled: true
  host: "localhost"
  port: 11434
  model: "mistral:7b-instruct"
  # ... (see LLM Integration section above for full config)
```

## Testing

Run individual components:

```bash
# Test bill collection
python tests/collect_bills.py

# Test specific parsers
python tests/summary_tab_parser.py
python tests/votes_pipeline.py
```

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

