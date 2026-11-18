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

This provides the executable `forgel-code`. The build has no dependencies: the
repository ships a small in-tree PEP 517 backend (`_build_backend.py`), so the
install works offline and does not need setuptools or a package index. The
engine (`forgel`) must be available on `PATH`; use `--engine PATH` or
`$FORGEL_ENGINE` to point at a specific binary.

## Commands

Every client command is a thin wrapper over an existing engine command, and
the engine is always called with `--json`. `<key>` below is the project the
client session selected with `forgel-code use`; while nothing is selected the
client passes no `--project` and the engine keeps its own active project.

| Client command | Engine command | Purpose |
| --- | --- | --- |
| `forgel-code say <phrase>` | `forgel say "<phrase>"` | Turn a free phrase into a task |
| `forgel-code status` | `forgel status` | State of the task and the milestone |
| `forgel-code tasks` | `forgel tasks` | List tasks |
| `forgel-code task <task>` | `forgel tasks` | State of one task, picked out of the engine's task list |
| `forgel-code accept <task>` | `forgel task --accept [--project <key>] --task <task>` | Accept a task |
| `forgel-code rework <task> <remark...>` | `forgel task [--project <key>] --task <task> --notes "<remark>"` | Send a task back for rework with remarks |
| `forgel-code resume` | `forgel resume` | Start or resume work |
| `forgel-code pause` | `forgel pause` | Pause work |
| `forgel-code plan <milestone> [goal...]` | `forgel plan <milestone> [--goal "<goal>"]` | Decompose the milestone goal into tasks |
| `forgel-code history` | `forgel history` | Short session history |
| `forgel-code projects` | `forgel projects` | List projects |
| `forgel-code session` | `forgel session` | Show the session the engine reports |
| `forgel-code use <key>` | `forgel use <key>` | Select the active project |

`forgel-code` does not read a project itself: `task <task>` asks the engine for
its task list and shows the one task you named. If that task is not in the
engine's answer, the client reports it and exits with a non-zero code.

`accept` and `rework` lean on the engine's `task` command: `accept` asks for
`--accept`, `rework` carries the remarks in `--notes`. The client adds no
subcommand of its own. The exact engine calls behind them are:

```sh
forgel task --accept --task <task> --json
forgel task --task <task> --notes "<remark>" --json
```

When the running engine does not provide the option a point needs, the client
prints the engine's own message plus an explicit note ("no engine command for
this point") and exits with a non-zero code instead of inventing behaviour.

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
default. `forgel-code use <key>` hands the key to the engine and, only when
the engine accepts it, makes it the active project; `forgel-code projects`
lists what the engine knows about. The default `local` label is never sent to
the engine as a project, so the engine's own active project is used until you
pick one explicitly. Set `FORGEL_CODE_HOME` to move the session file.

## Tests

```sh
python -m unittest discover -s tests
```

## License

Apache-2.0. See [LICENSE](LICENSE).
