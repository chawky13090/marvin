"""Régressions déterministes des périphériques Windows (imprimantes/USB/Bluetooth, v2.524).

Constat d'audit : aucun outil imprimante/USB/Bluetooth n'existait dans le projet.
Comblé avec le même patron que `windows_settings.py` (lecture sans confirmation,
mutation confirmée). Ces tests couvrent le parsing JSON réel de PowerShell, le rejet
d'un nom malveillant AVANT toute exécution, et la cohérence du registre d'outils.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import windows_devices


async def _run() -> None:
    calls: list[dict] = []

    async def fake_powershell(args: dict) -> dict:
        calls.append(args)
        script = args["script"]
        if "Get-Printer" in script:
            return {
                "returncode": 0,
                "stdout": (
                    '[{"Name":"Brother MFC-L3750CDW","DriverName":"Microsoft IPP Class Driver",'
                    '"PrinterStatus":0,"Default":true,"Shared":false}]'
                ),
                "stderr": "",
            }
        if "SetDefaultPrinter" in script:
            return {"returncode": 0, "stdout": "OK", "stderr": ""}
        if "USB*" in script:
            return {
                "returncode": 0,
                "stdout": '[{"FriendlyName":"Razer Naga V2","Class":"HIDClass","Status":"OK"}]',
                "stderr": "",
            }
        if "Bluetooth" in script:
            return {
                "returncode": 0,
                "stdout": (
                    '{"radios":{"FriendlyName":"Intel Wireless Bluetooth","Status":"OK"},'
                    '"paired":[]}'
                ),
                "stderr": "",
            }
        return {"returncode": 0, "stdout": "", "stderr": ""}

    windows_devices.configure(run_powershell=fake_powershell)

    # 1. Imprimantes : parsing JSON réel (objet unique -> liste).
    printers = await windows_devices.execute_pc_printer_list({})
    assert printers["success"] is True
    assert printers["count"] == 1
    assert printers["printers"][0]["Name"] == "Brother MFC-L3750CDW"

    # 2. USB.
    usb = await windows_devices.execute_pc_usb_list({})
    assert usb["success"] is True
    assert usb["devices"][0]["FriendlyName"] == "Razer Naga V2"

    # 3. Bluetooth : un radio unique (dict) est normalisé en liste.
    bt = await windows_devices.execute_pc_bluetooth_status({})
    assert bt["available"] is True
    assert bt["radios"][0]["FriendlyName"] == "Intel Wireless Bluetooth"
    assert bt["paired_devices"] == []

    # 4. Injection : un nom malveillant est rejeté AVANT tout appel PowerShell.
    calls.clear()
    malicious = await windows_devices.execute_pc_printer_set_default(
        {"name": "x'; Remove-Item C:\\*; '"}
    )
    assert "error" in malicious
    assert calls == [], "un nom invalide ne doit déclencher aucun appel PowerShell"

    # 5. Nom valide sans confirmation -> demande explicite.
    pending = await windows_devices.execute_pc_printer_set_default(
        {"name": "Brother MFC-L3750CDW"}
    )
    assert pending["requiresConfirmation"] is True

    # 6. Confirmé -> exécution réelle, nom injecté tel quel dans le script ciblé.
    applied = await windows_devices.execute_pc_printer_set_default(
        {"name": "Brother MFC-L3750CDW", "confirmed": True}
    )
    assert applied["success"] is True
    assert "Brother MFC-L3750CDW" in calls[-1]["script"]

    # 7. Cohérence du registre : chaque fonction publique du domaine doit être la
    # MÊME implémentation exposée par tools.py et son registre d'exécution.
    public_names = [
        name.removeprefix("execute_")
        for name in dir(windows_devices)
        if name.startswith("execute_pc_")
    ]
    assert len(public_names) == 4, public_names
    for public_name in public_names:
        implementation = getattr(windows_devices, f"execute_{public_name}")
        assert getattr(tools, f"execute_{public_name}") is implementation
        assert tools.TOOLS_REGISTRY[public_name] is implementation


def main() -> int:
    asyncio.run(_run())
    print(
        "Domaine périphériques Windows OK - imprimantes, USB, Bluetooth, "
        "injection rejetée et registre cohérent."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
