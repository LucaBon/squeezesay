# Vivavoce — web app vocale locale, in un container.
#
#   docker compose up -d          # vedi docker-compose.yml (consigliato)
#   docker build -t vivavoce .
#   docker run --network host -v squeezesay-data:/data vivavoce
#
# L'immagine contiene la web app locale (localvoice/ + motore engine/).
# Il certificato TLS viene generato al primo avvio nel volume /data.
FROM python:3.12-slim

# Senza TTY lo stdout di Python resta nel buffer: senza questo, `docker logs`
# non mostrerebbe la riga "Pronto: https://..." con l'indirizzo da aprire.
ENV PYTHONUNBUFFERED=1

# cryptography serve solo a generare il certificato self-signed al primo avvio.
RUN pip install --no-cache-dir "cryptography>=42.0"

# Variante ASR (opzionale): --build-arg ASR=1 preinstalla faster-whisper per
# il riconoscimento vocale locale (endpoint /transcribe, funzione Pro).
# Aggiunge ~600 MB all'immagine; il modello Whisper viene scaricato al primo
# uso dentro /data (il volume), quindi sopravvive agli aggiornamenti.
ARG ASR=0
RUN if [ "$ASR" = "1" ]; then pip install --no-cache-dir "faster-whisper>=1.0"; fi

WORKDIR /app
COPY engine/ engine/
COPY localvoice/ localvoice/
COPY tools/make_cert.py tools/make_cert.py
COPY deploy/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME /data
EXPOSE 8730

ENTRYPOINT ["/entrypoint.sh"]
