"""Campaign tool routing and complete recovery work through the real main shell."""
from importlib.util import find_spec
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import zipfile


@unittest.skipUnless(find_spec('PyQt6') is not None,'PyQt6 is not installed')
class CampaignToolIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PyQt6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.campaigns import CampaignRepository
        from dndgm4.models import Creature
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name)
        self.library=CreatureRepository(self.root/'live/library.sqlite3')
        self.pc=self.library.save(Creature(name='Starling',kind='pc',character_class='Wizard'))
        self.campaign=CampaignRepository(self.library.path).create_campaign('Crimson Coast')
        self.window=MainWindow(self.library)

    def tearDown(self):
        self.window.close()
        self.tmp.cleanup()

    def test_campaign_tools_route_the_chosen_campaign_and_correct_repository(self):
        cases=(
            ('dndgm4.map_ui.MapDeskDialog','open_maps',self.library),
            ('dndgm4.time_ui.CampaignTimeDialog','open_campaign_time',self.library.path),
            ('dndgm4.resources_ui.ResourcesDialog','open_resources',self.library.path),
            ('dndgm4.handouts_ui.HandoutGalleryDialog','open_handouts',self.library),
            ('dndgm4.reviewed_drafts_ui.ReviewedDraftsDialog','open_reviewed_drafts',self.library.path),
        )
        for target,method,repository in cases:
            with self.subTest(method=method),patch.object(self.window,'_choose_campaign',return_value=self.campaign.id),patch(target,autospec=True) as dialog:
                if method == 'open_resources':
                    dialog.return_value.character_changed = Mock()
                getattr(self.window,method)()
                dialog.assert_called_once_with(repository,self.campaign.id,parent=self.window)
                dialog.return_value.exec.assert_called_once_with()

    def test_cancel_campaign_selection_does_not_open_a_tool(self):
        with patch.object(self.window,'_choose_campaign',return_value=None),patch('dndgm4.map_ui.MapDeskDialog') as dialog:
            self.window.open_maps()
        dialog.assert_not_called()

    def test_rules_handoff_contains_evidence_and_finishes_the_lookup(self):
        from PyQt6.QtWidgets import QDialog
        def use(dialog):
            dialog.query.setText('cover');dialog.search();dialog.use_in_scribe()
            self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)
            return dialog.result()
        with patch('dndgm4.rules_ui.RulesReferenceDialog.exec',new=use),patch.object(self.window,'_open_scribe_with_context') as scribe:
            self.window.open_rules()
        scribe.assert_called_once()
        self.assertIn('[R1]',scribe.call_args.args[0])
        self.assertEqual(scribe.call_args.kwargs,{'task':'dm_advice'})

    def test_spell_management_uses_selected_persistent_character(self):
        self.window.refresh(select_id=self.pc.id)
        with patch('dndgm4.spell_progression_ui.SpellProgressionDialog',autospec=True) as dialog:
            self.window.open_spell_progression()
        dialog.assert_called_once_with(self.library,self.pc.id,parent=self.window)
        self.assertEqual(self.library.get(self.pc.id),self.pc)

    def test_editable_scribe_draft_reaches_review_with_active_session(self):
        from dndgm4.ai_ui import AIWritingDialog
        from dndgm4.campaigns import ActiveWorkspace, CampaignRepository
        session = CampaignRepository(self.library.path).create_session(self.campaign.id, 'The crossing')
        self.window.workspace = ActiveWorkspace(self.campaign.id, session.id, None)
        draft = AIWritingDialog('dm', parent=self.window)
        draft.dm_task.setCurrentIndex(draft.dm_task.findData('session_plan'))
        self.assertFalse(draft.review_campaign_button.isEnabled())
        draft.result.setPlainText('The party finds a broken bridge. [R1]')
        with patch('dndgm4.reviewed_drafts_ui.ReviewedDraftsDialog',autospec=True) as review,patch.object(self.window,'_flush_workspace') as flush:
            review.return_value.load_scribe_draft.return_value = True
            draft.review_campaign_button.click()
        flush.assert_called_once()
        review.assert_called_once_with(self.library.path,self.campaign.id,parent=self.window)
        review.return_value.load_scribe_draft.assert_called_once_with(
            'The party finds a broken bridge. [R1]',task='session_plan',session_id=session.id)
        review.return_value.exec.assert_called_once()
        draft.close()

    def test_level_up_routes_established_class_history_to_multiclass_tool(self):
        from dataclasses import replace
        self.library.save(replace(self.pc,sheet_json='{"class_levels":{"Wizard":1}}'))
        self.window.refresh(select_id=self.pc.id)
        with patch.object(self.window,'open_multiclass') as advance:
            self.window.level_up()
        advance.assert_called_once()

    def test_stale_editor_keeps_its_draft_and_preserves_later_xp(self):
        from dataclasses import replace
        from PyQt6.QtWidgets import QDialog
        self.window.refresh(select_id=self.pc.id)
        with patch('dndgm4.ui.CreatureEditor',autospec=True) as editor,patch('dndgm4.ui.QMessageBox.critical') as error:
            editor.return_value.result_creature = replace(self.pc,name='Stale proposed name')
            def accept_then_cancel():
                if self.library.get(self.pc.id) == self.pc:
                    self.library.save(replace(self.pc,sheet_json='{"experience_points":500}'))
                    return QDialog.DialogCode.Accepted
                return QDialog.DialogCode.Rejected
            editor.return_value.exec.side_effect = accept_then_cancel
            self.window.edit()
        self.assertEqual(editor.return_value.exec.call_count,2)
        error.assert_called_once()
        self.assertEqual(json.loads(self.library.get(self.pc.id).sheet_json)['experience_points'],500)
        self.assertEqual(self.library.get(self.pc.id).name,self.pc.name)

    def test_complete_backup_flushes_the_current_scene_into_the_bundle(self):
        destination=self.root/'game.dndbackup'
        self.window.scene['title']='Unsaved tabletop title'
        with patch('dndgm4.ui.QFileDialog.getSaveFileName',return_value=(str(destination),'')):
            self.window.backup_campaign_data()
        with zipfile.ZipFile(destination) as archive:
            scene=json.loads(archive.read('current_scene.json'))
        self.assertEqual(scene['title'],'Unsaved tabletop title')

    def test_restore_creates_separate_library_before_offering_next_launch(self):
        from dndgm4.recovery import create_backup
        from PyQt6.QtWidgets import QMessageBox
        archive=self.root/'backup.dndbackup';create_backup(self.library,archive)
        restored=self.root/'restored'
        with patch('dndgm4.ui.QFileDialog.getOpenFileName',return_value=(str(archive),'')),patch('dndgm4.ui.QFileDialog.getSaveFileName',return_value=(str(restored),'')),patch('dndgm4.ui.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes),patch.object(self.window,'_offer_library_on_restart') as offer:
            self.window.restore_campaign_data()
        offer.assert_called_once_with(restored/'library.sqlite3')
        self.assertEqual(self.window.library.path,self.library.path)
        self.assertEqual(self.library.get(self.pc.id),self.pc)
