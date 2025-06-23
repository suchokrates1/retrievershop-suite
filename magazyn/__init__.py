
import os

# Path to the SQLite database shared between the application and the
# printing agent.  It defaults to ``database.db`` located in this
# package directory but can be overridden with the ``DB_PATH``
# environment variable.
DB_PATH = os.getenv(
    "DB_PATH", os.path.join(os.path.dirname(__file__), "database.db")
)

# Allow ``from __init__ import DB_PATH`` when running modules as scripts.
import sys
sys.modules.setdefault("__init__", sys.modules[__name__])
