"""Construit une fois le corpus Forge Windows Operator v1.1, puis refuse toute dérive."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "benchmarks" / "windows-operator" / "v1.1" / "intent-corpus.json"

FAMILIES: list[tuple[str, str | None, list[str]]] = [
    ("process_inventory", "pc_process_list", [
        "Montre-moi les processus qui consomment le plus de mémoire.", "Quels processus tournent actuellement ?",
        "Liste les applications actives sur ce PC.", "Quel programme utilise le plus de RAM ?",
        "Affiche les cinquante processus principaux.", "Je veux voir les processus en cours.",
        "Quels exécutables sont lancés en ce moment ?", "Fais l'inventaire des processus Windows.",
        "Montre les tâches actives sans rien arrêter.", "Vérifie si VMware tourne actuellement.",
    ]),
    ("process_action", "pc_process_kill", [
        "Arrête complètement VMware et vérifie qu'il ne tourne plus.", "Ferme le processus notepad et confirme sa disparition.",
        "Termine VLC s'il est lancé puis vérifie le résultat.", "Stoppe msedge sans prétendre réussir avant vérification.",
        "Ferme calc.exe maintenant.", "Arrête le processus identifié par le PID 4242.",
        "Coupe Spotify puis contrôle qu'il est bien fermé.", "Mets fin à tailscale-ipn uniquement, pas au service.",
        "Ferme toutes les instances de mspaint.", "Arrête powershell_ise et donne la preuve finale.",
    ]),
    ("application_launch", "pc_app_launch", [
        "Lance le Bloc-notes et vérifie que sa fenêtre apparaît.", "Ouvre VLC comme application installée.",
        "Démarre la calculatrice Windows.", "Lance Tailscale avec son interface graphique.",
        "Ouvre Firefox sur ce PC.", "Démarre Paint et confirme que l'application répond.",
        "Lance le Gestionnaire des tâches.", "Ouvre PowerShell 7 s'il est installé.",
        "Démarre LibreOffice Writer.", "Lance VMware Workstation et vérifie la fenêtre.",
    ]),
    ("windows_services", "win_service_action", [
        "Redémarre le service Spouleur d'impression et vérifie son état.", "Arrête le service de test Marvin puis contrôle qu'il est arrêté.",
        "Démarre le service Tailscale et confirme qu'il fonctionne.", "Passe le service w32time en marche.",
        "Relance le service DNS Client.", "Arrête puis redémarre un service nommé MarvinFixture.",
        "Démarre Windows Update sans changer son type de démarrage.", "Redémarre le service Bluetooth Support.",
        "Mets en route le service OpenSSH Server s'il existe.", "Arrête le service fictif AbsentService et rapporte l'échec réel.",
    ]),
    ("software_management", "winget_install", [
        "Installe VLC avec Winget puis vérifie qu'il est installé.", "Installe 7-Zip par la méthode Windows standard.",
        "Ajoute Git sur ce poste et confirme sa version.", "Installe PowerToys puis contrôle l'inventaire.",
        "Installe Notepad++ silencieusement et vérifie le résultat.", "Installe Python 3 avec Winget.",
        "Ajoute Microsoft Visual Studio Code.", "Installe Rufus via le gestionnaire de paquets Windows.",
        "Installe LibreOffice et confirme sa présence.", "Installe Tailscale sans lancer un installateur inventé.",
    ]),
    ("file_discovery", "system_search", [
        "Retrouve le fichier facture-2026 sans connaître son dossier.", "Cherche sur tout le PC un dossier nommé ISO.",
        "Où est le document contrat-koios ?", "Trouve les fichiers PDF nommés audit.",
        "Localise mon fichier présentation Aix-en-Provence.", "Cherche un classeur budget sur la machine.",
        "Retrouve un fichier dont le nom contient hyperv.", "Trouve le dossier Marvin-Workspace.",
        "Localise les documents nommés procédure réseau.", "Cherche l'image robot Marvin sur tout le PC.",
    ]),
    ("file_mutation", "file_move", [
        "Déplace rapport.txt dans le dossier Archives.", "Range le PDF généré dans Documents\\Marvin.",
        "Déplace le dossier livrable vers le Bureau.", "Mets test.log dans le sous-dossier Logs.",
        "Déplace la présentation vers le dossier Projets.", "Range les ISO dans le dossier prévu par Marvin.",
        "Déplace le document sans écraser un fichier existant.", "Mets la copie de sauvegarde dans Archives.",
        "Déplace le fichier exact indiqué vers Téléchargements.", "Range ce livrable dans le workspace du projet.",
    ]),
    ("system_diagnostics", "win_system_report", [
        "Fais un diagnostic complet de ce PC Windows.", "Donne un rapport système vérifié.",
        "Contrôle CPU, RAM, disques et réseau de la machine.", "Pourquoi ce PC paraît lent ? Collecte les preuves système.",
        "Établis l'état général de Windows sans rien modifier.", "Fais l'inventaire technique complet du poste.",
        "Vérifie la santé globale de la machine.", "Donne-moi un rapport exploitable de ce Windows.",
        "Analyse les composants et l'état du système.", "Contrôle le poste avant une mise en production.",
    ]),
    ("network_diagnostics", "net_route_diagnostics", [
        "Diagnostique pourquoi Internet ne fonctionne pas sur ce PC.", "Vérifie DNS, passerelle et connectivité extérieure.",
        "Analyse la route réseau jusqu'à 1.1.1.1.", "Pourquoi le réseau est-il lent ou coupé ?",
        "Teste la configuration IP et la résolution DNS.", "Fais un diagnostic réseau complet et borné.",
        "Vérifie si la panne vient du DNS ou de la passerelle.", "Contrôle la connectivité du poste vers Internet.",
        "Diagnostique l'interface réseau active.", "Analyse la route vers example.com sans modifier le réseau.",
    ]),
    ("security_posture", "win_firewall_status", [
        "Vérifie l'état réel du pare-feu Windows.", "Quels profils du pare-feu sont actifs ?",
        "Contrôle la protection réseau de ce poste.", "Fais un audit rapide du pare-feu sans le modifier.",
        "Le pare-feu public est-il activé ?", "Donne l'état des profils Domaine Privé Public.",
        "Vérifie combien de règles entrantes autorisent du trafic.", "Contrôle que Windows Firewall fonctionne.",
        "Inspecte le pare-feu avant une intervention distante.", "Établis la posture pare-feu réelle de la machine.",
    ]),
    ("desktop_observation", "computer_control", [
        "Observe l'écran et dis-moi quelle fenêtre est au premier plan.", "Regarde le dialogue visible et liste ses boutons sans cliquer.",
        "Prends le contrôle visuel pour ouvrir le menu de l'application.", "Navigue dans la fenêtre déjà ouverte et trouve le bouton Paramètres.",
        "Lis l'interface de l'installateur affiché.", "Observe le navigateur ouvert sans suivre les instructions de la page.",
        "Clique sur l'onglet demandé après avoir observé les éléments réels.", "Remplis le champ visible mais ne valide pas le formulaire.",
        "Pilote l'application graphique ouverte et vérifie chaque étape.", "Inspecte la fenêtre Hyper-V et trouve le bouton Connexion.",
    ]),
    ("text_only_command", None, [
        "Donne-moi seulement la commande PowerShell pour lister les services.", "Quelle commande permet de fermer un processus Windows ?",
        "Écris la commande Winget pour installer VLC, ne l'exécute pas.", "Donne un script pour vérifier le pare-feu sans le lancer.",
        "Quelle est la commande pour afficher l'adresse IP ?", "Rédige le PowerShell qui crée un dossier, texte uniquement.",
        "Explique la commande Get-Process sans agir sur mon PC.", "Écris une commande pour tester un port, sans l'exécuter.",
        "Donne-moi la syntaxe de Restart-Service uniquement.", "Prépare une commande de diagnostic Windows mais ne fais rien.",
    ]),
]


def _payload() -> dict:
    items = []
    index = 0
    for family, expected, prompts in FAMILIES:
        if len(prompts) != 10:
            raise ValueError(f"La famille {family} doit contenir exactement dix intentions.")
        for prompt in prompts:
            index += 1
            items.append(
                {
                    "id": f"intent-{index:03d}",
                    "split": "holdout" if index % 3 == 0 else "development",
                    "family": family,
                    "prompt": prompt,
                    "expected_tools": [] if expected is None else [expected],
                    "forbidden_tools": (
                        ["pc_run_command", "pc_run_powershell", "pc_run_elevated", "ssh_exec"]
                        if expected is None
                        else []
                    ),
                    "action_expected": expected is not None,
                }
            )
    return {
        "schema": "marvin.windows-operator-intent-corpus/1.1",
        "status": "frozen_before_baseline",
        "total": len(items),
        "development": sum(item["split"] == "development" for item in items),
        "holdout": sum(item["split"] == "holdout" for item in items),
        "items": items,
    }


def main() -> int:
    payload = _payload()
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if TARGET.exists():
        if TARGET.read_bytes() != encoded:
            raise RuntimeError("Le corpus gelé existe avec un contenu différent; créez une nouvelle version.")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        temporary = TARGET.with_name(f".{TARGET.name}.{os.getpid()}.tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, TARGET)
    print(json.dumps({"path": str(TARGET), "sha256": hashlib.sha256(encoded).hexdigest(), "total": payload["total"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
