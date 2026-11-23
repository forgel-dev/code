# Release 0.1.1

- Tag: `v0.1.1`
- Date: 2026-11-23
- Project: `forgel-1d2bf685`
- Release train: `20261122025705947173_fix-install-sh-so-a-new-terminal-finds-forgel-co`
- Preset: python
- Version files: `forgel_code/__init__.py`
- GitHub release: https://github.com/forgel-dev/code/releases/tag/v0.1.1

## Tasks

- Fix install.sh so a new terminal finds forgel-code on PATH (`20261122025705_fix-install-sh-so-a-new-terminal-finds-f`)
- Release audit: --uninstall no longer honors FORGEL_CODE_PROFILE. The old code removed the block (`20261122034544_release-audit-uninstall-no-longer-honors`)
- Release audit: --uninstall omits ~/.bashrc, although the previous installer wrote the marked bl (`20261122034544_release-audit-uninstall-omits-bashrc-alt`)
- Make install.sh put forgel-code on PATH for a new terminal (`20261122062911_make-install-sh-put-forgel-code-on-path-`)
- Make the install.sh PATH check strictly bounded and keep the profile byte-identical on re-install (`20261122174453_make-the-install-sh-path-check-strictly-`)
- Release audit: `remove_profile_block` and `uninstall_profile` remove a block whenever `# >>> fo (`20261122192217_release-audit-remove-profile-block-and-u`)
- Release audit: The final task's recorded test run shows only `timed out after 120s` and partial (`20261122192217_release-audit-the-final-task-s-recorded-`)
- Release audit: `bounded_run` does not make the watchdog's timeout decision authoritative. After (`20261123062514_release-audit-bounded-run-does-not-make-`)
- Release audit: On a successful check, `bounded_run` clears `CHECK_CHILD` before `cleanup_check` (`20261123062514_release-audit-on-a-successful-check-boun`)
- Release audit: README.md still documents `.../v0.1.0/install.sh` for the install command and fo (`20261123062514_release-audit-readme-md-still-documents-`)
- Release audit: bounded_run clears CHECK_CHILD before calling cleanup_check, and install.sh deli (`20261123164954_release-audit-bounded-run-clears-check-c`)
- Release audit: install.sh's bounded_run still decides the timeout by testing for the timed-out (`20261123164954_release-audit-install-sh-s-bounded-run-s`)
- Release audit: The suite runtime regressed past the bound the release established. Task 2026112 (`20261123164954_release-audit-the-suite-runtime-regresse`)
