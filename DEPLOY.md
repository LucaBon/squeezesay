# Deploy & setup

Two ways to run the same engine (`lambda/actions.py` + `lambda/lms.py`):

- **A) Local web app** — no cloud, no account, no cost. **Recommended.**
- **B) Alexa skill** (Echo) — via **Alexa-hosted** (free, no AWS) or your own Lambda.

Wherever you see `http://<IP-LMS>:9000` or a player MAC `aa:bb:cc:dd:ee:ff`, substitute
your own. The local web app can usually **auto-discover** the LMS, so you may not need
the address at all.

---

## A) Local web app (recommended)

Runs on your LAN and talks straight to LMS: no Amazon, no AWS, no tunnel, zero cost.

### A0. Docker — one command, HTTPS included (Linux / NAS / Raspberry Pi)

```bash
docker compose up -d
# open https://<ip-of-this-host>:8730 and accept the certificate warning once
```

That's it: LMS is auto-discovered on the LAN, the TLS certificate is generated on
first start into a persistent volume (so the browser warning is one-time), and the
container restarts on boot (`restart: unless-stopped` — no systemd/autostart needed).
Everything is configured via environment variables in
[docker-compose.yml](docker-compose.yml), all optional:

| Variable | Meaning | Default |
|---|---|---|
| `SQUEEZESAY_LMS` | LMS URL, e.g. `http://192.168.1.50:9000` | auto-discovery (UDP) |
| `SQUEEZESAY_PLAYER` | player MAC | first player found |
| `SQUEEZESAY_PORT` | listen port | `8730` |
| `SQUEEZESAY_HTTPS` | `0` = plain HTTP (mic on localhost only) | `1` |
| `SQUEEZESAY_CERT_HOSTS` | extra SANs for the certificate (comma-separated) | — |
| `SQUEEZESAY_MATERIAL_URL` | URL for the "Material Skin" link | `<lms>/material/` |

> [!NOTE]
> The compose file uses `network_mode: host`, which is what makes auto-discovery and
> the certificate "just work" — it requires Linux (fine on NAS/Raspberry Pi). On
> **Docker Desktop (Windows/Mac)** or bridge networks, follow the comments in
> [docker-compose.yml](docker-compose.yml): map the port, set `SQUEEZESAY_LMS`
> explicitly, and put the host's LAN IP in `SQUEEZESAY_CERT_HOSTS`.

### A0-bis. Home Assistant add-on

If you run Home Assistant OS/Supervised, SqueezeSay installs as an add-on
(same engine, wrapped for the Supervisor — see [ha-addon/](ha-addon/)):

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories** → add
   `https://github.com/LucaBon/squeezesay`.
2. Install **SqueezeSay** and start it. LMS is auto-discovered; the options
   (all optional: `lms_url`, `player`, `port`, `https`, `cert_hosts`,
   `material_url`) mirror the Docker environment variables above.
3. Open `https://<home-assistant-ip>:8730` and accept the certificate warning
   once. Full details in the add-on's Documentation tab
   ([ha-addon/DOCS.md](ha-addon/DOCS.md)).

### A1. Without Docker

```bash
uv sync
uv run python localvoice/server.py            # auto-discovers LMS on the LAN
# or pin it:  uv run python localvoice/server.py --lms http://<IP-LMS>:9000
```

Open `http://<this-pc-ip>:8730` from a phone/tablet/PC on the same network → tap the mic
and speak, or type. The player is auto-detected (override with `--player <MAC>`).

### Microphone from other devices = HTTPS required

The browser mic works without a certificate only on `localhost`. From a phone the browser
requires **HTTPS**. Generate a self-signed cert and start in HTTPS:

```bash
uv run python tools/make_cert.py     # writes cert.pem / key.pem (SAN = this PC's IP)
uv run python localvoice/server.py --cert cert.pem --key key.pem
# open https://<this-pc-ip>:8730  (accept the warning once)
```

The **text box works everywhere**, even over HTTP.

### Autostart

- **Docker:** nothing to do — `restart: unless-stopped` in the compose file already
  restarts the container on boot and on failure.
- **Windows:** `tools/run_local.ps1` (starts HTTPS, generates the cert if missing) and
  `tools/install_autostart.ps1` (scheduled task at logon + firewall rule; run **as
  Administrator**). `tools/uninstall_autostart.ps1` removes it.
- **Linux** (Raspberry Pi / mini-PC): `deploy/squeezesay.service` (systemd). Copy to
  `/etc/systemd/system/`, adapt `WorkingDirectory`/paths, then
  `sudo systemctl enable --now squeezesay`.

### Using it from a phone
1. Same Wi-Fi as the server PC.
2. Open **Chrome/Edge** at `https://<this-pc-ip>:8730`.
3. First time: "connection not private" (self-signed cert) → **Advanced → Proceed**, once.
4. Tap the **mic**, allow the permission, speak in Italian — or use the text box. The
   reply shows on screen (silent by default). Tip: **Add to Home Screen** to use it like
   an app. When the reply offers a numbered list, its choices appear as **tappable
   buttons** — tap instead of saying "metti la 2".
