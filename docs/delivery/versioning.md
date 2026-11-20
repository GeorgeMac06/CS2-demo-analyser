# Versioning

CS2 Demo Scout follows [semantic versioning](https://semver.org): `MAJOR.MINOR.PATCH`.

## Where the version lives

- The version is only in `pyproject.toml`. `cs2scout.__version__` and `cs2scout --version` read it from there.
- Change it with `uv version 0.2.0` or `uv version --bump minor`. This also updates `uv.lock`. Add `--no-sync` when `cs2scout.exe` is running.
- Tags are `v` plus the version, for example `v0.2.0`.
- [GitHub Releases](https://github.com/GeorgeMac06/CS2-demo-analyser/releases) are the changelog. There is no `CHANGELOG.md`.

## What users rely on

This is an app, not a library. A change breaks something when it breaks one of these:

- the workspace folder (`library.sqlite`, parsed data, analyses, settings), and whether it still opens;
- the command line (`cs2scout`, its subcommands and flags);
- the environment variables `CS2SCOUT_HOME`, `CS2SCOUT_PORT`, `ANTHROPIC_API_KEY` and `CS2SCOUT_AI_MODEL`;
- export and brief files that people have already shared;
- the supported Python version and Windows.

## Which number goes up

| Bump | When | Examples |
|---|---|---|
| Major (from 1.0 on) | An existing workspace can't be opened, loses data, or needs a manual step. A command, flag or environment variable is removed or renamed. Python or Windows support is dropped. | A library change with no automatic migration. Renaming `CS2SCOUT_HOME`. |
| Minor | New behaviour the user can see. Any `SCHEMA_VERSION` bump. An automatic database migration that only adds. A new setting. | A new tab. New finding types. A new brief layout. |
| Patch | Fixes and tuning, with no new feature. | A wrong k/n fixed. Clearer wording. Thresholds tuned on real demos. A dependency bump with no visible change. |
| None | Nothing the user runs changes. No release needed. | Docs, tests, CI and `.claude/` files. |

If a PR fits more than one row, use the highest.

## While the version starts with 0

- A breaking change bumps the minor number and gets the `breaking` label as well. The release notes then call it out.
- `semver:major` is not used yet.
- We move to 1.0.0 once the prep document works and the workspace layout is settled. That is its own decision and PR.

## Labels

Every PR into `main` gets exactly one of these:

| Label | Meaning |
|---|---|
| `semver:major` | Breaking change. Only from 1.0 on. |
| `semver:minor` | New feature, or a `SCHEMA_VERSION` bump. |
| `semver:patch` | Fix or tuning. |
| `semver:none` | No release needed. |

Two more labels:

- `breaking`: added next to `semver:minor` for a breaking change while on 0.x.
- `release`: the PR that changes the version number.

Two workflows use the labels:

- **Version label** (`.github/workflows/pr-labels.yml`) fails until the PR has exactly one `semver:*` label.
- **Release notes** (`.github/workflows/release-notes.yml`) runs after each merge into `main`. It updates a draft GitHub release, with its notes grouped as Breaking changes, New, Fixes and Other, and the next version worked out from the labels. PRs labelled `semver:none` or `release` are left out. The rules are in `.github/release-drafter.yml`.

## Other version numbers

These stay separate from the app version. They decide what the app rebuilds, not what users see.

| Number | Where | Effect when it goes up |
|---|---|---|
| `SCHEMA_VERSION` | `src/cs2scout/core/findings.py` | Older analyses offer "Update now". |
| `EXTRACT_SCHEMA` | `src/cs2scout/core/schema.py` | Demos are parsed again. |
| Parser version | the installed awpy version, read in `src/cs2scout/parser/awpy_adapter.py` | Demos are parsed again. |
| Library `SCHEMA_VERSION` | `src/cs2scout/store/library.py` | An older app refuses the workspace. There is no migration code yet, so a change here also needs one. |

Raising any of them is at least a minor app bump. Raising the library schema without an automatic migration is a breaking change.

## How a release works

1. Open the draft release on GitHub (Releases). Its title is the next version, `vX.Y.Z`.
2. Open a "Release X.Y.Z" PR that runs `uv version X.Y.Z`. Give it the `release` and `semver:none` labels. Claude can prepare it.
3. The owner merges it.
4. The owner opens the draft, checks the notes and clicks **Publish release**. This creates the tag `vX.Y.Z` on `main`.
5. The **Release** workflow (`.github/workflows/release.yml`) then:
   - fails if the tag is not `v` plus the version in `pyproject.toml`, or is not on `main`;
   - runs G-fast and G-browser on the tag;
   - builds the wheel and sdist with `uv build` and attaches them to the release.

If the version in `pyproject.toml` already matches the draft, skip steps 2 and 3. This is the case for the first release, `v0.1.0`.

Teammates install a release with `uv tool install <link to the .whl>`. The README shows how.
