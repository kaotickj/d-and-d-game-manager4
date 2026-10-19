"""Parse and validate local AI character suggestions before applying to a Forge.

An AI can suggest choices; race, class, level, ability constraints, skill
budget, feat limits and spell lists are checked by deterministic local rules.
"""
from __future__ import annotations

import json
from .creation import ABILITIES, adjusted_scores
from .character_sheet import TEMPLATES, NPC_CLASS_TEMPLATES, ALIGNMENTS, SKILLS
from .character_sheet import class_specs, skill_budget, validate_allocations
from .build_rules import feat_review, inventory_from_text
from .spell_rules import default_spellbook, validate_spellbook

def parse_draft(text: str) -> dict:
    if not isinstance(text,str) or len(text)>16000:
        raise ValueError("AI character draft must be text under 16,000 characters.")
    decoder=json.JSONDecoder()
    for i,ch in enumerate(text):
        if ch=="{":
            try:
                parsed,_=decoder.raw_decode(text[i:])
            except ValueError:
                continue
            if isinstance(parsed,dict):
                return parsed
    raise ValueError("No valid JSON object in AI response. Edit the draft or regenerate.")

def _short(value,name,length=4000):
    if not isinstance(value,str) or len(value)>length:
        raise ValueError(f"{name} must be text under {length} characters.")
    return value.strip()

def _list(value,name,maxlen=100):
    if not isinstance(value,list) or len(value)>maxlen or any(
            not isinstance(x,str) or not x.strip() or len(x)>180 for x in value):
        raise ValueError(f"{name} must be a list of short names.")
    return list(dict.fromkeys(x.strip() for x in value))

def validate_draft(draft: dict, *, race: str, class_name: str,
                   kind: str, racial_modifiers: dict | None = None,
                   desired_gender: str = "", desired_age: str = "") -> dict:
    if not isinstance(draft,dict):
        raise ValueError("Character proposal must be a JSON object.")
    if draft.get("kind") != kind or kind not in ("pc","npc"):
        raise ValueError("The generated record must match PC or NPC creation.")
    if draft.get("race") != race or draft.get("class") != class_name:
        raise ValueError(
            "The model changed your selected race or class. Regenerate with "
            "the selected race/class, or change them in Forge first.")
    if class_name not in TEMPLATES:
        raise ValueError("AI builds require a verified class template.")
    if kind=="pc" and class_name in NPC_CLASS_TEMPLATES:
        raise ValueError("NPC classes cannot be imported as player characters.")
    if kind=="npc" and racial_modifiers is None:
        raise ValueError("Unverified NPC ancestry needs a manual character build.")
    scores=draft.get("base_scores")
    if (not isinstance(scores,dict) or set(scores)!=set(ABILITIES) or
            any(type(v) is not int or not 3<=v<=18 for v in scores.values())):
        raise ValueError("Six unadjusted base scores of 3-18 are required.")
    final=adjusted_scores(scores,race,racial_modifiers)
    alignment=_short(draft.get("alignment","True Neutral"),"alignment",32)
    if alignment not in ALIGNMENTS:
        raise ValueError("Choose a D&D 3.5 alignment.")
    feats=_list(draft.get("feats",[]),"feats",8)
    warnings=feat_review(feats,final,class_name=class_name,race=race,
        bab=1 if class_name in ("Fighter","Barbarian","Ranger","Paladin") else 0,
        strict=True)
    if warnings:
        raise ValueError("Unverified AI-selected feat(s): "+ "; ".join(warnings))
    gear=_list(draft.get("equipment",[]),"equipment",60)
    inventory=_short(draft.get("inventory",""),"inventory",9000)
    inventory_from_text(inventory or "\n".join(gear))
    skill_ranks=draft.get("skills_half_ranks",{})
    if (not isinstance(skill_ranks,dict) or
            any(name not in SKILLS or type(v) is not int or v<0
                for name,v in skill_ranks.items())):
        raise ValueError("Skills require SRD names and half-rank integer units.")
    if class_name=="Expert":
        raise ValueError("Expert requires selecting ten class skills in Custom Forge.")
    spec=class_specs(class_name)
    budget=skill_budget(class_name,final["intelligence"],race)
    validate_allocations(skill_ranks,spec,budget)
    magic=draft.get("spellbook")
    if magic is None:
        magic=default_spellbook(class_name,final)
    magic=validate_spellbook(class_name,final,magic)
    from .identity_rules import identity_text
    gender = identity_text(draft.get("gender", ""), "Gender")
    age = identity_text(draft.get("age", ""), "Age")
    if desired_gender and gender != desired_gender:
        raise ValueError("AI draft changed the selected gender.")
    if desired_age and age != desired_age:
        raise ValueError("AI draft changed the selected age.")
    features=_list(draft.get("class_features",[]),"class_features",30)
    return dict(name=_short(draft.get("name",""),"name",200),
        gender=gender, age=age,
        base_scores=scores, alignment=alignment, feats=feats,
        equipment=gear,inventory=inventory or "\n".join(gear),
        skills_half_ranks=skill_ranks, spellbook=magic,
        class_features=features,
        languages=_list(draft.get("languages",["Common"]),"languages",12),
        deity=_short(draft.get("deity",""),"deity",100),
        appearance=_short(draft.get("appearance",""),"appearance",1200),
        personality=_short(draft.get("personality",""),"personality",1200),
        biography=_short(draft.get("biography",""),"biography",5000),
        notes=_short(draft.get("notes",""),"notes",1200))
