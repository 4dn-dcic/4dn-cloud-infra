# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Build, test, validate

- `make build` (poetry install), `make test` (pytest), `make alpha` (synthesize + validate the core
  alpha stacks). CI runs all three against a mock `custom/config.json` — see `.github/workflows/main.yml`.
- `cli provision <stack> --stdout` synthesizes a stack's CloudFormation without touching AWS; that is
  the cheapest way to inspect a template change. `--validate` shells out to Docker + real AWS creds.
- Stack registrations (name → part/stack class) live in `src/stacks/alpha_stacks.py`.

## Sharp edges

- **An output has two names.** Its *output key* is the template logical id
  (`C4SRCENetworkMainApplicationSecurityGroup`, = `C4` + title token + camelized sharing qualifier +
  export id); its *export name* is `<stack name>-<export id>`
  (`c4-srce-network-main-stack-ApplicationSecurityGroup`), which is what `C4Exports.export()` writes
  and `Fn::ImportValue` reads. CloudFormation consumers resolve the export name at deploy time;
  pre-deploy resolvers (Foursight) should match the *same* export name, via
  `ConfigManager.find_stack_exports`, so both agree. Matching the logical id instead couples the
  lookup to stack tokens/qualifiers that can change independently.
- **Cross-stack export discovery is regex over `OutputKey`, account-wide.** `ConfigManager.find_stack_outputs`
  (`src/base.py`) scans *every* CloudFormation stack in the account and matches the output key, so the
  `_*_EXPORT_PATTERN` regexes in `src/parts/*.py` are only as safe as they are specific. Anything that
  cannot use `ImportValue` — notably Foursight, which chalice packages from literal IDs — resolves this
  way. `ConfigManager.find_stack(name_token)` has the same hazard: it matches on the `c4-<token>-` prefix,
  so a token that prefixes a sibling stack's name (`srce-network` vs `srce-network-db`) raises.
- **SRCE is three IT-provided VPCs** (Application / Database / Compute) whose network stacks deliberately
  export *identical* key names so downstream stacks import unchanged. That makes loose export regexes
  ambiguous. Foursight Lambdas must resolve to the Application VPC only — see
  `docs/source/deploy_srce.rst` ("Foursight Lambda networking contract") and
  `tests/test_srce_foursight_vpc.py`. The SRCE deploy target is `foursight-srce`; `--foursight-identity`
  sets only the `IDENTITY` env var and never selects SRCE networking.
- **`foursight_core.deploy.Deploy.build_config()` is vendored and mutates class state.** It gates on
  `if security_group_ids:`, so an empty resolution writes no `VpcConfig` and silently keeps whatever is
  already in `.chalice/config.json`; resolvers feeding it should fail loudly rather than return `[]`.
  Its `CONFIG_BASE` must be deep-copied per Foursight variant (`foursight_config_base` in `src/stack.py`).
- **Which application library ships is chosen by the provision target's *name*.**
  `build_config_and_package()` matches the caller's `args.stack` against target lists hardcoded in
  `foursight_core` (only `foursight-development`/`foursight-production` → `foursight_fourfront`,
  only `foursight-smaht` → `foursight_smaht`, everything else → `foursight_cgap`) to pick the poetry
  group exported into `requirements.txt`. Any *new* Foursight target is therefore silently packaged as
  CGAP while `app.py` imports whichever `chalicelib_*` its runtime env implies — a `Runtime.ImportModuleError`
  at Lambda startup, not a packaging error. A new variant must present a name that classifier knows;
  `C4FoursightSMAHTSRCEStack.PackageDeploy.build_config_and_package` (`src/stack.py`) is the pattern.
- **The fixed deployments must synthesize byte-identically.** Fourfront and the existing CGAP
  deployments are fixed infrastructure. `tests/test_fixed_stack_parity.py` fingerprints every
  registered stack's template across all app kinds and both deployment paradigms and compares it
  against `tests/parity/fixed_stack_baseline.json`, generated from `origin/master` by
  `tests/parity/synthesis_matrix.py` (run inside a `git archive` of the ref -- never against a
  feature branch, or the baseline asserts its own result). New behaviour for a new deployment goes
  behind a config gate that is off by default, or into a subclass; `ecr` and `appconfig` are the
  only stacks allowed a delta, and only an additive one.

- **Config list values arrive as strings.** `ConfigManager._load_config` stringifies every setting so it
  can be sourced into `os.environ`, so a JSON list in `config.json` reaches consumers as its Python repr —
  see the CLN-10 note in `src/base.py` and `_parse_subnet_ids` in `src/parts/srce_network.py`.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
