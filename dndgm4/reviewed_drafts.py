"""Reviewable text proposals with atomic, campaign-scoped application.

No model is called here. Sources are saved text, not independent verification:
the DM must identify which excerpts actually record events before citing them.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from .campaigns import CampaignRepository, Session, _session_values
from .world import WorldRepository, details_json

PROPOSAL_MARKER = "[REVIEWED PLAN / PROPOSAL - not a recorded event]"
_CITATION = re.compile(r"\[E-[^\]\r\n]+\]")
_FIELDS = {"session": ("notes", "recap"), "world": ("dm_notes", "summary")}


def _text(value, label, maximum=100000):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} must be text of at most {maximum:,} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} contains invalid Unicode.") from exc
    return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    campaign_id: str
    kind: str
    target_id: str
    label: str
    canonical_json: str
    digest: str

    @property
    def values(self):
        return json.loads(self.canonical_json)

    @property
    def allowed_fields(self):
        result = _FIELDS.get(self.kind, ())
        if self.kind == "world" and self.values["kind"] == "handout":
            result += ("player_text",)
        return result

    def field_text(self, field):
        if field not in self.allowed_fields:
            raise ValueError("Choose an allowed text field for this target.")
        data = self.values
        return json.loads(data["details_json"])["player_text"] if field == "player_text" else data[field]


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    campaign_id: str
    session_id: str
    source_kind: str
    source_id: str
    ordinal: int
    title: str
    text: str
    source_digest: str

    @property
    def citation(self):
        identity = _json([self.campaign_id, self.session_id, self.source_kind,
                          self.source_id, self.ordinal, self.text])
        return "[E-" + _digest(identity)[:12] + "]"


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    before: str
    draft: str
    after: str


@dataclass(frozen=True, slots=True)
class DraftProposal:
    baseline: TargetSnapshot
    changes: tuple[FieldChange, ...]
    evidence: tuple[SourceEvidence, ...] = ()
    recorded_evidence_confirmed: bool = False


class ReviewedDraftsRepository:
    """Existing library tables only; no additional migration or audit schema."""

    def __init__(self, database_path, campaign_id):
        self.campaigns = CampaignRepository(database_path)
        self.world = WorldRepository(database_path)
        self.path = self.campaigns.library.path
        self.campaign_id = _text(campaign_id, "Campaign ID", 200)
        if not self.campaign_id:
            raise ValueError("Select a saved campaign before reviewing drafts.")
        with self.campaigns._connection() as db:
            self._campaign(db)

    def _campaign(self, db):
        row = db.execute("SELECT * FROM campaigns WHERE id=?", (self.campaign_id,)).fetchone()
        if row is None or row["archived"]:
            raise ValueError("Select an existing, unarchived campaign.")
        return row

    def list_targets(self):
        with self.campaigns._connection() as db:
            self._campaign(db)
            result = [("session", row["id"], "Session: " + row["title"])
                      for row in db.execute("SELECT id,title FROM sessions WHERE campaign_id=? ORDER BY session_date,created_at,id",
                                            (self.campaign_id,))]
            result += [("world", row["id"], "World: " + row["name"])
                       for row in db.execute("SELECT id,name FROM world_records WHERE campaign_id=? AND archived=0 ORDER BY name,id",
                                             (self.campaign_id,))]
        return result

    def _snapshot(self, db, kind, target_id):
        self._campaign(db)
        if kind not in _FIELDS:
            raise ValueError("Choose a saved session or world entry.")
        table = "sessions" if kind == "session" else "world_records"
        row = db.execute(f"SELECT * FROM {table} WHERE id=? AND campaign_id=?",
                         (target_id, self.campaign_id)).fetchone()
        if row is None or (kind == "world" and row["archived"]):
            raise ValueError("The selected target is missing, archived, or belongs to another campaign.")
        if kind == "session":
            _session_values(self.campaigns._from_row(Session, row))
        else:
            self.world._from_row(row)
        # Whole-row snapshots catch simultaneous journal/scene changes even
        # though application updates only explicitly selected text columns.
        data = dict(row)
        canonical = _json(data)
        label = data["title"] if kind == "session" else data["name"]
        return TargetSnapshot(self.campaign_id, kind, target_id, label, canonical, _digest(canonical))

    def snapshot(self, kind, target_id):
        with self.campaigns._connection() as db:
            return self._snapshot(db, kind, target_id)

    def _evidence(self, db, session_id):
        session = self._snapshot(db, "session", session_id).values
        result = []
        notes = _text(session["notes"], "Saved session notes")
        # Our own planning drafts can never be reclassified as historical
        # evidence merely by selecting their generated prose.
        if notes.strip() and not notes.lstrip().startswith(PROPOSAL_MARKER):
            for index, paragraph in enumerate(re.split(r"\n\s*\n", notes)):
                if paragraph.strip() and PROPOSAL_MARKER not in paragraph:
                    result.append(SourceEvidence(self.campaign_id, session_id, "session_notes", session_id,
                                                 index, "Session notes - excerpt " + str(index + 1),
                                                 paragraph.strip(), _digest(notes)))
        encounters = db.execute("SELECT * FROM encounters WHERE session_id=? ORDER BY created_at,id", (session_id,)).fetchall()
        for encounter in encounters:
            battle = self.campaigns._read_battle(encounter["battle_json"])
            for index, line in enumerate(battle.log):
                if line.strip():
                    result.append(SourceEvidence(self.campaign_id, session_id, "encounter_log", encounter["id"],
                                                 index, encounter["title"] + " - log " + str(index + 1),
                                                 line, _digest(encounter["battle_json"])))
        if len(result) > 10000:
            raise ValueError("This session has too many evidence excerpts; no excerpts were silently omitted.")
        return tuple(result)

    def load_evidence(self, session_id):
        with self.campaigns._connection() as db:
            return self._evidence(db, session_id)

    def prepare(self, baseline, drafts, *, evidence=(), recorded_evidence_confirmed=False):
        if (not isinstance(baseline, TargetSnapshot) or baseline.campaign_id != self.campaign_id
                or baseline.digest != _digest(baseline.canonical_json)):
            raise ValueError("The draft baseline does not belong to this campaign or is invalid.")
        if not isinstance(drafts, dict) or not drafts:
            raise ValueError("Add at least one text-field draft for review.")
        if any(field not in baseline.allowed_fields for field in drafts):
            raise ValueError("Drafts may change only the allowed text fields.")
        evidence = tuple(evidence)
        if len(evidence) > 100 or any(not isinstance(item, SourceEvidence) for item in evidence):
            raise ValueError("Select at most 100 saved evidence excerpts.")
        if len({item.citation for item in evidence}) != len(evidence):
            raise ValueError("An evidence excerpt was selected more than once.")
        if evidence and (baseline.kind != "session" or "recap" not in drafts):
            raise ValueError("Recorded-event evidence is used only for a selected session recap.")
        for item in evidence:
            if item.campaign_id != self.campaign_id or item.session_id != baseline.target_id:
                raise ValueError("Recap evidence must belong to the selected session and campaign.")
        if "recap" in drafts and (not evidence or recorded_evidence_confirmed is not True):
            raise ValueError("Select saved evidence and confirm that it records actual events, rather than plans.")
        changes = []
        for field, raw in drafts.items():
            raw = _text(raw, "Draft").strip()
            if not raw:
                raise ValueError("A draft cannot be blank.")
            if field == "recap":
                citations = {item.citation for item in evidence}
                used = set(_CITATION.findall(raw))
                if not used or used - citations:
                    raise ValueError("The recap must cite selected evidence; unknown citation identifiers are rejected.")
                for paragraph in re.split(r"\n\s*\n", raw):
                    if paragraph.strip() and not _CITATION.search(paragraph):
                        raise ValueError("Cite selected recorded evidence in every recap paragraph.")
                retained = [item for item in evidence if item.citation in used]
                sources = "\n\nRECORDED SOURCE EVIDENCE (DM reviewed)\n" + "\n\n".join(
                    f"{item.citation} {item.title}\nSource: {item.source_kind}:{item.source_id}"
                    f"; excerpt {item.ordinal + 1}; SHA-256 {item.source_digest}\n{item.text}"
                    for item in retained)
                after = raw + sources
            elif field == "player_text":
                after = raw
            else:
                after = PROPOSAL_MARKER + "\n\n" + raw
            _text(after, "Reviewed text", 20000 if field == "summary" else 100000)
            changes.append(FieldChange(field, baseline.field_text(field), raw, after))
        return DraftProposal(baseline, tuple(changes), evidence, recorded_evidence_confirmed is True)

    def apply(self, proposal, *, selected_fields=None, public_reviewed=False):
        if not isinstance(proposal, DraftProposal):
            raise ValueError("Prepare and review a draft before applying it.")
        rebuilt = self.prepare(proposal.baseline, {item.field: item.draft for item in proposal.changes},
                               evidence=proposal.evidence,
                               recorded_evidence_confirmed=proposal.recorded_evidence_confirmed)
        if rebuilt != proposal:
            raise ValueError("The proposal changed after preparation. Prepare its review again.")
        selected = tuple(item.field for item in proposal.changes) if selected_fields is None else tuple(selected_fields)
        if not selected or len(set(selected)) != len(selected) or set(selected) - {item.field for item in proposal.changes}:
            raise ValueError("Select at least one proposed field, without duplicates or extra fields.")
        if set(selected) & {"summary", "player_text"} and public_reviewed is not True:
            raise ValueError("Review the complete public text and explicitly confirm it contains no DM secrets.")
        baseline = proposal.baseline
        with self.campaigns._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._snapshot(db, baseline.kind, baseline.target_id)
            if current != baseline:
                raise ValueError("The saved target changed after the draft was loaded. Reload it and review again; your draft is preserved.")
            if "recap" in selected:
                available = {item.citation: item for item in self._evidence(db, baseline.target_id)}
                if any(available.get(item.citation) != item for item in proposal.evidence):
                    raise ValueError("Recorded source evidence changed. Reload it and review the recap again.")
            updates = {item.field: item.after for item in proposal.changes if item.field in selected}
            if "player_text" in updates:
                details = json.loads(current.values["details_json"])
                details["player_text"] = updates.pop("player_text")
                updates["details_json"] = details_json("handout", details)
            table = "sessions" if baseline.kind == "session" else "world_records"
            assignments = ",".join(field + "=?" for field in updates)
            db.execute(f"UPDATE {table} SET {assignments},updated_at=CURRENT_TIMESTAMP WHERE id=? AND campaign_id=?",
                       (*updates.values(), baseline.target_id, self.campaign_id))
            saved = self._snapshot(db, baseline.kind, baseline.target_id)
        return saved


def build_draft_context(baseline, field, draft="", evidence=()):
    """Explicit selected-field context; public work never loads private fields."""
    if field not in baseline.allowed_fields:
        raise ValueError("Choose an allowed text field.")
    public = field in ("summary", "player_text")
    parts = ["D&D 3.5 REVIEWABLE TEXT DRAFT", "Target field: " + field,
             "Write only a proposal for DM review. Do not invent rolls, awards, statistics or recorded outcomes.",
             "PUBLIC TEXT: Include no secrets. Only the selected public field is loaded." if public else
             "PRIVATE DM WORK: Keep plans separate from recorded events.",
             "CURRENT SELECTED FIELD:\n" + baseline.field_text(field),
             "EDITABLE REQUEST / DRAFT:\n" + _text(draft, "Draft")]
    if field == "recap":
        if not evidence:
            raise ValueError("Select recorded evidence before requesting a recap draft.")
        parts.append("Cite the supplied [E-...] identifiers in every recap paragraph. "
                     "Use only recorded outcomes; selected notes still require the DM's factual review.")
        for item in evidence:
            parts.append(item.citation + " " + item.title + "\n" + item.text)
    context = "\n\n".join(parts)
    if len(context) > 6000:
        raise ValueError("Selected field, request and evidence exceed the Scribe's 6,000-character limit. Nothing was shortened.")
    return context
