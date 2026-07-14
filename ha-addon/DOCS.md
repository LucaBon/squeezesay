# SqueezeSay — add-on Home Assistant

Controllo vocale **in italiano** per un impianto LMS / Squeezebox / Daphile
(TIDAL incluso): di' «metti Comfortably Numb dei Pink Floyd» e parte *quel*
brano — o ricevi una domanda onesta, mai un brano sbagliato in silenzio.
L'add-on esegue la web app locale di [SqueezeSay](https://github.com/LucaBon/squeezesay):
nessun cloud, nessun account, i comandi restano nella tua rete.

## Installazione

1. **Impostazioni → Componenti aggiuntivi → Store → ⋮ → Repository** e aggiungi
   `https://github.com/LucaBon/squeezesay`.
2. Installa **SqueezeSay** e avvialo. Di norma non serve configurare nulla:
   LMS viene rilevato automaticamente sulla LAN (UDP) e viene usato il primo
   player trovato.
3. Apri `https://<ip-di-home-assistant>:8730` da telefono/tablet/PC sulla
   stessa rete e accetta **una volta** l'avviso del certificato self-signed
   (necessario: il microfono del browser richiede HTTPS). Consiglio: aggiungi
   la pagina alla home del telefono.

Poi parla (o scrivi), in italiano: «metti l'album The Wall», «dalla mia musica
metti Aerosmith», «quali album ho di Yes» → «metti la 2», «pausa», «alza il
volume», «cosa sta suonando».

## Opzioni

| Opzione | Significato | Default |
|---|---|---|
| `https` | `false` = solo HTTP (il microfono funziona solo su localhost) | `true` |
| `port` | porta di ascolto | `8730` |
| `lms_url` | URL di LMS, es. `http://192.168.1.50:9000` | auto-discovery |
| `player` | MAC del player da comandare | il primo trovato |
| `cert_hosts` | SAN extra nel certificato (IP/nomi, separati da virgola) | — |
| `material_url` | URL del link "Material Skin" nella pagina | `<lms>/material/` |

Il certificato TLS viene generato al **primo avvio** nello storage persistente
dell'add-on, quindi l'avviso del browser va accettato una sola volta. Se cambi
`cert_hosts` dopo il primo avvio, riavvia l'add-on dopo aver cancellato i file
`cert.pem`/`key.pem` dallo storage per rigenerarlo.

## Requisiti

- Un LMS/Daphile sulla stessa rete con almeno un player attivo (per TIDAL:
  plugin TIDAL installato e loggato).
- L'add-on usa la **rete host** (serve per l'auto-discovery UDP e per avere
  gli IP giusti nel certificato).
- Il microfono richiede Chrome/Edge; la casella di testo funziona ovunque.

## Note

- L'add-on scarica il codice dal branch `main` del repo al momento della
  build; un update dell'add-on ricompila con il codice aggiornato.
- Problemi o idee: https://github.com/LucaBon/squeezesay/issues
