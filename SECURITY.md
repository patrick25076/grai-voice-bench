# Security and data handling

The offline simulations run against fresh, in-memory business records. They do
not connect to a real CRM, send messages or create real orders. This is isolation
of business effects, **not an operating-system sandbox for untrusted code**.
Review adapters before letting them execute code or reach external services.

## Credentials and paid calls

- Keep credentials in your private environment. `.env.example` contains names
  and blank values. Never commit your filled `.env` or attach it to an issue.
- Use dedicated test phone numbers, trunks and dispatch rules. The included
  phone runner temporarily changes the specified test routing and attempts to
  restore it afterward. A process kill or provider failure can interrupt cleanup;
  verify routing after an abnormal exit.
- The local spending ledger is a reservation mechanism, not a provider billing
  limit. Configure account limits separately and reconcile actual charges.
- Keep routing snapshots, protobuf backups, SIP diagnostics, control tokens,
  raw logs and new recordings private. SIP routing diagnostics can contain the
  benchmark control token or account identifiers.
- Bind the listening/review service to localhost. Do not expose the development
  review server as a public authenticated application.

## Publishing evidence

Use synthetic business facts. Inspect prompts, tool arguments, transcripts,
recordings and release archives before publishing. `.gitignore` reduces accidental
tracking; it does not sanitize data. Audio can contain information that a text
secret scanner cannot detect. Do not publish real customer calls without the
appropriate authorization.

Frozen study releases are evidence snapshots. Publish an explained correction or
addendum instead of silently changing them. A successful secret scan is not a
guarantee that every log, recording or future contribution is safe.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting feature if it is available on this
repository. Otherwise open an issue asking for a private reporting channel,
without including an exploit, credential or sensitive recording. Do not paste
secrets into public issues. If a real credential is exposed, revoke or rotate it
first; deleting the current file does not remove copies or Git history.
