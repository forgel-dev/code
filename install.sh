#!/bin/sh
# Forgel Code installer.
#
# One command installs the client into a per-user prefix:
#
#   curl -fsSL https://raw.githubusercontent.com/forgel-dev/code/v0.1.0/install.sh | sh
#
# The client goes into ${FORGEL_CODE_HOME:-$HOME/.local/share/forgel-code}, the
# ``forgel-code`` launcher into ${FORGEL_CODE_BIN:-$HOME/.local/bin}, and that
# directory is put on PATH through one marked block in the profile an
# interactive login session of the login shell reads. The login shell is taken
# from $SHELL, then from the invoking process (ps), then from the account login
# shell; a shell outside the zsh and bash families gets the block in
# $HOME/.profile and a warning that names the edited file. After writing the
# block the installer starts that shell as a login interactive shell from a
# cleared environment, under a hard time limit, and checks that
# ``forgel-code`` resolves to the launcher it just wrote. Re-running replaces the
# installation; running with ``--uninstall`` removes it again.
#
# Environment variables:
#   FORGEL_CODE_HOME            install prefix (default: $HOME/.local/share/forgel-code)
#   FORGEL_CODE_BIN             launcher directory (default: $HOME/.local/bin)
#   FORGEL_CODE_SOURCE          local checkout to install from, without network
#   FORGEL_CODE_TAG             repository tag when no checkout is given (default: v0.1.0)
#   FORGEL_CODE_REPOSITORY      repository URL used with FORGEL_CODE_TAG
#   FORGEL_CODE_PYTHON          Python 3 interpreter (default: python3 on PATH)
#   FORGEL_CODE_PROFILE         shell profile to edit (default: chosen from the login shell)
#   FORGEL_CODE_NO_MODIFY_PATH  set to leave the shell profile untouched
#   FORGEL_CODE_NO_PROFILE_EDIT the same opt-out under its older name
#   FORGEL_CODE_TIMEOUT         seconds the fresh-shell check may take (default: 10)
#   FORGEL_CODE_VERIFY_GRACE    seconds between the graceful stop and the
#                               forceful one when the bound elapses (default: 2)
#   FORGEL_CODE_POLL_MS         how often, in milliseconds, the watchdog looks
#                               at the checked process (default: 1000)
#
# The script is POSIX ``sh`` and safe to pipe into: it never reads stdin.

set -eu

# The exact markers an uninstall looks for. They are compared byte for byte.
MARKER_START='# >>> forgel-code >>>'
MARKER_END='# <<< forgel-code <<<'

# A profile whose last line has no final newline cannot be restored byte for
# byte from the block alone: the newline that separates that line from the
# block is indistinguishable from one the file always had. The installer
# records the case in one comment line directly above the block and removes
# that line, with the separator newline, together with the block.
MARKER_SEPARATOR='# forgel-code: the line above had no final newline'

