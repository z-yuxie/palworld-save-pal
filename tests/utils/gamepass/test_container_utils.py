"""聚焦测试 save_modified_gamepass 的 KeyError 修复。

测试场景:
- 缺 UUID: _dps 容器在 original_containers 但 player_sav_data 无该 UUID
- 缺键: Player 容器在 original_containers 但 player_sav_data 缺 "sav" 键
- 正常替换: 有效修改字节覆盖原容器

Game Pass 容器命名使用无连字符的 32 位 hex 作为玩家标识符，
例如 "Players-abc123..." 而非 "Players-abc1-...-xyz"。
"""

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from palworld_save_pal.utils.gamepass.container_types import (
    FILETIME,
    Container,
    ContainerIndex,
)
from palworld_save_pal.utils.gamepass.container_utils import save_modified_gamepass

# ── 测试常量 ──────────────────────────────────────────────

SAVE_ID = "ABCDEF0123456789ABCDEF0123456789"
# Game Pass 使用无连字符的 hex 作为玩家 ID
PLAYER_ID = "12345678123456789abc123456789abc"
OTHER_ID = "aaaaaaaabbbbccccddddeeeeeeeeeeee"
PLAYER_UUID = uuid.UUID(PLAYER_ID)
OTHER_UUID = uuid.UUID(OTHER_ID)
CONTAINER_PATH = "/fake/container/path"
WORLD_NAME = "TestWorld"
LEVEL_BYTES = b"level_data"
SAV_BYTES = b"modified_player_sav"
DPS_BYTES = b"modified_player_dps"


# ── 辅助函数 ──────────────────────────────────────────────


def _make_container(name: str) -> Container:
    """构造最小 Container 对象。"""
    return Container(
        container_name=f"{SAVE_ID}-{name}",
        cloud_id="",
        seq=1,
        flag=5,
        container_uuid=uuid.uuid4(),
        mtime=FILETIME.from_timestamp(datetime.now().timestamp()),
        size=100,
    )


def _make_container_index(num_containers: int = 0) -> ContainerIndex:
    """构造最小 ContainerIndex。"""
    return ContainerIndex(
        flag1=1,
        package_name="test.package",
        mtime=FILETIME.from_timestamp(datetime.now().timestamp()),
        flag2=0,
        index_uuid=str(uuid.uuid4()),
        unknown=0,
        containers=[],
    )


# ── Mock 上下文集 ──────────────────────────────────────────


@pytest.fixture
def mocks():
    """构造通用 mock 集合: 屏蔽所有文件系统操作。"""
    with (
        patch(
            "palworld_save_pal.utils.gamepass.container_utils.create_new_container"
        ) as mk_create,
        patch(
            "palworld_save_pal.utils.gamepass.container_utils.copy_container"
        ) as mk_copy,
        patch.object(ContainerIndex, "write_file") as mk_write,
    ):
        # create_new_container 返回假 Container
        mk_create.return_value = _make_container("Level")
        # copy_container 返回带原始名称的假 Container
        mk_copy.side_effect = (
            lambda src, src_p, dst_p, sid, key, wn, pd: _make_container(key)
        )
        yield {
            "create_new_container": mk_create,
            "copy_container": mk_copy,
            "write_file": mk_write,
        }


# ── 测试用例 ──────────────────────────────────────────────


