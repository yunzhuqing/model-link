from types import SimpleNamespace

import pytest

from app.abstraction import ChatRequest, Message, MessageRole
from app.middleware.gateway_service import GatewayService, GatewayServiceError
from app.routes.files import (
    _is_seedance_2_or_newer_model,
    _is_seedance_2_or_newer_name,
    _seedance_asset_vendor,
)


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ConstraintSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _query):
        return _RowsResult(self._rows)


def _request(*file_ids):
    return ChatRequest(
        model="doubao-seedance-2.0",
        messages=[Message(role=MessageRole.USER, content="generate")],
        metadata={
            "file_id_media_map": {
                file_id: {"type": "image", "url": file_id}
                for file_id in file_ids
            }
        },
    )


@pytest.mark.asyncio
async def test_file_provider_constraint_intersects_all_asset_copies():
    rows = [
        SimpleNamespace(file_id="file-a", provider_id=1),
        SimpleNamespace(file_id="file-a", provider_id=2),
        SimpleNamespace(file_id="file-b", provider_id=2),
        SimpleNamespace(file_id="file-b", provider_id=3),
    ]

    provider_ids = await GatewayService().resolve_file_provider_constraint(
        _ConstraintSession(rows), _request("file-a", "file-b")
    )

    assert provider_ids == {2}


@pytest.mark.asyncio
async def test_file_provider_constraint_rejects_empty_intersection():
    rows = [
        SimpleNamespace(file_id="file-a", provider_id=1),
        SimpleNamespace(file_id="file-b", provider_id=2),
    ]

    with pytest.raises(GatewayServiceError, match="No provider has asset copies"):
        await GatewayService().resolve_file_provider_constraint(
            _ConstraintSession(rows), _request("file-a", "file-b")
        )


@pytest.mark.asyncio
async def test_file_provider_constraint_validates_explicit_provider():
    rows = [
        SimpleNamespace(file_id="file-a", provider_id=1),
        SimpleNamespace(file_id="file-a", provider_id=2),
    ]

    with pytest.raises(GatewayServiceError, match="Provider 3 has no asset copy"):
        await GatewayService().resolve_file_provider_constraint(
            _ConstraintSession(rows), _request("file-a"), explicit_provider_id=3
        )


@pytest.mark.asyncio
async def test_file_provider_constraint_rejects_missing_file():
    rows = [SimpleNamespace(file_id="file-a", provider_id=1)]

    with pytest.raises(GatewayServiceError, match="file-b"):
        await GatewayService().resolve_file_provider_constraint(
            _ConstraintSession(rows), _request("file-a", "file-b")
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("doubao-seedance-2.0-pro", True),
        ("seedance_2_1", True),
        ("vendor/seedance-3.0", True),
        ("seedance-1.5-pro", False),
        ("wonder-pro", False),
        (None, False),
    ],
)
def test_seedance_2_or_newer_name_detection(value, expected):
    assert _is_seedance_2_or_newer_name(value) is expected


def test_seedance_alias_can_mark_vendor_model_as_eligible():
    model = SimpleNamespace(name="vendor-video-v7", alias="seedance-2.1")
    assert _is_seedance_2_or_newer_model(model)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        (SimpleNamespace(type="volcengine", extra_config={}), "volcengine"),
        (SimpleNamespace(type="aliyun", extra_config={}), "aliyun"),
        (
            SimpleNamespace(
                type="openai", extra_config={"seedance_asset_vendor": "aliyun"}
            ),
            "aliyun",
        ),
        (SimpleNamespace(type="openai", extra_config={}), None),
    ],
)
def test_seedance_asset_vendor_mapping(provider, expected):
    assert _seedance_asset_vendor(provider) == expected


