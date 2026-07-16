# Lyrion forum launch post — draft

> Post to: forums.lyrion.org → 3rd party software. Title suggestion:
> **[ANNOUNCE] Vivavoce — say a song, the exact song plays (local web app, IT+EN, TIDAL/Qobuz)**
> Replace the two TODO links before posting. Attach 2–3 screenshots
> (tools/shots/) and ideally a 20-second GIF of "metti Comfortably Numb dei
> Pink Floyd" → playing.

---

Hi all — long-time LMS household here. I built the thing I couldn't find
anywhere: **actually starting music by voice**, not just pause/skip.

**Vivavoce** is a small web app that runs next to your LMS (Docker one-liner,
Home Assistant add-on, or plain Python). You open it on any phone/tablet on
your LAN, tap the mic (or type), and say:

- *"play Comfortably Numb by Pink Floyd"* → plays **that** recording, from
  your library or TIDAL/Qobuz (it detects which plugins you have);
- *"which albums do I have by Yes"* → reads the top 3, you say *"play number
  2"* or just tap the button;
- when several songs genuinely match, it **asks** instead of silently playing
  the wrong one. Matching is deterministic (rules + scoring, ~400 tests, no
  LLM, no cloud in the loop) — audio keeps flowing LMS → player, bit-perfect.

It speaks **Italian and English** (parsing and replies follow the language you
pick). There's a now-playing card with artwork, but for browsing it
deliberately links out to Material Skin instead of reinventing it.

**The honest bits**, because you'd find them anyway:

- The mic uses the browser's speech engine, so Chrome sends the audio to
  Google (Apple on iOS) for transcription. The text box is 100% local, and an
  offline ASR mode is the top roadmap item. Everything else never leaves your
  LAN — no telemetry, no accounts. (Full PRIVACY.md in the repo.)
- Wake-word mode on Android beeps at every listen restart — browser
  limitation, documented in-app; tap-to-talk is the phone-friendly mode.

**Model**: the core is free and **open source (AGPL)** — typed commands, all
the search/playback, transport, now-playing. The hands-free extras (mic,
wake word, read-back voices, PIN-protected kid-safe) are a one-time **Pro
license: 11,90 €, launch price 8,90 €** for the household, up to 5 devices,
no subscription, works offline forever. The license check is deliberately
trust-based and unobfuscated — the key is simply how you keep the project
alive. This community runs on donations and fair one-time apps (Material,
iPeng, Orange Squeeze); I tried to price it in that same spirit.

- Repo & docs: **TODO link github.com/LucaBon/vivavoce**
- Pro license: **TODO Lemon Squeezy link** (launch code inside)

I'd genuinely love your first impressions — especially misheard phrases (the
matching is deterministic, so one phrase is usually enough to reproduce and
fix), and what would make Pro worth it for you. Multiroom targeting ("play X
in the kitchen") and offline ASR are the current roadmap leaders.
