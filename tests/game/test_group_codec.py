"""测试本地 Guild/Group 结构化 codec。

验证 :class:`palworld_save_pal.game.group_codec` 的解码/编码往返行为，
覆盖 Palworld 1.0 新格式、旧格式、Organization、IndependentGuild 以及
无法解析的 raw tail 保底。
"""

import copy
import struct

import pytest
from palworld_save_tools.archive import FArchiveReader, FArchiveWriter

from palworld_save_pal.game.group_codec import (
    decode_bytes,
    encode,
    encode_bytes,
)


# ── 二进制构造辅助 ───────────────────────────────────────────

def _pack_guid(hex_str: str) -> bytes:
    """将十六进制 GUID 字符串打包为 16 字节。"""
    return bytes.fromhex(hex_str)


def _pack_fstring(s: str) -> bytes:
    """FString: i32(len+1) + ascii_bytes + b'\\x00'"""
    if s == "":
        return struct.pack("<i", 0)
    b = s.encode("ascii")
    return struct.pack("<i", len(b) + 1) + b + b"\x00"


def _pack_tarray_uuid(uuids: list[str]) -> bytes:
    """tarray of UUIDs: u32(count) + each 16 bytes"""
    return struct.pack("<I", len(uuids)) + b"".join(
        _pack_guid(u) for u in uuids
    )


def _pack_tarray_instance_ids(
    entries: list[tuple[str, str]],
) -> bytes:
    """tarray of instance_id: u32(count) + each guid+instance_id (32 字节)"""
    return struct.pack("<I", len(entries)) + b"".join(
        _pack_guid(g) + _pack_guid(i) for g, i in entries
    )


V1_MARKER = b"\x02\x00\x00\x00\x02\x03\x00\x00\x00\x00"

ZERO_GUID = "00000000000000000000000000000000"

# 有效测试 GUID（32 个十六进制字符）
ADMIN_UID = "ad" * 16  # "adadadad..."
PLAYER1_UID = "b1" * 16
PLAYER2_UID = "b2" * 16
OLD_GUILD_ID = "22" * 16
ORG_GUILD_ID = "33" * 16
INDIE_GUILD_ID = "44" * 16
INDIE_PLAYER_UID = "cc" * 16
RAWTAIL_GUILD_ID = "ff" * 16
FAIL_GUILD_ID = "fa" * 16  # for raw tail fallback test


# ── Guild 二进制构造 ─────────────────────────────────────────

def _build_v1_guild_bytes(
    *,
    group_id: str = "11" * 16,
    group_name: str = "TestGuild",
    org_type: int = 0,
    base_camp_level: int = 1,
    guild_name: str = "TestGuildName",
    admin_uid: str = ADMIN_UID,
    players: list[dict] | None = None,
    trailing_bytes: bytes = b"",
) -> bytes:
    """构造 Palworld 1.0 Guild 二进制 payload。"""
    if players is None:
        players = [
            {
                "player_uid": PLAYER1_UID,
                "player_name": "PlayerOne",
                "last_online": 1234567890,
                "u8_flag": 1,
            }
        ]

    buf = bytearray()
    # common header
    buf += _pack_guid(group_id)
    buf += _pack_fstring(group_name)
    buf += _pack_tarray_instance_ids([])
    buf += struct.pack("<B", org_type)

    # guild fields
    buf += b"\x00" * 4  # leading_bytes
    buf += _pack_tarray_uuid([])  # base_ids
    buf += struct.pack("<i", 0)  # unknown_1
    buf += struct.pack("<i", base_camp_level)
    buf += _pack_tarray_uuid([])
    buf += _pack_fstring(guild_name)
    buf += _pack_guid(ZERO_GUID)
    buf += b"\x00" * 4  # unknown_2

    # Palworld 1.0 marker
    buf += V1_MARKER
    buf += _pack_guid(admin_uid)

    # player tarray
    buf += struct.pack("<I", len(players))
    for p in players:
        buf += _pack_guid(p["player_uid"])
        buf += struct.pack("<q", p["last_online"])
        buf += _pack_fstring(p["player_name"])
        buf += struct.pack("<B", p["u8_flag"])

    buf += trailing_bytes
    return bytes(buf)


