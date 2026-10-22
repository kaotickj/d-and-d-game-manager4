"""Campaign metadata and isolated session/encounter state in the library DB.

Permanent creatures are shared references. Every encounter saves independent
combat instances; none of these operations change a creature template.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
import json
from pathlib import Path
from uuid import uuid4

from .battle_advanced import AdvancedBattle
from .models import Creature
from .scene_context import blank_scene, validate_scene
from .storage import CreatureRepository

SESSION_STATUSES = ("planned", "in_progress", "completed")
MAX_SCENE_BYTES = 150000
MAX_BATTLE_BYTES = 1500000


@dataclass(frozen=True, slots=True)
class Campaign:
    id: str
    name: str
    description: str = ""
    notes: str = ""
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    campaign_id: str
    title: str
    session_date: str = ""
    status: str = "planned"
    notes: str = ""
    recap: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class Encounter:
    id: str
    session_id: str
    title: str
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class ActiveWorkspace:
    campaign_id: str = ""
    session_id: str = ""
    encounter_id: str = ""


def _text(value, label, maximum=100000, *, required=False) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{label} must be text of at most {maximum:,} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} contains invalid Unicode.") from exc
    if "\x00" in value:
        raise ValueError(f"{label} contains an invalid null character.")
    if required and not value.strip():
        raise ValueError(f"{label} is required.")
    return value.strip() if required else value


def _identifier(value, label="Identifier") -> str:
    return _text(value, label, 200, required=True)


def _session_date(value) -> str:
    value = _text(value, "Session date", 10)
    if value:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Session date must be YYYY-MM-DD or blank.") from exc
        if parsed.isoformat() != value:
            raise ValueError("Session date must be YYYY-MM-DD or blank.")
    return value


def _campaign_values(campaign):
    if not isinstance(campaign, Campaign) or type(campaign.archived) is not bool:
        raise ValueError("Choose a valid campaign with an archived checkbox value.")
    return (_text(campaign.name, "Campaign name", 200, required=True),
            _text(campaign.description, "Campaign description", 20000),
            _text(campaign.notes, "Campaign notes"), int(campaign.archived), campaign.id)


def _session_values(session):
    if not isinstance(session, Session):
        raise ValueError("Choose a valid session.")
    title = _text(session.title, "Session title", 200, required=True)
    session_date = _session_date(session.session_date)
    if session.status not in SESSION_STATUSES:
        raise ValueError("Session status must be planned, in_progress, or completed.")
    return (title, session_date, session.status, _text(session.notes, "Session notes"),
            _text(session.recap, "Session recap"), session.id)


def _party_values(record_ids):
    if (not isinstance(record_ids, list) or len(record_ids) > 250
            or any(not isinstance(identity, str) or not identity.strip() or len(identity) > 200
                   for identity in record_ids)):
        raise ValueError("Party membership must contain at most 250 valid library IDs.")
    return list(dict.fromkeys(record_ids))


def _scene_json(scene) -> str:
    try:
        clean = validate_scene(scene)
        text = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        size = len(text.encode("utf-8"))
    except (TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Scene contains invalid data.") from exc
    if size > MAX_SCENE_BYTES:
        raise ValueError("Session scene exceeds the 150 KB limit.")
    return text


def _battle_json(battle) -> str:
    if not isinstance(battle, AdvancedBattle):
        raise ValueError("Encounter state must be an AdvancedBattle.")
    try:
        data = {"version": 1, **battle.snapshot()}
        AdvancedBattle.from_dict(data)
        text = json.dumps(data, ensure_ascii=False, sort_keys=True)
        size = len(text.encode("utf-8"))
    except (TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise ValueError("Encounter state contains invalid data.") from exc
    if size > MAX_BATTLE_BYTES:
        raise ValueError("Encounter state exceeds the 1.5 MB limit.")
    return text


class CampaignRepository:
    def __init__(self, database_path: str | Path):
        self.library = CreatureRepository(database_path)
        self.path = self.library.path

    def _connection(self):
        return self.library._connection()

    @staticmethod
    def _from_row(model, row):
        if row is None:
            return None
        values = {field.name: row[field.name] for field in fields(model)}
        if model is Campaign:
            values["archived"] = bool(values["archived"])
        return model(**values)

    @staticmethod
    def _require(db, table, identity, label):
        _identifier(identity, label + " ID")
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError(f"{label} no longer exists.")
        return row

    def create_campaign(self, name: str, description: str = "", notes: str = "") -> Campaign:
        name = _text(name, "Campaign name", 200, required=True)
        description = _text(description, "Campaign description", 20000)
        notes = _text(notes, "Campaign notes")
        identity = str(uuid4())
        with self._connection() as db:
            db.execute("INSERT INTO campaigns(id,name,description,notes) VALUES(?,?,?,?)",
                       (identity, name, description, notes))
            row = self._require(db, "campaigns", identity, "Campaign")
        return self._from_row(Campaign, row)

    def save_campaign(self, campaign: Campaign) -> Campaign:
        if campaign is None:
            raise ValueError("Choose a valid campaign.")
        saved, _ = self.save_journal(campaign=campaign)
        return saved

    def save_journal(self, campaign: Campaign | None = None,
                     record_ids: list[str] | None = None,
                     session: Session | None = None) -> tuple[Campaign | None, Session | None]:
        """Save the journal's campaign, roster and session as one transaction.

        Validate the entire draft first. A later validation or SQL failure must
        not leave earlier parts of a journal save committed.
        """
        if record_ids is not None and campaign is None:
            raise ValueError("Choose a campaign when saving party membership.")
        campaign_values = _campaign_values(campaign) if campaign is not None else None
        session_values = _session_values(session) if session is not None else None
        identities = _party_values(record_ids) if record_ids is not None else None
        if campaign is not None and session is not None and session.campaign_id != campaign.id:
            raise ValueError("The session does not belong to the selected campaign.")
        if campaign is None and session is None:
            return None, None
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # Check every reference before the first update, under the same
            # lock used for the whole journal commit.
            if campaign is not None:
                self._require(db, "campaigns", campaign.id, "Campaign")
            if session is not None:
                current = self._require(db, "sessions", session.id, "Session")
                if session.campaign_id != current["campaign_id"]:
                    raise ValueError("A saved session cannot be moved to another campaign.")
            if identities is not None:
                for identity in identities:
                    self._require(db, "creatures", identity, "Party member")
            if campaign_values is not None:
                db.execute("UPDATE campaigns SET name=?,description=?,notes=?,archived=?, "
                           "updated_at=CURRENT_TIMESTAMP WHERE id=?", campaign_values)
            if identities is not None:
                self._replace_party(db, campaign.id, identities)
            if session_values is not None:
                db.execute("UPDATE sessions SET title=?,session_date=?,status=?,notes=?,recap=?, "
                           "updated_at=CURRENT_TIMESTAMP WHERE id=?", session_values)
            saved_campaign = (self._from_row(Campaign, self._require(db, "campaigns", campaign.id, "Campaign"))
                              if campaign is not None else None)
            saved_session = (self._from_row(Session, self._require(db, "sessions", session.id, "Session"))
                             if session is not None else None)
        return saved_campaign, saved_session

    def get_campaign(self, campaign_id: str) -> Campaign | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        return self._from_row(Campaign, row)

    def list_campaigns(self, include_archived: bool = False) -> list[Campaign]:
        if type(include_archived) is not bool:
            raise ValueError("Include archived must be true or false.")
        with self._connection() as db:
            rows = db.execute("SELECT * FROM campaigns " + ("" if include_archived else "WHERE archived=0 ")
                              + "ORDER BY name COLLATE NOCASE,id").fetchall()
        return [self._from_row(Campaign, row) for row in rows]

    def set_party(self, campaign_id: str, record_ids: list[str]) -> None:
        identities = _party_values(record_ids)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require(db, "campaigns", campaign_id, "Campaign")
            for identity in identities:
                self._require(db, "creatures", identity, "Party member")
            self._replace_party(db, campaign_id, identities)

    @staticmethod
    def _replace_party(db, campaign_id, identities):
        db.execute("DELETE FROM campaign_members WHERE campaign_id=?", (campaign_id,))
        db.executemany("INSERT INTO campaign_members(campaign_id,creature_id) VALUES(?,?)",
                       [(campaign_id, identity) for identity in identities])

    def party_ids(self, campaign_id: str) -> list[str]:
        with self._connection() as db:
            self._require(db, "campaigns", campaign_id, "Campaign")
            rows = db.execute("SELECT creature_id FROM campaign_members WHERE campaign_id=? ORDER BY rowid",
                              (campaign_id,)).fetchall()
        return [row[0] for row in rows]

    def party(self, campaign_id: str) -> list[Creature]:
        with self._connection() as db:
            self._require(db, "campaigns", campaign_id, "Campaign")
            memberships = db.execute("SELECT creature_id FROM campaign_members WHERE campaign_id=? ORDER BY rowid",
                                     (campaign_id,)).fetchall()
            rows = [self._require(db, "creatures", row[0], "Party member") for row in memberships]
        return [self.library._from_row(row) for row in rows]

    @staticmethod
    def _insert_session(db, campaign_id, title, session_date, scene_json):
        identity = str(uuid4())
        db.execute("INSERT INTO sessions(id,campaign_id,title,session_date,scene_json) VALUES(?,?,?,?,?)",
                   (identity, campaign_id, title, session_date, scene_json))
        return identity

    def create_session(self, campaign_id: str, title: str, session_date: str = "") -> Session:
        title = _text(title, "Session title", 200, required=True)
        session_date = _session_date(session_date)
        scene = _scene_json(blank_scene())
        with self._connection() as db:
            self._require(db, "campaigns", campaign_id, "Campaign")
            identity = self._insert_session(db, campaign_id, title, session_date, scene)
            row = self._require(db, "sessions", identity, "Session")
        return self._from_row(Session, row)

    def save_session(self, session: Session) -> Session:
        if session is None:
            raise ValueError("Choose a valid session.")
        _, saved = self.save_journal(session=session)
        return saved

    def get_session(self, session_id: str) -> Session | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return self._from_row(Session, row)

    def list_sessions(self, campaign_id: str) -> list[Session]:
        with self._connection() as db:
            self._require(db, "campaigns", campaign_id, "Campaign")
            rows = db.execute("SELECT * FROM sessions WHERE campaign_id=? ORDER BY created_at,rowid",
                              (campaign_id,)).fetchall()
        return [self._from_row(Session, row) for row in rows]

    @staticmethod
    def _insert_encounter(db, session_id, title, battle_json):
        identity = str(uuid4())
        db.execute("INSERT INTO encounters(id,session_id,title,battle_json) VALUES(?,?,?,?)",
                   (identity, session_id, title, battle_json))
        return identity

    def create_encounter(self, session_id: str, title: str) -> Encounter:
        title = _text(title, "Encounter title", 200, required=True)
        battle = _battle_json(AdvancedBattle(title=title))
        with self._connection() as db:
            self._require(db, "sessions", session_id, "Session")
            identity = self._insert_encounter(db, session_id, title, battle)
            row = self._require(db, "encounters", identity, "Encounter")
        return self._from_row(Encounter, row)

    def get_encounter(self, encounter_id: str) -> Encounter | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM encounters WHERE id=?", (encounter_id,)).fetchone()
        return self._from_row(Encounter, row)

    def list_encounters(self, session_id: str) -> list[Encounter]:
        with self._connection() as db:
            self._require(db, "sessions", session_id, "Session")
            rows = db.execute("SELECT * FROM encounters WHERE session_id=? ORDER BY created_at,rowid",
                              (session_id,)).fetchall()
        return [self._from_row(Encounter, row) for row in rows]

    def rename_encounter(self, encounter_id: str, title: str) -> Encounter:
        title = _text(title, "Encounter title", 200, required=True)
        with self._connection() as db:
            current = self._require(db, "encounters", encounter_id, "Encounter")
            battle = self._read_battle(current["battle_json"])
            battle.title = title
            data = _battle_json(battle)
            db.execute("UPDATE encounters SET title=?,battle_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (title, data, encounter_id))
            row = self._require(db, "encounters", encounter_id, "Encounter")
        return self._from_row(Encounter, row)

    def load_scene(self, session_id: str) -> dict:
        with self._connection() as db:
            row = self._require(db, "sessions", session_id, "Session")
        try:
            if (not isinstance(row["scene_json"], str)
                    or len(row["scene_json"].encode("utf-8")) > MAX_SCENE_BYTES):
                raise ValueError("Session scene exceeds the 150 KB limit.")
            data = json.loads(row["scene_json"])
            clean = validate_scene(data)
            _scene_json(clean)
            return clean
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError("Saved session scene is invalid and was not overwritten.") from exc

    def save_scene(self, session_id: str, scene: dict) -> None:
        data = _scene_json(scene)
        with self._connection() as db:
            self._require(db, "sessions", session_id, "Session")
            db.execute("UPDATE sessions SET scene_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (data, session_id))

    @staticmethod
    def _read_battle(text) -> AdvancedBattle:
        try:
            if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BATTLE_BYTES:
                raise ValueError("Encounter state exceeds the 1.5 MB limit.")
            battle = AdvancedBattle.from_dict(json.loads(text))
            _battle_json(battle)
            return battle
        except (TypeError, KeyError, ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError("Saved encounter is invalid and was not overwritten.") from exc

    def load_battle(self, encounter_id: str) -> AdvancedBattle:
        with self._connection() as db:
            row = self._require(db, "encounters", encounter_id, "Encounter")
        return self._read_battle(row["battle_json"])

    def save_battle(self, encounter_id: str, battle: AdvancedBattle) -> None:
        data = _battle_json(battle)
        title = _text(battle.title, "Encounter title", 200, required=True)
        with self._connection() as db:
            self._require(db, "encounters", encounter_id, "Encounter")
            db.execute("UPDATE encounters SET title=?,battle_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (title, data, encounter_id))

    def get_workspace(self) -> ActiveWorkspace:
        with self._connection() as db:
            row = db.execute("SELECT * FROM workspace WHERE id=1").fetchone()
        if row is None:
            raise ValueError("Saved campaign workspace is missing.")
        result = ActiveWorkspace(row["campaign_id"] or "", row["session_id"] or "", row["encounter_id"] or "")
        if result.campaign_id or result.session_id or result.encounter_id:
            with self._connection() as db:
                self._validate_workspace(db, result)
        return result

    def _validate_workspace(self, db, workspace: ActiveWorkspace):
        if not isinstance(workspace.encounter_id, str):
            raise ValueError("Encounter ID must be text or blank.")
        campaign = self._require(db, "campaigns", workspace.campaign_id, "Campaign")
        if campaign["archived"]:
            raise ValueError("Unarchive this campaign before opening its sessions.")
        session = self._require(db, "sessions", workspace.session_id, "Session")
        if session["campaign_id"] != workspace.campaign_id:
            raise ValueError("The session does not belong to the selected campaign.")
        if workspace.encounter_id:
            encounter = self._require(db, "encounters", workspace.encounter_id, "Encounter")
            if encounter["session_id"] != workspace.session_id:
                raise ValueError("The encounter does not belong to the selected session.")

    def activate(self, campaign_id: str, session_id: str, encounter_id: str = "") -> ActiveWorkspace:
        result = ActiveWorkspace(campaign_id, session_id, encounter_id)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_workspace(db, result)
            db.execute("UPDATE workspace SET campaign_id=?,session_id=?,encounter_id=? WHERE id=1",
                       (campaign_id, session_id, encounter_id or None))
        return result

    def clear_workspace(self) -> ActiveWorkspace:
        with self._connection() as db:
            db.execute("UPDATE workspace SET campaign_id=NULL,session_id=NULL,encounter_id=NULL WHERE id=1")
        return ActiveWorkspace()

    def import_legacy_session(self, campaign_id: str, scene: dict, battle: AdvancedBattle,
                              title: str = "Imported local session") -> Session:
        title = _text(title, "Session title", 200, required=True)
        scene_data, battle_data = _scene_json(scene), _battle_json(battle)
        battle_title = _text(battle.title, "Encounter title", 200, required=True)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require(db, "campaigns", campaign_id, "Campaign")
            identity = self._insert_session(db, campaign_id, title, "", scene_data)
            self._insert_encounter(db, identity, battle_title, battle_data)
            row = self._require(db, "sessions", identity, "Session")
        return self._from_row(Session, row)


class SessionSceneStore:
    def __init__(self, repository: CampaignRepository, session_id: str):
        self.repository, self.session_id = repository, session_id
        self.path = repository.path

    def load(self) -> dict:
        return self.repository.load_scene(self.session_id)

    def save(self, scene: dict):
        self.repository.save_scene(self.session_id, scene)


class CampaignBattleStore:
    def __init__(self, repository: CampaignRepository, encounter_id: str):
        self.repository, self.encounter_id = repository, encounter_id
        self.path = repository.path

    def load(self) -> AdvancedBattle:
        return self.repository.load_battle(self.encounter_id)

    def save(self, battle: AdvancedBattle):
        self.repository.save_battle(self.encounter_id, battle)
