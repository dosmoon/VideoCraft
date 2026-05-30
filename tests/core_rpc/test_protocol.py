"""Unit tests for the JSON-RPC 2.0 protocol helpers (pure data, no I/O)."""

from __future__ import annotations

import pytest

from core_rpc import protocol
from core_rpc.protocol import RpcError


def test_parse_request_basic():
    req = protocol.parse_request(
        {"jsonrpc": "2.0", "method": "system.ping", "params": {"a": 1}, "id": 7}
    )
    assert req.method == "system.ping"
    assert req.params == {"a": 1}
    assert req.id == 7
    assert not req.is_notification


def test_parse_request_notification_has_no_id():
    req = protocol.parse_request({"jsonrpc": "2.0", "method": "event.x"})
    assert req.id is None
    assert req.is_notification
    assert req.params == {}  # absent params normalized to {}


@pytest.mark.parametrize(
    "bad",
    [
        42,                                              # not an object
        {"method": "x", "id": 1},                        # missing jsonrpc
        {"jsonrpc": "1.0", "method": "x", "id": 1},       # wrong version
        {"jsonrpc": "2.0", "id": 1},                      # missing method
        {"jsonrpc": "2.0", "method": "", "id": 1},        # empty method
    ],
)
def test_parse_request_rejects_malformed(bad):
    with pytest.raises(RpcError) as ei:
        protocol.parse_request(bad)
    assert ei.value.code == protocol.INVALID_REQUEST


def test_parse_request_rejects_non_object_params():
    with pytest.raises(RpcError) as ei:
        protocol.parse_request(
            {"jsonrpc": "2.0", "method": "x", "params": [1, 2], "id": 1}
        )
    assert ei.value.code == protocol.INVALID_PARAMS


def test_make_response_shape():
    assert protocol.make_response(3, {"v": 1}) == {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {"v": 1},
    }


def test_make_error_includes_data_only_when_present():
    assert "data" not in protocol.make_error(1, -32000, "boom")
    err = protocol.make_error(1, -32000, "boom", {"detail": 9})
    assert err["error"]["data"] == {"detail": 9}


def test_make_notification_omits_empty_params():
    assert protocol.make_notification("event.x") == {
        "jsonrpc": "2.0",
        "method": "event.x",
    }
    assert protocol.make_notification("event.x", {"a": 1})["params"] == {"a": 1}
