import base64
import json

import pytest

from immich_user_notify.ntfy_client import NtfyError


def test_publish_posts_json_to_root(ntfy, mocked_responses, ntfy_base):
    mocked_responses.post(f"{ntfy_base}/", status=200)
    ntfy.publish("immich-david-k", message="hi", title="T")
    req = mocked_responses.calls[0].request
    assert req.url == f"{ntfy_base}/"
    body = json.loads(req.body)
    assert body["topic"] == "immich-david-k"
    assert body["message"] == "hi"
    assert body["title"] == "T"


def test_publish_payload_and_auth(ntfy, mocked_responses, ntfy_base):
    mocked_responses.post(f"{ntfy_base}/", status=200)
    ntfy.publish(
        "t",
        message="body",
        title="Title",
        priority=4,
        tags=["camera_flash"],
        click="https://x/albums/1",
        icon="https://i",
    )
    req = mocked_responses.calls[0].request
    assert req.headers["Authorization"] == "Basic " + base64.b64encode(b"pub:secret").decode()
    assert req.headers["Content-Type"].startswith("application/json")
    body = json.loads(req.body)
    assert body["title"] == "Title"
    assert body["priority"] == 4
    assert body["tags"] == ["camera_flash"]
    assert body["click"] == "https://x/albums/1"
    assert body["icon"] == "https://i"
    assert body["message"] == "body"


def test_publish_unicode_title_and_body(ntfy, mocked_responses, ntfy_base):
    # The whole point of JSON publishing: Czech title + body survive intact.
    mocked_responses.post(f"{ntfy_base}/", status=200)
    ntfy.publish("t", message="„Trip“ Tomáš", title="Nové fotky")
    body = json.loads(mocked_responses.calls[0].request.body)
    assert body["title"] == "Nové fotky"
    assert body["message"] == "„Trip“ Tomáš"


def test_invalid_topic_raises(ntfy):
    with pytest.raises(NtfyError):
        ntfy.publish("bad topic!", message="x", title="T")


def test_publish_failure_raises(ntfy, mocked_responses, ntfy_base):
    mocked_responses.post(f"{ntfy_base}/", status=500)
    with pytest.raises(NtfyError):
        ntfy.publish("t", message="x", title="T")
