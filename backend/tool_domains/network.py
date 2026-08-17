"""Domaine r?seau : diagnostics, scans born?s, TLS/SNMP, topologie et inventaire."""
from __future__ import annotations
import asyncio
import ipaddress
import ipaddress as _ipaddress
import json
import re as _re
import shutil
import socket as _socket
import ssl as _ssl
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any
import database as db
import outbound_http

WinNetworkConfig = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
async def _missing_win_network_config(args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "Diagnostic r?seau Windows non configur?."}
_win_network_config: WinNetworkConfig = _missing_win_network_config
def configure(*, win_network_config: WinNetworkConfig) -> None:
    global _win_network_config
    _win_network_config = win_network_config

def _is_offline_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ("getaddrinfo", "temporary failure", "connecterror", "connection refused", "network is unreachable", "timed out", "readtimeout", "connecttimeout", "[errno 11001]", "failed to establish"))
def _net_error(exc: Exception, what: str = "la ressource") -> dict[str, Any]:
    if _is_offline_error(exc):
        return {"error": f"Pas de connexion internet (ou {what} injoignable). V?rifiez votre r?seau puis r?essayez.", "offline": True}
    return {"error": str(exc)}


def _console_output_encoding() -> str:
    """Encodage des utilitaires console natifs, distinct de l'ANSI sous Windows."""
    if sys.platform != "win32":
        return "utf-8"
    try:
        import ctypes

        return f"cp{int(ctypes.windll.kernel32.GetOEMCP())}"
    except (AttributeError, OSError, TypeError, ValueError):
        return "oem"


