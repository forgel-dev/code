# Release 0.2.0

- Tag: `v0.2.0`
- Date: 2026-11-24
- Project: `forgel-1d2bf685`
- Release train: `20261123193557155149_forgel-code-interactive-agent-client-instead-of-`
- Preset: python
- Version files: `forgel_code/__init__.py`
- GitHub release: https://github.com/forgel-dev/code/releases/tag/v0.2.0

## Tasks

- Forgel Code: interactive agent client instead of a command wrapper (`20261123193557_forgel-code-interactive-agent-client-ins`)
- Release audit: `forgel_code/interactive.py`'s `redact()` does not keep key material out of the (`20261123213155_release-audit-forgel-code-interactive-py`)
- Release audit: Localization does not satisfy the requirement that every reply follow the owner' (`20261123213155_release-audit-localization-does-not-sati`)
- Release audit: The session does not refresh task and release state on its own while the owner i (`20261123213155_release-audit-the-session-does-not-refre`)
- Release audit: Quoted secret labels are not fully redacted. For a message such as `'token': 'ab (`20261124003849_release-audit-quoted-secret-labels-are-n`)
- Release audit: Redaction misses values separated from a secret label by a newline and values be (`20261124003849_release-audit-redaction-misses-values-se`)
- Release audit: The session keeps unredacted engine text in memory. `show_state` assigns the raw (`20261124003849_release-audit-the-session-keeps-unredact`)
- Release audit: `redact()` in `forgel_code/interactive.py` treats the first word after a recogni (`20261124045451_release-audit-redact-in-forgel-code-inte`)
- Release audit: In `_quoted_binding`, after a quoted label and whitespace, a bare next token ret (`20261124053445_release-audit-in-quoted-binding-after-a-`)
- Release audit: `SENSITIVE_MARKERS` is English/Russian only. French/Spanish phrases such as `cré (`20261124053445_release-audit-sensitive-markers-is-engli`)
- Release audit: The redactor recognizes only English secret words and Russian stems (`SECRET_WOR (`20261124053445_release-audit-the-redactor-recognizes-on`)
- Release audit: The redactor recognizes the French password label only as the whitespace-separat (`20261124123936_release-audit-the-redactor-recognizes-th`)
- Release audit: `forgel_code/cli.py` changes the argparse description to include `Run it without (`20261124131129_release-audit-forgel-code-cli-py-changes`)
- Release audit: The sensitive-action guard is incomplete for required explicit actions. `SENSITI (`20261124131129_release-audit-the-sensitive-action-guard`)
