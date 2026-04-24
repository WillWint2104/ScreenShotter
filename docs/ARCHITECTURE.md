# ScreenShotter — System Architecture

Version: 1.0
Status: Locked for build
Last updated: 2026-04-24

---

## System Purpose

ScreenShotter is a trusted evidence acquisition layer.

It captures the full visible state of a task review page in a browser,
organises that captured evidence into structured sections, validates
the quality of the capture, and produces outputs that downstream systems
can consume without manual repair.

It does not reason about the content it captures.
It does not evaluate task responses.
It does not produce payloads, scores, or project cartridges.
It acquires and organises evidence. Nothing more.

---

## Hard Responsibility Boundary

### ScreenShotter owns

- Browser and window discovery
- Page profile management
- Scrollable section discovery
- Safe expansion of collapsed content
- Screenshot capture per section
- Section tagging and metadata
- Screenshot batching by section
- Capture quality validation
- Improvement recommendations (human-reviewed only)

### ScreenShotter does not own

- Payload construction
- Project cartridge generation
- Logic alignment reasoning
- Final task evaluation
- FEval generation
- Response scoring
- Dimension scoring
- Field filling
- Any reasoning about what the captured content means

These responsibilities belong to downstream systems.
ScreenShotter hands them clean, structured, tagged evidence.
What those systems do with that evidence is not ScreenShotter's concern.

---

## Critical Boundary: Capture Validator is not a Task Evaluator

The Capture Validator assesses the quality of the capture process only.

### Capture Validator assesses

- Whether all expected sections were found and captured
- Whether screenshots are complete (no missing content at page bottom)
- Whether OCR quality is sufficient for downstream use
- Whether section boundaries are clean (no contamination)
- Whether any sections are duplicated or missing
- Overall capture confidence

### Capture Validator never assesses

- Whether Response A is better than Response B
- Whether a task response is correct
- Whether scoring criteria are met
- Whether project instructions are followed
- Any dimension of task quality

This boundary is permanent. It must not be eroded in future builds.
If a future feature request asks the Capture Validator to reason about
content quality or task correctness, that feature belongs in a
downstream system, not here.

---

## Layer Model

```text
LAYER 0 — DATA & CONFIG
Raw files. No logic. Two sibling top-level directories:
  data/sessions/       Per-session capture outputs
  data/evaluations/    Accumulated capture validation results
  data/improvements/   Improvement reports and approved changes
  config/              Profiles, rules, parameters (peer of data/, not inside it)

LAYER 1 — FOUNDATION
  uia_utils.py
    Stable internal API for Windows UI Automation.
    Used by all layers above it.
    Finds browser windows, queries scrollable elements,
    scrolls via UIA ScrollPattern, detects protected elements.
    Written for downstream reuse across discovery,
    profile management, expansion, and field mapping.

LAYER 2 — PROFILE
  profile_manager.py
    Fingerprints the current page using multiple signals.
    Matches against saved profiles.
    Never hard-commits a match — always uses assisted mode.
    Tracks proficiency per profile over time.

LAYER 3 — DISCOVERY
  section_discoverer.py
    Finds all scrollable sections in the active browser window.
    Uses profile rules if a profile is matched.
    Falls back to general heuristics if no profile matched.
    Returns classified section list with confidence scores.

LAYER 4 — EXPANSION
  expander.py
    Expands collapsed content before capture begins.
    Requires all four safety conditions before clicking anything.
    Logs every expansion attempt with pre/post state.

LAYER 5 — CAPTURE ENGINE
  capture_engine.py    (reused from ScrollCapture)
  scroll_logic.py      (extended with UIA ScrollPattern)
  file_manager.py      (reused)
  manifest_writer.py   (extended with section metadata)
  tagger.py
    Producer (capture_engine + scroll_logic + file_manager):
      Captures each section completely.
      Scrolls via UIA element reference, not keyboard input.
      Emits section metadata alongside each screenshot, but writes no
      persistent tag.
    Consumer (tagger.py):
      Sole writer of persistent section tags.
      Consumes emitted metadata and applies tags to images and the
      manifest. Every screenshot belongs to exactly one section tag
      when tagger.py is done.

LAYER 6 — BATCHER
  batcher.py
    Groups screenshots by section tag.
    Enforces section purity rules.
    Produces batch.json per session.

LAYER 7 — CAPTURE VALIDATOR
  capture_validator.py
    Assesses capture quality only (see boundary above).
    Produces evaluation.json per session.
    Feeds confidence score back to profile proficiency.

LAYER 8 — IMPROVEMENT ENGINE
  improvement_engine.py
    Reads accumulated evaluation results.
    Identifies failure patterns across sessions.
    Produces human-reviewable recommendations only.
    Never modifies profiles or parameters automatically.
```

