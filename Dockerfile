FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo

WORKDIR /app
COPY . .

EXPOSE 8080
# servidor da loja (o docker-compose.yml também sobe o programa de demonstração, perfil dev)
CMD ["python", "servidor.py", "--host", "0.0.0.0", "--porta", "8080"]
