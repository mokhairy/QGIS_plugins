# Repository Guidelines

## Project Structure & Module Organization
This repository is a workspace of independent QGIS plugins, not a single package. Each top-level plugin directory (for example `apc_plan/`, `SaveAllScript/`, `OpenTopography-DEM-Downloader/`) is self-contained and usually includes:
- `__init__.py`, main plugin module(s), and `metadata.txt`
- optional UI/resources (`*.ui`, `resources.qrc`, `resources.py`, `icons/`)
- optional `test/`, `scripts/`, `i18n/`, and `help/`

Use plugin-local files for changes, tests, and packaging. Root-level `sync_qgis_plugins.sh` syncs this workspace with the local QGIS plugins profile.

## Build, Test, and Development Commands
Run commands from the specific plugin directory you are modifying:
- `make compile`: compile Qt resources/translations when configured.
- `make test`: run plugin regression tests (nose-based in plugin Makefiles).
- `make pylint`: run linting with the plugin’s `pylintrc`.
- `make deploy`: copy plugin files into a QGIS profile plugin path.
- `make package VERSION=<tag-or-commit>`: create a distributable zip from Git history.

Environment setup for QGIS-dependent tests/lint:
- `source scripts/run-env-linux.sh /path/to/qgis`

Optional plugin builder workflow (where `pb_tool.cfg` exists):
- `pb_tool deploy`
- `pb_tool zip`

## Coding Style & Naming Conventions
Use Python conventions reflected in project `pylintrc` files:
- 4-space indentation, max line length 80
- `snake_case` for modules/functions/variables
- `CapWords` for classes
- preserve established plugin entry filenames (`plugin.py`, `*_dialog.py`, etc.)

Keep `metadata.txt` and any referenced resources/icons consistent with code changes.

## Testing Guidelines
Tests live under each plugin’s `test/` directory and follow `test_*.py` naming. Current suites use `unittest` with QGIS test helpers. For every behavior change:
- add/update a focused test in the same plugin
- run `make test` in that plugin directory
- include QGIS-environment notes if tests require local setup

## Commit & Pull Request Guidelines
This checkout has no root `.git` metadata, so follow a clear default convention:
- commit format: `type(scope): summary` (example: `fix(apc_plan): validate missing layer input`)
- keep commits scoped to one plugin when possible
- PRs should include changed plugin paths, test/lint evidence, linked issue, and screenshots for UI changes (`.ui`, icons, dialogs)

## Security & Configuration Tips
Do not commit API keys, tokens, or machine-specific QGIS paths. Keep secrets in local config only, and verify deploy paths before running `make deploy`.
