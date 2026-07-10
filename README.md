# 🤖 SecretaryAI — Agent IA Secrétaire

Agent IA de secrétariat avec interface web : gestion d'emails, calendrier/RDV, et classement de fichiers. Propulsé par un modèle IA local (Ollama) — **aucune donnée ne quitte votre machine**.

![SecretaryAI](https://img.shields.io/badge/SecretaryAI-v1.0-8B5CF6?style=for-the-badge)
![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D6?style=for-the-badge&logo=windows)
![Ollama](https://img.shields.io/badge/Ollama-Local%20AI-000000?style=for-the-badge)

## ✨ Fonctionnalités

| Module | Fonctionnalités |
|--------|----------------|
| 💬 **Chat** | Conversation naturelle, appels d'outils automatiques, streaming temps réel |
| 📧 **Emails** | Lire, rechercher, rédiger, répondre (Gmail + Outlook) |
| 📅 **Calendrier** | Créer/modifier/supprimer RDV, vérifier disponibilités (Google + Outlook) |
| 📁 **Fichiers** | Explorer, renommer, déplacer, classer automatiquement par catégorie |
| 🔒 **Sécurité** | Données 100% locales, confirmation avant actions destructives, sandbox fichiers |

## 🚀 Installation rapide

### Prérequis
- Windows 10 ou 11
- Connexion Internet (pour l'installation uniquement)

### Installation automatique
```
Double-cliquez sur install.bat
```

Le script installera automatiquement :
1. ✅ Node.js (s'il n'est pas installé)
2. ✅ Ollama (s'il n'est pas installé)
3. ✅ Les dépendances du projet
4. ✅ Le modèle IA (qwen3:8b — ~5 Go)

### Lancement
```
Double-cliquez sur start.bat
```

Puis ouvrez **http://localhost:3000** dans votre navigateur.

## 📋 Configuration (optionnel)

Modifiez le fichier `.env.local` pour personnaliser :

```env
# Répertoire de fichiers géré par l'agent
FILE_SANDBOX_ROOT=C:\Users\MonNom\Documents

# Modèle Ollama (défaut: qwen3:8b)
OLLAMA_MODEL=qwen3:8b
```

### Connecter Gmail + Google Calendar
1. Allez sur [Google Cloud Console](https://console.cloud.google.com)
2. Créez un projet et activez Gmail API + Google Calendar API
3. Créez des identifiants OAuth 2.0
4. Ajoutez les ID dans `.env.local`

### Connecter Outlook + Outlook Calendar
1. Allez sur [Azure Portal](https://portal.azure.com)
2. Enregistrez une application
3. Ajoutez les permissions : Mail.ReadWrite, Calendars.ReadWrite
4. Ajoutez les ID dans `.env.local`

> 💡 **Sans configuration email/calendrier**, l'application fonctionne en **mode démo** avec des données simulées réalistes.

## 🗂️ Structure du projet

```
secretary-ai/
├── app/                  # Pages et API Routes (Next.js App Router)
│   ├── api/chat/         # 🧠 API principale du chatbot
│   ├── api/calendar/     # 📅 API calendrier
│   ├── api/files/        # 📁 API fichiers
│   ├── emails/           # Page emails
│   ├── calendar/         # Page calendrier
│   ├── files/            # Page fichiers
│   └── settings/         # Page paramètres
├── components/           # Composants React
├── lib/                  # Logique métier
│   ├── agent/tools.js    # 19 outils de l'agent IA
│   ├── services/         # Services (fichiers, démo, Gmail, Outlook)
│   └── ollama.js         # Client Ollama
├── install.bat           # 🔧 Script d'installation
├── start.bat             # ▶️ Script de démarrage
└── .env.local.example    # Template de configuration
```

## 🛠️ Développement

```bash
# Installer les dépendances
npm install

# Lancer en mode développement
npm run dev

# Construire pour la production
npm run build
npm start
```

## 📄 Licence

Projet propriétaire — Tous droits réservés.
