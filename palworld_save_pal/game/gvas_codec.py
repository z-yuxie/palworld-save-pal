import base64
import functools
import logging
import re
from enum import Enum
_logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=256)
def _log_eof_once(label: str, entity_id_repr: str) -> None:
    _logger.debug(
        "保留 %s %r 的原始字节（EOF 未到达）",
        label,
        entity_id_repr,
    )


def _make_eof_safe_decode(fn, label):
    """包装 ``decode_bytes`` 可调用对象，在 EOF 不匹配时返回原始字节。

    Palworld 1.0 新增了 save-tools 解码器不认识的字段，
    导致 ``Exception("Warning: EOF not reached ...")``。
    此包装器拦截该异常并保留原始字节，确保回写时逐位一致。
    """

    @functools.wraps(fn)
    def _wrapper(parent_reader, m_bytes, entity_id):
        try:
            return fn(parent_reader, m_bytes, entity_id)
        except Exception as exc:
            if str(exc).startswith("Warning: EOF not reached"):
                try:
                    key = repr(entity_id)
                except Exception:
                    key = "<unrepresentable>"
                _log_eof_once(label, key)
                return {"values": _ensure_bytes(m_bytes)}
            raise

    return _wrapper


def _install_eof_safe_wrappers():
    """幂等地在 map object 及 module 解码器上安装 EOF 安全包装器。"""
    import palworld_save_tools.rawdata.map_concrete_model as _mcm
    import palworld_save_tools.rawdata.map_concrete_model_module as _mcmm

    if not getattr(_mcm.decode_bytes, "_palworld_save_pal_eof_safe_v1", False):
        _mcm.decode_bytes = _make_eof_safe_decode(_mcm.decode_bytes, "map object")
        _mcm.decode_bytes._palworld_save_pal_eof_safe_v1 = True  # type: ignore[attr-defined]

    if not getattr(_mcmm.decode_bytes, "_palworld_save_pal_eof_safe_v1", False):
        _mcmm.decode_bytes = _make_eof_safe_decode(_mcmm.decode_bytes, "module")
        _mcmm.decode_bytes._palworld_save_pal_eof_safe_v1 = True  # type: ignore[attr-defined]



from palworld_save_tools.archive import (
    FArchiveReader,
    FArchiveWriter,
)
from palworld_save_tools.paltypes import PALWORLD_CUSTOM_PROPERTIES


def skip_decode(reader: FArchiveReader, type_name: str, size: int, path: str):
    if type_name == "ArrayProperty":
        array_type = reader.fstring()
        value = {
            "skip_type": type_name,
            "array_type": array_type,
            "id": reader.optional_guid(),
            "value": reader.read(size),
        }
    elif type_name == "MapProperty":
        key_type = reader.fstring()
        value_type = reader.fstring()
        _id = reader.optional_guid()
        value = {
            "skip_type": type_name,
            "key_type": key_type,
            "value_type": value_type,
            "id": _id,
            "value": reader.read(size),
        }
    elif type_name == "StructProperty":
        value = {
            "skip_type": type_name,
            "struct_type": reader.fstring(),
            "struct_id": reader.guid(),
            "id": reader.optional_guid(),
            "value": reader.read(size),
        }
    else:
        raise ValueError(
            f"Expected ArrayProperty or MapProperty or StructProperty, got {type_name} in {path}"
        )
    return value


_LEGACY_HEX_RE = re.compile(r"^[0-9a-f]*$")


def _ensure_bytes(value):
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        # Legacy palworld-save-tools emitted bytes as lowercase .hex();
        # current palworld-save-tools emits standard base64.
        if len(value) % 2 == 0 and _LEGACY_HEX_RE.match(value):
            return bytes.fromhex(value)
        return base64.b64decode(value, validate=True)
    return bytes(value)


_install_eof_safe_wrappers()

def skip_encode(writer: FArchiveWriter, property_type: str, properties: dict) -> int:
    if "skip_type" not in properties:
        if (
            properties["custom_type"] in PALWORLD_CUSTOM_PROPERTIES
            and PALWORLD_CUSTOM_PROPERTIES[properties["custom_type"]] is not None
        ):
            return PALWORLD_CUSTOM_PROPERTIES[properties["custom_type"]][1](
                writer, property_type, properties
            )
        else:
            # Never be run to here
            return writer.property_inner(writer, property_type, properties)
    if property_type == "ArrayProperty":
        writer.fstring(properties["array_type"])
        writer.optional_guid(properties.get("id", None))
        data = _ensure_bytes(properties["value"])
        writer.write(data)
        return len(data)
    elif property_type == "MapProperty":
        writer.fstring(properties["key_type"])
        writer.fstring(properties["value_type"])
        writer.optional_guid(properties.get("id", None))
        data = _ensure_bytes(properties["value"])
        writer.write(data)
        return len(data)
    elif property_type == "StructProperty":
        writer.fstring(properties["struct_type"])
        writer.guid(properties["struct_id"])
        writer.optional_guid(properties.get("id", None))
        data = _ensure_bytes(properties["value"])
        writer.write(data)
        return len(data)
    else:
        raise ValueError(
            f"Expected ArrayProperty or MapProperty or StructProperty, got {property_type}"
        )


CUSTOM_PROPERTIES = {k: v for k, v in PALWORLD_CUSTOM_PROPERTIES.items()}
CUSTOM_PROPERTIES[".worldSaveData.FoliageGridSaveDataMap"] = (skip_decode, skip_encode)
CUSTOM_PROPERTIES[".worldSaveData.MapObjectSpawnerInStageSaveData"] = (
    skip_decode,
    skip_encode,
)
CUSTOM_PROPERTIES[".worldSaveData.DungeonSaveData"] = (skip_decode, skip_encode)
CUSTOM_PROPERTIES[".worldSaveData.EnemyCampSaveData"] = (skip_decode, skip_encode)
CUSTOM_PROPERTIES[".worldSaveData.InvaderSaveData"] = (skip_decode, skip_encode)
CUSTOM_PROPERTIES[".worldSaveData.DungeonPointMarkerSaveData"] = (
    skip_decode,
    skip_encode,
)
CUSTOM_PROPERTIES[".worldSaveData.GameTimeSaveData"] = (skip_decode, skip_encode)
CUSTOM_PROPERTIES[".worldSaveData.OilrigSaveData"] = (skip_decode, skip_encode)
CUSTOM_PROPERTIES[".worldSaveData.SupplySaveData"] = (skip_decode, skip_encode)
CUSTOM_PROPERTIES[".worldSaveData.BaseCampSaveData.Value.ModuleMap"] = (
    skip_decode,
    skip_encode,
)
from palworld_save_pal.game.group_codec import decode as _group_decode, encode as _group_encode
CUSTOM_PROPERTIES[".worldSaveData.GroupSaveDataMap"] = (_group_decode, _group_encode)


class SaveType(int, Enum):
    STEAM = 0
    GAMEPASS = 1