@pytest.mark.asyncio
async def test_json_upload_replicates_one_file_to_volcengine_and_aliyun(monkeypatch):
    from quart import Quart
    import app.routes.files as files_route

    data = {
        "purpose": "seedance-ref",
        "input_video": "https://cdn.example/reference",
    }
    persisted = []
    aliyun_calls = []

    async def fake_parse_json_body():
        return data

    async def fake_project_name(_auth_ctx):
        return "project"

    async def fake_create_asset(**_kwargs):
        return {"Result": {"Id": "asset-volc"}}

    async def fake_poll_asset_status(**_kwargs):
        return {"asset-volc": "Active"}

    async def fake_aliyun_import(_creds, url, media_type, _register_config):
        aliyun_calls.append((url, media_type))
        return {"MediaId": "media-aliyun"}

    async def fake_persist(record):
        persisted.append(record)
        return True

    monkeypatch.setattr(files_route, "_parse_json_body", fake_parse_json_body)
    monkeypatch.setattr(files_route, "_resolve_project_name", fake_project_name)
    monkeypatch.setattr(files_route, "upload_and_create_asset", fake_create_asset)
    monkeypatch.setattr(files_route, "poll_asset_status", fake_poll_asset_status)
    monkeypatch.setattr(files_route, "_aliyun_import", fake_aliyun_import)
    monkeypatch.setattr(files_route, "_persist_upload_record", fake_persist)
    monkeypatch.setattr(files_route, "_gen_file_id", lambda: "file-shared")

    auth_ctx = SimpleNamespace(
        api_key_raw="sk-test", api_key_group_id=1, user_id=7
    )
    creds_list = [
        {
            "provider_id": 11,
            "api_key": "volc-key",
            "ark_group_id": "ark-group",
            "ark_region": "cn-beijing",
        },
        {
            "provider_id": 22,
            "vendor": "aliyun",
            "access_key_id": "ak",
            "access_key_secret": "sk",
        },
    ]

    async with Quart(__name__).app_context():
        response = await files_route._handle_json_upload(auth_ctx, creds_list)

    body = await response.get_json()
    assert body["data"][0]["id"] == "file-shared"
    assert aliyun_calls == [("https://cdn.example/reference", "video")]
    assert {
        (row.file_id, row.provider_id, row.type, row.object_key)
        for row in persisted
    } == {
        ("file-shared", 11, "volcengine", "asset-volc"),
        ("file-shared", 22, "aliyun", "media-aliyun"),
    }


@pytest.mark.asyncio
async def test_file_provider_constraint_skips_inline_url_file_ids():
    """Custom file_ids with a real external URL must not require a DB lookup.

    Regression test: a request that references media via custom file_ids
    (e.g. "apple_1") together with real image/video/audio URLs should pass
    through the constraint check without raising "Referenced files were not
    found".
    """
    request = ChatRequest(
        model="doubao-seedance-2.0",
        messages=[Message(role=MessageRole.USER, content="generate")],
        metadata={
            "file_id_media_map": {
                "apple_1": {
                    "type": "image",
                    "url": "https://cdn.example/pic1.jpg",
                    "role": "reference_image",
                },
                "tea_1": {
                    "type": "image",
                    "url": "https://cdn.example/pic2.jpg",
                    "role": "reference_image",
                },
                "video_1": {
                    "type": "video",
                    "url": "https://cdn.example/clip.mp4",
                    "role": "reference_video",
                },
                "audio_1": {
                    "type": "audio",
                    "url": "https://cdn.example/track.mp3",
                    "role": "reference_audio",
                },
            }
        },
    )

    # An empty session (no rows) must NOT raise — the constraint is None.
    provider_ids = await GatewayService().resolve_file_provider_constraint(
        _ConstraintSession([]), request
    )
    assert provider_ids is None


@pytest.mark.asyncio
async def test_file_provider_constraint_mixed_placeholder_and_inline():
    """A placeholder file_id (uploaded, no URL) constrains routing; an
    inline-URL file_id is ignored."""
    rows = [SimpleNamespace(file_id="file-aabbccdd1122334455667788", provider_id=1)]

    request = ChatRequest(
        model="doubao-seedance-2.0",
        messages=[Message(role=MessageRole.USER, content="generate")],
        metadata={
            "file_id_media_map": {
                "file-aabbccdd1122334455667788": {
                    "type": "image",
                    "url": "file-aabbccdd1122334455667788",
                    "role": "reference_image",
                },
                "apple_1": {
                    "type": "image",
                    "url": "https://cdn.example/pic.jpg",
                    "role": "reference_image",
                },
            }
        },
    )

    provider_ids = await GatewayService().resolve_file_provider_constraint(
        _ConstraintSession(rows), request
    )
    assert provider_ids == {1}
