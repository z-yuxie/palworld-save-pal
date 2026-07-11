"""Integration tests for Player entity using real save data."""

import asyncio
from uuid import UUID

import pytest

from palworld_save_pal.game.pal_objects import PalObjects
from palworld_save_pal.game.player import Player, PlayerGvasFiles
from tests.game.conftest import PLAYER_O_UID, PLAYER_SKY_UID, _noop


@pytest.fixture
def player_o(event_loop, fresh_save_manager):
    return event_loop.run_until_complete(
        fresh_save_manager.load_player_on_demand(PLAYER_O_UID, ws_callback=_noop)
    )


@pytest.fixture
def player_sky(event_loop, fresh_save_manager):
    return event_loop.run_until_complete(
        fresh_save_manager.load_player_on_demand(PLAYER_SKY_UID, ws_callback=_noop)
    )


class TestPlayerProperties:
    def test_nickname(self, player_o):
        assert player_o.nickname == "O"

    def test_level(self, player_o):
        assert player_o.level == 65

    def test_uid(self, player_o):
        assert player_o.uid == PLAYER_O_UID

    def test_pal_box_id(self, player_o):
        assert player_o.pal_box_id is not None
        assert isinstance(player_o.pal_box_id, UUID)

    def test_otomo_container_id(self, player_o):
        assert player_o.otomo_container_id is not None

    def test_instance_id(self, player_o):
        assert player_o.instance_id is not None

    def test_guild_id(self, player_o):
        assert player_o.guild_id is not None


class TestPlayerSky:
    def test_nickname(self, player_sky):
        assert player_sky.nickname == "sky"

    def test_level(self, player_sky):
        assert player_sky.level == 2


class TestPlayerWithoutRecordData:
    """Some player saves have no RecordData property; loading must not crash."""

    def test_loads_without_record_data(self, player_o):
        save_data = PalObjects.get_value(
            player_o._player_gvas_files.sav.properties["SaveData"]
        )
        save_data.pop("RecordData", None)

        gvas_files = PlayerGvasFiles(sav=player_o._player_gvas_files.sav, dps=None)
        player = Player(
            gvas_files=gvas_files,
            character_save_parameter=player_o._character_save,
        )

        assert player._record_data == {}

    def test_setters_persist_without_record_data(self, player_o):
        save_data = PalObjects.get_value(
            player_o._player_gvas_files.sav.properties["SaveData"]
        )
        save_data.pop("RecordData", None)

        gvas_files = PlayerGvasFiles(sav=player_o._player_gvas_files.sav, dps=None)
        player = Player(
            gvas_files=gvas_files,
            character_save_parameter=player_o._character_save,
        )

        player.collected_effigies = ["TestFlag"]

        # The created RecordData must be wired into SaveData so writes persist.
        assert "RecordData" in save_data
        assert player.collected_effigies == ["TestFlag"]


class TestPlayerContainers:
    def test_has_common_container(self, player_o):
        assert player_o.common_container is not None

    def test_has_essential_container(self, player_o):
        assert player_o.essential_container is not None


class TestMovementSpeedStatus:
    """Issue #279/#272: 移動速度アップ 在 Player.status_point_list 中引发 KeyError。"""

    def test_movement_speed_in_status_point_list(self, player_o):
        """读取包含 移動速度アップ 的状态点列表不应抛出 KeyError。"""
        save_param = player_o._save_parameter
        status_list = PalObjects.get_array_property(
            save_param["GotStatusPointList"]
        )
        # 注入玩家特有的 移動速度アップ 条目（模拟力量石像升级后的存档）
        status_list.append(
            PalObjects.StatusPointStruct("移動速度アップ", 500)
        )

        # 修复前此处抛出 KeyError('移動速度アップ')
        result = player_o.status_point_list
        assert "move_speed" in result
        assert result["move_speed"] == 500

    def test_movement_speed_round_trips(self, player_o):
        """setter 应保留/回写 移動速度アップ 字段。"""
        save_param = player_o._save_parameter
        status_list = PalObjects.get_array_property(
            save_param["GotStatusPointList"]
        )
        status_list.append(
            PalObjects.StatusPointStruct("移動速度アップ", 500)
        )

        # 读取 → 修改 → 回写
        points = player_o.status_point_list
        points["move_speed"] = 999
        player_o.status_point_list = points

        # 验证回写后值仍可读取
        result = player_o.status_point_list
        assert result["move_speed"] == 999



