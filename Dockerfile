FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo \
    DJANGO_SETTINGS_MODULE=config.settings \
    DESTRAVA_SERVIDOR_DADOS=/app/servidor-dados \
    DESTRAVA_RUNTIMES=/app/runtimes

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# a chave aqui é só para o collectstatic do build; a de verdade vem do env ou de servidor-dados/.secret_key
RUN DJANGO_SECRET_KEY=so-para-o-build python manage.py collectstatic --noinput -v0

# usuário sem privilégios; servidor-dados/ é volume e precisa ser gravável por ele (UID 10001)
RUN useradd --uid 10001 --create-home destrava && mkdir -p servidor-dados runtimes && chown -R destrava:destrava /app
USER destrava

EXPOSE 8080
# 1 worker de propósito: o lock de gravação e a numeração de OS são por processo (ver PROMPT-DJANGO.md §5)
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8080", \
     "--workers", "1", "--threads", "8", "--timeout", "120", "--access-logfile", "-"]
