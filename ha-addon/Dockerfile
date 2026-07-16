# Add-on Home Assistant per SqueezeSay (web app vocale locale).
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.21
FROM $BUILD_FROM

# Senza TTY lo stdout di Python resta nel buffer: senza questo, il log
# dell'add-on non mostrerebbe la riga "Pronto: https://..." da aprire.
ENV PYTHONUNBUFFERED=1

# py3-cryptography precompilato (niente toolchain Rust): serve solo a generare
# il certificato TLS self-signed al primo avvio. Il server usa solo stdlib.
# L'entrypoint condiviso invoca "python": su Alpine esiste solo python3.
RUN apk add --no-cache python3 py3-cryptography \
 && ln -sf python3 /usr/bin/python

# L'add-on vive nello stesso repo dell'app, ma il Supervisor builda con questa
# sola cartella come contesto: il sorgente va scaricato dal repo pubblico.
# BUILD_VERSION cambia a ogni release dell'add-on e invalida la cache, così
# un update dell'add-on riscarica il codice aggiornato.
ARG BUILD_VERSION
RUN curl -sSL https://github.com/LucaBon/squeezesay/archive/refs/heads/main.tar.gz \
    | tar xz -C /tmp \
 && mkdir -p /app \
 && cp -r /tmp/squeezesay-main/engine /tmp/squeezesay-main/localvoice \
          /tmp/squeezesay-main/tools /tmp/squeezesay-main/deploy /app/ \
 && rm -rf /tmp/squeezesay-main

COPY run.sh /run.sh
RUN chmod +x /run.sh /app/deploy/docker/entrypoint.sh

CMD ["/run.sh"]
