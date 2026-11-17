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
the engine is always called with `--json`. `<key>` below is the active project
of the client session.

| Client command | Engine command | Purpose |
| --- | --- | --- |
| `forgel-code say <phrase>` | `forgel say "<phrase>"` | Turn a free phrase into a task |
| `forgel-code status` | `forgel status` | State of the task and the milestone |
| `forgel-code tasks` | `forgel tasks` | List tasks |
| `forgel-code task <task>` | `forgel tasks` | State of one task, picked out of the engine's task list |
| `forgel-code accept <task>` | `forgel task accept --project <key> --task <task>` | Accept a task |
| `forgel-code rework <task> [remark...]` | `forgel task reject --project <key> --task <task> --reason "<remark>"` | Send a task back for rework with remarks |
| `forgel-code resume` | `forgel resume` | Start or resume work |
| `forgel-code pause` | `forgel pause` | Pause work |
| `forgel-code plan <milestone> [goal...]` | `forgel plan <milestone> [--goal "<goal>"]` | Decompose the milestone goal into tasks |
| `forgel-code history` | `forgel history` | Short session history |
| `forgel-code projects` | `forgel projects` | List projects |
| `forgel-code session` | `forgel session` | Show the active client session |
| `forgel-code use <key>` | `forgel use <key>` | Select the active project |

`forgel-code` does not read a project itself: `task <task>` asks the engine for
its task list and shows the one task you named. If that task is not in the
engine's answer, the client reports it and exits with a non-zero code.

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

## Tests

```sh
python -m unittest discover -s tests
```

## License

Apache-2.0. See [LICENSE](LICENSE).
