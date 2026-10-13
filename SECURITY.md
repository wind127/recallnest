# Security and data handling

RecallNest stores conversation history and personal memory locally. Its first release is designed for one user on a trusted machine, with the service listening on loopback by default. It does not provide production multi-user authentication.

## Data boundaries

- The application data directory contains the database, raw archive, configuration and capture state. It is separate from the source repository by default.
- Configured model providers receive the conversation segments and relevant context needed for the selected model operation. Using a remote provider transmits those segments to that provider; using a local compatible provider keeps that operation on the chosen local service.
- Model keys belong in server-side configuration. They are excluded from API status, logs, exported knowledge and version control.
- Saved provider settings are stored in `provider-settings.json` inside the private data directory. This file contains the key in plaintext with best-effort owner-only permissions; protect the directory and its backups. See [model configuration](docs/models.md).
- Knowledge exports contain your actual records. Keep them in destinations appropriate for your data.
- Import formats are untrusted. ZIP imports use size and member limits and never extract arbitrary paths.
- Imported Markdown and model output must remain inert text rather than executable HTML.

For access from other devices, place the service behind an authenticated reverse proxy and review the deployment boundaries first. Merely changing the bind address does not add authentication.

## Reporting a vulnerability

Report a reproducible issue using synthetic records and omit any credentials, private database or actual conversation export. If GitHub private vulnerability reporting is available for this repository, use it for sensitive details. Public issues should contain only a non-sensitive description until a safe disclosure path is arranged.
