# Running The Unofficial Guide

The Unofficial Guide is a local retrieval-augmented generation (RAG)
application. It searches a Chroma vector index built from the included campus
documents and sends grounded context to Gemini. The command line is the primary
way to run it. An optional Flask interface exposes the same pipeline over HTTP.

## Verified environment

The instructions below were verified with:

- Python 3.12.15
- macOS, using a standard Python virtual environment
- the exact direct dependency versions in `requirements.txt`
- the bundled `all-MiniLM-L6-v2` ONNX embedding model

Python 3.12 is recommended. Python 3.11 and 3.13 may also work with the pinned
packages, but Python 3.12.15 is the version verified for this capstone.

## Clone the repository

```bash
git clone https://github.com/cesar17e/unofficial-guide-rag.git
cd unofficial-guide-rag
```

## Install on macOS or Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

If your Python 3.12 executable is named `python3`, use `python3` in the first
command instead.

## Install on Windows PowerShell

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Activate the virtual environment again whenever you open a new terminal. The
shell prompt normally begins with `(.venv)` while it is active.

## Configure Gemini

Open `.env` and replace the placeholder with your own Gemini API key:

```text
GEMINI_API_KEY=your_key_here
AI201_CORPUS=campus_life
```

Do not add quotation marks around the key. `.env` is ignored by Git and should
never be pasted into source code, logs, screenshots, or commits.

Generation requires internet access to the Gemini API. Document loading,
embedding after the initial model download, Chroma storage, and retrieval run
locally.

## Embedding model and disk requirements

The default embedding model is `all-MiniLM-L6-v2`, provided by Chroma as an
ONNX model. It produces 384-dimensional embeddings. Its compressed first-use
download is approximately 80 MB; the extracted model cache occupied about
166 MB in the verified environment. Chroma downloads it from:

```text
chroma-onnx-models.s3.amazonaws.com
```

The first environment check or indexing run therefore needs internet access.
Later embedding runs use the locally cached model. The project virtual
environment is roughly 400 MB, excluding normal package-manager caches, and the
generated Chroma index for the included corpus is small by comparison.

## Verify the environment

The full environment check verifies Python, pinned packages, the API key, the
embedding model, Chroma, and one real Gemini request:

```bash
python test.py
```

The isolated instrumentation tests use mocks and make no Gemini or Chroma
calls:

```bash
python -m unittest discover -s tests -v
```

## Build the search index

The local Chroma index is generated and is not stored in Git. Build it after a
fresh clone, after changing corpora, or after changing chunking:

```bash
python app.py index
```

For the default `campus_life` corpus this loads 88 documents, keeps each short
document as one chunk, creates local embeddings, and writes a cosine-distance
collection under `chroma_db/`.

To build another included corpus:

```bash
python app.py --corpus city_guides index
```

## Ask questions from the command line

Ask one question:

```bash
python app.py ask "What time does Halden Hall close?"
```

Start an interactive session and continue until you submit an empty line:

```bash
python app.py ask
```

Useful commands:

| Command | Purpose |
|---|---|
| `python app.py corpora` | List the included corpora |
| `python app.py index` | Build the default Chroma index |
| `python app.py ask "question"` | Run retrieval, gating, and generation once |
| `python app.py ask` | Run an interactive question session |
| `python app.py retrieve "question"` | Inspect retrieval results without calling Gemini |
| `python app.py chunks` | Inspect representative chunks |
| `python app.py ask "question" --show-prompt` | Display the grounded prompt sent to Gemini |

Global options such as `--corpus` and `--variant` go before the subcommand:

```bash
python app.py --corpus campus_life --variant default ask "When does the shuttle run?"
```

## Structured JSONL logs

Every execution of `ask_pipeline()` attempts to append one JSON object to:

```text
logs/rag_runs.jsonl
```

The directory is created on the first logged question. The file is append-only
across sessions and is ignored by Git. Each line can be parsed independently
and contains:

| Field | Meaning |
|---|---|
| `timestamp` | UTC ISO 8601 completion time |
| `session_id` | UUID generated once for the application process |
| `request_id` | UUID generated for this question |
| `question` | Input text |
| `answer` | Generated answer, refusal, or `null` on failure |
| `status` | `success`, `refused`, or `error` |
| `retrieval_ms` | Chroma retrieval duration in milliseconds |
| `generation_ms` | Generation duration, or `null` if generation was not reached |
| `duration_ms` | Total pipeline duration in milliseconds |
| `prompt_tokens` | Gemini input tokens consumed by this request |
| `output_tokens` | Gemini output tokens consumed by this request |
| `cache_hit` | Whether generation was served from the response cache |
| `api_attempts` | Actual Gemini API calls attempted for this request |
| `retry_count` | Provider-triggered backoff waits for this request |
| `retry_wait_ms` | Measured time spent in provider-retry backoff |
| `rate_limit_wait_ms` | Measured time spent waiting for the local per-minute limiter |
| `error` | Safe error type/message, or `null` |

A relevance-gate refusal records zero tokens and `cache_hit: null` because
Gemini was not called. It also records zero API attempts, retries, and wait
time. A cached answer records zero newly consumed tokens, zero API attempts,
retries, and wait time, and `cache_hit: true`. A failure before generation
leaves generation-only measurements as `null`; once generation begins, all
known attempts and waits are preserved even if every retry fails. Unknown
measurements remain `null` rather than being estimated.

