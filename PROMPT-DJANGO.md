# Prompt — transformar o Destrava! em um web app Django (home + Docker na porta 8080)

> Especificação usada para reorganizar o servidor da loja em Django. Mantida no repositório como referência
> das regras R1–R5 (o que NÃO pode mudar). O que foi implementado está descrito em README-DEV.md.

## 1. Três modos do Destrava!

1. **Pendrive / local** — `dd_backup.py` sobe um servidor HTTP (`http.server`) na máquina atendida e abre
   `web/app.html` no navegador. Lê hardware e discos: **roda na máquina do cliente**.
2. **Servidor da loja** — entrega o pacote `Destrava.zip` + um Python fixo, autentica técnicos por chave `Bearer`
   e guarda fichas, históricos e o log de consentimentos em `servidor-dados/`. **É o que vira Django.**
3. **Desenvolvimento** — `testar-local.sh` / `Testar-Windows.bat` com dados em `_dev/`.

## 2. Objetivo

Servidor da loja como **web app Django** servido por Gunicorn em container na **porta 8080**, com uma **home**
própria, mantendo o agente (`dd_backup.py` e módulos) funcionando exatamente como antes.

## 3. Restrições invioláveis

**R1 — O motor continua stdlib-only.** `dd_backup.py`, `ficha.py`, `dados.py`, `otimizacoes.py`, `termo.py`,
`atualizador.py`, `conexao.py` (e `disco.py`, `mapa.py`) rodam no Python embeddable do Windows e num tarball de
Python em `/tmp`, sem pip, sem internet e sem Django. Nenhum deles importa Django ou pacote de terceiros.
Django importa esses módulos; eles nunca importam Django.

**R2 — O contrato HTTP do servidor da loja não muda.** `conexao.py`, `iniciar.sh` e `iniciar.ps1` já estão em
campo. Estas rotas respondem igual (métodos, corpos JSON, códigos):

```
GET    /                                  → HTML da home                       (público)
GET    /iniciar.ps1                       → text/plain, com __SERVIDOR__ resolvido (público)
GET    /iniciar.sh                        → text/plain, com __SERVIDOR__ resolvido (público)
GET    /api/quem                          → {"tecnico": str, "versao": str}
GET    /pacote/info                       → {"versao","sha256","runtimes":{...}}
GET    /pacote/info?formato=txt           → text/plain  versao=…\nsha256=…\nruntime_<k>=…
GET    /pacote/Destrava.zip               → application/zip (anexo), entradas com prefixo "Destrava/"
GET    /runtime/<nome>                    → application/octet-stream, streaming
GET    /api/maquinas                      → {"maquinas": [...]}
GET    /api/maquina/<mid>                 → {"arquivos": {nome: conteudo}}
GET    /api/log?mid=<mid>                 → {"linhas": [...]}
GET    /api/log/verificar                 → resultado de termo.verificar_linhas
POST   /api/log                           → linha gravada (hash encadeado, hora do servidor, nº de OS)
POST   /api/resolver                      → {"mid": str}
PUT    /api/maquina/<mid>/<arquivo>       → {"ok": true}   corpo application/octet-stream
DELETE /api/maquina/<mid>                 → {"ok": true}
```

Tudo exceto `/`, `/iniciar.sh` e `/iniciar.ps1` exige `Authorization: Bearer <chave>`; sem chave válida →
`401 {"erro": "Chave de técnico inválida."}`; IP bloqueado → `429 {"erro": "Muitas tentativas com chave errada.
Espere alguns minutos."}`; `ValueError` → `400 {"erro": <mensagem>}`; erro inesperado →
`500 {"erro": "Erro interno do servidor."}` (sem traceback). `Cache-Control: no-store` e
`X-Content-Type-Options: nosniff` em todas as respostas.

**R3 — Os dados dos clientes ficam onde estão.** `servidor-dados/` (`maquinas/`, `chaves.json`,
`consentimentos.log`), caminho de `DESTRAVA_SERVIDOR_DADOS`. Nada vai para o ORM: o log de consentimentos é
prova encadeada por hash.

**R4 — O pacote entregue continua idêntico em forma.** Entradas `Destrava/dd_backup.py`, `Destrava/web/app.html`…,
`date_time=(2020,1,1,0,0,0)`, `.sh` com `0o755`, SHA-256 estável. Lista fechada (`atualizador._is_code` +
exclusão do que é só do servidor). **Nenhum arquivo do Django, nenhuma chave, nenhum dado de cliente no zip.**

