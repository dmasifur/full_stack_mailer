"""
Inline image upload.

The endpoint's job is to refuse anything that is not an image before it reaches
storage, and to produce a URL a recipient's mail client can fetch without
credentials. Both are tested here; the R2 call itself is stubbed.
"""

from __future__ import annotations

import pytest

import server.api.assets as assets_api
from server.api.assets import MAX_ASSET_BYTES, _sniff
from server.services.asset_storage import AssetStorageNotConfiguredError, upload_asset

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32


@pytest.fixture
def stub_storage(monkeypatch):
    """Capture what would have been written to R2."""
    calls: list[dict[str, object]] = []

    def _upload(*, image_bytes: bytes, content_type: str) -> str:
        calls.append({"bytes": image_bytes, "content_type": content_type})
        return f"https://cdn.example.com/assets/stub.{content_type.split('/')[1]}"

    monkeypatch.setattr(assets_api, "upload_asset", _upload)
    return calls


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (GIF, "image/gif"),
        (WEBP, "image/webp"),
        (b"GIF87a" + b"\x00" * 32, "image/gif"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", None),
        (b"%PDF-1.7\n", None),
        (b"", None),
        (b"RIFF\x00\x00\x00\x00WAVE", None),
    ],
)
def test_sniff_identifies_by_magic_bytes(data, expected):
    assert _sniff(data) == expected


def test_upload_returns_public_url(client, stub_storage):
    response = client.post("/assets", files={"file": ("shot.png", PNG, "image/png")})

    assert response.status_code == 201
    assert response.json() == {"url": "https://cdn.example.com/assets/stub.png"}
    assert stub_storage[0]["content_type"] == "image/png"


def test_content_type_is_ignored_in_favour_of_the_bytes(client, stub_storage):
    """A caller claiming PNG while sending JPEG gets stored as what it is."""
    response = client.post("/assets", files={"file": ("lie.png", JPEG, "image/png")})

    assert response.status_code == 201
    assert stub_storage[0]["content_type"] == "image/jpeg"


def test_extension_alone_does_not_admit_a_non_image(client, stub_storage):
    response = client.post(
        "/assets",
        files={"file": ("payload.png", b"<script>alert(1)</script>", "image/png")},
    )

    assert response.status_code == 400
    assert "Unsupported image format" in response.json()["detail"]
    assert stub_storage == []


def test_empty_file_is_rejected(client, stub_storage):
    response = client.post("/assets", files={"file": ("empty.png", b"", "image/png")})

    assert response.status_code == 400
    assert stub_storage == []


def test_oversized_image_is_rejected(client, stub_storage):
    oversized = PNG + b"\x00" * MAX_ASSET_BYTES

    response = client.post(
        "/assets", files={"file": ("big.png", oversized, "image/png")}
    )

    assert response.status_code == 413
    assert stub_storage == []


def test_unconfigured_public_url_returns_503(client, monkeypatch):
    def _raise(**_kwargs: object) -> str:
        raise AssetStorageNotConfiguredError("no public base url")

    monkeypatch.setattr(assets_api, "upload_asset", _raise)

    response = client.post("/assets", files={"file": ("shot.png", PNG, "image/png")})

    assert response.status_code == 503
    assert "R2_PUBLIC_BASE_URL" in response.json()["detail"]


def test_upload_requires_authentication(anonymous_client):
    response = anonymous_client.post(
        "/assets", files={"file": ("shot.png", PNG, "image/png")}
    )

    assert response.status_code == 401


def test_storage_refuses_to_upload_without_a_public_url(monkeypatch):
    """
    An object stored with no way to address it is worse than no object: the
    campaign would send with an <img src> nobody can resolve.
    """
    import server.services.asset_storage as asset_storage

    monkeypatch.setattr(asset_storage.settings, "R2_PUBLIC_BASE_URL", "")

    with pytest.raises(AssetStorageNotConfiguredError):
        upload_asset(image_bytes=PNG, content_type="image/png")


def test_storage_builds_url_from_base_and_key(monkeypatch):
    import server.services.asset_storage as asset_storage

    stored: dict[str, object] = {}

    class _Client:
        def put_object(self, **kwargs: object) -> None:
            stored.update(kwargs)

    monkeypatch.setattr(
        asset_storage.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com"
    )
    monkeypatch.setattr(asset_storage, "get_client", lambda: _Client())

    url = upload_asset(image_bytes=PNG, content_type="image/png")

    assert url.startswith("https://cdn.example.com/assets/")
    assert url.endswith(".png")
    assert url == f"https://cdn.example.com/{stored['Key']}"
    assert stored["ContentType"] == "image/png"
    # Immutable: keys are UUIDs and objects are never rewritten.
    assert "immutable" in str(stored["CacheControl"])
