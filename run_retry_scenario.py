#!/usr/bin/env python3
"""Run a controlled retry-observability scenario without calling Gemini.

This is simulated evidence, not a live model evaluation. The script replaces
retrieval with one deterministic in-scope result and replaces the Gemini client
with a provider stub that raises two synthetic 429 errors before succeeding.
The real ``generate.generate`` retry loop, sleeps, ``app.ask_pipeline`` wiring,
and ``JsonlRequestLogger`` are used unchanged.

Usage:

    python run_retry_scenario.py --label after
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent


class SimulatedModels:
    """Fail twice like a rate-limited provider, then return fixed metadata."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.calls <= 2:
            raise RuntimeError("429 simulated provider rate limit")
        return SimpleNamespace(
            text="Simulated grounded answer from campus_document.txt.",
            usage_metadata=SimpleNamespace(
                prompt_token_count=12,
                candidates_token_count=5,
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the simulated provider-retry observability scenario."
    )
    parser.add_argument("--label", required=True, choices=("before", "after"))
    args = parser.parse_args()

    output = ROOT / "results" / f"retry_scenario_{args.label}.jsonl"
    report = ROOT / "results" / f"retry_scenario_{args.label}.md"
    existing = [path for path in (output, report) if path.exists()]
    if existing:
        names = ", ".join(str(path.relative_to(ROOT)) for path in existing)
        print(f"Refusing to overwrite {names}", file=sys.stderr)
        return 2

    import app
    import config
    import generate
    import observability
    import store

    result = store.Result(
        text="The simulated campus office opens at 9:00am.",
        source="campus_document.txt",
        label="campus_document.txt#0",
        distance=0.1,
        produced_by="run_retry_scenario.py::main (simulated retrieval)",
    )
    models = SimulatedModels()
    client = SimpleNamespace(models=models)
    logger = observability.JsonlRequestLogger(output)

    notice = "SIMULATED SCENARIO: no Gemini request and no live retrieval will run."
    print(notice)
    retry_console = io.StringIO()
    with redirect_stderr(retry_console):
        with (
            patch.object(config, "CACHE_ENABLED", False),
            patch.object(store, "search", return_value=[result]),
            patch.object(generate, "_client", client),
            patch.object(app, "log_request", logger.log_request),
        ):
            outcome = app.ask_pipeline("When does the simulated campus office open?")
    logger.close()

    record = json.loads(output.read_text(encoding="utf-8").splitlines()[-1])
    console_text = retry_console.getvalue()
    print(console_text, end="", file=sys.stderr)
    print(json.dumps(record, indent=2, ensure_ascii=False))
    print(f"Wrote simulated evidence to {output.relative_to(ROOT)}")

    metric_fields = (
        "api_attempts",
        "retry_count",
        "retry_wait_ms",
        "rate_limit_wait_ms",
    )
    fields_present = all(field in record for field in metric_fields)
    answer_matches = (
        outcome["answer"] == "Simulated grounded answer from campus_document.txt."
    )
    if args.label == "before":
        expected = answer_matches and not fields_present
    else:
        expected = (
            answer_matches
            and record.get("api_attempts") == 3
            and record.get("retry_count") == 2
            and record.get("retry_wait_ms", 0) >= 3000
            and record.get("rate_limit_wait_ms") == 0
        )

    report_lines = [
        f"# Controlled retry scenario — {args.label}",
        "",
        f"> {notice}",
        "",
        "Two synthetic provider `429` responses were followed by one fixed",
        "successful response. The application's real retry loop and sleeps ran.",
        "",
        "## Retry console output",
        "",
        "```text",
        console_text.rstrip(),
        "```",
        "",
        "## Structured JSONL record",
        "",
        "```json",
        json.dumps(record, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Verification",
        "",
        f"- Retry metric fields present: `{fields_present}`",
        f"- Scenario check: `{'MET' if expected else 'MISSED'}`",
        "",
    ]
    report.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"Wrote simulated report to {report.relative_to(ROOT)}")
    return 0 if expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