Both wait fields use the actual elapsed time measured by
`time.perf_counter()`. They are not calculated by simply adding the requested
sleep durations. `retry_wait_ms` covers exponential backoff after provider
pushback. `rate_limit_wait_ms` covers proactive waiting by this application's
local request-per-minute limiter.

Inspect recent records on macOS or Linux:

```bash
tail -n 5 logs/rag_runs.jsonl
```

Inspect the latest record on any platform with Python:

```bash
python -c "import json,pathlib; p=pathlib.Path('logs/rag_runs.jsonl'); print(json.dumps(json.loads(p.read_text(encoding='utf-8').splitlines()[-1]), indent=2))"
```

The log contains complete questions and answers. Treat it as local application
data and review it before sharing excerpts.

## Response caching

Caching is enabled by default and stores generated responses under `.cache/`.
Repeating an identical grounded prompt can therefore avoid another Gemini
request.

Disable caching for one command on macOS or Linux:

```bash
AI201_CACHE=0 python app.py ask "What time does Halden Hall close?"
```

Disable caching for a PowerShell session:

```powershell
$env:AI201_CACHE = "0"
python app.py ask "What time does Halden Hall close?"
Remove-Item Env:AI201_CACHE
```

You can also place `AI201_CACHE=0` in `.env` temporarily. Uncached runs make a
real Gemini request when the relevance gate passes and count against the
configured rate and session budgets.

## Optional local HTTP service

The CLI remains the primary run path. To expose the same `ask_pipeline()`
function locally over HTTP:

```bash
python serve.py
```

Then, from another terminal:

```bash
curl http://localhost:5000/health
curl -X POST http://localhost:5000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What time does Halden Hall close?"}'
```

On macOS or Linux, Gunicorn is also installed for a production-style local
process:

```bash
gunicorn serve:app
```

## Rate limits and usage guards

`generate.py` protects outgoing Gemini calls in several ways:

- No more than 30 outgoing attempts per minute from one application process.
- A 300-call session budget stops unexpected runaway loops.
- Rate-limit responses are retried up to four times with exponential backoff.
- Repeated prompts may be served from the local cache.
- Session-wide calls and tokens are printed when the CLI question process
  exits; per-request values are also stored in the JSONL log.

If the application prints a rate-limit waiting message, leave it running. A
`429` or resource-exhausted response normally means the provider quota needs
time to recover, not that the API key is invalid.

For a reproducible instrumentation-only check, run:

```bash
python run_retry_scenario.py --label after
```

This scenario is explicitly simulated: it performs no live retrieval and no
Gemini request. A provider stub returns two synthetic `429` failures followed
by a fixed response while the real retry loop, actual 1- and 2-second sleeps,
pipeline integration, and JSONL logger run normally. It writes
`results/retry_scenario_after.jsonl` and refuses to overwrite an existing
file. Use it to inspect retry fields, not as live model-quality evidence.

## Project structure

| Path | Purpose |
|---|---|
| `app.py` | CLI commands and the shared instrumented `ask_pipeline()` |
| `serve.py` | Optional Flask wrapper around `ask_pipeline()` |
| `config.py` | Corpus, model, retrieval, caching, and path settings |
| `ingest.py` | Loads and cleans corpus documents |
| `chunker.py` | Converts documents into chunks |
| `store.py` | Local embeddings, Chroma storage, semantic retrieval, and BM25/RRF reranking |
| `gate.py` | Refuses questions whose best retrieval distance is above the threshold |
| `generate.py` | Grounded Gemini calls, caching, retries, rate limiting, and token accounting |
| `observability.py` | Append-only structured JSONL logging helper |
| `run_retry_scenario.py` | Controlled simulated retry scenario for instrumentation comparisons |
| `corpora/` | Source documents included with the project |
| `tests/` | Mocked instrumentation, usage, cache, failure, and concurrency tests |
| `logs/rag_runs.jsonl` | Generated local request records; ignored by Git |
| `chroma_db/` | Generated local vector index; ignored by Git |
| `.cache/` | Generated response cache; ignored by Git |
| `results/` | Earlier committed evaluation evidence |

## Troubleshooting

| Symptom | Resolution |
|---|---|
| `No index called ...` | Run `python app.py index` for the same corpus and variant |
| `No GEMINI_API_KEY found` | Create `.env` from `.env.example` and add the key without quotes |
| `No corpus at ...` | Run `python app.py corpora` and use one of the listed names |
| Every question is refused | Confirm the correct index is selected; then inspect distances with `retrieve` |
| Nothing is refused | Inspect retrieval distances; the configured threshold may be too permissive |
| First indexing run is slow | The approximately 80 MB embedding model may still be downloading |
| `429` or resource exhausted | Wait for the printed backoff or retry after the provider quota resets |
| `QuotaGuard` after 300 calls | Stop and inspect the caller for a loop before changing the budget |
| No JSONL file | A question has not reached `ask_pipeline()`, or a visible logging error was printed |
| Cache unexpectedly used | Run with `AI201_CACHE=0` and confirm `cache_hit` in the JSONL record |

For reproducibility, run setup commands from the repository root and use the
same corpus and index variant for both indexing and questions.
