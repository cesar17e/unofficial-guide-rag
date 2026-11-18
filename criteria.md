# Acceptance criteria — The Unofficial Guide

Five criteria that say what "working" means for this system, written in unit 1
**before** any results existed.

An acceptance criterion names a target: a number, a count, a rate, or something
a person could plainly observe. *"Retrieval works"* is an opinion. *"For at
least 4 of my 5 test questions, the top results include a chunk containing the
answer"* is a criterion.

Under each one, write a sentence or two on **why that target** and not a
stricter or looser one. A reason that says something about your corpus or your
pipeline earns credit; *"80% seemed reasonable"* does not.

> Missing your own targets next unit costs you nothing. Setting a target so
> easy you can't miss it does.

---

## 1. Retrieved chunks contain the answer

For at least 4 of my 5 test questions, the retrieved chunks include one that
contains the answer.

**Why this target:**
The `campus_life` documents are short and usually focus on one specific topic, and each of my five questions asks about information directly stated in the corpus. I chose 4 of 5 because retrieval should find the correct single topic document most of the time while still allowing one difficult query.

---

## 2. Every answer names a source

Every answer the system produces names at least one source document.

**Why this target:**
Every generated answer is based on chunks retrieved from documents that already have a source metadata. Since the pipeline has the source available when generating an answer, I expect all answers it produces to name at least one source rather than accepting occasional unsourced answers.

---

## 3. The relevance gate stops out-of-corpus questions

When I ask a question my documents clearly don't cover, the relevance gate
stops it and the system returns "I don't have enough information about that" —
in at least 4 of 5 tries.

**Why this target:**
The five out-of-scope questions are intentionally unrelated to the `campus_life` corpus, so the relevance gate should reject most of them.
I chose 4 of 5 because embedding similarity can still produce an accidental close match even when a question is unrelated to the corpus.

---

## 4. Something about your chunks

All 5 of 5 sampled chunks should contain complete sentences without beginning or ending in the middle of a sentence.
     
**Why this target:**
The `campus_life` documents are short, averaging about 317 characters, and most contain only a few related sentences. Because the documents are already small, I expect the chunker to preserve complete sentences rather than splitting them in the middle.

---

## 5. Your choice

All 5 in-scope questions in `questions.py` should pass the relevance gate and reach answer generation.

**Why this target:**
Each of the five in-scope questions asks about information directly present in the campus_life corpus. Since the relevance gate is meant to block unsupported questions, I expect all five supported questions to pass the gate and reach answer generation.

---

<!-- ─────────────────────────────────────────────────────────────────────────
     UNIT 2 — read this before you change anything above.

     If a criterion turns out to be BROKEN rather than merely unmet, you can
     revise it, and that earns credit. But never delete or edit the original
     line. Add the revision underneath it, like this:

         ## 1. Retrieved chunks contain the answer

         For at least 4 of my 5 test questions, the retrieved chunks include
         one that contains the answer.

         **Why this target:** ...

         > **Revised in unit 2:** For at least 4 of 5 questions, the top three
         > results contain the answer.
         >
         > **Why revised:** I couldn't judge "the chunks include one that
         > contains the answer" the same way twice — I scored two questions
         > differently on Monday than on Wednesday. The new version is
         > something I can actually check.

     That's a revision because the criterion couldn't be MEASURED.

     Lowering a target because you missed it is not a revision, and it costs
     you the point:

         ✗ "I said 4 of 5 but got 2 of 5, so 2 of 5 is more realistic."

     A number you missed stays where it is, gets diagnosed, and gets a fix
     attempted. That's where the points are.

     The whole reason the originals stay visible is so someone can see what you
     said before you knew the answer.
     ───────────────────────────────────────────────────────────────────────── -->

## Capstone Acceptance Criteria

The target for each criterion below must be met in each of three independent
trials, not only when the results of all three trials are combined.

---

### 1. Every request produces one complete log record

