# Politique obligatoire de journalisation Marvin

Date de référence : 2026-07-28
Schéma : Marvin Structured Log 1.0
Périmètre : backend, Runner, outils, modèles, workers, API, Code Workspace, Forge,
VM/conteneurs, frontend, avatar, voix, installateur et scripts d'exploitation.

## 1. Obligation par évolution

La journalisation est une étape obligatoire de toute analyse, conception, implémentation,
revue et validation du projet. Chaque tranche doit documenter et tester :

1. les événements utiles à l'exploitation, à la sécurité et à la preuve de résultat ;
2. le composant, le nom d'événement, la sévérité, le résultat, la durée et le `trace_id`
   ou identifiant de corrélation lorsqu'un flux traverse plusieurs composants ;
3. les données explicitement interdites ou expurgées ;
4. la classe de rétention et la rotation applicables ;
5. le comportement en cas de disque plein, permission refusée ou journal indisponible ;
6. un test de non-divulgation et, pour un nouveau stockage, un test de rotation/rétention ;
7. l'impact sur les performances, le diagnostic et le rollback.

Une fonctionnalité nouvelle sans décision de journalisation explicite échoue au gate
d'architecture. « Aucun nouvel événement nécessaire » est recevable seulement si la décision
est motivée dans `DEVELOPMENT-JOURNAL.md`.

## 2. Référentiel et comparaison

Références primaires :

- OpenTelemetry Logs Data Model : timestamp, sévérité, `event_name`, ressource, attributs,
  `trace_id` et `span_id` — https://opentelemetry.io/docs/specs/otel/logs/data-model/
- OpenTelemetry Trace Context : représentation portable de `trace_id`, `span_id` et flags —
  https://opentelemetry.io/docs/specs/otel/compatibility/logging_trace_context/
- OWASP Logging Cheat Sheet : événements cohérents, données à exclure, résistance aux pannes,
  protection, supervision et destruction à l'échéance —
  https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- NIST SP 800-92 Rev. 1 : cycle générer, transmettre, stocker, consulter et éliminer —
  https://csrc.nist.gov/pubs/sp/800/92/r1/ipd
- OpenAI Agents SDK tracing : génération, outils, guardrails et corrélation de traces —
  https://openai.github.io/openai-agents-python/tracing/
- Google ADK observability : logs, traces, métriques et évaluation de trajectoire —
  https://adk.dev/observability/

Deux approches ont été comparées :

| Approche | Avantages | Limites |
|---|---|---|
| Windows Event Log comme stockage unique | intégration OS, ACL et outils d'administration | privilèges/installation d'une source, portabilité réduite, lecture moins simple |
| JSONL structuré local, export OpenTelemetry/Windows optionnel | portable, local-first, inspectable, sans service obligatoire | intégrité distante et requêtes avancées à ajouter si nécessaires |

Le JSONL structuré local est la source portable retenue. Windows Event Log, OTLP ou un SIEM
seront des exporteurs optionnels : leur absence ne doit pas bloquer le socle Marvin.

## 3. Schéma minimal

Tout nouvel événement structuré utilise au minimum :

- `schema_version` ;
- `timestamp` UTC au format RFC 3339 ;
- `severity_text` ;
- `event_name` stable, orienté machine ;
- `component` ;
- `outcome` (`success`, `failure`, `pending`, `cancelled` ou `degraded`) ;
- `trace_id` lorsqu'une demande, mission ou action est corrélable ;
- `duration_ms` pour toute opération mesurable ;
- `attributes` bornés et validés pour le contexte non sensible.

Les identifiants publics historiques peuvent rester présents pendant une migration compatible.
Les logs ne remplacent ni les métriques agrégées, ni les preuves Forge, ni les données métier.

## 4. Données interdites

Ne jamais stocker en clair dans un journal :

- mot de passe, token, cookie, secret, clé privée, chaîne de connexion ou en-tête
  d'autorisation ;
- prompt ou réponse LLM, corps d'e-mail, contenu de document, transcription, pièce jointe,
  script ou code utilisateur ;
- données personnelles non nécessaires à l'exploitation ;
- payload HTTP complet ou capture d'écran.

Quand une corrélation de contenu est nécessaire, conserver uniquement longueur, type et
SHA-256. Les messages d'erreur et tracebacks sont bornés et expurgés. Les journaux transmis
hors du PC requièrent une activation explicite, TLS, authentification et une politique de
minimisation au moins aussi stricte.

## 5. Rotation, rétention et budget disque

