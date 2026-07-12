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
   reply is also read aloud. Tip: **Add to Home Screen** to use it like an app.
5. Open the app's **🔊 Voci & lingue** panel to pick natural per-language voices.

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
   `lms.py`; put `ask-sdk-core` in `requirements.txt`. Create a **`config.py`**
   (see `lambda/config.example.py`) with `LMS_BASE_URL` (the tunnel URL) and
   `LMS_PLAYER_ID`. **Save** → **Deploy**.
4. **Test** tab: enable **Development** — the skill is now usable **only on your
   account** (no publishing, no Italian-store problem).

Try: «Alexa, apri impianto» → «metti l'album The Wall».

### B2. Your own AWS Lambda (needs an AWS account; free tier ≈ €0)
1. Build the zip: `python tools/build_lambda.py` → `skill.zip`.
2. AWS Console → **Lambda → Create function** → Runtime **Python 3.12** → upload
   `skill.zip` → **Handler** `lambda_function.handler`.
3. **Configuration → Environment variables**: `LMS_BASE_URL`, `LMS_PLAYER_ID`,
   (optional) `LMS_USERNAME`/`LMS_PASSWORD`.
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
