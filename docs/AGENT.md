# Agent Architecture

## Cycle Flow

1. **Parse notes** -- `note_reader.parse_notes` decodes and hashes the file.
   `as_of` defaults to the header date; missing both raises `CycleError`.
2. **Memory OFF check** -- if `memory_enabled=False`, skip all DB writes and
   return status `dry_run` after extraction only (no open actions loaded).
3. **Duplicate / resume check** -- `get_meeting_by_hash` looks up the hash.
   If the cycle is already `proposed` or `committed`, return `already_processed`
   with zero LLM calls. If the cycle is `extracted` (crashed earlier), resume it.
   Otherwise `add_meeting` and `create_cycle`.
4. **Injection guard** -- `find_suspicious_lines` scans the parsed doc.
   Each suspicious line is replaced in the prompt copy by
   `"[line withheld: instruction-like text]"` and a warning is added.
   The original doc is preserved for `verify_quote`.
5. **LLM call 1 (extract)** -- `prompts.build_extract_user` builds the prompt;
   `llm.call("extract.v1")` runs it; response is validated against
   `ExtractionResult`. Per-item validation:
   - `source_line` must exist and not be a suspicious line.
   - `is_grounded` must pass.
   - Unknown owner becomes `None` with `needs_clarification`.
   - Confidence below 0.6 forces `needs_clarification`.
   - `resolve_due` converts `due_text`; unparseable gives `due_date=None`.
   - Items beyond the 30-item cap are dropped with a warning.
6. **Load open actions** -- `get_open_actions` returns current team actions.
   Each is annotated with `classify_due` and `days_overdue`.
   Order: blocked / needs_clarification / overdue first, then by action_id.
7. **LLM call 2 (decide)** -- skipped when there are no open actions;
   all valid extracted items become `new_action` deterministically.
   Otherwise `build_decide_user` builds the prompt and `llm.call("decide.v1")` runs it.
   Per-decision validation:
   - `action_id` must be a known open action for this team.
   - `extracted_index` must be in range.
   - `close_with_evidence` and `mark_blocked` require a verified, non-suspicious
     evidence quote; failures downgrade to `ask_question`.
   - Duplicate decisions for the same action: later ones dropped.
   - Open action without any decision: auto-assigned `carry_over`.
   - `carry_over` on an overdue action escalates to `draft_reminder`.
   - Valid extracted items not referenced by any decision become `new_action`.
8. **Build proposals** -- owner and due_date from extracted items (never replacing
   existing values with None). `save_proposals` writes to DB and advances cycle
   to `proposed`.
9. **Approval gate** -- human calls `decide_proposal` (approved / edited / rejected),
   then `commit_approved` executes the effective payload via `commit_proposal`.
   Nothing is applied until the human approves.

## Guards

| Guard | Function | Rule protected |
|---|---|---|
| Suspicious-line detection | `is_suspicious_line` | Flags instruction-injection attempts |
| Prompt withholding | `withhold_lines` | Keeps injected text out of LLM context |
| Groundedness check | `is_grounded` | Prevents invented actions not in the notes |
| Evidence relevance | `evidence_is_relevant` | Ensures close/block evidence matches the action |
| Quote verification | `verify_quote` (note_reader) | Ensures evidence_quote is verbatim from notes |
| Team-scoped DB queries | All store functions | Team isolation: no cross-team data leakage |

## Follow-up-first Ordering

Proposals and open actions are sorted so blocked, `needs_clarification`, and
overdue items appear first, then remaining items by action_id. This ensures the
agent addresses the most urgent follow-ups in each meeting cycle.

## Injection Defence -- Honest Limits

The guards are defence in depth, not a complete solution:

- Suspicious-line detection uses a fixed regex list. A novel phrasing not in the
  list will not be caught. Extend `SUSPICIOUS_PATTERNS` in `guards.py` as new
  patterns emerge.
- `is_grounded` catches fully invented actions but not subtle paraphrases of
  real note text.
- Evidence verification (`verify_quote`) prevents the LLM from citing text that
  does not exist, but the LLM could still selectively quote out of context.
- The approval gate is the real control. All LLM output is pending until a human
  explicitly approves each proposal. No action is created or updated without
  that approval.
