"""D&D 3.5 spellbook, inventory, feat and AI-draft regression coverage."""
import json
import unittest
from dndgm4.spell_rules import (spell_profile,default_spellbook,
                                validate_spellbook,SPELL_LISTS)
from dndgm4.build_rules import (feat_review,first_level_feat_slots,
                                inventory_from_text,inventory_to_text)
from dndgm4.ai_character import parse_draft,validate_draft
from dndgm4.creation import ABILITIES,build_character
from dndgm4.character_sheet import (TEMPLATES,allocate_default_skills,
                                    skill_budget,build_sheet,load_sheet)

BASE=dict.fromkeys(ABILITIES,12)


class FirstLevelRulesTests(unittest.TestCase):
    def test_sorcerer_slots_and_known(self):
        scores={**BASE,"charisma":16}
        profile=spell_profile("Sorcerer",scores)
        self.assertEqual(profile["slots"],{"0":5,"1":4})
        self.assertEqual(profile["limits"],{"0":4,"1":2})
        b=default_spellbook("Sorcerer",scores)
        self.assertEqual(len(b["known"]["0"]),4)
        self.assertEqual(len(b["known"]["1"]),2)
        validate_spellbook("Sorcerer",scores,b)
        b["known"]["1"].append("Sleep")
        with self.assertRaisesRegex(ValueError,"Too many"):
            validate_spellbook("Sorcerer",scores,b)

    def test_wizard_book_and_preparation(self):
        scores={**BASE,"intelligence":16}
        b=default_spellbook("Wizard",scores)
        self.assertEqual(len(b["spellbook"]["1"]),6)
        self.assertEqual(set(b["spellbook"]["0"]),set(SPELL_LISTS["Wizard"][0]))
        self.assertEqual(spell_profile("Wizard",scores)["slots"]["1"],2)
        validate_spellbook("Wizard",scores,b)
        b["prepared"]["1"]=["Mage Armor","Magic Missile","Sleep"]
        with self.assertRaisesRegex(ValueError,"Too many"):
            validate_spellbook("Wizard",scores,b)
        b["prepared"]["1"]=["Ray of Enfeeblement"]
        with self.assertRaisesRegex(ValueError,"missing from their spellbook"):
            validate_spellbook("Wizard",scores,b)

    def test_cleric_domain_slot_bard_first_level_and_low_ability(self):
        self.assertEqual(spell_profile("Cleric",{**BASE,"wisdom":16})["domain_slot_1"],1)
        self.assertEqual(spell_profile("Cleric",{**BASE,"wisdom":16})["slots"]["1"],2)
        self.assertEqual(spell_profile("Bard",{**BASE,"charisma":16})["slots"]["1"],0)
        self.assertEqual(default_spellbook("Bard",BASE)["known"]["1"],[])
        weak={**BASE,"intelligence":10}
        self.assertEqual(spell_profile("Wizard",weak)["slots"]["1"],0)
        self.assertEqual(default_spellbook("Wizard",weak)["prepared"]["1"],[])

    def test_spell_constraints(self):
        b=default_spellbook("Cleric",BASE)
        b["prepared"]["0"]=["Mage Hand"]
        with self.assertRaisesRegex(ValueError,"cannot use"):
            validate_spellbook("Cleric",BASE,b)
        b=default_spellbook("Sorcerer",{**BASE,"charisma":16})
        b["spellbook"]["1"]=["Magic Missile"]
        with self.assertRaisesRegex(ValueError,"Only Wizards"):
            validate_spellbook("Sorcerer",{**BASE,"charisma":16},b)

    def test_sheet_inventory_spellbook_persistence(self):
        stats={**BASE,"charisma":16}
        c=build_character(name="Vela",race="Human",character_class="Sorcerer",
                          base=stats,method="manual")
        t=TEMPLATES["Sorcerer"]
        budget=skill_budget("Sorcerer",c.intelligence,"Human")
        b=default_spellbook("Sorcerer",{a:getattr(c,a) for a in ABILITIES})
        rec=build_sheet(character=c,class_name="Sorcerer",
            ranks=allocate_default_skills(t,budget),feats=["Improved Initiative"],
            equipment=["Quarterstaff"],alignment="True Neutral",deity="",
            languages=["Common"],appearance="",personality="",background="",
            spellbook=b,inventory=inventory_from_text("3 x Torch\n2 x Rations"))
        sheet=load_sheet(rec)
        self.assertEqual(sheet["spellbook"]["known"]["1"],["Mage Armor","Magic Missile"])
        self.assertEqual(sheet["inventory"][0]["quantity"],3)
        self.assertIn("2 x Rations",inventory_to_text(sheet["inventory"]))

    def test_feat_prerequisites_and_capacity(self):
        self.assertEqual(first_level_feat_slots("Fighter","Human")["general"],2)
        with self.assertRaisesRegex(ValueError,"Strength 13"):
            feat_review(["Power Attack"],BASE,class_name="Fighter",
                        race="Human",bab=1,strict=True)
        with self.assertRaisesRegex(ValueError,"requires Power Attack"):
            feat_review(["Cleave"],{**BASE,"strength":16},
                        class_name="Fighter",race="Human",bab=1,strict=True)
        self.assertFalse(feat_review(["Power Attack","Cleave","Improved Initiative"],
            {**BASE,"strength":16},class_name="Fighter",race="Human",
            bab=1,strict=True))

    def test_ai_draft_accepts_legal_and_rejects_illegal(self):
        p={"kind":"pc","race":"Human","class":"Fighter",
           "name":"Sir Aldric","base_scores":{**BASE,"strength":16,"dexterity":14},
           "alignment":"Lawful Good","feats":["Power Attack","Cleave"],
           "equipment":["Longsword"],"inventory":"2 x Rations",
           "skills_half_ranks":{"Ride":8,"Climb":8},
           "biography":"A royal guard."}
        data=validate_draft(parse_draft("AI draft:\n"+json.dumps(p)),
                            race="Human",class_name="Fighter",kind="pc")
        self.assertEqual(data["name"],"Sir Aldric")
        self.assertEqual(data["base_scores"]["strength"],16)
        with self.assertRaisesRegex(ValueError,"changed your selected"):
            validate_draft({**p,"race":"Elf"},race="Human",
                           class_name="Fighter",kind="pc")
        with self.assertRaisesRegex(ValueError,"Strength 13"):
            validate_draft({**p,"base_scores":dict(BASE)},
                           race="Human",class_name="Fighter",kind="pc")

    def test_ai_draft_unknown_feat_and_spell_rejected(self):
        p={"kind":"pc","race":"Elf","class":"Wizard",
           "name":"Nara","base_scores":{**BASE,"intelligence":16},
           "alignment":"Neutral Good","feats":["Made Up Power"],
           "equipment":["Spellbook"]}
        with self.assertRaisesRegex(ValueError,"Unverified"):
            validate_draft(p,race="Elf",class_name="Wizard",kind="pc")
        p["feats"]=["Improved Initiative"]
        book=default_spellbook("Wizard",{**BASE,"intelligence":16})
        book["spellbook"]["1"][0]="Fireball"
        p["spellbook"]=book
        with self.assertRaisesRegex(ValueError,"cannot use"):
            validate_draft(p,race="Elf",class_name="Wizard",kind="pc")


if __name__=="__main__":
    unittest.main()
