# r/squeezebox launch post — draft

> Title: **I built Vivavoce: say "play Comfortably Numb by Pink Floyd" and
> your Squeezebox plays exactly that (local web app, free core + one-time Pro)**
> Flair/format: text post with 2–3 screenshots. Replace TODO links.

---

Voice control for LMS that can actually **start** music has always been the
gap — Home Assistant/Music Assistant do transport only, and the certified
Alexa option is subscription + cloud. So I built a local one.

**What it is:** a web app that runs next to your LMS (Docker one-liner or HA
add-on). Any phone on your Wi-Fi opens it, you tap the mic or type:

- "play Comfortably Numb by Pink Floyd" → the exact track, from your library
  or TIDAL/Qobuz;
- "which albums do I have by Yes" → top-3 list, "play number 2" or tap;
- ambiguous match → it asks you, never silently plays the wrong thing.
  Deterministic matching (no LLM), ~400 tests, commands only — your
  bit-perfect chain is untouched.

Works in English and Italian. Now-playing card with artwork; browsing stays
Material Skin's job (there's a link, not a clone).

**Honesty corner:** the mic path uses the browser's speech engine (Chrome →
Google, iOS → Apple, transcription only); the text box and everything else is
100% LAN. No telemetry, no account. Wake-word mode beeps on Android (browser
limitation) — tap-to-talk is the phone mode. Offline ASR is the #1 roadmap
item.

**Price:** core is free and open source (AGPL) — typing, all search/playback,
transport, now-playing. Hands-free (mic, wake word, read-back voices,
PIN-protected kid-safe) is a one-time **Pro license, 11.90 € (8.90 € at
launch)** per household, 5 devices, offline forever, no subscription. The
gate is trust-based and unobfuscated by design.

Repo: **TODO github.com/LucaBon/vivavoce** · Pro: **TODO Lemon Squeezy link**

Feedback very welcome — especially phrases it mishears, and whether multiroom
targeting ("play X in the kitchen") or offline ASR should come first.
