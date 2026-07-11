"""Tests for DynamicItem model."""

from uuid import UUID, uuid4

import pytest

from palworld_save_pal.dto.dynamic_item import DynamicItemDTO
from palworld_save_pal.dto.item_container_slot import ItemContainerSlotDTO
from palworld_save_pal.game.dynamic_item import DynamicItem, DynamicItemType
from palworld_save_pal.game.pal_objects import PalObjects

TEST_LOCAL_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _make_raw_data(
    item_type="weapon",
    static_id="AssaultRifle_Default1",
    durability=1000.0,
    remaining_bullets=30,
    passive_skill_list=None,
    character_id=None,
    obj=None,
):
    raw = {
        "type": item_type,
        "id": {"static_id": static_id},
        "durability": durability,
    }
    if remaining_bullets is not None:
        raw["remaining_bullets"] = remaining_bullets
    if passive_skill_list is not None:
        raw["passive_skill_list"] = passive_skill_list
    if character_id is not None:
        raw["character_id"] = character_id
    if obj is not None:
        raw["object"] = obj
    return raw


def _make_dynamic_item_save_data(**kwargs):
    return {"RawData": {"value": _make_raw_data(**kwargs)}}


class TestDynamicItemConstruction:
    def test_create_with_local_id(self):
        item = DynamicItem(local_id=TEST_LOCAL_ID)
        assert item.local_id == TEST_LOCAL_ID

    def test_create_with_save_data(self):
        save_data = _make_dynamic_item_save_data()
        item = DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)
        assert item.local_id == TEST_LOCAL_ID

    def test_save_data_property(self):
        save_data = _make_dynamic_item_save_data()
        item = DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)
        assert item.save_data is save_data


class TestDynamicItemWeaponProperties:
    @pytest.fixture
    def weapon(self):
        save_data = _make_dynamic_item_save_data(
            item_type="weapon",
            static_id="AssaultRifle_Default1",
            durability=850.5,
            remaining_bullets=25,
            passive_skill_list=["Skill_A", "Skill_B"],
        )
        return DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)

    def test_type(self, weapon):
        assert weapon.type == "weapon"

    def test_static_id(self, weapon):
        assert weapon.static_id == "AssaultRifle_Default1"

    def test_durability(self, weapon):
        assert weapon.durability == 850.5

    def test_remaining_bullets(self, weapon):
        assert weapon.remaining_bullets == 25

    def test_passive_skill_list(self, weapon):
        assert weapon.passive_skill_list == ["Skill_A", "Skill_B"]

    def test_character_id_none_for_weapon(self, weapon):
        assert weapon.character_id is None

    def test_character_key_none_for_weapon(self, weapon):
        assert weapon.character_key is None


class TestDynamicItemArmorProperties:
    @pytest.fixture
    def armor(self):
        save_data = _make_dynamic_item_save_data(
            item_type="armor",
            static_id="HeadEquip001",
            durability=500.0,
            remaining_bullets=None,
        )
        return DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)

    def test_type(self, armor):
        assert armor.type == "armor"

    def test_static_id(self, armor):
        assert armor.static_id == "HeadEquip001"

    def test_durability(self, armor):
        assert armor.durability == 500.0

    def test_remaining_bullets_none(self, armor):
        assert armor.remaining_bullets is None


class TestDynamicItemEggProperties:
    @pytest.fixture
    def egg(self):
        save_data = _make_dynamic_item_save_data(
            item_type="egg",
            static_id="PalEgg_Dark_01",
            durability=None,
            remaining_bullets=None,
            character_id="Lamball",
        )
        # Remove durability key entirely for egg
        del save_data["RawData"]["value"]["durability"]
        return DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)

    def test_type(self, egg):
        assert egg.type == "egg"

    def test_character_id(self, egg):
        assert egg.character_id == "Lamball"

    def test_character_key(self, egg):
        assert egg.character_key is not None

    def test_durability_none(self, egg):
        assert egg.durability is None


class TestDynamicItemSetters:
    @pytest.fixture
    def weapon(self):
        save_data = _make_dynamic_item_save_data(
            item_type="weapon",
            durability=100.0,
            remaining_bullets=10,
            passive_skill_list=[],
        )
        return DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)

    def test_set_type(self, weapon):
        weapon.type = "armor"
        assert weapon.type == "armor"

    def test_set_static_id(self, weapon):
        weapon.static_id = "NewWeapon_01"
        assert weapon.static_id == "NewWeapon_01"

    def test_set_durability(self, weapon):
        weapon.durability = 999.0
        assert weapon.durability == 999.0

    def test_set_remaining_bullets(self, weapon):
        weapon.remaining_bullets = 50
        assert weapon.remaining_bullets == 50

    def test_set_passive_skill_list(self, weapon):
        weapon.passive_skill_list = ["SkillX"]
        assert weapon.passive_skill_list == ["SkillX"]

    def test_set_durability_on_egg_removes_it(self):
        save_data = _make_dynamic_item_save_data(
            item_type="egg", character_id="Lamball"
        )
        item = DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)
        item.durability = 100.0
        assert item.durability is None

    def test_set_remaining_bullets_on_armor_removes_it(self):
        save_data = _make_dynamic_item_save_data(
            item_type="armor", remaining_bullets=10
        )
        item = DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)
        item.remaining_bullets = 5
        assert item.remaining_bullets is None

    def test_set_character_id_on_weapon_removes_it(self):
        save_data = _make_dynamic_item_save_data(
            item_type="weapon", character_id="SomeChar"
        )
        item = DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)
        item.character_id = "AnotherChar"
        assert item.character_id is None


