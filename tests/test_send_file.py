"""send_file (§34 / UX-016): deliverables into the chat, with its own approval surface.

Gates: happy path via a fake FileSender (no network) · path containment against
workspace/roots · unsupported platform · missing token · as_screenshot HTML-only with an
injected renderer · and the permission split — a thread's standing send_message grant must
NEVER cover send_file.
"""

from pathlib import Path

from cogniwork.connectors.base import SendResult
from cogniwork.connectors.tools import make_send_file_tool
from cogniwork.permissions import Mode, PermissionEngine
from cogniwork.roots import RootDir
from cogniwork.secrets import SecretStore


def _secrets(tmp_path, token="xoxb-1") -> SecretStore:
    s = SecretStore(tmp_path / "secrets.json")
    if token:
        s.put("slack:default", {"bot_token": token, "enabled": True})
    return s


def _fake_sender(record: list):
    def sender(token, chat_id, thread_id, filename, data, title, comment):
        record.append(
            {
                "token": token,
                "chat_id": chat_id,
                "thread_id": thread_id,
                "filename": filename,
                "data": data,
                "title": title,
                "comment": comment,
            }
        )
        return SendResult(True, message_id="F123")

    return {"slack": sender}


def test_send_file_success_within_workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "report.pdf").write_bytes(b"%PDF-fake")
    record: list = []
    tool = make_send_file_tool(
        _secrets(tmp_path), workspace=ws, file_senders=_fake_sender(record)
    )

    out = tool("slack:C9:1700.1", "report.pdf", comment="here you go")
    assert out == {
        "ok": True,
        "file_id": "F123",
        "target": "slack:C9:1700.1",
        "filename": "report.pdf",
    }
    sent = record[0]
    assert sent["chat_id"] == "C9" and sent["thread_id"] == "1700.1"
    assert sent["data"] == b"%PDF-fake" and sent["comment"] == "here you go"


