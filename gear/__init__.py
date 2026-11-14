"""
Gear system: decides which tools, resources and equipment a Mars crew should bring, and says why.

    gear.tools.call_tool(name, args)   the entry point for the planning agent
    gear.tools.tool_specs(fmt)         tool definitions to hand to the model
    gear.engine.build_manifest(ctx)    the kit for a MissionContext
    gear.api.router                    the HTTP routes

See gear/README.md.
"""
