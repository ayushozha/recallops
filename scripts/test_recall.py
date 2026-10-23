"""Offline checks for the model-response boundary; never opens Snowflake."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import recall  # noqa: E402


class RecallResponseTests(unittest.TestCase):
    def setUp(self):
        self.scope = {
            "firm": "Queso Ñandú", "product_names": ["Cheese"],
            "upcs": ["1234"], "lot_codes": ["A1"], "best_by_dates": [],
            "reason": "Recall", "evidence": ['Lot "A1"'], "ambiguities": [],
        }

    def test_json_encodings_preserve_values(self):
        raw = json.dumps(self.scope, ensure_ascii=False, indent=2)
        samples = [self.scope, raw, json.dumps(raw), "```json\n" + raw + "\n```",
                   raw.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(recall._validate_scope(recall._parse(sample)), self.scope)

    def test_every_required_field_is_checked(self):
        for key in self.scope:
            invalid = dict(self.scope)
            del invalid[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                recall._validate_scope(invalid)

    def test_incorrect_types_are_rejected(self):
        for invalid in [None, [], {"upcs": "1234"}, dict(self.scope, upcs=[1234]),
                        dict(self.scope, evidence={"a": "b"}), dict(self.scope, firm=[]),
                        dict(self.scope, lot_codes=None)]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                recall._validate_scope(invalid)

    def test_null_structured_output_uses_same_model(self):
        with patch.object(recall, "query", side_effect=[
            [{"OUT": None}], [{"OUT": json.dumps(self.scope)}],
        ]) as mocked:
            self.assertEqual(recall.interpret(None, "notice", "claude-opus-5-5"), self.scope)
            self.assertEqual([call.args[2]["m"] for call in mocked.call_args_list],
                             ["claude-opus-5-5", "claude-opus-5-5"])

    def test_null_and_invalid_fallback_fail_closed(self):
        for fallback in [None, "not JSON", json.dumps(dict(self.scope, upcs="1234"))]:
            with self.subTest(fallback=fallback), patch.object(recall, "query", side_effect=[
                [{"OUT": None}], [{"OUT": fallback}],
            ]), self.assertRaises(ValueError):
                recall.interpret(None, "notice", "claude-opus-5-5")


if __name__ == "__main__":
    unittest.main()
