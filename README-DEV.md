# Destrava! — guia de desenvolvimento

## Estrutura

```
nucleo/        o agente (motor) que roda na máquina do cliente. SÓ biblioteca padrão do Python (3.8+).
               dd_backup.py (servidor local + tela), ficha, dados, otimizacoes, termo, mapa, disco, conexao, atualizador
               web/ (tela do agente). __init__.py liga o motor ao Django sem duplicar módulos.
config/        projeto Django do SERVIDOR DA LOJA (settings por variável de ambiente)
apps/home/     página pública em /
apps/servidor/ contrato HTTP do servidor da loja (auth, armazenamento, pacote, enderecos, views, comandos de chave)
static/        css e logos;  templates/base.html
tests/         unittest. Os do servidor se pulam sem Django; os do motor rodam em qualquer Python 3.8+
servidor-dados/, maquinas/, runtimes/   dados (fora do git e da imagem)
```

Regras que não podem quebrar (motor sem dependências, contrato HTTP, formato do zip…): `PROMPT-DJANGO.md`, R1–R5.

## Agente (motor)

```
sh testar-local.sh                    # Mac/Linux, dados de teste em ./_dev
python3 nucleo/dd_backup.py --dados .  # o mesmo que os lançadores Iniciar-*
sh testar-local.sh --coleta-salva tests/fixtures/win10_hd.json   # reproduz um Windows (ações simuladas)
```

## Servidor da loja (Django, precisa de Python 3.10+; no Docker é 3.13)

```
docker compose up -d --build web                          # http://localhost:8080 (healthcheck em /healthz)
docker compose exec web python manage.py nova_chave "Nome" # listar_chaves, revogar_chave "Nome"
docker compose --profile internet up -d tunel              # endereço público temporário (Cloudflare)
python3 nucleo/baixar_runtimes.py                          # Pythons fixos que o servidor entrega
```

Gunicorn com **1 worker** de propósito: o lock de gravação e a numeração de OS são por processo.

## Testes

```
python3 -m unittest discover tests        # motor (sem Django, os do servidor são pulados)
docker run --rm -v "$PWD":/app -w /app $(docker compose images -q web | head -1) python -m unittest discover tests   # tudo, com Django
docker run --rm -v "$PWD":/app -w /app python:3.8-slim python -m unittest discover tests                          # motor no Python 3.8
```
