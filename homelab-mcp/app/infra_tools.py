"""Infrastructure MCP tools — Proxmox and Docker live queries."""

import json
import os

import httpx

PROXMOX_TOKEN_ID = os.environ.get("PROXMOX_TOKEN_ID", "")
PROXMOX_TOKEN_SECRET = os.environ.get("PROXMOX_TOKEN_SECRET", "")

# Map each host URL to its local node name — query only local resources per host.
# Single-node homelab: everything runs on forge (10.0.0.25).
PROXMOX_NODES = {
    "https://10.0.0.25:8006": "forge",
}
PROXMOX_HOSTS = list(PROXMOX_NODES)

# Known Docker hosts (TCP API exposed). None currently expose the Docker TCP API.
DOCKER_HOSTS: dict[str, str] = {}


def _proxmox_headers():
    return {"Authorization": f"PVEAPIToken={PROXMOX_TOKEN_ID}={PROXMOX_TOKEN_SECRET}"}


def _proxmox_client():
    return httpx.AsyncClient(headers=_proxmox_headers(), verify=False, timeout=15)


def register(mcp):
    @mcp.tool()
    async def proxmox_list_vms() -> str:
        """List all VMs and LXCs across all Proxmox nodes with live status, CPU, and memory usage."""
        results = []
        errors = []
        async with _proxmox_client() as c:
            for host, node_name in PROXMOX_NODES.items():
                try:
                    for vm_type in ["qemu", "lxc"]:
                        r = await c.get(f"{host}/api2/json/nodes/{node_name}/{vm_type}")
                        r.raise_for_status()
                        for vm in r.json()["data"]:
                            mem_used = vm.get("mem", 0)
                            maxmem = vm.get("maxmem", 0)
                            # For running QEMU VMs, fetch balloon stats for accurate memory
                            if vm_type == "qemu" and vm.get("status") == "running":
                                try:
                                    sr = await c.get(f"{host}/api2/json/nodes/{node_name}/qemu/{vm['vmid']}/status/current")
                                    sr.raise_for_status()
                                    sd = sr.json()["data"]
                                    freemem = sd.get("freemem")
                                    if freemem is not None:
                                        mem_used = maxmem - freemem
                                except Exception:
                                    pass
                            results.append({
                                "node": node_name,
                                "vmid": vm["vmid"],
                                "name": vm.get("name", ""),
                                "type": vm_type,
                                "status": vm.get("status", ""),
                                "cpu_pct": round(vm.get("cpu", 0) * 100, 1),
                                "mem_used_mb": round(mem_used / 1024 / 1024),
                                "mem_max_mb": round(maxmem / 1024 / 1024),
                            })
                except Exception as e:
                    errors.append(f"{node_name} ({host}): {e}")

        # Deduplicate
        seen = set()
        deduped = []
        for vm in results:
            key = (vm["node"], vm["vmid"])
            if key not in seen:
                seen.add(key)
                deduped.append(vm)

        deduped.sort(key=lambda v: (v["node"], v["vmid"]))
        output = {"vms": deduped}
        if errors:
            output["errors"] = errors
        return json.dumps(output, indent=2)

    @mcp.tool()
    async def proxmox_vm_status(node: str, vmid: int, vm_type: str = "lxc") -> str:
        """Get detailed status of a specific VM or LXC. node: 'forge'. vm_type: 'qemu' or 'lxc'."""
        async with _proxmox_client() as c:
            for host in PROXMOX_HOSTS:
                try:
                    r = await c.get(f"{host}/api2/json/nodes/{node}/{vm_type}/{vmid}/status/current")
                    r.raise_for_status()
                    return json.dumps(r.json()["data"], indent=2)
                except httpx.HTTPStatusError:
                    continue
        return json.dumps({"error": f"VM {vmid} not found on node {node}"})

    @mcp.tool()
    async def proxmox_start_stop(node: str, vmid: int, action: str, vm_type: str = "lxc") -> str:
        """Start or stop a VM/LXC. action: 'start' or 'stop'. node: 'forge'. vm_type: 'qemu' or 'lxc'."""
        if action not in ("start", "stop"):
            return json.dumps({"error": "action must be 'start' or 'stop'"})
        async with _proxmox_client() as c:
            for host in PROXMOX_HOSTS:
                try:
                    r = await c.post(f"{host}/api2/json/nodes/{node}/{vm_type}/{vmid}/status/{action}")
                    r.raise_for_status()
                    return json.dumps(r.json(), indent=2)
                except httpx.HTTPStatusError:
                    continue
        return json.dumps({"error": f"Failed to {action} VM {vmid} on node {node}"})

    @mcp.tool()
    async def docker_list_containers(host: str = "") -> str:
        """List Docker containers on a host. host can be a name (e.g. 'gpu-vm') or URL (e.g. 'http://10.0.0.15:2375').
        If empty, lists known Docker hosts."""
        if not host:
            return json.dumps({"known_hosts": DOCKER_HOSTS})

        url = DOCKER_HOSTS.get(host, host)
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{url}/containers/json?all=true")
            r.raise_for_status()
            containers = r.json()
            return json.dumps(
                [{"name": ct["Names"][0].lstrip("/"), "image": ct["Image"],
                  "state": ct["State"], "status": ct["Status"]}
                 for ct in containers],
                indent=2,
            )

    @mcp.tool()
    async def docker_all_services() -> str:
        """Get container status across all known Docker hosts."""
        results = {}
        async with httpx.AsyncClient(timeout=10) as c:
            for name, url in DOCKER_HOSTS.items():
                try:
                    r = await c.get(f"{url}/containers/json?all=true")
                    r.raise_for_status()
                    containers = r.json()
                    results[name] = {
                        "url": url,
                        "containers": [
                            {"name": ct["Names"][0].lstrip("/"), "state": ct["State"], "status": ct["Status"]}
                            for ct in containers
                        ],
                        "total": len(containers),
                        "running": sum(1 for ct in containers if ct["State"] == "running"),
                    }
                except Exception as e:
                    results[name] = {"url": url, "error": str(e)}
        return json.dumps(results, indent=2)
