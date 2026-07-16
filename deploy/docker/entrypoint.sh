#!/bin/sh
# Entrypoint del container Vivavoce.
#
# Al primo avvio genera un certificato TLS self-signed in $VIVAVOCE_DATA_DIR
# (volume persistente: il browser chiede di accettarlo una volta sola, non a
# ogni riavvio del container), poi lancia il server web locale. Tutta la
# configurazione passa per variabili d'ambiente — vedi docker-compose.yml.
# I vecchi nomi SQUEEZESAY_* restano letti come ripiego per un rilascio.
set -eu

DATA_DIR="${VIVAVOCE_DATA_DIR:-${SQUEEZESAY_DATA_DIR:-/data}}"
PORT="${VIVAVOCE_PORT:-${SQUEEZESAY_PORT:-8730}}"
HTTPS="${VIVAVOCE_HTTPS:-${SQUEEZESAY_HTTPS:-1}}"
CERT_HOSTS="${VIVAVOCE_CERT_HOSTS:-${SQUEEZESAY_CERT_HOSTS:-}}"
LMS_URL="${VIVAVOCE_LMS:-${SQUEEZESAY_LMS:-}}"
PLAYER="${VIVAVOCE_PLAYER:-${SQUEEZESAY_PLAYER:-}}"
MATERIAL_URL="${VIVAVOCE_MATERIAL_URL:-${SQUEEZESAY_MATERIAL_URL:-}}"

mkdir -p "$DATA_DIR"

# Lo stato persistente del server (licenza, kid-safe) vive nello stesso
# volume del certificato.
set -- --host 0.0.0.0 --port "$PORT" --data-dir "$DATA_DIR"

# HTTPS attivo di default: senza, il microfono del browser funziona solo su
# localhost e il container non servirebbe a molto. VIVAVOCE_HTTPS=0 per HTTP.
if [ "$HTTPS" != "0" ]; then
    if [ ! -f "$DATA_DIR/cert.pem" ] || [ ! -f "$DATA_DIR/key.pem" ]; then
        echo "Genero il certificato TLS self-signed in $DATA_DIR ..."
        if [ -n "$CERT_HOSTS" ]; then
            python /app/tools/make_cert.py --out "$DATA_DIR" \
                --hosts "$CERT_HOSTS"
        else
            python /app/tools/make_cert.py --out "$DATA_DIR"
        fi
    fi
    set -- "$@" --cert "$DATA_DIR/cert.pem" --key "$DATA_DIR/key.pem"
fi

[ -n "$LMS_URL" ] && set -- "$@" --lms "$LMS_URL"
[ -n "$PLAYER" ] && set -- "$@" --player "$PLAYER"
[ -n "$MATERIAL_URL" ] && set -- "$@" --material-url "$MATERIAL_URL"

# exec: python diventa PID 1, così docker stop arriva pulito al server.
# -u: stdout non bufferizzato anche dove le ENV non arrivano al processo
# (es. sotto s6-overlay nell'add-on Home Assistant) — senza, `docker logs`
# non mostrerebbe la riga "Pronto: https://..." finché il processo è vivo.
exec python -u /app/localvoice/server.py "$@"
