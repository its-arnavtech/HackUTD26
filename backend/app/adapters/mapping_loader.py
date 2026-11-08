"""Load a canonical-event mapping and apply it to one source record.

The agent is configured by choosing a file under
``data/generated/schema_mappings/`` (``nessie``, ``paysim``, ``sparkov``,
``ibm_aml``, ``generic_card_processor``, ``telecom_billing``). Adding a source
system is a new YAML file, not a code change.

``apply_mapping`` returns only the fields that file defines. It does not invent
device, auth, or bill objects the source never had. Missing sources become
null, except where the file sets a default (currency, for example).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from app.config import DATA_DIR

MAPPINGS_DIR = DATA_DIR / "generated" / "schema_mappings"

_MISSING = object()


@dataclass(frozen=True)
class FieldSpec:
    source: tuple[str, ...]
    transform: str
    enum_map: dict[str, str] = field(default_factory=dict)
    default: Any = None
    factor: float = 1
    missing: Any = None
    notes: str = ""


@dataclass(frozen=True)
class SchemaMapping:
    """One source system, as declared in its YAML file."""

    name: str
    source_system: str
    description: str
    origin: str | None
    fields: dict[str, FieldSpec]

    def field_names(self) -> tuple[str, ...]:
        return tuple(self.fields)


def available_mappings(directory: Path | None = None) -> list[str]:
    """Mapping names, sorted, without the ``.yaml`` suffix."""
    folder = directory or MAPPINGS_DIR
    return sorted(path.stem for path in folder.glob("*.yaml"))


def load_mapping(name: str, directory: Path | None = None) -> SchemaMapping:
    """Load ``{name}.yaml``. ``name`` is a file stem, not a path."""
    folder = directory or MAPPINGS_DIR
    path = folder / f"{name}.yaml"
    if not path.is_file():
        known = ", ".join(available_mappings(folder)) or "(none)"
        raise FileNotFoundError(f"No mapping {name!r} in {folder}. Known: {known}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a mapping object")
    fields: dict[str, FieldSpec] = {}
    for key, raw in (data.get("fields") or {}).items():
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: field {key} is not a mapping")
        source = raw.get("source", [])
        if isinstance(source, str):
            source = [source]
        enum_map = {str(k): str(v) for k, v in (raw.get("enum_map") or {}).items()}
        fields[str(key)] = FieldSpec(
            source=tuple(str(item) for item in source),
            transform=str(raw.get("transform") or "identity"),
            enum_map=enum_map,
            default=raw.get("default"),
            factor=float(raw.get("factor", 1)),
            missing=raw.get("missing"),
            notes=str(raw.get("notes") or ""),
        )
    return SchemaMapping(
        name=str(data.get("name") or name),
        source_system=str(data.get("source_system") or name),
        description=str(data.get("description") or "").strip(),
        origin=data.get("origin") or None,
        fields=fields,
    )


def configure(name: str, directory: Path | None = None) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Return ``record -> canonical fields`` for the named mapping file."""
    mapping = load_mapping(name, directory)

    def convert(record: dict[str, Any]) -> dict[str, Any]:
        return apply_mapping(record, mapping)

    return convert


def apply_mapping(record: dict[str, Any], mapping: SchemaMapping) -> dict[str, Any]:
    """Map one source row onto the canonical fields that file declares."""
    out: dict[str, Any] = {"source_system": mapping.source_system}
    for key, spec in mapping.fields.items():
        raw = _first(record, spec.source)
        _assign(out, key, _transform(raw, spec, mapping))
    return out


def _first(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return _MISSING


def _assign(out: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = out
    for part in parts[:-1]:
        current = cursor.get(part)
        if not isinstance(current, dict):
            current = {}
            cursor[part] = current
        cursor = current
    cursor[parts[-1]] = value


def _transform(raw: Any, spec: FieldSpec, mapping: SchemaMapping) -> Any:
    if spec.transform == "identity":
        return spec.missing if raw is _MISSING else raw
    if spec.transform == "null_to_default":
        if raw is _MISSING or raw is None:
            return spec.default
        return raw
    if spec.transform == "multiply":
        if raw is _MISSING or raw is None:
            return spec.missing
        return int(round(float(raw) * spec.factor))
    if spec.transform == "enum_map":
        if raw is _MISSING or raw is None:
            return spec.missing
        return spec.enum_map.get(str(raw), spec.missing)
    if spec.transform == "truthy":
        if raw is _MISSING or raw is None:
            return spec.missing
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "y"}
        return bool(raw)
    if spec.transform == "to_utc":
        if raw is _MISSING or raw is None:
            return spec.missing
        return _to_utc(str(raw))
    if spec.transform == "hour_offset":
        if raw is _MISSING or raw is None:
            return spec.missing
        if not mapping.origin:
            raise ValueError(f"{mapping.name} uses hour_offset but has no origin")
        origin = datetime.fromisoformat(mapping.origin.replace("Z", "+00:00"))
        return (origin + timedelta(hours=int(raw))).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raise ValueError(f"Unknown transform {spec.transform!r} on {mapping.name}")


def _to_utc(value: str) -> str:
    text = value.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text}T00:00:00Z"
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    if text.endswith("Z"):
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    else:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
