"""Filename/metadata template engine (v0.2).

Syntax:  ${Field}  ${Field?}  ${Field:N}
- N       zero-pad width for int fields
- ?       optional (missing -> empty string; in reverse match, missing field
          is tolerated only when the anchor structure still resolves)

Greedy fields (free-text) must be separated by literal anchors; two adjacent
greedy fields without a literal between them cannot be uniquely split in
reverse matching and raise TemplateMatchError.
"""
import re
from dataclasses import dataclass


class TemplateError(ValueError):
    """Forward render failure (missing required field / unknown field)."""


class TemplateMatchError(ValueError):
    """Reverse match failure (missing required field / ambiguity)."""


# name: (reverse-match value regex, int?)
FIELDS = {
    "TrackNum":   (r"\d+(?:/\d+)?", True),
    "TrackTitle": (r".+?", False),
    "Artist":     (r".+?", False),
    "Album":      (r".+?", False),
    "Year":       (r"\d{4}", True),
    "Genre":      (r".+?", False),
    "DiscNum":    (r"\d+", True),
    "Composer":   (r".+?", False),
}
GREEDY = {"TrackTitle", "Artist", "Album", "Genre", "Composer"}

TEMPLATE_RE = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)"   # field name
    r"(\?)?"                           # optional marker
    r"(?::(\d+))?"                     # zero-pad width
    r"\}"
)


@dataclass
class Segment:
    kind: str            # "literal" | "field"
    value: str
    optional: bool = False
    width: int | None = None


def parse_template(tpl: str) -> list[Segment]:
    segs: list[Segment] = []
    pos = 0
    for m in TEMPLATE_RE.finditer(tpl):
        if m.start() > pos:
            segs.append(Segment("literal", tpl[pos:m.start()]))
        segs.append(Segment("field", m.group(1),
                            optional=bool(m.group(2)),
                            width=int(m.group(3)) if m.group(3) else None))
        pos = m.end()
    if pos < len(tpl):
        segs.append(Segment("literal", tpl[pos:]))
    return segs


def validate_template(tpl: str) -> list[str]:
    """Return error list; empty = valid."""
    errs = []
    segs = parse_template(tpl)
    if not any(s.kind == "field" for s in segs):
        errs.append("模板不包含任何字段（如 ${TrackNum}）")
    for s in segs:
        if s.kind == "field" and s.value not in FIELDS:
            errs.append(f"未知字段 {s.value}；可用：{', '.join(FIELDS)}")
    fields = [s for s in segs if s.kind == "field"]
    # 每对相邻贪婪字段之间必须有非空白字面量（与 match 的歧义规则一致）
    greedy = [s for s in fields if s.value in GREEDY]
    if len(greedy) > 1:
        for a, b in zip(greedy, greedy[1:]):
            ia, ib = segs.index(a), segs.index(b)
            between = segs[ia + 1:ib]
            if not any(s.kind == "literal" and s.value.strip() for s in between):
                errs.append("贪婪字段（标题/作者等）之间需要非空格分隔符，如 "
                            "'${TrackTitle} - ${Artist}'")
                break
    literals = [s for s in segs if s.kind == "literal" and s.value != ""]
    if len(fields) > 1 and not any(literals):
        errs.append("多个字段必须用字面量分隔（否则无法唯一解析），如 "
                    "'${TrackNum} ${TrackTitle}'")
    return errs


def _fmt_int(value, width: int | None) -> str:
    if width:
        return str(value).zfill(width)
    return str(value)


def render(tpl: str, fields: dict, total: int | None = None) -> str:
    """Forward render. Missing required field raises TemplateError.

    TrackNum renders zero-padded; the caller writes the track tag as
    `n/total` when `total` is provided (that logic lives in callers).
    """
    out = []
    for seg in parse_template(tpl):
        if seg.kind == "literal":
            out.append(seg.value)
            continue
        if seg.value not in FIELDS:
            raise TemplateError(f"未知字段 {seg.value}")
        val = fields.get(seg.value)
        if val is None or val == "":
            if seg.optional:
                out.append("")
                continue
            raise TemplateError(f"字段 {seg.value} 缺失")
        if seg.width is not None:
            out.append(str(val).zfill(seg.width))
        else:
            out.append(str(val))
    return "".join(out)


def match_filename(tpl: str, stem: str) -> dict:
    """Reverse: parse a filename stem into field values.

    TrackNum accepts `1`, `01`, `1/294` (TrackTotal derived).
    Ambiguity (adjacent greedy fields / failed required field) raises.
    """
    segs = parse_template(tpl)
    field_segs = [s for s in segs if s.kind == "field"]
    for s in field_segs:
        if s.value not in FIELDS:
            raise TemplateMatchError(f"未知字段 {s.value}")
    # 相邻两个贪婪字段之间必须有非空白字面量锚点，否则无法唯一切分
    # （纯空格分隔不算：懒惰匹配固定吞到第一个空格，切分不唯一）
    for a, b in zip(field_segs, field_segs[1:]):
        if a.value in GREEDY and b.value in GREEDY:
            ia, ib = segs.index(a), segs.index(b)
            between = segs[ia + 1:ib]
            if not any(s.kind == "literal" and s.value.strip() for s in between):
                raise TemplateMatchError(
                    f"字段 {a.value} 与 {b.value} 之间需要非空格分隔符"
                    f"（如 - · _），否则无法唯一解析")

    # Build regex: literal -> escaped (whitespace-flex), field -> group.
    # Greedy fields use possessive-ish chunks on the following anchor via
    # lazy match + overall anchor structure (regex backtracking handles it).
    pattern_parts = ["^"]
    for seg in segs:
        if seg.kind == "literal":
            pattern_parts.append(re.escape(seg.value).replace(r"\ ", r"\s*"))
        else:
            rx, _ = FIELDS[seg.value]
            pattern_parts.append(f"({rx})")
    pattern_parts.append(r"\s*$")
    pattern = "".join(pattern_parts)

    m = re.match(pattern, stem.strip())
    if not m:
        raise TemplateMatchError(f"文件名与模板不匹配：{stem!r}")

    out: dict = {}
    gi = 1
    for seg in segs:
        if seg.kind != "field":
            continue
        raw = m.group(gi)
        gi += 1
        rx, is_int = FIELDS[seg.value]
        if seg.value == "TrackNum" and "/" in raw:
            n, total = raw.split("/", 1)
            out["TrackNum"] = int(n)
            out["TrackTotal"] = int(total)
            continue
        out[seg.value] = int(raw) if is_int else raw.strip()
    # greedy fields may have swallowed separator spaces; strip
    for k in GREEDY:
        if k in out and isinstance(out[k], str):
            out[k] = out[k].strip()
    return out