class TestUnknownStatusNames:
    """Palworld 1.0 引入新状态名(如 空腹率低減)，getter/setter 应容错未知键不崩溃。"""

    def test_unknown_status_name_does_not_crash_getter(self, player_o):
        """注入合成未知状态名 未知のステータス，getter 不崩溃且已知键仍可读。"""
        save_param = player_o._save_parameter
        status_list = PalObjects.get_array_property(
            save_param["GotStatusPointList"]
        )
        status_list.append(
            PalObjects.StatusPointStruct("未知のステータス", 999)
        )

        result = player_o.status_point_list
        assert "未知のステータス" not in result
        # 已知键仍可正常读取
        assert "max_hp" in result

    def test_hunger_rate_reduction_mapped(self, player_o):
        """注入 空腹率低減 值 300，验证 getter 正确映射为 hunger_rate_reduction。"""
        save_param = player_o._save_parameter
        status_list = PalObjects.get_array_property(
            save_param["GotStatusPointList"]
        )
        status_list.append(
            PalObjects.StatusPointStruct("空腹率低減", 300)
        )

        result = player_o.status_point_list
        assert "hunger_rate_reduction" in result
        assert result["hunger_rate_reduction"] == 300

    def test_unknown_status_preserved_in_setter_roundtrip(self, player_o):
        """setter 设已知键值不应影响未知条目的存在。"""
        save_param = player_o._save_parameter
        status_list = PalObjects.get_array_property(
            save_param["GotStatusPointList"]
        )
        status_list.append(
            PalObjects.StatusPointStruct("未知のステータス", 777)
        )

        # 读取后只修改已知键，回写
        points = player_o.status_point_list
        assert "未知のステータス" not in points  # 未知键不会进入 dict
        points["max_hp"] = 9999
        player_o.status_point_list = points

        # 回写后已知键值正确
        result = player_o.status_point_list
        assert result["max_hp"] == 9999
        # 未知条目仍在 status_point_list 原始数组中
        raw_list = PalObjects.get_array_property(
            save_param["GotStatusPointList"]
        )
        unknown_items = [
            item for item in raw_list
            if PalObjects.get_value(item.get("StatusName", "")) == "未知のステータス"
        ]
        assert len(unknown_items) == 1
        assert PalObjects.get_value(unknown_items[0]["StatusPoint"]) == 777


class TestStatusCleanup:
    """Issue #9c7835fa: setter 遍历时修改列表导致连续无效条目漏删。"""

    def test_consecutive_invalid_entries_all_removed(self, player_o):
        """注入连续两个 StatusName=None 条目后调用 setter，两者均应被移除。"""
        save_param = player_o._save_parameter
        status_list = PalObjects.get_array_property(
            save_param["GotStatusPointList"]
        )

        # 注入两个连续的 StatusName="None" 条目（应被清除）
        none_entry_1 = {
            "StatusName": PalObjects.NameProperty("None"),
            "StatusPoint": PalObjects.IntProperty(1),
        }
        none_entry_2 = {
            "StatusName": PalObjects.NameProperty("None"),
            "StatusPoint": PalObjects.IntProperty(2),
        }
        status_list.append(none_entry_1)
        status_list.append(none_entry_2)

        # 注入一个未知但非None的状态条目（应保留）
        unknown = PalObjects.StatusPointStruct("未知のステータス", 777)
        status_list.append(unknown)

        # 通过 setter 触发清理
        points = player_o.status_point_list
        points["max_hp"] = 9999
        player_o.status_point_list = points

        # 验证两个 invalid 条目都被移除
        raw_list = PalObjects.get_array_property(
            save_param["GotStatusPointList"]
        )
        none_items = [
            item for item in raw_list
            if PalObjects.get_value(item.get("StatusName", {})) == "None"
        ]
        assert len(none_items) == 0, f"应移除全部 None 条目，剩余 {len(none_items)} 个"

        # 验证未知条目仍在
        unknown_items = [
            item for item in raw_list
            if PalObjects.get_value(item.get("StatusName", {})) == "未知のステータス"
        ]
        assert len(unknown_items) == 1
        assert PalObjects.get_value(unknown_items[0]["StatusPoint"]) == 777

        # 验证已知键值正确
        result = player_o.status_point_list
        assert result["max_hp"] == 9999