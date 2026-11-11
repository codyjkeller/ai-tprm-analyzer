# Security Policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: open the **Security** tab of this
repository and choose **Report a vulnerability**. Please do not open a public
issue for security problems.

Only the current `main` branch is maintained.

## Design

- **No network use by default.** The offline keyword screen makes no
  connections. AI review runs only when `--provider` or `TPRM_PROVIDER` is
  set, and then sends the vendor document's text to that provider.
- **Connections are opt-in and narrow.** Slack, Jira and Confluence are
  contacted only when requested on the command line. Addresses must be HTTPS,
  requests time out, redirects are not followed, and a pasted Confluence
  address is used only for its page number, so credentials go only to the
  configured site. Messages to Slack are escaped and carry no vendor quotes.
  Error messages never include the Slack webhook address.
- **No login of its own.** The tool runs with the permissions and credentials
  of the person or service account that starts it. Use least-privilege API
  tokens and keep `.env` readable only by that account.
- **Vendor documents are untrusted input.** They are size-limited, parsed
  without executing content, wrapped in a per-run random delimiter before
  being shown to a model, and scanned for instruction-like wording.
- **Model output is untrusted too.** Replies must match a fixed JSON shape.
  A Pass or Fail stands only if its quote is found in the vendor document and
  no forbidden term from the policy is present. Otherwise the item is marked
  for human review. These checks are ordinary code in `tprm/evaluate.py`.
- **The policy file fails closed.** Unknown keys, missing frameworks and
  invalid values stop the run.
- **Output is escaped.** Vendor text is HTML-escaped in Markdown reports and
  formula characters are neutralized in CSV.

## Known limits

- The tool assesses what a vendor wrote. It does not verify the vendor's
  claims.
- Quote checking proves a quote exists, not that the model interpreted it
  correctly. A person must review every report.
- The instruction-wording scan is a short pattern list and will miss
  rephrased attempts. The quote check is the control that matters.
- Reports and vendor files are stored unencrypted on local disk.
- The AI review path and the Slack, Jira and Confluence connections have
  automated tests against stand-in servers. Validate each against your own
  accounts before relying on it.
- Credentials are read from a plain-text `.env` file. In production, inject
  them from your secrets manager as environment variables instead.
