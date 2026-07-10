"""
security.py — Garde de sécurité d'exécution (défense en profondeur).

Objectif : même si le LLM est manipulé (injection de prompt), même en niveau Expert,
même si l'utilisateur confirme par erreur, Marvin ne doit JAMAIS exécuter une commande
CATASTROPHIQUE et irréversible pour le système (formatage disque, effacement de la racine,
destruction du bootloader, fork bomb…).

GARDE-FOU EN DUR, volontairement conservateur : il ne bloque que le sous-ensemble
« destruction du système » — pas les actions dangereuses ordinaires (gérées par les
confirmations + niveaux de permission). Couvre Windows (cmd + PowerShell) et POSIX
(cibles `ssh_exec` souvent Linux).

Brique réutilisable du pattern « allowlist / séparation de privilèges » : un futur
exécuteur élevé (sidecar) ferait passer TOUTE commande par `screen_command()`.
"""
import re


def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


# ── Motifs catastrophiques « autonomes » (ordre des tokens sans importance) ────
_SIMPLE = [(_rx(p), lbl) for p, lbl in [
    (r"\bformat\s+[a-z]:",                                  "formatage d'un lecteur (format X:)"),
    (r"\bdiskpart\b[\s\S]*\bclean\b",                       "diskpart clean (efface un disque)"),
    (r"\bclean\s+all\b",                                    "clean all (efface un disque)"),
    (r"\b(format-volume|clear-disk|initialize-disk|remove-partition)\b",
                                                            "cmdlet PowerShell de destruction de disque"),
    (r"\bcipher\s+/w",                                      "cipher /w (effacement sécurisé du disque)"),
    (r"\bbcdedit\b[\s\S]*(/delete|/deletevalue)",          "bcdedit (destruction du démarrage)"),
    (r"--no-preserve-root",                                "rm --no-preserve-root (contournement de garde)"),
    (r"\bmkfs(\.\w+)?\b",                                   "mkfs (formatage de système de fichiers)"),
    (r"\bwipefs\b",                                         "wipefs (effacement de signatures FS)"),
    (r"\bdd\b[\s\S]*\bof=\s*/dev/(sd|nvme|hd|disk|mmcblk)", "dd vers un disque brut (/dev/…)"),
    (r">\s*/dev/(sd|nvme|hd|disk)[a-z0-9]*\b",             "redirection vers un disque brut"),
    (r"\bchmod\s+-r\s+0{1,4}\s+/(\s|$)",                   "chmod -R 000 / (verrouille le système)"),
    (r"\bchown\s+-r\s+\S+\s+/(\s|$)",                      "chown -R … / (casse les permissions système)"),
    (r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:?\s*&?\s*\}\s*;\s*:",  "fork bomb (:(){ :|:& };:)"),
    # rm -rf de la racine ou du home (les flags -r -f dans n'importe quel ordre)
    (r"\brm\b(?:\s+-[a-z]+)*\s+-[a-z]*(?:rf|fr)[a-z]*(?:\s+-[a-z]+)*\s+(?:--[a-z-]+\s+)*(/|/\*|~|~/|\$home|\$\{home\})(\s|$)",
                                                            "rm -rf de la racine / du home"),
]]

# ── Éléments pour règles COMPOSÉES (ordre indépendant) ─────────────────────────
_RECURSIVE_FLAG = _rx(r"(-recurse\b|\s/s\b|\s-r\b|\s-rf\b|\s-fr\b)")
_FORCE_QUIET    = _rx(r"(-force\b|\s/q\b|\s/f\b)")
# Chemin « racine de lecteur » (C:\, C:, D:\ …) — PAS un sous-dossier profond.
_DRIVE_ROOT     = _rx(r"(^|\s|['\"])[a-z]:\\?(\s|$|['\"]|\*|\\\*)")
# Dossiers système critiques.
_SYSTEM_PATH    = _rx(r"(c:\\windows\b|c:\\program files|\$env:systemroot|\$env:windir|"
                      r"c:\\users(\s|['\"]|\\\*|\\\s|$)|/etc(\s|/|$)|/usr(\s|/|$)|/var(\s|/|$)|/boot(\s|/|$)|/bin(\s|/|$))")
_DELETE_VERB    = _rx(r"(\bremove-item\b|\bdel\b|\berase\b|\brd\b|\brmdir\b|\brm\b|\bri\b|\brimraf\b)")


