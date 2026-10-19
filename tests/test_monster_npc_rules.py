"""3.5 SRD monster core arithmetic and NPC ancestry regression tests."""
import json
import unittest

from dndgm4.creation import ABILITIES, RACIAL_ADJUSTMENTS, build_character
from dndgm4.character_sheet import NPC_CLASS_TEMPLATES, TEMPLATES, build_sheet
from dndgm4.monster_rules import (
    TYPES,SIZES,MonsterBlueprint,base_attack,base_save,compute_monster,
    build_monster,valid_cr)
from dndgm4.npc_races import NPC_RACES,NPC_RACE_NAMES

NEUTRAL=dict.fromkeys(ABILITIES,10)

def blueprint(**changes):
    args=dict(name="Marsh Warden",species="Original Marsh Warden",
              creature_type="Aberration",size="Medium",hit_dice=3,
              abilities=dict(NEUTRAL),cr="2")
    args.update(changes)
    return MonsterBlueprint(**args)

class MonsterTypeRulesTests(unittest.TestCase):
    def test_all_fifteen_35_types_and_size_bands(self):
        self.assertEqual(len(TYPES),15)
        self.assertEqual(len(SIZES),9)
        self.assertEqual(TYPES["Undead"].die,12)
        self.assertEqual(TYPES["Dragon"].attack,"full")
        self.assertEqual(TYPES["Fey"].attack,"poor")

    def test_bab_and_base_saves(self):
        self.assertEqual([base_attack(6,p) for p in ("full","medium","poor")],[6,4,3])
        self.assertEqual([base_save(6,True),base_save(6,False)],[5,2])

    def test_aberration_skills_feats_hp_armor(self):
        data=compute_monster(blueprint())
        self.assertEqual(data["die"],8)
        self.assertEqual(data["bab"],2)
        self.assertEqual((data["fort"],data["ref"],data["will"]),(1,1,3))
        self.assertEqual(data["feats_available"],2)
        self.assertEqual(data["skill_points"],12)
        self.assertEqual(data["hp"],13)
        self.assertEqual(data["armor_class"],10)
        self.assertEqual(data["melee"],2)

    def test_undead_without_con_and_mindless_construct(self):
        undead=blueprint(creature_type="Undead",hit_dice=2,
                         abilities={**NEUTRAL,"constitution":None,"wisdom":14})
        data=compute_monster(undead)
        self.assertEqual(data["hp"],13)
        self.assertEqual(data["fort"],0)
        self.assertEqual(data["will"],5)
        with self.assertRaises(ValueError):
            compute_monster(blueprint(creature_type="Undead"))
        construct=blueprint(creature_type="Construct",hit_dice=2,
                            abilities={**NEUTRAL,"constitution":None,
                                       "intelligence":None})
        data=compute_monster(construct)
        self.assertEqual(data["hp"],31)  # 2d10 avg 11 + medium construct 20
        self.assertEqual(data["skill_points"],0)
        self.assertEqual(data["feats_available"],0)
        self.assertEqual(data["construct_bonus_hp"],20)

    def test_elemental_subtype_and_humanoid_good_saves(self):
        air=compute_monster(blueprint(creature_type="Elemental",subtype="Air",hit_dice=4))
        self.assertEqual((air["fort"],air["ref"],air["will"]),(1,4,1))
        earth=compute_monster(blueprint(creature_type="Elemental",subtype="Earth",hit_dice=4))
        self.assertEqual(earth["fort"],4)
        with self.assertRaisesRegex(ValueError,"elemental subtype"):
            compute_monster(blueprint(creature_type="Elemental"))
        human=compute_monster(blueprint(creature_type="Humanoid",good_save="Will",hit_dice=1))
        self.assertEqual(human["will"],2)

    def test_size_modifiers_and_no_invented_cr(self):
        small=compute_monster(blueprint(size="Small",cr=""))
        self.assertEqual(small["size_ac"],1)
        self.assertEqual(small["armor_class"],11)
        self.assertEqual(small["grapple"],-2)
        self.assertIn("CR is a DM-reviewed value",small["warnings"][0])
        self.assertEqual(valid_cr("1/2"),"1/2")
        self.assertEqual(valid_cr(""),"")
        with self.assertRaises(ValueError):
            valid_cr("not a CR")

    def test_monster_roundtrip_preserves_original_species_and_null_stats(self):
        b=blueprint(creature_type="Undead",hit_dice=4,cr="5",
                    abilities={**NEUTRAL,"constitution":None},natural_armor=4,
                    special_qualities="Darkvision 60 ft.",feats=["Alertness"])
        c=build_monster(b)
        self.assertEqual(c.kind,"monster")
        self.assertEqual(c.constitution,0)
        self.assertEqual(c.challenge_rating,"5")
        info=json.loads(c.sheet_json)
        self.assertIn("constitution",info["null_abilities"])
        self.assertEqual(info["special_qualities"],"Darkvision 60 ft.")
        self.assertEqual(info["hit_dice"],4)

    def test_rolled_hp_deterministic_injected_die(self):
        dice=iter((2,3,4))
        stats=compute_monster(blueprint(hit_dice=3,hp_method="rolled"),
                              roller=lambda a,b:next(dice))
        self.assertEqual(stats["hp"],9)

