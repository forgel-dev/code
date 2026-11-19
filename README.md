# code

Forgel Code — thin console client for Forgel over the engine's machine-readable
commands.

The client does not import the engine. Its only channel is running
`forgel <command> --json` as a separate process and reading exactly one JSON
object from stdout. The model, sandbox, independent QA, review and release
approval stay in the engine: the client never calls a model, never reads
project files and never runs checks itself.

## Install

Forgel Code installs with the pip bundled with Python 3 — no extra tool is
needed. Install a pinned revision — a tag, a commit hash or an exact version —
never the moving default branch. The first command block is the plain pip
install into a virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python3 -m pip install "git+https://github.com/forgel-dev/code@v0.1.0"
```

### System Python without a virtual environment

`--user` installs under your home directory, so neither root access nor a
virtual environment is required:

```sh
python3 -m pip install --user "git+https://github.com/forgel-dev/code@v0.1.0"
```

Once a release is published on a package index, the exact version pins the
same revision:

```sh
python3 -m pip install "forgel-code==0.1.0"
```

### Where `forgel-code` lands and how to reach it

pip writes the `forgel-code` executable into the `bin` directory of the
environment it installed into — `.venv/bin/forgel-code` after the activation
above, or `.venv\Scripts\forgel-code.exe` on Windows. A `--user` install uses
pip's user scripts directory instead: `~/.local/bin` on Linux and macOS,
`%APPDATA%\Python\Python3x\Scripts` on Windows.

Activating the virtual environment already puts `.venv/bin` on `PATH`. If
`forgel-code` is not found, locate the scripts directory and add it to `PATH`:

```sh
python3 -m site --user-base         # the user scripts live in <that>/bin
python3 -m pip show -f forgel-code  # files and location of the install
export PATH="$HOME/.local/bin:$PATH"   # Windows: setx PATH "%APPDATA%\Python\Python3x\Scripts;%PATH%"
```

With the scripts directory on `PATH`, `forgel-code --version` prints the
installed version.

### Fallback: run the module

A `PATH` that does not include the scripts directory is not fatal — the
interpreter the package was installed into can run it as a module:

```sh
python3 -m forgel_code --version
```

Use the interpreter that owns the install: `.venv/bin/python3` with the virtual
environment active, or the system `python3` after a `--user` install.

The build has no dependencies: the repository ships a small in-tree PEP 517
backend (`_build_backend.py`), so the install works offline and does not need
setuptools or a package index. The engine (`forgel`) must be available on
`PATH`; use `--engine PATH` or `$FORGEL_ENGINE` to point at a specific binary.

Editable installs (`pip install -e`) are not supported: the in-tree backend
implements only the `build_wheel` and `build_sdist` PEP 517 hooks.

`pipx`, an optional alternative for isolation only, can install the same pinned
revision (`git+https://github.com/forgel-dev/code@v0.1.0`) instead — plain pip
above stays the primary path.

### Update

Updating means installing a newer pinned revision over the old one;
`--upgrade` moves to that version:

```sh
python3 -m pip install --upgrade "git+https://github.com/forgel-dev/code@v0.1.1"
```

When the version number is unchanged and only the commit moved, pip can treat
the pinned requirement as already satisfied and keep the old code. Force the
reinstall of that exact commit:

```sh
python3 -m pip install --upgrade --force-reinstall "git+https://github.com/forgel-dev/code@<commit-sha>"
```

`forgel-code --version` prints the version that is actually installed, and
`python3 -m forgel_code --version` does the same when `PATH` does not help.

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
| `forgel-code accept <task>` | `forgel task accept --task <task> [--project <key>]` | Accept a task |
| `forgel-code rework <task> <remark...>` | `forgel task reject --task <task> --notes "<remark>" [--project <key>]` | Send a task back for rework with remarks |
| `forgel-code resume` | `forgel resume` | Start or resume work |
| `forgel-code pause` | `forgel pause` | Pause work |
| `forgel-code plan "<goal>" [--milestone <key>]` | `forgel plan [<key>] --goal "<goal>"` | Decompose the milestone goal into tasks |
| `forgel-code history` | `forgel history` | Short session history |
| `forgel-code projects` | `forgel projects` | List projects |
| `forgel-code session` | `forgel session` | Show the session the engine reports |
| `forgel-code use <key>` | `forgel use <key>` | Select the active project |

`forgel-code` does not read a project itself: `task <task>` asks the engine for
its task list and shows the one task you named. If that task is not in the
engine's answer — or appears there more than once — the client reports it and
exits with a non-zero code.

`accept` and `rework` lean on the engine's `task` command and its positional
actions: accepting is `task accept`, sending back is `task reject`, and the
remarks travel in the engine's `--notes`. The client adds no subcommand and no
option of its own. The exact engine calls behind them are:

```sh
forgel task accept --task <task> --json
forgel task reject --task <task> --notes "<remark>" --json
```

When the running engine does not provide the action a point needs, the client
prints the engine's own message plus an explicit note ("no engine command for
this point") and exits with a non-zero code instead of inventing behaviour.
That decision is taken from the engine's return code and structured error
fields, never from the wording of its message, so it does not depend on the
locale.

### Output

Without a flag a command prints human readable text. With `--json` it prints
exactly one JSON object to stdout:

```json
{"command": "status", "project": "acme", "ok": true, "result": {}}
```

The `project` field is the project key actually handed to the engine, or `null`
when nothing was passed. On failure — including an argument-parse error — the
client exits with a non-zero code and, with `--json`, prints one JSON object
with `"ok": false` and the message under `error`. A structured engine refusal
(`"ok": false` in the engine's answer) is a failure even when the engine exits
with code 0, and its own fields are carried through. A failure report names the
engine that answered: the path configured by `--engine`, `$FORGEL_ENGINE` or
`forgel` leads the message.

### Active project

`forgel-code use <key>` hands the key to the engine and, only when the engine
accepts it, makes it the active project; every project-scoped command then
passes `--project <key>`. `forgel-code projects` lists what the engine knows
about. Until you pick a key no `--project` argument is sent, so the engine's own
active project is used. Set `FORGEL_CODE_HOME` to move the session file.

### Timeout

The engine call is bounded. `--timeout SECONDS` sets the limit for one call,
`$FORGEL_CODE_TIMEOUT` sets it for the environment, and the default is 600
seconds. When the limit elapses the client kills the engine and fails with a
structured error instead of blocking. The engine's stdout is always decoded as
UTF-8 and the child process does not receive the client's stdin.

`--json`, `--engine` and `--timeout` are parsed as options of their own and are
never substituted inside argument text, so a phrase or remark that mentions
such a word reaches the engine unchanged. Put `--` before a remark that itself
begins with a hyphen.

## Tests

```sh
python -m unittest discover -s tests
```

`python3 -m pytest -q` runs the same suite: when pytest is not installed, the
in-tree `pytest.py` shim forwards to `unittest`, and a real pytest is used when
it is available.

## License

Apache-2.0. See [LICENSE](LICENSE).
