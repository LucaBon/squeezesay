"""Optional config fallback (used only if the matching environment variables are
NOT set). Copy to ``config.py`` and fill in — handy for Alexa-hosted skills that
don't expose an environment-variable UI. Do NOT commit real values.

For an own-Lambda deploy, prefer environment variables and ignore this file.
"""

LMS_BASE_URL = "https://xxxx.trycloudflare.com"  # URL HTTPS del tunnel verso LMS
LMS_PLAYER_ID = "aa:bb:cc:dd:ee:ff"              # MAC del player Daphile
LMS_USERNAME = ""                                 # se il tunnel usa Basic Auth
LMS_PASSWORD = ""
# Servizio streaming usato dalla skill: "tidal" (default) o "qobuz". Il plugin
# corrispondente deve essere installato e loggato su LMS/Daphile.
MUSIC_SERVICE = "tidal"

# --- Filtro per età / riconoscimento voce (opzionale) ---
# Il tuo personId di Alexa Voice ID: quando parli tu accesso pieno, per chiunque
# altro (tua figlia, ospiti, voce non riconosciuta) si applica la blocklist.
# Come trovarlo: apri la skill una volta ("Alexa, apri impianto") e leggi
# "[personalization] personId=..." nei log CloudWatch. Vuoto = filtro disattivo.
TRUSTED_PERSON_ID = ""
# Blocklist permanente di base, separata da virgole (brani e/o cantanti).
KIDSAFE_BLOCKLIST = ""
# Tabella DynamoDB per i termini aggiunti a voce. Su Alexa-hosted la variabile
# DYNAMODB_PERSISTENCE_TABLE_NAME è già impostata: lascia vuoto. Imposta solo per
# un deploy con Lambda tua.
BLOCKLIST_TABLE = ""
