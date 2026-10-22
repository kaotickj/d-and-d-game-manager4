"""Read-only, complete campaign memory for explicitly requested Scribe work.

Campaign membership and scene presence are distinct. Preparation is background,
not evidence that events occurred. Context is rejected when it does not fit;
saved records and historical recaps are never silently shortened or rewritten.
"""
from __future__ import annotations

import json

from .scene_context import MAX_CONTEXT, record_details, validate_scene

CAMPAIGN_TASKS = frozenset(("session_plan", "campaign_plan", "recap", "dm_advice", "dm"))
_CAMPAIGN_FIELDS = ("id", "name", "description", "notes", "archived", "created_at", "updated_at")
_SESSION_FIELDS = ("id", "campaign_id", "title", "session_date", "status", "created_at", "updated_at")
_TASK_GUIDANCE = {
    "campaign_plan": "Propose a campaign plan that respects these saved facts. Label new ideas as proposals.",
    "session_plan": "Prepare this selected session. Separate proposed scenes and possible outcomes from established events.",
    "dm_advice": "Advise the DM about the supplied situation. Ask for missing information; no live battle state is implied by campaign membership.",
    "dm": "Narrate the supplied scene for players. Keep DM-only notes, hidden motives, and unresolved secrets out of read-aloud prose.",
    "recap": "Write a recap using recorded session events and the DM's confirmed outcomes only. A plan, roster, or scene description is not evidence that an event happened. If the notes contain only plans or no outcomes, request event notes instead of inventing a recap.",
}


def _json(value) -> str:
    # Formatting whitespace is expendable; saved facts and fields are not.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _metadata(record, names) -> dict:
    return {name: getattr(record, name, "") for name in names}


def _validate_limit(max_chars):
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("The Scribe context limit must be a positive whole number.")


def _record_details(record) -> str:
    return _json(json.loads(record_details(record)))


def _resolve_records(library, party_ids, scene_ids=()):
    resolved = []
    for record_id in dict.fromkeys(list(party_ids) + list(scene_ids)):
        record = library.get(record_id)
        role = "party" if record_id in party_ids else "scene"
        if record is None or record.archived:
            state = "missing" if record is None else "archived"
            label = record.name if record is not None else record_id
            raise ValueError(
                f"Campaign {role} record {label!r} is {state}. Restore it or "
                "revise the campaign party/session scene before loading the Scribe. "
                "No roster details were silently omitted.")
        roles = []
        if record_id in party_ids:
            roles.append("campaign party; current presence not implied")
        if record_id in scene_ids:
            roles.append("explicitly present in the selected scene")
        resolved.append((record, roles))
    return resolved


def _bounded_context(parts, max_chars):
    context = "\n\n".join(parts)
    if len(context) > max_chars:
        raise ValueError(
            f"Complete campaign context needs {len(context):,} characters, but "
            f"the Scribe limit is {max_chars:,}. Shorten campaign/session notes "
            "or revise the selected party and scene before loading it. "
            "No campaign history or character details were silently omitted.")
    return context


