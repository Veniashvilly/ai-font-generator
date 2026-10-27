"""Тестируем версии и порядок изменений БЕЗ запросов к GigaChat."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.session_state import FontSession, StateConflictError


SPEC = {
    "base_font": "Test/Test.ttf",
    "width": 0.8,
    "slant": 10.0,
    "spacing": 20,
    "script": "auto",
}


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.initial_ttf = self.root / "output" / "initial" / "result.ttf"
        self.initial_ttf.parent.mkdir(parents=True)
        self.initial_ttf.write_bytes(b"not a real TTF: mocked only")
        self.validator = patch(
            "engine.session_state.normalize_spec", side_effect=lambda x: dict(x)
        )
        self.validator.start()
        self.addCleanup(self.validator.stop)
        self.session = FontSession.start(
            SPEC, self.initial_ttf, sessions_dir=self.root / "sessions"
        )

    def test_three_versions_and_reload(self):
        self.assertEqual(len(self.session.history), 1)
        self.session.set_slider("width", 1.1)
        self.assertEqual(len(self.session.history), 1)  # Пока только черновик.
        current, revision = self.session.prepare_ai_request()
        self.assertEqual(len(self.session.history), 2)
        self.assertEqual(self.session.history[-1]["kind"], "manual_snapshot")
        self.assertEqual(current["width"], 1.1)

        new_ttf = self.root / "output" / "new" / "result.ttf"
        new_ttf.parent.mkdir(parents=True)
        new_ttf.write_bytes(b"generated: mocked")
        with patch("engine.session_state.generate_from_spec", return_value=new_ttf) as gen:
            result, new_file = self.session.apply_ai_patch({"slant": 3.0}, revision)
            args, kwargs = gen.call_args
            self.assertEqual(args[0]["width"], 1.1)
            self.assertEqual(args[0]["slant"], 3.0)
        self.assertTrue(new_file)
        self.assertEqual(result, new_ttf)
        self.assertEqual(len(self.session.history), 3)
        self.assertEqual(self.session.history[-1]["kind"], "ai_revision")
        restored = FontSession.load(
            self.session.data["session_id"], sessions_dir=self.root / "sessions"
        )
        self.assertEqual(restored.params["width"], 1.1)
        self.assertEqual(restored.params["slant"], 3.0)
        self.assertEqual(restored.latest_ttf, new_ttf)

    def test_no_duplicate_snapshot(self):
        self.session.prepare_ai_request()
        self.assertEqual(len(self.session.history), 1)
        self.session.set_slider("width", 1.1)
        self.session.set_slider("width", 0.8)
        self.assertFalse(self.session.is_dirty)
        self.session.prepare_ai_request()
        self.assertEqual(len(self.session.history), 1)

    def test_failed_generation_keeps_manual_state(self):
        self.session.set_slider("width", 1.1)
        _, revision = self.session.prepare_ai_request()
        with patch("engine.session_state.generate_from_spec", side_effect=RuntimeError("fail")):
            with self.assertRaises(RuntimeError):
                self.session.apply_ai_patch({"slant": 2}, revision)
        self.assertEqual(len(self.session.history), 2)
        self.assertEqual(self.session.params["width"], 1.1)
        self.assertEqual(self.session.latest_ttf, self.initial_ttf)

    def test_ai_can_revert_to_previous_ttf_without_regenerating(self):
        self.session.set_slider("width", 1.1)
        _, rev = self.session.prepare_ai_request()
        with patch("engine.session_state.generate_from_spec") as gen:
            file_path, generated = self.session.apply_ai_patch({"width": 0.8}, rev)
            gen.assert_not_called()
        self.assertFalse(generated)
        self.assertEqual(file_path, self.initial_ttf)
        self.assertEqual(len(self.session.history), 3)
        self.assertEqual(self.session.history[-1]["params"]["width"], 0.8)

    def test_stale_ai_result_rejected(self):
        _, revision = self.session.prepare_ai_request()
        self.session.set_slider("width", 1.1)
        with self.assertRaises(StateConflictError):
            self.session.apply_ai_patch({"slant": 3}, revision)


if __name__ == "__main__":
    unittest.main()
