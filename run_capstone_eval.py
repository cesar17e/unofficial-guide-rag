#!/usr/bin/env python3
"""Evaluate the Unit 9 capstone instrumentation against its five criteria.

Usage:

    python run_capstone_eval.py --label before
    python run_capstone_eval.py --label after

The parent process launches fresh Python processes for independent trials. Each
worker redirects the application's real JSONL logger to one label-specific file
under ``results/`` so older preliminary logs remain untouched. No generated
answer is mocked. The only injected exception is the controlled failure that
Criterion 4 explicitly requires.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"
WORKER_MARKER = "CAPSTONE_WORKER_RESULT="
TRIALS = 3
WARMUP_QUESTION = "How much printing credit does each student receive per semester?"


class ControlledGenerationError(RuntimeError):
    """Synthetic provider failure used only for the failure-observability check."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def configure_worker(log_path: Path, *, cache_enabled: bool, cache_dir: Path | None):
    """Point the real application logger and cache at evaluation-owned paths."""
    import config
    import observability

    config.CACHE_ENABLED = cache_enabled
    if cache_dir is not None:
        config.CACHE_DIR = cache_dir

    observability._default_logger.close()
    observability._default_logger = observability.JsonlRequestLogger(log_path=log_path)

    import app
    import generate

    return app, generate, observability


def execute_question(app_module, question: str) -> dict[str, Any]:
    """Run the genuine application pipeline and retain a safe outcome summary."""
    try:
        outcome = app_module.ask_pipeline(question)
        return {
            "completed": True,
            "refused": outcome["refused"],
            "answer": outcome["answer"],
        }
    except Exception as exc:  # noqa: BLE001 - failures are evaluation evidence
        return {
            "completed": False,
            "exception_type": type(exc).__name__,
        }


def run_core_worker(args) -> dict[str, Any]:
    """Produce evidence for Criteria 1, 2, and 4 in one fresh process."""
    app, generate, observability = configure_worker(
        Path(args.log_path), cache_enabled=False, cache_dir=None
    )
    import questions

    started = len(read_records(Path(args.log_path)))
    warmup = execute_question(app, WARMUP_QUESTION)

    criterion1_start = len(read_records(Path(args.log_path)))
    scored_runs = [execute_question(app, questions.QUESTIONS[0]["question"])]
    refusal = execute_question(app, questions.OUT_OF_SCOPE[0])

    canary = f"CAPSTONE_PRIVATE_{args.label.upper()}_TRIAL_{args.trial}"
    controlled = ControlledGenerationError(canary)
    reraised_same_object = False
    caught_type = None
    with patch.object(generate, "_get_client", side_effect=controlled):
        try:
            app.ask_pipeline(questions.QUESTIONS[2]["question"])
        except Exception as exc:  # noqa: BLE001 - identity is part of the criterion
            reraised_same_object = exc is controlled
            caught_type = type(exc).__name__

    criterion1_end = len(read_records(Path(args.log_path)))

    for item in questions.QUESTIONS[1:5]:
        scored_runs.append(execute_question(app, item["question"]))

    ended = len(read_records(Path(args.log_path)))
    observability._default_logger.close()
    return {
        "kind": "core",
        "trial": args.trial,
        "start": started,
        "end": ended,
        "warmup_index": started,
        "criterion1_start": criterion1_start,
        "criterion1_end": criterion1_end,
        "latency_indices": [criterion1_start, *range(criterion1_end, ended)],
        "failure_index": criterion1_start + 2,
        "warmup_outcome": warmup,
        "scored_outcomes": scored_runs,
        "refusal_outcome": refusal,
        "failure": {
            "canary": canary,
            "expected_type": type(controlled).__name__,
            "caught_type": caught_type,
            "reraised_same_object": reraised_same_object,
        },
        "model_attempts": generate.call_count(),
        "token_totals": generate.token_counts(),
    }


