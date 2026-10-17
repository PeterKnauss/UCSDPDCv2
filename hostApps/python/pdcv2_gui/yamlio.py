"""Round-trip YAML: edit values without losing the comments the config files carry"""
from __future__ import annotations
import copy
import io
import re
from pathlib import Path
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarint import HexCapsInt, HexInt, ScalarInt

_HINT = re.compile(r"^(?P<type>[A-Za-z]+)\s+-\s+(?P<rest>.*)$", re.S)


def _make() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    y.representer.add_representer(type(None), lambda r, d: r.represent_scalar("tag:yaml.org,2002:null", "null"))
    return y

_Y = _make()


def loads(text: str):
    return _Y.load(text) or CommentedMap()

def load(path) -> CommentedMap:
    return loads(Path(path).read_text())

def dumps(data) -> str:
    buf = io.StringIO()
    _Y.dump(data, buf)
    return buf.getvalue()

def save(data, path) -> None:
    Path(path).write_text(dumps(data))

def clone(data):
    return copy.deepcopy(data)

def flow_text(value) -> str:
    """One-line YAML text of a list or mapping, for editing in a line box"""
    return dumps(value).strip().replace("\n", " ")


def comment_of(parent: CommentedMap, key) -> str:
    """Trailing comment of a key. Continuation lines are joined, a blank line ends it"""
    tok = (parent.ca.items.get(key) or [None] * 3)[2]
    if tok is None:
        return ""
    lines = []
    for raw in tok.value.split("\n"):
        text = raw.strip().lstrip("#").strip()
        if not raw.strip() and lines:
            break
        if text:
            lines.append(text)
    return " ".join(lines)

def parse_hint(comment: str) -> tuple[str, list[str] | None, str]:
    """'Str - a | b - text' -> ('Str', ['a', 'b'], 'text'). Comments without the Type - form give ('', None, comment)"""
    m = _HINT.match(comment)
    if not m:
        return "", None, comment
    head, _, tail = m["rest"].partition(" - ")
    if "|" in head and len(head) < 120:
        return m["type"], [o.strip() for o in head.split("|") if o.strip()], tail.strip()
    return m["type"], None, m["rest"].strip()


_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\0": "\\0"}
_UNESCAPE = re.compile(r"\\(n|r|t|0|\\|x[0-9a-fA-F]{2})")

def escape_text(text: str) -> str:
    """Text as typed in a line box: control characters shown as \\n \\r \\t \\xNN. A backslash that would read as an escape is doubled"""
    out = []
    for i, ch in enumerate(text):
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ch < " " or ch == "\x7f":
            out.append(f"\\x{ord(ch):02x}")
        elif ch == "\\" and text[i + 1:i + 2] and (text[i + 1] in "nrt0x\\" or text[i + 1] < " " or text[i + 1] == "\x7f"):
            out.append("\\\\")
        else:
            out.append(ch)
    return "".join(out)

def unescape_text(text: str) -> str:
    """Inverse of escape_text. Backslashes that start no known escape stay as they are"""
    table = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "\\": "\\"}
    return _UNESCAPE.sub(lambda m: table[m[1]] if m[1] in table else chr(int(m[1][1:], 16)), text)

def is_hex(value) -> bool:
    return isinstance(value, (HexInt, HexCapsInt))

def coerce_like(old, new):
    """Gives new the YAML flavour of old: hex stays hex, quoted text stays quoted"""
    if isinstance(new, bool) or old is None:
        return new
    if is_hex(old) and isinstance(new, int):
        return HexCapsInt(new, width=max(len(f"{new:X}"), 1))
    if isinstance(old, str) and type(old) is not str and isinstance(new, str):
        return type(old)(new)
    if isinstance(old, ScalarInt) and isinstance(new, int):
        return int(new)
    return new

def walk(node, path: tuple = ()):
    """Yields (path, value) of every scalar or list in a nested mapping"""
    for k, v in node.items():
        if isinstance(v, CommentedMap):
            yield from walk(v, path + (k,))
        else:
            yield path + (k,), v

def resolve_key(node, seg: str):
    """The real key of node whose text is seg (keys like 1 are ints in the file)"""
    for k in node:
        if str(k) == str(seg):
            return k
    raise KeyError(seg)

def get_in(node, path):
    for p in path:
        node = node[p]
    return node

def path_str(path) -> str:
    return ".".join(str(p) for p in path)

def parse_path(node, text: str) -> tuple:
    """Dotted text back to a tuple of real keys. Raises KeyError when the path is not in node"""
    out = []
    for seg in text.split("."):
        k = resolve_key(node, seg)
        out.append(k)
        node = node[k]
    return tuple(out)
