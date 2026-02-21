# Repository Guidelines

## Project Structure & Module Organization
This repository is a QGIS (PyQGIS) plugin. Core runtime code lives at the top level.
Key paths:
- `APC_Plan.py`: plugin entry point and main logic.
- `APC_Plan_dialog.py`: Qt dialog controller.
- `APC_Plan_dialog_base.ui`: Qt Designer UI definition.
- `resources.qrc` and `resources.py`: Qt resource bundle.
- `icons/`: plugin icons used in the UI.
- `i18n/`: translation sources (`.ts`) and compiled files (`.qm`).
- `help/`: Sphinx docs sources and build output.
- `test/`: unit/integration tests plus fixtures.
- `metadata.txt`: QGIS plugin metadata.

## Build, Test, and Development Commands
Make targets are defined in `Makefile`:
- `make compile`: build `resources.py` from `resources.qrc` using `pyrcc5`.
- `make test`: run nose tests with coverage (requires a QGIS Python environment).
- `make pylint`: lint with `pylint` using `pylintrc`.
- `make pep8`: style check with `pep8` and repository-specific ignores.
- `make transup`: update translation `.ts` files.
- `make transcompile`: compile translations to `.qm`.
- `make doc`: build Sphinx docs in `help/`.
Linux users can set up QGIS environment variables with `scripts/run-env-linux.sh`.

## Coding Style & Naming Conventions
Style is enforced by `pylintrc`:
- Indentation: 4 spaces, max line length 80.
- Classes: `PascalCase` (regex in `pylintrc`).
- Functions, methods, variables: `snake_case` (3–30 chars).
- Constants: `UPPER_SNAKE_CASE`.
Run `make pylint` and `make pep8` before submitting changes.

## Testing Guidelines
Tests live in `test/` and follow the `test_*.py` naming pattern (e.g., `test_resources.py`).
Run `make test` to execute `nosetests` with coverage. If QGIS imports fail, load a QGIS
runtime first (see `scripts/run-env-linux.sh` for Linux).

## Commit & Pull Request Guidelines
This checkout does not include Git history, so no existing commit convention is visible.
Use concise, imperative messages (e.g., `Add survey export dialog`) and reference issues
if your workflow uses them. PRs should include:
- A short summary of behavior changes.
- Test evidence (command and result).
- Screenshots or GIFs for UI changes.

## Environment & Configuration Tips
This plugin expects a QGIS Python environment with PyQt and `pyrcc5` installed.
If you use `pb_tool`, review `pb_tool.cfg` for deploy settings and update paths as needed.
