# Deploy & setup

The web app runs on your LAN and talks straight to LMS: no cloud account, no
tunnel.

Wherever you see `http://<IP-LMS>:9000` or a player MAC `aa:bb:cc:dd:ee:ff`, substitute
your own. The web app can usually **auto-discover** the LMS, so you may not need
the address at all.

### Docker — one command, HTTPS included (Linux / NAS / Raspberry Pi)

```bash
docker compose up -d
# open https://<ip-of-this-host>:8730 and accept the certificate warning once
```

That's it: LMS is auto-discovered on the LAN, the TLS certificate is generated on
first start into a persistent volume (so the browser warning is one-time), and the
container restarts on boot (`restart: unless-stopped` — no systemd/autostart needed).
Everything is configured via environment variables in
[docker-compose.yml](docker-compose.yml), all optional (the pre-rename
`SQUEEZESAY_*` names still work for one release, with a deprecation note):

| Variable | Meaning | Default |
|---|---|---|
| `VIVAVOCE_LMS` | LMS URL, e.g. `http://192.168.1.50:9000` | auto-discovery (UDP) |
| `VIVAVOCE_PLAYER` | player MAC | first player found |
| `VIVAVOCE_PORT` | listen port | `8730` |
| `VIVAVOCE_HTTPS` | `0` = plain HTTP (mic on localhost only) | `1` |
| `VIVAVOCE_CERT_HOSTS` | extra SANs for the certificate (comma-separated) | — |
| `VIVAVOCE_MATERIAL_URL` | URL for the "Material Skin" link | `<lms>/material/` |

> [!NOTE]
> The compose file uses `network_mode: host`, which is what makes auto-discovery and
> the certificate "just work" — it requires Linux (fine on NAS/Raspberry Pi). On
> **Docker Desktop (Windows/Mac)** or bridge networks, follow the comments in
> [docker-compose.yml](docker-compose.yml): map the port, set `VIVAVOCE_LMS`
> explicitly, and put the host's LAN IP in `VIVAVOCE_CERT_HOSTS`.

### Home Assistant add-on

If you run Home Assistant OS/Supervised, Vivavoce installs as an add-on
(same engine, wrapped for the Supervisor — see [ha-addon/](ha-addon/)):

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories** → add
   `https://github.com/LucaBon/vivavoce`.
2. Install **Vivavoce** and start it. LMS is auto-discovered; the options
   (all optional: `lms_url`, `player`, `port`, `https`, `cert_hosts`,
   `material_url`) mirror the Docker environment variables above.
3. Open `https://<home-assistant-ip>:8730` and accept the certificate warning
   once. Full details in the add-on's Documentation tab
   ([ha-addon/DOCS.md](ha-addon/DOCS.md)).

### Without Docker

```bash
uv sync
uv run python localvoice/server.py            # auto-discovers LMS on the LAN
# or pin it:  uv run python localvoice/server.py --lms http://<IP-LMS>:9000
```

Open `http://<this-pc-ip>:8730` from a phone/tablet/PC on the same network → tap the mic
and speak, or type. The player is auto-detected (override with `--player <MAC>`).

### Microphone from other devices = HTTPS required

The browser mic works without a certificate only on `localhost`. From a phone the browser
requires **HTTPS**. Generate the certificate and start in HTTPS:

```bash
uv run python tools/make_cert.py     # writes ca.pem + cert.pem/key.pem (SAN = this PC's IP)
uv run python localvoice/server.py --cert cert.pem --key key.pem
# open https://<this-pc-ip>:8730  (accept the warning once)
```

`make_cert.py` creates a private **"Vivavoce Local CA"** (reused on every rerun)
and signs the server certificate with it. You can stop at the one-time browser
warning — everything works as before — or go one step further:

