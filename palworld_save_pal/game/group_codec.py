"""Palworld 存档 Group/Base 数据本地结构化编解码器。

将 :class:`palworld_save_tools.rawdata.group` 的代码逻辑移植到本仓库，
直接使用 :mod:`palworld_save_tools.archive` 的 ``FArchiveReader`` / ``FArchiveWriter``，
不经过上游 group 模块的 EOF 回退包装。

支持的 Group 类型
------------------
- ``EPalGroupType::Guild`` （含 Palworld 1.0 marker + 每玩家 ``_u8_flag``）
- ``EPalGroupType::Organization``
- ``EPalGroupType::IndependentGuild``
- 未知类型（保留剩余字节的 raw fallback）

与上游的关键差异
----------------
- 当 Palworld 1.0 tail 解析失败时保存到 ``_raw_tail`` 字段（二进制原文），
  而非直接抛出异常回退为 ``{"values": bytes}`` 丢失全部结构化信息。
- ``_u8_flag`` 逐玩家保留，不会被忽略。
- ``decode_bytes`` / ``encode_bytes`` 以 ``Sequence[int]`` / ``dict`` 为输入/输出，
  与上游接口兼容。

参见
----
实现了与参考实现等价的二进制往返保真，
参考自 ``PalworldSaveTools/src/palsav/palsav/rawdata/group.py``。
"""

import copy
from typing import Any, Sequence

from palworld_save_tools.archive import (
    FArchiveReader,
    FArchiveWriter,
    instance_id_reader,
    instance_id_writer,
    uuid_reader,
    uuid_writer,
)

V1_MARKER = b"\x02\x00\x00\x00\x02\x03\x00\x00\x00\x00"


# ── 解码 ──────────────────────────────────────────────────────


def decode(
    reader: FArchiveReader,
    type_name: str,
    size: int,
    path: str,
) -> dict[str, Any]:
    """解码 GroupSaveDataMap MapProperty。"""
    if type_name != "MapProperty":
        raise ValueError(f"Expected MapProperty, got {type_name}")
    value = reader.property(type_name, size, path, nested_caller_path=path)
    group_map: list[dict[str, Any]] = value["value"]
    for group in group_map:
        gv = group["value"]
        group_type: str = gv["GroupType"]["value"]["value"]
        group_bytes: Sequence[int] = gv["RawData"]["value"]["values"]
        gv["RawData"]["value"] = decode_bytes(reader, group_bytes, group_type)
    return value