def run_cache_worker(args) -> dict[str, Any]:
    """Produce Criterion 3 evidence in a fresh process and isolated cache."""
    app, generate, observability = configure_worker(
        Path(args.log_path),
        cache_enabled=True,
        cache_dir=Path(args.cache_dir),
    )
    import questions

    started = len(read_records(Path(args.log_path)))
    outcomes = []
    totals = []
    selected = questions.QUESTIONS[:3]
    for item in selected:
        outcomes.append(execute_question(app, item["question"]))
        totals.append(generate.token_counts().copy())

    outcomes.append(execute_question(app, selected[0]["question"]))
    totals.append(generate.token_counts().copy())

    ended = len(read_records(Path(args.log_path)))
    observability._default_logger.close()
    return {
        "kind": "cache",
        "trial": args.trial,
        "start": started,
        "end": ended,
        "indices": list(range(started, ended)),
        "outcomes": outcomes,
        "totals_after_each_request": totals,
        "model_attempts": generate.call_count(),
    }


def run_tracking_worker(args) -> dict[str, Any]:
    """Write two refusals so process-level identifier behavior can be checked."""
    app, generate, observability = configure_worker(
        Path(args.log_path), cache_enabled=False, cache_dir=None
    )
    import questions

    pair = questions.OUT_OF_SCOPE[:2] if args.process_name == "A" else questions.OUT_OF_SCOPE[2:4]
    started = len(read_records(Path(args.log_path)))
    outcomes = [execute_question(app, question) for question in pair]
    ended = len(read_records(Path(args.log_path)))
    observability._default_logger.close()
    return {
        "kind": "tracking",
        "trial": args.trial,
        "process_name": args.process_name,
        "start": started,
        "end": ended,
        "indices": list(range(started, ended)),
        "outcomes": outcomes,
        "model_attempts": generate.call_count(),
    }


def worker_main(args) -> int:
    if args.worker == "core":
        result = run_core_worker(args)
    elif args.worker == "cache":
        result = run_cache_worker(args)
    else:
        result = run_tracking_worker(args)
    print(WORKER_MARKER + json.dumps(result, ensure_ascii=False))
    return 0


def run_worker(
    *,
    label: str,
    trial: int,
    kind: str,
    log_path: Path,
    cache_dir: Path | None = None,
    process_name: str | None = None,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--label",
        label,
        "--worker",
        kind,
        "--trial",
        str(trial),
        "--log-path",
        str(log_path),
    ]
    if cache_dir is not None:
        command += ["--cache-dir", str(cache_dir)]
    if process_name is not None:
        command += ["--process-name", process_name]

    process = subprocess.run(
        command,
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )
    marker_lines = [line for line in process.stdout.splitlines() if line.startswith(WORKER_MARKER)]
    if process.returncode != 0 or not marker_lines:
        return {
            "worker_error": True,
            "kind": kind,
            "trial": trial,
            "process_name": process_name,
            "returncode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
    result = json.loads(marker_lines[-1][len(WORKER_MARKER) :])
    result["worker_stdout"] = "\n".join(
        line for line in process.stdout.splitlines() if not line.startswith(WORKER_MARKER)
    )
    result["worker_stderr"] = process.stderr
    return result


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def valid_uuid(value: Any) -> bool:
    try:
        UUID(value)
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def valid_timestamp(value: Any) -> bool:
    try:
        return isinstance(value, str) and value.endswith("Z") and datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).utcoffset() is not None
    except ValueError:
        return False


def validate_schema(record: dict[str, Any], schema_fields: tuple[str, ...]) -> bool:
    if tuple(record) != schema_fields:
        return False
    if not valid_timestamp(record["timestamp"]):
        return False
    if not valid_uuid(record["session_id"]) or not valid_uuid(record["request_id"]):
        return False
    if not isinstance(record["question"], str):
        return False
    if record["status"] not in {"success", "refused", "error"}:
        return False
    for field in (
        "retrieval_ms",
        "generation_ms",
        "duration_ms",
        "retry_wait_ms",
        "rate_limit_wait_ms",
    ):
        if record[field] is not None and not is_number(record[field]):
            return False
    for field in ("prompt_tokens", "output_tokens", "api_attempts", "retry_count"):
        value = record[field]
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            return False
    if record["cache_hit"] not in {True, False, None}:
        return False
    if record["status"] == "error":
        if record["answer"] is not None:
            return False
        error = record["error"]
        if not isinstance(error, dict) or set(error) != {"type", "message"}:
            return False
        if not all(isinstance(value, str) and value.strip() for value in error.values()):
            return False
    elif not isinstance(record["answer"], str) or record["error"] is not None:
        return False
    return True


