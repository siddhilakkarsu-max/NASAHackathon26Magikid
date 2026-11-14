"""
Kept so old commands keep working:

    uvicorn gear_server:server --reload --port 8000

The main app now includes the gear router, so `uvicorn app:app` serves everything (the planner API,
/api/gear/*, tiles and the front end). `server` is simply that same app.
"""
from app import app as server  # noqa: F401
