# Controlled retry scenario — after

> SIMULATED SCENARIO: no Gemini request and no live retrieval will run.

Two synthetic provider `429` responses were followed by one fixed
successful response. The application's real retry loop and sleeps ran.

## Retry console output

```text
  [rate limit] service pushed back. Retrying in 1s (attempt 1 of 4).
  [rate limit] service pushed back. Retrying in 2s (attempt 2 of 4).
```

## Structured JSONL record

```json
{
  "timestamp": "2026-11-19T19:08:07.554Z",
  "session_id": "a95ca66a-c0d9-4107-a3c6-cb0e4269800f",
  "request_id": "d81966ad-9f59-4c6f-9824-82900f3cb3c5",
  "question": "When does the simulated campus office open?",
  "answer": "Simulated grounded answer from campus_document.txt.",
  "status": "success",
  "retrieval_ms": 0.01737500133458525,
  "generation_ms": 3009.193290999974,
  "duration_ms": 3009.769625001354,
  "prompt_tokens": 12,
  "output_tokens": 5,
  "cache_hit": false,
  "api_attempts": 3,
  "retry_count": 2,
  "retry_wait_ms": 3008.7179170077434,
  "rate_limit_wait_ms": 0.0,
  "error": null
}
```

## Verification

- Retry metric fields present: `True`
- Scenario check: `MET`