class TestDynamicItemNoSaveParameter:
    """Test computed fields that depend on _save_parameter when it's absent."""

    @pytest.fixture
    def item(self):
        save_data = _make_dynamic_item_save_data(item_type="weapon")
        return DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)

    def test_gender_none(self, item):
        assert item.gender is None

    def test_active_skills_none(self, item):
        assert item.active_skills is None

    def test_learned_skills_none(self, item):
        assert item.learned_skills is None

    def test_passive_skills_none(self, item):
        assert item.passive_skills is None

    def test_talent_hp_none(self, item):
        assert item.talent_hp is None

    def test_talent_shot_none(self, item):
        assert item.talent_shot is None

    def test_talent_defense_none(self, item):
        assert item.talent_defense is None


class TestDynamicItemTypeEnum:
    def test_armor_value(self):
        assert DynamicItemType.ARMOR.value == "armor"

    def test_egg_value(self):
        assert DynamicItemType.EGG.value == "egg"

    def test_weapon_value(self):
        assert DynamicItemType.WEAPON.value == "weapon"

    def test_all_types(self):
        assert len(DynamicItemType) == 3


class TestDynamicItemNoData:
    def test_properties_default_none_without_save_data(self):
        item = DynamicItem(local_id=TEST_LOCAL_ID)
        assert item.type is None
        assert item.static_id is None
        assert item.durability is None
        assert item.remaining_bullets is None
        assert item.passive_skill_list is None
        assert item.character_id is None



