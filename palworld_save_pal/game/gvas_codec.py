import base64
import re
import logging
from functools import wraps


_logger = logging.getLogger(__name__)


def _make_eof_safe_decode(fn, label):
    """Wrap a ``decode_bytes`` callable to return raw bytes on EOF mismatch.

    Palworld 1.0 adds fields that the save-tools decoders don't know about,
    causing ``Exception("Warning: EOF not reached ...")``.  This wrapper
    intercepts those and preserves the original bytes so round-trip re-encoding
    is bit-identical.
    """

    @wraps(fn)
    def _wrapper(parent_reader, m_bytes, entity_id):
        try:
            return fn(parent_reader, m_bytes, entity_id)
        except Exception as exc:
            if str(exc).startswith("Warning: EOF not reached"):
                _logger.debug(
                    "Preserving raw bytes for %s %r (EOF not reached)",
                    label,
                    entity_id,
                )
                return {"values": _ensure_bytes(m_bytes)}
            raise

    return _wrapper


def _install_eof_safe_wrappers():
    """Idempotently install EOF-safe wrappers on both map concrete model decoders."""
    import palworld_save_tools.rawdata.map_concrete_model as _mcm
    import palworld_save_tools.rawdata.map_concrete_model_module as _mcmm

    if not getattr(_mcm.decode_bytes, "_eof_safe", False):
        _mcm.decode_bytes = _make_eof_safe_decode(_mcm.decode_bytes, "map object")
        _mcm.decode_bytes._eof_safe = True  # type: ignore[attr-defined]

    if not getattr(_mcmm.decode_bytes, "_eof_safe", False):
        _mcmm.decode_bytes = _make_eof_safe_decode(_mcmm.decode_bytes, "module")
        _mcmm.decode_bytes._eof_safe = True  # type: ignore[attr-defined]


_install_eof_safe_wrappers()


from enum import Enum

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


class SaveType(int, Enum):
    STEAM = 0
    GAMEPASS = 1
