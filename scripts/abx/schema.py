"""The JSON Schema subset the harness's own schemas use, validated without dependencies.

Supported keywords: type, properties, required, additionalProperties (false only), items,
enum, const, minItems, maxItems, minLength, maxLength, pattern, minimum, maximum.
An unsupported keyword in a schema is an error, so a schema can't silently ask for a
check this validator doesn't perform.
"""

import re

_SUPPORTED = {
    "type", "properties", "required", "additionalProperties", "items", "enum", "const",
    "minItems", "maxItems", "minLength", "maxLength", "pattern", "minimum", "maximum",
    "description", "title", "$schema",
}

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _is_type(value, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def errors(value, schema: dict, where: str = "$") -> list[str]:
    """Every violation, as `path: reason`; empty when valid."""
    unknown = set(schema) - _SUPPORTED
    if unknown:
        raise ValueError(f"schema at {where} uses unsupported keywords {sorted(unknown)}")
    if schema.get("additionalProperties", False) is not False:
        raise ValueError(f"schema at {where}: additionalProperties may only be false")
    out: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_is_type(value, n) for n in names):
            return [f"{where}: expected {expected}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        out.append(f"{where}: not the required constant")
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{where}: not one of the allowed values")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            out.append(f"{where}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{where}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{where}: does not match {schema['pattern']}")
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{where}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{where}: above {schema['maximum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            out.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{where}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                out += errors(item, schema["items"], f"{where}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{where}: missing {key!r}")
        if schema.get("additionalProperties") is False:
            out += [f"{where}: unexpected field" for k in value if k not in props]
        for key, sub in props.items():
            if key in value:
                out += errors(value[key], sub, f"{where}.{key}")
    return out
