"""Read-only session dashboard projections and narrowly scoped quick notes.

The dashboard owns no campaign or encounter state. In-memory scene and battle
objects remain authoritative until their existing editors save them.
"""
from __future__ import annotations

from .campaigns import ActiveWorkspace, Session, _identifier, _text
from .scene_context import validate_scene


def build_session_snapshot(library, campaigns, workspace, scene, battle=None) -> dict:
    """Project existing state without loading a saved battle over live edits.

    Invalid workspace relationships and missing party references are errors;
    missing optional scene records remain visible so the DM can repair them.
    """
    if not isinstance(workspace, ActiveWorkspace):
        raise ValueError("Choose a valid active workspace.")
    if any(not isinstance(identity, str) for identity in (
            workspace.campaign_id, workspace.session_id, workspace.encounter_id)):
        raise ValueError("Workspace identifiers must be text or blank.")
    checked_scene = validate_scene(scene)
    campaign_name, session_title, session_status = "Standalone", "No active session", ""
    session_notes, encounter_title, party_ids = "", "", []
    if any((workspace.campaign_id, workspace.session_id, workspace.encounter_id)):
        with campaigns._connection() as db:
            campaigns._validate_workspace(db, workspace)
            campaign = campaigns._require(db, "campaigns", workspace.campaign_id, "Campaign")
            session = campaigns._require(db, "sessions", workspace.session_id, "Session")
            campaign_name = campaign["name"]
            session_title, session_status, session_notes = session["title"], session["status"], session["notes"]
            party_ids = [row[0] for row in db.execute(
                "SELECT creature_id FROM campaign_members WHERE campaign_id=? ORDER BY rowid",
                (workspace.campaign_id,))]
            if workspace.encounter_id:
                encounter_title = campaigns._require(
                    db, "encounters", workspace.encounter_id, "Encounter")["title"]

    live_fighters = list(battle.fighters) if battle is not None else []
    party = []
    for identity in party_ids:
        record = library.get(identity)
        if record is None:
            raise ValueError(f"Party member no longer exists: {identity}")
        instances = [fighter for fighter in live_fighters if fighter.source_id == identity]
        encounter_hp = "; ".join(
            f"{fighter.name}: {fighter.hp}/{fighter.max_hp} HP"
            + (f" (+{fighter.temp_hp} temporary)" if fighter.temp_hp else "")
            for fighter in instances) or "Not in encounter"
        party.append({"id": record.id, "name": record.name, "level": record.level,
                      "character_class": record.character_class, "ac": record.armor_class,
                      "max_hp": record.max_hit_points, "encounter_hp": encounter_hp})

    roster = []
    for identity in checked_scene["record_ids"]:
        record = library.get(identity)
        roster.append(record.name if record is not None else f"[Missing record: {identity}]")
    fighters = []
    current_name = ""
    for fighter in sorted(live_fighters, key=lambda item: (
            item.initiative is None, -(item.initiative or 0), -item.dex_mod)):
        current = fighter.uid == battle.current_id
        if current:
            current_name = fighter.name
        conditions = ", ".join(
            item["name"] + (f" ({item['rounds']} rounds)" if item.get("rounds") is not None else "")
            for item in fighter.conditions)
        fighters.append({"id": fighter.uid, "name": fighter.name,
                         "initiative": fighter.initiative, "hp": fighter.hp,
                         "max_hp": fighter.max_hp, "temp_hp": fighter.temp_hp,
                         "ac": fighter.ac, "conditions": conditions,
                         "current": current, "active": fighter.active})
    if battle is not None and battle.current_id and not current_name:
        raise ValueError("Current turn references a missing combatant.")
    scene_text = "\n\n".join(
        f"{label}: {checked_scene[field]}" for field, label in (
            ("scenery", "Scenery"), ("places", "Places"),
            ("time_conditions", "Time and conditions"), ("campaign_notes", "Campaign notes"))
        if checked_scene[field].strip())
    return {
        "workspace_key": (workspace.campaign_id, workspace.session_id, workspace.encounter_id),
        "campaign_name": campaign_name, "session_title": session_title,
        "session_status": session_status, "session_id": workspace.session_id,
        "encounter_title": battle.title if battle is not None else encounter_title or "No active encounter",
        "scene_title": checked_scene["title"], "scene_location": checked_scene["location"],
        "scene_text": scene_text, "session_notes": session_notes,
        "party": party, "scene_roster": roster, "fighters": fighters,
        "phase": battle.phase if battle is not None else "setup",
        "round": battle.round if battle is not None else 0, "current_name": current_name,
        "combat_log": list(battle.log[-30:]) if battle is not None else [],
    }


def append_session_note(campaigns, session_id, note, *, expected_notes) -> Session:
    """Append one reviewed note atomically; reject a stale notes baseline.

    Only notes and updated_at are written, preserving recaps and editor fields
    even when another editor has changed them since the dashboard refreshed.
    """
    session_id = _identifier(session_id, "Session ID")
    note = _text(note, "Quick note", 5000, required=True)
    expected_notes = _text(expected_notes, "Expected session notes")
    with campaigns._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = campaigns._require(db, "sessions", session_id, "Session")
        if row["notes"] != expected_notes:
            raise ValueError("Session notes changed. Refresh the dashboard before appending this note.")
        combined = _text(row["notes"] + ("\n\n" if row["notes"] else "") + note,
                         "Session notes")
        db.execute("UPDATE sessions SET notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                   (combined, session_id))
        saved = campaigns._from_row(Session, campaigns._require(db, "sessions", session_id, "Session"))
    return saved
