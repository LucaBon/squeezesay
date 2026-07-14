#!/bin/sh
# Traduce le opzioni dell'add-on nelle variabili SQUEEZESAY_* e delega
# all'entrypoint condiviso con l'immagine Docker standalone.
#
# Le opzioni si leggono direttamente da /data/options.json (che il Supervisor
# scrive sempre) con jq, non via bashio: le bashio recenti interrogano l'API
# del Supervisor, che non esiste quando si testa il container fuori da Home
# Assistant. /data è lo storage persistente dell'add-on: il certificato TLS
# generato al primo avvio sopravvive a riavvii e update.
set -eu

OPTS=/data/options.json

opt() {
    if [ -f "$OPTS" ]; then
        jq -r --arg k "$1" '.[$k] // empty' "$OPTS"
    fi
}

export SQUEEZESAY_DATA_DIR=/data

PORT="$(opt port)"
if [ -n "$PORT" ]; then
    export SQUEEZESAY_PORT="$PORT"
fi
if [ "$(opt https)" = "false" ]; then
    export SQUEEZESAY_HTTPS=0
fi
LMS="$(opt lms_url)"
if [ -n "$LMS" ]; then
    export SQUEEZESAY_LMS="$LMS"
fi
PLAYER="$(opt player)"
if [ -n "$PLAYER" ]; then
    export SQUEEZESAY_PLAYER="$PLAYER"
fi
CERT_HOSTS="$(opt cert_hosts)"
if [ -n "$CERT_HOSTS" ]; then
    export SQUEEZESAY_CERT_HOSTS="$CERT_HOSTS"
fi
MATERIAL="$(opt material_url)"
if [ -n "$MATERIAL" ]; then
    export SQUEEZESAY_MATERIAL_URL="$MATERIAL"
fi

exec /app/deploy/docker/entrypoint.sh