def evaluate_criterion_1(core: dict[str, Any], records: list[dict[str, Any]], schema_fields):
    if core.get("worker_error"):
        return {"passed": False, "reason": "core worker failed", "records_added": None}
    start, end = core["criterion1_start"], core["criterion1_end"]
    selected = records[start:end]
    expected_statuses = ["success", "refused", "error"]
    schema_checks = [validate_schema(record, schema_fields) for record in selected]
    request_ids = [record.get("request_id") for record in selected]
    passed = (
        end - start == 3
        and len(selected) == 3
        and [record.get("status") for record in selected] == expected_statuses
        and all(schema_checks)
        and len(set(request_ids)) == 3
    )
    return {
        "passed": passed,
        "records_added": end - start,
        "line_numbers": list(range(start + 1, end + 1)),
        "statuses": [record.get("status") for record in selected],
        "schema_valid": schema_checks,
        "request_ids": request_ids,
    }


def evaluate_criterion_2(core: dict[str, Any], records: list[dict[str, Any]]):
    if core.get("worker_error"):
        return {"passed": False, "reason": "core worker failed", "durations_ms": []}
    warmup = records[core["warmup_index"]] if core["warmup_index"] < len(records) else None
    selected = [records[index] for index in core["latency_indices"] if index < len(records)]
    durations = [record.get("duration_ms") for record in selected]
    valid_runs = (
        len(selected) == 5
        and all(record.get("status") == "success" for record in selected)
        and all(record.get("cache_hit") is False for record in selected)
        and all(is_number(value) for value in durations)
    )
    within_4000 = sum(value <= 4000 for value in durations if is_number(value))
    maximum = max((value for value in durations if is_number(value)), default=None)
    warmup_valid = bool(
        warmup
        and warmup.get("status") == "success"
        and warmup.get("cache_hit") is False
    )
    passed = valid_runs and warmup_valid and within_4000 >= 4 and maximum <= 7000
    return {
        "passed": passed,
        "warmup_valid": warmup_valid,
        "warmup_duration_ms": warmup.get("duration_ms") if warmup else None,
        "line_numbers": [index + 1 for index in core["latency_indices"]],
        "durations_ms": durations,
        "within_4000_ms": within_4000,
        "maximum_ms": maximum,
        "all_successful_uncached": valid_runs,
    }


def evaluate_criterion_3(cache: dict[str, Any], records: list[dict[str, Any]]):
    if cache.get("worker_error"):
        return {"passed": False, "reason": "cache worker failed"}
    selected = [records[index] for index in cache["indices"] if index < len(records)]
    fresh = selected[:3]
    repeated = selected[3] if len(selected) == 4 else None
    fresh_valid = len(fresh) == 3 and all(
        record.get("status") == "success"
        and record.get("cache_hit") is False
        and isinstance(record.get("prompt_tokens"), int)
        and record["prompt_tokens"] > 0
        and isinstance(record.get("output_tokens"), int)
        and record["output_tokens"] > 0
        for record in fresh
    )
    per_request_prompt = sum(record.get("prompt_tokens") or 0 for record in fresh)
    per_request_output = sum(record.get("output_tokens") or 0 for record in fresh)
    totals = cache.get("totals_after_each_request", [])
    final_totals = totals[-1] if totals else None
    before_repeat = totals[-2] if len(totals) >= 2 else None
    totals_match = bool(
        final_totals
        and final_totals.get("prompt") == per_request_prompt
        and final_totals.get("output") == per_request_output
        and final_totals.get("total") == per_request_prompt + per_request_output
    )
    repeat_valid = bool(
        repeated
        and repeated.get("status") == "success"
        and repeated.get("cache_hit") is True
        and repeated.get("prompt_tokens") == 0
        and repeated.get("output_tokens") == 0
        and before_repeat == final_totals
    )
    return {
        "passed": fresh_valid and totals_match and repeat_valid,
        "line_numbers": [index + 1 for index in cache["indices"]],
        "fresh_prompt_tokens": [record.get("prompt_tokens") for record in fresh],
        "fresh_output_tokens": [record.get("output_tokens") for record in fresh],
        "per_request_sum": {
            "prompt": per_request_prompt,
            "output": per_request_output,
            "total": per_request_prompt + per_request_output,
        },
        "session_totals": final_totals,
        "cache_record": {
            "cache_hit": repeated.get("cache_hit") if repeated else None,
            "prompt_tokens": repeated.get("prompt_tokens") if repeated else None,
            "output_tokens": repeated.get("output_tokens") if repeated else None,
        },
        "session_totals_unchanged": before_repeat == final_totals,
        "fresh_valid": fresh_valid,
        "totals_match": totals_match,
    }


