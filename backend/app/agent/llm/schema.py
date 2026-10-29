"""JSON Schemas for structured output and tool parameters, from Pydantic models.

The Meta Model API checks `strict: true` schemas against a strict subset
(https://dev.meta.ai/docs/structured-output): the root is a plain object, every object sets
`additionalProperties: false` and lists all its properties in `required`, `allOf` / `oneOf` are
not supported and recursive `$ref` is rejected. Pydantic's schema is rewritten to that subset:
references are inlined, `allOf` wrappers of a single schema are unwrapped, optional fields
become required-but-nullable, and annotation-only keywords are dropped. Pydantic still validates
the parsed result against the full model.
"""

from typing import Any

from pydantic import BaseModel

# Keywords that do not constrain the output, or whose support is not documented.
_DROPPED = frozenset({"title", "default", "examples", "format", "discriminator"})
MAX_DEPTH = 10  # documented nesting limit


class SchemaError(ValueError):
    pass


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs: dict[str, Any] = raw.pop("$defs", {})
    schema: dict[str, Any] = _rewrite(raw, defs, depth=0, seen=())
    if schema.get("type") != "object":
        raise SchemaError(f"{model.__name__}: the root of a structured output must be an object")
    return schema


def _resolve(ref: str, defs: dict[str, Any], seen: tuple[str, ...]) -> tuple[Any, str]:
    name = ref.removeprefix("#/$defs/")
    if name in seen:
        raise SchemaError(f"recursive schema through {name!r} is not supported")
    if name not in defs:
        raise SchemaError(f"unknown reference {ref!r}")
    return defs[name], name


def _rewrite(node: Any, defs: dict[str, Any], *, depth: int, seen: tuple[str, ...]) -> Any:
    if depth > MAX_DEPTH * 3:  # each level of nesting is a few schema nodes deep
        raise SchemaError("schema nests deeper than the documented limit")
    if isinstance(node, list):
        return [_rewrite(n, defs, depth=depth + 1, seen=seen) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target, name = _resolve(node["$ref"], defs, seen)
        merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        return _rewrite(merged, defs, depth=depth + 1, seen=(*seen, name))
    if "allOf" in node:
        parts = node["allOf"]
        if len(parts) != 1:
            raise SchemaError("allOf with several schemas is not supported")
        merged = {**parts[0], **{k: v for k, v in node.items() if k != "allOf"}}
        return _rewrite(merged, defs, depth=depth + 1, seen=seen)
    if "oneOf" in node:
        node = {**{k: v for k, v in node.items() if k != "oneOf"}, "anyOf": node["oneOf"]}
    if isinstance(node.get("additionalProperties"), dict):
        raise SchemaError("free-form maps (dict fields) are not supported in strict schemas")
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROPPED:
            continue
        if key == "properties":
            out[key] = {
                name: _rewrite(sub, defs, depth=depth + 1, seen=seen) for name, sub in value.items()
            }
        else:
            out[key] = _rewrite(value, defs, depth=depth + 1, seen=seen)
    if out.get("type") == "object" or "properties" in out:
        out["type"] = "object"
        out.setdefault("properties", {})
        out["required"] = list(out["properties"])
        out["additionalProperties"] = False
    return out
