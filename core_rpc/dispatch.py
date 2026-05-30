"""dispatch_message: the transport-free core of the sidecar.

Given a Context and one decoded inbound message, look up the handler, call
it, and return the response dict (or None for a notification). This function
never touches stdio or threads, so it is fully unit-testable: feed it a dict,
assert on the dict it returns.

Error policy (the channel must never die):
  - malformed message              → INVALID_REQUEST error response
  - unknown method                 → METHOD_NOT_FOUND error response
  - handler raises RpcError        → that code/message/data
  - handler raises anything else   → HANDLER_ERROR, message = str(exc)
  - any error on a notification    → swallowed (no id to respond to)
"""

from __future__ import annotations

import traceback
from typing import Any, Optional

from . import protocol
from .protocol import RpcError
from .registry import Context, get_handler


def dispatch_message(ctx: Context, obj: Any) -> Optional[dict[str, Any]]:
    """Process one decoded JSON-RPC message. Returns a response dict, or None
    when the message is a notification (or is so malformed there's no id)."""
    # Parse/validate. A bad request still needs a reply if it carried an id,
    # so try to recover the id even when validation fails.
    try:
        req = protocol.parse_request(obj)
    except RpcError as exc:
        req_id = obj.get("id") if isinstance(obj, dict) else None
        if req_id is None:
            return None
        return protocol.make_error(req_id, exc.code, exc.message, exc.data)

    handler = get_handler(req.method)
    if handler is None:
        if req.is_notification:
            return None
        return protocol.make_error(
            req.id, protocol.METHOD_NOT_FOUND, f"method not found: {req.method}"
        )

    try:
        result = handler(ctx, **req.params)
    except RpcError as exc:
        if req.is_notification:
            return None
        return protocol.make_error(req.id, exc.code, exc.message, exc.data)
    except TypeError as exc:
        # Most commonly a bad params shape (unexpected/missing kwarg). Tracebacks
        # to stderr; the client gets a clean INVALID_PARAMS.
        traceback.print_exc()
        if req.is_notification:
            return None
        return protocol.make_error(req.id, protocol.INVALID_PARAMS, str(exc))
    except Exception as exc:  # noqa: BLE001 — wrap, never crash the loop
        traceback.print_exc()
        if req.is_notification:
            return None
        return protocol.make_error(req.id, protocol.HANDLER_ERROR, str(exc))

    if req.is_notification:
        return None
    return protocol.make_response(req.id, result)