---

## Contamination Rules

A failure in Layer N affects Layer N only.
Higher layers read outputs. They never receive push from lower layers.
A capture failure never corrupts a profile.
A profile mismatch never corrupts a session's raw screenshots.
A batcher grouping error never affects the underlying screenshot files.

---

## Profile System

### Purpose

Page structure varies across task types and applications.
Profiles encode learned knowledge about a specific page type
so the system improves with use rather than starting from scratch
every time.

### Profile match behaviour — Option C (silent assisted mode)

When a profile match is found above threshold:
- Profile is loaded silently
- General heuristics remain active as fallback
- Which profile was used is recorded in the session manifest
- No interruption to the capture workflow
- User can review and correct profile attribution after capture
- Corrections feed the improvement engine

When no profile match is found:
- General heuristics used
- Session is treated as a new page type candidate
- After successful capture and validation, user may save as new profile

### Fingerprinting — multiple signals required

No single signal determines a profile match.
The following are used together:

- URL pattern (domain and stable path pattern, not full URL)
- Scrollable container count
- Approximate container geometry ratios
- Landmark words present in the page
- Visible field label cluster signature
- Repeated section header token signature
- Major layout region count

Match confidence is a weighted combination of all signals.
A match is only suggested when combined confidence exceeds threshold.

### Profile match output

```json
{
  "profile_matched": true,
  "profile_name": "task_review_v1",
  "profile_match_confidence": 0.91,
  "profile_match_reason": [
    "url_pattern_match",
    "container_count_match",
    "field_label_signature_match",
    "section_header_tokens_match"
  ],
  "mode": "assisted"
}
```

### Proficiency rules

A profile is considered proficient only when both conditions are met:

- proficiency_score >= 0.85
- successful_sessions >= 5

Proficiency score is weighted toward recent sessions.
Early sessions carry less weight than recent ones.
Repeated failures decrease proficiency score.
A profile that drops below threshold is flagged for review.

---

## Expander Safety Rules

The expander must satisfy all four conditions before clicking any element:

1. Element is not on the protected list
2. Element is near a likely content section (not browser chrome)
3. Element appears expandable by role or visual affordance
4. Post-click state change is detected

### State change detection

After clicking, the expander checks for:
- Region height increase
- New text appearing in the container
- Scroll height increase
- Chevron or expanded-state change in the element

If no meaningful state change is detected:
- Element is marked as false expansion candidate
- Same element is not retried
- Logged as action_result: no_change

### Protected elements — never clicked under any circumstances

Any element whose name or accessible value contains any of the following tokens:

- abort
- back
- cancel
- close
- complete
- dismiss
- done
- escape
- finish
- flag
- next
- skip
- submit

Case-insensitive matching.
Kept alphabetised for easier diffing.
This list is additive — future entries only, never removed.

### Expansion log format

```json
{
  "element_name": "...",
  "element_role": "...",
  "container_id": "...",
  "pre_height": 0,
  "post_height": 0,
  "state_changed": true,
  "action_result": "expanded | no_change | blocked"
}
```

Every expansion attempt is logged.

---

## Capture Validator Output Contract

