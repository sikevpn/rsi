"""Strict-subset YAML loader with zero third-party dependencies.

The report keeps configuration in ``gate.yaml`` / ``config/*.yaml`` but also insists on
"极轻依赖" (§5.1).  This module therefore parses the subset we actually ship, and can
optionally cross-check against PyYAML when it happens to be installed.

Supported subset
----------------
* block mappings nested by indentation (spaces only, tabs rejected)
* block sequences (``- item``), including sequences of mappings
* scalars: int, float, bool (true/false/yes/no/on/off), null (``~``/``null``/empty),
  single- or double-quoted strings
* flow sequences of scalars: ``[a, b, c]``
* full-line comments and `` #`` inline comments outside quotes

Anything outside the subset raises :class:`MiniYAMLError` rather than being guessed at.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

__all__ = ["MiniYAMLError", "loads", "load_file", "dumps_scalar"]


class MiniYAMLError(ValueError):
    """Raised when input falls outside the supported YAML subset."""


_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")


def _strip_comment(raw: str) -> str:
    """Remove a trailing ``#`` comment that is not inside quotes."""
    quote: str | None = None
    for i, ch in enumerate(raw):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i]
    return raw


def _tokenize(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        leading = line[: len(line) - len(line.lstrip())]
        if "\t" in leading:
            raise MiniYAMLError(f"line {lineno}: tabs are not allowed for indentation")
        indent = len(leading)
        out.append((indent, line.lstrip()))
    return out


def _scalar(token: str, lineno: int = 0) -> Any:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part, lineno) for part in _split_flow(inner)]
    low = token.lower()
    if low in ("", "null", "~"):
        return None
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if _INT_RE.match(token):
        return int(token)
    if _FLOAT_RE.match(token):
        return float(token)
    return token


def _split_flow(inner: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    buf: list[str] = []
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _looks_like_map_entry(text: str) -> bool:
    quote: str | None = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == ":" and (i + 1 == len(text) or text[i + 1] == " "):
            return True
    return False


def _split_key(text: str) -> tuple[str, str]:
    quote: str | None = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == ":" and (i + 1 == len(text) or text[i + 1] == " "):
            return text[:i].strip(), text[i + 1 :].strip()
    raise MiniYAMLError(f"expected 'key: value', got {text!r}")


def _parse_block(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[Any, int]:
    if lines[i][1] == "-" or lines[i][1].startswith("- "):
        return _parse_list(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_map(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while i < len(lines):
        cur_indent, content = lines[i]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise MiniYAMLError(f"unexpected indentation before {content!r}")
        if content == "-" or content.startswith("- "):
            break
        key, rest = _split_key(content)
        key = _scalar(key)
        if not isinstance(key, str):
            raise MiniYAMLError(f"mapping keys must be strings, got {key!r}")
        if rest:
            result[key] = _scalar(rest)
            i += 1
            continue
        if i + 1 < len(lines) and lines[i + 1][0] > cur_indent:
            value, i = _parse_block(lines, i + 1, lines[i + 1][0])
            result[key] = value
        else:
            result[key] = None
            i += 1
    return result, i


def _parse_list(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while i < len(lines):
        cur_indent, content = lines[i]
        if cur_indent < indent or not (content == "-" or content.startswith("- ")):
            break
        if cur_indent > indent:
            raise MiniYAMLError(f"unexpected indentation before {content!r}")
        item = content[1:].strip()
        if not item:
            if i + 1 < len(lines) and lines[i + 1][0] > cur_indent:
                value, i = _parse_block(lines, i + 1, lines[i + 1][0])
                result.append(value)
            else:
                result.append(None)
                i += 1
        elif _looks_like_map_entry(item):
            sub: list[tuple[int, str]] = [(cur_indent + 2, item)]
            i += 1
            while i < len(lines) and lines[i][0] > cur_indent:
                sub.append(lines[i])
                i += 1
            value, _ = _parse_map(sub, 0, cur_indent + 2)
            result.append(value)
        else:
            result.append(_scalar(item))
            i += 1
    return result, i


def _parse(text: str) -> Any:
    lines = _tokenize(text)
    if not lines:
        return None
    value, consumed = _parse_block(lines, 0, lines[0][0])
    if consumed != len(lines):
        raise MiniYAMLError(f"trailing content not understood: {lines[consumed][1]!r}")
    return value


def loads(text: str, engine: str = "mini") -> Any:
    """Parse ``text``.

    ``engine`` is ``"mini"`` (default, zero deps), ``"pyyaml"`` (requires PyYAML) or
    ``"auto"`` (PyYAML when importable, mini otherwise).
    """
    if engine == "pyyaml":
        import yaml  # noqa: PLC0415 - optional dependency, imported on demand

        return yaml.safe_load(text)
    if engine == "auto":
        try:
            import yaml  # noqa: PLC0415

            return yaml.safe_load(text)
        except ImportError:
            return _parse(text)
    if engine == "mini":
        return _parse(text)
    raise MiniYAMLError(f"unknown engine {engine!r}")


def load_file(path: str | Path, engine: str = "mini") -> Any:
    return loads(Path(path).read_text(encoding="utf-8"), engine=engine)


def dumps_scalar(value: Any) -> str:
    """Render a scalar the way :func:`_scalar` will read it back."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or text.lower() in {"null", "~", "true", "false", "yes", "no", "on", "off"}:
        return f'"{text}"'
    if _INT_RE.match(text) or _FLOAT_RE.match(text) or text[0] in "\"'[]#":
        return f'"{text}"'
    if " #" in text:
        return f'"{text}"'
    return text
