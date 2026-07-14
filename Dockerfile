# SqueezeSay — web app vocale locale, in un container.
#
#   docker compose up -d          # vedi docker-compose.yml (consigliato)
#   docker build -t squeezesay .
#   docker run --network host -v squeezesay-data:/data squeezesay
#
# L'immagine contiene solo la web app locale (localvoice/ + motore lambda/):
# la skill Alexa si deploya a parte (vedi DEPLOY.md). Il certificato TLS viene
# generato al primo avvio nel volume /data.
FROM python:3.12-slim

# Senza TTY lo stdout di Python resta nel buffer: senza questo, `docker logs`
# non mostrerebbe la riga "Pronto: https://..." con l'indirizzo da aprire.
ENV PYTHONUNBUFFERED=1

# cryptography serve solo a generare il certificato self-signed al primo avvio.
RUN pip install --no-cache-dir "cryptography>=42.0"

WORKDIR /app
COPY lambda/ lambda/
COPY localvoice/ localvoice/
COPY tools/make_cert.py tools/make_cert.py
COPY deploy/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME /data
EXPOSE 8730

ENTRYPOINT ["/entrypoint.sh"]