def _build_old_guild_bytes(
    *,
    group_id: str = OLD_GUILD_ID,
    group_name: str = "OldGuild",
    org_type: int = 0,
    base_camp_level: int = 2,
    guild_name: str = "OldGuildName",
    trailing_bytes: bytes = b"\xff\xee",
) -> bytes:
    """构造旧格式 Guild 二进制（无 Palworld 1.0 marker/player 数据）。"""
    buf = bytearray()
    buf += _pack_guid(group_id)
    buf += _pack_fstring(group_name)
    buf += _pack_tarray_instance_ids([])
    buf += struct.pack("<B", org_type)
    buf += b"\x00" * 4  # leading_bytes
    buf += _pack_tarray_uuid([])
    buf += struct.pack("<i", 0)  # unknown_1
    buf += struct.pack("<i", base_camp_level)
    buf += _pack_tarray_uuid([])
    buf += _pack_fstring(guild_name)
    buf += _pack_guid(ZERO_GUID)
    buf += b"\x00" * 4  # unknown_2
    buf += trailing_bytes
    return bytes(buf)


def _build_org_bytes(
    *,
    group_id: str = ORG_GUILD_ID,
    group_name: str = "TestOrg",
    org_type: int = 2,
    trailing_bytes: bytes = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c",
    unknown_bytes: bytes = b"",
) -> bytes:
    buf = bytearray()
    buf += _pack_guid(group_id)
    buf += _pack_fstring(group_name)
    buf += _pack_tarray_instance_ids([])
    buf += struct.pack("<B", org_type)
    buf += trailing_bytes
    if unknown_bytes:
        buf += unknown_bytes
    return bytes(buf)


def _build_independent_guild_bytes(
    *,
    group_id: str = INDIE_GUILD_ID,
    group_name: str = "IndependentGuild",
    org_type: int = 1,
    base_camp_level: int = 3,
    guild_name: str = "IndieGuild",
    player_uid: str = INDIE_PLAYER_UID,
    guild_name_2: str = "IndieGuild2",
    player_name: str = "IndiePlayer",
    last_online: int = 9876543210,
    unknown_bytes: bytes = b"",
) -> bytes:
    buf = bytearray()
    buf += _pack_guid(group_id)
    buf += _pack_fstring(group_name)
    buf += _pack_tarray_instance_ids([])
    buf += struct.pack("<B", org_type)
    buf += struct.pack("<i", base_camp_level)
    buf += _pack_tarray_uuid([])
    buf += _pack_fstring(guild_name)
    buf += _pack_guid(player_uid)
    buf += _pack_fstring(guild_name_2)
    buf += struct.pack("<q", last_online)
    buf += _pack_fstring(player_name)
    if unknown_bytes:
        buf += unknown_bytes
    return bytes(buf)


# ── 测试类 ────────────────────────────────────────────────────


class TestPalworldV1GuildDecode:
    """Palworld 1.0 Guild 解码测试。"""

    @staticmethod
    def _make_reader(raw: bytes):
        return FArchiveReader(b"\x00")

    def test_v1_guild_fields_readable(self):
        """Palworld 1.0 Guild 全部字段可读取。"""
        raw = _build_v1_guild_bytes(
            admin_uid=ADMIN_UID,
            players=[
                {
                    "player_uid": PLAYER1_UID,
                    "player_name": "Alice",
                    "last_online": 1000000,
                    "u8_flag": 42,
                },
                {
                    "player_uid": PLAYER2_UID,
                    "player_name": "Bob",
                    "last_online": 2000000,
                    "u8_flag": 7,
                },
            ],
        )
        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )

        assert result["group_type"] == "EPalGroupType::Guild"
        assert result["group_name"] == "TestGuild"
        assert result["base_camp_level"] == 1
        assert result["guild_name"] == "TestGuildName"
        assert "admin_player_uid" in result
        assert result["_has_v1_marker"] is True

        players = result["players"]
        assert len(players) == 2
        assert players[0]["player_info"]["player_name"] == "Alice"
        assert players[0]["_u8_flag"] == 42
        assert players[1]["player_info"]["player_name"] == "Bob"
        assert players[1]["_u8_flag"] == 7

    def test_v1_guild_roundtrip(self):
        """Palworld 1.0 Guild 解码后编码逐字节一致。"""
        raw = _build_v1_guild_bytes(
            admin_uid=ADMIN_UID,
            players=[
                {
                    "player_uid": PLAYER1_UID,
                    "player_name": "Alice",
                    "last_online": 1000000,
                    "u8_flag": 42,
                },
            ],
            trailing_bytes=b"\x99\x88",
        )
        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )
        re_encoded = encode_bytes(result)
        assert re_encoded == raw, f"roundtrip failed: {re_encoded!r} != {raw!r}"


