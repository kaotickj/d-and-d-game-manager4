"""Real GUI lifecycle regression: Use Draft may NEVER exit the whole app.

Run the actual QApplication event loop and three nested steps:
 MainWindow -> CharacterCreatorDialog.exec() -> AIWritingDialog.exec()
 -> Use Draft QPushButton.click() -> Character Forge remains visible.

A separate Python process detects PyQt native termination, fatal exceptions,
or unexpected early event-loop exit (which ordinary mock-based tests miss).
No GGUF inference process or network access is used.
"""
import os
import subprocess
import sys
import textwrap
import unittest
from importlib.util import find_spec

@unittest.skipUnless(find_spec("PyQt6") is not None,"PyQt6 unavailable")
class ChildWindowLifecycleTests(unittest.TestCase):
    def test_real_use_draft_does_not_terminate_app(self):
        source = textwrap.dedent(r'''
            import json
            import sys
            import faulthandler
            import traceback
            faulthandler.enable(all_threads=True)
            def log_exc(t,v,tb):
                print('STAGE_PYTHON_EXCEPTION',repr(v),flush=True)
                traceback.print_exception(t,v,tb)
            sys.excepthook = log_exc
            print('STAGE_IMPORT_START',flush=True)
            from pathlib import Path
            from tempfile import TemporaryDirectory
            from PyQt6.QtCore import QTimer, Qt
            from PyQt6.QtWidgets import QApplication
            import dndgm4.ui as ui
            import dndgm4.roll_ui as roll_ui
            from dndgm4.ai_ui import AIWritingDialog
            from dndgm4.storage import CreatureRepository
            from dndgm4.theme import apply_theme

            print('STAGE_APP_INIT',flush=True)
            app = QApplication([])
            app.setQuitOnLastWindowClosed(False)
            apply_theme(app)
            payload = {
                "kind":"pc","race":"Human","class":"Fighter",
                "name":"Captain Reeve",
                "base_scores":{
                    "strength":16,"dexterity":14,"constitution":14,
                    "intelligence":12,"wisdom":11,"charisma":12},
                "alignment":"Lawful Good",
                "feats":["Power Attack","Cleave"],
                "skills_half_ranks":{"Ride":8,"Climb":8},
                "equipment":["Longsword","Chainmail"],
                "inventory":"2 x Rations\nLongsword",
                "biography":"A watch captain with a hidden oath.",
                "languages":["Common"],"class_features":["Fighter bonus feat"],
                "gender":"Female","age":"31",
            }
            class AutoScribe(AIWritingDialog):
                def exec(self):
                    print('STAGE_SCRIBE_EXEC',flush=True)
                    def click_use_draft():
                        print('STAGE_SCRIBE_CLICK_START',flush=True)
                        assert self.kind == "character_build"
                        self.result.setPlainText(json.dumps(payload))
                        assert self.use.text() == "Use Draft"
                        self.use.click()  # ACTUAL button and actual QDialog.accept()
                        print('STAGE_SCRIBE_CLICK_FINISHED',flush=True)
                    QTimer.singleShot(0, click_use_draft)
                    return super().exec()

            class AutoCreator(roll_ui.CharacterCreatorDialog):
                def exec(self):
                    print('STAGE_CREATOR_EXEC',flush=True)
                    self.creation_mode.setCurrentIndex(1)
                    self.race.setCurrentText("Human")
                    self.character_class.setCurrentText("Fighter")
                    def after_draft():
                        result = (main.isVisible() and self.isVisible()
                                  and self.ai_draft_applied
                                  and self.name.text() == "Captain Reeve"
                                  and self.options.background.toPlainText().startswith(
                                      "A watch captain"))
                        print("USE_DRAFT_APPLICATION_ALIVE=" + str(result),flush=True)
                        self.reject()  # unwind only the character dialog
                    def click_generate():
                        print('STAGE_GENERATE_CLICK',flush=True)
                        self.ai_build_button.click()
                        print('STAGE_GENERATE_RETURNED',flush=True)
                    QTimer.singleShot(0, click_generate)
                    QTimer.singleShot(250, after_draft)
                    return super().exec()

            ui.CharacterCreatorDialog = AutoCreator
            roll_ui.AIWritingDialog = AutoScribe

            with TemporaryDirectory() as tmp:
                print('STAGE_MAIN_CREATING',flush=True)
                main = ui.MainWindow(CreatureRepository(Path(tmp)/"library.sqlite3"))
                main.show()
                assert main.isVisible()
                def run_forge():
                    print('STAGE_MAIN_CREATE_PC',flush=True)
                    main.create("pc")  # actual create() / dialog.exec() path
                    alive = main.isVisible()
                    print("MAIN_STILL_VISIBLE=" + str(alive),flush=True)
                    main.close()
                    if not alive:
                        app.exit(7)
                QTimer.singleShot(0, run_forge)
                QTimer.singleShot(10000, lambda: (
                    print("LIFECYCLE_TIMEOUT",flush=True), app.exit(8)))
                print('STAGE_EVENT_LOOP_START',flush=True)
                exit_code = app.exec()
                print("QT_EVENT_LOOP_EXIT=" + str(exit_code),flush=True)
                sys.exit(exit_code)
        ''')
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        # QT_NO_DEBUG_OUTPUT leaves actual crashes and Python stderr visible.
        result = subprocess.run(
            [sys.executable,"-c",source],
            env=env,text=True,capture_output=True,timeout=35,
        )
        detail = ("stdout:\n"+result.stdout+"\nstderr:\n"+result.stderr)
        self.assertEqual(result.returncode,0,detail)
        self.assertIn("USE_DRAFT_APPLICATION_ALIVE=True",result.stdout,detail)
        self.assertIn("MAIN_STILL_VISIBLE=True",result.stdout,detail)
        self.assertNotIn("LIFECYCLE_TIMEOUT",result.stdout,detail)


if __name__ == "__main__":
    unittest.main()