def evaluate_criterion_4(core: dict[str, Any], records: list[dict[str, Any]]):
    if core.get("worker_error"):
        return {"passed": False, "reason": "core worker failed"}
    index = core["failure_index"]
    record = records[index] if index < len(records) else None
    failure = core["failure"]
    serialized = json.dumps(record, ensure_ascii=False) if record else ""
    safe = bool(
        record
        and failure["canary"] not in serialized
        and record.get("status") == "error"
        and record.get("answer") is None
        and record.get("error", {}).get("type") == failure["expected_type"]
        and isinstance(record.get("error", {}).get("message"), str)
        and record["error"]["message"].strip()
        and is_number(record.get("retrieval_ms"))
        and is_number(record.get("generation_ms"))
        and is_number(record.get("duration_ms"))
        and record.get("prompt_tokens") is None
        and record.get("output_tokens") is None
        and record.get("cache_hit") is False
    )
    passed = safe and failure["reraised_same_object"] and failure["caught_type"] == failure["expected_type"]
    return {
        "passed": passed,
        "line_number": index + 1,
        "error": record.get("error") if record else None,
        "retrieval_ms": record.get("retrieval_ms") if record else None,
        "generation_ms": record.get("generation_ms") if record else None,
        "duration_ms": record.get("duration_ms") if record else None,
        "known_usage": {
            "prompt_tokens": record.get("prompt_tokens") if record else None,
            "output_tokens": record.get("output_tokens") if record else None,
            "cache_hit": record.get("cache_hit") if record else None,
        },
        "canary_absent": bool(record) and failure["canary"] not in serialized,
        "original_exception_reraised": failure["reraised_same_object"],
    }


def evaluate_criterion_5(
    process_a: dict[str, Any],
    process_b: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    prefix_preserved: bool,
    records_added: int,
):
    if process_a.get("worker_error") or process_b.get("worker_error"):
        return {"passed": False, "reason": "tracking worker failed"}
    a_records = [records[index] for index in process_a["indices"] if index < len(records)]
    b_records = [records[index] for index in process_b["indices"] if index < len(records)]
    all_records = a_records + b_records
    request_ids = [record.get("request_id") for record in all_records]
    a_sessions = {record.get("session_id") for record in a_records}
    b_sessions = {record.get("session_id") for record in b_records}
    passed = (
        prefix_preserved
        and records_added == 4
        and len(a_records) == 2
        and len(b_records) == 2
        and len(request_ids) == 4
        and all(valid_uuid(value) for value in request_ids)
        and len(set(request_ids)) == 4
        and len(a_sessions) == 1
        and len(b_sessions) == 1
        and a_sessions.isdisjoint(b_sessions)
    )
    return {
        "passed": passed,
        "line_numbers": [index + 1 for index in process_a["indices"] + process_b["indices"]],
        "records_added": records_added,
        "prefix_preserved": prefix_preserved,
        "process_a_session_id": next(iter(a_sessions), None),
        "process_b_session_id": next(iter(b_sessions), None),
        "request_ids": request_ids,
        "request_ids_unique": len(set(request_ids)) == 4 if len(request_ids) == 4 else False,
    }


CRITERION_INFO = {
    "1": {
        "name": "Logging completeness",
        "producer": "app.py::ask_pipeline and observability.py::JsonlRequestLogger.log_request",
    },
    "2": {
        "name": "End-to-end latency",
        "producer": "app.py::ask_pipeline using time.perf_counter",
    },
    "3": {
        "name": "Token accounting and cache accuracy",
        "producer": "generate.py::generate, _record_tokens, request_usage, and token_counts",
    },
    "4": {
        "name": "Failure observability",
        "producer": "app.py::ask_pipeline and observability.py::safe_error",
    },
    "5": {
        "name": "Session and request tracking",
        "producer": "observability.py::SESSION_ID, new_request_id, and JsonlRequestLogger.log_request",
    },
}


def format_ms(value: Any) -> str:
    return "missing" if value is None else f"{value:.2f} ms"


