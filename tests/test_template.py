"""template.py: parse/render/match + TrackNum special handling."""
import pytest

from hac.template import (
    parse_template, render, match_filename, validate_template,
    TemplateError, TemplateMatchError,
)


# ---------- parse ----------

def test_parse_literal_and_fields():
    segs = parse_template("第${TrackNum:3}集 ${TrackTitle}")
    kinds = [(s.kind, s.value, s.width) for s in segs]
    assert ("literal", "第", None) in kinds
    assert ("field", "TrackNum", 3) in kinds
    assert ("field", "TrackTitle", None) in kinds


def test_parse_optional_marker():
    segs = parse_template("${Album?} - ${TrackTitle}")
    album = next(s for s in segs if s.value == "Album")
    assert album.optional is True


def test_parse_unknown_field_still_parses():
    # validation catches unknown fields; parser is structural
    segs = parse_template("${Nope}")
    assert segs[0].kind == "field"


# ---------- render ----------

def test_render_zero_pad():
    assert render("第${TrackNum:3}集", {"TrackNum": 1}) == "第001集"
    assert render("${TrackNum}", {"TrackNum": 12}) == "12"


def test_render_optional_missing_empty():
    assert render("${Album?}-${TrackTitle}", {"TrackTitle": "x"}) == "-x"


def test_render_required_missing_raises():
    with pytest.raises(TemplateError):
        render("${Album} - ${TrackTitle}", {"TrackTitle": "x"})


def test_render_unknown_field_raises():
    with pytest.raises(TemplateError):
        render("${Nope}", {})


# ---------- match ----------

def test_match_basic():
    fields = match_filename("第${TrackNum}集 ${TrackTitle}", "第1集 风起")
    assert fields["TrackNum"] == 1
    assert fields["TrackTitle"] == "风起"


def test_match_padded():
    fields = match_filename("第${TrackNum}集 ${TrackTitle}", "第01集 风起")
    assert fields["TrackNum"] == 1


def test_match_track_total():
    fields = match_filename("${TrackNum} ${TrackTitle}", "1/294 风起")
    assert fields["TrackNum"] == 1
    assert fields.get("TrackTotal") == 294


def test_match_greedy_ambiguity_raises():
    with pytest.raises(TemplateMatchError):
        match_filename("${TrackTitle} ${TrackTitle}", "a b")


def test_match_missing_required():
    with pytest.raises(TemplateMatchError):
        match_filename("第${TrackNum}集", "没有编号")


def test_match_anchor_backtrack():
    # 首尾贪婪：${TrackTitle} - 第${TrackNum}集，标题含空格仍回溯正确
    fields = match_filename("${TrackTitle} - 第${TrackNum}集", "魔高一丈 - 第2集")
    assert fields["TrackNum"] == 2
    assert fields["TrackTitle"] == "魔高一丈"


def test_match_trailing_greedy():
    # 尾部贪婪字段吃掉剩余全部（含空格）
    fields = match_filename("第${TrackNum}集 ${TrackTitle}", "第2集 魔高一丈 虹桥死战")
    assert fields["TrackNum"] == 2
    assert fields["TrackTitle"] == "魔高一丈 虹桥死战"


def test_match_year_strict():
    fields = match_filename("${Year} ${TrackTitle}", "2023 歌名")
    assert fields["Year"] == 2023


# ---------- validate ----------

def test_validate_unknown_field():
    errs = validate_template("第${Nope}集")
    assert errs and "Nope" in errs[0]


def test_validate_no_anchor_multi_fields():
    errs = validate_template("${TrackTitle}${Artist}")
    assert errs


def test_validate_ok():
    assert validate_template("第${TrackNum:3}集 ${TrackTitle}") == []
    assert validate_template("${TrackTitle}") == []   # 单字段允许
