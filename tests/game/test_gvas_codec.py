import base64
import copy

import pytest
from palworld_save_tools.archive import FArchiveReader, FArchiveWriter

from palworld_save_pal.game.gvas_codec import (
    CUSTOM_PROPERTIES,
    SaveType,
    _ensure_bytes,
    skip_encode,
)


def _skipped_array_property() -> dict:
    """A property dict shaped like skip_decode() output for an ArrayProperty."""
    return {
        "skip_type": "ArrayProperty",
        "array_type": "ByteProperty",
        "id": None,
        "value": b"\x01\x02\x03\x04",
        "custom_type": ".worldSaveData.FoliageGridSaveDataMap",
    }


class TestSaveType:
    def test_steam_value(self):
        assert SaveType.STEAM == 0

    def test_gamepass_value(self):
        assert SaveType.GAMEPASS == 1

    def test_is_int_enum(self):
        assert isinstance(SaveType.STEAM.value, int)


class TestCustomProperties:
    def test_foliage_registered(self):
        assert ".worldSaveData.FoliageGridSaveDataMap" in CUSTOM_PROPERTIES

    def test_dungeon_registered(self):
        assert ".worldSaveData.DungeonSaveData" in CUSTOM_PROPERTIES

    def test_enemy_camp_registered(self):
        assert ".worldSaveData.EnemyCampSaveData" in CUSTOM_PROPERTIES

    def test_game_time_registered(self):
        assert ".worldSaveData.GameTimeSaveData" in CUSTOM_PROPERTIES

    def test_base_camp_module_map(self):
        assert ".worldSaveData.BaseCampSaveData.Value.ModuleMap" in CUSTOM_PROPERTIES

    def test_skip_properties_have_decode_encode_tuple(self):
        key = ".worldSaveData.FoliageGridSaveDataMap"
        handler = CUSTOM_PROPERTIES[key]
        assert isinstance(handler, tuple)
        assert len(handler) == 2
        assert callable(handler[0])
        assert callable(handler[1])

    def test_inherits_palworld_custom_properties(self):
        # Should include properties from palworld-save-tools
        assert len(CUSTOM_PROPERTIES) > 10


class TestEnsureBytes:
    def test_passes_bytes_through(self):
        assert _ensure_bytes(b"\x01\x02\x03") == b"\x01\x02\x03"

    def test_converts_bytearray(self):
        assert _ensure_bytes(bytearray(b"\x01\x02")) == b"\x01\x02"

    def test_decodes_base64_string(self):
        payload = b"\x00\x10\xffhello"
        encoded = base64.b64encode(payload).decode("ascii")
        assert _ensure_bytes(encoded) == payload

    def test_falls_back_to_hex_for_legacy_strings(self):
        payload = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        encoded = payload.hex()
        assert _ensure_bytes(encoded) == payload

    def test_empty_string_returns_empty_bytes(self):
        assert _ensure_bytes("") == b""

    def test_list_of_ints_converted(self):
        assert _ensure_bytes([1, 2, 3]) == b"\x01\x02\x03"


class TestSkipEncodePurity:
    """skip_encode must not consume the dict it is handed.

    SaveManager caches GvasFile objects and serializes them more than once
    (to_level_sav_file, level_meta_sav, to_player_sav_files). An encoder that
    strips `custom_type`/`skip_type` in place makes the second write wrong.
    """

    def test_does_not_mutate_caller_dict(self):
        properties = _skipped_array_property()
        expected = copy.deepcopy(properties)

        skip_encode(FArchiveWriter(), "ArrayProperty", properties)

        assert properties == expected

    def test_encode_twice_produces_identical_bytes(self):
        properties = _skipped_array_property()

        first = FArchiveWriter()
        skip_encode(first, "ArrayProperty", properties)

        second = FArchiveWriter()
        skip_encode(second, "ArrayProperty", properties)

        assert first.bytes() == second.bytes()

    def test_returns_payload_length(self):
        properties = _skipped_array_property()
        written = skip_encode(FArchiveWriter(), "ArrayProperty", properties)
        assert written == 4


