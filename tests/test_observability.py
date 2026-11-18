import json
import logging
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from observability import SCHEMA_FIELDS, SESSION_ID, JsonlRequestLogger, safe_error


class JsonlRequestLoggerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "nested" / "rag_runs.jsonl"

    def tearDown(self):
        self.temp_dir.cleanup()

    def read_records(self):
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
        ]

    def test_writes_valid_json_with_the_complete_schema(self):
        logger = JsonlRequestLogger(self.log_path)
        record = logger.log_request(
            question="What time does Halden Hall close?",
            answer="It closes at 7:00 p.m.",
            status="success",
            retrieval_ms=12.5,
            generation_ms=None,
            duration_ms=12.5,
            prompt_tokens=None,
            output_tokens=None,
            cache_hit=None,
        )
        logger.close()

        saved = self.read_records()[0]
        self.assertEqual(saved, record)
        self.assertEqual(tuple(saved), SCHEMA_FIELDS)
        self.assertIsNone(saved["generation_ms"])
        self.assertIsNone(saved["prompt_tokens"])
        self.assertIsNone(saved["error"])
        self.assertTrue(saved["timestamp"].endswith("Z"))
        datetime.fromisoformat(saved["timestamp"].replace("Z", "+00:00"))

    def test_appends_without_overwriting_prior_records(self):
        first = JsonlRequestLogger(self.log_path)
        first.log_request(question="first", answer="one", status="success")
        first.close()

        second = JsonlRequestLogger(self.log_path)
        second.log_request(question="second", answer="two", status="success")
        second.close()

        self.assertEqual([r["question"] for r in self.read_records()], ["first", "second"])

    def test_session_and_request_ids_have_the_expected_lifetimes(self):
        logger = JsonlRequestLogger(self.log_path)
        first = logger.log_request(question="one", answer="answer", status="success")
        second = logger.log_request(question="two", answer="answer", status="success")
        logger.close()

        UUID(first["session_id"])
        UUID(first["request_id"])
        UUID(second["request_id"])
        self.assertEqual(first["session_id"], SESSION_ID)
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertNotEqual(first["request_id"], second["request_id"])

    def test_failure_record_uses_safe_error_and_null_unknowns(self):
        logger = JsonlRequestLogger(self.log_path)
        exception = RuntimeError("secret-token-should-not-be-logged")
        record = logger.log_request(
            question="Will this fail?",
            answer=None,
            status="error",
            duration_ms=3.0,
            error=safe_error(exception, "The request could not be completed."),
        )
        logger.close()

        saved_text = self.log_path.read_text(encoding="utf-8")
        self.assertNotIn("secret-token-should-not-be-logged", saved_text)
        self.assertEqual(record["error"]["type"], "RuntimeError")
        self.assertEqual(record["error"]["message"], "The request could not be completed.")
        self.assertIsNone(record["retrieval_ms"])
        self.assertIsNone(record["generation_ms"])
        self.assertIsNone(record["cache_hit"])

    def test_file_write_failure_is_raised_even_when_logging_suppresses_errors(self):
        class BrokenStream:
            def write(self, value):
                raise OSError("disk write failed")

            def flush(self):
                pass

            def close(self):
                pass

        logger = JsonlRequestLogger(self.log_path)
        logger._ensure_handler()
        logger._handler.stream = BrokenStream()

        with patch.object(logging, "raiseExceptions", False):
            with self.assertRaises(OSError):
                logger.log_request(question="question", answer="answer", status="success")

        logger.close()


if __name__ == "__main__":
    unittest.main()
