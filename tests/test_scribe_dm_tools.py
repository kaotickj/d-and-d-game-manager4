"""DM task prompts and explicit, local Scribe interactions without inference."""
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import unittest

from dndgm4 import local_ai


class DMTaskPromptTests(unittest.TestCase):
    def test_each_dm_task_uses_its_own_local_prompt(self):
        tasks = ("dm", "campaign_plan", "session_plan", "dm_advice", "recap")
        self.assertEqual(len({local_ai.PROMPTS[task] for task in tasks}), len(tasks))
        for task in tasks:
            with self.subTest(task=task), patch.object(
                    local_ai, "_post_json", return_value={"response": "Reviewed draft."}) as post:
                draft = local_ai.text_generate(task, "Known party at the old bridge.",
                                               model="qwen3:4b", backend="ollama")
                self.assertEqual(draft, "Reviewed draft.")
                self.assertEqual(post.call_args.args[0], local_ai.OLLAMA_URL)
                self.assertIn(local_ai.PROMPTS[task], post.call_args.args[1]["prompt"])
                self.assertGreaterEqual(post.call_args.args[1]["options"]["num_predict"], 650)

    def test_planning_advice_and_recap_respect_the_dm_and_known_events(self):
        self.assertIn("player-facing", local_ai.PROMPTS["dm"])
        for task in ("campaign_plan", "session_plan", "dm_advice", "recap"):
            self.assertIn("DM-only", local_ai.PROMPTS[task])
        self.assertIn("proposals", local_ai.PROMPTS["campaign_plan"])
        self.assertIn("proposals", local_ai.PROMPTS["session_plan"])
        self.assertIn("uncertainty", local_ai.PROMPTS["dm_advice"])
        self.assertIn("do not fabricate source", local_ai.PROMPTS["dm_advice"])
        self.assertIn("Summarize only the supplied", local_ai.PROMPTS["recap"])
        self.assertIn("no events are supplied", local_ai.PROMPTS["recap"])


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class ScribeDMUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.ai_ui import AIWritingDialog
        self.dialog = AIWritingDialog("dm", "Known party: Élara. Scene: the old bridge.")

    def tearDown(self):
        self.dialog.hide()
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_task_switch_keeps_context_draft_and_model_without_generation(self):
        self.dialog.result.setPlainText("An edited narration draft.")
        self.dialog.dm_request.setText("Help plan the bridge meeting.")
        context = self.dialog.context.toPlainText()
        model = self.dialog.model.text()
        with patch("dndgm4.ai_ui.text_generate") as generate:
            for task in ("campaign_plan", "session_plan", "dm_advice", "recap", "dm"):
                self.dialog.dm_task.setCurrentIndex(self.dialog.dm_task.findData(task))
                self.assertEqual(self.dialog.kind, "dm")
                self.assertEqual(self.dialog.context.toPlainText(), context)
                self.assertEqual(self.dialog.result.toPlainText(), "An edited narration draft.")
                self.assertEqual(self.dialog.dm_request.text(), "Help plan the bridge meeting.")
                self.assertEqual(self.dialog.model.text(), model)
            generate.assert_not_called()
        self.assertIsNone(self.dialog.worker)

    def test_model_settings_can_be_opened_without_generating_or_losing_context(self):
        context = self.dialog.context.toPlainText()
        self.assertTrue(self.dialog.engine_settings.isHidden())
        with patch("dndgm4.ai_ui.text_generate") as generate:
            self.dialog.settings_toggle.click()
            self.assertFalse(self.dialog.engine_settings.isHidden())
            self.dialog.settings_toggle.click()
            self.assertTrue(self.dialog.engine_settings.isHidden())
            generate.assert_not_called()
        self.assertEqual(self.dialog.context.toPlainText(), context)

    def test_generation_uses_selected_task_and_preserves_loaded_context(self):
        original = self.dialog.context.toPlainText()
        self.dialog.dm_task.setCurrentIndex(self.dialog.dm_task.findData("dm_advice"))
        self.dialog.dm_request.setText("How can I offer three ways past the guard?")
        with patch("dndgm4.ai_ui.QThreadPool") as pool:
            self.dialog.generate_button.click()
        worker = self.dialog.worker
        self.assertEqual(worker.kind, "dm_advice")
        self.assertIn(original, worker.context)
        self.assertIn("DM REQUEST:\nHow can I offer three ways past the guard?", worker.context)
        self.assertEqual(self.dialog.context.toPlainText(), original)
        pool.globalInstance.return_value.start.assert_called_once_with(worker)
        self.assertFalse(self.dialog.generate_button.isEnabled())
        self.dialog.generation_completed("Three reviewed options.")
        self.assertEqual(self.dialog.result.toPlainText(), "Three reviewed options.")
        self.assertTrue(self.dialog.generate_button.isEnabled())

    def test_request_only_is_valid_and_overflow_is_not_silently_truncated(self):
        self.dialog.context.clear()
        self.dialog.dm_request.setText("Plan a campaign about rival merchant houses.")
        with patch("dndgm4.ai_ui.QThreadPool") as pool:
            self.dialog.generate()
        self.assertIn("merchant houses", self.dialog.worker.context)
        pool.globalInstance.return_value.start.assert_called_once()
        self.dialog.generation_completed("A planning draft.")
        self.dialog.context.setPlainText("x" * 6000)
        with patch("dndgm4.ai_ui.QThreadPool") as pool:
            self.dialog.generate()
        pool.globalInstance.return_value.start.assert_not_called()
        self.assertEqual(self.dialog.context.toPlainText(), "x" * 6000)
        self.assertIn("no details were omitted", self.dialog.status.text())
        self.assertTrue(self.dialog.generate_button.isEnabled())

    def test_close_keeps_dm_assistant_reusable_in_every_task(self):
        self.dialog.result.setPlainText("Saved in this window.")
        self.dialog.dm_task.setCurrentIndex(self.dialog.dm_task.findData("session_plan"))
        self.dialog.show()
        self.app.processEvents()
        self.dialog.close()
        self.app.processEvents()
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.dialog.result.toPlainText(), "Saved in this window.")
        self.dialog.show()
        self.app.processEvents()
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(self.dialog.dm_task.currentData(), "session_plan")

    def test_biography_dialog_still_uses_original_task_without_dm_controls(self):
        from dndgm4.ai_ui import AIWritingDialog
        biography = AIWritingDialog("bio", "A young ranger.")
        try:
            self.assertFalse(hasattr(biography, "dm_task"))
            with patch("dndgm4.ai_ui.QThreadPool"):
                biography.generate()
            self.assertEqual(biography.worker.kind, "bio")
            self.assertEqual(biography.worker.context, "A young ranger.")
        finally:
            biography.close()

    def test_save_editable_draft_as_utf8_and_cancel_without_writing(self):
        self.dialog.result.setPlainText("Élara crosses the bridge.\nEdited by the DM.")
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "session.md"
            with patch("dndgm4.ai_ui.QFileDialog.getSaveFileName",
                       return_value=(str(target), "Markdown files (*.md)")):
                self.dialog.save_draft_button.click()
            self.assertEqual(target.read_text(encoding="utf-8"), self.dialog.result.toPlainText())
            self.assertIn("Draft saved", self.dialog.status.text())
            with patch("dndgm4.ai_ui.QFileDialog.getSaveFileName", return_value=("", "")), \
                    patch("dndgm4.ai_ui.os.replace") as replace:
                self.dialog.save_draft()
            replace.assert_not_called()

    def test_failed_draft_save_preserves_previous_file_and_reports_error(self):
        self.dialog.result.setPlainText("New draft.")
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "session.txt"
            target.write_text("Previous draft.", encoding="utf-8")
            with patch("dndgm4.ai_ui.QFileDialog.getSaveFileName", return_value=(str(target), "")), \
                    patch("dndgm4.ai_ui.os.replace", side_effect=OSError("Disk full")), \
                    patch("dndgm4.ai_ui.QMessageBox.warning") as warning:
                self.dialog.save_draft()
            warning.assert_called_once()
            self.assertEqual(target.read_text(encoding="utf-8"), "Previous draft.")
            self.assertEqual(list(Path(temporary).glob(".scribe_*")), [])


if __name__ == "__main__":
    unittest.main()
