"""
Run the planner with the gear routes added, without editing app.py:

    uvicorn gear_server:server --reload --port 8000

The gear router answers /api/gear/*. Everything else (the planner API, tiles and the front end) falls
through to the existing app, mounted underneath. Once the two-line hook is in app.py this file is
no longer needed and `uvicorn app:app` serves everything.
"""
from fastapi import FastAPI

from app import app as planner
from gear.api import router as gear_router

server = FastAPI(title="Marswalk Planner + gear")
server.include_router(gear_router)
server.mount("/", planner)
