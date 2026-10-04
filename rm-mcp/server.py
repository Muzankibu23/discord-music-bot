"""Serveur MCP Odoo 100% lecture seule (profil « commercial »).

Garanties :
  1. Le code n'appelle QUE search_read / read / search_count / read_group /
     fields_get. Aucune autre méthode Odoo n'est exposée (pas de write, create,
     unlink, execute_kw générique...).
  2. Seuls les modèles de la liste blanche (calendrier, CRM, ventes, projet,
     comptabilité + référentiels) sont accessibles.
  3. Il faut aussi que l'utilisateur Odoo utilisé ait des droits en lecture
     seule (défense en profondeur, voir README).
"""
import functools
import hmac
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

ODOO_URL = os.environ["ODOO_URL"].rstrip("/")
ODOO_DB = os.environ["ODOO_DB"]
ODOO_LOGIN = os.environ["ODOO_LOGIN"]
ODOO_API_KEY = os.environ["ODOO_API_KEY"]
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
MAX_LIMIT = int(os.environ.get("MAX_LIMIT", "200"))

# --- Liste blanche : domaine fonctionnel -> modèles Odoo -------------------
ALLOWED: dict[str, list[str]] = {
    "calendrier": ["calendar.event", "calendar.attendee"],
    "crm": ["crm.lead", "crm.stage", "crm.team", "crm.tag", "crm.lost.reason"],
    "ventes": [
        "sale.order", "sale.order.line", "product.template", "product.product",
        "product.category", "crm.team",
    ],
    "projet": ["project.project", "project.task", "project.task.type", "project.tags"],
    "comptabilite": [
        "account.move", "account.move.line", "account.payment", "account.journal",
        "account.account", "account.tax", "account.payment.term",
    ],
    "referentiels": ["res.partner", "res.partner.category", "res.company", "res.currency", "uom.uom"],
}
ALLOWED_MODELS = {m for models in ALLOWED.values() for m in models}

# Seules ces méthodes (toutes en lecture) sont jamais envoyées à Odoo.
READ_METHODS = {"search_read", "read", "search_count", "read_group", "fields_get"}

VALID_OPS = {
    "=", "!=", ">", ">=", "<", "<=", "like", "ilike", "not like", "not ilike",
    "=like", "=ilike", "in", "not in", "child_of", "parent_of", "=?",
}
LOGIC = {"&", "|", "!"}

REFUSAL = "C'est pas possible : ce serveur est en lecture seule et limité au calendrier, CRM, ventes, projet et comptabilité."


class Refused(Exception):
    pass


class Odoo:
    def __init__(self) -> None:
        self.http = httpx.Client(timeout=30)
        self.uid: int | None = None

    def _rpc(self, service: str, method: str, args: list) -> Any:
        r = self.http.post(
            f"{ODOO_URL}/jsonrpc",
            json={"jsonrpc": "2.0", "method": "call", "id": 1,
                  "params": {"service": service, "method": method, "args": args}},
        )
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            err = data["error"].get("data", {}).get("message") or data["error"].get("message")
            raise Refused(f"Odoo a refusé la requête : {err}")
        return data["result"]

    def read_call(self, model: str, method: str, args: list, kwargs: dict | None = None) -> Any:
        # Verrous de sécurité côté code
        if model not in ALLOWED_MODELS:
            raise Refused(f"{REFUSAL} (modèle « {model} » non autorisé)")
        if method not in READ_METHODS:
            raise Refused(REFUSAL)
        if self.uid is None:
            self.uid = self._rpc("common", "authenticate", [ODOO_DB, ODOO_LOGIN, ODOO_API_KEY, {}])
            if not self.uid:
                raise Refused("Authentification Odoo échouée (login / clé API).")
        return self._rpc("object", "execute_kw",
                         [ODOO_DB, self.uid, ODOO_API_KEY, model, method, args, kwargs or {}])


odoo = Odoo()


def _check_domain(domain: list | None) -> list:
    domain = domain or []
    if not isinstance(domain, list):
        raise Refused("Le domaine doit être une liste.")
    clean = []
    for term in domain:
        if isinstance(term, str):
            if term not in LOGIC:
                raise Refused(f"Opérateur logique invalide : {term}")
            clean.append(term)
        elif isinstance(term, (list, tuple)) and len(term) == 3 and isinstance(term[0], str) and term[1] in VALID_OPS:
            clean.append(list(term))
        else:
            raise Refused(f"Condition invalide : {term!r} (attendu [champ, opérateur, valeur])")
    return clean


