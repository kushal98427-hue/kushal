import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nepse_ta.notify import build_message, diagnose_ntfy_secret, notify, selftest_ntfy

SCAN = {
    "meta": {"market_date": "2026-10-30", "freshness": "stale", "expected_latest_session": "2026-11-02",
             "historical_expectancy_r": -0.014},
    "master": {"top_setups": ["ABC"]},
    "stocks": [{"symbol": "ABC", "plan": {"plan_type": "breakout", "entry_low": 1, "entry_high": 2, "stop": 0.5, "target1": 3}}],
}


@pytest.fixture
def server():
    received = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, json.loads(body)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def do_GET(self):  # noqa: N802 - ntfy poll API: one JSON message per line
            topic = self.path.split("/")[1]
            lines = [json.dumps({"message": b["message"]}) for _, b in received if b.get("topic") == topic]
            self.send_response(200)
            self.end_headers()
            self.wfile.write("\n".join(lines).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", received
    srv.shutdown()


def test_message_marks_stale_and_negative_expectancy():
    title, body = build_message(SCAN, "https://example/report")
    assert "STALE" in title and "2026-10-30" in title
    assert "सिफारिस होइन" in body and "-0.014R" in body and "https://example/report" in body


def test_unconfigured_channels_are_skipped(tmp_path, monkeypatch):
    for k in ("NTFY_TOPIC", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    p = tmp_path / "scan.json"
    p.write_text(json.dumps(SCAN))
    assert all(v.startswith("skipped") for v in notify(p).values())


def test_ntfy_and_telegram_requests(tmp_path, monkeypatch, server):
    url, received = server
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("NTFY_TOPIC", "test-topic-xyz")
    monkeypatch.setenv("NTFY_SERVER", url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_API_BASE", url)
    p = tmp_path / "scan.json"
    p.write_text(json.dumps(SCAN))
    assert notify(p) == {"ntfy": "sent", "telegram": "sent"}
    (p1, b1), (p2, b2) = received
    assert b1["topic"] == "test-topic-xyz" and "ABC" in b1["message"]
    assert p2 == "/bot123:abc/sendMessage" and b2["chat_id"] == "42"


def test_failure_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("NTFY_TOPIC", "x")
    monkeypatch.setenv("NTFY_SERVER", "http://127.0.0.1:9")  # closed port
    p = tmp_path / "scan.json"
    p.write_text(json.dumps(SCAN))
    assert notify(p)["ntfy"].startswith("error")


def test_selftest_publishes_and_polls(monkeypatch, server):
    url, received = server
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    res = selftest_ntfy(url)
    assert res == {"published": True, "received_by_server": True}
    assert received[0][1]["topic"].startswith("nepse-selftest-")


def test_diagnose_never_returns_value(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "NTFY_TOPIC")
    d = diagnose_ntfy_secret()
    assert d["is_literal_text_NTFY_TOPIC"] is True
    monkeypatch.setenv("NTFY_TOPIC", " nepse-abcDEF123 \n")
    d = diagnose_ntfy_secret()
    assert d["has_leading_or_trailing_whitespace"] and d["starts_with_nepse_dash"] and d["valid_ntfy_topic_chars"]
    assert "nepse-abcDEF123" not in str(d)
