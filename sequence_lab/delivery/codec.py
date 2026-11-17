import hashlib
import json
from fractions import Fraction
from math import gcd


class CodecError(ValueError):
    pass


def _pack(value):
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", value]
    if type(value) is str:
        return ["str", value]
    if isinstance(value, Fraction):
        return ["fraction", value.numerator, value.denominator]
    if type(value) in (tuple, list):
        return ["tuple" if type(value) is tuple else "list",
                [_pack(x) for x in value]]
    if type(value) is dict and all(type(k) is str for k in value):
        return ["dict", [[k, _pack(value[k])] for k in sorted(value)]]
    raise CodecError("unsupported value type")


def _unpack(node):
    if type(node) is not list or not node or type(node[0]) is not str:
        raise CodecError("invalid tagged value")
    tag = node[0]
    if tag == "null" and len(node) == 1:
        return None
    scalar = {"bool": bool, "int": int, "str": str}
    if tag in scalar and len(node) == 2 and type(node[1]) is scalar[tag]:
        return node[1]
    if tag == "fraction" and len(node) == 3:
        a, b = node[1:]
        if type(a) is int and type(b) is int and b > 0 and gcd(a, b) == 1:
            return Fraction(a, b)
    if tag in ("list", "tuple") and len(node) == 2 and type(node[1]) is list:
        items = [_unpack(x) for x in node[1]]
        return tuple(items) if tag == "tuple" else items
    if tag == "dict" and len(node) == 2 and type(node[1]) is list:
        result = {}
        previous = None
        for pair in node[1]:
            if type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str:
                raise CodecError("invalid dictionary entry")
            key, value = pair
            if previous is not None and key <= previous:
                raise CodecError("unordered or duplicate dictionary key")
            previous = key
            result[key] = _unpack(value)
        return result
    raise CodecError("unknown tag or incomplete value")


def encode_value(value):
    return json.dumps({"version": 1, "value": _pack(value)},
                      ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def decode_value(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CodecError("duplicate JSON key")
            result[key] = value
        return result
    try:
        envelope = json.loads(text, object_pairs_hook=pairs)
        if (type(envelope) is not dict or set(envelope) != {"version", "value"}
                or type(envelope["version"]) is not int or envelope["version"] != 1):
            raise CodecError("unsupported encoding envelope")
        return _unpack(envelope["value"])
    except (ValueError, TypeError, RecursionError) as exc:
        raise CodecError(str(exc)) from exc


def content_digest(value):
    return hashlib.sha256(encode_value(value).encode("utf-8")).hexdigest()