class TestSaveModifiedGamepass:
    """save_modified_gamepass 的 KeyError 修复测试。"""

    def test_missing_uuid_for_dps_container_preserves_original(self, mocks):
        """_dps 容器存在但 player_sav_data 无该 UUID → 不抛 KeyError，保留原容器。"""
        container_index = _make_container_index()

        dps_container = _make_container(f"Players-{PLAYER_ID}_dps")
        original_containers = {
            f"Players-{PLAYER_ID}_dps": dps_container,
        }

        # player_sav_data 不含该 UUID
        player_sav_data = {}

        # 不应抛异常
        save_modified_gamepass(
            container_index=container_index,
            container_path=CONTAINER_PATH,
            save_id=SAVE_ID,
            modified_level_data=LEVEL_BYTES,
            player_sav_data=player_sav_data,
            original_containers=original_containers,
            world_name=WORLD_NAME,
        )

        mk_copy = mocks["copy_container"]
        assert mk_copy.call_count == 1
        # copy_container(source, src_path, dst_path, save_id, key, world_name, player_data)
        assert mk_copy.call_args.args[6] is None

    def test_missing_dps_key_in_player_sav_data_preserves_original(self, mocks):
        """_dps 容器存在，UUID 在 player_sav_data 但 "dps" 键不存在 → 保留原容器。"""
        container_index = _make_container_index()

        dps_container = _make_container(f"Players-{PLAYER_ID}_dps")
        original_containers = {
            f"Players-{PLAYER_ID}_dps": dps_container,
        }

        # player_sav_data 含 UUID 但缺 "dps" 键
        player_sav_data = {PLAYER_UUID: {"sav": SAV_BYTES}}

        save_modified_gamepass(
            container_index=container_index,
            container_path=CONTAINER_PATH,
            save_id=SAVE_ID,
            modified_level_data=LEVEL_BYTES,
            player_sav_data=player_sav_data,
            original_containers=original_containers,
            world_name=WORLD_NAME,
        )

        mk_copy = mocks["copy_container"]
        assert mk_copy.call_count == 1
        assert mk_copy.call_args.args[6] is None

    def test_missing_sav_key_for_player_container_preserves_original(self, mocks):
        """Player 容器存在，UUID 在 player_sav_data 但缺 "sav" 键 → 保留原容器。"""
        container_index = _make_container_index()

        player_container = _make_container(f"Players-{PLAYER_ID}")
        original_containers = {
            f"Players-{PLAYER_ID}": player_container,
        }

        # player_sav_data 含 UUID 但缺 "sav" 键
        player_sav_data = {PLAYER_UUID: {"dps": DPS_BYTES}}

        save_modified_gamepass(
            container_index=container_index,
            container_path=CONTAINER_PATH,
            save_id=SAVE_ID,
            modified_level_data=LEVEL_BYTES,
            player_sav_data=player_sav_data,
            original_containers=original_containers,
            world_name=WORLD_NAME,
        )

        mk_copy = mocks["copy_container"]
        assert mk_copy.call_count == 1
        assert mk_copy.call_args.args[6] is None

    def test_normal_replacement_with_valid_data(self, mocks):
        """有效修改字节存在 → copy_container 收到正确的 player_data。"""
        container_index = _make_container_index()

        sav_container = _make_container(f"Players-{PLAYER_ID}")
        dps_container = _make_container(f"Players-{PLAYER_ID}_dps")
        original_containers = {
            f"Players-{PLAYER_ID}": sav_container,
            f"Players-{PLAYER_ID}_dps": dps_container,
        }

        player_sav_data = {
            PLAYER_UUID: {"sav": SAV_BYTES, "dps": DPS_BYTES},
        }

        save_modified_gamepass(
            container_index=container_index,
            container_path=CONTAINER_PATH,
            save_id=SAVE_ID,
            modified_level_data=LEVEL_BYTES,
            player_sav_data=player_sav_data,
            original_containers=original_containers,
            world_name=WORLD_NAME,
        )

        mk_copy = mocks["copy_container"]
        assert mk_copy.call_count == 2

        calls = {(c.args[4], c.args[6]) for c in mk_copy.call_args_list}
        assert (f"Players-{PLAYER_ID}", SAV_BYTES) in calls
        assert (f"Players-{PLAYER_ID}_dps", DPS_BYTES) in calls

    def test_multiple_players_mixed_data(self, mocks):
        """多玩家混合：一个有有效数据，另一个缺 _dps → 各自正确处理。"""
        container_index = _make_container_index()

        p1_container = _make_container(f"Players-{PLAYER_ID}")
        p1_dps = _make_container(f"Players-{PLAYER_ID}_dps")
        p2_container = _make_container(f"Players-{OTHER_ID}")
        p2_dps = _make_container(f"Players-{OTHER_ID}_dps")

        original_containers = {
            f"Players-{PLAYER_ID}": p1_container,
            f"Players-{PLAYER_ID}_dps": p1_dps,
            f"Players-{OTHER_ID}": p2_container,
            f"Players-{OTHER_ID}_dps": p2_dps,
        }

        # p1 有完整数据，p2 仅 "sav" 无 "dps"
        player_sav_data = {
            PLAYER_UUID: {"sav": SAV_BYTES, "dps": DPS_BYTES},
            OTHER_UUID: {"sav": b"p2_sav_data"},
        }

        save_modified_gamepass(
            container_index=container_index,
            container_path=CONTAINER_PATH,
            save_id=SAVE_ID,
            modified_level_data=LEVEL_BYTES,
            player_sav_data=player_sav_data,
            original_containers=original_containers,
            world_name=WORLD_NAME,
        )

        mk_copy = mocks["copy_container"]
        assert mk_copy.call_count == 4

        calls = {(c.args[4], c.args[6]) for c in mk_copy.call_args_list}
        assert (f"Players-{PLAYER_ID}", SAV_BYTES) in calls
        assert (f"Players-{PLAYER_ID}_dps", DPS_BYTES) in calls
        assert (f"Players-{OTHER_ID}", b"p2_sav_data") in calls
        # p2 的 _dps 应保留原容器 (player_data=None)
        assert (f"Players-{OTHER_ID}_dps", None) in calls
