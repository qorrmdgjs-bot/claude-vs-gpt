---
name: review-loop
description: Run a bounded Codex implementation loop with separate Claude code review and audit sessions for trusted scratch tasks, or inspect its local reports. Use when the user requests this cross-model workflow.
---

# Review Loop

Use the installed `review-loop` CLI as the controller. If it is not on PATH, run `python <this-skill-folder>/scripts/launch.py <arguments>`; the launcher uses the interpreter recorded by the installer. Do not replace the loop with informal conversation or launch recursive skill sessions. The implementation worker is Codex; reviewers and auditors are independent Claude CLI calls with tools disabled.

1. Run `review-loop doctor`. If CLI is unavailable, ask for the project installation location and follow its INSTALL_AND_USAGE.ko.md. Do not invent a working installation.
2. Prepare a task JSON with goal, criteria linked to check IDs, one or two initial instructions, initial UTF-8 files, and approved check argument arrays. Use the project's examples/calculator.json format. Checks execute code: inspect them before starting. Keep inputs free of company data and credentials.
3. Fix the goal, criteria and file allowlist before launch. Runtime creates a new scratch workspace; it does not modify the original project. Check script files named in argv are protected from modification.
4. Run `review-loop run --task <task.json> --output <new-private-directory> --allow-live` only when user authorization covers sending task data to both providers and running its checks. Existing authorization can satisfy this; do not ask redundantly.
5. Read REPORT.md and state.json. Report actual status and remaining issues. Do not call a stopped run complete. Raw provider output is intentionally discarded. Runtime artifacts remain local and must not be published.

Use `review-loop status <directory>`, `review-loop cancel <directory>` and explicit `review-loop resume <directory> --allow-live` as needed. Resume preserves the original four-hour deadline and revalidates before edits. Unclean exit markers require process ownership inspection; do not delete them blindly.

The controller enforces at most two next instructions, a one-hour implementation limit, three consecutive no-progress rounds, a four-hour total deadline and thirty AI calls. File changes invalidate earlier evidence. Do not weaken goals, checks or limits to make a run pass.

This is an experimental trusted-task tool, not an OS isolation or secret-detection guarantee. Before company use, stop and obtain an approved isolation/data policy. Windows code must be tested on the user's Windows machine. Never infer Windows verification from Mac tests. GitHub push, PR creation, merge and deployment require separate authorization.
