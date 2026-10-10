"""Destrava! - servidor da loja. Tudo vem de variáveis de ambiente, com padrões seguros (DEBUG desligado)."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# dados dos clientes ficam em arquivos (R3): fichas, chaves e o log de consentimentos encadeado por hash
DESTRAVA_SERVIDOR_DADOS = Path(os.environ.get("DESTRAVA_SERVIDOR_DADOS") or BASE_DIR / "servidor-dados").resolve()
DESTRAVA_RUNTIMES = Path(os.environ.get("DESTRAVA_RUNTIMES") or BASE_DIR / "runtimes").resolve()
DESTRAVA_NUCLEO = BASE_DIR / "nucleo"
DESTRAVA_URL_PUBLICA = os.environ.get("DESTRAVA_URL_PUBLICA", "").strip().rstrip("/")

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"


def _chave_secreta():
    """DJANGO_SECRET_KEY do ambiente; sem ela, uma gerada uma vez e guardada nos dados do servidor (fora do git e da imagem)."""
    if os.environ.get("DJANGO_SECRET_KEY"):
        return os.environ["DJANGO_SECRET_KEY"]
    arq = DESTRAVA_SERVIDOR_DADOS / ".secret_key"
    try:
        return arq.read_text().strip()
    except OSError:
        pass
    chave = secrets.token_urlsafe(50)
    try:
        DESTRAVA_SERVIDOR_DADOS.mkdir(parents=True, exist_ok=True)
        arq.write_text(chave)
        os.chmod(arq, 0o600)
    except OSError:
        pass  # pasta só leitura (ex.: collectstatic no build): vale só para este processo
    return chave


SECRET_KEY = _chave_secreta()

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DESTRAVA_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
ALLOWED_HOSTS += [".trycloudflare.com", ".ts.net"]  # túneis (endereço muda a cada reinício)
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# sem admin, sem login humano, sem sessões: nenhum banco de dados (R3). Fichas e chaves ficam em arquivos.
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "apps.home",
    "apps.servidor",
]
DATABASES = {}

MIDDLEWARE = [
    "apps.servidor.middleware.SemCache",  # por fora de tudo: vale até para respostas de erro (R2)
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": []},
}]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = os.environ.get("TZ", "America/Sao_Paulo")
USE_I18N = False
USE_TZ = False

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {"staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
WHITENOISE_MANIFEST_STRICT = False  # sem collectstatic (testes, dev) usa o nome sem hash em vez de quebrar

# o PUT de arquivos de máquina vai até 10 MiB (MAX_ARQ); o limite de verdade é checado na view antes de ler o corpo
DATA_UPLOAD_MAX_MEMORY_SIZE = 11 * 1024 * 1024

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 31536000  # só vale em pedidos HTTPS (os que chegam pelo túnel)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SILENCED_SYSTEM_CHECKS = [
    "security.W008",  # SSL redirect: o acesso local (127.0.0.1:8080 e healthcheck) é http; o HTTPS vem do túnel
    "security.W003",  # CSRF: não há cookie, sessão nem formulário; a API é autenticada por chave Bearer
    "security.W005",  # HSTS em subdomínios: os túneis usam domínios compartilhados (trycloudflare.com, ts.net)
    "security.W021",  # HSTS preload: idem, não se aplica a domínio compartilhado
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"destrava": {"handlers": ["console"], "level": "INFO"}},
}
