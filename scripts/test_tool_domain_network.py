"""Régressions déterministes du domaine d'outils réseau."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import network


async def _run() -> None:
    assert network._net_parse_ports("443,80,80,90-88") == [80, 88, 89, 90, 443]
    assert network._net_parse_ports("-5,0,65536") == []
    try:
        network._net_parse_ports("abc")
    except ValueError:
        pass
    else:
        raise AssertionError("Un port non numérique doit être refusé.")

    hosts, blocked = network._net_targets(
        "192.0.2.0/24", confirmed=False, max_hosts=256
    )
    assert not hosts
    assert blocked and blocked["requiresConfirmation"] is True
    hosts, blocked = network._net_targets(
        "192.0.2.0/30", confirmed=False, max_hosts=64
    )
    assert hosts == ["192.0.2.1", "192.0.2.2"] and blocked is None

    subnet = await network.execute_net_subnet_calc(
        {"cidr": "192.0.2.0/24", "new_prefix": 26}
    )
    assert subnet["success"] is True
    assert subnet["subnet_count"] == 4
    assert subnet["next_subnet"] == "192.0.3.0/24"

    invalid_ports = await network.execute_net_port_scan(
        {"host": "127.0.0.1", "ports": "abc"}
    )
    assert "invalides" in invalid_ports["error"]
    invalid_count = await network.execute_net_ping(
        {"host": "127.0.0.1", "count": "beaucoup"}
    )
    assert "count" in invalid_count["error"]
    invalid_snmp = await network.execute_net_snmp_query(
        {"host": "127.0.0.1", "port": 70000}
    )
    assert "Port SNMP invalide" in invalid_snmp["error"]

    async def fake_windows_config(_args: dict) -> dict:
        return {"adapters": [{"Gateway": "192.0.2.1"}]}

    network.configure(win_network_config=fake_windows_config)
    assert await network._win_network_config({}) == {
        "adapters": [{"Gateway": "192.0.2.1"}]
    }

    public_names = (
        "ping", "port_scan", "dns_lookup", "traceroute", "scan_local", "whois",
        "nmap_scan", "service_detect", "http_probe", "tls_check", "tls_check_bulk",
        "subnet_calc", "snmp_query", "topology_diagram", "subnet_sweep",
        "route_diagnostics", "inventory_scan", "inventory_list",
        "inventory_annotate",
    )
    for suffix in public_names:
        assert getattr(tools, f"execute_net_{suffix}") is getattr(
            network, f"execute_net_{suffix}"
        )
        assert tools.TOOLS_REGISTRY[f"net_{suffix}"] is getattr(
            network, f"execute_net_{suffix}"
        )


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine réseau OK")
