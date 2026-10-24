"""Login com Google (OpenID Connect, fluxo de código com PKCE).

O ID token vem direto do endpoint de token do Google, por HTTPS. Nesse caso a
especificação OIDC (Core 3.1.3.7) permite usar a validação TLS no lugar da
assinatura; as demais declarações do token são conferidas aqui.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from .models import is_ifc_email, normalize_email


AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
ALLOWED_DOMAIN = "ifc.edu.br"
FLOW_MAX_AGE = 10 * 60
CLOCK_SKEW = 5 * 60


class GoogleAuthError(Exception):
    """Falha no login com Google. "code" vai para a tela de login."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def is_configured(config):
    return all(
        config.get(key)
        for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")
    )


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def start(config, now=None):
    """Retorna a URL de autorização e os dados a guardar na sessão até o retorno."""
    flow = {
        "state": secrets.token_urlsafe(32),
        "nonce": secrets.token_urlsafe(32),
        "verifier": secrets.token_urlsafe(64),
        "created_at": int(time.time() if now is None else now),
    }
    challenge = _b64url(hashlib.sha256(flow["verifier"].encode()).digest())
    query = urllib.parse.urlencode(
        {
            "client_id": config["GOOGLE_CLIENT_ID"],
            "redirect_uri": config["GOOGLE_REDIRECT_URI"],
            "response_type": "code",
            "scope": "openid email",
            "state": flow["state"],
            "nonce": flow["nonce"],
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Só sugere a conta institucional; o domínio é conferido no retorno.
            "hd": ALLOWED_DOMAIN,
            "prompt": "select_account",
        }
    )
    return f"{AUTHORIZATION_ENDPOINT}?{query}", flow


def check_callback_state(flow, state, now=None):
    now = time.time() if now is None else now
    if (
        not isinstance(flow, dict)
        or not isinstance(state, str)
        or not hmac.compare_digest(state, flow.get("state", ""))
        or now - flow.get("created_at", 0) > FLOW_MAX_AGE
    ):
        raise GoogleAuthError("sessao", "Estado do login com Google ausente, divergente ou expirado.")


def exchange_code(config, code, verifier):
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": config["GOOGLE_CLIENT_ID"],
            "client_secret": config["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": config["GOOGLE_REDIRECT_URI"],
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            tokens = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise GoogleAuthError("google", f"Falha ao trocar o código no Google: {error}") from error
    if not isinstance(tokens, dict) or not isinstance(tokens.get("id_token"), str):
        raise GoogleAuthError("google", "Resposta do Google sem ID token.")
    return tokens


def id_token_email(id_token, config, nonce, now=None):
    """Confere o ID token e devolve o e-mail institucional verificado."""
    now = time.time() if now is None else now
    try:
        _, payload, _ = id_token.split(".")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, TypeError) as error:
        raise GoogleAuthError("google", "ID token malformado.") from error
    if not isinstance(claims, dict):
        raise GoogleAuthError("google", "ID token malformado.")
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    client_id = config["GOOGLE_CLIENT_ID"]
    exp, iat = claims.get("exp"), claims.get("iat")
    if (
        claims.get("iss") not in ISSUERS
        or client_id not in audiences
        or claims.get("azp", client_id) != client_id
        or not isinstance(exp, (int, float)) or exp <= now
        or not isinstance(iat, (int, float)) or iat > now + CLOCK_SKEW
        or not isinstance(claims.get("nonce"), str)
        or not hmac.compare_digest(claims["nonce"], nonce)
    ):
        raise GoogleAuthError("google", "ID token com emissor, público, validade ou nonce inválido.")
    email = normalize_email(claims.get("email"))
    if (
        claims.get("email_verified") not in (True, "true")
        or claims.get("hd") != ALLOWED_DOMAIN
        or not is_ifc_email(email)
    ):
        raise GoogleAuthError("dominio", "A conta Google não é um e-mail @ifc.edu.br verificado.")
    return email
