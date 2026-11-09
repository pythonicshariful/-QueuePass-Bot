"""Unit and integration tests for QueuePass Bot."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from queuebot.config import DEFAULT_CONFIG, get_default_config, load_config, save_config
from queuebot.dashboard import create_app
from queuebot.discord_notify import build_pass_embed_payload, send_discord_pass_webhook
from queuebot.engine import QueuePassEngine
from queuebot.linkparse import parse_waiting_link, validate_queue_host
from queuebot.proxies import assign_proxies_for_sessions, parse_proxy, parse_proxy_list
from queuebot.queue_monitor import (
    extract_queueit_token,
    is_pass_url,
    parse_queue_page,
    select_best_session,
)
from queuebot.storage import load_results_history, read_last_pass, record_pass_result


# ---------------------------------------------------------------------------
# 1. linkparse tests
# ---------------------------------------------------------------------------


def test_linkparse_psv_per_match_link() -> None:
    url = (
        "https://psveindhoven.queue-it.net/"
        "?c=psveindhoven&e=psveventq261026"
        "&t=https%3A%2F%2Fticketshop.psv.nl%2F&cid=nl-NL"
    )
    parsed = parse_waiting_link(url)
    assert parsed.c == "psveindhoven"
    assert parsed.e == "psveventq261026"
    assert parsed.t == "https://ticketshop.psv.nl/"
    assert parsed.cid == "nl-NL"
    assert parsed.host == "psveindhoven.queue-it.net"
    assert parsed.timezone_id == "Europe/Amsterdam"


def test_linkparse_liverpool_safety_net_link() -> None:
    url = (
        "https://liverpoolfc.queue-it.net/"
        "?c=liverpoolfc&e=e_allticketssafetynet"
        "&t=https%3A%2F%2Fticketing.liverpoolfc.com%2Ftickets%2F&cid=en-GB"
    )
    parsed = parse_waiting_link(url)
    assert parsed.c == "liverpoolfc"
    assert parsed.e == "e_allticketssafetynet"
    assert parsed.t == "https://ticketing.liverpoolfc.com/tickets/"
    assert parsed.cid == "en-GB"
    assert parsed.host == "liverpoolfc.queue-it.net"
    assert parsed.timezone_id == "Europe/London"


def test_linkparse_rejects_non_queueit_host() -> None:
    assert validate_queue_host("psveindhoven.queue-it.net") is True
    assert validate_queue_host("liverpoolfc.queue-it.net") is True
    assert validate_queue_host("ticketshop.psv.nl") is False
    with pytest.raises(ValueError, match="Invalid Queue-it host"):
        parse_waiting_link("https://ticketshop.psv.nl/?c=psveindhoven&e=psveventq261026")


# ---------------------------------------------------------------------------
# 2. queue_monitor tests (real observed PSV fixtures + 10-min entry warning)
# ---------------------------------------------------------------------------


def test_queue_monitor_fixture_sale_start_dutch() -> None:
    fixture_text = """
    U bevindt zich nu in de wachtrij voor PSV Ticketshop.
    Uw rijnummer: 8969
    Aantal gebruikers voor u: 8.949
    Verwachte wachttijd: meer dan een uur
    Wanneer u aan de beurt bent, hebt u 10 minuten om de website te betreden.
    """
    stats = parse_queue_page(
        fixture_text,
        current_url="https://psveindhoven.queue-it.net/?c=psveindhoven&e=psveventq261026",
    )
    assert stats.state == "in-queue"
    assert stats.queue_number == 8969
    assert stats.people_ahead == 8949
    assert stats.estimated_wait == "meer dan een uur"


def test_queue_monitor_fixture_after_12_minutes() -> None:
    fixture_text = """
    Je rijnummer: 8969
    Aantal mensen voor je: 6.471
    Verwachte wachttijd: ~37 min
    Voortgang: 28%
    You have 10 minutes to enter the website once your turn arrives.
    """
    stats = parse_queue_page(
        fixture_text,
        current_url="https://psveindhoven.queue-it.net/?c=psveindhoven&e=psveventq261026",
    )
    assert stats.state == "in-queue"
    assert stats.queue_number == 8969
    assert stats.people_ahead == 6471
    assert stats.estimated_wait == "~37 min"
    assert stats.progress == 28


def test_queue_monitor_fixture_6007_and_152_tickets() -> None:
    fixture_text = """
    Your queue number is: 6007
    Number of users in line ahead of you: 4,210
    152 tickets available
    Please note: you have 10 minutes to enter when it is your turn.
    """
    stats = parse_queue_page(fixture_text)
    assert stats.state == "in-queue"
    assert stats.queue_number == 6007
    assert stats.people_ahead == 4210
    assert stats.tickets_available == 152
    # Must NOT parse "10 minutes to enter" as estimated wait time
    assert stats.estimated_wait is None


def test_queue_monitor_fixture_1167_tickets_max_4() -> None:
    fixture_text = """
    Queue number: 3102
    1,167 tickets available, max 4 per transaction.
    You have 10 minutes to enter.
    """
    stats = parse_queue_page(fixture_text)
    assert stats.queue_number == 3102
    assert stats.tickets_available == 1167
    assert stats.max_per_transaction == 4
    # Confirm 10-minute entry window text is NOT parsed as wait time
    assert stats.estimated_wait is None


def test_queue_monitor_entry_window_never_parsed_as_wait_time() -> None:
    text_en = "Welcome to the queue. Queue number: 500. You have 10 minutes to enter the website."
    stats_en = parse_queue_page(text_en)
    assert stats_en.queue_number == 500
    assert stats_en.estimated_wait is None

    text_nl = "Welkom. Uw wachtrijnummer: 500. U hebt 10 minuten om de website te betreden."
    stats_nl = parse_queue_page(text_nl)
    assert stats_nl.queue_number == 500
    assert stats_nl.estimated_wait is None


def test_select_best_session() -> None:
    sessions = [
        {"session_id": 1, "state": "in-queue", "people_ahead": 8949, "queue_number": 8969},
        {"session_id": 2, "state": "in-queue", "people_ahead": 1204, "queue_number": 1250},
        {"session_id": 3, "state": "in-queue", "people_ahead": 6471, "queue_number": 6500},
    ]
    best = select_best_session(sessions)
    assert best is not None
    assert best["session_id"] == 2


# ---------------------------------------------------------------------------
# 3. Pass detection tests
# ---------------------------------------------------------------------------


def test_pass_detection_rules() -> None:
    fake_token = (
        "e_psveventq261026~ts_1730000000~ce_true"
        "~q_00000000-1111-2222-3333-444444444444~rt_queue"
        "~h_0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    )

    # 1. URL on queue-it.net -> NOT passed (even if queueittoken is in query)
    queueit_url = f"https://psveindhoven.queue-it.net/?c=psveindhoven&e=psveventq261026&queueittoken={fake_token}"
    assert is_pass_url(queueit_url) is False

    # 2. URL on target domain WITHOUT token -> NOT passed
    target_no_token = "https://ticketshop.psv.nl/nl-NL/events"
    assert is_pass_url(target_no_token) is False

    # 3. URL on target domain WITH queueittoken -> PASSED
    target_with_token = f"https://ticketshop.psv.nl/?queueittoken={fake_token}"
    assert is_pass_url(target_with_token) is True
    assert extract_queueit_token(target_with_token) == fake_token

    stats = parse_queue_page("Welcome to PSV Ticketshop", current_url=target_with_token)
    assert stats.state == "passed"
    assert stats.pass_url == target_with_token


# ---------------------------------------------------------------------------
# 4. Proxy parsing and rotation tests
# ---------------------------------------------------------------------------


def test_proxies_all_four_formats_and_rotation() -> None:
    raw_lines = [
        "198.51.100.1:8001",
        "198.51.100.2:8002:userA:passA",
        "userB:passB@198.51.100.3:8003",
        "http://userC:passC@198.51.100.4:8004",
    ]
    parsed = parse_proxy_list(raw_lines)
    assert len(parsed) == 4

    assert parsed[0].server == "http://198.51.100.1:8001"
    assert parsed[0].username is None
    assert parsed[0].masked == "198.51.100.1:8001"

    assert parsed[1].server == "http://198.51.100.2:8002"
    assert parsed[1].username == "userA"
    assert parsed[1].password == "passA"
    assert parsed[1].masked == "userA:***@198.51.100.2:8002"

    assert parsed[2].server == "http://198.51.100.3:8003"
    assert parsed[2].username == "userB"
    assert parsed[2].password == "passB"
    assert parsed[2].masked == "userB:***@198.51.100.3:8003"

    assert parsed[3].server == "http://198.51.100.4:8004"
    assert parsed[3].username == "userC"
    assert parsed[3].password == "passC"
    assert parsed[3].masked == "userC:***@198.51.100.4:8004"

    # Rotation across 6 sessions wraps around cleanly
    assigned = assign_proxies_for_sessions(parsed, num_sessions=6, allow_no_proxy=False)
    assert [p.host if p else None for p in assigned] == [
        "198.51.100.1",
        "198.51.100.2",
        "198.51.100.3",
        "198.51.100.4",
        "198.51.100.1",
        "198.51.100.2",
    ]

    # Empty proxy list behavior
    assert assign_proxies_for_sessions([], num_sessions=3, allow_no_proxy=True) == [
        None,
        None,
        None,
    ]
    with pytest.raises(ValueError, match="allow_no_proxy"):
        assign_proxies_for_sessions([], num_sessions=3, allow_no_proxy=False)


# ---------------------------------------------------------------------------
# 5. Discord webhook embed builder & mocked sender test
# ---------------------------------------------------------------------------


def test_discord_notify_payload_and_mocked_post() -> None:
    fake_link = "https://ticketshop.psv.nl/?queueittoken=e_test~ts_1700000000~ce_true~q_1234~rt_queue~h_abcd"
    payload = build_pass_embed_payload(
        task_id="00000000-1111-2222-3333-444444444444",
        platform="PSV",
        task_label="PSV Matchday",
        queue_host="psveindhoven.queue-it.net",
        session_id=3,
        queue_number=6007,
        best_ahead=0,
        time_in_queue=145,
        pass_link=fake_link,
    )

    assert "embeds" in payload
    embed = payload["embeds"][0]
    assert embed["author"]["name"] == "Task Update"
    assert embed["title"] == "PSV Matchday Successfully passed Queue (psveindhoven.queue-it.net)!"
    field_map = {f["name"]: f["value"] for f in embed["fields"]}
    assert field_map["Identifier"] == "`00000000-1111-2222-3333-444444444444`"
    assert field_map["Platform"] == "PSV"
    assert field_map["Mode"] == "safe"
    assert field_map["Session"] == "#3"
    assert field_map["Queue Number"] == "6007"
    assert field_map["Best Ahead"] == "0"
    assert field_map["Time In Queue"] == "2m 25s"
    assert fake_link in field_map["Direct Pass Link"]

    with patch("queuebot.discord_notify.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_post.return_value = mock_resp

        ok = send_discord_pass_webhook(
            "https://discord.com/api/webhooks/000000/PLACEHOLDER_WEBHOOK",
            payload,
        )
        assert ok is True
        mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Config defaults + save/load round-trip test
# ---------------------------------------------------------------------------


def test_config_defaults_and_round_trip(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"

    # Defaults when file does not exist yet
    defaults = load_config(cfg_file)
    assert defaults["platform"] == "PSV"
    assert defaults["sessions"] == 5
    assert defaults["headless"] is True
    assert defaults["allow_no_proxy"] is True
    assert defaults["poll_interval_sec"] == 5
    assert defaults["hold_minutes_after_pass"] == 10
    assert defaults["stop_others_minutes_after_pass"] == 2
    assert defaults["dashboard_port"] == 5055

    # Modify and save
    updated = dict(defaults)
    updated["platform"] = "Liverpool"
    updated["sessions"] = 12
    updated["headless"] = False
    updated["proxies"] = ["192.0.2.1:8080", "192.0.2.2:8080:user:pass"]
    save_config(updated, cfg_file)

    reloaded = load_config(cfg_file)
    assert reloaded["platform"] == "Liverpool"
    assert reloaded["sessions"] == 12
    assert reloaded["headless"] is False
    assert reloaded["proxies"] == ["192.0.2.1:8080", "192.0.2.2:8080:user:pass"]


# ---------------------------------------------------------------------------
# 7. Storage tests (last_pass.txt + results.json)
# ---------------------------------------------------------------------------


def test_storage_writes_last_pass_and_results_history(tmp_path: Path) -> None:
    link1 = "https://ticketshop.psv.nl/?queueittoken=e_test1~h_0001"
    link2 = "https://ticketshop.psv.nl/?queueittoken=e_test2~h_0002"

    record_pass_result(
        task_id="task-1",
        platform="PSV",
        label="Match 1",
        session_id=1,
        queue_stats={"queue_number": 8969, "best_ahead": 8949},
        link=link1,
        data_dir=tmp_path,
    )
    assert read_last_pass(tmp_path) == link1

    record_pass_result(
        task_id="task-2",
        platform="PSV",
        label="Match 2",
        session_id=4,
        queue_stats={"queue_number": 120, "best_ahead": 0},
        link=link2,
        data_dir=tmp_path,
    )
    assert read_last_pass(tmp_path) == link2

    history = load_results_history(tmp_path)
    assert len(history) == 2
    assert history[0]["task_id"] == "task-1"
    assert history[0]["link"] == link1
    assert history[1]["task_id"] == "task-2"
    assert history[1]["session"] == 4
    assert history[1]["link"] == link2


# ---------------------------------------------------------------------------
# 8. Dashboard tests (Flask test client)
# ---------------------------------------------------------------------------


def test_dashboard_loads_and_status_api(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    data_dir = tmp_path / "data"
    save_config(get_default_config(), cfg_file)

    flask_app = create_app(config_path=cfg_file, data_dir=data_dir)
    client = flask_app.test_client()

    res_index = client.get("/")
    assert res_index.status_code == 200
    assert b"QueuePass Bot" in res_index.data

    res_status = client.get("/api/status")
    assert res_status.status_code == 200
    status_json = res_status.get_json()
    assert isinstance(status_json, dict)
    assert "sessions" in status_json
    assert isinstance(status_json["sessions"], list)

    # Test UI proxy validation endpoint & saving settings from UI
    res_proxies = client.post(
        "/api/validate-proxies",
        json={
            "proxies": ["198.51.100.1:8080", "198.51.100.2:8080:user:pass"],
            "sessions": 3,
            "allow_no_proxy": False,
        },
    )
    assert res_proxies.status_code == 200
    assert res_proxies.get_json()["ok"] is True
    assert len(res_proxies.get_json()["preview"]) == 3

    # Test UI link validation endpoint
    res_link = client.post(
        "/api/validate-link",
        json={
            "waiting_link": "https://psveindhoven.queue-it.net/?c=psveindhoven&e=psveventq261026&t=https%3A%2F%2Fticketshop.psv.nl%2F&cid=nl-NL"
        },
    )
    assert res_link.status_code == 200
    assert res_link.get_json()["c"] == "psveindhoven"


# ---------------------------------------------------------------------------
# 9. SIMULATED End-to-End Test (Local HTTP Server + 1 Real Headless Chromium)
# ---------------------------------------------------------------------------


class _SimulatedQueueHandler(BaseHTTPRequestHandler):
    """Tiny local HTTP server handler simulating a Queue-it waiting page and redirect.

    NOTE: This is a SIMULATED local test server — NOT a live Queue-it pass.
    """

    fake_token = (
        "e_simulatedpsv~ts_1730000000~ce_true"
        "~q_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee~rt_queue"
        "~h_fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    )

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # Silence server logs during pytest

    def do_GET(self) -> None:  # noqa: N802
        host_header = self.headers.get("Host", "127.0.0.1")
        if self.path.startswith("/shop"):
            body = (
                "<html><head><title>Simulated Ticketshop</title></head>"
                "<body><h1>Welcome to Simulated PSV Ticketshop</h1></body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Serve the simulated Queue-it waiting room with real Dutch fixture metrics,
        # which automatically redirects to /shop?queueittoken=... after 400ms.
        shop_url = f"http://{host_header}/shop?queueittoken={self.fake_token}"
        html = f"""<!DOCTYPE html>
        <html lang="nl">
        <head>
          <meta charset="utf-8" />
          <title>Queue-it Simulated Waiting Room</title>
          <script>
            setTimeout(function() {{
              window.location.href = "{shop_url}";
            }}, 400);
          </script>
        </head>
        <body>
          <h1>SIMULATED QUEUE-IT WAITING ROOM</h1>
          <p>Uw rijnummer: 8969</p>
          <p>Aantal gebruikers voor u: 8.949</p>
          <p>Verwachte wachttijd: meer dan een uur</p>
          <p>Voortgang: 28%</p>
          <p>You have 10 minutes to enter the website.</p>
        </body>
        </html>
        """.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


def test_simulated_end_to_end_single_headless_chromium_session(
    tmp_path: Path,
) -> None:
    """SIMULATED END-TO-END TEST (not a live pass):
    Starts a local HTTP server serving a fake queue page with real fixture text
    that redirects to a fake shop URL with a FAKE queueittoken, runs ONE real
    headless Chromium session against it, and asserts:
      1. The pass is detected,
      2. data/last_pass.txt and data/results.json are written,
      3. The Discord webhook embed payload is built.
    """
    server = HTTPServer(("127.0.0.1", 0), _SimulatedQueueHandler)
    port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        simulated_waiting_link = (
            f"http://127.0.0.1:{port}/queue"
            f"?c=psveindhoven&e=simulatedpsv"
            f"&t=http%3A%2F%2F127.0.0.1%3A{port}%2Fshop&cid=nl-NL"
        )
        expected_pass_url = (
            f"http://127.0.0.1:{port}/shop"
            f"?queueittoken={_SimulatedQueueHandler.fake_token}"
        )

        cfg = get_default_config()
        cfg.update(
            {
                "waiting_link": simulated_waiting_link,
                "platform": "PSV-SIMULATED",
                "task_label": "Simulated E2E Test",
                "sessions": 1,
                "proxies": [],
                "allow_no_proxy": True,
                "headless": True,
                "poll_interval_sec": 0.25,
                "hold_minutes_after_pass": 0.0,
                "stop_others_minutes_after_pass": 0.0,
                "discord_webhook_url": "",
            }
        )

        engine = QueuePassEngine(cfg, data_dir=tmp_path, allow_local=True)
        asyncio.run(engine.run_async())

        # 1. Assert pass was detected by the engine
        assert engine.pass_link == expected_pass_url
        assert engine.winning_session_id == 1

        # 2. Assert data/last_pass.txt and data/results.json were written
        assert read_last_pass(tmp_path) == expected_pass_url
        results = load_results_history(tmp_path)
        assert len(results) == 1
        assert results[0]["link"] == expected_pass_url
        assert results[0]["platform"] == "PSV-SIMULATED"
        assert results[0]["session"] == 1

        # 3. Assert Discord webhook payload was built with expected CiroAIO fields
        assert engine.last_discord_payload is not None
        embed = engine.last_discord_payload["embeds"][0]
        assert "Successfully passed Queue" in embed["title"]
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert fields["Platform"] == "PSV-SIMULATED"
        assert fields["Mode"] == "safe"
        assert fields["Session"] == "#1"
        assert expected_pass_url in fields["Direct Pass Link"]
    finally:
        server.shutdown()
        server.server_close()