HOME_DIR=${HOME:-/}
PREFIX=${FORGEL_CODE_HOME:-$HOME_DIR/.local/share/forgel-code}
BIN_DIR=${FORGEL_CODE_BIN:-$HOME_DIR/.local/bin}
LAUNCHER=$BIN_DIR/forgel-code
TAG=${FORGEL_CODE_TAG:-v0.1.0}
REPOSITORY=${FORGEL_CODE_REPOSITORY:-https://github.com/forgel-dev/code}

# What a fresh shell reports back: its own PATH and the path it resolves
# ``forgel-code`` to. The prefixes keep the answer readable next to anything a
# system-wide profile may print.
CHECK_PATH=/usr/bin:/bin
CHECK_COMMAND='printf "forgel-fresh-path=%s\n" "$PATH"; fresh=$(command -v forgel-code || true); printf "forgel-fresh-resolved=%s\n" "$fresh"'

# The bound for the fresh-shell check, in seconds, when FORGEL_CODE_TIMEOUT is
# unset, the grace period the checked shell gets between the graceful stop and
# the forceful one, and the watchdog's poll interval in milliseconds. A login
# shell reads its startup files in milliseconds; ten seconds leaves room on a
# slow machine and still bounds a shell that never answers.
DEFAULT_VERIFY_LIMIT=10
VERIFY_GRACE=2
VERIFY_POLL_MS=1000

# The profile files this installer can have written. ``--uninstall`` cleans the
# block out of every one of them, so no stale PATH entry stays behind. The list
# is a superset of what the install path may edit, including ~/.bashrc, because
# a non-login bash session reads that file and an earlier installation could
# have left its block there.
PROFILE_NAMES='.zshrc .zprofile .zshenv .bash_profile .bash_login .profile .bashrc'

# Set by ``verify_profile`` once the fresh shell resolved the launcher.
VERIFIED_PATH=

# What the bounded check owns while it runs: its private directory, the process
# it started and the watchdog that bounds it. Every one of them is released by
# ``cleanup_check``, whichever way the script ends.
CHECK_DIR=
CHECK_CHILD=
CHECK_WATCHER=

# Set by ``bounded_run``: the exit status of the checked command and what it
# printed. A status of 124 means the bound elapsed.
CHECK_STATUS=0
CHECK_OUTPUT=

usage() {
    cat <<'USAGE'
Usage: install.sh [--uninstall] [--help]

Installs the Forgel Code client into ${FORGEL_CODE_HOME:-$HOME/.local/share/forgel-code}
and its launcher into ${FORGEL_CODE_BIN:-$HOME/.local/bin}, adding that directory
to PATH with one marked block in the profile the login shell reads. The result
is checked in a freshly started login interactive shell under a bounded time
limit.

  --uninstall   remove the installation, the launcher and the PATH block
  --help        show this text

Set FORGEL_CODE_NO_MODIFY_PATH=1 to leave the shell profile untouched; the
script then prints the exact export PATH=... line to add yourself.
USAGE
}

detect_python() {
    if [ -n "${FORGEL_CODE_PYTHON:-}" ]; then
        printf '%s\n' "$FORGEL_CODE_PYTHON"
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return 0
    fi
    if command -v python >/dev/null 2>&1; then
        command -v python
        return 0
    fi
    return 1
}

# A directory counts as a checkout only when it is this project, so a stray
# pyproject.toml next to the caller cannot silently install another package.
is_forgel_code_source() {
    directory=$1
    if [ -z "$directory" ] || [ ! -d "$directory" ]; then
        return 1
    fi
    if [ ! -d "$directory/forgel_code" ] || [ ! -f "$directory/pyproject.toml" ]; then
        return 1
    fi
    grep -q 'name = "forgel-code"' "$directory/pyproject.toml"
}

# The directory holding this script. With ``curl ... | sh`` there is none.
script_directory() {
    case ${0:-} in
        */*) cd -P -- "${0%/*}" 2>/dev/null && pwd ;;
        *) return 1 ;;
    esac
}

resolve_source() {
    if [ -n "${FORGEL_CODE_SOURCE:-}" ]; then
        if ! is_forgel_code_source "$FORGEL_CODE_SOURCE"; then
            echo "install.sh: FORGEL_CODE_SOURCE is not a Forgel Code checkout: $FORGEL_CODE_SOURCE" >&2
            return 1
        fi
        printf '%s\n' "$FORGEL_CODE_SOURCE"
        return 0
    fi
    for candidate in "$(script_directory 2>/dev/null || true)" "$(pwd)"; do
        if is_forgel_code_source "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    printf '%s\n' "$REPOSITORY/archive/refs/tags/$TAG.tar.gz"
}

# The account login shell: the macOS Directory Service entry first, then the
# passwd database. Prints nothing when neither source answers.
account_login_shell() {
    if command -v dscl >/dev/null 2>&1; then
        found=$(dscl . -read "$HOME_DIR" UserShell 2>/dev/null | sed -n 's/^UserShell:[[:space:]]*//p' | head -n 1) || found=
        if [ -n "$found" ]; then
            printf '%s\n' "$found"
            return 0
        fi
    fi
    user=$(id -u 2>/dev/null) || user=
    if [ -n "$user" ]; then
        found=
        if command -v getent >/dev/null 2>&1; then
            found=$(getent passwd "$user" 2>/dev/null | cut -d: -f7 | head -n 1) || found=
        fi
        if [ -z "$found" ] && [ -r /etc/passwd ]; then
            found=$(awk -F: -v u="$user" '$3 == u { print $7; exit }' /etc/passwd) || found=
        fi
        if [ -n "$found" ]; then
            printf '%s\n' "$found"
            return 0
        fi
    fi
    printf '\n'
}

shell_name() {
    printf '%s\n' "${1##*/}"
}

# The shells whose login sessions this installer can place a PATH block for.
is_handled_shell() {
    case $(shell_name "$1") in
        zsh|bash|sh|dash|ksh|ksh93|mksh|pdksh|ash|yash) return 0 ;;
    esac
    return 1
}