class TestMapObjectEofRecovery:
    """Palworld 1.0 map object/module 数据中未知尾部字节的测试。

    当 Palworld 1.0 新增字段时，palworld-save-tools 解码器会抛出
    ``Exception("Warning: EOF not reached ...")``。
    gvas_codec 包装器必须拦截此异常并原样返回原始字节，以确保回写安全。
    """

    # 用户真实 shrine_lantern 错误中提取的 44 字节 hex：
    # 前 32 字节为两个 GUID（instance_id + model_instance_id），
    # 后 12 字节为尾部数据。解码器期望 36 字节，多出 8 字节触发 EOF 异常。
    SHRINE_LANTERN_HEX = (
        "0614917f7d395045b9e58ae99a17a60b"
        "f686220f85f8cd4d9bcaca3f54f7e31f"
        "000000000000000000000000"
    )

    @staticmethod
    def _parent_reader():
        from palworld_save_tools.archive import FArchiveReader
        return FArchiveReader(b"\x00")

    def test_extra_trailing_bytes_preserved(self):
        """map object 中 EOF 未到达时原样返回原始 44 字节。"""
        from palworld_save_tools.rawdata import map_concrete_model

        raw = list(bytes.fromhex(self.SHRINE_LANTERN_HEX))
        result = map_concrete_model.decode_bytes(
            self._parent_reader(), raw, "shrine_lantern"
        )

        assert len(raw) == 44
        assert result == {"values": bytes(raw)}

    def test_unknown_module_bytes_preserved(self):
        """module 解码器中 EOF 未到达时原样返回原始字节。"""
        from palworld_save_tools.rawdata import map_concrete_model_module

        raw = list(bytes([0xBB] * 12))
        result = map_concrete_model_module.decode_bytes(
            self._parent_reader(),
            raw,
            "EPalMapObjectConcreteModelModuleType::OperationalLoad",
        )

        assert result == {"values": bytes(raw)}

    def test_non_eof_exception_propagates(self):
        """不以 'Warning: EOF not reached' 开头的异常会被重新抛出。"""
        from palworld_save_pal.game.gvas_codec import _make_eof_safe_decode

        _sentinel = Exception("SomeOtherError: something went wrong")

        def _fake_decoder(_reader, m_bytes, _entity_id):
            raise _sentinel

        wrapped = _make_eof_safe_decode(_fake_decoder, "test")

        with pytest.raises(Exception) as exc_info:
            wrapped(self._parent_reader(), b"\x00", "test_entity")

        # 同一个异常对象传播，未被吞没或替换
        assert exc_info.value is _sentinel

    def test_successful_decode_unaffected(self):
        """无 EOF 不匹配的正常解码返回结构化数据。"""
        from palworld_save_tools.rawdata import map_concrete_model

        # 恰好 36 字节：两个 GUID（16+16）+ 4 字节尾部 — 无多余字节
        valid = b"\x01" * 16 + b"\x02" * 16 + b"\x00" * 4
        result = map_concrete_model.decode_bytes(
            self._parent_reader(), list(valid), "shrine_lantern"
        )

        assert "instance_id" in result
        assert "model_instance_id" in result
        assert result.get("concrete_model_type") == "PalMapObjectLampModel"

    def test_shrine_fallback_roundtrip(self):
        """Shrine 回退结果通过 array_property 写读往返后字节一致。"""
        from palworld_save_tools.archive import FArchiveReader, FArchiveWriter
        from palworld_save_tools.rawdata import map_concrete_model

        raw = list(bytes.fromhex(self.SHRINE_LANTERN_HEX))
        # 第一步：触发 EOF 回退，拿到 {'values': bytes(raw)}
        fallback = map_concrete_model.decode_bytes(
            self._parent_reader(), raw, "shrine_lantern"
        )
        assert fallback == {"values": bytes(raw)}

        # 第二步：将回退结果写入 FArchiveWriter
        writer = FArchiveWriter()
        writer.array_property("ByteProperty", fallback)
        written = writer.bytes()

        # 第三步：从写入的字节读回
        reader = FArchiveReader(written)
        read_back = reader.array_property(
            "ByteProperty", len(raw), "shrine_lantern"
        )

        # 第四步：断言读回的字节与原始字节完全一致
        assert read_back["values"] == bytes(raw)


class TestGroupLocalCodec:
    """本地 Group codec 集成测试。

    验证 :mod:`palworld_save_pal.game.group_codec` 已正确注册到
    ``CUSTOM_PROPERTIES`` 并替代上游 ``rawdata.group`` 的 EOF 回退包装，
    实现结构化 Guild 解码而非整段回退为原始字节。
    """

    def test_local_codec_registered(self):
        """GroupSaveDataMap 指向本地 group_codec。"""
        from palworld_save_pal.game.gvas_codec import CUSTOM_PROPERTIES as cp
        from palworld_save_pal.game.group_codec import decode, encode

        handler = cp[".worldSaveData.GroupSaveDataMap"]
        assert handler == (decode, encode)

    def test_map_object_wrapper_still_installed(self):
        """map_concrete_model EOF 包装器保持安装。"""
        from palworld_save_tools.rawdata import map_concrete_model as mcm
        assert getattr(mcm.decode_bytes, "_palworld_save_pal_eof_safe_v1", False)

    def test_module_wrapper_still_installed(self):
        """map_concrete_model_module EOF 包装器保持安装。"""
        from palworld_save_tools.rawdata import map_concrete_model_module as mcmm
        assert getattr(mcmm.decode_bytes, "_palworld_save_pal_eof_safe_v1", False)

    def test_non_eof_exception_propagates(self):
        """不以 'Warning: EOF not reached' 开头的异常会被重新抛出。"""
        from palworld_save_pal.game.gvas_codec import _make_eof_safe_decode

        _sentinel = Exception("SomeOtherError: something went wrong")

        def _fake_decoder(_reader, m_bytes, _entity_id):
            raise _sentinel

        wrapped = _make_eof_safe_decode(_fake_decoder, "test")

        with pytest.raises(Exception) as exc_info:
            wrapped(FArchiveReader(b"\x00"), b"\x00", "test_entity")

        assert exc_info.value is _sentinel

    def test_wrapper_idempotent(self):
        """包装器幂等：重复安装不改变 map_concrete_model.decode_bytes 引用。"""
        from palworld_save_pal.game.gvas_codec import _install_eof_safe_wrappers
        from palworld_save_tools.rawdata import map_concrete_model as mcm

        _install_eof_safe_wrappers()
        fn_first = mcm.decode_bytes

        _install_eof_safe_wrappers()
        fn_second = mcm.decode_bytes

        assert fn_first is fn_second
