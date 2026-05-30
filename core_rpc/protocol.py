"""JSON-RPC 2.0 message helpers and error codes.

Pure data — no I/O, no business logic. The transport (server.py) frames
each message as one UTF-8 line of JSON (newline-delimited); this module
only builds/inspects the message dicts.

Spec: https://www.jsonrpc.org/specification
  request       {jsonrpc, method, params?, id}        — expects a response
  notification  {jsonrpc, method, params?}            — no id, no response
  response      {jsonrpc, result, id}                 — success
  error         {jsonrpc, error:{code,message,data?}, id}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

JSONRPC_VERSION = "2.0"

# Standard JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# Implementation-defined server errors live in [-32000, -32099].
HANDLER_ERROR = -32000  # a bound handler raised (business/core exception)


class RpcError(Exception):
    """Raised by handlers (or dispatch) to produce a JSON-RPC error response.

    Carries the wire `code`/`message` plus optional structured `data`. Any
    non-RpcError exception from a handler is wrapped as HANDLER_ERROR so the
    channel never dies on a stray traceback.
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass(frozen=True)
class Request:
    """A parsed inbound message. `id is None` ⇒ notification (no reply)."""

    method: str
    params: dict[str, Any]
    id: Optional[Any]

    @property
    def is_notification(self) -> bool:
        return self.id is None


def parse_request(obj: Any) -> Request:
    """Validate a decoded JSON value into a Request.

    Raises RpcError(INVALID_REQUEST) for anything malformed. `params` is
    normalized to a dict (positional arrays are not used by this codebase —
    all RPC methods take keyword params).
    """
    if not isinstance(obj, dict):
        raise RpcError(INVALID_REQUEST, "request must be a JSON object")
    if obj.get("jsonrpc") != JSONRPC_VERSION:
        raise RpcError(INVALID_REQUEST, "jsonrpc must be '2.0'")
    method = obj.get("method")
    if not isinstance(method, str) or not method:
        raise RpcError(INVALID_REQUEST, "method must be a non-empty string")
    params = obj.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise RpcError(INVALID_PARAMS, "params must be an object (keyword args)")
    # Absent id ⇒ notification. Note: an explicit null id is also treated as a
    # notification here (this codebase never sends null-id requests).
    return Request(method=method, params=params, id=obj.get("id"))


def make_response(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "error": err}


def make_notification(method: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if params:
        msg["params"] = params
    return msg