def build_campaign_context(repository, library, session_id: str, *,
                           task: str = "session_plan", max_chars: int = MAX_CONTEXT) -> str:
    """Resolve a selected session's campaign, history, and precise saved roster.

    Previous recaps follow the repository's session order and stop at the
    selected session. Only completed sessions contribute historical recaps;
    future/planned session text is not pulled into the selected session's facts.
    """
    if not isinstance(task, str) or task not in CAMPAIGN_TASKS:
        raise ValueError("Choose campaign planning, session preparation, narration, advice, or recap.")
    _validate_limit(max_chars)
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Select a saved campaign session before loading Scribe context.")
    session = repository.get_session(session_id)
    if session is None:
        raise ValueError("The selected session no longer exists. Reopen campaign management and select a session.")
    campaign = repository.get_campaign(session.campaign_id)
    if campaign is None:
        raise ValueError("The selected session's campaign no longer exists. Review campaign management before using the Scribe.")
    scene = validate_scene(repository.load_scene(session.id))
    sessions = repository.list_sessions(campaign.id)
    prior_recaps = []
    found_session = False
    for previous in sessions:
        if previous.id == session.id:
            found_session = True
            break
        if previous.status == "completed" and previous.recap.strip():
            prior_recaps.append({**_metadata(previous, _SESSION_FIELDS),
                                 "recorded_recap": previous.recap})

    if not found_session:
        raise ValueError("The selected session is missing from its campaign history. Reopen campaign management before loading the Scribe.")
    party_ids = list(dict.fromkeys(repository.party_ids(campaign.id)))
    resolved = _resolve_records(library, party_ids, scene["record_ids"])

    parts = [
        "D&D 3.5 CAMPAIGN / SESSION CONTEXT",
        "Use saved data as the DM's supplied campaign information. Distinguish "
        "established facts, recorded events, and proposed plans. Do not invent "
        "dice results, change saved statistics, or decide player actions. "
        "DM-only material must remain separate from player-facing narration.",
        f"Requested task: {task}\n{_TASK_GUIDANCE[task]}",
        "CAMPAIGN BACKGROUND / DM-ONLY NOTES\n" + _json(_metadata(campaign, _CAMPAIGN_FIELDS)),
        "SELECTED SESSION METADATA\n" + _json(_metadata(session, _SESSION_FIELDS)),
        "SELECTED SESSION NOTES / DM-SUPPLIED EVENT EVIDENCE\n"
        "Notes may contain plans as well as events. Only explicit recorded "
        "outcomes establish what happened; status alone does not establish events.\n"
        + (session.notes if session.notes else "[No session notes recorded.]"),
        "SELECTED SESSION EXISTING RECAP / DM-RECORDED HISTORY\n"
        + (session.recap if session.recap else "[No recap recorded.]"),
        "PREVIOUS COMPLETED SESSION RECAPS / RECORDED HISTORY\n"
        + (_json(prior_recaps) if prior_recaps else "[No earlier completed recaps recorded.]"),
        "SELECTED SESSION SCENE / PREPARATION BACKGROUND\n"
        "A saved scene describes a situation; it does not prove that the party "
        "visited it, fought its creatures, or obtained its clues.\n" + _json(scene),
        "CAMPAIGN PARTY MEMBERSHIP / PRESENCE NOT IMPLIED\n" + _json(party_ids),
        "EXPLICIT SCENE ROSTER\n" + _json(scene["record_ids"]),
        f"Complete unique library records: {len(resolved)}",
    ]
    for index, (record, roles) in enumerate(resolved, 1):
        parts.append(f"RECORD {index} / {record.name} ({record.kind})\n"
                     f"Use: {'; '.join(roles)}\n" + _record_details(record))
    return _bounded_context(parts, max_chars)


def build_campaign_planning_context(repository, library, campaign_id: str, *,
                                    max_chars: int = MAX_CONTEXT) -> str:
    """Plan a campaign before it has sessions, using full saved party/history."""
    _validate_limit(max_chars)
    if not isinstance(campaign_id, str) or not campaign_id:
        raise ValueError("Select a saved campaign before loading campaign planning context.")
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise ValueError("The selected campaign no longer exists. Reopen campaign management and select a campaign.")
    party_ids = list(dict.fromkeys(repository.party_ids(campaign.id)))
    records = _resolve_records(library, party_ids)
    completed_recaps = [
        {**_metadata(session, _SESSION_FIELDS), "recorded_recap": session.recap}
        for session in repository.list_sessions(campaign.id)
        if session.status == "completed" and session.recap.strip()
    ]
    parts = [
        "D&D 3.5 CAMPAIGN PLANNING CONTEXT",
        "Use saved data as the DM's supplied campaign information. Keep "
        "established facts separate from proposed plans. Do not invent dice "
        "results, change saved statistics, or decide player actions. DM-only "
        "material must remain separate from player-facing narration.",
        "Requested task: campaign_plan\n" + _TASK_GUIDANCE["campaign_plan"],
        "No session or scene is selected. This is campaign-wide preparation; "
        "party membership does not establish where characters are or what "
        "events occurred. Planned session notes are not included as history.",
        "CAMPAIGN BACKGROUND / DM-ONLY NOTES\n" + _json(_metadata(campaign, _CAMPAIGN_FIELDS)),
        "COMPLETED SESSION RECAPS / RECORDED HISTORY\n"
        + (_json(completed_recaps) if completed_recaps else "[No completed recaps recorded.]"),
        "CAMPAIGN PARTY MEMBERSHIP / PRESENCE NOT IMPLIED\n" + _json(party_ids),
        f"Complete unique library records: {len(records)}",
    ]
    for index, (record, roles) in enumerate(records, 1):
        parts.append(f"RECORD {index} / {record.name} ({record.kind})\n"
                     f"Use: {'; '.join(roles)}\n" + _record_details(record))
    return _bounded_context(parts, max_chars)
