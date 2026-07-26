# Contributing to ha-fake-solis-probe

Thank you for your interest in contributing! This is a small community project, so
contributions are welcome — especially from people running different Solis models or
Tibber setups.

## Bug Reports

Please use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md).
Before filing, check existing issues to avoid duplicates.

**Important:** Remove all IP addresses, sensor entity IDs, and any personally
identifiable information before posting logs or configuration snippets.

## Feature Requests

Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md).

## Pull Requests

- Keep PRs small and focused — one change per PR
- Follow [PEP 8](https://pep8.org/) for Python code
- Update `CHANGELOG.md` under `[Unreleased]` with a short description of your change
- Install the development tools before running checks:
  `python -m pip install --requirement requirements-dev.txt`
- Apply Ruff's safe lint fixes and formatter before submitting:
  `ruff check --fix .` and `ruff format .`
- Verify Ruff is clean:
  `ruff check .` and `ruff format --check .`
- Compile all Python sources:
  `python -m compileall -q fake_solis_probe`
- Run the regression tests (the register-mapping suite uses pytest):
  `python -B fake_solis_probe/tests/test_behavior.py`,
  `python -B fake_solis_probe/tests/test_log_rotation.py`, and
  `python3 -B -m pytest fake_solis_probe/tests/test_register_mapping.py`
- Do not commit personal information (IP addresses, entity IDs, tokens, real names unless you choose to)

## Testing Locally

1. Copy `fake_solis_probe/` to your HA `/addons/` via Samba
2. Reload the addon store and install
3. Configure sensors and start the addon
4. Verify in the Log tab and `events.jsonl` that polling works
5. Confirm Tibber Bridge connects and reads data

## Code Style

- Python 3.11+, standard library only (no external dependencies)
- Ruff is used for linting, import sorting, and formatting. Run
  `ruff check --fix .` followed by `ruff format .` to apply both kinds of
  changes locally.
- Type hints on all public functions
- Log events via `log_event()` — do not use `print()` except in `load_options()` before logging is available
- All Modbus logic goes through `ModbusHandler` — do not add protocol handling elsewhere

## What We're Not Looking For

- Dependencies on external Python packages (keep it stdlib-only)
- Changes that forward any data to external services
- Hardcoded IP addresses, tokens, or entity IDs
