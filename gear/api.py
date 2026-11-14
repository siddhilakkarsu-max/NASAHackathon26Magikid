"""
HTTP surface for the gear system.

    GET  /api/gear/tools?format=anthropic|openai   tool definitions for the planning agent
    POST /api/gear/tools/{name}                    call a tool with its arguments as the JSON body
    POST /api/gear/kit                             the page's call: full manifest for a mission context
    GET  /api/gear/published                       the kit the planning agent last published, if any
    GET  /api/gear/catalog | /archetypes | /rules  reference data for the page

Mounting (two lines in app.py, placed BEFORE the static-files mount):
    from gear.api import router as gear_router
    app.include_router(gear_router)
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import catalog, rules as rule_mod, tools
from .context import MissionContext, archetype_public
from .sources import CONFIDENCE

router = APIRouter(prefix="/api/gear", tags=["gear"])


class KitRequest(BaseModel):
    context: MissionContext
    adjustments: Optional[tools.Adjustments] = None


def _ok(result):
    if isinstance(result, dict) and result.get("error"):
        status = 404 if result["error"] == "unknown_item" else 400
        raise HTTPException(status, result)
    return result


@router.get("/tools")
def tool_definitions(format: str = "anthropic"):
    if format not in ("anthropic", "openai"):
        raise HTTPException(400, "format must be 'anthropic' or 'openai'")
    return {"format": format, "tools": tools.tool_specs(format)}


@router.post("/tools/{name}")
def run_tool(name: str, arguments: Optional[dict] = None):
    return _ok(tools.call_tool(name, arguments or {}))


@router.post("/kit")
def kit(req: KitRequest):
    args = {"context": req.context.model_dump(exclude_none=True), "detail": "full"}
    if req.adjustments:
        args["adjustments"] = req.adjustments.model_dump()
    return _ok(tools.call_tool("recommend_gear", args))


@router.get("/published")
def published():
    """The kit the planning agent last published. manifest is null until it publishes one."""
    p = tools.PUBLISHED
    return {"manifest": p["manifest"], "published_at": p["published_at"], "note": p["note"]}


@router.get("/catalog")
def catalog_all():
    items = [i.public() for i in catalog.ITEMS.values()]
    return {"categories": [{"id": c, "label": l} for c, l in catalog.CATEGORIES], "items": items,
            "confidence": CONFIDENCE, "count": len(items)}


@router.get("/archetypes")
def archetypes():
    return {"archetypes": archetype_public()}


@router.get("/rules")
def rules():
    return tools.call_tool("list_gear_rules", {})
