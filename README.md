# 🎵 Vivavoce

> Say **«metti Comfortably Numb dei Pink Floyd»** — and the *exact* song plays on your hi-fi.

**Hands-free voice control — in Italian or English — for a [Daphile](https://www.daphile.com/) /
[Lyrion Music Server](https://lyrion.org/) (LMS / Squeezebox) system — TIDAL and
Qobuz included.**
No cloud required, no LLM, no compromise on sound: Vivavoce sends **only control
commands**, while the audio keeps flowing LMS → Squeezelite → your DAC, bit-perfect.

```text
You:  «vivavoce, metti Comfortably Numb dei Pink Floyd»
App:  «Riproduco Comfortably Numb di Pink Floyd.»

You:  «metti Love»
App:  «Quale intendi? 1: Love di Lana Del Rey, 2: Love di John Lennon, 3: …»
You:  «la 2»            ← or just tap the "2" button on screen
App:  «Riproduco Love di John Lennon.»
```

## The idea

Great visual apps for this ecosystem already exist — Vivavoce deliberately does
**not** reinvent browsing, queueing, or now-playing. It's a **companion**:

- 👀 **See & touch** with **[Material Skin](https://github.com/CDrummond/lms-material)**
  (web) or **[Squeezer](https://f-droid.org/en/packages/uk.org.ngo.squeezer/)** (Android)
  — browse, queue, artwork, multi-room.
- 🗣️ **Speak** with **Vivavoce** — the one thing those don't do well hands-free.

The app is a **local web app** (`localvoice/`) over a tested engine
(`engine/actions.py` + `engine/lms.py`): a browser mic/text page on your LAN
that talks straight to LMS. No cloud, no account.

## Why it doesn't play the wrong song

The whole point: *say a song and the exact song plays* — or you get an honest
question, **never a silent wrong pick**. Matching is deterministic (rules + scoring,
no LLM), so behaviour is testable and repeatable.

| | |
|---|---|
| 🧠 **Title / artist / album parsing** | "metti Comfortably Numb **dei** Pink Floyd" → title + artist; "… **dall'album** X" → album. |
| 🎯 **Artist-aware ranking** | Streaming results are read in *menu mode*, which carries the **artist** — so among three "Comfortably Numb" it plays *Pink Floyd's* edition and confirms it out loud. |
| 🎼 **Two streaming services** | **TIDAL** and **Qobuz** (plus your local library): pick one in the page's source selector — it only lists the plugins your LMS actually has — or just say «da qobuz metti …». "Auto" tries your library first, then the default service. |
| ❓ **"Did you mean" (top 3)** | When genuinely different songs match, it reads back the top three and you answer «metti la 2» — the choices are also **tappable buttons**. Exact matches just play; junk never wins. |
| 📀 **Local library scored too** | A generic word like "love" never plays an unrelated album, and "aerosmith" plays the *artist*, not a random album. |
| 👂 **Mishearing resilience** | The web app tries the browser's alternative transcriptions until one hits (English names that it-IT often mangles). |
| 🪄 **Wake word (web app)** | Optionally arm a spoken keyword ("vivavoce" by default): «vivavoce metti Time» — no touching the screen. Off by default; otherwise the mic is tap-to-talk. |
| 🌍 **Natural multilingual read-back** | Optional, off by default (the transcript is on screen). When on, the Italian frame is spoken by an Italian voice and the title/artist in *their* language (English/Spanish/French/German), with the best natural voices your browser offers — pickable in settings. |

## Quick start — local web app

Prereqs: an LMS/Daphile on the LAN with the TIDAL and/or Qobuz plugin installed
and logged in, and at least one active player.

**With Docker** (Linux / NAS / Raspberry Pi — easiest, HTTPS included):

```bash
docker compose up -d
# open https://<this-host-ip>:8730 from a phone/tablet/PC on the same network
# (accept the self-signed certificate warning once — the mic then works)
```

**As a Home Assistant add-on**: add this repo's URL under *Settings → Add-ons →
Add-on store → ⋮ → Repositories*, then install **Vivavoce** — see
[DEPLOY.md](DEPLOY.md).


**Without Docker** (Python ≥ 3.9 + [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
uv run python localvoice/server.py          # auto-discovers LMS on the LAN
# open http://<this-pc-ip>:8730 from a phone/tablet/PC on the same network
```

Then say (or type), in Italian — or in English, after picking the mic language
on the page (the whole UI follows):

> «metti Comfortably Numb dei Pink Floyd» · «metti l'album The Wall» ·
> «dalla mia musica metti Aerosmith» · «da qobuz metti Time» ·
> «quali album ho di Yes» → «metti la 2» ·
> «pausa» · «alza il volume» · «cosa sta suonando»

> [!NOTE]
> The browser microphone needs **HTTPS** when used from another device — the Docker
> image sets this up automatically (certificate generated once into a volume);
> without Docker, start the server with a certificate (`--cert/--key`, auto-generated
> by the helper scripts). Install the generated **local CA** once per phone (page
> panel *"📱 Installa come app"*) for a green lock and a real **installable PWA**.
> The **text box works everywhere**, even plain HTTP. Full setup — Docker, HTTPS,
> autostart on Windows/Linux — is in **[DEPLOY.md](DEPLOY.md)**.

There's a link to Material Skin right in the page for when you want to browse visually.

## Repo layout

| Path | What |
|---|---|
| `engine/actions.py` | Voice-action business logic (matching, ranking, did-you-mean) |
| `engine/lms.py` | LMS JSON-RPC client + TIDAL search/playback |
| `engine/discovery.py` | LMS LAN auto-discovery (UDP) |
| `engine/blocklist_store.py` | Kid-safe blocklist (store contract) |
| `localvoice/` | Local web app: `server.py`, `router.py`, `index.html` |
| `tools/probe_lms.py` | Validate search/playback against a real LMS |
| `tests/` | pytest suite (simulated LMS transport, no network) |

## Tests

```bash
uv run pytest        # 355 tests, no network — uses a simulated LMS transport
```

Validate against a real LMS (read-only, or `--play` to actually play):

```bash
uv run python tools/probe_lms.py --query "Comfortably Numb dei Pink Floyd"
uv run python tools/probe_lms.py --service qobuz --query "Pink Floyd"
```

## Honest caveats

- **The voice interface speaks Italian and English.** Pick the mic language on
  the page — commands are parsed and answered in that language, and the page
  labels follow it too. Other languages fall back to Italian for now.
- **Wake-word mode on Android beeps**: the browser plays its own earcon every time
  continuous listening restarts — a platform behaviour Vivavoce can't silence
  (the app warns about it in-page).
- Streaming free-text search quality depends on the plugin; matching is deterministic
  (no LLM). Natural TTS voices depend on your device/browser.
- **Qobuz login on LMS can be flaky**: Qobuz has been tightening authentication
  for third-party clients (mid-2026), so the plugin's email+password login may
  fail with 401 a few times before it sticks — retry, or check the
  troubleshooting notes in DEPLOY.md. Once logged in, the stored token keeps
  working. (Vivavoce's Qobuz support itself is verified against a live
  LMS 9 + plugin-Qobuz 3.7.0.)
- **No Spotify**: Spotify Lossless (launched Sept 2025) is not delivered to
  third-party Connect clients, so the LMS plugin (Spotty/librespot) still gets
  lossy Ogg Vorbis 320 kbps — pointless on a bit-perfect chain. If Spotify ever
  opens lossless to the Connect API, a plugin path may become worth adding.
- Bit-perfect: Vivavoce sends **only commands**; ensure LMS doesn't resample to the player.

## License

Open-core. The engine, the web server and the free features are **AGPL-3.0**
([LICENSE](LICENSE)). The files under `localvoice/pro/` are proprietary,
covered by the [Pro EULA](licenses/PRO-EULA.md) and unlocked by a one-time
Pro license key. Details in [licenses/README.md](licenses/README.md).