def decode_bytes(
    parent_reader: FArchiveReader,
    group_bytes: Sequence[int],
    group_type: str,
) -> dict[str, Any]:
    """解码单个 group 的 ``RawData`` 字节为结构化 dict。

    参数
    ----
    parent_reader:
        上层解析器，用于创建子解析器。
    group_bytes:
        待解析的字节序列。
    group_type:
        Group 类型字符串，如 ``"EPalGroupType::Guild"``。

    返回
    ----
    dict
        含 ``group_type``、``group_id``、``group_name`` 及类型专属字段。
        失败时可能包含 ``_raw_tail`` 字段。
    """
    reader = parent_reader.internal_copy(bytes(group_bytes), debug=False)
    group_data: dict[str, Any] = {
        "group_type": group_type,
        "group_id": reader.guid(),
        "group_name": reader.fstring(),
        "individual_character_handle_ids": reader.tarray(instance_id_reader),
    }

    if group_type in (
        "EPalGroupType::Guild",
        "EPalGroupType::IndependentGuild",
        "EPalGroupType::Organization",
    ):
        group_data["org_type"] = reader.byte()

    # ── Organization ──
    if group_type == "EPalGroupType::Organization":
        group_data["trailing_bytes"] = [
            int(b) for b in reader.byte_list(12)
        ]
        if not reader.eof():
            group_data["unknown_bytes"] = [
                int(b) for b in reader.read_to_end()
            ]
        return group_data

    # ── IndependentGuild ──
    if group_type == "EPalGroupType::IndependentGuild":
        group_data["base_camp_level"] = reader.i32()
        group_data["map_object_instance_ids_base_camp_points"] = reader.tarray(
            uuid_reader
        )
        group_data["guild_name"] = reader.fstring()
        group_data["player_uid"] = reader.guid()
        group_data["guild_name_2"] = reader.fstring()
        group_data["player_info"] = {
            "last_online_real_time": reader.i64(),
            "player_name": reader.fstring(),
        }
        if not reader.eof():
            group_data["unknown_bytes"] = [
                int(b) for b in reader.read_to_end()
            ]
        return group_data

    # ── 未知类型（非 Guild/Organization/IndependentGuild）──
    if group_type not in (
        "EPalGroupType::Guild",
        "EPalGroupType::Organization",
        "EPalGroupType::IndependentGuild",
    ):
        import sys as _sys
        print(
            f"group_codec.py: unknown group_type {group_type}",
            file=_sys.stderr,
        )
        if not reader.eof():
            group_data["unknown_bytes"] = [
                int(b) for b in reader.read_to_end()
            ]
        return group_data

    # ── Guild（含 Palworld 1.0 marker 检测）──
    group_data["leading_bytes"] = [
        int(b) for b in reader.byte_list(4)
    ]
    group_data["base_ids"] = reader.tarray(uuid_reader)
    group_data["unknown_1"] = reader.i32()
    group_data["base_camp_level"] = reader.i32()
    group_data["map_object_instance_ids_base_camp_points"] = reader.tarray(
        uuid_reader
    )
    group_data["guild_name"] = reader.fstring()
    group_data["last_guild_name_modifier_player_uid"] = reader.guid()
    group_data["unknown_2"] = [int(b) for b in reader.byte_list(4)]

    post_unk2 = reader.read_to_end()
    original_tail = post_unk2

    # Palworld 1.0 marker 检测
    vi = post_unk2.find(V1_MARKER)
    if vi >= 0:
        group_data["_has_v1_marker"] = True
        pre = post_unk2[:vi]
        if pre:
            group_data["_pre_v1_bytes"] = pre
        post_unk2 = post_unk2[vi + 10:]

    # 尝试解析 v1 尾部（admin UID + player tarray）
    try:
        sub = parent_reader.internal_copy(bytes(post_unk2), debug=False)
        admin_player_uid = sub.guid()
        player_count = sub.u32()
        # 验证 player_count 合理性：每玩家最少 GUID16+i64 8+fstring长度头4=28 字节
        _min_per_player = 28
        _remaining = len(post_unk2) - sub.data.tell()
        if player_count * _min_per_player > _remaining:
            raise ValueError(
                f"player_count {player_count} exceeds remaining "
                f"{_remaining} bytes (min {_min_per_player}/player)"
            )
        players: list[dict[str, Any]] = []
        for _ in range(player_count):
            puid = sub.guid()
            lt = sub.i64()
            nm = sub.fstring()
            if group_data.get("_has_v1_marker") and not sub.eof():
                flag = sub.byte()
                players.append(
                    {
                        "player_uid": puid,
                        "player_info": {
                            "last_online_real_time": lt,
                            "player_name": nm,
                        },
                        "_u8_flag": flag,
                    }
                )
            else:
                players.append(
                    {
                        "player_uid": puid,
                        "player_info": {
                            "last_online_real_time": lt,
                            "player_name": nm,
                        },
                    }
                )
        group_data["admin_player_uid"] = admin_player_uid
        group_data["players"] = players
        trailing_bytes = sub.read_to_end()
        if trailing_bytes:
            group_data["_trailing_bytes"] = [
                int(b) for b in trailing_bytes
            ]
    except Exception:
        group_data["_raw_tail"] = original_tail

    group_data.setdefault("players", [])

    if not reader.eof():
        group_data["unknown_bytes"] = [
            int(b) for b in reader.read_to_end()
        ]

    return group_data


# ── 编码 ──────────────────────────────────────────────────────


