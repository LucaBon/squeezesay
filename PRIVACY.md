# Privacy

Vivavoce runs **in your home**. This page lists, exhaustively, every way data
moves — including the one part that is *not* local.

## The one honest caveat: browser speech recognition

The microphone uses the browser's **Web Speech API**. On Chrome (desktop and
Android) the audio of what you say is sent to **Google's** speech servers for
transcription; on Safari/iOS it goes to **Apple**. This is how the browser
implements speech recognition — Vivavoce receives only the resulting text and
sends **none of it** anywhere.

If you don't want any audio leaving your home:

- use the **text box** (free tier, works everywhere) — fully local;
- a fully offline wake-word + speech-recognition mode is on the roadmap,
  precisely to close this gap.

## What stays on your LAN

- Every command, transcript, search and playback request: browser → Vivavoce
  server (your machine) → your LMS. Nothing is proxied through any cloud.
- The kid-safe blocklist and its PIN (hashed, PBKDF2-SHA256): a JSON file in
  the server's data directory.
- No telemetry, no analytics, no accounts, no cookies beyond `localStorage`
  preferences on your own devices.

## The only outbound connections

1. **Pro license activation** — when *you* enter a key, one HTTPS request to
   `api.lemonsqueezy.com` (the merchant of record). The response is cached in
   `license.json` in the data directory: the key (shown masked in the UI),
   an instance id, and timestamps. Nothing else is sent.
2. **License re-validation** — at most **once a week**, at server startup, the
   cached key is re-checked. A network failure changes nothing (an offline
   household keeps Pro forever); only a definitive "disabled/refunded" answer
   turns Pro off. Opt out entirely with `VIVAVOCE_NO_REVALIDATE=1`.
3. **Album artwork** — fetched by the server from your LMS (or from the URL
   your streaming plugin reports) and proxied to the page.

## Payments

Purchases happen on **Lemon Squeezy** (merchant of record): they process the
payment, handle EU VAT and invoices, and store your payment data under
[their privacy policy](https://www.lemonsqueezy.com/privacy). Vivavoce never
sees your payment details — only the license key works locally.

## Questions

Open an issue: https://github.com/LucaBon/vivavoce/issues