# The shell of the invoking process, read with ps. A piped run often has no
# useful $SHELL but a meaningful parent shell. Prints nothing when that process
# is not a shell this installer handles or cannot be resolved.
parent_login_shell() {
    if ! command -v ps >/dev/null 2>&1; then
        return 1
    fi
    pid=${PPID:-}
    if [ -z "$pid" ]; then
        return 1
    fi
    found=$(ps -p "$pid" -o comm= 2>/dev/null) || found=
    found=${found%%[[:space:]]*}
    # A login shell often reports itself as ``-zsh``.
    found=${found#-}
    if [ -z "$found" ] || ! is_handled_shell "$found"; then
        return 1
    fi
    if ! resolved=$(command -v "$found" 2>/dev/null) || [ -z "$resolved" ]; then
        return 1
    fi
    printf '%s\n' "$resolved"
}

# The shell that reads the edited profile for an interactive login session.
# $SHELL decides when it names a shell we handle; otherwise the invoking process
# and then the account login shell decide, and a POSIX ``sh`` is the last
# resort, which reads $HOME/.profile. An empty $SHELL never decides for bash by
# itself.
detect_login_shell() {
    candidate=${SHELL:-}
    if [ -n "$candidate" ] && is_handled_shell "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
    fi
    candidate=$(parent_login_shell) || candidate=
    if [ -n "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
    fi
    candidate=$(account_login_shell) || candidate=
    if [ -n "$candidate" ] && is_handled_shell "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
    fi
    printf '%s\n' /bin/sh
}

shell_family() {
    case $(shell_name "$1") in
        zsh) printf '%s\n' zsh ;;
        bash) printf '%s\n' bash ;;
        *) printf '%s\n' posix ;;
    esac
}

# Which profile file an interactive login session of the detected shell reads.
# The block never goes into $HOME/.bashrc alone: a login bash does not read it.
profile_path() {
    if [ -n "${FORGEL_CODE_PROFILE:-}" ]; then
        printf '%s\n' "$FORGEL_CODE_PROFILE"
        return 0
    fi
    case $(shell_family "$DETECTED_SHELL") in
        zsh)
            printf '%s\n' "$HOME_DIR/.zshrc"
            ;;
        bash)
            for name in .bash_profile .bash_login .profile; do
                if [ -f "$HOME_DIR/$name" ]; then
                    printf '%s\n' "$HOME_DIR/$name"
                    return 0
                fi
            done
            printf '%s\n' "$HOME_DIR/.bash_profile"
            ;;
        *)
            printf '%s\n' "$HOME_DIR/.profile"
            ;;
    esac
}

no_profile_edit() {
    case ${FORGEL_CODE_NO_MODIFY_PATH:-} in
        ''|0|false|no|off) ;;
        *) return 0 ;;
    esac
    case ${FORGEL_CODE_NO_PROFILE_EDIT:-} in
        ''|0|false|no|off) ;;
        *) return 0 ;;
    esac
    return 1
}

# The marked block. Its body is a POSIX ``case ":$PATH:"`` guard: the launcher
# directory is prepended only when it is not already in PATH, so sourcing the
# block twice, or from several profiles, leaves one entry in PATH.
print_block() {
    printf '%s\n' "$MARKER_START"
    printf 'case ":$PATH:" in\n'
    printf '    *":%s:"*) ;;\n' "$BIN_DIR"
    printf '    *) PATH="%s:$PATH" ;;\n' "$BIN_DIR"
    printf 'esac\n'
    printf 'export PATH\n'
    printf '%s\n' "$MARKER_END"
}

