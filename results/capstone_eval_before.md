# Capstone baseline evaluation — before

- Started: 2026-11-18T20:29:40Z
- Finished: 2026-11-18T20:30:49Z
- Python: 3.12.15
- Gemini model: `gemini-3.5-flash-lite`
- Raw JSONL: `results/capstone_eval_before.jsonl`
- Detailed JSON: `results/capstone_eval_before.json`
- Model attempts: 30

Each criterion was evaluated in three fresh trials. Successful answer records
came from genuine Gemini responses. The only injected behavior was a controlled exception
for the failure-observability criterion; it was not treated as an answer.

## Verdicts

| Criterion | Trial 1 | Trial 2 | Trial 3 | Overall |
|---|---|---|---|---|
| 1. Logging completeness | PASS | PASS | PASS | **PASS** |
| 2. End-to-end latency | PASS | PASS | PASS | **PASS** |
| 3. Token accounting and cache accuracy | PASS | PASS | PASS | **PASS** |
| 4. Failure observability | PASS | PASS | PASS | **PASS** |
| 5. Session and request tracking | PASS | PASS | PASS | **PASS** |

## Criterion 1: Logging completeness

Evidence produced by `app.py::ask_pipeline and observability.py::JsonlRequestLogger.log_request`.

- Trial 1 — **PASS:** 3/3 records; statuses ['success', 'refused', 'error']; schema [True, True, True]
- Trial 2 — **PASS:** 3/3 records; statuses ['success', 'refused', 'error']; schema [True, True, True]
- Trial 3 — **PASS:** 3/3 records; statuses ['success', 'refused', 'error']; schema [True, True, True]

## Criterion 2: End-to-end latency

Evidence produced by `app.py::ask_pipeline using time.perf_counter`.

- Trial 1 — **PASS:** 5/5 within 4,000 ms; max 1985.30 ms; [811.73 ms, 1985.30 ms, 1252.29 ms, 837.82 ms, 1749.60 ms]
- Trial 2 — **PASS:** 5/5 within 4,000 ms; max 1753.91 ms; [1753.91 ms, 774.40 ms, 1668.03 ms, 793.91 ms, 714.05 ms]
- Trial 3 — **PASS:** 5/5 within 4,000 ms; max 980.44 ms; [840.96 ms, 756.22 ms, 782.26 ms, 980.44 ms, 790.88 ms]

## Criterion 3: Token accounting and cache accuracy

Evidence produced by `generate.py::generate, _record_tokens, request_usage, and token_counts`.

- Trial 1 — **PASS:** request sum {'prompt': 2043, 'output': 118, 'total': 2161}; session {'prompt': 2043, 'output': 118, 'total': 2161}; cache {'cache_hit': True, 'prompt_tokens': 0, 'output_tokens': 0}
- Trial 2 — **PASS:** request sum {'prompt': 2043, 'output': 121, 'total': 2164}; session {'prompt': 2043, 'output': 121, 'total': 2164}; cache {'cache_hit': True, 'prompt_tokens': 0, 'output_tokens': 0}
- Trial 3 — **PASS:** request sum {'prompt': 2043, 'output': 114, 'total': 2157}; session {'prompt': 2043, 'output': 114, 'total': 2157}; cache {'cache_hit': True, 'prompt_tokens': 0, 'output_tokens': 0}

## Criterion 4: Failure observability

Evidence produced by `app.py::ask_pipeline and observability.py::safe_error`.

- Trial 1 — **PASS:** error {'type': 'ControlledGenerationError', 'message': 'The question could not be completed.'}; timings 56.66 ms/0.07 ms/56.75 ms; canary absent=True
- Trial 2 — **PASS:** error {'type': 'ControlledGenerationError', 'message': 'The question could not be completed.'}; timings 65.43 ms/0.08 ms/65.53 ms; canary absent=True
- Trial 3 — **PASS:** error {'type': 'ControlledGenerationError', 'message': 'The question could not be completed.'}; timings 57.40 ms/0.15 ms/57.58 ms; canary absent=True

## Criterion 5: Session and request tracking

Evidence produced by `observability.py::SESSION_ID, new_request_id, and JsonlRequestLogger.log_request`.

- Trial 1 — **PASS:** sessions 4ea4e816-e2bd-49bf-9433-9019b4825881 / 5733df89-c3d0-4439-a854-553baf858b9a; 4 IDs unique=True; prefix preserved=True
- Trial 2 — **PASS:** sessions 7df3eb73-b15e-45ac-99ba-f5bf96c5bcb9 / 8508c255-97fe-4ccc-8807-fc243ae7faeb; 4 IDs unique=True; prefix preserved=True
- Trial 3 — **PASS:** sessions 31206727-bf9c-4775-aebe-92cb77015094 / 1110ce46-0813-4f99-82d6-f13ec3f4da99; 4 IDs unique=True; prefix preserved=True

## Raw evidence

Every answer, refusal, error, identifier, timing, and token count is preserved
as one unedited JSON object per line in `results/capstone_eval_before.jsonl`.
