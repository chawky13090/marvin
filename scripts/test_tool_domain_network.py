"""Régressions déterministes du domaine d'outils réseau."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import outbound_http
import tools
from tool_domains import network


async def _run() -> None:
    assert network._console_output_encoding()
    assert network._net_parse_ports("443,80,80,90-88") == [80, 88, 89, 90, 443]
    assert network._net_parse_ports("-5,0,65536") == []
    try:
        network._net_parse_ports("abc")
    except ValueError:
        pass
    else:
        raise AssertionError("Un port non numérique doit être refusé.")

    hosts, blocked = network._net_targets(
        "192.0.2.0/24", max_hosts=64
    )
    assert not hosts
    assert blocked and blocked["needsClarification"] is True
    assert "requiresConfirmation" not in blocked
    hosts, blocked = network._net_targets(
        "192.0.2.0/30", max_hosts=64
    )
    assert hosts == ["192.0.2.1", "192.0.2.2"] and blocked is None

    arp_process = subprocess.CompletedProcess(
        ["arp", "-a"],
        0,
        stdout=(
            b"  192.168.1.12  aa-bb-cc-dd-ee-01 dynamic\r\n"
            b"  192.168.1.255 ff-ff-ff-ff-ff-ff static\r\n"
            b"  224.0.0.22 01-00-5e-00-00-16 static\r\n"
        ),
        stderr=b"",
    )
    with patch.object(network.subprocess, "run", return_value=arp_process):
        arp = await network.execute_net_scan_local({})
    assert arp["count"] == 1
    assert arp["devices"][0]["ip"] == "192.168.1.12"
    assert arp["excluded_entries"] == 2
    assert arp["discovery_mode"] == "passive_cache"
    assert "raw" not in arp

    too_large = await network.execute_net_nmap_scan(
        {"target": "192.0.2.0/24", "profile": "top100", "confirmed": True}
    )
    assert too_large["needsClarification"] is True
    assert "requiresConfirmation" not in too_large

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
    unreachable_process = subprocess.CompletedProcess(
        ["ping"], 1, stdout=b"Destination host unreachable.", stderr=b""
    )
    with patch.object(network.subprocess, "run", return_value=unreachable_process):
        unreachable = await network.execute_net_ping(
            {"host": "192.0.2.1", "count": 1}
        )
    assert unreachable["success"] is True
    assert unreachable["reachable"] is False
    assert unreachable["returncode"] == 1
    invalid_snmp = await network.execute_net_snmp_query(
        {"host": "127.0.0.1", "port": 70000}
    )
    assert "Port SNMP invalide" in invalid_snmp["error"]

    ip_payload = (
        b'{"success":true,"ip":"8.8.8.8","country":"United States",'
        b'"country_code":"US","region":"California","city":"Mountain View",'
        b'"postal":"94043","latitude":37.4,"longitude":-122.1,'
        b'"timezone":{"id":"America/Los_Angeles"},'
        b'"connection":{"asn":15169,"org":"Google","isp":"Google LLC"}}'
    )
    with patch.object(
        outbound_http,
        "fetch_public",
        new=AsyncMock(
            return_value=outbound_http.PublicResponse(
                url="https://ipwho.is/8.8.8.8",
                status_code=200,
                headers={"content-type": "application/json"},
                content=ip_payload,
                elapsed_ms=10,
            )
        ),
    ):
        ip_info = await network.execute_ip_info({"ip": "8.8.8.8"})
    assert ip_info["success"] is True
    assert ip_info["asn"] == "15169"
    assert ip_info["provider"] == "ipwho.is"
    assert "globales" in (await network.execute_ip_info({"ip": "127.0.0.1"}))["error"]
    assert "invalide" in (await network.execute_ip_info({"ip": "not-an-ip"}))["error"]
    assert tools.execute_ip_info is network.execute_ip_info

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
