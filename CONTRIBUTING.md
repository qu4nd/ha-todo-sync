# Contributing to To-do Sync

Thanks for your interest in contributing! To-do Sync is a small Home Assistant integration, and focused changes are usually easier to review and maintain than broad refactorings.

## Development setup

The project tests run with Python 3.13 and Home Assistant's custom-component test helpers.

1. Clone the repository and enter its directory.
2. Create and activate a virtual environment.
3. Install `uv` and the test dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   python -m pip install uv
   uv pip install -r requirements_test.txt
   ```

   On Windows, activate the environment with `.venv\\Scripts\\activate`.

4. Run the test suite from the repository root:

   ```bash
   PYTHONPATH=. pytest -q
   ```

The same test command is used by the GitHub Actions validation workflow. The workflow installs the test dependencies with `uv` and also runs Home Assistant's hassfest validation and HACS validation.

## Project structure

- `custom_components/todo_sync/__init__.py`: synchronization engine, lifecycle, event handling, snapshot storage, conflict resolution and retries.
- `custom_components/todo_sync/config_flow.py`: initial list selection and periodic interval options.
- `custom_components/todo_sync/button.py`: the per-configuration **Sync now** button.
- `custom_components/todo_sync/const.py`: integration domain, configuration keys and shared constants.
- `custom_components/todo_sync/translations/`: English and German UI strings.
- `tests/`: automated tests for synchronization behavior.

## Synchronization model

To-do items are matched by their normalized name: leading/trailing whitespace is removed and matching is case-insensitive. The integration stores a snapshot of the last successfully synchronized state and compares both current lists against it (a three-way comparison).

This snapshot is important: it lets the integration distinguish a change on one side from a conflict where both sides changed. If both sides changed, the list that triggered the run wins; a periodic run without a triggering list defaults to List A.

A few behaviors are intentional:

- Both lists are read before any changes are applied. A failed read must not be interpreted as an empty list.
- Completed items are treated as provider history and are not recreated or deleted on the other list when absent there.
- A sudden disappearance of at least five open items and more than half of the open snapshot is held back for six minutes before it is accepted.
- Read and write failures are retried with bounded exponential backoff, starting at 30 seconds and capped at 300 seconds. Failed item writes keep their previous snapshot value so the next run can detect and retry the outstanding change.

Please preserve these safety properties when changing the synchronization flow. Add a regression test whenever a change affects conflict resolution, deletion handling, snapshots, or retries.

## Making a change

- Keep changes focused and avoid provider-specific behavior unless there is a demonstrated compatibility need.
- Prefer comments that explain *why* a decision or safety check exists; avoid comments that merely repeat the code.
- Update the English and German translations together when changing user-facing configuration strings.
- Update the README when user-visible behavior, setup steps, limitations, or examples change.
- Add or adjust tests for behavior changes. Do not weaken an assertion merely to make a failing test pass; first verify that the test exercises the intended code path.
- Run `PYTHONPATH=. pytest -q` before opening a pull request.

Contributions are welcome through pull requests. Please use a pull request to propose any change; direct commits to the project are not part of the contribution workflow. Each pull request should address one focused change, explain the motivation and user-visible impact, and describe the tests or validations performed. If a change is based on provider-specific behavior, include the provider and a reproducible description. Submitting a pull request does not guarantee that it will be accepted or merged.