# Whether the last byte of the file is a newline.
ends_with_newline() {
    [ -s "$1" ] || return 1
    [ "$(tail -c 1 "$1" | wc -l | tr -d ' ')" = "1" ]
}

# Whether a start marker is left open, without an end marker after it. Such a
# block is not a block: where it ends is unknown, so it is never removed and the
# file is left exactly as it is. Status 0 means an open marker was found, 1 a
# well-formed or marker-free file, anything else that the file is unreadable.
has_unclosed_block() {
    awk -v start="$MARKER_START" -v end="$MARKER_END" '
        $0 == start { inside = 1; next }
        $0 == end { inside = 0 }
        END { exit (inside ? 0 : 1) }
    ' "$1"
}

# Drop the marked block, if there is one. Every other line is kept byte for
# byte, including whether the file ended with a newline: the rewrite carries
# the last line without a terminator when the input had none. A block this
# installer appended after a last line that had no final newline carries the
# separator comment, and both go away, so uninstall restores the original. An
# unterminated start marker is reported and the file is left untouched, because
# removing everything from that marker on would delete unrelated content.
remove_profile_block() {
    profile=$1
    if [ ! -f "$profile" ]; then
        return 0
    fi
    if ! grep -Fq "$MARKER_START" "$profile"; then
        return 0
    fi
    scan=0
    has_unclosed_block "$profile" || scan=$?
    case $scan in
        0)
            echo "install.sh: $profile has a '$MARKER_START' line with no matching '$MARKER_END' line; leaving the file unchanged. Repair that block and run install.sh again." >&2
            return 1
            ;;
        1) ;;
        *)
            echo "install.sh: cannot read $profile" >&2
            return 1
            ;;
    esac
    tmp=$profile.forgel-code.$$
    if ! cp -p "$profile" "$tmp"; then
        echo "install.sh: cannot write next to $profile" >&2
        return 1
    fi
    final_newline=0
    if ends_with_newline "$profile"; then
        final_newline=1
    fi
    if ! awk -v start="$MARKER_START" -v end="$MARKER_END" \
            -v separator="$MARKER_SEPARATOR" -v final_newline="$final_newline" '
            { text[NR] = $0 }
            END {
                total = NR
                kept = 0
                inside = 0
                block_end = 0
                for (i = 1; i <= total; i++) {
                    if (inside == 0 && text[i] == start) {
                        inside = 1
                        block_end = 0
                        continue
                    }
                    if (inside == 1) {
                        if (text[i] == end) {
                            inside = 0
                            block_end = i
                        }
                        continue
                    }
                    kept++
                    kept_text[kept] = text[i]
                    kept_index[kept] = i
                }
                restore_missing_newline = 0
                if (block_end == total && kept > 0 && kept_text[kept] == separator) {
                    kept--
                    restore_missing_newline = 1
                }
                for (i = 1; i <= kept; i++) {
                    terminate = 1
                    if (i == kept && restore_missing_newline == 1) {
                        terminate = 0
                    } else if (i == kept && kept_index[i] == total && final_newline == 0) {
                        terminate = 0
                    }
                    if (terminate) {
                        printf "%s\n", kept_text[i]
                    } else {
                        printf "%s", kept_text[i]
                    }
                }
            }
        ' "$profile" > "$tmp"; then
        rm -f "$tmp"
        echo "install.sh: cannot rewrite $profile" >&2
        return 1
    fi
    if ! mv "$tmp" "$profile"; then
        rm -f "$tmp"
        echo "install.sh: cannot replace $profile" >&2
        return 1
    fi
    return 0
}