def trial_summary(number: str, trial: dict[str, Any]) -> str:
    if number == "1":
        return f"{trial.get('records_added')}/3 records; statuses {trial.get('statuses')}; schema {trial.get('schema_valid')}"
    if number == "2":
        durations = ", ".join(format_ms(value) for value in trial.get("durations_ms", []))
        return f"{trial.get('within_4000_ms')}/5 within 4,000 ms; max {format_ms(trial.get('maximum_ms'))}; [{durations}]"
    if number == "3":
        return f"request sum {trial.get('per_request_sum')}; session {trial.get('session_totals')}; cache {trial.get('cache_record')}"
    if number == "4":
        return f"error {trial.get('error')}; timings {format_ms(trial.get('retrieval_ms'))}/{format_ms(trial.get('generation_ms'))}/{format_ms(trial.get('duration_ms'))}; canary absent={trial.get('canary_absent')}"
    return f"sessions {trial.get('process_a_session_id')} / {trial.get('process_b_session_id')}; 4 IDs unique={trial.get('request_ids_unique')}; prefix preserved={trial.get('prefix_preserved')}"


def write_markdown_report(result: dict[str, Any], path: Path) -> None:
    lines = [
        f"# Capstone evaluation — {result['label']}",
        "",
        f"- Started: {result['started_at']}",
        f"- Finished: {result['finished_at']}",
        f"- Python: {result['environment']['python']}",
        f"- Gemini model: `{result['environment']['model']}`",
        f"- Raw JSONL: `{result['files']['raw_jsonl']}`",
        f"- Detailed JSON: `{result['files']['json']}`",
        f"- Model attempts: {result['api_usage']['model_attempts']}",
        "",
        "Each criterion was evaluated in three fresh trials. Successful answer records",
        "came from genuine Gemini responses. The only injected behavior was a controlled exception",
        "for the failure-observability criterion; it was not treated as an answer.",
        "",
        "## Verdicts",
        "",
        "| Criterion | Trial 1 | Trial 2 | Trial 3 | Overall |",
        "|---|---|---|---|---|",
    ]
    for number, criterion in result["criteria"].items():
        cells = ["PASS" if trial["passed"] else "FAIL" for trial in criterion["trials"]]
        overall = "PASS" if criterion["passed"] else "FAIL"
        lines.append(f"| {number}. {criterion['name']} | {' | '.join(cells)} | **{overall}** |")

    for number, criterion in result["criteria"].items():
        lines += [
            "",
            f"## Criterion {number}: {criterion['name']}",
            "",
            f"Evidence produced by `{criterion['producer']}`.",
            "",
        ]
        for index, trial in enumerate(criterion["trials"], 1):
            verdict = "PASS" if trial["passed"] else "FAIL"
            lines.append(f"- Trial {index} — **{verdict}:** {trial_summary(number, trial)}")

    lines += [
        "",
        "## Raw evidence",
        "",
        "Every answer, refusal, error, identifier, timing, and token count is preserved",
        f"as one unedited JSON object per line in `{result['files']['raw_jsonl']}`.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parent_main(args) -> int:
    import config
    from observability import SCHEMA_FIELDS

    RESULTS_DIR.mkdir(exist_ok=True)
    raw_path = RESULTS_DIR / f"capstone_eval_{args.label}.jsonl"
    json_path = RESULTS_DIR / f"capstone_eval_{args.label}.json"
    markdown_path = RESULTS_DIR / f"capstone_eval_{args.label}.md"
    existing = [path for path in (raw_path, json_path, markdown_path) if path.exists()]
    if existing:
        joined = ", ".join(str(path.relative_to(ROOT)) for path in existing)
        print(f"Refusing to overwrite existing evaluation evidence: {joined}", file=sys.stderr)
        return 2

    started_at = utc_now()
    worker_runs = []
    trial_inputs = []

    for trial in range(1, TRIALS + 1):
        print(f"Trial {trial}/{TRIALS}: uncached warm-up, five latency questions, refusal, and controlled failure", flush=True)
        core = run_worker(
            label=args.label,
            trial=trial,
            kind="core",
            log_path=raw_path,
        )
        worker_runs.append(core)

        print(f"Trial {trial}/{TRIALS}: three fresh generations and one cache hit", flush=True)
        with tempfile.TemporaryDirectory(prefix=f"capstone-{args.label}-cache-{trial}-") as temp:
            cache = run_worker(
                label=args.label,
                trial=trial,
                kind="cache",
                log_path=raw_path,
                cache_dir=Path(temp),
            )
        worker_runs.append(cache)

        before_bytes = raw_path.read_bytes() if raw_path.exists() else b""
        before_records = len(read_records(raw_path))
        print(f"Trial {trial}/{TRIALS}: process restart and append-only identifier check", flush=True)
        process_a = run_worker(
            label=args.label,
            trial=trial,
            kind="tracking",
            log_path=raw_path,
            process_name="A",
        )
        process_b = run_worker(
            label=args.label,
            trial=trial,
            kind="tracking",
            log_path=raw_path,
            process_name="B",
        )
        worker_runs += [process_a, process_b]
        after_bytes = raw_path.read_bytes() if raw_path.exists() else b""
        after_records = len(read_records(raw_path))
        trial_inputs.append(
            {
                "core": core,
                "cache": cache,
                "process_a": process_a,
                "process_b": process_b,
                "prefix_preserved": after_bytes.startswith(before_bytes),
                "tracking_records_added": after_records - before_records,
            }
        )

    records = read_records(raw_path)
    criteria = {
        number: {
            "name": info["name"],
            "producer": info["producer"],
            "trials": [],
        }
        for number, info in CRITERION_INFO.items()
    }
    for item in trial_inputs:
        criteria["1"]["trials"].append(evaluate_criterion_1(item["core"], records, SCHEMA_FIELDS))
        criteria["2"]["trials"].append(evaluate_criterion_2(item["core"], records))
        criteria["3"]["trials"].append(evaluate_criterion_3(item["cache"], records))
        criteria["4"]["trials"].append(evaluate_criterion_4(item["core"], records))
        criteria["5"]["trials"].append(
            evaluate_criterion_5(
                item["process_a"],
                item["process_b"],
                records,
                prefix_preserved=item["prefix_preserved"],
                records_added=item["tracking_records_added"],
            )
        )
    for criterion in criteria.values():
        criterion["passed"] = all(trial["passed"] for trial in criterion["trials"])

    model_attempts = sum(
        worker.get("model_attempts", 0)
        for worker in worker_runs
        if not worker.get("worker_error")
    )
    result = {
        "schema_version": 1,
        "label": args.label,
        "started_at": started_at,
        "finished_at": utc_now(),
        "environment": {
            "python": platform.python_version(),
            "model": config.MODEL,
            "embedding_model": config.EMBEDDING_MODEL,
            "corpus": config.CORPUS,
            "index_variant": "default",
        },
        "methodology": {
            "trials": TRIALS,
            "latency_condition": "one unscored uncached warm-up, then five genuine uncached questions per fresh process",
            "cache_condition": "three genuine cache misses and one immediate repeat in an empty isolated cache per fresh process",
            "failure_condition": "real retrieval followed by an injected client exception; no mocked answer",
            "tracking_condition": "two refusal requests in each of two sequential fresh processes",
            "old_logs_untouched": True,
        },
        "api_usage": {
            "model_attempts": model_attempts,
            "expected_without_provider_retries": 27,
        },
        "files": {
            "raw_jsonl": str(raw_path.relative_to(ROOT)),
            "json": str(json_path.relative_to(ROOT)),
            "markdown": str(markdown_path.relative_to(ROOT)),
        },
        "criteria": criteria,
        "worker_runs": worker_runs,
        "raw_record_count": len(records),
    }
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown_report(result, markdown_path)

    print(f"\nWrote {raw_path.relative_to(ROOT)} ({len(records)} records)")
    print(f"Wrote {json_path.relative_to(ROOT)}")
    print(f"Wrote {markdown_path.relative_to(ROOT)}")
    print(f"Gemini model attempts: {model_attempts}")
    for number, criterion in criteria.items():
        verdicts = ", ".join("pass" if trial["passed"] else "fail" for trial in criterion["trials"])
        overall = "PASS" if criterion["passed"] else "FAIL"
        print(f"Criterion {number}: {overall} ({verdicts})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Unit 9 capstone acceptance evaluation.")
    parser.add_argument("--label", required=True, choices=("before", "after"))
    parser.add_argument("--worker", choices=("core", "cache", "tracking"), help=argparse.SUPPRESS)
    parser.add_argument("--trial", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--log-path", help=argparse.SUPPRESS)
    parser.add_argument("--cache-dir", help=argparse.SUPPRESS)
    parser.add_argument("--process-name", choices=("A", "B"), help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.worker:
        return worker_main(args)
    return parent_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
