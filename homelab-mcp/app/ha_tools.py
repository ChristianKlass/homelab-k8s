"""Home Assistant MCP tools — full control via REST API."""

import json
import os

import httpx

HA_URL = os.environ.get("HA_URL", "http://10.0.0.2:8123")
HA_TOKEN = os.environ.get("HA_TOKEN", "")


def _headers():
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


def _client():
    return httpx.AsyncClient(base_url=HA_URL, headers=_headers(), timeout=30)


def register(mcp):
    @mcp.tool()
    async def ha_get_entities(domain: str = "") -> str:
        """List all Home Assistant entities. Optionally filter by domain (e.g. 'light', 'switch', 'sensor')."""
        async with _client() as c:
            r = await c.get("/api/states")
            r.raise_for_status()
            entities = r.json()
            if domain:
                entities = [e for e in entities if e["entity_id"].startswith(f"{domain}.")]
            return json.dumps(
                [{"entity_id": e["entity_id"], "state": e["state"],
                  "friendly_name": e.get("attributes", {}).get("friendly_name", "")}
                 for e in entities],
                indent=2,
            )

    @mcp.tool()
    async def ha_get_entity_state(entity_id: str) -> str:
        """Get the full state and attributes of a specific Home Assistant entity."""
        async with _client() as c:
            r = await c.get(f"/api/states/{entity_id}")
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

    @mcp.tool()
    async def ha_call_service(domain: str, service: str, data: str = "{}") -> str:
        """Call a Home Assistant service. Examples: domain='light', service='turn_on', data='{"entity_id": "light.living_room"}'.
        The data parameter is a JSON string with service call data."""
        async with _client() as c:
            r = await c.post(f"/api/services/{domain}/{service}", content=data)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

    @mcp.tool()
    async def ha_list_services(domain: str = "") -> str:
        """List available Home Assistant services. Optionally filter by domain."""
        async with _client() as c:
            r = await c.get("/api/services")
            r.raise_for_status()
            services = r.json()
            if domain:
                services = [s for s in services if s["domain"] == domain]
            return json.dumps(services, indent=2)

    @mcp.tool()
    async def ha_render_template(template: str) -> str:
        """Render a Home Assistant Jinja2 template. Example: '{{ states(\"sensor.temperature\") }}'."""
        async with _client() as c:
            r = await c.post("/api/template", json={"template": template})
            r.raise_for_status()
            return r.text

    @mcp.tool()
    async def ha_get_history(entity_id: str, start_time: str, end_time: str = "") -> str:
        """Get state history for an entity. start_time and end_time in ISO format (e.g. '2026-03-28T00:00:00+00:00')."""
        params = {"filter_entity_id": entity_id, "minimal_response": "", "significant_changes_only": ""}
        if end_time:
            params["end_time"] = end_time
        async with _client() as c:
            r = await c.get(f"/api/history/period/{start_time}", params=params)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

    @mcp.tool()
    async def ha_get_logbook(start_time: str, entity_id: str = "", end_time: str = "") -> str:
        """Get logbook entries from a timestamp. Optionally filter by entity_id."""
        params = {}
        if entity_id:
            params["entity"] = entity_id
        if end_time:
            params["end_time"] = end_time
        async with _client() as c:
            r = await c.get(f"/api/logbook/{start_time}", params=params)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

    @mcp.tool()
    async def ha_fire_event(event_type: str, data: str = "{}") -> str:
        """Fire a custom Home Assistant event. data is a JSON string."""
        async with _client() as c:
            r = await c.post(f"/api/events/{event_type}", content=data)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

    @mcp.tool()
    async def ha_get_config() -> str:
        """Get Home Assistant configuration (version, location, components, etc.)."""
        async with _client() as c:
            r = await c.get("/api/config")
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

    @mcp.tool()
    async def ha_get_error_log() -> str:
        """Get the Home Assistant error log (recent warnings/errors via system_log)."""
        # /api/error_log was removed from the REST API in HA 2026.8;
        # system_log/list over the websocket API is the replacement.
        import websockets

        ws_url = HA_URL.replace("http", "ws", 1) + "/api/websocket"
        async with websockets.connect(ws_url, open_timeout=30) as ws:
            msg = json.loads(await ws.recv())
            if msg.get("type") == "auth_required":
                await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
                msg = json.loads(await ws.recv())
                if msg.get("type") != "auth_ok":
                    raise RuntimeError(f"HA websocket auth failed: {msg}")
            await ws.send(json.dumps({"id": 1, "type": "system_log/list"}))
            msg = json.loads(await ws.recv())
            if not msg.get("success"):
                raise RuntimeError(f"system_log/list failed: {msg}")
            entries = msg.get("result", [])
            lines = []
            for e in entries:
                ts = e.get("timestamp", 0)
                level = e.get("level", "")
                name = e.get("name", "")
                message = "; ".join(e.get("message", []))
                count = e.get("count", 1)
                suffix = f" (x{count})" if count > 1 else ""
                lines.append(f"{ts:.3f} {level} [{name}] {message}{suffix}")
            return "\n".join(lines) if lines else "No recent errors or warnings."

    @mcp.tool()
    async def ha_check_config() -> str:
        """Validate Home Assistant configuration files."""
        async with _client() as c:
            r = await c.post("/api/config/core/check_config")
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

    @mcp.tool()
    async def ha_manage_automation(automation_id: str, action: str = "get", config: str = "") -> str:
        """Manage HA automations. action: 'get', 'create_or_update', 'delete'.
        For create_or_update, provide config as a JSON string with the automation definition."""
        async with _client() as c:
            if action == "get":
                r = await c.get(f"/api/config/automation/config/{automation_id}")
            elif action == "delete":
                r = await c.delete(f"/api/config/automation/config/{automation_id}")
            elif action == "create_or_update":
                r = await c.post(f"/api/config/automation/config/{automation_id}", content=config)
            else:
                return json.dumps({"error": f"Unknown action: {action}"})
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

    @mcp.tool()
    async def ha_conversation(text: str, agent_id: str = "") -> str:
        """Process natural language via Home Assistant Assist (uses configured conversation agent like Ollama)."""
        payload = {"text": text, "language": "en"}
        if agent_id:
            payload["agent_id"] = agent_id
        async with _client() as c:
            r = await c.post("/api/conversation/process", json=payload)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)
