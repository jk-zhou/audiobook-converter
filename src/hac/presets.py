from .models import Preset, TranscodeSettings

PRESETS: list[Preset] = [
    Preset(
        id="audiobook_opus_32k",
        name="有声书 · Opus 低 (32k)",
        description="极小体积，纯人声/播客最佳",
        settings=TranscodeSettings(
            format="opus", codec="libopus", bitrate="32k",
            samplerate=24000, channels=1, compression_level=10,
        ),
        extension="opus", filename_suffix="_opus_32k",
    ),
    Preset(
        id="audiobook_opus_48k",
        name="有声书 · Opus 中 (48k)",
        description="平衡档，人声+轻背景音乐",
        settings=TranscodeSettings(
            format="opus", codec="libopus", bitrate="48k",
            samplerate=24000, channels=1, compression_level=10,
        ),
        extension="opus", filename_suffix="_opus_48k",
    ),
    Preset(
        id="audiobook_opus_64k",
        name="有声书 · Opus 高 (64k)",
        description="高质量档，有声剧/含背景音乐",
        settings=TranscodeSettings(
            format="opus", codec="libopus", bitrate="64k",
            samplerate=24000, channels=1, compression_level=10,
        ),
        extension="opus", filename_suffix="_opus_64k",
    ),
    Preset(
        id="audiobook_aac_lc_64k",
        name="有声书 · AAC-LC 64k (M4A/M4B)",
        description="原生 AAC 编码器，M4B 合并路线基础，无额外依赖",
        settings=TranscodeSettings(
            format="m4a", codec="aac", bitrate="64k",
            samplerate=24000, channels=1,
        ),
        extension="m4a", filename_suffix="_aac_64k",
    ),
    Preset(
        id="audiobook_aac_he_48k",
        name="有声书 · HE-AAC v1 48k",
        description="需要 libfdk_aac；单声道 HE 正确形态（SBR）",
        settings=TranscodeSettings(
            format="m4a", codec="libfdk_aac", profile="aac_he",
            bitrate="48k", channels=1,
        ),
        extension="m4a", filename_suffix="_he_48k",
        requires_encoder="libfdk_aac",
    ),
    Preset(
        id="audiobook_aac_he_v2_32k",
        name="有声书 · HE-AAC v2 32k 立体声",
        description="需要 libfdk_aac；PS 仅对立体声有效，故为双声道",
        settings=TranscodeSettings(
            format="m4a", codec="libfdk_aac", profile="aac_he_v2",
            bitrate="32k", channels=2,
        ),
        extension="m4a", filename_suffix="_he_v2_32k",
        requires_encoder="libfdk_aac",
    ),
]


def get_preset(pid: str) -> Preset | None:
    return next((p for p in PRESETS if p.id == pid), None)


def presets_payload(encoders: set[str]) -> list[dict]:
    out = []
    for p in PRESETS:
        enabled = p.effective_enabled(encoders)
        d = p.model_dump()
        d["enabled"] = enabled
        if not enabled:
            d["disabled_reason"] = f"当前 ffmpeg 缺少编码器 {p.requires_encoder}（运行 scripts/setup-ffmpeg.sh 可启用）"
        out.append(d)
    return out
