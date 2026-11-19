# Controlled retry scenario — before

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
  "timestamp": "2026-11-19T19:07:57.209Z",
  "session_id": "eb4af9a7-a89a-4f55-8d11-341cf479f6de",
  "request_id": "9bd1c1df-958d-4394-b092-c690d01e0435",
  "question": "When does the simulated campus office open?",
  "answer": "Simulated grounded answer from campus_document.txt.",
  "status": "success",
  "retrieval_ms": 0.01737500133458525,
  "generation_ms": 3010.530250001466,
  "duration_ms": 3011.140707996674,
  "prompt_tokens": 12,
  "output_tokens": 5,
  "cache_hit": false,
  "error": null
}
```

## Verification

- Retry metric fields present: `False`
- Scenario check: `MET`
