import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app


REQUEST_ID = "00000000-0000-4000-8000-000000000001"


class AskPipelineObservabilityTests(unittest.TestCase):
    def fake_modules(self, *, passed=True, answer="grounded answer", usage=None):
        results = [SimpleNamespace(source="source_b.txt"), SimpleNamespace(source="source_a.txt")]
        decision = SimpleNamespace(passed=passed, best_distance=0.2, threshold=0.6)
        usage = usage or SimpleNamespace(
            prompt_tokens=21,
            output_tokens=5,
            cache_hit=False,
            api_attempts=3,
            retry_count=2,
            retry_wait_ms=3000.0,
            rate_limit_wait_ms=250.0,
        )

        search = Mock(return_value=results)
        check = Mock(return_value=decision)
        build_prompt = Mock(return_value="assembled prompt")
        answer_from_chunks = Mock(return_value=answer)
        reset_request_usage = Mock()
        request_usage = Mock(return_value=usage)

        modules = {
            "store": SimpleNamespace(search=search),
            "gate": SimpleNamespace(check=check, REFUSAL="not enough information"),
            "generate": SimpleNamespace(
                answer_from_chunks=answer_from_chunks,
                build_prompt=build_prompt,
                request_usage=request_usage,
                reset_request_usage=reset_request_usage,
            ),
        }
        return modules, search, check, build_prompt, answer_from_chunks

    def test_success_logs_one_record_with_stage_timings(self):
        modules, search, check, build_prompt, generate = self.fake_modules()
        on_gate = Mock()
        on_prompt = Mock()

        with (
            patch.dict(sys.modules, modules),
            patch("app.new_request_id", return_value=REQUEST_ID),
            patch("app.log_request") as write_log,
            patch("app.time.perf_counter", side_effect=[10.0, 10.1, 10.125, 10.2, 10.5, 10.7]),
        ):
            outcome = app.ask_pipeline(
                "question",
                on_gate=on_gate,
                on_prompt=on_prompt,
            )

        self.assertEqual(outcome["answer"], "grounded answer")
        self.assertEqual(outcome["sources"], ["source_a.txt", "source_b.txt"])
        search.assert_called_once()
        check.assert_called_once()
        build_prompt.assert_called_once()
        generate.assert_called_once()
        on_gate.assert_called_once()
        on_prompt.assert_called_once_with("assembled prompt")
        write_log.assert_called_once()

        record = write_log.call_args.kwargs
        self.assertEqual(record["request_id"], REQUEST_ID)
        self.assertEqual(record["status"], "success")
        self.assertAlmostEqual(record["retrieval_ms"], 25.0)
        self.assertAlmostEqual(record["generation_ms"], 300.0)
        self.assertAlmostEqual(record["duration_ms"], 700.0)
        self.assertEqual(record["prompt_tokens"], 21)
        self.assertEqual(record["output_tokens"], 5)
        self.assertFalse(record["cache_hit"])
        self.assertEqual(record["api_attempts"], 3)
        self.assertEqual(record["retry_count"], 2)
        self.assertEqual(record["retry_wait_ms"], 3000.0)
        self.assertEqual(record["rate_limit_wait_ms"], 250.0)
        self.assertIsNone(record["error"])

    def test_cached_success_logs_zero_new_tokens_and_cache_hit(self):
        cached_usage = SimpleNamespace(
            prompt_tokens=0,
            output_tokens=0,
            cache_hit=True,
            api_attempts=0,
            retry_count=0,
            retry_wait_ms=0.0,
            rate_limit_wait_ms=0.0,
        )
        modules, _, _, _, generate = self.fake_modules(usage=cached_usage)

        with (
            patch.dict(sys.modules, modules),
            patch("app.new_request_id", return_value=REQUEST_ID),
            patch("app.log_request") as write_log,
            patch("app.time.perf_counter", side_effect=[15.0, 15.1, 15.15, 15.2, 15.21, 15.3]),
        ):
            outcome = app.ask_pipeline("repeated question")

        self.assertEqual(outcome["answer"], "grounded answer")
        generate.assert_called_once()
        write_log.assert_called_once()
        record = write_log.call_args.kwargs
        self.assertEqual(record["prompt_tokens"], 0)
        self.assertEqual(record["output_tokens"], 0)
        self.assertTrue(record["cache_hit"])
        self.assertEqual(record["api_attempts"], 0)
        self.assertEqual(record["retry_count"], 0)
        self.assertEqual(record["retry_wait_ms"], 0.0)
        self.assertEqual(record["rate_limit_wait_ms"], 0.0)

    def test_refusal_logs_once_without_calling_generation(self):
        modules, _, _, build_prompt, generate = self.fake_modules(passed=False)

        with (
            patch.dict(sys.modules, modules),
            patch("app.new_request_id", return_value=REQUEST_ID),
            patch("app.log_request") as write_log,
            patch("app.time.perf_counter", side_effect=[20.0, 20.1, 20.15, 20.3]),
        ):
            outcome = app.ask_pipeline("unanswerable")

        self.assertTrue(outcome["refused"])
        self.assertEqual(outcome["answer"], "not enough information")
        build_prompt.assert_not_called()
        generate.assert_not_called()
        write_log.assert_called_once()

        record = write_log.call_args.kwargs
        self.assertEqual(record["status"], "refused")
        self.assertAlmostEqual(record["retrieval_ms"], 50.0)
        self.assertIsNone(record["generation_ms"])
        self.assertAlmostEqual(record["duration_ms"], 300.0)
        self.assertEqual(record["prompt_tokens"], 0)
        self.assertEqual(record["output_tokens"], 0)
        self.assertIsNone(record["cache_hit"])
        self.assertEqual(record["api_attempts"], 0)
        self.assertEqual(record["retry_count"], 0)
        self.assertEqual(record["retry_wait_ms"], 0.0)
        self.assertEqual(record["rate_limit_wait_ms"], 0.0)

    def test_generation_failure_logs_once_and_reraises_original_exception(self):
        known_usage = SimpleNamespace(
            prompt_tokens=3,
            output_tokens=1,
            cache_hit=False,
            api_attempts=4,
            retry_count=3,
            retry_wait_ms=7000.0,
            rate_limit_wait_ms=125.0,
        )
        modules, _, _, _, generate = self.fake_modules(usage=known_usage)
        original = RuntimeError("private upstream details")
        generate.side_effect = original

        with (
            patch.dict(sys.modules, modules),
            patch("app.new_request_id", return_value=REQUEST_ID),
            patch("app.log_request") as write_log,
            patch("app.time.perf_counter", side_effect=[30.0, 30.1, 30.15, 30.2, 30.45, 30.6]),
        ):
            with self.assertRaises(RuntimeError) as raised:
                app.ask_pipeline("question that fails")

        self.assertIs(raised.exception, original)
        write_log.assert_called_once()
        record = write_log.call_args.kwargs
        self.assertEqual(record["status"], "error")
        self.assertIsNone(record["answer"])
        self.assertAlmostEqual(record["retrieval_ms"], 50.0)
        self.assertAlmostEqual(record["generation_ms"], 250.0)
        self.assertAlmostEqual(record["duration_ms"], 600.0)
        self.assertEqual(record["error"]["type"], "RuntimeError")
        self.assertEqual(record["error"]["message"], "The question could not be completed.")
        self.assertNotIn("private upstream details", str(record["error"]))
        self.assertEqual(record["prompt_tokens"], 3)
        self.assertEqual(record["output_tokens"], 1)
        self.assertFalse(record["cache_hit"])
        self.assertEqual(record["api_attempts"], 4)
        self.assertEqual(record["retry_count"], 3)
        self.assertEqual(record["retry_wait_ms"], 7000.0)
        self.assertEqual(record["rate_limit_wait_ms"], 125.0)

    def test_failure_before_generation_logs_unknown_generation_metrics(self):
        modules, search, _, _, _ = self.fake_modules()
        original = RuntimeError("retrieval failed")
        search.side_effect = original
        modules["generate"].request_usage.return_value = None

        with (
            patch.dict(sys.modules, modules),
            patch("app.new_request_id", return_value=REQUEST_ID),
            patch("app.log_request") as write_log,
            patch("app.time.perf_counter", side_effect=[35.0, 35.1, 35.4, 35.5]),
        ):
            with self.assertRaises(RuntimeError) as raised:
                app.ask_pipeline("question that fails during retrieval")

        self.assertIs(raised.exception, original)
        record = write_log.call_args.kwargs
        self.assertEqual(record["status"], "error")
        self.assertIsNone(record["generation_ms"])
        self.assertIsNone(record["api_attempts"])
        self.assertIsNone(record["retry_count"])
        self.assertIsNone(record["retry_wait_ms"])
        self.assertIsNone(record["rate_limit_wait_ms"])

    def test_logging_failure_does_not_mask_pipeline_exception(self):
        modules, _, _, _, generate = self.fake_modules()
        original = RuntimeError("original pipeline failure")
        generate.side_effect = original

        with (
            patch.dict(sys.modules, modules),
            patch("app.new_request_id", return_value=REQUEST_ID),
            patch("app.log_request", side_effect=OSError("disk unavailable")) as write_log,
            patch("app.time.perf_counter", side_effect=[40.0, 40.1, 40.15, 40.2, 40.3, 40.4]),
            self.assertLogs("app", level="ERROR") as captured,
        ):
            with self.assertRaises(RuntimeError) as raised:
                app.ask_pipeline("question that fails")

        self.assertIs(raised.exception, original)
        write_log.assert_called_once()
        self.assertIn("Structured request logging failed", captured.output[0])
        self.assertNotIn("disk unavailable", captured.output[0])

    def test_logging_failure_does_not_prevent_successful_answer(self):
        modules, _, _, _, _ = self.fake_modules()

        with (
            patch.dict(sys.modules, modules),
            patch("app.new_request_id", return_value=REQUEST_ID),
            patch("app.log_request", side_effect=OSError("disk unavailable")) as write_log,
            patch("app.time.perf_counter", side_effect=[50.0, 50.1, 50.15, 50.2, 50.3, 50.4]),
            self.assertLogs("app", level="ERROR") as captured,
        ):
            outcome = app.ask_pipeline("answerable question")

        self.assertEqual(outcome["answer"], "grounded answer")
        self.assertFalse(outcome["refused"])
        write_log.assert_called_once()
        self.assertIn("failed after success response", captured.output[0])
        self.assertNotIn("disk unavailable", captured.output[0])

    def test_logging_failure_does_not_prevent_refusal(self):
        modules, _, _, _, generate = self.fake_modules(passed=False)

        with (
            patch.dict(sys.modules, modules),
            patch("app.new_request_id", return_value=REQUEST_ID),
            patch("app.log_request", side_effect=OSError("disk unavailable")) as write_log,
            patch("app.time.perf_counter", side_effect=[60.0, 60.1, 60.15, 60.3]),
            self.assertLogs("app", level="ERROR") as captured,
        ):
            outcome = app.ask_pipeline("unanswerable question")

        self.assertEqual(outcome["answer"], "not enough information")
        self.assertTrue(outcome["refused"])
        generate.assert_not_called()
        write_log.assert_called_once()
        self.assertIn("failed after refused response", captured.output[0])
        self.assertNotIn("disk unavailable", captured.output[0])


if __name__ == "__main__":
    unittest.main()