**R5 — Nada de regressão de segurança.** Hash+sal das chaves (`sha256(sal+chave)`), comparação em tempo
constante, `MAX_ARQ = 10 MiB` / `MAX_JSON = 256 KiB`, `MID_RE` / `ARQ_RE` / `EVENTO_RE` / `HOST_RE`, gravação
atômica (`.tmp` + `os.replace`), `chmod 600` em `chaves.json`, descarte de `n`/`prev`/`hash`/`tecnico_servidor`/
`quando_pc` vindos do cliente em `POST /api/log`.

## 4. Estrutura

`config/` (projeto Django), `apps/home` (home pública), `apps/servidor` (auth, armazenamento, pacote, enderecos,
views, commands `nova_chave` / `listar_chaves` / `revogar_chave`), `nucleo/` (o motor, conteúdo intocado),
`static/` (css, logos), `templates/base.html`, `tests/`. `servidor.py` e `servidor_web/` deixam de existir.

## 5. Lado Django

Views sem DRF (`JsonResponse` + `csrf_exempt`); decorator `@exige_tecnico` (IP: CF-Connecting-IP →
X-Forwarded-For[0] → REMOTE_ADDR); decorator de erros; **1 worker Gunicorn com threads** (lock e numeração de
OS são por processo; escalar exige `fcntl.flock`, TODO). `iniciar.sh`/`iniciar.ps1` como texto cru
(`str.replace` de `__SERVIDOR__`), nunca pelo engine de template. `DESTRAVA_URL_PUBLICA` tem prioridade; senão
deriva do pedido, com `SECURE_PROXY_SSL_HEADER`, `USE_X_FORWARDED_HOST` e `CF-Visitor`. WhiteNoise para estáticos.
`/runtime/<nome>` com `FileResponse`.

Env: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` (0), `DESTRAVA_ALLOWED_HOSTS`, `DESTRAVA_SERVIDOR_DADOS`,
`DESTRAVA_URL_PUBLICA`, `TZ=America/Sao_Paulo`.

## 6. Home

Identidade (logo, "Destrava!", "D&D Technology", "Somos únicos. Somos diferentes. Somos D&D."); comandos
copiáveis (Windows: `irm …/iniciar.ps1 | iex`; Mac/Linux: `curl -fsSL …/iniciar.sh | sh`); o que acontece em 4
passos, dizendo que fichas, históricos e termos ficam no servidor da loja; estado do servidor (versão, SHA curto,
runtimes, aviso se falta algum). **Nada** de máquinas, clientes ou técnicos. CSS próprio, sem CDN, claro/escuro,
360 px, foco visível, AA, `lang="pt-BR"`; o único JS é o Copiar e ele degrada.

## 7. Docker

Gunicorn na **8080** no container, compose publica `127.0.0.1:8080:8080`; `servidor-dados/` e `runtimes/` por
volume; usuário sem privilégio (UID 10001); túneis `tunel`/`tunel-fixo` apontando para `http://web:8080`;
`agente-demo` (perfil `dev`) na 8081; healthcheck `GET /healthz` → `{"ok": true}`.

## 8. Aceite

`manage.py check --deploy` limpo; suíte verde; healthz; home com a URL certa; commands de chave; `/api/quem` com e
sem chave; `iniciar.sh` idêntico ao anterior a menos do `__SERVIDOR__`; agente ponta a ponta contra o Django com
`/api/log/verificar` íntegro; zip extraído roda **sem Django**; sem referência órfã a `servidor.py`/`servidor_web`;
LEIA-ME atualizado.

## 9. Fora do escopo

Transformar o agente em views; migrar fichas/consentimentos para o ORM; DRF, Celery, Redis, Postgres, nginx, Node,
CDN; "modernizar" o motor; reescrever `web/app.html`; mudar rotas, campos, códigos ou o formato do zip; comitar
`chaves.json`, `servidor-dados/`, `maquinas/`, `runtimes/` ou `.env`; `DEBUG=1` ou `SECRET_KEY` fixa no repositório.

## 10. Decisões tomadas (§11 original)

Área do técnico no navegador: fora desta etapa. Django admin: desligado (sem banco). Chaves: continuam em
`chaves.json`. Gunicorn: 1 worker.
