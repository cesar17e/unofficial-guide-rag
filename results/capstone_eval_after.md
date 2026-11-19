# Capstone evaluation — after

- Started: 2026-11-19T19:08:27Z
- Finished: 2026-11-19T19:09:43Z
- Python: 3.12.15
- Gemini model: `gemini-3.5-flash-lite`
- Raw JSONL: `results/capstone_eval_after.jsonl`
- Detailed JSON: `results/capstone_eval_after.json`
- Model attempts: 39

Each criterion was evaluated in three fresh trials. Successful answer records
came from genuine Gemini responses. The only injected behavior was a controlled exception
for the failure-observability criterion; it was not treated as an answer.

## Verdicts

| Criterion | Trial 1 | Trial 2 | Trial 3 | Overall |
|---|---|---|---|---|
| 1. Logging completeness | PASS | PASS | PASS | **PASS** |
| 2. End-to-end latency | PASS | PASS | PASS | **PASS** |
| 3. Token accounting and cache accuracy | PASS | FAIL | PASS | **FAIL** |
| 4. Failure observability | PASS | PASS | PASS | **PASS** |
| 5. Session and request tracking | PASS | PASS | PASS | **PASS** |

## Criterion 1: Logging completeness

Evidence produced by `app.py::ask_pipeline and observability.py::JsonlRequestLogger.log_request`.

- Trial 1 — **PASS:** 3/3 records; statuses ['success', 'refused', 'error']; schema [True, True, True]
- Trial 2 — **PASS:** 3/3 records; statuses ['success', 'refused', 'error']; schema [True, True, True]
- Trial 3 — **PASS:** 3/3 records; statuses ['success', 'refused', 'error']; schema [True, True, True]

## Criterion 2: End-to-end latency

Evidence produced by `app.py::ask_pipeline using time.perf_counter`.

- Trial 1 — **PASS:** 5/5 within 4,000 ms; max 922.97 ms; [698.32 ms, 922.97 ms, 594.35 ms, 633.83 ms, 716.21 ms]
- Trial 2 — **PASS:** 5/5 within 4,000 ms; max 3688.80 ms; [722.80 ms, 854.67 ms, 856.29 ms, 766.31 ms, 3688.80 ms]
- Trial 3 — **PASS:** 5/5 within 4,000 ms; max 3983.78 ms; [2006.66 ms, 3983.78 ms, 506.05 ms, 579.54 ms, 822.23 ms]

## Criterion 3: Token accounting and cache accuracy

Evidence produced by `generate.py::generate, _record_tokens, request_usage, and token_counts`.

- Trial 1 — **PASS:** request sum {'prompt': 2043, 'output': 117, 'total': 2160}; session {'prompt': 2043, 'output': 117, 'total': 2160}; cache {'cache_hit': True, 'prompt_tokens': 0, 'output_tokens': 0}
- Trial 2 — **FAIL:** request sum {'prompt': 1324, 'output': 83, 'total': 1407}; session {'prompt': 2043, 'output': 111, 'total': 2154}; cache {'cache_hit': False, 'prompt_tokens': 719, 'output_tokens': 28}
- Trial 3 — **PASS:** request sum {'prompt': 2043, 'output': 112, 'total': 2155}; session {'prompt': 2043, 'output': 112, 'total': 2155}; cache {'cache_hit': True, 'prompt_tokens': 0, 'output_tokens': 0}

## Criterion 4: Failure observability

Evidence produced by `app.py::ask_pipeline and observability.py::safe_error`.

- Trial 1 — **PASS:** error {'type': 'ControlledGenerationError', 'message': 'The question could not be completed.'}; timings 53.14 ms/0.06 ms/53.20 ms; canary absent=True
- Trial 2 — **PASS:** error {'type': 'ControlledGenerationError', 'message': 'The question could not be completed.'}; timings 59.32 ms/0.07 ms/59.40 ms; canary absent=True
- Trial 3 — **PASS:** error {'type': 'ControlledGenerationError', 'message': 'The question could not be completed.'}; timings 58.32 ms/0.05 ms/58.38 ms; canary absent=True

## Criterion 5: Session and request tracking

Evidence produced by `observability.py::SESSION_ID, new_request_id, and JsonlRequestLogger.log_request`.

- Trial 1 — **PASS:** sessions 09bd5cf6-8335-48d5-b490-86c058d50243 / dff22aff-3b0e-4ea3-ac7f-f6161e8095e7; 4 IDs unique=True; prefix preserved=True
- Trial 2 — **PASS:** sessions 6c55cad8-62a1-463b-82d5-8f067ac54ac8 / 57e99932-0abf-4d5d-b902-09c63f533969; 4 IDs unique=True; prefix preserved=True
- Trial 3 — **PASS:** sessions 55542112-fa78-428d-91e1-f6f0a682f3a4 / 73dd957a-f5bb-4c3f-a54c-6d46ca862410; 4 IDs unique=True; prefix preserved=True

## Raw evidence

Every answer, refusal, error, identifier, timing, and token count is preserved
as one unedited JSON object per line in `results/capstone_eval_after.jsonl`.
