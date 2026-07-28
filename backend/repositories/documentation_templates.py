"""Catalogue statique des modèles de documentation technique intégrés."""

DEFAULT_DOCUMENT_TEMPLATES = (
    (
        "report",
        "Rapport d'intervention standard",
        "Compte rendu professionnel d'une intervention sur site ou à distance",
        """# Compte rendu d'intervention {{number}}

**Date :** {{date}}    **Technicien :** {{technician}}    **Durée :** {{duration}}

## Client
{{client_block}}

## Contexte
{{context}}

## Diagnostic
{{diagnostic}}

## Actions réalisées
{{actions}}

## Commandes exécutées
```
{{commands}}
```

## Résultat
{{resolution}}

## Recommandations
{{recommendations}}

---
*Rapport généré automatiquement par Marvin AI.*
""",
    ),
    (
        "procedure",
        "Procédure technique pas-à-pas",
        "Procédure reproductible pour intervention type (déploiement, configuration…)",
        """# Procédure : {{title}}

**Version :** 1.0    **Date :** {{date}}    **Auteur :** {{technician}}    **Difficulté :** {{difficulty}}

## Objectif
{{objective}}

## Prérequis
{{prerequisites}}

## Matériel/Outils nécessaires
{{tools_required}}

## Procédure détaillée

{{steps}}

## Commandes
```
{{commands}}
```

## Vérification & validation
{{validation}}

## Retour arrière (rollback)
{{rollback}}

## Notes & pièges à éviter
{{notes}}

---
*Procédure documentée par Marvin AI.*
""",
    ),
    (
        "client_sheet",
        "Fiche client (infrastructure)",
        "Synthèse complète de l'infrastructure d'un client",
        """# Fiche client : {{client_name}}

**Type :** {{client_type}}    **Contact principal :** {{contact}}    **Téléphone :** {{phone}}    **Email :** {{email}}

## Présentation
{{presentation}}

## Infrastructure

### Postes de travail
{{workstations}}

### Serveurs
{{servers}}

### Réseau
{{network}}

### Sécurité
{{security}}

### Sauvegarde
{{backup}}

## Contrats en cours
{{contracts}}

## Historique des interventions (12 derniers mois)
{{history}}

## Contacts techniques
{{contacts}}

---
*Fiche maintenue par Marvin AI. Dernière mise à jour : {{date}}.*
""",
    ),
    (
        "recovery_plan",
        "Plan de reprise d'activité (PRA/PCA)",
        "Plan formel de continuité et reprise après sinistre",
        """# Plan de Reprise d'Activité — {{client_name}}

**Version :** 1.0    **Date :** {{date}}    **Validé par :** {{validator}}

## 1. Périmètre
{{scope}}

## 2. Analyse de risques
| Risque | Probabilité | Impact | Priorité |
|--------|-------------|--------|----------|
{{risks_table}}

## 3. Indicateurs de continuité

| Service | RTO (Recovery Time) | RPO (Recovery Point) |
|---------|---------------------|----------------------|
{{services_table}}

## 4. Architecture de sauvegarde
{{backup_arch}}

## 5. Procédure de reprise
{{recovery_steps}}

## 6. Tests réguliers
{{tests}}

## 7. Contacts d'urgence
{{contacts}}

## 8. Annexes
{{annexes}}

---
*PRA généré par Marvin AI conformément aux bonnes pratiques ISO 22301.*
""",
    ),
    (
        "maintenance",
        "Procédure de maintenance préventive",
        "Checklist de maintenance régulière (mensuelle/trimestrielle/annuelle)",
        """# Procédure de maintenance préventive

**Périodicité :** {{frequency}}    **Client :** {{client_name}}    **Durée estimée :** {{duration}}

## Checklist

### 🖥️ Postes de travail
- [ ] Mises à jour Windows
- [ ] Mises à jour applicatives (navigateurs, Office, etc.)
- [ ] Analyse antivirus complète
- [ ] Nettoyage fichiers temporaires
- [ ] Vérification espace disque
- [ ] Tests de sauvegarde
{{workstation_extra}}

### 🖥️ Serveurs
- [ ] Mises à jour Windows Server / Linux
- [ ] Vérification logs système (erreurs critiques)
- [ ] Vérification état RAID / disques
- [ ] Vérification sauvegardes (intégrité + restauration)
- [ ] Vérification certificats SSL/TLS
- [ ] Mise à jour antivirus serveur
{{server_extra}}

### 🌐 Réseau
- [ ] État liens WAN/LAN
- [ ] Logs firewall (tentatives d'intrusion)
- [ ] Vérification Wi-Fi (puissance, perfs)
- [ ] Sauvegarde configuration équipements
{{network_extra}}

### 🔐 Sécurité
- [ ] Revue des accès utilisateurs
- [ ] Vérification politique mots de passe
- [ ] Test restauration sauvegarde
- [ ] Mises à jour antivirus
{{security_extra}}

## Anomalies détectées
{{anomalies}}

## Actions correctives recommandées
{{corrective_actions}}

---
*Maintenance documentée par Marvin AI.*
""",
    ),
    (
        "runbook",
        "Runbook (procédure d'urgence)",
        "Procédure d'intervention rapide en cas d'incident critique",
        """# 🚨 RUNBOOK — {{title}}

**Sévérité :** {{severity}}    **Service impacté :** {{service}}    **Auteur :** {{technician}}

## ⚡ Symptômes
{{symptoms}}

## 🎯 Impact business
{{business_impact}}

## 🔍 Diagnostic rapide
{{diagnostic_steps}}

## 🛠️ Actions de remédiation

### Étape 1 — Mitigation immédiate
{{step1}}

### Étape 2 — Investigation
{{step2}}

### Étape 3 — Résolution
{{step3}}

### Étape 4 — Vérification
{{step4}}

## 📞 Escalade
- **Niveau 1 :** {{level1_contact}}
- **Niveau 2 :** {{level2_contact}}
- **Niveau 3 (urgence) :** {{level3_contact}}

## 📋 Post-mortem
À remplir après l'incident :
- Cause racine identifiée :
- Actions préventives à mettre en place :
- Documentation à mettre à jour :

---
*Runbook Marvin AI.*
""",
    ),
    (
        "schema",
        "Schéma logique (Mermaid)",
        "Schéma d'architecture réseau ou logique en Mermaid",
        """```mermaid
graph TB
    subgraph "Internet"
        WAN[FAI / Internet]
    end
    subgraph "DMZ"
        FW[Firewall]
        WAN --> FW
    end
    subgraph "LAN"
        SW[Switch Principal]
        FW --> SW
        SV[Serveur AD/DC]
        SF[Serveur Fichiers]
        SW --> SV
        SW --> SF
    end
    subgraph "Postes"
        SW --> PC1[Poste 1]
        SW --> PC2[Poste 2]
        SW --> PCN[...Poste N]
    end
```
""",
    ),
)
