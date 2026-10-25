"""First-level SRD feat prerequisite checks and structured inventory.

Rules not encoded yet must be explicitly flagged for DM review. Never treat
unknown feat names as validated simply because a text model proposed them.
"""
from __future__ import annotations

import re

SIMPLE_FEATS = frozenset({
    "Alertness","Blind-Fight","Combat Casting","Endurance",
    "Great Fortitude","Improved Initiative","Iron Will","Lightning Reflexes",
    "Point Blank Shot","Toughness","Track","Skill Focus","Run","Negotiator",
    "Stealthy","Acrobatic","Athletic","Deceitful","Deft Hands","Diligent",
    "Investigator","Magical Aptitude","Nimble Fingers","Persuasive",
    "Self-Sufficient",
})
# prerequisite ability, score, another feat, minimum BAB
PREREQUISITES = {
    # https://www.d20srd.org/srd/feats.htm#dodge
    "Dodge": ("dexterity",13,None,0),
    "Power Attack": ("strength",13,None,0),
    "Cleave": ("strength",13,"Power Attack",0),
    "Great Cleave": ("strength",13,"Cleave",4),
    "Combat Expertise": ("intelligence",13,None,0),
    "Improved Trip": ("intelligence",13,"Combat Expertise",0),
    "Improved Disarm": ("intelligence",13,"Combat Expertise",0),
    "Mobility": ("dexterity",13,"Dodge",0),
    "Spring Attack": ("dexterity",13,"Mobility",4),
    "Rapid Shot": ("dexterity",13,"Point Blank Shot",0),
    "Precise Shot": (None,0,"Point Blank Shot",0),
    "Manyshot": ("dexterity",17,"Rapid Shot",6),
    "Weapon Finesse": (None,0,None,1),
    "Weapon Focus": (None,0,None,1),
}


def prerequisite_failures(feat: str, owned: set[str], scores: dict[str, int],
                          bab: int) -> list[str]:
    """Review the complete encoded prerequisite chain without changing a sheet.

    Ownership alone does not prove that a legacy prerequisite feat is usable.
    Same-level selections may be included in ``owned`` by the caller. Class
    bonus exceptions remain the caller's responsibility. Weapon choice and
    proficiency are not encoded here and still require DM review.

    SRD: https://www.d20srd.org/srd/feats.htm#prerequisites
    https://www.d20srd.org/srd/feats.htm#greatCleave
    https://www.d20srd.org/srd/feats.htm#springAttack
    https://www.d20srd.org/srd/feats.htm#manyshot
    Those feats explicitly require the earlier feats in their complete chains.
    The public four-field table remains compatible with existing callers.
    """
    failures = []
    visiting = set()
    reviewed = set()

    def add(message):
        if message not in failures:
            failures.append(message)

    def review(name):
        if name in visiting:
            add(f"{feat}: cyclic prerequisite rules require DM review.")
            return
        if name in reviewed:
            return
        rule = PREREQUISITES.get(name)
        if rule is None:
            if name not in SIMPLE_FEATS:
                add(f"Unverified feat or prerequisites: {name} (DM review).")
            return
        visiting.add(name)
        attr, minimum, needed, min_bab = rule
        if attr and scores.get(attr, 0) < minimum:
            add(f"{feat} requires {attr.title()} {minimum}+.")
        if bab < min_bab:
            add(f"{feat} requires base attack bonus +{min_bab}.")
        if needed:
            if needed not in owned:
                add(f"{feat} requires {needed}.")
            review(needed)
        visiting.remove(name)
        reviewed.add(name)

    review(feat)
    return failures


FIGHTER_BONUS = frozenset({
    "Blind-Fight","Cleave","Combat Expertise","Dodge","Great Cleave",
    "Improved Disarm","Improved Trip","Mobility","Point Blank Shot",
    "Power Attack","Precise Shot","Rapid Shot","Spring Attack",
    "Weapon Finesse","Weapon Focus",
})
UNSUPPORTED = ("Specialization", "Metamagic", "Item Creation")
_AUTOMATIC_CLASS_FEATS = {
    "Wizard": {1: ("Scribe Scroll",)},
    # https://www.d20srd.org/srd/classes/ranger.htm
    "Ranger": {1: ("Track",), 3: ("Endurance",)},
}


