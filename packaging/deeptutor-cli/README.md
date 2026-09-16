# deeptutor-cli

CLI-only DeepTutor distribution. It installs the `deeptutor` command and the
Python modules required for terminal workflows, RAG, document parsing, and model
provider integrations, but it does not ship the packaged Next.js Web assets or
FastAPI/Uvicorn server dependencies used by `deeptutor start`.

Business commands are PostgreSQL-only. `deeptutor --help`, `--version`, and
offline migration source checks can run without a database, but `run`, `chat`,
sessions, notebooks, books, learning, cron, partners, and tools require:

- `DEEPTUTOR_POSTGRES_CONFIG` pointing at a JSON deployment config;
- backend/maintenance Secret environment variables referenced from that config,
  including `DEEPTUTOR_DATABASE_URL`;
- an authenticated user token supplied by env var name, for example
  `--auth-token-env DEEPTUTOR_AUTH_TOKEN`.

Do not put DSNs or tokens in CLI arguments, README examples, frontend settings,
or `NEXT_PUBLIC_*`. See `docs/postgresql-runtime-runbook.md` for schema apply,
identity bootstrap, and offline SQLite/PocketBase import commands.

Install from the repository root when you want a local CLI-only environment:

```bash
python3 -m venv .venv-cli
source .venv-cli/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ./packaging/deeptutor-cli
```

Keep the checkout in place after installation because editable installs point
the `deeptutor` command at these source files.
