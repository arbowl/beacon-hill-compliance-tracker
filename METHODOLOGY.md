# Technical Methodology

**Beacon Hill Compliance Tracker -- as of v1.4.1**

This document has two parts. The first ([How It Works](#how-it-works)) is a plain-language overview intended for anyone who wants to understand what the Tracker does and why its findings can be trusted. The second ([Technical Detail](#technical-detail)) is a deeper description of the implementation for contributors and technical reviewers.

For the plain-English description of the compliance rules themselves, see [RULESET194.md](RULESET194.md).

---

## How It Works

### What the Tracker does

In 2025, the Massachusetts Legislature adopted new Joint Rules requiring legislative committees to give the public advance notice of hearings, to vote on bills within a fixed window after those hearings, and to post both a written summary in advance of the hearing and a record of how members voted. The Beacon Hill Compliance Tracker checks whether committees are meeting those obligations, automatically, by reading the Legislature's own public website.

### Step by step

**1. Find the committees.**
The Tracker starts with the list of active Massachusetts legislative committees (House, Senate, and Joint) drawn directly from the Legislature's website (`malegislature.gov`).

**2. Find the hearings and bills.**
For each committee, it collects two lists: bills that have been assigned a hearing date, and all bills that have been referred to that committee regardless of whether a hearing has been scheduled. Each bill's page is visited to extract its action history, the sequence of formal steps (referral, hearing notice, report-out, etc.) that constitute its legislative record.

**3. Check the notice.**
For Senate and Joint committees, the law requires that hearings be announced a minimum number of days in advance (5 days for Senate, 10 days for Joint). The Tracker computes the gap between the public announcement date and the hearing date and flags hearings that fall short.

**4. Check the deadline.**
After a hearing, committees have a set window to act on each bill (typically 60 days for House bills, with session-specific deadlines for Senate and Joint bills). The Tracker computes the applicable deadline for each bill, checks whether the committee formally reported the bill out within that window, and flags bills where the deadline has passed with no recorded action.

**5. Look for the documents.**
The Tracker searches for two types of required documents: a hearing summary and a vote record. These can appear in several places on the Legislature's site: attached directly to a bill, embedded in the committee's hearing pages, posted as PDFs or Word documents in the committee's document folder, or recorded in the House or Senate journal. The Tracker tries each location in order, starting with the cheapest (most likely) source and moving on if nothing is found.

**6. Classify each bill.**
With all of the above in hand, the Tracker applies four rules -- notice, deadline, summary posting, and vote posting -- and assigns each bill one of four states:

- **Compliant**: all requirements met
- **Non-Compliant**: one or more requirements failed
- **Incomplete**: a subset of requirements is missing (same as Non-Compliant in effect, but used to audit edge cases and bifurcate single-offenders with multi-offenders)
- **Unknown**: the deadline has not yet passed, or the Tracker cannot determine the answer from available data

**7. Publish the results.**
Results are written to dated HTML and JSON files and sent to [beaconhilltracker.org](https://beaconhilltracker.org), where they are publicly accessible. Every run is recorded with a full audit log so that any finding can be traced back to the specific data that produced it.

### Why scraping, not the API?

The Legislature provides a developer API. The Tracker deliberately does not use it as a primary source, because compliance is only meaningful if it is visible in the public record. A document that exists in a database but is not accessible on the public website does not satisfy the transparency purpose of the Rules. The Tracker checks what a citizen would see.

### External validation

The Tracker's findings have been used and independently verified by policy advocates, legislative researchers, and journalists. Coverage and citations include:

- [Boston Globe](https://www.bostonglobe.com/2026/05/05/metro/legislature-transparency-loophole-committee-votes/) (May 2026)
- [Commonwealth Beacon Op-Ed](https://commonwealthbeacon.org/opinion/beacon-hills-new-rules-are-good-they-should-follow-them/) (December 2025)
- [New Bedford Light](https://newbedfordlight.org/how-much-progress-did-new-bedfords-legislators-make-in-fall-2025/) (Fall 2025 retrospective)
- [POLITICO Massachusetts Playbook](https://www.politico.com/newsletters/massachusetts-playbook/2025/11/19/legislature-hits-the-halfway-mark-00658660) (November 2025)
- [Act On Mass](https://actonmass.org/post/2025/11/24/11-22-2025-saturday-scoop-reps-vote-to-roll-back-mas-climate-laws-in-classic-tale-of-beacon-hill-corruption/) (November 2025)
- [Progressive Massachusetts](https://www.progressivemass.com/new-state-house-accountability-tool-launched/) (tool launch)

### Contributing

The Tracker is open source. If you find a bug in how a document is detected, a committee is parsed, or a deadline is computed, contributions are welcome via pull request. The [unit test suite](#12-unit-testing) includes recorded web responses (cassettes) so that parser fixes can be verified without live network access. See [README.md](README.md) for setup instructions.

---

## Technical Detail

This section describes the implementation at a level sufficient for a technical reviewer to evaluate correctness, reproducibility, and methodological rigor. It is not a user guide.

---

## Contents

1. [Design Philosophy](#1-design-philosophy)
2. [Data Collection](#2-data-collection)
3. [Bill Lifecycle Model](#3-bill-lifecycle-model)
4. [Normalization](#4-normalization)
5. [Adaptive Parser Pipeline](#5-adaptive-parser-pipeline)
6. [Ruleset Engine](#6-ruleset-engine)
7. [Document Cache and Storage](#7-document-cache-and-storage)
8. [Artifact Persistence and Re-analysis](#8-artifact-persistence-and-re-analysis)
9. [LLM Integration](#9-llm-integration)
10. [Human-in-the-Loop Review](#10-human-in-the-loop-review)
11. [Audit Logging](#11-audit-logging)
12. [Unit Testing](#12-unit-testing)
13. [Limitations and Caveats](#13-limitations-and-caveats)

---

## 1. Design Philosophy

The tool validates what citizens see on the Massachusetts Legislature website. It deliberately scrapes the public-facing site rather than consuming the official API, on the principle that compliance is only meaningful if it is visible in the citizen-accessible record. Data collected from the API might reflect internal state that is not yet, or never will be, publicly posted.

All compliance decisions are deterministic given the same input data. The optional LLM component (§9) can influence document confidence scoring but never overrides the rule engine. Every decision that affects a compliance classification is traceable to a specific collected artifact.

---

## 2. Data Collection

Five collectors (`collectors/`) fetch data that is guaranteed to exist if the underlying page exists. They are not speculative — they raise or return empty on failure rather than returning partial results.

| Collector | Source | Returns |
|---|---|---|
| `bills_from_hearing` | Committee hearings page | `BillAtHearing` list with hearing date, ID, URL |
| `bills_from_committee_tab` | Committee "Bills" tab (paginated) | `BillAtHearing` list without hearing metadata |
| `bill_status_basic` | Individual bill page | `BillStatus` with deadlines, reported status, referral date |
| `committee_contact_info` | Committee detail page | Chair/vice-chair, room and phone numbers |
| `extension_orders` | House/Senate "Order of Business" pages | `ExtensionOrder` list with bill ID and extension date |

`bill_status_basic` calls `extract_timeline()` (§3) internally and then applies the same deadline arithmetic as the ruleset to produce `deadline_60`, `deadline_90`, and `effective_deadline` fields. These fields are also recomputed by the ruleset at classification time; the two computations must stay in sync (`components/utils.py::compute_deadlines` mirrors `components/ruleset.py::ReportedOutRequirementRule`).

**Extension order detection** uses regex against the "Order of Business" page. When the regex fails to match the expected structure, the collector falls back to heuristic line scanning and sets `is_fallback=True` on the returned `ExtensionOrder`. Downstream code preserves this flag and the audit log records it.

---

## 3. Bill Lifecycle Model

### Timeline Extraction

`timeline/extract_timeline(bill_url, bill_id)` parses the action history table on a bill's page (columns: Date, Branch, Action). Each row is matched against a registry of `ActionNode` objects. The registry contains 40+ distinct `ActionType` values covering the full legislative lifecycle:

```
REFERRED > HEARING_SCHEDULED > [HEARING_RESCHEDULED] >
    REPORTED | STUDY_ORDER | ACCOMPANIED   < terminal committee actions
        v
    READ > READ_SECOND > READ_THIRD > ENACTED > SIGNED
```

This forms an implicit finite state machine: certain action types are only meaningful after specific predecessors. The timeline module does not enforce valid transitions (the Legislature's own data is authoritative), but the ruleset uses the presence or absence of terminal actions to determine whether a committee has acted.

### ActionNode Matching

Each `ActionNode` carries:

- One or more compiled regex patterns ordered by priority
- Field extractors that operate on the regex match object (e.g., extracting a committee ID from `"Referred to the Committee on ..."`)
- A `calculate_confidence(match)` function returning 0.0–1.0
- A `match()` method that returns the first pattern match or `None`

The timeline extractor iterates the registry in priority order and takes the first `ActionNode` that matches. Unrecognized action text is stored as `ActionType.UNKNOWN`.

### Hearing Inference

When an action is matched as `HEARING_SCHEDULED` but the extracted committee ID is absent, the module attempts to infer it from the bill's referred-to committee. This handles cases where the Legislature records a hearing without a committee attribution.

---

## 4. Normalization

### Committee Alias Resolution

Committee names in scraped text are inconsistent (e.g., "Jt. Comm. on Labor" vs. "Joint Committee on Labor and Workforce Development"). `timeline/normalizers.py` maintains a registry of `CommitteeAlias` objects, each holding a canonical name, short-name variants, and a numeric committee ID.

Resolution uses substring matching: a candidate string must contain at least one of the alias variants. When multiple aliases match, the longest match wins. If no match is found, the ID is left unresolved and flagged.

### Date Parsing

`parse_date()` accepts two formats observed on the Legislature site:

- `MM/DD/YYYY` (action history tables)
- `Month DD, YYYY` (full month name; hearing pages)

Dates outside these formats are not accepted; the action is stored with a null date and logged as an error.

### Text Normalization

Parser `discover()` methods strip leading navigation boilerplate before extracting preview text. The LLM truncation logic (§9) also normalizes input by preferring sentence boundaries over character limits.

---

## 5. Adaptive Parser Pipeline

The pipeline (`components/pipeline.py`) is responsible for discovering summary documents and vote records for each bill. It operates two independent registries:

- `SUMMARY_REGISTRY`: 7 parsers sourcing from bill tabs, hearing PDFs, committee DOCX files
- `VOTES_REGISTRY`: 7 parsers sourcing from embedded vote tables, journal PDFs, accompanied bills

### Three-Tier Selection

For each bill, parsers are ordered into three tiers before any network request is made:

| Tier | Name | Source | Description |
|---|---|---|---|
| 0 | `BILL_CACHED` | `cache.json` | Parser that succeeded for this exact bill on a prior run |
| 1 | `COMMITTEE_PROVEN` | `cache.json` | Parsers with an established success record for this committee |
| 2 | `COST_FALLBACK` | Static | All remaining parsers sorted by `cost` (lower = cheaper) |

Tier 0 is highest trust: the same parser that found a document before is tried first. This is both an optimization and a consistency property; re-runs are stable unless the source document has changed.

### Committee Learning

The cache tracks per-committee parser statistics:
- `count`: total successes for this parser on this committee
- `current_streak`: consecutive successes (resets to 0 on any other parser succeeding)

A parser is promoted to Tier 1 for a committee when `streak ≥ 3` and `count ≥ 5`. This prevents short-lived flukes from polluting the ranking. A new committee, or one where document sourcing practices have recently changed, begins at Tier 2 until a pattern is established.

### Cost Ordering

Each parser class declares an integer `cost` attribute (1-5, lower = cheaper). In Tier 2, all unproven parsers are sorted ascending by cost. Parsers that hit a single URL on a page the tool already has cached score 1-2; parsers that must download binary files or traverse deep document trees score 4-5. This ordering reduces network load on the common case where a cheap parser succeeds.

### Committee Attribution Validation

Before accepting a vote record, the pipeline validates that the document is attributable to the target committee. `_detect_vote_committee()` scans the first 20 lines of document text for committee name patterns. Longest alias match wins (see §4). If a detected committee does not match the target, the result is rejected and the pipeline continues to the next parser.

**Limitation:** If no committee name is detectable (e.g., a PDF with only a vote tally table), attribution falls back to accepting the document. In such cases the audit log records that attribution could not be verified.

### LLM Confidence Gating

After a parser returns a result, the pipeline decides whether to invoke the LLM (§9) for confirmation based on the parser's tier and the committee's learning state:

- **Tier 0**: Skip LLM unless `confidence < 0.3`
- **Tier 1, learning phase** (`streak < 3` OR `count < 5`): Always invoke
- **Tier 1, established**: Invoke only if `confidence < 0.5`
- **Tier 2**: Always invoke

This means the LLM is most active on unfamiliar parsers and committees, and becomes progressively less active as the committee's parser profile stabilizes.

---

## 6. Ruleset Engine

The ruleset (`components/ruleset.py`) classifies each bill via four composable rules applied in priority order. Each rule implements an abstract base class with `check()`, `is_deal_breaker()`, and optional `requires_special_handling()` / `get_special_state()` methods.

**Rules and their priorities:**

| Rule | Priority | Deal-breaker | Special handling |
|---|---|---|---|
| `NoticeRequirementRule` | 1 | Yes (insufficient notice) | Yes (missing data) |
| `ReportedOutRequirementRule` | 2 | No | Yes (before deadline) |
| `SummaryRequirementRule` | 4 | No | No |
| `VoteRequirementRule` | 5 | No | No |

House committees skip `NoticeRequirementRule` (zero-day requirement is structural, not evaluated). The factory in `RuleFactory.create_rule_set(context)` constructs the appropriate list for each committee type.

**Aggregation:** See [RULESET194.md](RULESET194.md) for the full plain-English logic. Technically, `aggregate_to_compliance()` proceeds as follows:

1. Run all rules in priority order, collecting `RuleResult` objects
2. On any deal-breaker failure, return immediately with `NON_COMPLIANT`
3. If any rule signals special handling and its condition holds, return its `get_special_state()` (typically `UNKNOWN`)
4. Count the number of core requirements satisfied (reported-out, votes, summary)
5. All three satisfied → `COMPLIANT`; any missing → `NON_COMPLIANT` with concatenated reason string

**Session Constants (`Constants194`)** encode hardcoded legislative deadlines for the 194th Session: the notice requirement implementation date (2025-06-26), Senate joint-committee report-out cutoffs, and the J24 (Healthcare Finance) anomalous referral rule.

---

## 7. Document Cache and Storage

### In-Memory URL Cache (`DecayingUrlCache`)

`components/interfaces.py` implements a hybrid LRU+LFU in-memory cache for HTML responses. The eviction score for each entry is:

```
score = hit_count / (current_time - last_access_time + 1)
```

Low scores (infrequently accessed or long-idle entries) are evicted first. Eviction triggers when total memory crosses 90% of the 512 MB cap, reducing to 70% of cap. The cache is protected by an `RLock` for thread safety.

**Request deduplication:** When multiple threads request the same URL simultaneously, only the first thread issues the network request. Subsequent threads block on a `threading.Event` and receive the cached result when the first completes. The cache tracks `dedup_waits` for audit logging.

### Persistent Document Cache

Fetched binary documents (PDFs, DOCX) are written to disk under `cache/document_cache/`. Storage is content-addressed: the on-disk filename is `SHA256(content)`. The `cache.json` index records per-URL metadata: `etag`, `last_modified`, `access_count`, and `file_size_bytes`.

On subsequent runs, the cache issues conditional HTTP requests (`If-None-Match` / `If-Modified-Since`) for documents older than `validate_after_days`. A 304 response reuses the cached copy without re-downloading. Documents older than `max_age_days` are evicted from the index (the disk file may remain until a separate cleanup pass).

The content-addressed scheme means that two different URLs pointing to the same document (e.g., a hearing summary accessible from both the bill page and the committee page) store only one copy on disk and are linked via the index.

### Parser Result Cache (`cache.json`)

A single JSON file (`cache/cache.json`) records which parser succeeded per bill and which parsers have proven track records per committee. The structure is:

```json
{
  "bill_parsers": {
    "<bill_id>": {
      "summary": { "module": "...", "confirmed": true, "result": {...} },
      "votes_by_committee": {
        "<committee_id>": { "votes": { "module": "...", "result": {...} } }
      }
    }
  },
  "committee_parsers": {
    "<committee_id>": {
      "summary": { "<module_name>": { "count": 12, "current_streak": 4, "last_used": "..." } }
    }
  }
}
```

Votes are keyed by committee ID because the same bill can have different vote records for different committees (e.g., a joint bill referred to both chambers). The cache is written atomically after each bill completes using an `RLock`. When the active legislative session changes, the cache is archived to `cache/archive/<session>/cache.json` and a fresh cache is started.

---

## 8. Artifact Persistence and Re-analysis

### Storage

`history/` persists all raw source data collected for a bill in a DuckDB database (`bill_artifacts.db`). The schema separates artifact types into related tables:

- `bill_artifacts`: one row per (bill, session, committee); holds bill metadata
- `hearing_records`, `timeline_actions`, `extension_records`: normalized action data
- `document_artifacts`: one row per discovered document; includes `parser_module`, `parser_version`, `confidence`, `content_hash`, `full_content` (JSON-serialized)
- `artifact_snapshots`: compliance state at each processing run
- `document_index`: denormalized search-optimized view
- `vote_participants`: per-legislator vote records

Every `document_artifact` row records the parser version at the time of collection, so it is possible to identify which findings may be affected by a parser change.

### Re-analysis

`BillArtifactEvaluator` (`history/evaluator.py`) reconstructs the inputs to the ruleset from stored artifacts without re-scraping:

- `reconstitute_to_status()` rebuilds `BillStatus` from timeline actions
- `reconstitute_documents()` rebuilds `SummaryInfo` and `VoteInfo` from stored `full_content` fields
- `recompute_compliance()` passes the reconstituted inputs through the current `classify()` call

This enables retroactive re-analysis: if the ruleset changes (e.g., a new session constant is added), historical bills can be re-evaluated against the updated logic without re-scraping the Legislature website. The audit trail records both the original classification and any subsequent recomputations.

---

## 9. LLM Integration

The optional LLM component (`components/llm.py`) acts as a **confidence booster for document classification, not a compliance evaluator**. It never makes a compliance determination. Its sole role is to validate that a document a parser has proposed actually appears to be what it claims to be (a bill summary, a vote record).

### Mechanism

`LLMParser.make_decision(content, doc_type, bill_id)` calls a local [Ollama](https://ollama.com) instance (default: `localhost:11434`, model: `qwen3:4b`). It sends a short text excerpt — aggressively truncated to prevent token expansion and timeout — and expects a `yes / no / unsure` response.

Truncation strategy (applied in order until the excerpt is under 200 characters):
1. First 1-2 complete sentences
2. First 15 words
3. First 200 characters verbatim

The response is parsed by scanning for the last occurrence of `yes`, `no`, or `unsure` in the output (the model may reason before concluding). An `unsure` or `None` response is treated as "no confidence boost" — the pipeline falls back to the parser's intrinsic confidence score.

LLM inference is disabled by default (`config.yaml: llm.enabled: false`). The pipeline's gating logic (§5) further controls when calls are made even when the LLM is available.

### Limitations

**The LLM response is non-deterministic.** At temperature 0.1 the model is close to deterministic but not guaranteed. Two identical inputs may receive different responses across model versions or hardware configurations. For this reason:

- LLM decisions are logged verbatim to `config.audit_log.file` with the truncated input, raw response, and final decision
- A rejected document due to LLM decision can be overridden via the human-in-the-loop review (§10)
- No compliance state is solely determined by an LLM call

The model is configured locally; network calls to third-party inference endpoints are not made.

---

## 10. Human-in-the-Loop Review

When parser confidence is low and the LLM either disagrees or is unavailable, the pipeline can defer the decision for human review. Three modes are supported (configured via `config.yaml: review_mode`):

| Mode | Behavior |
|---|---|
| `off` | Auto-accept with `needs_review=True` flag; human review never presented |
| `on` | Interactive UI prompt per document during collection; forces `max_workers=1` |
| `deferred` | Accumulates all uncertain cases in a `DeferredReviewSession`, presents them as a batch after collection completes |

### Batch Review (`deferred` mode)

`DeferredReviewSession` is a thread-safe container (protected by a `Lock`) that accumulates `DeferredConfirmation` objects during the multi-threaded collection phase. Each confirmation stores: bill ID, parser type, module name, the `DiscoveryResult` candidate, a preview excerpt, and the parser's confidence score.

After collection, `conduct_batch_review()` presents each pending confirmation in turn:
- 15 lines of preview text, wrapped at 80 characters
- Parser confidence (if shown in config)
- Options: accept (`y`), reject (`n`), skip (`s`), accept all remaining (`a`), quit (`q`)

`apply_review_results()` writes accepted decisions back to `cache.json` with `confirmed=True`. Rejected decisions are not cached; the bill will be reattempted on the next run. Skipped decisions are left with `needs_review=True`.

This design ensures that human reviewers see all uncertain cases in context, rather than making ad-hoc per-document decisions while collection is still running.

---

## 11. Audit Logging

`components/auditing.py` implements structured logging across five independent writers, all coordinated by a `RunLogger` context manager. Each run writes to a timestamped directory: `out/runs/YYYY-MM-DD_HH-MM-SS_<mode>_<committees>/`.

| Writer | File | Format | Content |
|---|---|---|---|
| `ManifestWriter` | `manifest.json` | JSON | Run ID, version, start/end times, config snapshot, bill count, success rate |
| `ParserAnalyticsWriter` | `parser_analytics.json` | JSON | Per-parser: attempts, successes, tier usage, avg confidence, avg duration |
| `BillProcessingWriter` | `bill_processing.jsonl` | JSONL | One record per bill: stage, duration (ms), parser module, success/failure |
| `ErrorLedgerWriter` | `errors.json` | JSON | Structured errors: type, message, stack trace, recoverable flag, context |
| `PerformanceWriter` | `performance.json` | JSON | Named timers and metrics with min/max/avg/total aggregation |

All writers are fail-safe: write errors are caught and do not propagate. A logging failure does not affect the compliance run. Old run directories are cleaned up based on `config.yaml: audit_log.retention_days`.

The `RunLogger` also captures Python `WARNING`-and-above log events emitted anywhere in the application and routes them to the error ledger with full context tags (`bill_id`, `committee_id`, `parser_module`) set via thread-local context managers.

---

## 12. Unit Testing

Tests live in `unit/` and use `pytest`. The suite is designed to be fast and deterministic: no live network calls are made in standard test runs.

### Factory Pattern

`unit/fixtures/` provides three core factories:

- **`BillFactory`**: Programmatically constructs `BillStatus`, `SummaryInfo`, and `VoteInfo` objects for specific compliance scenarios. Fluent helpers like `create_noncompliant_bill(missing=[Requirement.VOTES])` produce consistent, named test inputs.
- **`TimelineFactory`**: Constructs `BillActionTimeline` objects with specific action sequences.
- **`DateScenarios`**: Provides pre-computed deadline and transition dates for a given session, parameterized by committee type.

### Cassettes

Parsers and collectors are tested against recorded HTML responses stored as cassette files in `unit/cassettes/`. A cassette is a saved HTTP response body written to disk during an initial recording run. Tests replay from cassettes, making parser tests reproducible regardless of live site changes. When the Legislature redesigns a page, the affected cassette is re-recorded and the test is updated to match.

### Key Test Suites

- `test_compliance_rules.py`: Each rule in isolation, including edge cases (before/after deadline, missing data, deal-breaker short-circuiting)
- `test_deadline_calculation.py`: Full deadline arithmetic across House, Senate, Joint, and J24 scenarios, with and without extensions
- `test_joint_rule_10_edge_cases.py`: Session-specific edge cases for Joint Rule 10 cutoff behavior
- `test_notice_requirements.py`: Notice gap computation and the pre-2025-06-26 exemption
- `test_timeline.py`: `ActionNode` matching, normalization, and hearing inference
- `test_real_bills.py`: Integration tests using YAML-encoded real bills from the Legislature; asserts known compliance states have not regressed

---

## 13. Limitations and Caveats

### Scraping Fragility

All data is scraped from `malegislature.gov`. HTML structure changes on the Legislature's site will break affected collectors and parsers. The cassette-based test suite detects regressions, but only after re-recording is triggered manually.

### Committee Attribution Heuristics

Vote document attribution (§5) is based on committee name matching in the first 20 lines of a document. This heuristic can fail in two ways:

1. **False rejection**: A legitimate vote record where the committee name does not appear in the header (e.g., minimally formatted PDFs) will be rejected, causing the bill to appear as missing votes.
2. **False acceptance**: A document mentioning multiple committees in its header could in principle be attributed to the wrong one.

Both failure modes are logged. False rejections can be corrected via the human-in-the-loop review (§10) or by recording the parser result in `cache.json` with `confirmed=True`.

### LLM Non-Determinism

As described in §9, LLM responses at low temperature are close to but not strictly deterministic. Cross-run reproducibility should not be assumed when `llm.enabled: true`. Audit logs record every LLM call, so divergences between runs can be identified and investigated.

### Session-Specific Constants

`Constants194` in `components/ruleset.py` encodes deadlines specific to the 194th Legislative Session. These values must be updated at the start of each new session. The code does not automatically detect session boundaries for the purpose of applying the correct ruleset constants.

### Extension Order Fallback

When the extension order collector's primary regex fails (§2), it falls back to heuristic line scanning. Orders detected via the fallback path are flagged with `is_fallback=True` and should be manually verified.
