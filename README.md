# code

Forgel Code — thin console client for Forgel over the engine's machine-readable
commands.

The client does not import the engine. Its only channel is running
`forgel <command> --json` as a separate process and reading exactly one JSON
object from stdout. The model, sandbox, independent QA, review and release
approval stay in the engine: the client never calls a model, never reads
project files and never runs checks itself.

## Install

From the repository, one command:

```sh
pipx install git+https://github.com/forgel-dev/code   # or: pip install .
```

This provides the executable `forgel-code`. The engine (`forgel`) must be
available on `PATH`; use `--engine PATH` or `$FORGEL_ENGINE` to point at a
specific binary.

## Commands

Every client command is a thin wrapper over an existing engine command, and
the engine is always called with `--json`.

| Client command | Engine command | Purpose |
| --- | --- | --- |
| `forgel-code say <phrase>` | `forgel say <phrase> --json` | Turn a free phrase into a task |
| `forgel-code status` | `forgel status --json` | State of the task and the milestone |
| `forgel-code tasks` | `forgel tasks --json` | List tasks |
| `forgel-code task <task>` | `forgel task <task> --json` | State of one task |
| `forgel-code accept <task>` | — | No engine command yet; reported explicitly |
| `forgel-code rework <task> [remarks...]` | — | No engine command yet; reported explicitly |
| `forgel-code resume` | `forgel resume --json` | Start or resume work |
| `forgel-code pause` | `forgel pause --json` | Pause work |
| `forgel-code plan [goal...]` | `forgel plan [goal] --json` | Decompose the milestone goal into tasks |
| `forgel-code history` | `forgel history --json` | Short session history |
| `forgel-code projects` | `forgel projects --json` | List projects |
| `forgel-code session` | `forgel session --json` | Show the active client session |
| `forgel-code use <key>` | `forgel use <key> --json` | Select the active project |

### Output

Without a flag a command prints human readable text. With `--json` it prints
exactly one JSON object to stdout:

```json
{"command": "status", "project": "local", "ok": true, "result": {}}
```

On failure the engine's own message is printed to stderr, the client exits
with a non-zero code, and with `--json` it also prints one JSON object with
`"ok": false` and the message under `error`.

### Active project

The active project is the client's own session, with the key `local` by
default. `forgel-code use <key>` selects another project and persists the
choice; `forgel-code projects` lists what the engine knows about. Set
`FORGEL_CODE_HOME` to move the session file.

## Requirements the client does not cover

Accepting a task and sending it back for rework with remarks have no engine
command yet. The client says so instead of inventing behaviour; these will be
wired once the engine exposes them.

## Tests

```sh
python -m unittest discover -s tests
```

## License

Apache-2.0. See [LICENSE](LICENSE).
