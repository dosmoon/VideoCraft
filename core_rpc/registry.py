"""RPC method registry + the Context handed to every handler.

A handler is `def handler(ctx: Context, **params) -> Any`. It is registered
under a dotted name (`project.recent_list`) via the @rpc_method decorator.
Importing core_rpc.methods populates the registry as a side effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .jobs import EmitFn, JobRegistry
from .session import Session

__all__ = ["REGISTRY", "Context", "EmitFn", "Handler", "get_handler", "rpc_method"]

# name -> handler. Handlers are pure-ish: they read params + ctx and return a
# JSON-serializable result, or raise RpcError / any Exception (wrapped by
# dispatch). Registration order is irrelevant; lookup is by name.
REGISTRY: dict[str, "Handler"] = {}


@dataclass
class Context:
    """Per-process state shared by all handlers.

    session — single in-memory owner of the open Project (disk is the source
              of truth; see migration doc §2.3).
    emit    — push a JSON-RPC notification to the client.
    jobs    — long-task registry; handlers that kick off ASR/render/AI use it.
    """

    session: Session
    emit: EmitFn
    jobs: JobRegistry

    def notify(self, method: str, params: Optional[dict[str, Any]] = None) -> None:
        self.emit(method, params)


Handler = Callable[..., Any]


def rpc_method(name: str) -> Callable[[Handler], Handler]:
    """Register `fn` as the handler for the dotted RPC `name`.

    Duplicate names are a programming error (two modules claiming one method),
    so we fail loud at import time rather than silently shadowing.
    """

    def decorate(fn: Handler) -> Handler:
        if name in REGISTRY:
            raise ValueError(f"duplicate RPC method registration: {name!r}")
        REGISTRY[name] = fn
        return fn

    return decorate


def get_handler(name: str) -> Optional[Handler]:
    return REGISTRY.get(name)