In each trial, I will execute one successful in-scope request, one
relevance-gate refusal, and one controlled failure. The log must gain exactly
three lines: one per request and no duplicates. Every line must parse as JSON
and contain all 13 fields in `SCHEMA_FIELDS` with valid UUIDs, a UTC timestamp,
a valid status, and values or `null` appropriate to that status.

**Why this target:**
Successes, refusals, and errors follow different paths through `ask_pipeline()`,
so testing all three is necessary. Logging is deterministic infrastructure;
accepting a missing, duplicated, or malformed record would make later
measurements unreliable.

**How to test:**
Record the JSONL line count before each trial, execute the three requests, and
parse only the appended lines using Python's standard `json` and `uuid`
modules. Match each record's question and status to its execution and validate
its field names and types.

---

### 2. Warm uncached questions return within an interactive response-time limit

In each trial, I will start a new process, run one unscored uncached in-scope
request to warm the embedding model, index, and Gemini client, and then run
five genuine uncached in-scope questions. At least 4 of the 5 measured requests
must finish within 4,000 ms, and all 5 must finish within 7,000 ms.

**Why this target:**
The CLI is interactive, so most answers should arrive within a few seconds.
The 4-second target is demanding but allows some Gemini network variation,
while the 7-second ceiling prevents one very slow request from being hidden by
an average. Cold-start latency is excluded from the target but must still be
recorded and reported separately.

**How to test:**
Use `AI201_CACHE=0` and the same five questions in three fresh processes. Read
`duration_ms` from the five scored `success` records in each session and
confirm `cache_hit` is `false`. This target is not guaranteed by the
preliminary run; it must be tested again.

---

### 3. Per-request token and cache accounting agrees with session totals

In each trial, I will start a new process with an empty or isolated response
cache, ask three distinct in-scope questions with caching enabled, and
immediately repeat one question. Each fresh generation must record
`cache_hit: false` with positive integer prompt and output token counts. Their
per-request token sums must exactly equal the session totals. The repeated
request must record `cache_hit: true`, zero prompt tokens, zero output tokens,
and leave the session totals unchanged.

**Why this target:**
Token counts are the project's primary operational cost measurement. Exact
agreement is required because a count accidentally carried over from another
request would make both individual costs and session totals misleading. A
cache hit must not be presented as new Gemini usage.

**How to test:**
After each request, compare its JSONL record with `generate.token_counts()` or
the final CLI session summary. Sum only the three cache-miss records, then
confirm the cached repeat does not change that sum.

---

### 4. Controlled failures leave useful records without leaking exception details

In each trial, I will trigger a controlled generation failure whose raw
exception message contains a unique canary value that represents sensitive
information. The original exception must still reach the caller, and exactly
one log record must be written with `status: "error"`, `answer: null`, the
correct exception type, a nonempty safe message, and all timing and usage
values known before the failure. The canary and raw exception message must not
appear anywhere in the JSONL record.

**Why this target:**
A failure record should identify the affected request, exception type, and
stage timing well enough to support diagnosis, but logs should not copy API
keys, provider payloads, URLs, or other sensitive exception text. Preserving
the original exception also ensures instrumentation does not change
application behavior.

**How to test:**
Use a mock that raises a known exception after retrieval begins, with a
different canary in each trial. Catch the re-raised exception, parse the one
appended record, verify its fields and available timings, and search its
serialized JSON for the canary.

---

### 5. Session and request IDs remain correct across restarts

In each trial, I will preserve a byte-for-byte copy of the existing log, run
two requests in process A, stop it, and run two more in process B. All four
request IDs must be valid and unique. Each process's two records must share one
session ID, the session IDs for processes A and B must differ, and the existing
log content must remain unchanged with exactly four new records appended.

**Why this target:**
Request IDs allow one question to be traced, while session IDs group related
activity from one running application. Restarting must create a new session
without overwriting earlier evidence because the shared JSONL file is intended
to preserve multiple runs.

**How to test:**
Use refusal requests so this check does not require Gemini calls. Compare the
log's original byte prefix and line count before and after both processes,
then validate and group the four appended UUIDs.