async def execute_ip_info(args: dict) -> dict:
    """Retourne la géolocalisation d'une IP globale via l'endpoint HTTPS IPWhois."""
    raw_ip = str(args.get("ip") or "").strip()
    if len(raw_ip) > 64:
        return {"error": "Adresse IP trop longue."}
    if raw_ip:
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError:
            return {"error": f"Adresse IP invalide : {raw_ip}"}
        if not address.is_global:
            return {"error": "Seules les adresses IP globales peuvent être géolocalisées."}
        normalized_ip = address.compressed
    else:
        normalized_ip = ""
    url = "https://ipwho.is/" + normalized_ip
    try:
        response = await outbound_http.fetch_public(
            url,
            max_bytes=100_000,
            timeout=10.0,
            headers={"User-Agent": "Marvin/2.369 (+ip-info)"},
        )
        if response.status_code >= 400:
            return {"error": f"Service IPWhois indisponible : HTTP {response.status_code}"}
        payload = json.loads(response.content.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Réponse IPWhois invalide.")
        if payload.get("success") is False:
            return {"error": str(payload.get("message") or "IP introuvable ou réservée")[:500]}
        connection = payload.get("connection")
        connection = connection if isinstance(connection, dict) else {}
        timezone = payload.get("timezone")
        timezone = timezone if isinstance(timezone, dict) else {}
        latitude = payload.get("latitude")
        longitude = payload.get("longitude")
        if not isinstance(latitude, (int, float)) or not -90 <= latitude <= 90:
            latitude = None
        if not isinstance(longitude, (int, float)) or not -180 <= longitude <= 180:
            longitude = None
        return {
            "success": True,
            "ip": str(payload.get("ip") or normalized_ip),
            "country": str(payload.get("country") or ""),
            "country_code": str(payload.get("country_code") or ""),
            "region": str(payload.get("region") or ""),
            "city": str(payload.get("city") or ""),
            "postal_code": str(payload.get("postal") or ""),
            "latitude": latitude,
            "longitude": longitude,
            "timezone": str(timezone.get("id") or ""),
            "isp": str(connection.get("isp") or ""),
            "org": str(connection.get("org") or ""),
            "asn": str(connection.get("asn") or ""),
            "provider": "ipwho.is",
        }
    except (json.JSONDecodeError, OSError, TypeError, ValueError, outbound_http.httpx.HTTPError) as exc:
        return _net_error(exc, "IPWhois")


async def execute_net_ping(args: dict) -> dict:
    """Ping une adresse IP ou un nom d'hôte."""
    # 'target'/'ip' acceptés en alias de 'host' : le LLM emploie parfois ces noms courants,
    # mieux vaut être tolérant que de faire échouer l'appel pour un mauvais nom de paramètre.
    host = str(args.get("host") or args.get("target") or args.get("ip") or "").strip()
    try:
        count = max(1, min(int(args.get("count", 4)), 20))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'count' invalide : entier attendu entre 1 et 20."}
    if not host:
        return {"error": "Paramètre 'host' requis."}
    def _do_ping():
        flag = "-n" if sys.platform == "win32" else "-c"
        result = subprocess.run(
            ["ping", flag, str(count), host],
            capture_output=True, timeout=30,
        )
        output = result.stdout.decode(_console_output_encoding(), errors="replace")
        lines = [l for l in output.splitlines() if l.strip()]
        return {
            "host": host,
            # Le processus ping a bien exécuté le diagnostic même si la cible
            # ne répond pas. Ne pas comptabiliser un hôte injoignable comme une
            # panne de l'outil dans la télémétrie de fiabilité.
            "success": True,
            "reachable": result.returncode == 0,
            "returncode": result.returncode,
            "output": output.strip(),
            "summary": lines[-1] if lines else "",
        }
    try:
        return await asyncio.get_running_loop().run_in_executor(None, _do_ping)
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout en pingant {host}"}
    except Exception as e:
        return {"error": repr(e)}


async def execute_net_port_scan(args: dict) -> dict:
    """Scanne les ports ouverts sur un hôte."""
    host = str(args.get("host") or "").strip()
    ports_raw = args.get("ports", "22,80,443,3389,8080,8443,21,25,53,110,143,3306,5432,6379,27017")
    if not host:
        return {"error": "Paramètre 'host' requis."}
    try:
        timeout = max(0.1, min(float(args.get("timeout", 1.0)), 10.0))
        port_list = _net_parse_ports(ports_raw, limit=100)
    except (TypeError, ValueError) as exc:
        return {"error": f"Paramètres de scan invalides : {exc}"}
    if not port_list:
        return {"error": "Aucun port TCP valide à scanner."}

    open_ports = []
    closed_ports = []

    async def check_port(port: int):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            open_ports.append(port)
        except Exception:
            closed_ports.append(port)

    await asyncio.gather(*[check_port(p) for p in port_list])
    open_ports.sort()
    return {
        "host": host,
        "open_ports": open_ports,
        "closed_count": len(closed_ports),
        "scanned": len(port_list),
        "summary": f"{len(open_ports)} port(s) ouvert(s) sur {len(port_list)} scannés",
    }


async def execute_net_dns_lookup(args: dict) -> dict:
    """Résolution DNS d'un nom d'hôte ou reverse lookup d'une IP."""
    host = (args.get("host") or args.get("domain") or args.get("hostname") or "").strip()
    record_type = args.get("type", "A").upper()
    if not host:
        return {"error": "Paramètre 'host' requis."}
    try:
        results = {}
        # Forward lookup
        try:
            addrs = _socket.getaddrinfo(host, None)
            results["addresses"] = list(set(a[4][0] for a in addrs))
        except Exception as e:
            results["forward_error"] = str(e)

        # Reverse lookup if IP
        try:
            _ipaddress.ip_address(host)
            hostname, _, _ = _socket.gethostbyaddr(host)
            results["hostname"] = hostname
        except (ValueError, _socket.herror):
            pass

        # nslookup for more details
        try:
            proc = await asyncio.create_subprocess_exec(
                "nslookup", host,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            results["nslookup"] = stdout.decode("cp850", errors="replace").strip()
        except Exception:
            pass

        return {"host": host, **results}
    except Exception as e:
        return {"error": str(e)}


async def execute_net_traceroute(args: dict) -> dict:
    """Traceroute vers une adresse IP ou un nom d'hôte."""
    host = args.get("host", "").strip()
    max_hops = max(1, min(int(args.get("max_hops", 15)), 30))
    if not host:
        return {"error": "Paramètre 'host' requis."}
    def _do_trace():
        if sys.platform == "win32":
            cmd = ["tracert", "-h", str(max_hops), "-d", host]
        else:
            cmd = ["traceroute", "-m", str(max_hops), host]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        output = result.stdout.decode(_console_output_encoding(), errors="replace")
        return {"host": host, "output": output.strip(), "success": result.returncode == 0}
    try:
        return await asyncio.get_running_loop().run_in_executor(None, _do_trace)
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout traceroute vers {host}"}
    except Exception as e:
        return {"error": repr(e)}


async def execute_net_scan_local(args: dict) -> dict:
    """Lit le cache ARP local et en extrait uniquement les voisins plausibles."""
    try:
        result = await asyncio.to_thread(subprocess.run, ["arp", "-a"], capture_output=True, timeout=15)
        output = result.stdout.decode(_console_output_encoding(), errors="replace")

        # Parse ARP table
        devices = []
        excluded_entries = 0
        for line in output.splitlines():
            # Windows: "  192.168.1.1   aa-bb-cc-dd-ee-ff   dynamic"
            parts = line.split()
            if len(parts) >= 2:
                ip = parts[0].strip()
                mac = parts[1].strip() if len(parts) > 1 else ""
                type_ = parts[2].strip() if len(parts) > 2 else ""
                try:
                    address = _ipaddress.ip_address(ip)
                    normalized_mac = mac.replace(":", "-").casefold()
                    is_broadcast_mac = normalized_mac == "ff-ff-ff-ff-ff-ff"
                    if (
                        address.is_multicast
                        or address.is_unspecified
                        or str(address) == "255.255.255.255"
                        or is_broadcast_mac
                    ):
                        excluded_entries += 1
                        continue
                    devices.append({"ip": ip, "mac": mac, "type": type_})
                except ValueError:
                    pass

        return {
            "success": True,
            "devices": devices,
            "count": len(devices),
            "source": "arp_cache",
            "discovery_mode": "passive_cache",
            "excluded_entries": excluded_entries,
            "coverage_caveat": (
                "Le cache ARP n'est pas un scan actif : il peut omettre des appareils "
                "qui n'ont pas communiqué récemment avec ce PC."
            ),
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_net_whois(args: dict) -> dict:
    """Informations WHOIS sur un domaine ou une IP (via whois CLI ou service web)."""
    host = args.get("host", "").strip()
    if not host:
        return {"error": "Paramètre 'host' requis."}
    try:
        # Essaie d'abord whois CLI
        proc = await asyncio.create_subprocess_exec(
            "whois", host,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        output = stdout.decode(errors="replace").strip()
        if output:
            # Limiter à 3000 chars
            return {"host": host, "whois": output[:3000], "truncated": len(output) > 3000}
    except Exception:
        pass
    # Fallback: requête HTTP vers un service whois public
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"https://www.whois.com/whois/{host}")
            # Extraction simple du texte
            text = resp.text
            start = text.find("Registrant")
            if start == -1:
                start = text.find("Domain Name")
            snippet = text[max(0, start):start + 2000] if start != -1 else text[:2000]
            return {"host": host, "whois": snippet, "source": "whois.com"}
    except Exception as e2:
        return {"error": f"whois CLI indisponible et fallback HTTP échoué: {e2}"}


_NET_PROFILE_PORTS = {
    "quick": "22,53,80,135,139,443,445,3389,5985,8000,8080,8443",
    "web": "80,443,8000,8080,8081,8443,3000,5000,5173,9000,9443",
    "windows": "53,88,135,139,389,445,464,593,636,3389,5985,5986",
    "remote": "21,22,23,25,53,80,110,143,443,465,587,993,995,3389,5900,8080",
    "top100": (
        "7,9,13,21,22,23,25,26,37,53,79,80,81,88,106,110,111,113,119,135,139,143,"
        "144,179,199,389,427,443,444,445,465,513,514,515,543,544,548,554,587,631,"
        "646,873,990,993,995,1025,1026,1027,1028,1029,1110,1433,1720,1723,1755,"
        "1900,2000,2001,2049,2121,2717,3000,3128,3306,3389,3986,4899,5000,5009,"
        "5051,5060,5101,5190,5357,5432,5631,5666,5800,5900,6000,6001,6646,7070,"
        "8000,8008,8009,8080,8081,8443,8888,9100,9999,10000,32768,49152,49153,49154"
    ),
}


def _net_parse_ports(ports_raw: Any, *, limit: int = 256) -> list[int]:
    if limit < 1:
        return []
    raw = str(ports_raw or "").strip() or _NET_PROFILE_PORTS["quick"]
    ports: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("-"):
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a.strip()), int(b.strip())
            if start > end:
                start, end = end, start
            start, end = max(1, start), min(65535, end)
            if start <= end:
                ports.extend(range(start, end + 1))
        else:
            p = int(part)
            if 1 <= p <= 65535:
                ports.append(p)
    return sorted(set(ports))[:limit]


def _net_targets(target: str, *, max_hosts: int = 64) -> tuple[list[str], dict | None]:
    """Résout une cible bornée sans accepter de pseudo-confirmation du modèle."""
    target = str(target or "").strip()
    if not target:
        return [], {"error": "Paramètre 'target' requis."}
    if "/" not in target:
        return [target], None
    try:
        net = _ipaddress.ip_network(target, strict=False)
    except Exception as e:
        return [], {"error": f"CIDR invalide : {e}"}
    host_count = int(net.num_addresses) if net.num_addresses <= 2 else int(net.num_addresses - 2)
    if host_count > max_hosts:
        return [], {
            "success": False,
            "needsClarification": True,
            "scopeRejected": True,
            "message": (
                f"Périmètre trop large : {target} contient {host_count} hôtes utilisables. "
                f"Choisissez au maximum {max_hosts} hôtes ou utilisez d'abord l'inventaire ARP."
            ),
            "target_count": host_count,
            "max_hosts": max_hosts,
        }
    hosts = [str(ip) for ip in net.hosts()]
    if not hosts and net.num_addresses == 1:
        hosts = [str(net.network_address)]
    return hosts, None


async def _net_tcp_probe(host: str, port: int, timeout: float = 0.8) -> dict:
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return {"host": host, "port": port, "open": True, "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
    except Exception as e:
        return {"host": host, "port": port, "open": False, "error": str(e)[:120]}


def _net_parse_nmap_xml(xml_text: str) -> list[dict]:
    import xml.etree.ElementTree as _ET
    hosts: list[dict] = []
    try:
        root = _ET.fromstring(xml_text)
    except Exception:
        return hosts
    for h in root.findall("host"):
        status_el = h.find("status")
        status = (status_el.attrib if status_el is not None else {}).get("state", "")
        addrs = [a.attrib.get("addr") for a in h.findall("address") if a.attrib.get("addr")]
        hostnames = [n.attrib.get("name") for n in h.findall("./hostnames/hostname") if n.attrib.get("name")]
        ports = []
        for p in h.findall("./ports/port"):
            state = p.find("state")
            service = p.find("service")
            sattr = service.attrib if service is not None else {}
            ports.append({
                "port": int(p.attrib.get("portid", 0)),
                "protocol": p.attrib.get("protocol", "tcp"),
                "state": (state.attrib if state is not None else {}).get("state", ""),
                "service": sattr.get("name", ""),
                "product": sattr.get("product", ""),
                "version": sattr.get("version", ""),
            })
        hosts.append({"addresses": addrs, "hostnames": hostnames, "status": status, "ports": ports})
    return hosts


async def execute_net_nmap_scan(args: dict) -> dict:
    """Scan de ports façon Nmap. Utilise nmap.exe si présent dans le PATH, sinon repli par
    sondage TCP asynchrone interne (aucune installation requise dans les deux cas)."""
    target = (args.get("target") or args.get("host") or "").strip()
    profile = str(args.get("profile") or "quick").lower()
    timeout = max(0.2, min(float(args.get("timeout", 0.8)), 5.0))
    port_limit = 256
    ports_raw = args.get("ports") or _NET_PROFILE_PORTS.get(profile, _NET_PROFILE_PORTS["quick"])
    try:
        ports = _net_parse_ports(ports_raw, limit=port_limit)
    except Exception as e:
        return {"error": f"Ports invalides : {e}"}
    if not ports:
        return {"error": "Aucun port valide à scanner."}
    targets, blocked = _net_targets(target, max_hosts=64)
    if blocked:
        return blocked
    if len(targets) * len(ports) > 1200:
        return {
            "success": False,
            "needsClarification": True,
            "scopeRejected": True,
            "message": "Scan trop large pour une exécution directe. Réduisez les ports ou la cible.",
            "target_count": len(targets),
            "port_count": len(ports),
            "probe_count": len(targets) * len(ports),
            "max_probes": 1200,
        }

    nmap_path = shutil.which("nmap")
    if nmap_path:
        cmd = [
            nmap_path, "-Pn", "-T3", "--max-retries", "2", "--host-timeout", "75s",
            "-oX", "-", "-p", ",".join(map(str, ports)), target,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            xml_text = stdout.decode("utf-8", errors="replace")
            err_text = stderr.decode("utf-8", errors="replace").strip()
            hosts = _net_parse_nmap_xml(xml_text)
            open_ports = [
                {"host": (h.get("addresses") or [""])[0], **p}
                for h in hosts for p in h.get("ports", []) if p.get("state") == "open"
            ]
            return {
                "target": target,
                "profile": profile,
                "used_nmap": True,
                "nmap_path": nmap_path,
                "hosts": hosts,
                "open_ports": open_ports,
                "scanned_hosts": len(hosts),
                "scanned_ports": len(ports),
                "stderr": err_text[:1000],
                "summary": f"{len(open_ports)} port(s) ouvert(s) via Nmap sur {len(hosts) or len(targets)} hôte(s)",
            }
        except Exception as e:
            nmap_error = str(e)
    else:
        nmap_error = "nmap.exe non trouvé dans le PATH (utilisation du repli TCP intégré)"

    sem = asyncio.Semaphore(160)

    async def bounded(host: str, port: int):
        async with sem:
            return await _net_tcp_probe(host, port, timeout=timeout)

    probes = await asyncio.gather(*[bounded(h, p) for h in targets for p in ports])
    by_host: dict[str, list[dict]] = {}
    for r in probes:
        if r.get("open"):
            by_host.setdefault(r["host"], []).append({"port": r["port"], "state": "open", "latency_ms": r.get("latency_ms")})
    hosts = [{"addresses": [h], "status": "up" if ports_ else "unknown", "ports": ports_} for h, ports_ in by_host.items()]
    open_ports = [{"host": h, **p} for h, ports_ in by_host.items() for p in ports_]
    return {
        "target": target,
        "profile": profile,
        "used_nmap": False,
        "nmap_error": nmap_error,
        "hosts": hosts,
        "open_ports": open_ports,
        "scanned_hosts": len(targets),
        "scanned_ports": len(ports),
        "summary": f"{len(open_ports)} port(s) ouvert(s) via repli TCP sur {len(targets)} hôte(s)",
    }


async def execute_net_service_detect(args: dict) -> dict:
    """Détecte les services et bannières TCP sans scan agressif (une seule sonde/port)."""
    host = (args.get("host") or "").strip()
    if not host:
        return {"error": "Paramètre 'host' requis."}
    try:
        ports = _net_parse_ports(args.get("ports") or _NET_PROFILE_PORTS["quick"], limit=80)
    except Exception as e:
        return {"error": f"Ports invalides : {e}"}
    timeout = max(0.3, min(float(args.get("timeout", 1.5)), 8.0))

    async def grab(port: int) -> dict:
        item = {"host": host, "port": port, "open": False, "banner": "", "service_hint": ""}
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
            item["open"] = True
            if port in (80, 8080, 8000, 8081):
                writer.write(f"HEAD / HTTP/1.0\r\nHost: {host}\r\n\r\n".encode("ascii", errors="ignore"))
                item["service_hint"] = "http"
            elif port in (443, 8443, 9443):
                item["service_hint"] = "https"
            else:
                writer.write(b"\r\n")
            await writer.drain()
            try:
                data = await asyncio.wait_for(reader.read(512), timeout=timeout)
                item["banner"] = data.decode("utf-8", errors="replace").strip()[:500]
            except Exception:
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        except Exception as e:
            item["error"] = str(e)[:120]
        return item

    services = await asyncio.gather(*[grab(p) for p in ports])
    open_services = [s for s in services if s.get("open")]
    return {
        "host": host,
        "services": open_services,
        "scanned": len(ports),
        "summary": f"{len(open_services)} service(s) TCP détecté(s) sur {len(ports)} port(s)",
    }


async def execute_net_http_probe(args: dict) -> dict:
    """Analyse rapide HTTP/HTTPS : statut, redirections, en-têtes, titre, sécurité."""
    url = str(args.get("url") or args.get("host") or "").strip()
    if not url:
        return {"error": "Paramètre 'url' requis."}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    timeout = max(2.0, min(float(args.get("timeout", 8.0)), 20.0))
    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Marvin-Network-Probe/1.0"})
        text = resp.text[:200000]
        title = ""
        m = _re.search(r"<title[^>]*>(.*?)</title>", text, _re.I | _re.S)
        if m:
            title = _re.sub(r"\s+", " ", m.group(1)).strip()[:160]
        headers = {k.lower(): v for k, v in resp.headers.items()}
        security_headers = {
            "https": str(resp.url).startswith("https://"),
            "hsts": "strict-transport-security" in headers,
            "csp": "content-security-policy" in headers,
            "x_frame_options": "x-frame-options" in headers,
            "x_content_type_options": "x-content-type-options" in headers,
            "referrer_policy": "referrer-policy" in headers,
        }
        return {
            "url": str(resp.url),
            "status_code": resp.status_code,
            "reason": resp.reason_phrase,
            "title": title,
            "headers": dict(list(headers.items())[:60]),
            "security": security_headers,
            "redirects": [str(r.url) for r in resp.history],
            "server": headers.get("server", ""),
            "content_type": headers.get("content-type", ""),
            "summary": f"HTTP {resp.status_code} {resp.reason_phrase} - {title or resp.url.host}",
        }
    except Exception as e:
        return _net_error(e, url)


async def execute_net_tls_check(args: dict) -> dict:
    """Contrôle TLS/certificat : émetteur, SAN, expiration, protocole et cipher."""
    host = (args.get("host") or "").strip()
    port = int(args.get("port") or 443)
    if not host:
        return {"error": "Paramètre 'host' requis."}
    host = host.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
    timeout = max(2.0, min(float(args.get("timeout", 5.0)), 15.0))

    def check() -> dict:
        import ssl as _ssl
        import datetime as _dt
        ctx = _ssl.create_default_context()
        with _socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                not_after = cert.get("notAfter", "")
                expires_ts = _ssl.cert_time_to_seconds(not_after) if not_after else 0
                expires = _dt.datetime.fromtimestamp(expires_ts, tz=_dt.timezone.utc) if expires_ts else None
                days_left = (expires - _dt.datetime.now(_dt.timezone.utc)).days if expires else None
                subject = dict(x[0] for x in cert.get("subject", []) if x)
                issuer = dict(x[0] for x in cert.get("issuer", []) if x)
                san = [v for k, v in cert.get("subjectAltName", []) if k.lower() == "dns"]
                return {
                    "host": host,
                    "port": port,
                    "subject": subject,
                    "issuer": issuer,
                    "san": san[:80],
                    "not_before": cert.get("notBefore", ""),
                    "not_after": not_after,
                    "expires_at": expires.isoformat() if expires else "",
                    "days_left": days_left,
                    "protocol": ssock.version(),
                    "cipher": ssock.cipher(),
                    "summary": f"TLS {ssock.version()} - certificat expire dans {days_left} jour(s)" if days_left is not None else "TLS OK",
                }

    try:
        return await asyncio.get_running_loop().run_in_executor(None, check)
    except Exception as e:
        return {"error": str(e)}


async def execute_net_tls_check_bulk(args: dict) -> dict:
    """Contrôle TLS/certificat sur PLUSIEURS hôtes en une fois (réutilise net_tls_check par
    hôte, en parallèle) — pour surveiller les expirations d'un parc de services (ex. plusieurs
    services auto-hébergés) sans un appel par hôte."""
    hosts_raw = args.get("hosts")
    if isinstance(hosts_raw, str):
        hosts = [h.strip() for h in hosts_raw.split(",") if h.strip()]
    elif isinstance(hosts_raw, list):
        hosts = [str(h).strip() for h in hosts_raw if str(h).strip()]
    else:
        hosts = []
    if not hosts:
        return {"error": "Paramètre 'hosts' requis (liste ou chaîne séparée par des virgules)."}
    hosts = hosts[:25]  # borne raisonnable
    port = int(args.get("port") or 443)
    timeout = max(2.0, min(float(args.get("timeout", 5.0)), 15.0))

    results = await asyncio.gather(
        *[execute_net_tls_check({"host": h, "port": port, "timeout": timeout}) for h in hosts],
        return_exceptions=True,
    )
    out = []
    expiring_soon = []
    for h, r in zip(hosts, results):
        if isinstance(r, Exception) or r.get("error"):
            out.append({"host": h, "error": (r.get("error") if isinstance(r, dict) else str(r))})
            continue
        entry = {"host": h, "days_left": r.get("days_left"), "expires_at": r.get("expires_at"),
                  "issuer": r.get("issuer", {}).get("organizationName") or r.get("issuer", {}).get("commonName", ""),
                  "protocol": r.get("protocol")}
        out.append(entry)
        if isinstance(r.get("days_left"), int) and r["days_left"] <= 30:
            expiring_soon.append(f"{h} ({r['days_left']}j)")
    return {
        "success": True, "count": len(out), "results": out,
        "expiring_soon": expiring_soon,
        "message": (f"{len(expiring_soon)} certificat(s) expirent sous 30 jours : {', '.join(expiring_soon)}"
                    if expiring_soon else f"{len(out)} hôte(s) vérifié(s), aucun certificat proche de l'expiration."),
    }


def _subnet_calc_sync(cidr: str) -> dict:
    import ipaddress
    net = ipaddress.ip_network(cidr, strict=False)
    hosts = list(net.hosts()) if net.num_addresses > 2 else []
    result = {
        "cidr": str(net),
        "network_address": str(net.network_address),
        "broadcast_address": str(net.broadcast_address) if net.version == 4 else None,
        "netmask": str(net.netmask),
        "wildcard_mask": str(net.hostmask),
        "prefix_length": net.prefixlen,
        "total_addresses": net.num_addresses,
        "usable_hosts": max(net.num_addresses - 2, 0) if net.version == 4 else net.num_addresses,
        "first_usable": str(hosts[0]) if hosts else None,
        "last_usable": str(hosts[-1]) if hosts else None,
        "is_private": net.is_private,
        "version": net.version,
    }
    try:
        # v2.154 — bug réel trouvé en testant : la version précédente (via supernet()/subnets())
        # retournait le sous-réseau LUI-MÊME quand il occupait la 2e moitié de son supernet
        # (ex. 192.168.1.0/24 → "192.168.1.0/24" au lieu de 192.168.2.0/24). Le calcul correct
        # du sous-réseau CONTIGU suivant est arithmétique : adresse réseau + nombre d'adresses.
        next_addr = int(net.network_address) + net.num_addresses
        max_addr = (2 ** (32 if net.version == 4 else 128)) - 1
        result["next_subnet"] = (
            str(ipaddress.ip_network((ipaddress.ip_address(next_addr), net.prefixlen), strict=False))
            if next_addr <= max_addr else None
        )
    except Exception:
        result["next_subnet"] = None
    return result


async def execute_net_subnet_calc(args: dict) -> dict:
    """Calculateur de sous-réseau (VLSM/CIDR) : adresse réseau, broadcast, masque, masque
    générique, plage d'hôtes utilisables, nombre d'adresses. Accepte aussi 'new_prefix' pour
    découper le CIDR donné en sous-réseaux de cette taille (VLSM)."""
    cidr = (args.get("cidr") or "").strip()
    if not cidr:
        return {"error": "Paramètre 'cidr' requis (ex: 192.168.1.0/24 ou 10.0.0.0/8)."}
    try:
        base = _subnet_calc_sync(cidr)
    except Exception as e:
        return {"error": f"CIDR invalide : {e}"}

    new_prefix = args.get("new_prefix")
    if new_prefix:
        try:
            import ipaddress
            net = ipaddress.ip_network(cidr, strict=False)
            new_prefix = int(new_prefix)
            if new_prefix <= net.prefixlen:
                return {"error": f"new_prefix ({new_prefix}) doit être PLUS GRAND que le préfixe actuel ({net.prefixlen})."}
            subnets = list(net.subnets(new_prefix=new_prefix))
            if len(subnets) > 256:
                return {"error": f"Découpage en {len(subnets)} sous-réseaux — trop grand, précise un new_prefix plus proche."}
            base["subnets"] = [
                {"cidr": str(s), "network_address": str(s.network_address),
                 "broadcast_address": str(s.broadcast_address) if s.version == 4 else None,
                 "usable_hosts": max(s.num_addresses - 2, 0)}
                for s in subnets
            ]
            base["subnet_count"] = len(subnets)
        except Exception as e:
            return {"error": f"Paramètre new_prefix invalide : {e}"}

    base["success"] = True
    base["message"] = (f"{base['cidr']} — {base['usable_hosts']} hôte(s) utilisable(s) "
                        f"({base.get('first_usable', 'N/A')} → {base.get('last_usable', 'N/A')})")
    return base


_SNMP_SYSTEM_OIDS = {
    "sysDescr": "1.3.6.1.2.1.1.1.0", "sysUpTime": "1.3.6.1.2.1.1.3.0",
    "sysContact": "1.3.6.1.2.1.1.4.0", "sysName": "1.3.6.1.2.1.1.5.0",
    "sysLocation": "1.3.6.1.2.1.1.6.0",
}


_SNMP_IF_TABLE_OIDS = {"ifDescr": "1.3.6.1.2.1.2.2.1.2", "ifOperStatus": "1.3.6.1.2.1.2.2.1.8"}


async def execute_net_snmp_query(args: dict) -> dict:
    """Interroge un équipement via SNMP (v2c) — 'action'="sysinfo" (infos système : nom,
    description, uptime, contact, localisation, en un seul appel) ou "interfaces" (liste des
    interfaces réseau + état up/down, via un walk borné) ou "get" avec un OID précis. Utile
    pour un switch/routeur/serveur exposant SNMP (souvent activé par défaut sur les
    équipements réseau pro — community 'public' en lecture seule fréquente en labo)."""
    host = (args.get("host") or "").strip()
    if not host:
        return {"error": "Paramètre 'host' requis."}
    community = str(args.get("community") or "public").strip()
    try:
        port = int(args.get("port") or 161)
        timeout = max(1, min(int(args.get("timeout", 4)), 10))
    except (TypeError, ValueError):
        return {"error": "Port ou timeout SNMP invalide."}
    if not 1 <= port <= 65535:
        return {"error": "Port SNMP invalide : valeur attendue entre 1 et 65535."}
    action = str(args.get("action") or "sysinfo").strip().lower()
    if action not in {"sysinfo", "interfaces", "get"}:
        return {"error": "Action SNMP invalide : sysinfo, interfaces ou get attendu."}
    oid = str(args.get("oid") or "").strip()

    try:
        from pysnmp.hlapi.v3arch.asyncio import (
            SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
            ObjectType, ObjectIdentity, get_cmd, walk_cmd,
        )
    except ImportError:
        return {"error": "Module pysnmp non installé côté backend."}

    engine = SnmpEngine()
    auth = CommunityData(community, mpModel=1)  # mpModel=1 → SNMPv2c
    try:
        transport = await UdpTransportTarget.create((host, port), timeout=timeout, retries=1)
    except Exception as e:
        return {"error": f"Cible SNMP injoignable : {e}"}

    if action == "interfaces":
        results = []
        # v2.155 — bug trouvé en testant contre un hôte sans agent SNMP : sans distinguer
        # "erreur dès le 1er paquet" de "0 résultat légitime", l'outil renvoyait un succès
        # trompeur ("0 interface trouvée") au lieu de signaler l'absence de réponse SNMP.
        got_any_response = False
        try:
            for base_name, base_oid in _SNMP_IF_TABLE_OIDS.items():
                count = 0
                async for errind, errstat, errix, varbinds in walk_cmd(
                        engine, auth, transport, ContextData(), ObjectType(ObjectIdentity(base_oid))):
                    if errind or errstat:
                        break
                    got_any_response = True
                    for vb in varbinds:
                        oid_str, val = str(vb[0]), str(vb[1])
                        idx = oid_str.rsplit(".", 1)[-1]
                        entry = next((r for r in results if r["index"] == idx), None)
                        if not entry:
                            entry = {"index": idx}
                            results.append(entry)
                        entry[base_name] = val
                        count += 1
                    if count >= 40:
                        break
        except Exception as e:
            return {"error": f"Échec du walk SNMP (community/port corrects ? SNMP activé sur la cible ?) : {e}"}
        if not got_any_response:
            return {"error": f"Aucune réponse SNMP de {host} (community/port corrects ? SNMP activé sur la cible ?)."}
        for r in results:
            r["status"] = {"1": "up", "2": "down", "3": "testing"}.get(r.get("ifOperStatus", ""), r.get("ifOperStatus", "?"))
        return {"success": True, "host": host, "count": len(results), "interfaces": results,
                "message": f"{len(results)} interface(s) trouvée(s) sur {host}."}

    # sysinfo (défaut) ou get(oid) : requête simple via get_cmd
    if action == "get":
        if not oid:
            return {"error": "Paramètre 'oid' requis pour action='get'."}
        targets = {"value": oid}
    else:
        targets = _SNMP_SYSTEM_OIDS

    try:
        errind, errstat, errix, varbinds = await get_cmd(
            engine, auth, transport, ContextData(),
            *[ObjectType(ObjectIdentity(o)) for o in targets.values()],
        )
    except Exception as e:
        return {"error": f"Échec de la requête SNMP : {e}"}
    if errind:
        return {"error": f"SNMP : {errind} (community/port corrects ? SNMP activé sur la cible ?)"}
    if errstat:
        return {"error": f"SNMP : {errstat.prettyPrint()}"}

    values = {name: str(vb[1]) for name, vb in zip(targets.keys(), varbinds)}
    return {"success": True, "host": host, "values": values,
            "message": f"Réponse SNMP reçue de {host}."}


async def execute_net_topology_diagram(args: dict) -> dict:
    """Génère un diagramme visuel de topologie réseau (image PNG affichée dans le chat) à
    partir d'une liste d'hôtes (ou d'un scan réseau local si 'hosts' est omis). Passerelle/
    routeur au centre, appareils autour — utile pour documenter ou réviser une architecture
    réseau."""
    hosts_arg = args.get("hosts")
    gateway_ip = (args.get("gateway") or "").strip()
    if hosts_arg:
        if isinstance(hosts_arg, str):
            devices = [{"ip": h.strip(), "mac": ""} for h in hosts_arg.split(",") if h.strip()]
        else:
            devices = [{"ip": str(h), "mac": ""} for h in hosts_arg]
    else:
        scan = await execute_net_scan_local({})
        if scan.get("error"):
            return scan
        devices = [{"ip": d.get("ip", ""), "mac": d.get("mac", "")}
                   for d in scan.get("devices", []) if d.get("ip")]
        if not gateway_ip:
            # v2.155 — bug trouvé en testant : net_scan_local n'a jamais eu de champ "gateway"
            # (juste une liste ip/mac/type issue de `arp -a`) — la passerelle réelle vient de
            # win_network_config (Get-NetIPConfiguration), pas d'un champ halluciné ici.
            try:
                netcfg = await _win_network_config({})
                for a in (netcfg.get("adapters") or []):
                    gw = (a.get("Gateway") or "").strip()
                    if gw:
                        gateway_ip = gw
                        break
            except Exception:
                pass

    if not devices:
        return {"error": "Aucun appareil à représenter (scan vide ou 'hosts' non fourni)."}
    devices = devices[:20]  # borne raisonnable pour la lisibilité
    # La passerelle ne doit pas aussi apparaître comme un "appareil" autour d'elle-même
    if gateway_ip:
        devices = [d for d in devices if d.get("ip") != gateway_ip]

    def draw() -> str:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import math, io, base64 as _b64
        from datetime import datetime as _dt

        # v2.156 — présentation revue (retour utilisateur : « pouvons-nous améliorer la
        # présentation ? »). Couleurs exactement calées sur app/globals.css (--bg-primary
        # #0a0a0d, --accent-primary #4f8cff, --accent-secondary #38bdf8, --text-muted
        # #5f606a) plutôt qu'une palette approximative. Disposition en ANNEAUX CONCENTRIQUES
        # au-delà de 8 appareils — un seul cercle surchargeait les libellés en réseau dense
        # (le cas réel testé, 11 appareils, montrait déjà des libellés serrés).
        BG, INK, MUTED, ACCENT, ACCENT2, BORDER = "#0a0a0d", "#e4e4e7", "#8b8d98", "#4f8cff", "#38bdf8", "#2a2d3a"
        n = len(devices)
        RING_CAPACITY = 8
        rings: list[list[dict]] = []
        for i in range(0, n, RING_CAPACITY):
            rings.append(devices[i:i + RING_CAPACITY])

        size = 9.5 if n <= RING_CAPACITY else 11.5
        fig, ax = plt.subplots(figsize=(size, size))
        fig.patch.set_facecolor(BG)
        ax.set_facecolor(BG)
        max_radius = 1.35 + 0.95 * (len(rings) - 1)
        extent = max_radius + 0.65  # marge pour le nœud, ses libellés (IP+MAC) et la légende
        ax.set_xlim(-extent, extent)
        ax.set_ylim(-extent, extent)
        ax.set_aspect("equal")
        ax.axis("off")

        # Centre = passerelle. Les emoji (🌐/🖥) s'affichaient en "tofu" (glyphe manquant,
        # police par défaut matplotlib DejaVu Sans sans couverture emoji) — remplacés par des
        # libellés texte courts, garantis lisibles quelle que soit la police système.
        ax.scatter([0], [0], s=2000, c=ACCENT, edgecolors=INK, linewidths=1.5, zorder=4)
        ax.text(0, 0, "GW", ha="center", va="center", fontsize=14, fontweight="bold", color=BG, zorder=5)
        ax.text(0, -0.26, gateway_ip or "Passerelle", ha="center", va="top", color=INK, fontsize=9.5,
                fontweight="bold", zorder=5)

        for ring_idx, ring_devices in enumerate(rings):
            radius = 1.35 + ring_idx * 0.95
            m = len(ring_devices)
            # Décale chaque anneau d'un demi-pas pour éviter que les nœuds se retrouvent
            # exactement alignés radialement d'un anneau à l'autre (lisibilité).
            phase = (math.pi / max(m, 1)) if ring_idx % 2 else 0
            for i, dev in enumerate(ring_devices):
                angle = 2 * math.pi * i / max(m, 1) + phase
                x, y = radius * math.cos(angle), radius * math.sin(angle)
                # Trait jusqu'au centre pour le 1er anneau, jusqu'au nœud parent le plus proche
                # du côté centre pour les anneaux suivants — évite un enchevêtrement de traits
                # tous tirés vers (0,0) quand il y a plusieurs anneaux.
                inner = (radius - 0.95) * math.cos(angle), (radius - 0.95) * math.sin(angle) if ring_idx else (0, 0)
                ax.plot([0 if ring_idx == 0 else inner[0], x], [0 if ring_idx == 0 else inner[1], y],
                        color=BORDER, linewidth=1, zorder=1)
                ax.scatter([x], [y], s=950, c="#161821", edgecolors=ACCENT2, linewidths=1.5, zorder=3)
                ax.text(x, y, "PC", ha="center", va="center", fontsize=9.5, fontweight="bold", color=ACCENT2, zorder=4)
                ip = dev.get("ip", "")
                label_out = y >= 0 or n <= RING_CAPACITY
                offset = 0.16 if label_out else -0.16
                va = "bottom" if label_out else "top"
                ax.text(x, y + offset, ip[:22], ha="center", va=va, color=INK, fontsize=8, zorder=4)
                if dev.get("mac"):
                    ax.text(x, y + offset + (0.055 if label_out else -0.055), dev["mac"][:22], ha="center", va=va,
                            color=MUTED, fontsize=6.5, zorder=4)

        ax.set_title(f"Topologie réseau — {n} appareil(s)", color=INK, fontsize=13, fontweight="bold", pad=16)
        # Légende + horodatage, pour situer le diagramme (utile si on le garde/partage pour
        # documenter une architecture, cf. demande initiale).
        legend_y = -extent + 0.25
        ax.scatter([-extent + 0.3], [legend_y], s=200, c=ACCENT, edgecolors=INK, linewidths=1, zorder=5)
        ax.text(-extent + 0.5, legend_y, "Passerelle", ha="left", va="center", color=MUTED, fontsize=8, zorder=5)
        ax.scatter([-extent + 2.1], [legend_y], s=200, c="#161821", edgecolors=ACCENT2, linewidths=1, zorder=5)
        ax.text(-extent + 2.3, legend_y, "Appareil", ha="left", va="center", color=MUTED, fontsize=8, zorder=5)
        ax.text(extent - 0.3, legend_y, _dt.now().strftime("%d/%m/%Y %H:%M"), ha="right", va="center",
                color=MUTED, fontsize=7.5, zorder=5)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        return "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode("ascii")

    try:
        img = await asyncio.get_running_loop().run_in_executor(None, draw)
    except Exception as e:
        return {"error": f"Échec de la génération du diagramme : {e}"}
    return {"success": True, "image": img, "device_count": len(devices),
            "message": f"Diagramme généré — {len(devices)} appareil(s) autour de {gateway_ip or 'la passerelle'}."}


async def execute_net_subnet_sweep(args: dict) -> dict:
    """Sweep TCP borné d'un CIDR pour repérer les hôtes actifs sur ports courants."""
    cidr = (args.get("cidr") or args.get("target") or "").strip()
    confirmed = bool(args.get("confirmed", False))
    ports_raw = args.get("ports") or "22,80,443,445,3389,5985,8080"
    try:
        ports = _net_parse_ports(ports_raw, limit=32)
    except Exception as e:
        return {"error": f"Ports invalides : {e}"}
    targets, blocked = _net_targets(cidr, confirmed=confirmed, max_hosts=512 if confirmed else 128)
    if blocked:
        return blocked
    timeout = max(0.15, min(float(args.get("timeout", 0.45)), 2.0))
    sem = asyncio.Semaphore(220)

    async def scan_host(host: str):
        async with sem:
            probes = await asyncio.gather(*[_net_tcp_probe(host, p, timeout=timeout) for p in ports])
        opened = [p["port"] for p in probes if p.get("open")]
        return {"host": host, "open_ports": opened, "alive": bool(opened)}

    results = await asyncio.gather(*[scan_host(h) for h in targets])
    alive = [r for r in results if r["alive"]]
    return {
        "cidr": cidr,
        "ports": ports,
        "hosts": alive,
        "scanned_hosts": len(targets),
        "summary": f"{len(alive)} hôte(s) actif(s) repéré(s) sur {len(targets)} testé(s)",
    }


async def execute_net_route_diagnostics(args: dict) -> dict:
    """Diagnostic de connectivité complet : IP locale, DNS, ping internet, route."""
    target = (args.get("target") or "1.1.1.1").strip()
    include_trace = bool(args.get("include_trace", False))
    diagnostics: dict[str, Any] = {"target": target}
    try:
        diagnostics["local_config"] = await _win_network_config({}) if sys.platform == "win32" else {}
    except Exception as e:
        diagnostics["local_config_error"] = str(e)
    diagnostics["target_dns"] = await execute_net_dns_lookup({"host": target})
    diagnostics["target_ping"] = await execute_net_ping({"host": target, "count": 3})
    diagnostics["dns_ping"] = await execute_net_ping({"host": "1.1.1.1", "count": 2})
    if include_trace:
        diagnostics["traceroute"] = await execute_net_traceroute({"host": target, "max_hops": 15})
    ok = bool(diagnostics.get("target_ping", {}).get("success") or diagnostics.get("dns_ping", {}).get("success"))
    diagnostics["success"] = ok
    diagnostics["summary"] = "Connexion OK" if ok else "Connexion instable ou cible injoignable"
    return diagnostics


async def execute_net_inventory_scan(args: dict) -> dict:
    """Scanne le réseau local ET enregistre les appareils dans un inventaire PERSISTANT (pas
    un instantané jetable comme `net_scan_local` seul) — première vue/dernière vue conservées,
    permet un suivi dans le temps (nouvel appareil détecté, appareil disparu). Utilise ceci pour
    un vrai inventaire réseau, `net_scan_local` pour un coup d'œil ponctuel."""
    scan = await execute_net_scan_local({})
    if scan.get("error"):
        return scan
    devices = scan.get("devices", [])
    new_count = 0
    for d in devices:
        ip = d.get("ip", "")
        mac = d.get("mac", "")
        if not ip:
            continue
        hostname = ""
        try:
            import socket as _socket
            hostname = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, lambda: _socket.gethostbyaddr(ip)[0]),
                timeout=1.5,
            )
        except Exception:
            pass
        r = db.upsert_network_device(ip=ip, mac=mac, hostname=hostname)
        if r.get("new"):
            new_count += 1
    return {
        "success": True,
        "scanned": len(devices),
        "new_devices": new_count,
        "message": f"{len(devices)} appareil(s) scanné(s), {new_count} nouveau(x) dans l'inventaire.",
    }


async def execute_net_inventory_list(args: dict) -> dict:
    """Liste l'inventaire réseau PERSISTANT (appareils déjà vus, avec première/dernière
    apparition, nom personnalisé et notes si renseignés) — pas un scan en direct. Appelle
    `net_inventory_scan` d'abord si tu veux des données fraîches."""
    days = max(1, min(int(args.get("days", 30)), 365))
    devices = db.get_network_devices(days=days)
    return {"success": True, "count": len(devices), "period_days": days, "devices": devices}


async def execute_net_inventory_annotate(args: dict) -> dict:
    """Ajoute un nom personnalisé et/ou une note à un appareil de l'inventaire réseau (ex:
    « imprimante bureau », « switch salle serveur »)."""
    device_id = args.get("device_id", "").strip()
    if not device_id:
        return {"error": "Paramètre 'device_id' requis (obtenu via net_inventory_list)."}
    custom_name = args.get("custom_name")
    notes = args.get("notes")
    return db.set_network_device_notes(device_id, custom_name=custom_name, notes=notes)
