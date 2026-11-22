# code

Forgel Code — thin console client for Forgel over the engine's machine-readable
commands.

The client does not import the engine. Its only channel is running
`forgel <command> --json` as a separate process and reading exactly one JSON
object from stdout. The model, sandbox, independent QA, review and release
approval stay in the engine: the client never calls a model, never reads
project files and never runs checks itself.

## Install

Forgel Code installs with one command. It needs Python 3.9 or newer with the
`pip` module it ships, and the `forgel` engine on `PATH`.

```sh
curl -fsSL https://raw.githubusercontent.com/forgel-dev/code/v0.1.0/install.sh | sh
```

The installer puts the client into `~/.local/share/forgel-code` and a
`forgel-code` launcher into `~/.local/bin`, then adds that directory to `PATH`
through one marked block in the profile your login shell reads. No virtual
environment and no activation step are involved, and the same command run again
replaces the installation instead of duplicating anything.

| Login shell | Profile file that receives the block |
| --- | --- |
| zsh | `~/.zshrc` |
| bash | the first existing of `~/.bash_profile`, `~/.bash_login`, `~/.profile`; `~/.bash_profile` is created when none of them exists |
| other POSIX `sh` | `~/.profile`, with a warning on stderr that names the file and the detected shell |

The login shell comes from `$SHELL`. When that is unset, empty or names a shell
the installer does not handle, it reads the shell of the invoking process and
then the account login shell — the macOS Directory Service entry, otherwise the
passwd entry — and only then falls back to `~/.profile`. The block is never
written to `~/.bashrc` alone, because a login bash shell does not read that
file. A profile file that does not exist yet is created.

The block carries a `case "$PATH:"` guard and prepends the launcher directory
only when it is not already there, so sourcing it again, or sourcing several
profiles that carry it, leaves exactly one entry. There is no unguarded
`export PATH=...` line.

After writing the block the installer checks it: it starts the detected login
shell as a login interactive shell from a cleared environment, under a bounded
time limit enforced without GNU `timeout`, and requires `command -v forgel-code`
to resolve to the launcher it just wrote. On success it prints the detected
shell, the edited profile file and the path that fresh shell resolved. If the
check fails, or the shell does not answer within the limit, it exits non-zero
and prints on stderr the edited profile file, the exact block it wrote, the
shell it checked, the `PATH` that shell saw and what `forgel-code` resolved to,
so a profile your login shell never reads is never reported as active.
Re-running keeps exactly one marked block and leaves the rest of the file as it
was.

The client has no dependencies and builds through the small in-tree PEP 517
backend (`_build_backend.py`), so the installer never needs a package index.
Editable installs are not supported: the backend implements only the
`build_wheel` and `build_sdist` hooks.

### Options

| Variable | Effect |
| --- | --- |
| `FORGEL_CODE_HOME` | installation prefix (default `~/.local/share/forgel-code`) |
| `FORGEL_CODE_BIN` | directory of the `forgel-code` launcher (default `~/.local/bin`) |
| `FORGEL_CODE_PROFILE` | shell profile that receives the `PATH` block, instead of the detected one; the uninstall cleans it too |
| `FORGEL_CODE_NO_MODIFY_PATH` | set it to leave the shell profile untouched |
| `FORGEL_CODE_SOURCE` | install from a local checkout instead of the network |

With `FORGEL_CODE_NO_MODIFY_PATH=1` no profile file is opened for writing, no
fresh-shell check runs, the installer prints the exact line to add yourself and
exits with code 0.

```sh
export PATH="$HOME/.local/bin:$PATH"
```

```sh
FORGEL_CODE_SOURCE=/path/to/code sh install.sh
```

The `forgel` engine must be available on `PATH`; use `--engine PATH` or
`$FORGEL_ENGINE` to point at a specific binary. `forgel-code --version` prints
the installed version.

### Update

```sh
curl -fsSL https://raw.githubusercontent.com/forgel-dev/code/v0.1.1/install.sh | sh
```

### Uninstall

```sh
curl -fsSL https://raw.githubusercontent.com/forgel-dev/code/v0.1.0/install.sh | sh -s -- --uninstall
```

The uninstall removes the installation prefix, the `forgel-code` launcher and
the marked `PATH` block from every profile file this installer can have written:
`~/.zshrc`, `~/.zprofile`, `~/.zshenv`, `~/.bash_profile`, `~/.bash_login`,
`~/.profile` and `~/.bashrc`. When `FORGEL_CODE_PROFILE` names another file, the
same run also removes the marked block from that exact file, so a block left
behind by an install that edited a custom profile — including an install that
wrote the block and then failed its fresh-shell check — does not survive. A file
that is missing or carries no marker is left alone, no file is created, and the
rest of each edited file is left unchanged.

Windows is not the main installation method; the fallback there is `python -m pip install --user` of the pinned revision.

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

From a checkout the suite needs nothing but the Python standard library:

```sh
python -m unittest discover -s tests
```

Installing the client with its `test` extra brings the pytest the wheel
declares, so a pinned revision can run the same suite too:

```sh
python3 -m pip install "https://github.com/forgel-dev/code/archive/refs/tags/v0.1.1.tar.gz[test]"
python -m pytest -q
```

## License

Apache-2.0. See [LICENSE](LICENSE).
