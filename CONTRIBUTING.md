# Contributing to firnline

Thanks for your interest in contributing.

## How to Propose Changes

1. **Open an issue** first — describe the bug or feature before writing code.
   Use the issue templates in `.github/ISSUE_TEMPLATE/`.

2. **Fork the repo**, create a feature branch, make your changes.

3. **Run the full test suite** before opening a PR:

   ```bash
   uv sync --all-packages
   uv run pytest
   ```

   Tests run with no network requirement (mocked external calls). Integration
   tests (requiring a running dev instance) are deselected by default; run them
   explicitly with:

   ```bash
   uv run pytest -m integration
   ```

4. **Run the linter:**

   ```bash
   uv run ruff check
   ```

   Formatting is automatic with:

   ```bash
   uv run ruff format
   ```

5. **Run the melt test** — ensures the kernel (firnline-core, zero extensions)
   composes, generates code, imports, and passes its test suite without any
   extension dependency:

   ```bash
   bash scripts/melt-test.sh
   ```

   The melt test is also run by `scripts/validate-release.sh` and gates every
   release. It verifies that no kernel module accidentally depends on an
   extension.

6. **Open a pull request** — fill in the PR template. Reference the related
   issue. Keep PRs small and focused (one concern per PR).

## Pull Request Bar

A PR is ready to merge when:

- [ ] Issue exists and is linked in the PR description
- [ ] All existing tests pass (`uv run pytest`)
- [ ] New tests cover the changed behaviour
- [ ] `uv run ruff check` is clean
- [ ] The melt test passes (`bash scripts/melt-test.sh`)
- [ ] New schema / configuration is documented in the relevant doc pages
- [ ] Commit messages follow [conventional
  commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`,
  etc.)

## Code Style

- Python 3.12+
- Ruff for linting (`E`, `F`, `W` rules; line length 120)
- Double quotes, spaces for indentation
- Type hints on all public functions
- `asyncio_mode = "auto"` for pytest-asyncio

## Project Layout

The monorepo uses `uv` workspaces. See
[docs/development/project-structure.md](docs/development/project-structure.md)
for the full layout.

## Need Help?

Open a [discussion](https://github.com/BaLion29/lms/discussions) or comment
on a relevant issue.