**Install the CA once per device → green lock + installable app.** The server
offers the CA at **`/ca.pem`** (the page's *"📱 Installa come app"* panel has
per-OS steps). Once trusted, the warning disappears **and** the service worker
turns on, so *Install app / Add to Home Screen* gives a real fullscreen PWA
with an offline shell. (Chrome refuses service workers on untrusted certificates,
even after clicking through the warning — that's why the CA matters for the PWA.)
Re-issuing the server cert for new IPs reuses the CA, so devices stay trusted.

The **text box works everywhere**, even over HTTP.

### Local speech recognition (Pro, optional)

By default the mic uses the browser's speech engine, which sends the audio to
Google (Chrome) or Apple (Safari) for transcription — the one non-local step in
the whole app. Installing the optional **asr** group moves transcription onto
*your* server with [faster-whisper](https://github.com/SYSTRAN/faster-whisper):
the page records the command and POSTs it to `/transcribe`, and no audio ever
leaves the LAN. A new settings switch («🎙 riconoscimento vocale locale»)
appears once the server reports the engine installed; the browser engine stays
the default and the automatic fallback if a transcription fails.

```bash
uv sync --group asr                      # the core stays dependency-free without it
uv run python localvoice/server.py       # "Riconoscimento vocale locale attivo"
```

- **Model**: `--asr-model` or `VIVAVOCE_ASR_MODEL` (default `small`; `tiny`
  and `base` are faster and lighter, `medium` more accurate). Runs int8 on
  CPU — no GPU needed. The model is downloaded once, on the first
  transcription, into the data directory (`asr-models/`), so in Docker it
  lands in the persistent volume.
- **Docker**: build the ASR variant with
  `docker build --build-arg ASR=1 -t vivavoce:asr .` (adds ~600 MB to the
  image), or add the build arg under `build:` in your compose file. The
  standard image ships without it and reports `/asr` as unavailable.
- **Home Assistant add-on**: the published add-on image doesn't include the
  engine (it would double its size for everyone). If you want it on HA, build
  the add-on locally with the same `ASR=1` build arg, or run the ASR Docker
  image alongside HA.
- **Hardware expectations**: with the default `small` model, a 3–5 s spoken
  command transcribes in roughly **2–4 s on an Intel N100 / Raspberry Pi 5**
  class box, using ~0.7–1 GB of RAM during the call (nothing while idle:
  the model loads lazily on first use, which also adds a one-time delay).
  `base` roughly halves latency and memory at some accuracy cost — a good
  fit for a Pi 4. Language follows the page's mic-language selector (it/en).

### Autostart

- **Docker:** nothing to do — `restart: unless-stopped` in the compose file already
  restarts the container on boot and on failure.
- **Windows:** `tools/run_local.ps1` (starts HTTPS, generates the cert if missing) and
  `tools/install_autostart.ps1` (scheduled task at logon + firewall rule; run **as
  Administrator**). `tools/uninstall_autostart.ps1` removes it.
- **Linux** (Raspberry Pi / mini-PC): `deploy/vivavoce.service` (systemd). Copy to
  `/etc/systemd/system/`, adapt `WorkingDirectory`/paths, then
  `sudo systemctl enable --now vivavoce`.

### Using it from a phone
1. Same Wi-Fi as the server PC.
2. Open **Chrome/Edge** at `https://<this-pc-ip>:8730`.
3. First time: "connection not private" (self-signed cert) → **Advanced → Proceed**, once.
4. Tap the **mic**, allow the permission, speak in Italian — or use the text box. The
   reply shows on screen (silent by default). Tip: install the **local CA** (page panel
   *"📱 Installa come app"* → `/ca.pem`) and then **Install app**: green lock, no
   warnings, fullscreen app icon. When the reply offers a numbered list, its choices
   appear as **tappable buttons** — tap instead of saying "metti la 2".
5. Optional, hands-free: tick **"attiva a voce con una parola chiave"** and start commands
   with the wake word ("vivavoce" by default) — «vivavoce metti Time».
6. Want the reply read aloud too? Tick **"🔊 leggi la risposta ad alta voce"**; the
   **Voci & lingue** panel then lets you pick natural per-language voices.

### Streaming services (TIDAL / Qobuz)

Install and log in the plugin(s) on LMS/Daphile first (**LMS Settings → Plugins**:
*TIDAL* and/or *Qobuz*). Then:

By default the server **auto-detects** the installed plugins and the
page's "Sorgente musica" selector only shows what's really there. Override with
`--services tidal,qobuz` (skips detection) and pick which one "auto" mode falls
back to with `--default-service qobuz`. Spoken phrases «da tidal …» / «da qobuz …»
always win over the selector. (Docker needs nothing: detection is the default.)

> [!NOTE]
> Qobuz support is verified against a live LMS 9.0.3 + plugin-Qobuz 3.7.0. If the
> plugin's **login fails with "authorization failed"** despite correct credentials:
> Qobuz has been tightening third-party authentication (mid-2026) and the
> email+password login can 401 intermittently — make sure the account has a real
> password (accounts created via Google/Apple sign-in need one set on qobuz.com),
> then simply retry a few times; once a login succeeds the stored token keeps
> working. To debug, set `plugin.qobuz` to Debug in LMS Settings → Advanced →
> Logging (and set it back afterwards: at Debug level the plugin writes your
> password's MD5 hash into server.log). To validate the Vivavoce side, run
> `uv run python tools/probe_lms.py --service qobuz --query "Pink Floyd"`.

---

## Updating
Edit files in `engine/`/`localvoice/` and restart the local server (Docker:
`docker compose pull && docker compose up -d`; HA: update the add-on).

## Audio quality
Vivavoce sends **only commands**: audio flows LMS → Squeezelite (Daphile) →
DAC as always, so hi-res quality is unchanged. Make sure LMS doesn't resample to the player.
