
"""Package level helpers and backward compatibility variables."""

from .config import settings

# Path to the SQLite database shared between the application and the
# printing agent.  It defaults to ``database.db`` located in this
# package directory but can be overridden with the ``DB_PATH``
# environment variable.  Other modules historically imported
# ``DB_PATH`` from ``magazyn`` so expose it here for convenience.
DB_PATH = settings.DB_PATH

# Allow ``from __init__ import DB_PATH`` when running modules as scripts.
import sys
sys.modules.setdefault("__init__", sys.modules[__name__])