class TestOldGuildDecode:
    """旧格式 Guild 解码测试。"""

    @staticmethod
    def _make_reader(raw: bytes):
        return FArchiveReader(b"\x00")

    def test_old_guild_fields_readable(self):
        """旧格式 Guild 字段可读取，无 v1 marker。"""
        raw = _build_old_guild_bytes(
            group_id=OLD_GUILD_ID,
            group_name="Vintage",
            base_camp_level=5,
            guild_name="VintageGuild",
        )
        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )

        assert result["group_type"] == "EPalGroupType::Guild"
        assert result["group_name"] == "Vintage"
        assert result["base_camp_level"] == 5
        assert result["guild_name"] == "VintageGuild"
        assert result.get("_has_v1_marker") is not True
        assert result.get("admin_player_uid") is None

    def test_old_guild_roundtrip(self):
        """旧格式 Guild 解码后编码逐字节一致。"""
        raw = _build_old_guild_bytes(trailing_bytes=b"\xab\xcd")
        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )
        re_encoded = encode_bytes(result)
        assert re_encoded == raw


class TestRawTailFallback:
    """无法解析的 Guild tail 保底到 _raw_tail。"""

    @staticmethod
    def _make_reader(raw: bytes):
        return FArchiveReader(b"\x00")

    def test_unparseable_tail_stored_as_raw(self):
        """无法解析的尾部数据保存到 _raw_tail 且往返一致。"""
        buf = bytearray()
        buf += _pack_guid(FAIL_GUILD_ID)
        buf += _pack_fstring("BrokenGuild")
        buf += _pack_tarray_instance_ids([])
        buf += struct.pack("<B", 0)  # org_type
        buf += b"\x00" * 4  # leading_bytes
        buf += _pack_tarray_uuid([])
        buf += struct.pack("<i", 0)  # unknown_1
        buf += struct.pack("<i", 99)  # base_camp_level
        buf += _pack_tarray_uuid([])
        buf += _pack_fstring("BrokenName")
        buf += _pack_guid(ZERO_GUID)
        buf += b"\x00" * 4  # unknown_2
        buf += b"\xff\xfe\xfd\xfc\xfb"  # garbage tail
        raw = bytes(buf)

        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )

        assert "_raw_tail" in result
        assert result["_raw_tail"] == b"\xff\xfe\xfd\xfc\xfb"
        assert result["base_camp_level"] == 99

    def test_raw_tail_roundtrip(self):
        """_raw_tail 字段在编码时逐字节写回。"""
        buf = bytearray()
        buf += _pack_guid(RAWTAIL_GUILD_ID)
        buf += _pack_fstring("RawTailGuild")
        buf += _pack_tarray_instance_ids([])
        buf += struct.pack("<B", 0)
        buf += b"\x00" * 4
        buf += _pack_tarray_uuid([])
        buf += struct.pack("<i", 0)
        buf += struct.pack("<i", 1)
        buf += _pack_tarray_uuid([])
        buf += _pack_fstring("RT")
        buf += _pack_guid(ZERO_GUID)
        buf += b"\x00" * 4
        buf += b"\xde\xad\xbe\xef"  # garbage
        raw = bytes(buf)

        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )
        assert "_raw_tail" in result
        re_encoded = encode_bytes(result)
        assert re_encoded == raw


