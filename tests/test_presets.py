from hac import encoders
from hac.presets import PRESETS, presets_payload


def test_reset_and_detect(real_ffmpeg):
    encoders.reset_cache()
    enc = encoders.detect_encoders(real_ffmpeg["ffmpeg"])
    assert "libopus" in enc
    assert "aac" in enc


def test_requires_encoder_filtering():
    from hac.presets import get_preset
    p = get_preset("audiobook_aac_he_48k")
    assert p.requires_encoder == "libfdk_aac"
    assert p.effective_enabled({"libfdk_aac"}) is True
    assert p.effective_enabled({"aac"}) is False
    # opus presets never require an encoder
    assert get_preset("audiobook_opus_48k").effective_enabled(set()) is True


def test_presets_payload_marks_disabled_reason():
    payload = presets_payload(set())  # nothing available
    by_id = {p["id"]: p for p in payload}
    assert by_id["audiobook_opus_48k"]["enabled"] is True
    assert by_id["audiobook_aac_he_48k"]["enabled"] is False
    assert "libfdk_aac" in by_id["audiobook_aac_he_48k"]["disabled_reason"]


def test_all_six_presets_defined():
    assert len(PRESETS) == 6
