"""Explicit provenance review, audience separation and stale-context protection."""
from dataclasses import dataclass, replace
import importlib.util
import os
import unittest

HAS_QT = importlib.util.find_spec("PyQt6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QDialog
    from dndgm4.campaign_recall_ui import CampaignRecallDialog


@dataclass(frozen=True)
class MemoryHit:
    citation: str = "[NPC:secret]"
    kind: str = "NPC"
    source_id: str = "secret"
    field: str = "dm_notes"
    title: str = "<b>Innkeeper</b>"
    text: str = "<script>Literal source text</script>"
    digest: str = "abc123"
    source_url: str = "https://example.invalid/source"
    source_version: str = "3.5"
    classification: str = "DM secret"
    public: bool = False


@unittest.skipUnless(HAS_QT, "PyQt6 is not installed")
class CampaignRecallUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.hits = [MemoryHit(), replace(MemoryHit(), citation="[QUEST:public]", source_id="public", field="player_summary", classification="Player", public=True)]
        self.search_calls = []
        self.build_calls = []
        self.search_error = False
        self.build_error = False
        self.large = False
        def search(query, **kwargs):
            self.search_calls.append((query, kwargs))
            if self.search_error:
                raise ValueError("Database unavailable")
            return list(self.hits)
        def build(hits, **kwargs):
            self.build_calls.append((list(hits), kwargs))
            if self.build_error or kwargs["audience"] == "player" and any(not hit.public for hit in hits):
                raise ValueError("Private sources cannot enter player context")
            return "x" * 6001 if self.large else "\n".join(hit.citation + " " + hit.text for hit in hits)
        self.dialog = CampaignRecallDialog(search, build, query="innkeeper")

    def tearDown(self):
        self.dialog.reject()
        self.dialog.deleteLater()
        self.app.processEvents()

    def select(self, row=0):
        self.dialog.results.item(row, 0).setCheckState(Qt.CheckState.Checked)

    def test_no_automatic_search_or_context_loading(self):
        self.assertEqual(self.search_calls, [])
        self.assertEqual(self.build_calls, [])
        self.assertFalse(self.dialog.load_button.isEnabled())
        self.dialog.accept()
        self.assertIsNone(self.dialog.result_context)
        self.assertNotEqual(self.dialog.result(), QDialog.DialogCode.Accepted)

    def test_full_plain_source_and_explicit_preview_then_accept(self):
        self.assertTrue(self.dialog.search())
        self.assertEqual(self.search_calls, [("innkeeper", {"audience": "dm", "limit": 20})])
        preview = self.dialog.source_preview.toPlainText()
        for value in ("<b>Innkeeper</b>", "<script>Literal source text</script>", "dm_notes", "abc123", "https://example.invalid/source", "3.5"):
            self.assertIn(value, preview)
        self.select()
        self.assertEqual(self.build_calls, [])
        self.assertFalse(self.dialog.load_button.isEnabled())
        self.assertTrue(self.dialog.preview_context())
        self.assertEqual(self.build_calls[-1][1], {"audience": "dm", "max_chars": 6000})
        self.assertIsNone(self.dialog.result_context)
        context = self.dialog.context_preview.toPlainText()
        self.dialog.accept()
        self.assertEqual(self.dialog.result_context, context)
        self.assertEqual(self.dialog.result_audience, "dm")

    def test_audience_change_removes_all_dm_sources_and_previews(self):
        self.dialog.search()
        self.select()
        self.dialog.preview_context()
        self.dialog.audience.setCurrentIndex(1)
        self.assertEqual(self.dialog.results.rowCount(), 0)
        self.assertEqual(self.dialog.source_preview.toPlainText(), "")
        self.assertEqual(self.dialog.context_preview.toPlainText(), "")
        self.assertFalse(self.dialog.load_button.isEnabled())
        self.assertEqual(len(self.search_calls), 1)
        self.dialog.accept()
        self.assertIsNone(self.dialog.result_context)

    def test_query_selection_and_preview_tampering_invalidate_review(self):
        self.dialog.search()
        self.select()
        self.assertTrue(self.dialog.preview_context())
        self.select(1)
        self.assertFalse(self.dialog.load_button.isEnabled())
        self.assertTrue(self.dialog.preview_context())
        self.dialog.context_preview.setPlainText("Changed after review")
        self.dialog.accept()
        self.assertIsNone(self.dialog.result_context)
        self.dialog.query.setText("quest")
        self.assertEqual(self.dialog.results.rowCount(), 0)
        self.assertFalse(self.dialog.preview_button.isEnabled())

    def test_oversize_context_rejected_without_truncating_or_loading(self):
        self.dialog.search()
        self.select()
        self.large = True
        self.assertFalse(self.dialog.preview_context())
        self.assertIn("Nothing was truncated", self.dialog.status.text())
        self.assertFalse(self.dialog.load_button.isEnabled())
        self.assertEqual(self.dialog.context_preview.toPlainText(), "")
        self.assertIn("abc123", self.dialog.source_preview.toPlainText())

    def test_builder_enforces_player_privacy_independently(self):
        self.dialog.audience.setCurrentIndex(1)
        self.dialog.search()
        self.select()
        self.assertFalse(self.dialog.preview_context())
        self.assertEqual(self.build_calls[-1][1]["audience"], "player")
        self.assertIn("Private sources", self.dialog.status.text())
        self.assertFalse(self.dialog.load_button.isEnabled())
        self.dialog.results.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        self.select(1)
        self.assertTrue(self.dialog.preview_context())
        self.dialog.accept()
        self.assertEqual(self.dialog.result_audience, "player")
        self.assertNotIn("NPC:secret", self.dialog.result_context)

    def test_errors_retain_inspectable_sources_but_disable_load(self):
        self.dialog.search()
        self.select()
        self.dialog.preview_context()
        old_source = self.dialog.source_preview.toPlainText()
        self.search_error = True
        self.assertFalse(self.dialog.search())
        self.assertEqual(self.dialog.source_preview.toPlainText(), old_source)
        self.assertFalse(self.dialog.load_button.isEnabled())
        self.assertFalse(self.dialog.preview_context())
        self.dialog.accept()
        self.assertIsNone(self.dialog.result_context)

    def test_source_change_or_missing_result_after_preview_blocks_load(self):
        self.dialog.search()
        self.select()
        self.assertTrue(self.dialog.preview_context())
        original_context = self.dialog.context_preview.toPlainText()
        self.hits[0] = replace(self.hits[0], text="Changed in another window", digest="new-digest")
        self.dialog.accept()
        self.assertIsNone(self.dialog.result_context)
        self.assertFalse(self.dialog.load_button.isEnabled())
        self.assertFalse(self.dialog.preview_button.isEnabled())
        self.assertEqual(self.dialog.context_preview.toPlainText(), original_context)
        self.assertIn("Search and preview again", self.dialog.status.text())
        self.assertTrue(self.dialog.search())
        self.select()
        self.assertTrue(self.dialog.preview_context())
        self.hits.pop(0)
        self.dialog.accept()
        self.assertIsNone(self.dialog.result_context)

    def test_accept_verification_failure_retains_draft_without_loading(self):
        self.dialog.search()
        self.select()
        self.dialog.preview_context()
        old_source = self.dialog.source_preview.toPlainText()
        self.search_error = True
        self.dialog.accept()
        self.assertEqual(self.dialog.source_preview.toPlainText(), old_source)
        self.assertIsNone(self.dialog.result_context)
        self.assertFalse(self.dialog.load_button.isEnabled())

    def test_empty_selection_and_cancel_never_load(self):
        self.dialog.search()
        self.assertFalse(self.dialog.preview_context())
        self.select()
        self.assertTrue(self.dialog.preview_context())
        self.dialog.reject()
        self.assertIsNone(self.dialog.result_context)
        self.assertIsNone(self.dialog.result_audience)


if __name__ == "__main__":
    unittest.main()
