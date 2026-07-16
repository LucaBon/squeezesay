# Lemon Squeezy setup — operator guide (for Luca)

One-time checklist to go from zero to selling Vivavoce Pro keys. Budget ~1
hour plus store-approval wait time.

## 1. Store

1. Create the account at https://app.lemonsqueezy.com/ (merchant-of-record:
   they handle EU VAT, invoices and refunds — you never touch tax paperwork).
2. Create a store, e.g. `vivavoce` → the storefront becomes
   `https://vivavoce.lemonsqueezy.com`. **If you pick a different slug, update
   `PRO_STORE_URL` in `localvoice/index.html`.**
3. Fill in the business details and connect the payout account; submit the
   store for activation (test mode works immediately, live sales need the
   approval).

## 2. Product

1. **Products → New product**: name **Vivavoce Pro**, one-time purchase,
   price **11,90 €** ("tax inclusive" ON for consumer-friendly EU pricing).
2. Description: paste the Free-vs-Pro table from the README, plus the promise
   that matters: *one-time, per household, up to 5 devices, works offline
   forever, 14-day refunds.*
3. **Confirmation email / receipt**: mention that the key is activated from
   the web page: *Settings → Pro → paste the key → Activate.*

## 3. License keys

In the product's settings enable **Generate license keys**:

- **Activation limit: 5** (the EULA promises 5 device activations; the HA
  add-on reinstall after the rename consumes one, so don't go lower).
- **Expires: never.**
- Nothing else — the app only uses the public `activate`/`validate` endpoints,
  which need no API key. **No webhooks, no backend.**

## 4. Launch discount

Create a **discount code** `LAUNCH` (or similar): **-3 €** (or 25%) bringing
11,90 € → **8,90 €**, limited in time (e.g. 4 weeks). A discount code keeps
the 11,90 € anchor visible — better than a temporary list price.

## 5. Test the whole loop before announcing

1. Toggle the store to **Test mode**, make a test purchase (test card
   `4242 4242 4242 4242`), grab the generated license key.
2. Run the app, Settings → Pro → paste the key → **Activate** → "Pro attivo".
3. Restart the server → still Pro. Disconnect the WAN, restart → still Pro
   (the offline promise).
4. Enter a wrong key → the "invalid key" message; disconnect WAN and try to
   activate → the "can't reach the license server" message (they must differ).
5. In the Lemon Squeezy dashboard disable the test key → within a week the
   app downgrades (or immediately: delete `last_validated` from
   `license.json` and restart). Re-activating with a valid key restores Pro.
6. Toggle back to **Live mode**.

## 6. Wire the checkout URL

1. Copy the product's checkout link (Share → copy link).
2. Put it in `PRO_STORE_URL` (`localvoice/index.html`) and in the README's
   Free-and-Pro section, commit, release.

## Ongoing

- **Refund requests**: approve them in the dashboard within the 14-day
  window; the key gets disabled automatically and the app's weekly
  revalidation turns Pro off on its own.
- **Activation-limit complaints** (rare): the dashboard can reset a key's
  activations.
- Payouts: Lemon Squeezy pays out on their schedule minus 5% + 0,50 $ per
  transaction.