def _guard(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Refused as e:
            return {"error": str(e)}
        except httpx.HTTPError as e:
            return {"error": f"Erreur réseau vers Odoo : {e}"}
    return wrapper


# --- Serveur MCP ------------------------------------------------------------
allowed_hosts = [h for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h]
mcp = FastMCP(
    "rm-mcp",
    host=os.environ.get("MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("MCP_PORT", "8765")),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(allowed_hosts),
        allowed_hosts=allowed_hosts,
        allowed_origins=["*"],
    ),
)


@mcp.tool()
@_guard
def list_models() -> dict:
    """Liste les modèles Odoo accessibles (lecture seule), par domaine."""
    return ALLOWED


@mcp.tool()
@_guard
def get_fields(model: str) -> dict:
    """Décrit les champs d'un modèle autorisé (nom, type, libellé)."""
    f = odoo.read_call(model, "fields_get", [], {"attributes": ["string", "type", "relation", "selection"]})
    return f


@mcp.tool()
@_guard
def search(model: str, domain: list | None = None, fields: list[str] | None = None,
           limit: int = 50, offset: int = 0, order: str | None = None) -> Any:
    """Recherche des enregistrements (lecture seule).
    domain ex: [["stage_id.name","=","Won"],["expected_revenue",">",1000]]"""
    kw: dict = {"limit": max(1, min(limit, MAX_LIMIT)), "offset": max(0, offset)}
    if fields:
        kw["fields"] = fields
    if order:
        kw["order"] = order
    return odoo.read_call(model, "search_read", [_check_domain(domain)], kw)


@mcp.tool()
@_guard
def get_record(model: str, record_id: int, fields: list[str] | None = None) -> Any:
    """Lit un enregistrement par son id."""
    kw = {"fields": fields} if fields else {}
    return odoo.read_call(model, "read", [[record_id]], kw)


@mcp.tool()
@_guard
def count(model: str, domain: list | None = None) -> int:
    """Compte les enregistrements correspondant au domaine."""
    return odoo.read_call(model, "search_count", [_check_domain(domain)])


@mcp.tool()
@_guard
def group(model: str, fields: list[str], groupby: list[str], domain: list | None = None,
          limit: int = 100, order: str | None = None) -> Any:
    """Agrégats (somme, compte) groupés. ex: model=sale.order, fields=["amount_total:sum"], groupby=["partner_id"]"""
    kw: dict = {"lazy": False, "limit": max(1, min(limit, MAX_LIMIT))}
    if order:
        kw["orderby"] = order
    return odoo.read_call(model, "read_group", [_check_domain(domain), fields, groupby], kw)


@mcp.tool()
def refuse(request: str = "") -> str:
    """À appeler quand l'utilisateur demande une écriture/modification/suppression
    ou un sujet hors calendrier/CRM/ventes/projet/comptabilité."""
    return REFUSAL


class BearerAuth:
    """Middleware ASGI : accepte soit 'Authorization: Bearer <token>', soit le
    token dans le chemin : /<token>/mcp (pour les custom connectors claude.ai,
    qui ne permettent pas de header personnalisé)."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            prefix = f"/{MCP_AUTH_TOKEN}"
            path = scope["path"]
            ok = False
            if path == prefix or path.startswith(prefix + "/"):
                ok = True
                scope = dict(scope, path=path[len(prefix):] or "/",
                             raw_path=scope.get("raw_path", b"")[len(prefix):] or b"/")
            else:
                auth = dict(scope["headers"]).get(b"authorization", b"").decode()
                ok = hmac.compare_digest(auth, f"Bearer {MCP_AUTH_TOKEN}")
            if not ok:
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self.app(scope, receive, send)


def build_app():
    if not MCP_AUTH_TOKEN or len(MCP_AUTH_TOKEN) < 24:
        raise SystemExit("MCP_AUTH_TOKEN manquant ou trop court (>= 24 caractères).")
    return BearerAuth(mcp.streamable_http_app())


if __name__ == "__main__":
    if os.environ.get("MCP_TRANSPORT", "http") == "stdio":
        mcp.run("stdio")
    else:
        import uvicorn
        uvicorn.run(build_app(), host=mcp.settings.host, port=mcp.settings.port)