Valeurs par défaut, configurables avec bornes :

| Classe | Exemples | Rétention | Rotation | Budget maximal |
|---|---|---:|---:|---:|
| Audit | outils, approbations, mutations | 90 jours | quotidienne ou 10 Mio | 30 archives et 300 Mio |
| Incident | exceptions et erreurs exploitables | 30 jours | quotidienne ou 10 Mio | 30 archives et 300 Mio |
| Diagnostic détaillé temporaire | debug activé pour incident | 7 jours | quotidienne ou 10 Mio | 10 archives et 100 Mio |
| Agrégats qualité | SLO, Forge, tendances sans contenu | 180 jours | stockage dédié borné | selon contrat du composant |

La rotation s'effectue au changement de jour UTC ou avant dépassement de taille. La purge
s'effectue à l'écriture et à la lecture et applique trois limites simultanées : âge, nombre
d'archives et taille totale. Les archives les plus anciennes sont supprimées en premier.
Une politique réglementaire ou contractuelle peut changer ces valeurs, mais doit être
documentée; aucun journal n'est conservé indéfiniment par défaut.

Variables actuelles :

- `MARVIN_AUDIT_RETENTION_DAYS`, `MARVIN_AUDIT_MAX_BYTES`,
  `MARVIN_AUDIT_MAX_ARCHIVES`, `MARVIN_AUDIT_MAX_TOTAL_BYTES` ;
- `MARVIN_BUG_LOG_RETENTION_DAYS`, `MARVIN_BUG_LOG_MAX_BYTES`,
  `MARVIN_BUG_LOG_MAX_ARCHIVES`, `MARVIN_BUG_LOG_MAX_TOTAL_BYTES`.

## 6. Résilience, sécurité et supervision

- Le SLI HTTP utilise une fenêtre mémoire roulante d'une heure, au plus 20 000 échantillons
  et un minimum de 20 requêtes avant décision. Les objectifs initiaux sont 99 % de
  disponibilité et 95 % des requêtes sous deux secondes.
- Les décisions d'accès et d'idempotence utilisent uniquement des compteurs en mémoire à
  étiquettes fermées. Elles distinguent authentification, capacité, origine, CSRF, exécution,
  replay, conflit, résultat inconnu et panne de reçu sans conserver session, adresse, clé,
  empreinte, route métier ou charge utile. Un redémarrage remet volontairement ces compteurs
  à zéro; les anomalies nécessitant une enquête gardent leur incident corrélé dans les
  journaux structurés existants.
- Les probes `/api/health`, requêtes `OPTIONS`, `/api/chat` et routes terminées par `/stream`
  ne consomment pas le budget : leur fréquence ou leur durée intrinsèque fausserait le signal
  utilisateur. Elles restent comptées dans les métriques HTTP générales et les erreurs 5xx
  ou lenteurs continuent d'être journalisées.
- Le SLO n'enregistre ni route par échantillon, ni identifiant, ni contenu; seuls timestamp,
  statut et durée agrégés résident en mémoire. Un redémarrage remet volontairement la fenêtre
  à zéro et produit `insufficient`, jamais un faux succès.
- L'écriture est synchronisée dans le processus et la rotation utilise un renommage atomique.
- Une panne de journal est best-effort et ne transforme pas un succès métier en échec.
- Les tests simulent secrets, contenu, concurrence, rotation, expiration et limite d'archives.
- Le niveau nécessaire aux événements de sécurité ne peut pas être désactivé globalement.
- L'accès aux fichiers suit le compte utilisateur Marvin et n'exige pas l'administration.
- L'effacement administratif exige une confirmation explicite et laisse ensuite une nouvelle
  entrée d'audit attestant l'opération; les futurs exports sensibles devront être audités.
- Les erreurs de journalisation seront exposées par métrique bornée lors de la généralisation
  aux autres composants; aucun contenu sensible ne sera utilisé comme label de métrique.

## 7. Migration et rollback

La migration est progressive derrière les API existantes. `audit.py` et `bug_log.py`
conservent leurs fonctions publiques et leurs champs historiques, puis chaque autre JSONL
rejoint le même contrat avec un test de compatibilité.

Rollback de cette fondation : `git revert <commit>`, redémarrage backend, puis tests ciblés,
architecture, gate rapide, `/api/health` et smoke API. Les fichiers JSONL enrichis restent
lisibles par les anciens lecteurs grâce aux champs historiques; les champs supplémentaires
sont ignorables.
