# Acceptance Criteria

This document defines what “working” means for The Unofficial Guide. The
criteria were written before their corresponding evaluation runs so results
could be judged against fixed targets rather than adjusted after the fact.

## RAG quality criteria

These criteria cover the original retrieval and grounding behavior.

| # | Criterion | Target | Why this target |
|---|---|---|---|
| 1 | Retrieved context contains the answer | At least 4 of 5 in-scope questions retrieve a chunk containing the answer. | The corpus contains short, focused documents, so the correct topic should be retrieved consistently while allowing one difficult query. |
| 2 | Answers identify their evidence | Every generated answer names at least one source document. | Source metadata is already available to the generation prompt, so an unsourced answer is not acceptable. |
| 3 | Unsupported questions are refused | At least 4 of 5 clearly out-of-scope questions return the standard refusal. | Embedding similarity can occasionally produce an accidental match, but unrelated questions should normally be stopped before generation. |
| 4 | Chunks preserve complete thoughts | All 5 sampled chunks begin and end with complete sentences. | The campus documents are short enough to remain intact, so arbitrary mid-sentence splits would add retrieval noise without providing useful granularity. |
| 5 | Supported questions reach generation | All 5 in-scope questions pass the relevance gate. | Each question asks for information explicitly present in the indexed corpus. |

The original retrieval evaluation evidence is preserved in:

- [Before improvement](../results/run_2026-09-27_1944_before.md)
- [After improvement](../results/run_2026-09-27_2247_after.md)

## Observability acceptance criteria

Each criterion below must pass in **three independent trials**. These are the
formal targets used by run_capstone_eval.py.

### 1. Every request produces one complete log record

**Target:** In each trial, one successful request, one relevance refusal, and
one controlled failure must add exactly three JSONL lines. Each line must parse
as JSON and contain the original 13 required schema fields with valid UUIDs, a
UTC timestamp, a valid status, and values or null appropriate to that status.
The current extended schema contains 17 fields after retry instrumentation.

**Why:** Successes, refusals, and errors take different paths through
ask_pipeline(). Missing, duplicated, or malformed records would make every
later measurement unreliable.

**Verification:** Compare line counts before and after the three requests,
parse only the appended lines, and validate field names, types, IDs, timestamps,
questions, and statuses.

### 2. Warm uncached requests meet an interactive latency target

**Target:** Start a fresh process, run one unscored uncached warm-up, then run
five genuine uncached in-scope questions. At least 4 of 5 must complete within
4,000 ms, and all 5 must complete within 7,000 ms.

**Why:** The CLI is interactive, so most answers should arrive within a few
seconds. The two-part target allows normal network variation without hiding one
extremely slow request behind an average.

**Verification:** Run the same five questions in three fresh processes with
AI201_CACHE=0, then read duration_ms from the scored success records and
confirm every cache_hit value is false.

### 3. Per-request token and cache accounting matches session totals

**Target:** Start with an empty cache, ask three distinct in-scope questions,
and immediately repeat one. Fresh generations must record positive prompt and
output token counts, and their sum must exactly match the session totals. The
repeat must be a cache hit with zero new tokens and leave the totals unchanged.

**Why:** Tokens are the primary operational cost measurement. Counts attributed
to the wrong request would make both request-level and session-level reporting
misleading.

**Verification:** Compare every request record with generate.token_counts(),
sum the three cache misses, and confirm the repeated request does not change
the total.

### 4. Failures are diagnosable without leaking sensitive details

**Target:** A controlled generation exception containing a unique sensitive
canary must be re-raised to the caller and produce exactly one error record.
The record must include the exception type, a safe public message, and every
timing or usage value known before failure. It must not contain the canary or
raw exception message.

**Why:** Operational logs need enough context to diagnose the failing stage,
but provider payloads, URLs, API keys, and other exception details must not be
copied into stored records.

**Verification:** Trigger a different canary-bearing exception in each trial,
catch the original exception, validate the appended record, and search its
serialized JSON for the canary.

### 5. Request and session identifiers survive process restarts correctly

**Target:** Preserve the existing log, run two requests in process A, then two
in process B. All request IDs must be valid and unique. Records within a
process must share one session ID, the two process session IDs must differ, and
the previous log bytes must remain unchanged with exactly four lines appended.

**Why:** Request IDs trace one question; session IDs group work from one
application process. The append-only file must retain evidence across restarts.

**Verification:** Use refusal requests so no Gemini call is required. Compare
the original byte prefix and line count, then validate the four UUIDs and their
process groupings.

## Formal evaluation results

| Criterion | Baseline | After retry instrumentation |
|---|---:|---:|
| Logging completeness | PASS | PASS |
| End-to-end latency | PASS | PASS |
| Token and cache accuracy | PASS | **FAIL** |
| Failure observability | PASS | PASS |
| Session and request tracking | PASS | PASS |

The baseline passed all five criteria in all three trials. The post-improvement
run passed 14 of 15 individual trials and four of five criteria overall.
Criterion 3 missed in its second trial because provider rate limiting exhausted
the cache-seeding request before it produced a response. With nothing available
to cache, the repeat required another live generation. The other two cache
trials correctly recorded zero-token hits.

Complete reports and raw evidence:

- [Baseline report](../results/capstone_eval_before.md)
- [Baseline JSON](../results/capstone_eval_before.json)
- [Baseline JSONL](../results/capstone_eval_before.jsonl)
- [Post-improvement report](../results/capstone_eval_after.md)
- [Post-improvement JSON](../results/capstone_eval_after.json)
- [Post-improvement JSONL](../results/capstone_eval_after.jsonl)
