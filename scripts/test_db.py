"""Offline regression checks for local and hosted Snowflake parameter bindings."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import db  # noqa: E402
import recall  # noqa: E402


class QueryBindingTests(unittest.TestCase):
    def connection(self, pyformat=False):
        conn = MagicMock(is_pyformat=pyformat)
        conn.cursor.return_value.fetchall.return_value = [{"OUT": "test"}]
        return conn

    def test_empty_parameters_omit_binding_argument(self):
        # The hosted connector rejects even an empty dict with error 252004.
        for params in (None, {}, []):
            with self.subTest(params=params):
                conn = self.connection()
                self.assertEqual(db.query(conn, "SELECT CURRENT_USER()", params), [{"OUT": "test"}])
                conn.cursor.return_value.execute.assert_called_once_with("SELECT CURRENT_USER()")

    def test_local_named_parameters_are_unchanged(self):
        conn = self.connection(pyformat=True)
        params = {"name": "a value with ' quotes and % signs"}
        db.query(conn, "SELECT %(name)s", params)
        conn.cursor.return_value.execute.assert_called_once_with("SELECT %(name)s", params)
        self.assertIs(conn.cursor.return_value.execute.call_args.args[1], params)

    def test_hosted_named_parameters_preserve_order_and_repetition(self):
        conn = self.connection()
        value = "literal ' ? %(not_a_parameter)s"
        db.query(conn, "SELECT %(a)s, %(b)s, %(a)s", {"b": 4, "a": value})
        conn.cursor.return_value.execute.assert_called_once_with("SELECT ?, ?, ?", [value, 4, value])

    def test_hosted_ordered_list_is_unchanged(self):
        conn = self.connection()
        params = ["one", 2]
        db.query(conn, "SELECT ?, ?", params)
        conn.cursor.return_value.execute.assert_called_once_with("SELECT ?, ?", params)
        self.assertIs(conn.cursor.return_value.execute.call_args.args[1], params)

    def scope(self):
        return {key: ("test" if recall.SCOPE_SCHEMA["properties"][key]["type"] == "string" else [])
                for key in recall.SCOPE_SCHEMA["required"]}

    def test_structured_ai_sql_preserves_schema_and_binds_values(self):
        conn = self.connection()
        scope = self.scope()
        conn.cursor.return_value.fetchall.return_value = [{"OUT": json.dumps(scope)}]
        notice, model = "UNIQUE-NOTICE ' % ?", "claude-opus-5-5"
        self.assertEqual(recall.interpret(conn, notice, model), scope)
        sql, params = conn.cursor.return_value.execute.call_args.args
        self.assertIn("model => ?, prompt => ?", sql)
        self.assertIn("response_format =>", sql)
        self.assertIn(recall.sf_object({"type": "json", "schema": recall.SCOPE_SCHEMA}), sql)
        self.assertEqual(params, [model, recall.PROMPT + notice])
        self.assertNotIn(notice, sql)
        self.assertNotIn(model, sql)

    def test_ai_fallback_preserves_same_model_and_binding_style(self):
        conn = self.connection()
        scope = self.scope()
        conn.cursor.return_value.fetchall.side_effect = [
            [{"OUT": None}], [{"OUT": json.dumps(scope)}],
        ]
        model, notice = "claude-opus-5-5", "test notice"
        self.assertEqual(recall.interpret(conn, notice, model), scope)
        calls = conn.cursor.return_value.execute.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual([call.args[1][0] for call in calls], [model, model])
        self.assertEqual(calls[1].args[0], "SELECT AI_COMPLETE(?, ?) AS OUT")
        self.assertEqual(calls[1].args[1][1], recall.PROMPT + notice + recall.JSON_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
