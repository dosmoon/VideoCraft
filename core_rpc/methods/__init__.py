"""RPC method bindings. Importing this package registers every handler.

Two side effects on import:
  1. each domain module's @rpc_method decorators populate registry.REGISTRY
  2. material/creation plugins self-register their MaterialType (so the
     registry-driven factory lookups in session.py resolve) — see
     load_plugins() below. Pre-alpha there is exactly one material plugin;
     add new ones there as they land.
"""

from __future__ import annotations

# Domain handler modules (order irrelevant; each self-registers).
from . import ai as ai  # noqa: F401
from . import capability as capability  # noqa: F401
from . import creation as creation  # noqa: F401
from . import env as env  # noqa: F401
from . import gpu as gpu  # noqa: F401
from . import material as material  # noqa: F401
from . import models as models  # noqa: F401
from . import project as project  # noqa: F401
from . import system as system  # noqa: F401


def load_plugins() -> None:
    """Import plugin packages so they self-register with the material registry.

    Separate from module import so tests can register handlers without pulling
    in plugin trees, and so the server can fail loudly if a plugin import breaks.
    """
    import materials.news_video  # noqa: F401  (registers the news_video type)
    import creations.clip  # noqa: F401  (registers the clip creation type)
    import creations.news_desk  # noqa: F401  (registers the news_desk creation type)
