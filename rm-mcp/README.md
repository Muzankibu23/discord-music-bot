# Odoo MCP lecture seule (profil commercial)

Accès **uniquement en lecture** à : calendrier, CRM, ventes, projet, comptabilité
(+ partenaires/produits/devises comme référentiels). Toute autre demande
(écriture, suppression, RH, utilisateurs, paramètres…) répond :
« C'est pas possible ».

## Sécurité en 2 couches
1. **Code** : seules `search_read, read, search_count, read_group, fields_get`
   sont envoyées à Odoo, sur une liste blanche de modèles (`ALLOWED` dans `server.py`).
   Pas d'`execute_kw` générique, pas de bash.
2. **Odoo** (obligatoire) : crée un utilisateur dédié `mcp.commercial`
   - Droits d'accès : *Ventes › Utilisateur : documents propres* (ou « tous les documents »),
     *Calendrier*, *Projet › Utilisateur*, *Facturation › Lecture seule* (« Facturation: lecture »).
     **Aucun** droit Administration / Paramètres.
   - Profil → Sécurité du compte → **Nouvelle clé API** → mets-la dans `.env`.
   Les règles d'accès Odoo (record rules) restent donc appliquées en plus.

## Installation sur le VPS
```bash
sudo useradd -r -s /usr/sbin/nologin rmmcp
sudo mkdir -p /opt/rm-mcp && sudo cp server.py requirements.txt .env.example /opt/rm-mcp/
cd /opt/rm-mcp
sudo python3 -m venv venv && sudo venv/bin/pip install -r requirements.txt
sudo cp .env.example .env && sudo nano .env      # remplir + MCP_AUTH_TOKEN=$(openssl rand -hex 32)
sudo chown -R rmmcp: . && sudo chmod 600 .env
sudo cp rm-mcp.service /etc/systemd/system/ && sudo systemctl enable --now rm-mcp
```
Écoute sur `127.0.0.1:8765`. Expose-le via nginx/Caddy en HTTPS
(ex. `https://mcp.example.com/mcp`) et mets `MCP_ALLOWED_HOSTS=mcp.example.com` dans `.env`.

## Connexion côté client
URL : `https://mcp.example.com/mcp` — header `Authorization: Bearer <MCP_AUTH_TOKEN>`.
Ou en local (stdio) : `MCP_TRANSPORT=stdio python server.py`.

## Outils
`list_models`, `get_fields`, `search`, `get_record`, `count`, `group`, `refuse`.
Ajouter un modèle = l'ajouter dans `ALLOWED` (jamais de méthode d'écriture).