5. Optional, hands-free: tick **"attiva a voce con una parola chiave"** and start commands
   with the wake word ("impianto" by default) — «impianto metti Time».
6. Want the reply read aloud too? Tick **"🔊 leggi la risposta ad alta voce"**; the
   **Voci & lingue** panel then lets you pick natural per-language voices.

### Streaming services (TIDAL / Qobuz)

Install and log in the plugin(s) on LMS/Daphile first (**LMS Settings → Plugins**:
*TIDAL* and/or *Qobuz*). Then:

- **Web app**: by default the server **auto-detects** the installed plugins and the
  page's "Sorgente musica" selector only shows what's really there. Override with
  `--services tidal,qobuz` (skips detection) and pick which one "auto" mode falls
  back to with `--default-service qobuz`. Spoken phrases «da tidal …» / «da qobuz …»
  always win over the selector. (Docker needs nothing: detection is the default.)
- **Alexa skill**: one service per skill, chosen with `MUSIC_SERVICE=tidal|qobuz`
  (env var or `config.py`; default `tidal`).

> [!NOTE]
> Qobuz support is verified against a live LMS 9.0.3 + plugin-Qobuz 3.7.0. If the
> plugin's **login fails with "authorization failed"** despite correct credentials:
> Qobuz has been tightening third-party authentication (mid-2026) and the
> email+password login can 401 intermittently — make sure the account has a real
> password (accounts created via Google/Apple sign-in need one set on qobuz.com),
> then simply retry a few times; once a login succeeds the stored token keeps
> working. To debug, set `plugin.qobuz` to Debug in LMS Settings → Advanced →
> Logging (and set it back afterwards: at Debug level the plugin writes your
> password's MD5 hash into server.log). To validate the SqueezeSay side, run
> `uv run python tools/probe_lms.py --service qobuz --query "Pink Floyd"`.

---

## B) Alexa skill (Echo)

The code runs **in Amazon's cloud**, so you need a **tunnel** from home to LMS (the only
way for Alexa to reach your server).

### B0. Tunnel to LMS (both sub-options)
On an always-on home host (not Daphile itself), expose LMS over HTTPS. With
**Cloudflare Tunnel** (free, no router ports opened):
```bash
cloudflared tunnel --url http://<IP-LMS>:9000
```
You get an `https://….trycloudflare.com` URL → that's your `LMS_BASE_URL`. **Protect it**
(Cloudflare Access or Basic Auth); if you use Basic Auth, also set
`LMS_USERNAME`/`LMS_PASSWORD`.

### B1. Alexa-hosted (free, NO AWS account) — easiest for Echo
1. https://developer.amazon.com/alexa/console/ask → **Create Skill** → **Custom** →
   hosting **Alexa-hosted (Python)** → language **Italiano (IT)**.
2. **Build → JSON Editor**: paste `interaction-models/it-IT.json` → **Build Model**.
3. **Code** tab: replace the contents with our `lambda_function.py`, `actions.py`,
   `lms.py`, `messages.py`, `blocklist_store.py`; put `ask-sdk-core` in
   `requirements.txt`. Create a **`config.py`**
   (see `lambda/config.example.py`) with `LMS_BASE_URL` (the tunnel URL) and
   `LMS_PLAYER_ID` (optional: `MUSIC_SERVICE = "qobuz"` to stream from Qobuz
   instead of TIDAL). **Save** → **Deploy**.
4. **Test** tab: enable **Development** — the skill is now usable **only on your
   account** (no publishing, no Italian-store problem).

Try: «Alexa, apri impianto» → «metti l'album The Wall».

### B2. Your own AWS Lambda (needs an AWS account; free tier ≈ €0)
1. Build the zip: `python tools/build_lambda.py` → `skill.zip`.
2. AWS Console → **Lambda → Create function** → Runtime **Python 3.12** → upload
   `skill.zip` → **Handler** `lambda_function.handler`.
3. **Configuration → Environment variables**: `LMS_BASE_URL`, `LMS_PLAYER_ID`,
   (optional) `LMS_USERNAME`/`LMS_PASSWORD`, (optional) `MUSIC_SERVICE`
   (`tidal`, default, or `qobuz`).
4. **Add trigger → Alexa Skills Kit** (paste the Skill ID from step 5).
5. Developer Console: create a **Custom** skill (hosting *Provision your own*), import the
   it-IT model, put the Lambda **ARN** in **Endpoint** → **Build Model** → **Test**.

---

## Updating
- Web app / logic: edit files in `lambda/` and restart the local server; or rebuild the
  zip (`python tools/build_lambda.py`) and re-upload; or paste updated files into the
  Alexa-hosted editor and **Deploy**.
- Voice model: re-import `interaction-models/it-IT.json` and **Build Model**.

## Audio quality
In every case SqueezeSay sends **only commands**: audio flows LMS → Squeezelite (Daphile) →
DAC as always, so hi-res quality is unchanged. Make sure LMS doesn't resample to the player.
