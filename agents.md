# AGENTS instructions

## Coding Standards

- **Always format and check Python files with ruff immediately after writing or editing them:** `uv run ruff format <file_path>` and `uv run ruff check --fix <file_path>`. Do this for every Python file you create or modify, before moving on to the next step.
- No `assert` in production code.
- Name functions and methods with action verbs: `get_`, `extract_`, `find_`, `compute_`, `build_`, etc. Avoid noun-only names like `_serialize_keys` or `_base_names` — they read as attributes, not callables. Predicates (`is_`, `has_`) are the one exception.
- Imports at top of file. Valid exceptions: circular imports, lazy loading for worker isolation, `TYPE_CHECKING` blocks.

## Testing Standards

- Target exactly 100% coverage of what the PR changes — no more, no less. Every changed or added behaviour must have a test; every test must fail without the PR's change. Do not add tests for pre-existing logic that was already present before the PR, and do not test standard-library or third-party functions. The exception is deliberate behaviour or integration tests, which may cross those boundaries by design.
- Use pytest patterns, not `unittest.TestCase`.
- Use `spec`/`autospec` when mocking.
- Use `time_machine` for time-dependent tests. Do not use `datetime.now()`
- Use `@pytest.mark.parametrize` for multiple similar inputs — consolidate tests that only differ in input/expected values into a single parametrized test.
- Use `@pytest.mark.db_test` for tests that require database access.