def test_send_file_rejects_paths_outside_roots(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("secret")
    tool = make_send_file_tool(
        _secrets(tmp_path), workspace=ws, file_senders=_fake_sender([])
    )

    # Absolute path outside every base, and a traversal attempt — both refused.
    assert "error" in tool("slack:C9", str(outside))
    assert "error" in tool("slack:C9", "../elsewhere.txt")


def test_send_file_roots_extend_the_reachable_set(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "data.csv").write_text("a,b\n1,2\n")
    record: list = []
    tool = make_send_file_tool(
        _secrets(tmp_path),
        workspace=ws,
        roots=[RootDir(path=shared)],
        file_senders=_fake_sender(record),
    )
    out = tool("slack:C9", str(shared / "data.csv"))
    assert out["ok"] and record[0]["filename"] == "data.csv"


def test_send_file_unsupported_platform_and_missing_token(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("x")
    tool = make_send_file_tool(
        _secrets(tmp_path), workspace=ws, file_senders=_fake_sender([])
    )
    assert "not supported" in tool("telegram:123", "a.txt")["error"]

    no_token = make_send_file_tool(
        _secrets(tmp_path / "nt", token=None),
        workspace=ws,
        file_senders=_fake_sender([]),
    )
    assert "no bot token" in no_token("slack:C9", "a.txt")["error"]


def test_send_file_screenshot_is_html_only_and_renames_to_png(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "dash.html").write_text("<h1>hi</h1>")
    (ws / "notes.md").write_text("# hi")
    record: list = []
    tool = make_send_file_tool(
        _secrets(tmp_path),
        workspace=ws,
        file_senders=_fake_sender(record),
        render_html=lambda p: b"PNG-bytes-for-" + Path(p).name.encode(),
    )

    assert (
        "only applies to .html"
        in tool("slack:C9", "notes.md", as_screenshot=True)["error"]
    )

    out = tool("slack:C9", "dash.html", as_screenshot=True)
    assert out["ok"] and out["filename"] == "dash.png"
    assert record[-1]["data"] == b"PNG-bytes-for-dash.html"


def test_thread_send_message_grant_never_covers_send_file(tmp_path):
    """The §31 mention-thread grant pre-approves send_message for its thread target — the
    SAME target on send_file must still ask (task_rules key on the tool name)."""
    engine = PermissionEngine(workspace_root=tmp_path, mode=Mode.INTERACTIVE)
    target = "slack:T1/C9:1700.1"
    engine.task_rules.setdefault("send_message", set()).add(target)

    from cogniwork.connectors.tools import make_send_file_tool, make_send_message_tool

    msg_meta = make_send_message_tool(_secrets(tmp_path)).__aisuite_tool_metadata__
    file_meta = make_send_file_tool(
        _secrets(tmp_path), workspace=tmp_path
    ).__aisuite_tool_metadata__

    allowed = engine.evaluate(
        "send_message", {"target": target, "text": "hi"}, msg_meta
    )
    assert allowed.allowed and "standing rule" in allowed.reason

    asked = engine.evaluate(
        "send_file", {"target": target, "path": "report.pdf"}, file_meta
    )
    assert not asked.allowed and asked.needs_user


def _telegram_secrets(tmp_path, token="tg-token-123") -> SecretStore:
    s = SecretStore(tmp_path / "secrets.json")
    if token:
        s.put("telegram:default", {"bot_token": token, "enabled": True})
    return s


def test_send_file_telegram_success_with_default_sender(tmp_path, monkeypatch):
    import httpx

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "bubble_sort.c").write_text("void bubble_sort() {}")

    posted: list[dict] = []

    def fake_post(url, data=None, files=None, json=None, timeout=None):
        posted.append({"url": url, "data": data, "files": files})

        class FakeResp:
            status_code = 200

            def json(self):
                return {"ok": True, "result": {"message_id": 9876}}

        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    tool = make_send_file_tool(_telegram_secrets(tmp_path), workspace=ws)
    out = tool("telegram:5506865927", "bubble_sort.c", comment="Here is your code")

    assert out == {
        "ok": True,
        "file_id": "9876",
        "target": "telegram:5506865927",
        "filename": "bubble_sort.c",
    }
    assert len(posted) == 1
    assert "sendDocument" in posted[0]["url"]
    assert posted[0]["data"]["chat_id"] == "5506865927"
    assert posted[0]["data"]["caption"] == "Here is your code"
    assert posted[0]["files"]["document"][0] == "bubble_sort.c"
    assert b"void bubble_sort" in posted[0]["files"]["document"][1]


def test_send_file_telegram_default_target_implicit(tmp_path, monkeypatch):
    import httpx

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "main.py").write_text("print('hello')")

    posted: list[dict] = []

    def fake_post(url, data=None, files=None, json=None, timeout=None):
        posted.append({"url": url, "data": data, "files": files})

        class FakeResp:
            status_code = 200

            def json(self):
                return {"ok": True, "result": {"message_id": 1122}}

        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    # Tool configured with default_target
    tool = make_send_file_tool(
        _telegram_secrets(tmp_path),
        workspace=ws,
        default_target="telegram:99999",
    )
    # Model calls send_file with ONLY the path (no target given)
    out = tool("main.py")

    assert out["ok"] is True
    assert out["target"] == "telegram:99999"
    assert out["file_id"] == "1122"
    assert posted[0]["data"]["chat_id"] == "99999"


def test_send_file_telegram_api_failure_propagates_error(tmp_path, monkeypatch):
    import httpx

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "data.csv").write_text("a,b,c")

    def fake_post(url, data=None, files=None, json=None, timeout=None):
        class FakeResp:
            status_code = 400

            def json(self):
                return {
                    "ok": False,
                    "error_code": 400,
                    "description": "Bad Request: chat not found",
                }

        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    tool = make_send_file_tool(_telegram_secrets(tmp_path), workspace=ws)
    out = tool("telegram:bad_chat", "data.csv")

    assert out == {"error": "Bad Request: chat not found"}

