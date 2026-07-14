# 🎵 SqueezeSay

> Say **«metti Comfortably Numb dei Pink Floyd»** — and the *exact* song plays on your hi-fi.

**Hands-free Italian voice control for a [Daphile](https://www.daphile.com/) /
[Lyrion Music Server](https://lyrion.org/) (LMS / Squeezebox) system — TIDAL included.**
No cloud required, no LLM, no compromise on sound: SqueezeSay sends **only control
commands**, while the audio keeps flowing LMS → Squeezelite → your DAC, bit-perfect.

```text
You:  «impianto, metti Comfortably Numb dei Pink Floyd»
App:  «Riproduco Comfortably Numb di Pink Floyd.»

You:  «metti Love»
App:  «Quale intendi? 1: Love di Lana Del Rey, 2: Love di John Lennon, 3: …»
You:  «la 2»            ← or just tap the "2" button on screen
App:  «Riproduco Love di John Lennon.»
```

## The idea

Great visual apps for this ecosystem already exist — SqueezeSay deliberately does
**not** reinvent browsing, queueing, or now-playing. It's a **companion**:

- 👀 **See & touch** with **[Material Skin](https://github.com/CDrummond/lms-material)**
  (web) or **[Squeezer](https://f-droid.org/en/packages/uk.org.ngo.squeezer/)** (Android)
  — browse, queue, artwork, multi-room.
- 🗣️ **Speak** with **SqueezeSay** — the one thing those don't do well hands-free.

Two front-ends share one tested engine (`lambda/actions.py` + `lambda/lms.py`):

1. 🏠 **Local web app** (`localvoice/`) — **recommended.** No cloud, no account, no
   cost. A browser mic/text page on your LAN that talks straight to LMS.
2. 🔵 **Alexa skill** (`lambda/`) — a private, unpublished custom skill for your Echo.

## Why it doesn't play the wrong song

The whole point: *say a song and the exact song plays* — or you get an honest
question, **never a silent wrong pick**. Matching is deterministic (rules + scoring,
no LLM), so behaviour is testable and repeatable.

| | |
|---|---|
| 🧠 **Title / artist / album parsing** | "metti Comfortably Numb **dei** Pink Floyd" → title + artist; "… **dall'album** X" → album. |
| 🎯 **Artist-aware ranking** | TIDAL results are read in *menu mode*, which carries the **artist** — so among three "Comfortably Numb" it plays *Pink Floyd's* edition and confirms it out loud. |
| ❓ **"Did you mean" (top 3)** | When genuinely different songs match, it reads back the top three and you answer «metti la 2» — on both front-ends. On the web app the choices are also **tappable buttons**. Exact matches just play; junk never wins. |
| 📀 **Local library scored too** | A generic word like "love" never plays an unrelated album, and "aerosmith" plays the *artist*, not a random album. |
| 👂 **Mishearing resilience** | The web app tries the browser's alternative transcriptions until one hits (English names that it-IT often mangles). |
| 🪄 **Wake word (web app)** | Optionally arm a spoken keyword ("impianto" by default): «impianto metti Time» — no touching the screen. Off by default; otherwise the mic is tap-to-talk. |
| 🌍 **Natural multilingual read-back** | Optional, off by default (the transcript is on screen). When on, the Italian frame is spoken by an Italian voice and the title/artist in *their* language (English/Spanish/French/German), with the best natural voices your browser offers — pickable in settings. |
| 🧒 **Kid-safe filter (Alexa only)** | A voice-editable blocklist gated by Alexa Voice ID. |

## Quick start — local web app

Prereqs: an LMS/Daphile on the LAN with the TIDAL plugin installed and logged in,
and at least one active player.

**With Docker** (Linux / NAS / Raspberry Pi — easiest, HTTPS included):

```bash
docker compose up -d
# open https://<this-host-ip>:8730 from a phone/tablet/PC on the same network
# (accept the self-signed certificate warning once — the mic then works)
```

**Without Docker** (Python ≥ 3.9 + [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
uv run python localvoice/server.py          # auto-discovers LMS on the LAN
# open http://<this-pc-ip>:8730 from a phone/tablet/PC on the same network
```

Then say (or type), in Italian:

> «metti Comfortably Numb dei Pink Floyd» · «metti l'album The Wall» ·
> «dalla mia musica metti Aerosmith» · «quali album ho di Yes» → «metti la 2» ·
> «pausa» · «alza il volume» · «cosa sta suonando»

> [!NOTE]
> The browser microphone needs **HTTPS** when used from another device — the Docker
> image sets this up automatically (self-signed cert, generated once into a volume);
> without Docker, start the server with a certificate (`--cert/--key`, auto-generated
> by the helper scripts). The **text box works everywhere**, even plain HTTP. Full
> setup — Docker, HTTPS, autostart on Windows/Linux, and the Alexa skill — is in
> **[DEPLOY.md](DEPLOY.md)**.

There's a link to Material Skin right in the page for when you want to browse visually.

## Repo layout

| Path | What |
|---|---|
| `lambda/actions.py` | Voice-action business logic (matching, ranking, did-you-mean) |
| `lambda/lms.py` | LMS JSON-RPC client + TIDAL search/playback |
| `lambda/lambda_function.py` | Alexa skill handlers (ask-sdk) |
| `lambda/discovery.py` | LMS LAN auto-discovery (UDP) |
| `lambda/blocklist_store.py` | Kid-safe blocklist (DynamoDB) |
| `localvoice/` | Local web app: `server.py`, `router.py`, `index.html` |
| `interaction-models/it-IT.json` | Alexa interaction model |
| `tools/probe_lms.py` | Validate search/playback against a real LMS |
| `tests/` | pytest suite (simulated LMS transport, no network) |

## Tests

```bash
uv run pytest        # 258 tests, no network — uses a simulated LMS transport
```

Validate against a real LMS+TIDAL (read-only, or `--play` to actually play):

```bash
uv run python tools/probe_lms.py --query "Comfortably Numb dei Pink Floyd"
```

## Honest caveats

- **The voice interface is Italian only** (it-IT interaction model + Italian responses).
- **The Alexa path needs an always-on home host + an HTTPS tunnel** (Cloudflare
  Tunnel/ngrok): Alexa runs in the cloud and can't reach your LMS otherwise. The
  **local web app needs none of that.**
- **Wake-word mode on Android beeps**: the browser plays its own earcon every time
  continuous listening restarts — a platform behaviour SqueezeSay can't silence
  (the app warns about it in-page).
- TIDAL free-text search quality depends on the plugin; matching is deterministic (no
  LLM). Natural TTS voices depend on your device/browser.
- Bit-perfect: SqueezeSay sends **only commands**; ensure LMS doesn't resample to the player.