# Exactly one block, whatever the profile already held. The previous block is
# removed first and only then is the new one appended, so an interrupted run
# leaves one block at most. The append is byte-stable: a second run over the
# same profile rewrites it to the same bytes, and a last line without a final
# newline is recorded so the block can be dropped without leaving a newline
# behind.
add_profile_block() {
    profile=$1
    case $profile in
        */*) mkdir -p "${profile%/*}" || return 1 ;;
    esac
    if ! remove_profile_block "$profile"; then
        return 1
    fi
    {
        if [ -s "$profile" ] && ! ends_with_newline "$profile"; then
            printf '\n'
            printf '%s\n' "$MARKER_SEPARATOR"
        fi
        print_block
    } >> "$profile" || return 1
    return 0
}

# The bound in seconds: FORGEL_CODE_TIMEOUT when it is a positive integer, the
# built-in default otherwise.
verify_limit() {
    configured=${FORGEL_CODE_TIMEOUT:-}
    case $configured in
        ''|*[!0-9]*)
            printf '%s\n' "$DEFAULT_VERIFY_LIMIT"
            return 0
            ;;
    esac
    if [ "$configured" -lt 1 ]; then
        printf '%s\n' "$DEFAULT_VERIFY_LIMIT"
        return 0
    fi
    printf '%s\n' "$configured"
}

# The grace period in seconds between the graceful stop and the forceful one:
# FORGEL_CODE_VERIFY_GRACE when it is a non-negative integer, the built-in
# default otherwise. Zero is allowed and stops forcefully at once.
verify_grace() {
    configured=${FORGEL_CODE_VERIFY_GRACE:-}
    case $configured in
        ''|*[!0-9]*)
            printf '%s\n' "$VERIFY_GRACE"
            return 0
            ;;
    esac
    printf '%s\n' "$configured"
}

# The watchdog's poll interval in milliseconds: FORGEL_CODE_POLL_MS when it is a
# positive integer, one second otherwise. The default is a whole second, so the
# default path asks nothing of ``sleep`` beyond POSIX.
verify_poll() {
    configured=${FORGEL_CODE_POLL_MS:-}
    case $configured in
        ''|*[!0-9]*)
            printf '%s\n' "$VERIFY_POLL_MS"
            return 0
            ;;
    esac
    if [ "$configured" -lt 1 ]; then
        printf '%s\n' "$VERIFY_POLL_MS"
        return 0
    fi
    printf '%s\n' "$configured"
}

# An unpredictable name component, so the check directory cannot be guessed
# and pre-created by another user.
random_token() {
    token=
    if [ -r /dev/urandom ] && command -v od >/dev/null 2>&1; then
        token=$(od -An -N 8 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n') || token=
    fi
    case $token in
        ''|*[!0-9a-f]*) token= ;;
    esac
    if [ -z "$token" ]; then
        token=$$$$$$
    fi
    printf '%s\n' "$token"
}

# A directory only the current user can enter or read, under the system
# temporary directory, with a name nobody can predict.
create_check_dir() {
    parent=${TMPDIR:-/tmp}
    if [ -z "$parent" ] || [ ! -d "$parent" ]; then
        parent=/tmp
    fi
    attempt=0
    while [ "$attempt" -lt 10 ]; do
        candidate=$parent/forgel-code-check.$(random_token)
        if (umask 077 && mkdir -m 700 "$candidate" 2>/dev/null); then
            CHECK_DIR=$candidate
            return 0
        fi
        attempt=$((attempt + 1))
    done
    echo "install.sh: cannot create a private directory under $parent" >&2
    return 1
}

# The members of a process group, one pid per line.
process_group() {
    ps -A -o pid= -o pgid= 2>/dev/null | awk -v group="$1" '$2 == group { print $1 }'
}

# Every descendant of a process, one pid per line.
process_tree() {
    ps -A -o pid= -o ppid= 2>/dev/null | awk -v root="$1" '
        { parent[$1] = $2; ids[NR] = $1 }
        END {
            frontier[0] = root
            count = 1
            for (i = 0; i < count; i++) {
                for (j = 1; j <= NR; j++) {
                    pid = ids[j]
                    if (parent[pid] == frontier[i] && !(pid in seen)) {
                        seen[pid] = 1
                        frontier[count] = pid
                        count++
                    }
                }
            }
            for (i = 1; i < count; i++) print frontier[i]
        }'
}

# Signal a process and every process it started. When the process leads its own
# process group the whole group is signalled, so a shell that forked cannot
# leave anything behind; otherwise the process tree is walked. The checked
# command is started in the installer's own process group on purpose, so this
# never signals the installer itself.
signal_run() {
    signal=$1
    root=$2
    if [ -z "$root" ]; then
        return 0
    fi
    targets=
    if command -v ps >/dev/null 2>&1; then
        group=$(ps -o pgid= -p "$root" 2>/dev/null | tr -d ' ') || group=
        own=$(ps -o pgid= -p "$$" 2>/dev/null | tr -d ' ') || own=
        case $group in
            ''|*[!0-9]*) group= ;;
        esac
        if [ -n "$group" ] && [ "$group" != "$own" ]; then
            targets=$(process_group "$group")
        fi
    fi
    if [ -z "$targets" ]; then
        targets=$(process_tree "$root")
    fi
    for pid in $targets; do
        kill -"$signal" "$pid" 2>/dev/null || true
    done
    kill -"$signal" "$root" 2>/dev/null || true
    return 0
}

# Release everything the bounded check owns: the watchdog, the checked process
# and its children, and the private directory. It is idempotent, so it can run
# from the exit trap and again from a signal trap.
cleanup_check() {
    if [ -n "$CHECK_WATCHER" ]; then
        kill -TERM "$CHECK_WATCHER" 2>/dev/null || true
        wait "$CHECK_WATCHER" 2>/dev/null || true
        CHECK_WATCHER=
    fi
    if [ -n "$CHECK_CHILD" ]; then
        signal_run KILL "$CHECK_CHILD"
        wait "$CHECK_CHILD" 2>/dev/null || true
        CHECK_CHILD=
    fi
    if [ -n "$CHECK_DIR" ]; then
        rm -rf "$CHECK_DIR" 2>/dev/null || true
        CHECK_DIR=
    fi
    return 0
}

check_interrupted() {
    cleanup_check
    exit "$1"
}

# Run a command under a hard time bound. ``timeout`` from GNU coreutils is not
# required and is not used: the command runs in the background, a watchdog
# sends a graceful stop when the bound elapses and forcefully stops whatever
# remains of the process tree after the grace period, and the caller returns
# as soon as the command itself is done. Nothing the function starts survives
# it. CHECK_STATUS is 124 when the bound elapsed.
#
# The checked command is deliberately *not* given its own process group here.
# ``set -m`` makes the shell put the background job in a background process
# group, and an interactive login shell in that position stops on its first
# terminal access instead of answering, which is exactly the hang this check
# must not have. The process tree walk in ``signal_run`` reaches everything the
# shell forked without it.
bounded_run() {
    limit=$1
    shift
    grace=$(verify_grace)
    poll=$(verify_poll)
    CHECK_STATUS=0
    CHECK_OUTPUT=
    if ! create_check_dir; then
        return 1
    fi
    out=$CHECK_DIR/output
    timed_out=$CHECK_DIR/timed-out
    saved_umask=$(umask)
    umask 077
    if ! : > "$out"; then
        umask "$saved_umask"
        cleanup_check
        return 1
    fi
    "$@" > "$out" 2>/dev/null < /dev/null &
    CHECK_CHILD=$!
    umask "$saved_umask"
    child=$CHECK_CHILD
    (
        exec > /dev/null 2>&1 < /dev/null
        sleeper=
        trap 'kill "$sleeper" 2>/dev/null || true; exit 0' TERM
        # A partial second poll only works where ``sleep`` understands one; fall
        # back to whole seconds so the bound never elapses early.
        if [ $((poll % 1000)) -ne 0 ] && ! sleep 0.001 2>/dev/null; then
            poll=1000
        fi
        limit_ms=$((limit * 1000))
        elapsed_ms=0
        while [ "$elapsed_ms" -lt "$limit_ms" ]; do
            pause=$poll
            remaining=$((limit_ms - elapsed_ms))
            if [ "$pause" -gt "$remaining" ]; then
                pause=$remaining
            fi
            delay=$((pause / 1000))
            if [ $((pause % 1000)) -ne 0 ]; then
                delay=$(printf '%d.%03d' "$delay" $((pause % 1000)))
            fi
            sleep "$delay" &
            sleeper=$!
            wait "$sleeper" 2>/dev/null || true
            sleeper=
            elapsed_ms=$((elapsed_ms + pause))
            if ! kill -0 "$child" 2>/dev/null; then
                exit 0
            fi
        done
        : > "$timed_out" 2>/dev/null || true
        signal_run TERM "$child"
        sleep "$grace" 2>/dev/null || true
        signal_run KILL "$child"
    ) &
    CHECK_WATCHER=$!
    wait "$child" || CHECK_STATUS=$?
    CHECK_CHILD=
    if [ -e "$timed_out" ]; then
        # The watchdog still owns the graceful then the forceful stop; let it
        # finish so nothing outlives the check.
        wait "$CHECK_WATCHER" 2>/dev/null || true
        CHECK_STATUS=124
    else
        kill -TERM "$CHECK_WATCHER" 2>/dev/null || true
        wait "$CHECK_WATCHER" 2>/dev/null || true
    fi
    CHECK_WATCHER=
    CHECK_OUTPUT=$(cat "$out") || CHECK_OUTPUT=
    cleanup_check
    return 0
}

report_path() {
    printf '%s\n' "$1" | sed -n 's/^forgel-fresh-path=//p' | tail -n 1
}

report_resolved() {
    printf '%s\n' "$1" | sed -n 's/^forgel-fresh-resolved=//p' | tail -n 1
}

# The defined failure report: the edited file, the exact block, the shell that
# was checked and the PATH that shell reported.
verification_failure() {
    shell=$1
    profile=$2
    fresh_path=$3
    resolved=$4
    status=$5
    limit=$6
    echo "install.sh: the fresh login shell did not put forgel-code on PATH" >&2
    case $status in
        0) ;;
        124) echo "install.sh: the check was stopped after ${limit}s; a timed-out or signalled check is a failure" >&2 ;;
        start) echo "install.sh: the fresh login shell could not be started" >&2 ;;
        *) echo "install.sh: the fresh login shell exited with status $status" >&2 ;;
    esac
    echo "install.sh: login shell: $shell" >&2
    echo "install.sh: profile file: $profile" >&2
    echo "install.sh: launcher: $LAUNCHER" >&2
    echo "install.sh: PATH block written:" >&2
    print_block >&2
    echo "install.sh: PATH in the fresh shell: ${fresh_path:-<empty>}" >&2
    echo "install.sh: forgel-code resolves to: ${resolved:-<not found>}" >&2
    echo "install.sh: check that $shell reads $profile when it starts a login session" >&2
    return 0
}

# Verify the block in a freshly started login interactive shell. The check
# passes only when that shell answered in time, exited cleanly and resolved
# ``forgel-code`` to the launcher just written, character for character.
verify_profile() {
    shell=$1
    profile=$2
    limit=$(verify_limit)
    report=
    resolved=
    fresh_path=
    status=start
    if [ -n "$shell" ] && [ -x "$shell" ]; then
        if bounded_run "$limit" env -i HOME="$HOME_DIR" SHELL="$shell" TERM=dumb PATH="$CHECK_PATH" "$shell" -l -i -c "$CHECK_COMMAND"; then
            status=$CHECK_STATUS
            report=$CHECK_OUTPUT
            fresh_path=$(report_path "$report")
            resolved=$(report_resolved "$report")
        fi
    fi
    if [ "$status" = "0" ] && [ -n "$resolved" ] && [ "$resolved" = "$LAUNCHER" ]; then
        VERIFIED_PATH=$resolved
        return 0
    fi
    verification_failure "$shell" "$profile" "$fresh_path" "$resolved" "$status" "$limit"
    return 1
}

write_launcher() {
    mkdir -p "$BIN_DIR"
    {
        printf '%s\n' '#!/bin/sh'
        printf '%s\n' '# Forgel Code launcher written by install.sh; do not edit.'
        printf 'PYTHONPATH="%s${PYTHONPATH:+:$PYTHONPATH}"\n' "$PREFIX"
        printf '%s\n' 'export PYTHONPATH'
        printf 'exec "%s" -m forgel_code "$@"\n' "$PYTHON"
    } > "$LAUNCHER"
    chmod 755 "$LAUNCHER"
}

add_path() {
    if no_profile_edit; then
        echo "Leaving the shell profile untouched."
        echo "Add this line to your shell profile:"
        printf 'export PATH="%s:$PATH"\n' "$BIN_DIR"
        return 0
    fi
    DETECTED_SHELL=$(detect_login_shell)
    profile=$(profile_path)
    if ! add_profile_block "$profile"; then
        return 1
    fi
    case $(shell_family "$DETECTED_SHELL") in
        posix)
            echo "install.sh: warning: $DETECTED_SHELL is neither zsh nor bash; the PATH block is in $profile" >&2
            ;;
    esac
    if ! verify_profile "$DETECTED_SHELL" "$profile"; then
        return 1
    fi
    echo "Login shell: $DETECTED_SHELL"
    echo "PATH block written to $profile"
    echo "Fresh login shell check: command -v forgel-code -> $VERIFIED_PATH"
    echo "Open a new terminal to pick the change up."
    return 0
}

install_client() {
    if ! PYTHON=$(detect_python); then
        echo "install.sh: no Python 3 interpreter found on PATH" >&2
        return 1
    fi
    if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
        echo "install.sh: $PYTHON is older than Python 3.9 or cannot run" >&2
        return 1
    fi
    # Looking pip up by name is answerable without importing it, which costs a
    # fraction of the import. Only an interpreter that cannot even name the
    # module pays for the import that tells us whether it works.
    if ! "$PYTHON" -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec("pip") is not None else 1)' >/dev/null 2>&1; then
        if ! "$PYTHON" -c 'import pip' >/dev/null 2>&1; then
            echo "install.sh: $PYTHON has no pip module; install pip and try again" >&2
            return 1
        fi
    fi
    if ! SOURCE=$(resolve_source); then
        return 1
    fi
    echo "Installing Forgel Code from $SOURCE"
    mkdir -p "$PREFIX"
    if ! "$PYTHON" -m pip install --target "$PREFIX" --upgrade --no-deps --no-index --no-cache-dir --no-build-isolation --no-compile --disable-pip-version-check --no-warn-script-location "$SOURCE"; then
        echo "install.sh: installing the client failed" >&2
        return 1
    fi
    if ! write_launcher; then
        echo "install.sh: cannot write $LAUNCHER" >&2
        return 1
    fi
    if ! installed=$("$LAUNCHER" --version); then
        echo "install.sh: the installed launcher does not run" >&2
        return 1
    fi
    printf '%s\n' "$installed"
    echo "Installed into $PREFIX"
    echo "Launcher: $LAUNCHER"
    add_path
}

# Clean the marked block out of one profile file, reporting it only when the
# file really carried one.
uninstall_profile() {
    profile=$1
    if [ ! -f "$profile" ] || ! grep -Fq "$MARKER_START" "$profile"; then
        return 0
    fi
    if remove_profile_block "$profile"; then
        echo "Removed the PATH block from $profile"
        return 0
    fi
    return 1
}

uninstall() {
    status=0
    if [ -d "$PREFIX" ]; then
        if rm -rf "$PREFIX"; then
            echo "Removed $PREFIX"
        else
            echo "install.sh: cannot remove $PREFIX" >&2
            status=1
        fi
    fi
    if [ -f "$LAUNCHER" ]; then
        if rm -f "$LAUNCHER"; then
            echo "Removed $LAUNCHER"
        else
            echo "install.sh: cannot remove $LAUNCHER" >&2
            status=1
        fi
    fi
    for name in $PROFILE_NAMES; do
        if ! uninstall_profile "$HOME_DIR/$name"; then
            status=1
        fi
    done
    # An install may have written the block into the profile named by
    # FORGEL_CODE_PROFILE instead of one of the standard names, and a run that
    # failed its fresh-shell check leaves the block behind. Clean that path too;
    # it is a no-op when it names a file the loop above already cleaned.
    if [ -n "${FORGEL_CODE_PROFILE:-}" ]; then
        if ! uninstall_profile "$FORGEL_CODE_PROFILE"; then
            status=1
        fi
    fi
    if [ "$status" = "0" ]; then
        echo "Forgel Code is uninstalled."
    fi
    return "$status"
}

main() {
    case ${1:-} in
        '')
            install_client
            ;;
        --uninstall)
            uninstall
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "install.sh: unknown argument: $1" >&2
            usage >&2
            return 2
            ;;
    esac
}

# Nothing this script started may outlive it, however it ends.
trap 'cleanup_check' EXIT
trap 'check_interrupted 129' HUP
trap 'check_interrupted 130' INT
trap 'check_interrupted 143' TERM

main "$@"
