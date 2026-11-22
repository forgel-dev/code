#!/bin/sh
# Forgel Code installer.
#
# One command installs the client into a per-user prefix:
#
#   curl -fsSL https://raw.githubusercontent.com/forgel-dev/code/v0.1.0/install.sh | sh
#
# The client goes into ${FORGEL_CODE_HOME:-$HOME/.local/share/forgel-code}, the
# ``forgel-code`` launcher into ${FORGEL_CODE_BIN:-$HOME/.local/bin}, and that
# directory is put on PATH through one marked block in the profile the login
# shell reads. The login shell is taken from $SHELL; when that is unset, empty or
# names a shell this installer does not handle, the account login shell decides.
# After writing the block the installer starts that shell as a login interactive
# shell from a cleared environment and checks that ``forgel-code`` resolves to
# the launcher it just wrote. Re-running replaces the installation; running with
# ``--uninstall`` removes it again.
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
#
# The script is POSIX ``sh`` and safe to pipe into: it never reads stdin.

set -eu

# The exact markers an uninstall looks for. They are compared byte for byte.
MARKER_START='# >>> forgel-code >>>'
MARKER_END='# <<< forgel-code <<<'

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

# The profile files this installer can have written. ``--uninstall`` cleans the
# block out of every one of them, so no stale PATH entry stays behind. The list
# is a superset of what the install path may edit, including ~/.bashrc, because
# a non-login bash session reads that file and an earlier installation could
# have left its block there.
PROFILE_NAMES='.zshrc .zprofile .zshenv .bash_profile .bash_login .profile .bashrc'

# Set by ``verify_profile`` once the fresh shell resolved the launcher.
VERIFIED_PATH=

usage() {
    cat <<'USAGE'
Usage: install.sh [--uninstall] [--help]

Installs the Forgel Code client into ${FORGEL_CODE_HOME:-$HOME/.local/share/forgel-code}
and its launcher into ${FORGEL_CODE_BIN:-$HOME/.local/bin}, adding that directory
to PATH with one marked block in the profile the login shell reads. The result
is checked in a freshly started login interactive shell.

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

# The shell that reads the edited profile for an interactive login session.
# $SHELL decides when it names a shell we handle; otherwise the account login
# shell decides, and a POSIX ``sh`` is the last resort, which reads $HOME/.profile.
detect_login_shell() {
    candidate=${SHELL:-}
    if [ -n "$candidate" ] && is_handled_shell "$candidate"; then
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

# Drop the marked block, if there is one. Every other line is kept as it was.
remove_profile_block() {
    profile=$1
    if [ ! -f "$profile" ]; then
        return 0
    fi
    if ! grep -Fq "$MARKER_START" "$profile"; then
        return 0
    fi
    tmp=$profile.forgel-code.$$
    if ! cp -p "$profile" "$tmp"; then
        echo "install.sh: cannot write next to $profile" >&2
        return 1
    fi
    if ! awk -v start="$MARKER_START" -v end="$MARKER_END" '
            $0 == start { inside = 1; next }
            inside == 1 && $0 == end { inside = 0; next }
            inside == 1 { next }
            { print }
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

# Exactly one block, whatever the profile already held.
add_profile_block() {
    profile=$1
    case $profile in
        */*) mkdir -p "${profile%/*}" ;;
    esac
    if ! remove_profile_block "$profile"; then
        return 1
    fi
    if [ -s "$profile" ]; then
        if [ "$(tail -c 1 "$profile" | wc -l | tr -d ' ')" = "0" ]; then
            printf '\n' >> "$profile"
        fi
    fi
    {
        printf '%s\n' "$MARKER_START"
        printf 'export PATH="%s:$PATH"\n' "$BIN_DIR"
        printf '%s\n' "$MARKER_END"
    } >> "$profile"
    return 0
}

# The detected shell as a login interactive shell started from a cleared
# environment: a new terminal, with nothing inherited from this one.
fresh_shell_report() {
    shell=$1
    env -i HOME="$HOME_DIR" SHELL="$shell" TERM=dumb PATH="$CHECK_PATH" "$shell" -l -i -c "$CHECK_COMMAND" </dev/null 2>/dev/null || true
    return 0
}

report_path() {
    printf '%s\n' "$1" | sed -n 's/^forgel-fresh-path=//p' | tail -n 1
}

report_resolved() {
    printf '%s\n' "$1" | sed -n 's/^forgel-fresh-resolved=//p' | tail -n 1
}

verification_failure() {
    shell=$1
    profile=$2
    fresh_path=$3
    resolved=$4
    echo "install.sh: the fresh login shell did not put forgel-code on PATH" >&2
    echo "install.sh: login shell: $shell" >&2
    echo "install.sh: profile file: $profile" >&2
    echo "install.sh: PATH block written:" >&2
    printf '%s\n' "$MARKER_START" >&2
    printf 'export PATH="%s:$PATH"\n' "$BIN_DIR" >&2
    printf '%s\n' "$MARKER_END" >&2
    echo "install.sh: PATH in the fresh shell: ${fresh_path:-<empty>}" >&2
    echo "install.sh: forgel-code resolves to: ${resolved:-<not found>}" >&2
    echo "install.sh: that shell does not read $profile when it starts a login session" >&2
    return 0
}

# Verify the block in a freshly started login interactive shell. The check
# passes only when that shell resolves forgel-code to the launcher just written.
verify_profile() {
    shell=$1
    profile=$2
    report=
    resolved=
    fresh_path=
    if [ -n "$shell" ] && [ -x "$shell" ]; then
        report=$(fresh_shell_report "$shell")
        fresh_path=$(report_path "$report")
        resolved=$(report_resolved "$report")
    fi
    if [ "$resolved" = "$LAUNCHER" ]; then
        VERIFIED_PATH=$resolved
        return 0
    fi
    verification_failure "$shell" "$profile" "$fresh_path" "$resolved"
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
    if ! "$PYTHON" -c 'import pip' >/dev/null 2>&1; then
        echo "install.sh: $PYTHON has no pip module; install pip and try again" >&2
        return 1
    fi
    if ! SOURCE=$(resolve_source); then
        return 1
    fi
    echo "Installing Forgel Code from $SOURCE"
    mkdir -p "$PREFIX"
    if ! "$PYTHON" -m pip install --target "$PREFIX" --upgrade --no-deps --no-index --no-cache-dir --no-build-isolation --disable-pip-version-check --no-warn-script-location "$SOURCE"; then
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

main "$@"