```json
{
  "capture_complete": true,
  "section_scores": {
    "conversation_history": {
      "found": true,
      "confidence": 0.91,
      "screenshot_count": 8,
      "ocr_quality": 0.88,
      "issues": []
    }
  },
  "missing_sections": [],
  "duplicate_sections": [],
  "ocr_quality": {
    "overall": 0.84,
    "by_section": {}
  },
  "overall_capture_confidence": 0.87,
  "recommended_action": "accept | review | retry"
}
```

This output is for capture quality assessment only.
It must never include task scores, response comparisons,
dimension ratings, or any content-level judgements.

---

## Batcher Section Purity Rules

### Required output groups

- instructions
- prompt
- conversation_history
- response_a
- response_b
- examples
- ui_fields
- buttons
- unknown

### Purity rules

- ui_fields and buttons are never merged into response content groups
- prompt is never merged into conversation_history
- response_a and response_b are never merged
- instructions are never merged into examples
- Any screenshot with low-confidence classification goes to unknown
- unknown is never force-fitted into any named section

Contamination across section boundaries is a critical failure.
The batcher must flag contamination explicitly rather than
silently placing content in the wrong group.

---

## Improvement Engine Constraints

### May do

- Detect patterns across accumulated evaluation results
- Summarise recurring failure types
- Recommend profile edits
- Recommend capture parameter adjustments
- Recommend expander trigger word additions
- Recommend UIA search depth changes

### May never do

- Modify profiles automatically
- Modify capture parameters automatically
- Auto-apply expander rules
- Auto-change classification thresholds
- Make any system change without human review and approval

### Approval workflow

Improvement engine produces `improvement_report_{date}.json`.
Human reviews each recommendation.
Approved changes are recorded in `approved_changes_{date}.json`.
Changes are applied manually or via a dedicated apply step.
Every applied change is traceable to a specific recommendation.

---

## Data Structure

```text
screenshotter/
  app/
    core/
      capture_engine.py
      scroll_logic.py
      file_manager.py
      manifest_writer.py
      section_discoverer.py
      expander.py
      tagger.py
      batcher.py
      capture_validator.py
      improvement_engine.py
      profile_manager.py
      rule_manager.py
    models/
      section.py
      batch.py
      evaluation.py
      improvement.py
      profile.py
      capture_config.py
      capture_session.py
    ui/
      main_window.py
      discovery_panel.py
      capture_progress.py
      evaluation_panel.py
      improvement_panel.py
    utils/
      uia_utils.py
      screen_utils.py
      paths.py
      logging_utils.py
      image_utils.py
  data/
    sessions/
      {session_id}/
        screenshots/
        manifest.json
        batch.json
        evaluation.json
    evaluations/
    improvements/
  config/
    profiles/
      default.json
    classification_rules.json
    capture_params.json
    improvement_history.json
  docs/
    ARCHITECTURE.md
    ROOT_PROBLEM.md
  requirements.txt
  launch.py
  run_app.bat
```

---

## Build Order

```text
Spec 1   uia_utils.py              Foundation UIA API
Spec 2   models/                   All data models before logic
Spec 3   profile_manager.py        Profile layer
Spec 4   section_discoverer.py     Discovery using profile + heuristics
Spec 5   expander.py               Safe expansion with state change detection
Spec 6   tagger.py                 Section metadata per screenshot
Spec 7   batcher.py                Section grouping with purity rules
Spec 8   capture_validator.py      Capture quality assessment only
Spec 9   improvement_engine.py     Pattern detection and recommendations
```

Nothing is built without the spec for that layer being reviewed first.
Nothing is incorporated without its own assessment passing.

---

## Success Standard

The Full Capture system is considered production-ready when:

- All nine specs are built and pass their assessments
- A profile reaches proficiency on a real task page
  (score >= 0.85, sessions >= 5)
- Capture Validator consistently returns
  `recommended_action: accept` on proficient profiles
- Batcher produces zero contamination flags
  on proficient profile sessions
- Improvement Engine has produced at least one
  human-approved recommendation that improved
  a subsequent session's capture confidence
