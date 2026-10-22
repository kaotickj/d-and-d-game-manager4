"""A bad selected library can be changed without editing OS settings by hand."""
from importlib.util import find_spec
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec('PyQt6') is not None, 'PyQt6 is not installed')
class StartupRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PyQt6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from PyQt6.QtCore import QSettings
        self.tmp=TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.settings=QSettings(str(self.root/'settings.ini'),QSettings.Format.IniFormat)
        self.default=self.root/'default/library.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_selection_can_use_default_without_creating_the_missing_file(self):
        from dndgm4.__main__ import open_startup_library
        missing=self.root/'moved.sqlite3'
        self.settings.setValue('library/path',str(missing))
        choose,default,cancel=object(),object(),object()
        with patch('PyQt6.QtWidgets.QMessageBox') as message, patch('dndgm4.__main__.default_database_path',return_value=self.default):
            message.return_value.addButton.side_effect=[choose,default,cancel]
            message.return_value.clickedButton.return_value=default
            library=open_startup_library(self.settings)
        self.assertEqual(library.path,self.default)
        self.assertFalse(missing.exists())
        self.assertFalse(self.settings.contains('library/path'))

    def test_cancel_preserves_selected_path_for_later_recovery(self):
        from dndgm4.__main__ import open_startup_library
        missing=str(self.root/'moved.sqlite3')
        self.settings.setValue('library/path',missing)
        with patch('PyQt6.QtWidgets.QMessageBox') as message:
            message.return_value.clickedButton.return_value=None
            self.assertIsNone(open_startup_library(self.settings))
        self.assertEqual(self.settings.value('library/path'),missing)

    def test_choose_valid_library_keeps_corrupt_file_and_changes_selection(self):
        from dndgm4.__main__ import open_startup_library
        from dndgm4.storage import CreatureRepository
        valid=CreatureRepository(self.root/'valid.sqlite3')
        bad=self.root/'bad.sqlite3';bad.write_bytes(b'not a sqlite database')
        self.settings.setValue('library/path',str(bad))
        choose,default,cancel=object(),object(),object()
        with patch('PyQt6.QtWidgets.QMessageBox') as message, patch('PyQt6.QtWidgets.QFileDialog.getOpenFileName',return_value=(str(valid.path),'')):
            message.return_value.addButton.side_effect=[choose,default,cancel]
            message.return_value.clickedButton.return_value=choose
            result=open_startup_library(self.settings)
        self.assertEqual(result.path,valid.path)
        self.assertEqual(bad.read_bytes(),b'not a sqlite database')
        self.assertEqual(self.settings.value('library/path'),str(valid.path.resolve()))