def automatic_class_feats(class_name: str, level: int = 1) -> list[str]:
    """Encoded class-granted feats owned by this class level, outside slots."""
    return [feat for required, feats in _AUTOMATIC_CLASS_FEATS.get(class_name, {}).items()
            if level >= required for feat in feats]


def first_level_feat_slots(class_name: str, race: str) -> dict:
    return {
        "general": 1 + (1 if race=="Human" else 0),
        "fighter_bonus": 1 if class_name=="Fighter" else 0,
        "automatic": automatic_class_feats(class_name),
    }


def feat_review(feats: list[str], scores: dict[str,int], *,
                class_name: str, race: str, bab: int = 0,
                strict: bool = False) -> list[str]:
    """Validate known first-level feat rules, flag unmodeled feats honestly.

    Feat-specific ability and chain checks work for encoded core feats.
    Fighter has an additional combat feat. This model does not substitute
    for full PHB/monster feat prerequisites.
    """
    if not isinstance(feats,list) or len(feats)>30:
        raise ValueError("Feats must be a list of at most 30.")
    selected=[feat.strip() for feat in feats if isinstance(feat,str) and feat.strip()]
    if len(selected)!=len(feats):
        raise ValueError("Feats must all be nonempty strings.")
    if len(selected)!=len(set(selected)):
        raise ValueError("Duplicate feats require a feat-specific repeatability rule.")
    info=first_level_feat_slots(class_name,race)
    # Saved first-level lists may include their automatic class grants alongside
    # chosen feats. Those grants are neither selections nor unverified choices.
    choices=[feat for feat in selected if feat not in info["automatic"]]
    capacity=info["general"]+info["fighter_bonus"]
    if len(choices)>capacity:
        msg=f"Selected {len(choices)} feats but {race} {class_name} has {capacity} first-level selections."
        if strict:raise ValueError(msg)
        return [msg]
    warnings=[]
    for feat in choices:
        rule=PREREQUISITES.get(feat)
        if rule:
            failures = prerequisite_failures(
                feat, set(selected) | set(info["automatic"]), scores, bab)
            if strict and failures:
                raise ValueError(failures[0])
            warnings.extend(failures)
            if feat == "Weapon Focus":
                warnings.append("Weapon Focus requires a chosen weapon and proficiency confirmation (DM review).")
        elif feat not in SIMPLE_FEATS:
            warnings.append(f"Unverified feat or prerequisites: {feat} (DM review).")
    if class_name=="Fighter" and len(choices)>info["general"]:
        if not any(feat in FIGHTER_BONUS for feat in choices):
            warnings.append("Fighter bonus feat must be a qualifying fighter feat.")
    return warnings


def inventory_from_text(value: str) -> list[dict]:
    """Parse one item per line: '3 x Torch' or 'Spellbook'.

    First-level weight, item price and slot restrictions require catalog
    entries that are not yet implemented; do not invent them.
    """
    if not isinstance(value,str) or len(value)>15000:
        raise ValueError("Inventory text must be under 15,000 characters.")
    result=[]
    for line in value.splitlines():
        name=line.strip()
        if not name: continue
        qty=1
        m=re.fullmatch(r"(\d{1,4})\s*[xX×]\s*(.+)",name)
        if m:
            qty=int(m.group(1))
            name=m.group(2).strip()
        if not 1<=qty<=999 or not 1<=len(name)<=180:
            raise ValueError("Inventory items require a name and quantity 1-999.")
        result.append({"name":name,"quantity":qty,"container":"carried",
                       "equipped":False})
    if len(result)>150:
        raise ValueError("At most 150 inventory lines are supported.")
    return result


def inventory_to_text(items: list[dict]) -> str:
    lines=[]
    for item in items:
        quantity=item.get("quantity",1)
        label=item.get("name","")
        lines.append(f"{quantity} x {label}" if quantity!=1 else label)
    return "\n".join(lines)
