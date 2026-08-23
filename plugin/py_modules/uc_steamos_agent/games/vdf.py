"""Minimal parser for Valve's VDF (KeyValues) text format.

Just enough to read Steam's localconfig.vdf and appmanifest_*.acf files --
quoted-key/quoted-value pairs and nested {} blocks. No comments or
type-annotated values, since Steam's own generated files don't use those.
Deliberately stdlib-only: no pip dependency for something this small.
"""


def parse(text: str) -> dict:
    tokens = _tokenize(text)
    result, _ = _parse_block(tokens, 0)
    return result


def _tokenize(text: str) -> list[str]:
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c in "{}":
            tokens.append(c)
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            tokens.append("".join(buf))
            i = j + 1
            continue
        i += 1  # skip anything unexpected rather than fail the whole parse
    return tokens


def _parse_block(tokens: list[str], pos: int) -> tuple[dict, int]:
    result: dict = {}
    while pos < len(tokens):
        token = tokens[pos]
        if token == "}":
            return result, pos + 1
        key = token
        pos += 1
        if pos >= len(tokens):
            break
        next_token = tokens[pos]
        if next_token == "{":
            value, pos = _parse_block(tokens, pos + 1)
        else:
            value = next_token
            pos += 1
        result[key] = value
    return result, pos