class TestDynamicItemUpdateFromLeadingBytes:
    """Issue #278: update_from 未能为类型变更后的 DynamicItem 补齐 leading_bytes/trailing_bytes，
    导致 palworld-save-tools 的 encode_bytes 引发 KeyError。"""

    def test_update_unknown_to_weapon_adds_leading_bytes(self):
        """未知类型 -> 武器时应自动添加 leading_bytes=[0]*4 和 trailing_bytes=[0]*4。"""
        raw_data = {
            "type": "unknown",
            "id": {
                "created_world_id": PalObjects.EMPTY_UUID,
                "local_id_in_created_world": uuid4(),
                "static_id": "TestWeapon",
            },
            "trailer": [1, 2, 3],
        }
        save_data = {"RawData": {"value": raw_data}}
        item = DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)
        item.update_from({
            "type": "weapon",
            "durability": 50.0,
            "remaining_bullets": 10,
            "passive_skill_list": [],
        })
        assert item._raw_data["leading_bytes"] == [0, 0, 0, 0]
        assert item._raw_data["trailing_bytes"] == [0, 0, 0, 0]
        # encode_bytes 不应抛出 KeyError
        from palworld_save_tools.rawdata.dynamic_item import encode_bytes
        assert len(encode_bytes(item._raw_data)) > 0

    def test_update_unknown_to_egg_adds_leading_bytes(self):
        """未知类型 -> 蛋时应自动添加 leading_bytes=[0]*4 和 trailing_bytes=[0]*28。"""
        raw_data = {
            "type": "unknown",
            "id": {
                "created_world_id": PalObjects.EMPTY_UUID,
                "local_id_in_created_world": uuid4(),
                "static_id": "TestEgg",
            },
            "trailer": [1, 2, 3],
        }
        save_data = {"RawData": {"value": raw_data}}
        item = DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)
        item.update_from({
            "type": "egg",
            "character_id": "SomeChar",
            "modified": False,
        })
        assert item._raw_data["leading_bytes"] == [0, 0, 0, 0]
        # egg 类型的 trailing_bytes 长度为 28，与 decode_bytes 契约一致
        assert item._raw_data["trailing_bytes"] == [0] * 28
        from palworld_save_tools.rawdata.dynamic_item import encode_bytes
        assert len(encode_bytes(item._raw_data)) > 0

    def test_egg_to_egg_preserves_nonzero_trailing(self):
        """同类型 egg→egg 应保留原始 trailing_bytes 中的非零数据（保真）。"""
        non_zero_trailing = [0xFF] * 28
        raw_data = {
            "type": "egg",
            "id": {
                "created_world_id": PalObjects.EMPTY_UUID,
                "local_id_in_created_world": uuid4(),
                "static_id": "TestEgg",
            },
            "leading_bytes": [0, 0, 0, 0],
            "trailing_bytes": non_zero_trailing,
            "object": {},
            "unknown_bytes": [0, 0, 0, 0],
            "unknown_id": PalObjects.EMPTY_UUID,
            "character_id": "OldChar",
        }
        save_data = {"RawData": {"value": raw_data}}
        item = DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)
        item.update_from({
            "type": "egg",
            "character_id": "NewChar",
            "modified": False,
        })
        # 长度正确(28)的非零数据应原样保留
        assert item._raw_data["trailing_bytes"] == non_zero_trailing
        assert len(item._raw_data["trailing_bytes"]) == 28
        from palworld_save_tools.rawdata.dynamic_item import encode_bytes
        assert len(encode_bytes(item._raw_data)) > 0

    def test_egg_to_weapon_trailing_28_to_4(self):
        """egg→weapon 转换：trailing_bytes 应从 28 字节收缩为 4 字节。"""
        raw_data = {
            "type": "egg",
            "id": {
                "created_world_id": PalObjects.EMPTY_UUID,
                "local_id_in_created_world": uuid4(),
                "static_id": "TestEgg",
            },
            "leading_bytes": [0, 0, 0, 0],
            "trailing_bytes": [0xFF] * 28,
            "object": {},
            "unknown_bytes": [0, 0, 0, 0],
            "unknown_id": PalObjects.EMPTY_UUID,
            "character_id": "Char1",
        }
        save_data = {"RawData": {"value": raw_data}}
        item = DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)
        item.update_from({
            "type": "weapon",
            "durability": 60.0,
            "remaining_bullets": 20,
            "passive_skill_list": [],
        })
        assert item._raw_data["trailing_bytes"] == [0, 0, 0, 0]
        assert len(item._raw_data["trailing_bytes"]) == 4
        from palworld_save_tools.rawdata.dynamic_item import encode_bytes
        assert len(encode_bytes(item._raw_data)) > 0

    def test_armor_to_egg_trailing_4_to_28(self):
        """armor→egg 转换：trailing_bytes 应从 4 字节扩展为 28 字节。"""
        raw_data = {
            "type": "armor",
            "id": {
                "created_world_id": PalObjects.EMPTY_UUID,
                "local_id_in_created_world": uuid4(),
                "static_id": "TestArmor",
            },
            "durability": 50.0,
            "leading_bytes": [0, 0, 0, 0],
            "trailing_bytes": [0, 0, 0, 0],
        }
        save_data = {"RawData": {"value": raw_data}}
        item = DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)
        item.update_from({
            "type": "egg",
            "character_id": "Char2",
            "modified": False,
        })
        assert len(item._raw_data["trailing_bytes"]) == 28
        assert item._raw_data["trailing_bytes"] == [0] * 28
        from palworld_save_tools.rawdata.dynamic_item import encode_bytes
        assert len(encode_bytes(item._raw_data)) > 0

    def test_update_none_type_to_armor_adds_leading_bytes(self):
        """空类型 -> 护甲时应自动添加 leading_bytes=[0]*4 和 trailing_bytes=[0]*4。"""
        raw_data = {
            "type": None,
            "id": {
                "created_world_id": PalObjects.EMPTY_UUID,
                "local_id_in_created_world": uuid4(),
                "static_id": "TestArmor",
            },
        }
        save_data = {"RawData": {"value": raw_data}}
        item = DynamicItem(local_id=TEST_LOCAL_ID, dynamic_item_save_data=save_data)
        item.update_from({
            "type": "armor",
            "durability": 75.0,
        })
        assert item._raw_data["leading_bytes"] == [0, 0, 0, 0]
        assert item._raw_data["trailing_bytes"] == [0, 0, 0, 0]
        from palworld_save_tools.rawdata.dynamic_item import encode_bytes
        assert len(encode_bytes(item._raw_data)) > 0

    def test_new_dynamic_item_all_types_have_leading_bytes(self):
        """PalObjects.DynamicItem 为所有已知类型生成的 RawData 都必须含 leading_bytes。"""
        for item_type, static_id in [
            ("weapon", "W_Test"),
            ("armor", "A_Test"),
            ("egg", "E_Test"),
        ]:
            dto = DynamicItemDTO(
                local_id=uuid4(),
                type=item_type,
                durability=100.0 if item_type != "egg" else None,
                remaining_bullets=30 if item_type == "weapon" else None,
                passive_skill_list=[] if item_type == "weapon" else None,
                character_id="Char1" if item_type == "egg" else None,
            )
            slot_dto = ItemContainerSlotDTO(slot_index=0, count=1, static_id=static_id, dynamic_item=dto)
            result = PalObjects.DynamicItem(slot_dto)
            value = result["RawData"]["value"]
            assert "leading_bytes" in value, f"missing leading_bytes for {item_type}"
            assert "trailing_bytes" in value, f"missing trailing_bytes for {item_type}"
