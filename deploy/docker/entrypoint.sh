#!/bin/sh
# Entrypoint del container SqueezeSay.
#
# Al primo avvio genera un certificato TLS self-signed in $SQUEEZESAY_DATA_DIR
# (volume persistente: il browser chiede di accettarlo una volta sola, non a
# ogni riavvio del container), poi lancia il server web locale. Tutta la
# configurazione passa per variabili d'ambiente — vedi docker-compose.yml.
set -eu

DATA_DIR="${SQUEEZESAY_DATA_DIR:-/data}"
PORT="${SQUEEZESAY_PORT:-8730}"

mkdir -p "$DATA_DIR"

set -- --host 0.0.0.0 --port "$PORT"

# HTTPS attivo di default: senza, il microfono del browser funziona solo su
# localhost e il container non servirebbe a molto. SQUEEZESAY_HTTPS=0 per HTTP.
if [ "${SQUEEZESAY_HTTPS:-1}" != "0" ]; then
    if [ ! -f "$DATA_DIR/cert.pem" ] || [ ! -f "$DATA_DIR/key.pem" ]; then
        echo "Genero il certificato TLS self-signed in $DATA_DIR ..."
        if [ -n "${SQUEEZESAY_CERT_HOSTS:-}" ]; then
            python /app/tools/make_cert.py --out "$DATA_DIR" \
                --hosts "$SQUEEZESAY_CERT_HOSTS"
        else
            python /app/tools/make_cert.py --out "$DATA_DIR"
        fi
    fi
    set -- "$@" --cert "$DATA_DIR/cert.pem" --key "$DATA_DIR/key.pem"
fi

[ -n "${SQUEEZESAY_LMS:-}" ] && set -- "$@" --lms "$SQUEEZESAY_LMS"
[ -n "${SQUEEZESAY_PLAYER:-}" ] && set -- "$@" --player "$SQUEEZESAY_PLAYER"
[ -n "${SQUEEZESAY_MATERIAL_URL:-}" ] && set -- "$@" --material-url "$SQUEEZESAY_MATERIAL_URL"

# exec: python diventa PID 1, così docker stop arriva pulito al server.
exec python /app/localvoice/server.py "$@"
