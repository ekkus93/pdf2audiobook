# CLI output contracts

JSON Schemas (draft 2020-12) for every CLI output the desktop app reads (spec D9.c). They are the
single source for both sides: the Python tests check real CLI output against them, and the Rust
tests check the bridge's parser fixtures against them.

Fields may be added to an output, so objects allow extra properties; a listed field may never be
renamed, removed or change type without updating these files and both sides' tests.

| Schema | Output |
|---|---|
| `doctor` | `doctor --json` |
| `config-show` | `config show --sources --json` |
| `inspect-book`, `inspect-manifest` | `inspect BOOK --json`, `inspect MANIFEST --json` |
| `workspace`, `voices`, `thumbnail` | the commands of the same name with `--json` |
| `analyze`, `convert`, `convert-dry-run` | `analyze --json`, `convert --json`, `convert --dry-run --json` |
| `edits-list`, `pack-m4b` | `edits list --json`, `pack-m4b --json` |
| `review-address` | the first stdout line of `review --json` |
| `error` | the last JSON line on stderr of any failed command |
| `run-status` | `reports/run_status.json` in a workspace |
