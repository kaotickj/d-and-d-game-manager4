"""Explicit, isolated release acceptance check for source and bundled builds.

This module does nothing on import. ``--smoke-test REPORT`` is the sole caller;
all saved-game activity belongs to a disposable folder beside REPORT. The
report and screenshots are the only retained output. No preferences, model,
user-library discovery, or network access is needed.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
import time
import traceback

_SMOKE_APPLICATION = None
CAMPAIGN_ID = "smoke-campaign"
SESSION_ID = "smoke-session"
ENCOUNTER_ID = "smoke-encounter"
HERO_ID = "smoke-hero"


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _create_v3_fixture(path):
    """Create the original core-v3 layout, without using today's migrations."""
    from .battle_advanced import AdvancedBattle
    from .battle_rules import fighter_from_record
    from .models import Creature
    from .scene_context import blank_scene

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = "2026-01-02 03:04:05"
    hero = Creature(id=HERO_ID, name="Smoke Wizard", kind="pc", race_type="Human",
                    character_class="Wizard", level=5, max_hit_points=24,
                    constitution=14, intelligence=18, armor_class=14,
                    sheet_json=json.dumps({"class": "Wizard", "skills_half_ranks": {},
                                           "feats": [], "class_features": [],
                                           "background": "Saved before the upgrade."}),
                    created_at=stamp, updated_at=stamp)
    npc = Creature(id="smoke-npc", name="Archived Guide", kind="npc", archived=True,
                   created_at=stamp, updated_at=stamp)
    scene = blank_scene()
    scene.update(title="The Old Bridge", location="North road", record_ids=[HERO_ID],
                 campaign_notes="Private saved campaign notes.")
    battle = AdvancedBattle(title="Bridge Patrol", scene="A saved encounter.")
    fighter = fighter_from_record(hero)
    fighter.uid = "smoke-fighter"
    fighter.hp = 11
    battle.add(fighter)
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE creatures (
                id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('pc','npc','monster')),
                race_type TEXT NOT NULL DEFAULT '',character_class TEXT NOT NULL DEFAULT '',
                level INTEGER NOT NULL DEFAULT 1,challenge_rating TEXT NOT NULL DEFAULT '',
                armor_class INTEGER NOT NULL DEFAULT 10,max_hit_points INTEGER NOT NULL DEFAULT 1,
                strength INTEGER NOT NULL DEFAULT 10,dexterity INTEGER NOT NULL DEFAULT 10,
                constitution INTEGER NOT NULL DEFAULT 10,intelligence INTEGER NOT NULL DEFAULT 10,
                wisdom INTEGER NOT NULL DEFAULT 10,charisma INTEGER NOT NULL DEFAULT 10,
                notes TEXT NOT NULL DEFAULT '',sheet_json TEXT NOT NULL DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX idx_creatures_kind_name ON creatures(kind,name COLLATE NOCASE);
            CREATE INDEX idx_creatures_archived ON creatures(archived);
            CREATE TABLE campaigns (id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE campaign_members (campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                creature_id TEXT NOT NULL REFERENCES creatures(id),PRIMARY KEY(campaign_id,creature_id));
            CREATE TABLE sessions (id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                title TEXT NOT NULL,session_date TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'planned'
                CHECK(status IN('planned','in_progress','completed')),notes TEXT NOT NULL DEFAULT '',
                recap TEXT NOT NULL DEFAULT '',scene_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX idx_sessions_campaign ON sessions(campaign_id);
            CREATE TABLE encounters (id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),
                title TEXT NOT NULL,battle_json TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX idx_encounters_session ON encounters(session_id);
            CREATE TABLE workspace (id INTEGER PRIMARY KEY CHECK(id=1),campaign_id TEXT REFERENCES campaigns(id),
                session_id TEXT REFERENCES sessions(id),encounter_id TEXT REFERENCES encounters(id));
            PRAGMA user_version=3;
        """)
        for creature in (hero, npc):
            values = asdict(creature)
            db.execute("INSERT INTO creatures (" + ",".join(values) + ") VALUES (" +
                       ",".join("?" for _ in values) + ")", tuple(values.values()))
        db.execute("INSERT INTO campaigns(id,name,description,notes) VALUES(?,?,?,?)",
                   (CAMPAIGN_ID, "Smoke Campaign", "An older saved campaign", "Private campaign journal"))
        db.execute("INSERT INTO campaign_members VALUES(?,?)", (CAMPAIGN_ID, HERO_ID))
        db.execute("INSERT INTO sessions(id,campaign_id,title,session_date,status,notes,recap,scene_json) VALUES(?,?,?,?,?,?,?,?)",
                   (SESSION_ID, CAMPAIGN_ID, "Bridge Session", "2026-01-02", "in_progress",
                    "Session notes", "Prior recap", json.dumps(scene)))
        db.execute("INSERT INTO encounters(id,session_id,title,battle_json) VALUES(?,?,?,?)",
                   (ENCOUNTER_ID, SESSION_ID, battle.title, json.dumps({"version": 1, **battle.snapshot()})))
        db.execute("INSERT INTO workspace VALUES(1,?,?,?)", (CAMPAIGN_ID, SESSION_ID, ENCOUNTER_ID))
    return {"creatures": [asdict(hero), asdict(npc)], "scene": scene, "battle": battle.snapshot()}


def _verify_core(library, expected):
    from .campaigns import CampaignRepository
    from .storage import SCHEMA_VERSION
    campaigns = CampaignRepository(library.path)
    with library._connection() as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        _require(version == SCHEMA_VERSION, "Library did not reach the current schema.")
        _require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite integrity check failed.")
        _require(not db.execute("PRAGMA foreign_key_check").fetchall(), "Foreign-key check failed.")
    for creature in expected["creatures"]:
        _require(asdict(library.get(creature["id"])) == creature, "Migration/recovery changed a permanent creature.")
    campaign = campaigns.get_campaign(CAMPAIGN_ID)
    _require(campaign.name == "Smoke Campaign" and campaign.notes == "Private campaign journal", "Campaign metadata changed.")
    session = campaigns.get_session(SESSION_ID)
    _require((session.title, session.status, session.notes, session.recap, session.session_date) ==
             ("Bridge Session", "in_progress", "Session notes", "Prior recap", "2026-01-02"), "Session metadata changed.")
    _require(campaigns.party_ids(CAMPAIGN_ID) == [HERO_ID], "Party membership changed.")
    _require(campaigns.load_scene(SESSION_ID) == expected["scene"], "Saved scene changed.")
    _require(campaigns.load_battle(ENCOUNTER_ID).snapshot() == expected["battle"], "Encounter instance state changed.")
    _require(asdict(campaigns.get_workspace()) == {"campaign_id": CAMPAIGN_ID,
             "session_id": SESSION_ID, "encounter_id": ENCOUNTER_ID}, "Active workspace changed.")
    return {"schema_version": version, "creatures": 2, "campaigns": 1, "sessions": 1,
            "encounters": 1, "scene_and_party_retained": True}


def _check_artwork():
    from importlib.resources import files
    from PyQt6.QtCore import QByteArray
    from PyQt6.QtGui import QImage, QImageReader
    from PyQt6.QtSvg import QSvgRenderer
    from .artwork import load_artwork, window_icon
    assets = files("dndgm4").joinpath("assets")
    checked = []
    load_artwork.cache_clear()
    for name in ("app_banner.jpg", "dragon_crest.png", "name_genie_crest.png"):
        _require(assets.joinpath(name).is_file(), f"Missing packaged artwork: {name}")
        pixmap = load_artwork(name)
        _require(not pixmap.isNull() and min(pixmap.width(), pixmap.height()) > 100,
                 f"Packaged artwork could not be decoded: {name}")
        checked.append(name)
    icon = QImage()
    _require(icon.loadFromData(assets.joinpath("app_icon.ico").read_bytes(), "ICO"), "Packaged ICO could not be decoded.")
    _require(not window_icon().isNull(), "Application icon is empty.")
    formats = sorted(bytes(item).decode("ascii") for item in QImageReader.supportedImageFormats())
    _require("svg" in formats, "Qt SVG image plugin is unavailable.")
    for name in ("checkmark.svg", "chevron_up.svg", "chevron_down.svg"):
        payload = assets.joinpath(name).read_bytes()
        _require(QSvgRenderer(QByteArray(payload)).isValid(), f"Invalid packaged SVG: {name}")
        decoded = QImage()
        _require(decoded.loadFromData(payload, "SVG") and not decoded.isNull(),
                 f"Qt image plugin could not render packaged SVG: {name}")
        checked.append(name)
    return {"assets": checked + ["app_icon.ico"], "qt_image_formats": formats}


def run_packaged_smoke(report_path) -> int:
    """Run bounded offline release checks; return zero only after every gate passes."""
    global _SMOKE_APPLICATION
    report_path = Path(report_path).absolute()
    screenshot_folder = report_path.with_name(report_path.stem + "-screenshots")
    screenshot_folder_owned = False
    # This explicit diagnostic mode must never replace a saved game, an earlier
    # report, or a link to either. Reserve outputs before creating test data.
    try:
        _require(report_path.suffix.lower() == ".json", "Smoke report must be a fresh .json file.")
        _require(not any(path.is_symlink() for path in (report_path, *report_path.parents)),
                 "Smoke report path cannot contain symbolic links.")
        _require(not report_path.exists(), "Smoke report already exists; choose a fresh output path.")
        _require(not screenshot_folder.exists() and not screenshot_folder.is_symlink(),
                 "Smoke screenshot destination already exists; choose a fresh output path.")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_folder.mkdir()
        screenshot_folder_owned = True
        report_handle = report_path.open("x", encoding="utf-8")
    except (OSError, RuntimeError) as exc:
        if screenshot_folder_owned:
            screenshot_folder.rmdir()
        print(f"Could not reserve smoke output: {exc}", file=sys.stderr)
        return 1
    started = time.monotonic()
    from . import __version__
    report = {"status": "failed", "platform": platform.platform(),
              "app_version": __version__,
              "frozen": bool(getattr(sys, "frozen", False)), "checks": [], "errors": [],
              "screenshots": [], "temporary_data_removed": False}
    widgets = []
    app = None
    previous_quit = None
    temporary_path = None

    def check(name, action):
        check_start = time.monotonic()
        try:
            details = action()
            report["checks"].append({"name": name, "status": "passed", "details": details or {},
                                     "seconds": round(time.monotonic() - check_start, 3)})
            return details
        except Exception as exc:
            report["checks"].append({"name": name, "status": "failed", "error": str(exc)})
            report["errors"].append({"check": name, "error": str(exc), "traceback": traceback.format_exc()})
            raise

    try:
        from PyQt6.QtCore import QBuffer, QCoreApplication, QEvent, QIODevice
        from PyQt6.QtGui import QColor, QImage, QPainter
        from PyQt6.QtWidgets import QApplication
        from .storage import CreatureRepository
        from .theme import apply_theme
        app = QApplication.instance()
        if app is None:
            _SMOKE_APPLICATION = app = QApplication([])
            apply_theme(app)
        previous_quit = app.quitOnLastWindowClosed()
        app.setQuitOnLastWindowClosed(False)
        check("packaged_artwork_and_svg", _check_artwork)

        def render(name, factory, size=(1050, 720)):
            widget = factory()
            if widget not in widgets:
                widgets.append(widget)
            widget.resize(*size)
            widget.show()
            app.processEvents()
            app.processEvents()
            _require(widget.isVisible(), f"{name} did not become visible.")
            shot = widget.grab()
            output = screenshot_folder / (name + ".png")
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            _require(not shot.isNull() and shot.save(buffer, "PNG"), f"Could not capture {name}.")
            with output.open("xb") as screenshot_handle:
                screenshot_handle.write(bytes(buffer.data()))
            buffer.close()
            report["screenshots"].append(str(output))
            actual = [widget.width(), widget.height()]
            widget.hide()
            return {"screenshot": str(output), "size": actual}

        with tempfile.TemporaryDirectory(prefix="dndgm4-smoke-", dir=report_path.parent) as folder:
            temporary_path = Path(folder)
            report["temporary_data_path"] = str(temporary_path)
            path = temporary_path / "original" / "library.sqlite3"
            expected = check("create_core_v3_fixture", lambda: _create_v3_fixture(path))
            library = CreatureRepository(path)
            check("v3_to_current_migration", lambda: _verify_core(library, expected))
            from .campaigns import CampaignRepository
            from .world import WorldRepository
            from .maps import MapRepository
            from .handouts import HandoutRepository
            from .resources import ResourceRepository
            from .campaign_time import CampaignTimeRepository
            from .scene_context import SceneStore
            from .battle_advanced import AdvancedBattleStore

            def populate():
                world = WorldRepository(path)
                handout = world.create(CAMPAIGN_ID, "handout", "Private DM handout name",
                    dm_notes="SMOKE SECRET", details={"player_text": "Meet at the old bridge."})
                source = temporary_path / "fixture-map.png"
                image = QImage(320, 200, QImage.Format.Format_ARGB32)
                image.fill(QColor("#292127"))
                painter = QPainter(image)
                painter.fillRect(25, 25, 270, 150, QColor("#9a7542"))
                painter.fillRect(145, 0, 35, 200, QColor("#557e96"))
                painter.end()
                _require(image.save(str(source), "PNG"), "Could not save temporary image fixture.")
                maps = MapRepository(library)
                map_record = maps.import_image(CAMPAIGN_ID, source, "Old Bridge Map")
                state = map_record.state
                state["revealed"] = [[0, 0], [1, 0]]
                state["tokens"] = [{"id": "smoke-token", "label": "Scout", "x": 25, "y": 25,
                                    "visible": True, "color": "#ed6276"}]
                maps.save_state(map_record.id, state, campaign_id=CAMPAIGN_ID)
                handouts = HandoutRepository(library)
                asset = handouts.import_image(CAMPAIGN_ID, handout.id, source)
                handouts.select_image(CAMPAIGN_ID, handout.id, asset.id)
                public = handouts.public_payload(CAMPAIGN_ID, handout.id)
                _require(public.text == "Meet at the old bridge." and public.image_png,
                         "Player handout lost its public text/image.")
                _require("SMOKE SECRET" not in public.text and "Private DM" not in public.text,
                         "Private handout text escaped into the player payload.")
                resources = ResourceRepository(path)
                wallet = resources.create_wallet(CAMPAIGN_ID, "Party")
                resources.adjust_money(CAMPAIGN_ID, wallet.id, 1234, "Smoke award", "smoke-money")
                resources.add_item(CAMPAIGN_ID, wallet.id, "Rations", 2, 1000, "Smoke supplies", "smoke-rations")
                clock = CampaignTimeRepository(path)
                clock.add_event(CAMPAIGN_ID, 60, "Departure")
                clock.apply_preview(clock.preview_advance(CAMPAIGN_ID, 30, "Smoke time"))
                SceneStore(path).save(expected["scene"])
                AdvancedBattleStore(path).save(CampaignRepository(path).load_battle(ENCOUNTER_ID))
                return {"map_id": map_record.id, "handout_id": handout.id, "wallet_id": wallet.id,
                        "map_state": maps.get(map_record.id).state, "public_text": public.text,
                        "public_image_bytes": len(public.image_png)}

            extra = check("new_campaign_tools_saved_state", populate)
            from .ui import MainWindow
            from .campaign_ui import CampaignManagerDialog
            from .world_ui import WorldManagerDialog
            from .map_ui import MapDeskDialog, PlayerMapWindow
            from .time_ui import CampaignTimeDialog
            from .resources_ui import ResourcesDialog
            from .reviewed_drafts_ui import ReviewedDraftsDialog
            from .handouts_ui import HandoutGalleryDialog, PlayerHandoutWindow
            from .spell_progression_ui import SpellProgressionDialog
            from .multiclass_ui import MulticlassDialog

            def main_window(current_library):
                widget = MainWindow(current_library)
                widgets.append(widget)
                _require(widget.workspace.session_id == SESSION_ID and widget.scene == expected["scene"],
                         "Main window did not open the migrated active session.")
                _require(not widget._workspace_error and not widget._scene_error,
                         "Main window recovered from a workspace/scene load error.")
                return widget

            main = main_window(library)
            check("main_window_desktop", lambda: render("main-desktop", lambda: main, (1551, 924)))
            def compact():
                result = render("main-compact", lambda: main, (830, 540))
                _require(result["size"] == [830, 540], "Main window cannot fit the supported 830x540 size.")
                return result
            check("main_window_830x540", compact)
            maps = MapRepository(library)
            map_record = maps.get(extra["map_id"])
            public = HandoutRepository(library).public_payload(CAMPAIGN_ID, extra["handout_id"])
            dialogs = (
                ("campaign", lambda: CampaignManagerDialog(CampaignRepository(path), library)),
                ("world", lambda: WorldManagerDialog(WorldRepository(path), CAMPAIGN_ID, library)),
                ("map", lambda: MapDeskDialog(library, CAMPAIGN_ID)),
                ("player-map", lambda: PlayerMapWindow(maps.load_image(map_record), map_record.state)),
                ("time", lambda: CampaignTimeDialog(path, CAMPAIGN_ID)),
                ("resources", lambda: ResourcesDialog(path, CAMPAIGN_ID)),
                ("reviewed-drafts", lambda: ReviewedDraftsDialog(path, CAMPAIGN_ID)),
                ("handouts", lambda: HandoutGalleryDialog(library, CAMPAIGN_ID)),
                ("player-handout", lambda: PlayerHandoutWindow(public)),
                ("spells", lambda: SpellProgressionDialog(library, HERO_ID)),
                ("multiclass", lambda: MulticlassDialog(library, HERO_ID)),
            )
            for name, factory in dialogs:
                check("render_" + name, lambda name=name, factory=factory: render(name, factory))

            from .recovery import create_backup, restore_backup
            archive = temporary_path / "complete-backup.zip"
            manifest = check("complete_backup", lambda: create_backup(library, archive))
            _require(len(manifest["files"]) >= 5, "Backup omitted expected saved files/assets.")
            restored_path = check("restore_to_new_folder", lambda: {"path": str(restore_backup(archive, temporary_path / "restored"))})["path"]
            restored = CreatureRepository(restored_path)
            check("reopened_restored_core_records", lambda: _verify_core(restored, expected))

            def verify_extra():
                restored_maps = MapRepository(restored)
                saved_map = restored_maps.get(extra["map_id"], campaign_id=CAMPAIGN_ID)
                _require(saved_map.state == extra["map_state"], "Restored map state changed.")
                _require(not restored_maps.load_image(saved_map).isNull(), "Restored map asset is unreadable.")
                payload = HandoutRepository(restored).public_payload(CAMPAIGN_ID, extra["handout_id"])
                _require(payload == public, "Restored player handout changed.")
                resource = ResourceRepository(restored.path)
                _require(resource.get_wallet(CAMPAIGN_ID, extra["wallet_id"]).copper == 1234, "Restored party money changed.")
                items = resource.list_items(CAMPAIGN_ID, extra["wallet_id"])
                _require(len(items) == 1 and items[0].name == "Rations" and items[0].quantity == 2,
                         "Restored inventory changed.")
                _require(CampaignTimeRepository(restored.path).get_clock(CAMPAIGN_ID).minutes == 30,
                         "Restored campaign clock changed.")
                _require(SceneStore(restored.path).load() == expected["scene"], "Standalone scene backup changed.")
                _require(AdvancedBattleStore(restored.path).load().snapshot() == expected["battle"],
                         "Standalone encounter backup changed.")
                return {"map_and_handout_images": True, "inventory_and_money": True,
                        "clock_minutes": 30, "standalone_state": True}
            check("restored_campaign_tools_and_assets", verify_extra)
            check("restart_restored_main_window", lambda: render("restored-main", lambda: main_window(restored), (1280, 800)))
            # Destroy before the temporary folder is removed (important on Windows).
            for widget in reversed(widgets):
                widget.hide()
                widget.deleteLater()
            widgets.clear()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        report["temporary_data_removed"] = not temporary_path.exists()
        _require(report["temporary_data_removed"], "Temporary saved-game data was not removed.")
        report["status"] = "passed"
    except Exception as exc:
        if not report["errors"]:
            report["errors"].append({"check": "smoke_setup_or_cleanup", "error": str(exc), "traceback": traceback.format_exc()})
    finally:
        if app is not None:
            for widget in reversed(widgets):
                try:
                    widget.hide()
                    widget.deleteLater()
                except RuntimeError:
                    pass
            try:
                from PyQt6.QtCore import QCoreApplication, QEvent
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                app.processEvents()
            finally:
                if previous_quit is not None:
                    app.setQuitOnLastWindowClosed(previous_quit)
        if temporary_path is not None:
            report["temporary_data_removed"] = not temporary_path.exists()
        report["seconds"] = round(time.monotonic() - started, 3)
        try:
            json.dump(report, report_handle, indent=2, ensure_ascii=False, default=str)
            report_handle.write("\n")
            report_handle.flush()
        except OSError as exc:
            print(f"Could not write smoke report: {exc}", file=sys.stderr)
            return 1
        finally:
            report_handle.close()
    return 0 if report["status"] == "passed" else 1
