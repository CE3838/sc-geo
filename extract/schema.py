"""Validate extraction results against extract/schema.json (standard library only).

Implements the subset of JSON Schema the file uses: type, const, enum,
properties, required, additionalProperties, items, minimum, minLength,
maxLength, anyOf and local $ref. Errors are 'path: message' strings, with
paths like units[0].name.page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"
SCHEMA: dict = json.loads(SCHEMA_PATH.read_text())
NOT_STATED = "not stated"

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _is_type(x: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(x, int) and not isinstance(x, bool)
    if t == "number":
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    return isinstance(x, _TYPES[t])


def _resolve(ref: str, root: dict) -> dict:
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def _join(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if path else key


def _check(x: Any, s: dict, path: str, root: dict, errs: list[str]) -> None:
    if "$ref" in s:
        _check(x, _resolve(s["$ref"], root), path, root, errs)
        return
    if "anyOf" in s:
        trials = []
        for sub in s["anyOf"]:
            e: list[str] = []
            _check(x, sub, path, root, e)
            if not e:
                return
            trials.append(e)
        best = min(trials, key=len)
        errs.extend(best if len(best) <= 3 else [f"{path or '$'}: matches none of the allowed forms"])
        return
    if "const" in s and x != s["const"]:
        errs.append(f"{path or '$'}: must be {s['const']!r}")
        return
    if "enum" in s and x not in s["enum"]:
        errs.append(f"{path or '$'}: {x!r} is not one of {s['enum']}")
        return
    if "type" in s:
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_is_type(x, t) for t in types):
            errs.append(f"{path or '$'}: expected {' or '.join(types)}, got {type(x).__name__}")
            return
    if isinstance(x, (int, float)) and not isinstance(x, bool) and "minimum" in s and x < s["minimum"]:
        errs.append(f"{path or '$'}: must be >= {s['minimum']}")
    if isinstance(x, str):
        if len(x) < s.get("minLength", 0):
            errs.append(f"{path or '$'}: too short")
        if "maxLength" in s and len(x) > s["maxLength"]:
            errs.append(f"{path or '$'}: longer than {s['maxLength']} characters")
    if isinstance(x, dict):
        props = s.get("properties", {})
        for key in s.get("required", []):
            if key not in x:
                errs.append(f"{_join(path, key)}: required")
        for key, val in x.items():
            if key in props:
                _check(val, props[key], _join(path, key), root, errs)
            elif s.get("additionalProperties") is False:
                errs.append(f"{_join(path, key)}: unexpected field '{key}'")
    if isinstance(x, list) and "items" in s:
        for i, item in enumerate(x):
            _check(item, s["items"], _join(path, i), root, errs)


def validate(doc: Any, schema: dict = SCHEMA) -> list[str]:
    errs: list[str] = []
    _check(doc, schema, "", schema, errs)
    return errs


def is_value(x: Any) -> bool:
    return isinstance(x, dict) and {"value", "page", "quote", "inferred"} <= x.keys()


def iter_values(doc: Any, path: str = "") -> Iterator[tuple[str, dict]]:
    """(path, value object) for every value in a result, in document order."""
    if is_value(doc):
        yield path, doc
    elif isinstance(doc, dict):
        for k, v in doc.items():
            yield from iter_values(v, _join(path, k))
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            yield from iter_values(v, _join(path, i))


def get_path(doc: Any, path: str) -> Any:
    node = doc
    for name, idx in re.findall(r"([^.\[\]]+)|\[(\d+)\]", path):
        node = node[int(idx)] if idx else node[name]
    return node