def encode(
    writer: FArchiveWriter,
    property_type: str,
    properties: dict[str, Any],
) -> int:
    """编码 GroupSaveDataMap MapProperty。

    在内部，将已解码的 group 数据重新序列化为字节并写入 raw ``values``，
    这样上层 MapProperty 写入器就能以 ByteProperty 数组的形式输出。
    """
    if property_type != "MapProperty":
        raise ValueError(f"Expected MapProperty, got {property_type}")
    # 深拷贝以避免修改调用者的 properties 字典
    properties = copy.deepcopy(properties)
    del properties["custom_type"]
    group_map: list[dict[str, Any]] = properties["value"]
    for group in group_map:
        raw_val = group["value"].get("RawData", {}).get("value")
        if not raw_val or "values" in raw_val:
            continue
        encoded_bytes = encode_bytes(raw_val)
        group["value"]["RawData"]["value"] = {
            "values": [b for b in encoded_bytes]
        }
    return writer.property_inner(property_type, properties)


def encode_bytes(p: dict[str, Any]) -> bytes:
    """将单个 group 的结构化 dict 编码为二进制字节。

    参数
    ----
    p:
        与 :func:`decode_bytes` 返回格式一致的字典。
        如果包含 ``values`` 键（原始字节回退），直接返回该字节。

    返回
    ----
    bytes
        编码后的二进制数据。
    """
    if "values" in p:
        return bytes(p["values"])

    writer = FArchiveWriter()
    writer.guid(p["group_id"])
    writer.fstring(p["group_name"])
    writer.tarray(instance_id_writer, p["individual_character_handle_ids"])

    if p["group_type"] in (
        "EPalGroupType::Guild",
        "EPalGroupType::IndependentGuild",
        "EPalGroupType::Organization",
    ):
        writer.byte(p["org_type"])

    # ── Organization ──
    if p["group_type"] == "EPalGroupType::Organization":
        writer.write(bytes(p["trailing_bytes"]))
        if "unknown_bytes" in p:
            writer.write(bytes(p["unknown_bytes"]))
        return writer.bytes()

    # ── IndependentGuild ──
    if p["group_type"] == "EPalGroupType::IndependentGuild":
        writer.i32(p["base_camp_level"])
        writer.tarray(
            uuid_writer, p["map_object_instance_ids_base_camp_points"]
        )
        writer.fstring(p["guild_name"])
        writer.guid(p["player_uid"])
        writer.fstring(p["guild_name_2"])
        writer.i64(p["player_info"]["last_online_real_time"])
        writer.fstring(p["player_info"]["player_name"])
        if "unknown_bytes" in p:
            writer.write(bytes(p["unknown_bytes"]))
        return writer.bytes()

    # ── Guild ──
    if p["group_type"] == "EPalGroupType::Guild":
        writer.write(bytes(p["leading_bytes"]))
        writer.tarray(uuid_writer, p["base_ids"])
        writer.i32(p["unknown_1"])
        writer.i32(p["base_camp_level"])
        writer.tarray(
            uuid_writer, p["map_object_instance_ids_base_camp_points"]
        )
        writer.fstring(p["guild_name"])
        writer.guid(p["last_guild_name_modifier_player_uid"])
        writer.write(bytes(p["unknown_2"]))

        if "_raw_tail" in p:
            writer.write(bytes(p["_raw_tail"]))
        elif "admin_player_uid" in p:
            if p.get("_has_v1_marker"):
                if "_pre_v1_bytes" in p:
                    writer.write(bytes(p["_pre_v1_bytes"]))
                writer.write(V1_MARKER)
            writer.guid(p["admin_player_uid"])
            writer.tarray(_player_info_writer, p.get("players", []))
            if "_trailing_bytes" in p:
                writer.write(bytes(p["_trailing_bytes"]))
            elif "trailing_bytes" in p:
                writer.write(bytes(p["trailing_bytes"]))

        if "unknown_bytes" in p:
            writer.write(bytes(p["unknown_bytes"]))
        return writer.bytes()

    # ── 未知类型 ──
    if "unknown_bytes" in p:
        writer.write(bytes(p["unknown_bytes"]))
    return writer.bytes()


def _player_info_writer(
    writer: FArchiveWriter, p: dict[str, Any]
) -> None:
    """将玩家信息写入 tarray writer 回调。"""
    if "player_uid" in p:
        writer.guid(p["player_uid"])
        writer.i64(p["player_info"]["last_online_real_time"])
        writer.fstring(p["player_info"]["player_name"])
        if "_u8_flag" in p:
            writer.byte(p["_u8_flag"])
