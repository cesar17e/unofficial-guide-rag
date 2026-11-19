import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import config
import generate


def response(text, prompt_tokens, output_tokens):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens,
            candidates_token_count=output_tokens,
        ),
    )


class GenerationUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp_dir.name) / "cache"
        self.models = SimpleNamespace(generate_content=Mock())
        self.client = SimpleNamespace(models=self.models)

        self.patchers = [
            patch.object(config, "CACHE_DIR", self.cache_dir),
            patch.object(config, "CACHE_ENABLED", True),
            patch.object(generate, "_client", self.client),
            patch.object(generate, "_session_calls", 0),
            patch.object(generate, "_session_prompt_tokens", 0),
            patch.object(generate, "_session_output_tokens", 0),
            patch.object(generate, "_cache_hits", 0),
            patch.object(generate, "_call_times", []),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_fresh_generation_reports_response_tokens(self):
        self.models.generate_content.return_value = response("fresh", 12, 4)

        answer = generate.generate("new prompt")
        usage = generate.request_usage()

        self.assertEqual(answer, "fresh")
        self.assertEqual(usage.prompt_tokens, 12)
        self.assertEqual(usage.output_tokens, 4)
        self.assertFalse(usage.cache_hit)
        self.assertEqual(usage.api_attempts, 1)
        self.assertEqual(usage.retry_count, 0)
        self.assertEqual(usage.retry_wait_ms, 0.0)
        self.assertEqual(usage.rate_limit_wait_ms, 0.0)
        self.assertEqual(generate.token_counts(), {"prompt": 12, "output": 4, "total": 16})

    def test_cached_response_reports_zero_new_tokens(self):
        self.models.generate_content.return_value = response("cached answer", 8, 2)

        generate.generate("same prompt")
        generate.generate("same prompt")
        usage = generate.request_usage()

        self.models.generate_content.assert_called_once()
        self.assertEqual(usage.prompt_tokens, 0)
        self.assertEqual(usage.output_tokens, 0)
        self.assertTrue(usage.cache_hit)
        self.assertEqual(usage.api_attempts, 0)
        self.assertEqual(usage.retry_count, 0)
        self.assertEqual(usage.retry_wait_ms, 0.0)
        self.assertEqual(usage.rate_limit_wait_ms, 0.0)
        self.assertEqual(generate.token_counts(), {"prompt": 8, "output": 2, "total": 10})

    def test_failed_generation_reports_unknown_tokens_and_cache_miss(self):
        self.models.generate_content.side_effect = RuntimeError("upstream failed")

        with self.assertRaises(RuntimeError):
            generate.generate("failing prompt", cache=False)

        usage = generate.request_usage()
        self.assertIsNone(usage.prompt_tokens)
        self.assertIsNone(usage.output_tokens)
        self.assertFalse(usage.cache_hit)
        self.assertEqual(usage.api_attempts, 1)
        self.assertEqual(usage.retry_count, 0)
        self.assertEqual(usage.retry_wait_ms, 0.0)
        self.assertEqual(usage.rate_limit_wait_ms, 0.0)

    def test_success_after_retries_accumulates_attempts_and_actual_waits(self):
        self.models.generate_content.side_effect = [
            RuntimeError("429 rate limit"),
            RuntimeError("resource exhausted"),
            response("eventual success", 14, 5),
        ]

        with (
            patch.object(generate.time, "sleep") as sleep,
            patch.object(
                generate.time,
                "perf_counter",
                side_effect=[10.0, 10.125, 20.0, 20.25],
            ),
        ):
            answer = generate.generate("retry prompt", cache=False)

        usage = generate.request_usage()
        self.assertEqual(answer, "eventual success")
        self.assertEqual(usage.api_attempts, 3)
        self.assertEqual(usage.retry_count, 2)
        self.assertAlmostEqual(usage.retry_wait_ms, 375.0)
        self.assertEqual(usage.rate_limit_wait_ms, 0.0)
        self.assertEqual((usage.prompt_tokens, usage.output_tokens), (14, 5))
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_exhausted_retries_preserve_all_known_metrics(self):
        self.models.generate_content.side_effect = RuntimeError("429 rate limit")

        with (
            patch.object(config, "MAX_RETRIES", 3),
            patch.object(generate.time, "sleep") as sleep,
            patch.object(
                generate.time,
                "perf_counter",
                side_effect=[1.0, 1.1, 2.0, 2.2, 3.0, 3.3],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Still rate limited"):
                generate.generate("exhausted prompt", cache=False)

        usage = generate.request_usage()
        self.assertEqual(usage.api_attempts, 3)
        self.assertEqual(usage.retry_count, 3)
        self.assertAlmostEqual(usage.retry_wait_ms, 600.0)
        self.assertEqual(usage.rate_limit_wait_ms, 0.0)
        self.assertIsNone(usage.prompt_tokens)
        self.assertIsNone(usage.output_tokens)
        self.assertFalse(usage.cache_hit)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 4])

    def test_local_rate_limit_wait_uses_measured_elapsed_time(self):
        self.models.generate_content.return_value = response("after local wait", 9, 2)
        generate._call_times[:] = [99.0]

        with (
            patch.object(config, "REQUESTS_PER_MINUTE", 1),
            patch.object(generate.time, "sleep") as sleep,
            patch.object(
                generate.time,
                "monotonic",
                side_effect=[100.0, 160.2, 160.3],
            ),
            patch.object(generate.time, "perf_counter", side_effect=[5.0, 5.25]),
        ):
            answer = generate.generate("locally paced prompt", cache=False)

        usage = generate.request_usage()
        self.assertEqual(answer, "after local wait")
        self.assertEqual(usage.api_attempts, 1)
        self.assertEqual(usage.retry_count, 0)
        self.assertEqual(usage.retry_wait_ms, 0.0)
        self.assertAlmostEqual(usage.rate_limit_wait_ms, 250.0)
        self.assertAlmostEqual(sleep.call_args.args[0], 59.1)

    def test_multiple_questions_do_not_reuse_previous_request_tokens(self):
        self.models.generate_content.side_effect = [
            response("first", 5, 1),
            response("second", 13, 3),
        ]

        generate.generate("first prompt", cache=False)
        first = generate.request_usage()
        generate.generate("second prompt", cache=False)
        second = generate.request_usage()

        self.assertEqual((first.prompt_tokens, first.output_tokens), (5, 1))
        self.assertEqual((second.prompt_tokens, second.output_tokens), (13, 3))
        self.assertEqual((first.api_attempts, second.api_attempts), (1, 1))
        self.assertEqual((first.retry_count, second.retry_count), (0, 0))
        self.assertEqual(generate.token_counts(), {"prompt": 18, "output": 4, "total": 22})

    def test_retry_metrics_do_not_leak_to_the_next_request(self):
        self.models.generate_content.side_effect = [
            RuntimeError("429 rate limit"),
            response("first", 5, 1),
            response("second", 13, 3),
        ]

        with (
            patch.object(generate.time, "sleep"),
            patch.object(generate.time, "perf_counter", side_effect=[4.0, 4.2]),
        ):
            generate.generate("first prompt", cache=False)
            first = generate.request_usage()
            generate.generate("second prompt", cache=False)
            second = generate.request_usage()

        self.assertEqual(first.api_attempts, 2)
        self.assertEqual(first.retry_count, 1)
        self.assertAlmostEqual(first.retry_wait_ms, 200.0)
        self.assertEqual(second.api_attempts, 1)
        self.assertEqual(second.retry_count, 0)
        self.assertEqual(second.retry_wait_ms, 0.0)
        self.assertEqual(second.rate_limit_wait_ms, 0.0)

    def test_concurrent_contexts_keep_usage_separate(self):
        def generate_content(**kwargs):
            if kwargs["contents"] == "first prompt":
                return response("first", 7, 2)
            return response("second", 17, 6)

        self.models.generate_content.side_effect = generate_content

        def run(prompt):
            generate.generate(prompt, cache=False)
            usage = generate.request_usage()
            return (
                usage.prompt_tokens,
                usage.output_tokens,
                usage.api_attempts,
                usage.retry_count,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, "first prompt")
            second = pool.submit(run, "second prompt")

        self.assertEqual(first.result(), (7, 2, 1, 0))
        self.assertEqual(second.result(), (17, 6, 1, 0))


if __name__ == "__main__":
    unittest.main()
