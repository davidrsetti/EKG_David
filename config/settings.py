"""
config/settings.py — Centralised configuration for NEXUS platform.
All environment variables resolved here. Never import os.getenv elsewhere.
"""
from __future__ import annotations
import os
import ssl as _ssl
from dataclasses import dataclass, field
from dotenv import load_dotenv


# Load .env from the package root regardless of the working directory
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=False)
load_dotenv(override=False)  # also check CWD as fallback


def _patch_corporate_ssl() -> None:
    """
    Detect and remove broken SSL env vars set by corporate SSL inspection agents
    (e.g. Zscaler) that point to public-key files, stub strings, or directories
    that contain no valid CA certificates.

    Broken vars:
      SSL_CERT_FILE, REQUESTS_CA_BUNDLE — file paths to public keys / stubs
      SSL_CERT_DIR                       — directory with no valid CA certs

    Python's ssl / httpx rejects these, breaking all HTTPS calls to OpenAI.
    Removing them lets Python fall back to the OS certificate store
    (macOS Security framework), which already trusts the corporate root CA.

    Run AFTER load_dotenv() so any stubs in .env are also cleaned up.
    """
    import glob as _glob

    # ── File-based cert vars ───────────────────────────────────────────
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        path = os.environ.get(var, "").strip()
        if not path or path.lower() in ("false", "0", "none"):
            os.environ.pop(var, None)
            continue
        try:
            ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
            ctx.load_verify_locations(cafile=path)
        except (_ssl.SSLError, OSError):
            os.environ.pop(var, None)

    # ── Directory-based cert var ───────────────────────────────────────
    dir_path = os.environ.get("SSL_CERT_DIR", "").strip()
    if dir_path:
        # Validate: directory must contain at least one parseable PEM cert.
        # OpenSSL hashed cert dirs use *.0 files; plain dirs use *.pem.
        candidates = (
            _glob.glob(os.path.join(dir_path, "*.pem")) +
            _glob.glob(os.path.join(dir_path, "*.0"))
        )
        valid = False
        for f in candidates[:5]:
            try:
                ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
                ctx.load_verify_locations(cafile=f)
                valid = True
                break
            except (_ssl.SSLError, OSError):
                pass
        if not valid:
            os.environ.pop("SSL_CERT_DIR", None)

_patch_corporate_ssl()


@dataclass(frozen=True)
class StardogSettings:
    endpoint:     str  = field(default_factory=lambda: os.getenv("STARDOG_ENDPOINT", ""))
    token:        str  = field(default_factory=lambda: os.getenv("STARDOG_TOKEN", ""))
    auth_scheme:  str  = field(default_factory=lambda: os.getenv("STARDOG_AUTH_SCHEME", "Bearer"))
    database:     str  = field(default_factory=lambda: os.getenv("STARDOG_DB", "nexus"))
    verify_tls:   bool = field(default_factory=lambda: os.getenv("STARDOG_VERIFY_TLS", "false").lower() == "true")
    timeout:      int  = field(default_factory=lambda: int(os.getenv("STARDOG_TIMEOUT", "30")))


@dataclass(frozen=True)
class OpenAISettings:
    api_key:        str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    sparql_model:   str = field(default_factory=lambda: os.getenv("SPARQL_MODEL",   "o3-mini"))
    clarify_model:  str = field(default_factory=lambda: os.getenv("CLARIFY_MODEL",  "gpt-4o-mini"))
    answer_model:   str = field(default_factory=lambda: os.getenv("ANSWER_MODEL",   "gpt-4o"))
    guard_model:    str = field(default_factory=lambda: os.getenv("GUARD_MODEL",    "gpt-4o-mini"))
    max_tokens:     int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "2000")))


@dataclass(frozen=True)
class SecuritySettings:
    jwt_secret:         str  = field(default_factory=lambda: os.getenv("JWT_SECRET", "change-me-in-prod"))
    jwt_algorithm:      str  = "HS256"
    token_expire_mins:  int  = field(default_factory=lambda: int(os.getenv("TOKEN_EXPIRE_MINS", "480")))
    rate_limit_per_hour: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_HOUR", "60")))
    max_result_rows:    int  = field(default_factory=lambda: int(os.getenv("MAX_RESULT_ROWS", "500")))
    max_sparql_complexity: int = field(default_factory=lambda: max(int(os.getenv("MAX_SPARQL_COMPLEXITY", "25")), 25))


@dataclass(frozen=True)
class AuditSettings:
    sink:       str  = field(default_factory=lambda: os.getenv("AUDIT_SINK", "file"))  # file|postgres|azure_monitor
    log_path:   str  = field(default_factory=lambda: os.getenv("AUDIT_LOG_PATH", "logs/nexus_audit.jsonl"))
    db_url:     str  = field(default_factory=lambda: os.getenv("AUDIT_DB_URL", ""))
    enabled:    bool = field(default_factory=lambda: os.getenv("AUDIT_ENABLED", "true").lower() == "true")


@dataclass(frozen=True)
class DenodoSettings:
    endpoint:   str = field(default_factory=lambda: os.getenv("DENODO_ENDPOINT", ""))
    username:   str = field(default_factory=lambda: os.getenv("DENODO_USER", ""))
    password:   str = field(default_factory=lambda: os.getenv("DENODO_PASSWORD", ""))
    database:   str = field(default_factory=lambda: os.getenv("DENODO_DATABASE", "nexus_vdb"))
    enabled:    bool = field(default_factory=lambda: os.getenv("DENODO_ENABLED", "false").lower() == "true")


@dataclass(frozen=True)
class Settings:
    stardog:    StardogSettings  = field(default_factory=StardogSettings)
    openai:     OpenAISettings   = field(default_factory=OpenAISettings)
    security:   SecuritySettings = field(default_factory=SecuritySettings)
    audit:      AuditSettings    = field(default_factory=AuditSettings)
    denodo:     DenodoSettings   = field(default_factory=DenodoSettings)
    environment: str             = field(default_factory=lambda: os.getenv("NEXUS_ENV", "development"))

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


# Singleton — import this everywhere
settings = Settings()

# Fail fast in production if secrets are still at their insecure defaults
if settings.is_production and settings.security.jwt_secret == "change-me-in-prod":
    raise RuntimeError(
        "JWT_SECRET must be set to a strong secret value in production. "
        "Do not use the default 'change-me-in-prod' value."
    )