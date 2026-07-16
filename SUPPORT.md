# Support

Vivavoce is built and maintained by **one person**. Here is exactly what you
can expect — the limits are declared, not discovered.

## Channels

- **GitHub Issues** — bugs, questions, feature requests:
  https://github.com/LucaBon/vivavoce/issues
  Pro buyers: mention it in the issue and it gets priority.
- No phone, no live chat, no SLA.

## What's included

- **Free tier**: the software as-is, best-effort fixes for reproducible bugs.
- **Pro license**: same channel with priority, all 0.x updates included.
  Pro is a one-time purchase for your household, up to 5 device activations,
  and keeps working offline forever — see the [EULA](licenses/PRO-EULA.md).

## Refunds

Handled by Lemon Squeezy (the merchant of record): **14 days**, no questions
asked, from the receipt email or https://app.lemonsqueezy.com/my-orders — I
never see your payment data. A refunded key stops unlocking Pro features (an
enabled kid-safe blocklist keeps being enforced; only its configuration
locks).

## Before opening an issue

1. Update to the latest version (`docker compose pull && docker compose up -d`
   or update the Home Assistant add-on).
2. Grab the server log (Docker: `docker logs vivavoce`; add-on: the Log tab).
3. Say what LMS version and player you use, and the exact phrase that failed —
   the matching is deterministic, so a phrase is usually all I need to
   reproduce it.
