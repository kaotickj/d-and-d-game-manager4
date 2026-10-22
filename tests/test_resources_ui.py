"""Real Qt resource workflows require review and preserve failed drafts."""
from importlib.util import find_spec
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6"), "PyQt6 is not installed")
class ResourceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.models import Creature
        from dndgm4.resources import ResourceRepository
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.repo = ResourceRepository(self.path)
        self.campaign = self.repo.campaigns.create_campaign("Ash Road")
        self.hero = self.repo.library.save(Creature(name="Arden", level=3))
        self.party = self.repo.create_wallet(self.campaign.id, "Party")
        self.purse = self.repo.create_wallet(self.campaign.id, "Arden", self.hero.id)
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
        self.app.processEvents()
        self.temp.cleanup()

    def dialog(self, wallet=None):
        from dndgm4.resources_ui import ResourcesDialog
        dialog = ResourcesDialog(self.path, self.campaign.id)
        self.dialogs.append(dialog)
        if wallet:
            from PyQt6.QtCore import Qt
            for row in range(dialog.wallets.count()):
                item = dialog.wallets.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == wallet.id:
                    dialog.wallets.setCurrentItem(item)
                    break
        return dialog

    def test_open_refresh_and_cancel_preview_have_no_financial_side_effect(self):
        dialog = self.dialog(self.purse)
        dialog.reason.setText("Bridge rescue")
        dialog.copper.setText("200")
        dialog.xp.setText("100")
        with patch.object(dialog, "_confirm", return_value=False) as confirm:
            self.assertFalse(dialog.money_command("award"))
        self.assertIn("pending XP", confirm.call_args.args[1])
        self.assertEqual(self.repo.get_wallet(self.campaign.id, self.purse.id).copper, 0)
        self.assertEqual(self.repo.operations(self.campaign.id), [])
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)

    def test_reviewed_reward_updates_ledger_and_xp_requires_separate_apply(self):
        dialog = self.dialog(self.purse)
        dialog.reason.setText("Bridge rescue")
        dialog.copper.setText("200")
        dialog.xp.setText("100")
        with patch.object(dialog, "_confirm", return_value=True):
            self.assertTrue(dialog.money_command("award"))
        self.assertEqual(self.repo.get_wallet(self.campaign.id, self.purse.id).copper, 200)
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)
        with patch.object(dialog, "_confirm", return_value=False):
            self.assertFalse(dialog.apply_pending_xp())
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)
        changed = []
        dialog.character_changed.connect(changed.append)
        with patch.object(dialog, "_confirm", return_value=True):
            self.assertTrue(dialog.apply_pending_xp())
        self.assertEqual(json.loads(self.repo.library.get(self.hero.id).sheet_json)["experience_points"], 100)
        self.assertEqual(self.repo.library.get(self.hero.id).level, 3)
        self.assertEqual(changed, [self.hero.id])
        self.assertIn("Bridge rescue", dialog.history.toPlainText())

    def test_invalid_expense_preserves_input_and_saved_balance(self):
        dialog = self.dialog(self.party)
        dialog.reason.setText("Food")
        dialog.copper.setText("50")
        with patch.object(dialog, "_confirm", return_value=True):
            self.assertFalse(dialog.money_command("expense"))
        self.assertIn("insufficient", dialog.message.text())
        self.assertEqual(dialog.copper.text(), "50")
        self.assertEqual(dialog.reason.text(), "Food")
        self.assertEqual(self.repo.operations(self.campaign.id), [])

    def test_transfer_and_consumption_follow_actual_selected_inventory(self):
        self.repo.add_item(self.campaign.id, self.party.id, "Rations", 5, 1000, "Provisions", "start")
        dialog = self.dialog(self.party)
        dialog.reason.setText("Travel supplies")
        dialog.item_target.setCurrentIndex(dialog.item_target.findData(self.purse.id))
        dialog.item_quantity.setValue(2)
        with patch.object(dialog, "_confirm", return_value=True):
            self.assertTrue(dialog.item_command("transfer"))
        self.assertEqual(self.repo.list_items(self.campaign.id, self.party.id)[0].quantity, 3)
        self.assertEqual(self.repo.list_items(self.campaign.id, self.purse.id)[0].quantity, 2)
        dialog.item_quantity.setValue(1)
        with patch.object(dialog, "_confirm", return_value=True):
            self.assertTrue(dialog.item_command("consume"))
        self.assertEqual(self.repo.list_items(self.campaign.id, self.party.id)[0].quantity, 2)

    def test_failed_new_item_keeps_modal_draft_and_never_saves_it(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QDialogButtonBox, QLineEdit, QSpinBox
        dialog = self.dialog(self.purse)
        dialog.reason.setText("Found in chest")
        observed = []
        def exercise():
            editor = self.app.activeModalWidget()
            try:
                fields = [field for field in editor.findChildren(QLineEdit)
                          if not isinstance(field.parentWidget(), QSpinBox)]
                fields[0].setText("Silver dust")
                fields[1].setText("not a weight")
                editor.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
                observed.append((editor.isVisible(), fields[0].text(), fields[1].text()))
            finally:
                editor.reject()
        QTimer.singleShot(0, exercise)
        with patch.object(dialog, "_confirm", return_value=False):
            self.assertFalse(dialog.new_item())
        self.assertEqual(observed, [(True, "Silver dust", "not a weight")])
        self.assertEqual(self.repo.list_items(self.campaign.id, self.purse.id), [])

    def test_compact_view_keeps_actions_in_scrollable_inventory(self):
        dialog = self.dialog(self.purse)
        dialog.resize(830, 540)
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.minimumWidth(), 830)
        self.assertTrue(dialog.tabs.widget(0).widgetResizable())
        self.assertTrue(dialog.tabs.widget(1).widgetResizable())

    def test_corrupt_audit_metadata_is_visible_without_crashing_or_rewriting_data(self):
        self.repo.adjust_money(self.campaign.id, self.party.id, 50, "Starting funds", "fund")
        with self.repo._connection() as db:
            db.execute("UPDATE resource_operations SET payload_json='[]' WHERE id='fund'")
        dialog = self.dialog(self.party)
        self.assertIn("metadata is damaged", dialog.history.toPlainText())
        self.assertEqual(self.repo.operations(self.campaign.id)[0]["payload_json"], "[]")
        self.assertEqual(self.repo.get_wallet(self.campaign.id, self.party.id).copper, 50)
