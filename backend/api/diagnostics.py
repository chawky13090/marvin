"""Routes de diagnostic du routage agentique et de l'accès réseau local."""

import io
import socket

import psutil
import qrcode
from fastapi import APIRouter
from fastapi.responses import Response


router = APIRouter(tags=["diagnostics"])


@router.get("/api/router/route")
async def router_route(q: str):
    import agent
    import tool_router

    text = (q or "").lower()
    keyword = set(agent._ALWAYS_INCLUDE)
    for keywords, tools in agent._KEYWORD_TOOLS.items():
        if any(item in text for item in keywords):
            keyword.update(tools)
    keyword -= set(agent._ALWAYS_INCLUDE)
    routed = await tool_router.route_tools(q)
    return {
        "query": q,
        "keyword": sorted(keyword),
        "semantic": sorted(routed.get("semantic", set())),
        "learned": sorted(routed.get("learned", set())),
    }


@router.get("/api/network")
async def network_info():
    hostname = socket.gethostname()
    primary = None
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(0.5)
        probe.connect(("8.8.8.8", 80))
        primary = probe.getsockname()[0]
        probe.close()
    except Exception:
        pass

    addresses = []
    seen = set()
    try:
        for interface, interface_addresses in psutil.net_if_addrs().items():
            for address in interface_addresses:
                if address.family != socket.AF_INET or address.address.startswith(("127.", "169.254.")):
                    continue
                ip = address.address
                if ip in seen:
                    continue
                seen.add(ip)
                lowered = interface.lower()
                if ip.startswith("100.") or "tailscale" in lowered:
                    kind = "tailscale"
                elif any(
                    marker in lowered
                    for marker in ("vmware", "virtualbox", "vethernet", "hyper-v", "loopback")
                ):
                    kind = "virtuel"
                elif ip.startswith(("192.168.", "10.", "172.")):
                    kind = "lan"
                else:
                    kind = "autre"
                addresses.append(
                    {
                        "ip": ip,
                        "interface": interface,
                        "kind": kind,
                        "primary": ip == primary,
                        "url": f"http://{ip}:3000",
                    }
                )
    except Exception:
        pass

    order = {"lan": 0, "tailscale": 1, "autre": 2, "virtuel": 3}
    addresses.sort(key=lambda item: (0 if item["primary"] else 1, order.get(item["kind"], 9)))
    return {
        "hostname": hostname,
        "primary_ip": primary,
        "primary_url": f"http://{primary}:3000" if primary else None,
        "addresses": addresses,
    }


@router.get("/api/network/qr")
async def network_qr(url: str):
    image = qrcode.make(url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )
