from app.providers.tencent.vod.video_generation import (
    _build_file_infos_from_map,
    _parse_video_model_name_version,
    is_tencentvod_video_model,
)
from app.data.tencentvod_templates import TENCENTVOD_TEMPLATES


def test_minimax_h3_is_routed_to_hailuo_h3():
    assert is_tencentvod_video_model("MiniMax-H3") is True
    assert is_tencentvod_video_model("minimax-h3") is True
    assert _parse_video_model_name_version("MiniMax-H3") == ("Hailuo", "H3")

    template = next(item for item in TENCENTVOD_TEMPLATES if item["name"] == "MiniMax-H3")
    assert template["support_image"] is True
    assert template["support_audio"] is True
    assert template["support_video"] is True


def test_minimax_h3_supports_at_variables_for_image_audio_and_video_references():
    media = {
        "图片1": {"type": "image", "url": "https://example.com/1.png", "role": ""},
        "图片2": {"type": "image", "url": "https://example.com/2.png", "role": ""},
        "音频1": {"type": "audio", "url": "https://example.com/1.mp3", "role": ""},
        "音频2": {"type": "audio", "url": "https://example.com/2.mp3", "role": ""},
        "视频1": {"type": "video", "url": "https://example.com/1.mp4", "role": ""},
        "视频2": {"type": "video", "url": "https://example.com/2.mp4", "role": ""},
    }
    original_prompt = "参考@图片1、@图片2，配合@音频1、@音频2，并使用@视频1、@视频2的动作"

    file_infos, last_frame_url, prompt = _build_file_infos_from_map(
        media,
        "Hailuo",
        original_prompt,
    )

    assert last_frame_url == ""
    assert prompt == original_prompt
    assert file_infos == [
        {"Type": "Url", "Category": "Image", "Url": "https://example.com/1.png", "ObjectId": "图片1", "Usage": "Reference"},
        {"Type": "Url", "Category": "Image", "Url": "https://example.com/2.png", "ObjectId": "图片2", "Usage": "Reference"},
        {"Type": "Url", "Category": "Audio", "Url": "https://example.com/1.mp3", "ObjectId": "音频1", "Usage": "Reference"},
        {"Type": "Url", "Category": "Audio", "Url": "https://example.com/2.mp3", "ObjectId": "音频2", "Usage": "Reference"},
        {"Type": "Url", "Category": "Video", "Url": "https://example.com/1.mp4", "ObjectId": "视频1", "Usage": "Reference"},
        {"Type": "Url", "Category": "Video", "Url": "https://example.com/2.mp4", "ObjectId": "视频2", "Usage": "Reference"},
    ]


def test_minimax_h3_at_variable_requires_an_exact_file_id_match():
    media = {
        "图片1": {"type": "image", "url": "https://example.com/1.png", "role": ""},
        "图片10": {"type": "image", "url": "https://example.com/10.png", "role": ""},
    }

    file_infos, _, _ = _build_file_infos_from_map(media, "Hailuo", "仅使用@图片10")

    by_url = {item["Url"]: item for item in file_infos}
    assert "Usage" not in by_url["https://example.com/1.png"]
    assert by_url["https://example.com/10.png"]["ObjectId"] == "图片2"
    assert by_url["https://example.com/10.png"]["Usage"] == "Reference"


def test_minimax_h3_converts_common_brace_variables_to_hailuo_at_variables():
    media = {
        "video_1": {"type": "video", "url": "https://example.com/pov.mp4", "role": ""},
        "audio_1": {"type": "audio", "url": "https://example.com/music.mp3", "role": ""},
        "apple_1": {"type": "image", "url": "https://example.com/apple.png", "role": ""},
        "tea_1": {"type": "image", "url": "https://example.com/tea.png", "role": ""},
    }
    original_prompt = (
        "全程使用{{video_1}}的第一视角构图，全程使用{{audio_1}}作为背景音乐。"
        "首帧为{{apple_1}}；你将{{tea_1}}中的果茶举到镜头前，尾帧定格为{{tea_1}}。"
    )

    file_infos, last_frame_url, prompt = _build_file_infos_from_map(
        media, "Hailuo", original_prompt
    )

    assert last_frame_url == ""
    assert prompt == (
        "全程使用@视频1的第一视角构图，全程使用@音频1作为背景音乐。"
        "首帧为@图片1；你将@图片2中的果茶举到镜头前，尾帧定格为@图片2。"
    )
    assert {item["ObjectId"] for item in file_infos} == {
        "视频1", "音频1", "图片1", "图片2"
    }
    assert all(item["Usage"] == "Reference" for item in file_infos)
