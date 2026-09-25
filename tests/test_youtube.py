import pytest

from moises_sync.workflow import youtube_options


def test_enables_node_when_deno_is_missing(monkeypatch):
    monkeypatch.setattr(
        "moises_sync.workflow.shutil.which", lambda name: "/bin/node" if name == "node" else None
    )
    assert youtube_options()["js_runtimes"] == {"node": {"path": "/bin/node"}}


def test_missing_runtime_has_setup_instructions(monkeypatch):
    monkeypatch.setattr("moises_sync.workflow.shutil.which", lambda _: None)
    with pytest.raises(ValueError, match="Node.js 22"):
        youtube_options()