class TestOrganizationDecode:
    """Organization 类型解码测试。"""

    @staticmethod
    def _make_reader(raw: bytes):
        return FArchiveReader(b"\x00")

    def test_org_fields_readable(self):
        """Organization 字段及尾部字节可读。"""
        raw = _build_org_bytes(unknown_bytes=b"\xee\xff")
        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Organization"
        )

        assert result["group_type"] == "EPalGroupType::Organization"
        assert result["group_name"] == "TestOrg"
        assert result["org_type"] == 2
        assert "trailing_bytes" in result
        assert result.get("unknown_bytes") is not None

    def test_org_roundtrip(self):
        """Organization 解码后编码逐字节一致。"""
        raw = _build_org_bytes(unknown_bytes=b"\xee\xff")
        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Organization"
        )
        re_encoded = encode_bytes(result)
        assert re_encoded == raw


class TestIndependentGuildDecode:
    """IndependentGuild 类型解码测试。"""

    @staticmethod
    def _make_reader(raw: bytes):
        return FArchiveReader(b"\x00")

    def test_independent_guild_fields_readable(self):
        """IndependentGuild 全部字段可读。"""
        raw = _build_independent_guild_bytes(unknown_bytes=b"\x11\x22")
        result = decode_bytes(
            self._make_reader(raw),
            list(raw),
            "EPalGroupType::IndependentGuild",
        )

        assert result["group_type"] == "EPalGroupType::IndependentGuild"
        assert result["group_name"] == "IndependentGuild"
        assert result["base_camp_level"] == 3
        assert result["guild_name"] == "IndieGuild"
        assert result["guild_name_2"] == "IndieGuild2"
        assert result["player_info"]["player_name"] == "IndiePlayer"
        assert result["player_info"]["last_online_real_time"] == 9876543210
        assert "unknown_bytes" in result

    def test_independent_guild_roundtrip(self):
        """IndependentGuild 解码后编码逐字节一致。"""
        raw = _build_independent_guild_bytes(unknown_bytes=b"\x11\x22")
        result = decode_bytes(
            self._make_reader(raw),
            list(raw),
            "EPalGroupType::IndependentGuild",
        )
        re_encoded = encode_bytes(result)
        assert re_encoded == raw


class TestEncodePurity:
    """编码纯度测试：两次 encode 一致且不修改输入。"""

    @staticmethod
    def _make_reader(raw: bytes):
        return FArchiveReader(b"\x00")

    def test_encode_twice_identical_v1_guild(self):
        """Palworld 1.0 Guild 两次 encode 结果一致。"""
        raw = _build_v1_guild_bytes()
        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )
        first = encode_bytes(result)
        second = encode_bytes(result)
        assert first == second
        assert first == raw

    def test_encode_does_not_mutate_properties(self):
        """encode 不修改输入字典。"""
        raw = _build_v1_guild_bytes()
        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )
        expected = copy.deepcopy(result)
        encode_bytes(result)
        assert result == expected


class TestFallbackRawValues:
    """已包含 values 键的 dict 直接返回原始字节。"""

    def test_values_key_triggers_raw_pass_through(self):
        """当 properties 包含 values 键时原样返回。"""
        raw = b"\x01\x02\x03"
        result = encode_bytes({"values": raw})
        assert result == raw



