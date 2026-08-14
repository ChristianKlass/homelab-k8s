"""Homelab MCP Server — centralized control for Home Assistant and infrastructure."""

import logging
import os

from mcp.server.fastmcp import FastMCP

import ha_tools
import infra_tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")

PORT = int(os.environ.get("PORT", "8080"))

mcp = FastMCP("homelab", port=PORT, host="0.0.0.0")

# Register all tool modules
ha_tools.register(mcp)
infra_tools.register(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    app = mcp.streamable_http_app()

    # Remove TrustedHostMiddleware added by MCP SDK (we're behind a LoadBalancer)
    app.middleware_stack = None  # Force rebuild
    app.user_middleware = [m for m in app.user_middleware
                          if "TrustedHost" not in str(m.cls)]

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