def screen_command(command: str) -> dict:
    """
    Analyse une commande shell/PowerShell brute AVANT exécution.
    Retourne {"allowed": bool, "reason": str|None, "match": str|None}.

    allowed=False => commande catastrophique à REFUSER en dur, quel que soit le
    niveau de permission ou la confirmation utilisateur.
    """
    if not command or not isinstance(command, str):
        return {"allowed": True, "reason": None, "match": None}
    # Normalisation anti-obfuscation : retire échappements PowerShell/cmd, compacte les espaces.
    norm = command.replace("`", "").replace("^", "")
    norm = re.sub(r"\s+", " ", norm).strip()

    for rx, label in _SIMPLE:
        if rx.search(norm):
            return _deny(label)

    # Règle composée : suppression RÉCURSIVE d'une racine de lecteur ou d'un dossier système.
    if _DELETE_VERB.search(norm) and _RECURSIVE_FLAG.search(norm):
        if _DRIVE_ROOT.search(norm) or _SYSTEM_PATH.search(norm):
            return _deny("suppression récursive d'une racine de lecteur ou d'un dossier système")

    return {"allowed": True, "reason": None, "match": None}


def _deny(label: str) -> dict:
    return {"allowed": False, "match": label,
            "reason": f"Commande refusée par la garde de sécurité : {label}. Cette action "
                      f"détruirait le système de façon irréversible. Si c'est réellement voulu, "
                      f"exécute-la toi-même manuellement, en connaissance de cause."}


def guard_result(command: str) -> dict | None:
    """Pour les exécuteurs : renvoie un dict d'ERREUR prêt à retourner si bloqué, sinon None.
        blocked = security.guard_result(cmd)
        if blocked: return blocked
    """
    v = screen_command(command)
    return None if v["allowed"] else {"error": "🛡️ " + v["reason"], "blocked": True,
                                       "security_block": v["match"]}


# v2.144 — trouvé en auditant une vraie conversation (« script d'installation zabbix sur
# debian ») : l'agent avait appelé `pc_run_command` avec un script écrit pour RHEL/CentOS
# (dnf, systemctl…) sur la machine Windows locale — sans dégât (dnf n'existe pas sous
# Windows) mais révélateur d'une confusion « écrire une commande » / « l'exécuter ICI ».
# PAS un blocage dur (une commande Linux/Unix n'est pas catastrophique en soi — WSL, test
# de syntaxe, etc. sont des usages légitimes) : enrichit juste le message de confirmation
# déjà obligatoire pour que l'HUMAIN voie l'alerte avant de cliquer, même si le jugement du
# modèle a échoué malgré la règle d'or #14.
_NON_WINDOWS_PATTERNS = [_rx(p) for p in [
    r"^#!\s*/bin/(ba)?sh\b", r"^#!\s*/usr/bin/env\s+(ba)?sh\b",
    r"\bsudo\s+", r"\bapt(-get)?\s+(install|update|upgrade|remove)\b",
    r"\bdnf\s+(-y\s+)?install\b", r"\byum\s+(-y\s+)?install\b", r"\bpacman\s+-S\b",
    r"\bsystemctl\s+(start|stop|enable|restart|status)\b", r"\bchmod\s+\+x\b",
    r"\buseradd\b", r"\bgroupadd\b", r"\bufw\s+(allow|enable|deny)\b",
    r"/etc/(apt|systemd|nginx|apache2|mysql|ssh)/", r"\bjournalctl\b",
    r"\bapt-get\b", r"\bsystemctl\b",
]]


def detect_cross_platform_mismatch(command: str) -> str | None:
    """Retourne un avertissement si la commande ressemble à du Linux/Unix (pas de blocage,
    juste un signal à afficher dans le dialogue de confirmation) — None sinon."""
    if not command or not isinstance(command, str):
        return None
    if any(rx.search(command) for rx in _NON_WINDOWS_PATTERNS):
        return ("⚠️ Cette commande ressemble à du Linux/Unix (sudo/apt/systemctl…) — elle ne "
                "fonctionnera pas telle quelle sur CETTE machine Windows. Si tu voulais juste "
                "le TEXTE du script (pour une autre machine), pas la peine de confirmer ; pour "
                "l'exécuter sur un serveur distant, utilise ssh_exec/ssh_write_and_run à la place.")
    return None