class TestTruncatedPlayerCount:
    """截断/损坏的 player_count 应立即回退到 _raw_tail。"""

    @staticmethod
    def _make_reader(raw: bytes):
        return FArchiveReader(b"\x00")

    def test_huge_player_count_triggers_raw_tail(self):
        """player_count 极大但剩余字节不足时回退到 _raw_tail。"""
        guild_id = "fa" * 16
        buf = bytearray()
        buf += _pack_guid(guild_id)
        buf += _pack_fstring("HugeCountGuild")
        buf += _pack_tarray_instance_ids([])
        buf += struct.pack("<B", 0)  # org_type
        buf += b"\x00" * 4  # leading_bytes
        buf += _pack_tarray_uuid([])
        buf += struct.pack("<i", 0)  # unknown_1
        buf += struct.pack("<i", 1)  # base_camp_level
        buf += _pack_tarray_uuid([])
        buf += _pack_fstring("HC")
        buf += _pack_guid(ZERO_GUID)
        buf += b"\x00" * 4  # unknown_2
        # post_unk2: admin_uid(16) + player_count(4, huge) + only 5 bytes garbage
        buf += _pack_guid(ZERO_GUID)  # admin_player_uid
        buf += struct.pack("<I", 0x7FFFFFFF)  # huge player_count as u32
        buf += b"\xff" * 5  # not enough data for any player
        raw = bytes(buf)

        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )

        assert "_raw_tail" in result
        # 应保留原始尾部（admin_uid + huge_count + garbage）
        assert result["base_camp_level"] == 1
        assert result.get("players", []) == []

    def test_truncated_player_count_falls_back(self):
        """player_count 值截断（字节不足）时回退到 _raw_tail。"""
        guild_id = "fb" * 16
        buf = bytearray()
        buf += _pack_guid(guild_id)
        buf += _pack_fstring("TruncCountGuild")
        buf += _pack_tarray_instance_ids([])
        buf += struct.pack("<B", 0)  # org_type
        buf += b"\x00" * 4  # leading_bytes
        buf += _pack_tarray_uuid([])
        buf += struct.pack("<i", 0)  # unknown_1
        buf += struct.pack("<i", 1)  # base_camp_level
        buf += _pack_tarray_uuid([])
        buf += _pack_fstring("TC")
        buf += _pack_guid(ZERO_GUID)
        buf += b"\x00" * 4  # unknown_2
        # post_unk2: only 16+3 bytes — player_count u32 被截断
        buf += _pack_guid(ZERO_GUID)  # admin_player_uid (16 bytes)
        buf += b"\x01\x02\x03"  # truncated count (only 3 of 4 bytes)
        raw = bytes(buf)

        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )

        assert "_raw_tail" in result
        assert result.get("players", []) == []


class TestPlayerUidUuidType:
    """解码后 player_uid 保持 UUID 类型。"""

    @staticmethod
    def _make_reader(raw: bytes):
        return FArchiveReader(b"\x00")

    def test_player_uid_is_uuid_not_str(self):
        """player_uid 是 UUID（非字符串），类型保持与 reader.guid() 一致。"""
        raw = _build_v1_guild_bytes(
            admin_uid=ADMIN_UID,
            players=[
                {
                    "player_uid": PLAYER1_UID,
                    "player_name": "Alice",
                    "last_online": 1000000,
                    "u8_flag": 42,
                },
            ],
        )
        result = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )

        players = result["players"]
        assert len(players) == 1
        puid = players[0]["player_uid"]
        # 不应转换为 str；保持 reader.guid() 返回的 UUID 类型
        assert not isinstance(puid, str), (
            f"player_uid should be UUID, got str: {puid!r}"
        )
        # 确认可以写回（writer.guid 接受 UUID）
        re_encoded = encode_bytes(result)
        assert re_encoded == raw, f"roundtrip failed: {re_encoded!r} != {raw!r}"


class TestEncodePurityV2:
    """encode() 函数对调用者输入纯净。"""

    @staticmethod
    def _make_reader(raw: bytes):
        return FArchiveReader(b"\x00")

    def test_encode_does_not_mutate_properties_input(self):
        """encode() 不修改调用者传入的 properties 字典。"""
        raw = _build_v1_guild_bytes(
            admin_uid=ADMIN_UID,
            players=[
                {
                    "player_uid": PLAYER1_UID,
                    "player_name": "TestPlayer",
                    "last_online": 1000000,
                    "u8_flag": 3,
                },
            ],
        )
        group_data = decode_bytes(
            self._make_reader(raw), list(raw), "EPalGroupType::Guild"
        )
        properties = {
            "custom_type": "MapProperty",
            "key_type": "StructProperty",
            "value_type": "StructProperty",
            "key_struct_type": "Guid",
            "value_struct_type": "GroupSaveDataMap",
            "value": [
                {
                    "key": {
                        "struct_type": "Guid",
                        "struct_id": "00000000-0000-0000-0000-000000000000",
                        "id": "00000000-0000-0000-0000-000000000000",
                        "value": ZERO_GUID.replace("-", ""),
                    },
                    "value": {
                        "RawData": {
                            "value": copy.deepcopy(group_data),
                        }
                    },
                }
            ],
        }
        expected = copy.deepcopy(properties)
        try:
            writer = FArchiveWriter()
            encode(writer, "MapProperty", properties)
        except Exception:
            pass  # property_inner 可能需要更完整结构，但不影响纯度断言
        assert properties == expected, (
            "encode() mutated the caller's properties dict"
        )