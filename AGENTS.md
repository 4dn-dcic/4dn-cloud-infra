# Project agent memory

- CI setup and its required dummy `custom/config.json` / `custom/secrets.json` are in `.github/workflows/main.yml`; reproduce with locked dependencies and `pytest tests src/tests`. Missing config can mask actual failures with import/collection errors. `poetry.toml` disables automatic virtualenv creation, so establish an isolated environment first.
- For offline validation, synthesize in-process and use local `cfn-lint`, with fake credentials and network/SDK calls blocked. `make alpha` and `cli provision --validate` contact CloudFormation; they are not offline checks. Foursight packaging and some export lookups require deployed infrastructure.
- `ConfigManager` in `src/base.py` stringifies JSON values; many part attributes resolve config at import time. Establish app/deployment settings before importing stack modules (use separate processes for configuration matrices).
- Use the naming helpers in `src/names.py` when seeding AWS mocks, rather than reconstructing legacy names. In particular, GAC secrets belong to the appconfig stack, not the datastore naming scheme.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
