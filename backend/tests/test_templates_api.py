"""
Template read and editor-authored save.

R2 is replaced with an in-memory store so the routes can be exercised without
network access; the storage service itself is covered by its own module.
"""

from __future__ import annotations

import pytest

import app.api.templates as templates_api
from app.api.templates import MAX_TEMPLATE_BYTES, _slug
from app.models.template import Template
from app.services.template_storage import TemplateStorageError


@pytest.fixture
def r2(monkeypatch):
    """An in-memory stand-in for the bucket, keyed exactly as R2 would be."""

    class Store:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}
            self.deleted: list[str] = []
            self.n = 0
            self.fail_fetch = False
            self.fail_delete = False

        def upload(self, *, html_bytes: bytes, original_filename: str) -> str:
            self.n += 1
            key = f"templates/key-{self.n}.html"
            self.objects[key] = html_bytes
            return key

        def fetch(self, storage_key: str) -> str:
            if self.fail_fetch:
                raise TemplateStorageError("bucket unreachable")
            return self.objects[storage_key].decode("utf-8")

        def delete(self, storage_key: str) -> None:
            if self.fail_delete:
                raise TemplateStorageError("bucket unreachable")
            self.deleted.append(storage_key)
            self.objects.pop(storage_key, None)

    store = Store()
    monkeypatch.setattr(templates_api, "upload_template", store.upload)
    monkeypatch.setattr(templates_api, "fetch_template", store.fetch)
    monkeypatch.setattr(templates_api, "delete_template", store.delete)
    return store


@pytest.fixture
def saved(client, r2):
    """A template created through the editor route, as the default user."""

    def _save(name: str = "Newsletter", html: str = "<p>Hello</p>") -> dict[str, str]:
        response = client.post("/templates/html", json={"name": name, "html": html})
        assert response.status_code == 201, response.text
        created: dict[str, str] = response.json()
        return created

    return _save


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Newsletter", "newsletter.html"),
        ("Q3 Product Update", "q3-product-update.html"),
        ("  spaced  out  ", "spaced-out.html"),
        ("!!!", "template.html"),
        ("", "template.html"),
    ],
)
def test_slug_builds_a_filename(name, expected):
    assert _slug(name) == expected


def test_create_from_html_stores_the_markup(client, r2, saved):
    template = saved(html="<h1>Launch</h1>")

    assert template["name"] == "Newsletter"
    assert template["original_filename"] == "newsletter.html"
    assert list(r2.objects.values()) == [b"<h1>Launch</h1>"]


def test_created_template_reads_back(client, saved):
    template = saved(html="<h1>Launch</h1>")

    response = client.get(f"/templates/{template['id']}/html")

    assert response.status_code == 200
    assert response.json() == {"html": "<h1>Launch</h1>"}


def test_read_html_preserves_a_full_email_document(client, saved):
    """A table-based template must survive the round trip byte for byte."""
    body = (
        "<!DOCTYPE html><html><body>"
        '<table role="presentation" width="600"><tr><td>Hi</td></tr></table>'
        "</body></html>"
    )
    template = saved(html=body)

    assert client.get(f"/templates/{template['id']}/html").json()["html"] == body


def test_read_html_is_available_to_any_authenticated_user(client, saved, bob):
    """Templates are a shared library — decision 13."""
    template = saved()
    client.login_as(bob)

    assert client.get(f"/templates/{template['id']}/html").status_code == 200


def test_read_html_requires_authentication(anonymous_client, db, alice, r2):
    template = Template(
        name="N",
        storage_key="templates/key-1.html",
        original_filename="n.html",
        uploaded_by=str(alice.id),
    )
    db.add(template)
    db.commit()

    assert anonymous_client.get(f"/templates/{template.id}/html").status_code == 401


def test_read_html_of_a_missing_template_is_404(client, r2):
    missing = "00000000-0000-0000-0000-000000000000"

    assert client.get(f"/templates/{missing}/html").status_code == 404


def test_unreachable_storage_reports_a_gateway_error(client, r2, saved):
    """Not a 500: the failure is the bucket's, and it is worth distinguishing."""
    template = saved()
    r2.fail_fetch = True

    assert client.get(f"/templates/{template['id']}/html").status_code == 502


def test_update_replaces_the_markup(client, r2, saved):
    template = saved(html="<p>v1</p>")

    response = client.put(
        f"/templates/{template['id']}/html", json={"html": "<p>v2</p>"}
    )

    assert response.status_code == 200
    assert client.get(f"/templates/{template['id']}/html").json() == {
        "html": "<p>v2</p>"
    }


def test_update_writes_a_new_key_and_removes_the_old_object(client, r2, saved):
    template = saved(html="<p>v1</p>")
    original_key = next(iter(r2.objects))

    client.put(f"/templates/{template['id']}/html", json={"html": "<p>v2</p>"})

    assert r2.deleted == [original_key]
    assert original_key not in r2.objects


def test_update_can_rename(client, r2, saved):
    template = saved(name="Old name")

    response = client.put(
        f"/templates/{template['id']}/html",
        json={"name": "New name", "html": "<p>v2</p>"},
    )

    assert response.json()["name"] == "New name"


def test_update_keeps_the_name_when_none_is_given(client, r2, saved):
    template = saved(name="Keep me")

    response = client.put(
        f"/templates/{template['id']}/html", json={"html": "<p>v2</p>"}
    )

    assert response.json()["name"] == "Keep me"


def test_only_the_uploader_can_update(client, r2, saved, bob):
    template = saved()
    client.login_as(bob)

    response = client.put(
        f"/templates/{template['id']}/html", json={"html": "<p>hijacked</p>"}
    )

    assert response.status_code == 403


def test_update_survives_a_failed_cleanup_of_the_old_object(client, r2, saved):
    """An orphaned object is cheaper than losing the user's edit."""
    template = saved(html="<p>v1</p>")
    r2.fail_delete = True

    response = client.put(
        f"/templates/{template['id']}/html", json={"html": "<p>v2</p>"}
    )

    assert response.status_code == 200
    assert client.get(f"/templates/{template['id']}/html").json() == {
        "html": "<p>v2</p>"
    }


def test_oversized_html_is_rejected_on_create(client, r2):
    response = client.post(
        "/templates/html",
        json={"name": "Huge", "html": "x" * (MAX_TEMPLATE_BYTES + 1)},
    )

    assert response.status_code == 413
    assert r2.objects == {}


def test_oversized_html_is_rejected_on_update(client, r2, saved):
    template = saved(html="<p>v1</p>")

    response = client.put(
        f"/templates/{template['id']}/html",
        json={"html": "x" * (MAX_TEMPLATE_BYTES + 1)},
    )

    assert response.status_code == 413
    assert client.get(f"/templates/{template['id']}/html").json() == {
        "html": "<p>v1</p>"
    }


def test_empty_html_is_rejected(client, r2):
    response = client.post("/templates/html", json={"name": "Empty", "html": ""})

    assert response.status_code == 422