class NPCRulesTests(unittest.TestCase):
    def test_npc_registry_and_five_classes(self):
        self.assertTrue({"Goblin","Kobold","Orc","Hobgoblin"}.issubset(NPC_RACES))
        self.assertTrue({"Gnoll","Lizardfolk","Dragon"}.issubset(NPC_RACE_NAMES))
        self.assertTrue({"Warrior","Commoner","Adept","Aristocrat","Expert"}.issubset(NPC_CLASS_TEMPLATES))
        self.assertEqual(NPC_CLASS_TEMPLATES["Warrior"].hit_die,8)
        self.assertEqual(NPC_CLASS_TEMPLATES["Commoner"].hit_die,4)
        self.assertEqual(NPC_CLASS_TEMPLATES["Expert"].skill_points,6)
        self.assertEqual(NPC_RACES["Hobgoblin"].level_adjustment,1)

    def test_npc_forge_respects_racial_scores_and_kind(self):
        profile=NPC_RACES["Goblin"]
        npc=build_character(name="Murk",race="Goblin",character_class="Warrior",
            base=dict.fromkeys(ABILITIES,10),method="Manual",
            custom_hit_die=8,custom_skill_points=2,kind="npc",
            racial_override=profile.ability_adjustments,size_override=profile.size)
        self.assertEqual(npc.kind,"npc")
        self.assertEqual(npc.strength,8)
        self.assertEqual(npc.dexterity,12)
        self.assertEqual(npc.charisma,8)
        self.assertEqual(npc.armor_class,12)
        sheet=build_sheet(character=npc,class_name="Warrior",ranks={},
                          feats=[],equipment=[],alignment="True Neutral",
                          deity="",languages=[],appearance="",personality="",background="")
        self.assertEqual(json.loads(sheet.sheet_json)["class"],"Warrior")
        self.assertEqual(set(RACIAL_ADJUSTMENTS),{"Human","Dwarf","Elf","Gnome","Half-elf","Half-orc","Halfling"})

    def test_player_class_forge_rejects_npc_only_races(self):
        with self.assertRaisesRegex(ValueError,"player race"):
            build_character(name="Murk",race="Goblin",character_class="Fighter",
                            base=dict(NEUTRAL),method="Manual")
        with self.assertRaisesRegex(ValueError,"NPC ancestry modifiers"):
            build_character(name="Murk",race="Goblin",character_class="Warrior",
                base=dict(NEUTRAL),method="Manual",kind="npc",
                custom_hit_die=8,custom_skill_points=2)

if __name__=="__main__":
    unittest.main()
