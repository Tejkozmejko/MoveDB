#!/usr/bin/env python3
"""Centric Claude bridge - runs on a developer machine, not on the Odoo server.

Odoo.sh cannot run the Claude Code CLI, so this process does it instead. It polls
Odoo over HTTPS for queued turns, runs each one with `claude -p` against your local
checkout, and posts the reply plus any changed files back for review in Odoo.

Because it calls out to Odoo, it needs no inbound port, no CORS and no browser
permission for local network access.

Setup
-----
1. In Odoo: Settings > Centric Claude > set Claude Backend to "Local Claude Code
   agent", pick "Agent Runs As", and click "Generate Agent Token".
2. Have Claude Code installed and logged in. The bridge finds it automatically:
   first on PATH, then inside the VS Code / Cursor extension folder, which is
   where the marketplace install keeps it. Override with --claude-bin if needed.
   The bridge does NOT pass --bare, so Claude Code uses your subscription login;
   no Anthropic API key is involved.
3. Run it from anywhere:

     export CENTRIC_CLAUDE_URL=https://your-odoo.odoo.com
     export CENTRIC_CLAUDE_TOKEN=<the generated token>
     export CENTRIC_CLAUDE_REPO=/path/to/your/local/clone
     python claude_bridge.py

Safety
------
* Only files under an approved module directory are sent back to Odoo.
* Nothing is committed or pushed. Odoo stages the changes; a human clicks Commit.
* The bridge refuses to run if the repository has uncommitted changes, so it can
  tell which edits belong to Claude.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_POLL_SECONDS = 3
DEFAULT_TIMEOUT_SECONDS = 900
MAX_FILE_BYTES = 512000

SYSTEM_PROMPT = """\
You are the Claude developer assistant for Centric, invoked from an Odoo workspace.

You are working in a local checkout of the team's Odoo addons repository.
Only modify modules whose directory name starts with: {prefix}
Never touch Odoo core, third-party modules, CI configuration, or secrets.

Your edits are NOT committed. They are sent back to Odoo, staged as a reviewable
diff, and a human decides whether to commit them to a review branch. Do not run
git commit, git push, or gh. Make the edits and explain what you changed.

Current base branch: {branch}
Developer Mode: {mode}
{permission}
"""


class BridgeError(RuntimeError):
    pass


# --------------------------------------------------------- finding claude ---
VSCODE_EXTENSION_DIRS = (".vscode", ".vscode-insiders", ".vscode-server", ".cursor")


def _version_key(name):
    """Sort extension folder names like anthropic.claude-code-2.1.237-win32-x64."""
    return tuple(int(part) for part in re.findall(r"\d+", name)) or (0,)


def find_claude(preferred="claude"):
    """Locate the Claude Code CLI.

    Prefers whatever is on PATH. Falls back to the copy bundled inside the VS Code
    extension, which is where it lives when Claude Code was installed from the
    marketplace and never added to PATH. The newest installed version wins, so
    this keeps working when the extension updates.
    """
    on_path = shutil.which(preferred)
    if on_path:
        return on_path
    if preferred != "claude":
        if os.path.isfile(preferred):
            return preferred
        raise BridgeError("No Claude Code executable at %r." % preferred)

    home = os.path.expanduser("~")
    candidates = []
    for editor_dir in VSCODE_EXTENSION_DIRS:
        root = os.path.join(home, editor_dir, "extensions")
        if not os.path.isdir(root):
            continue
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        for entry in entries:
            if not entry.startswith("anthropic.claude-code-"):
                continue
            for exe in ("claude.exe", "claude"):
                path = os.path.join(root, entry, "resources", "native-binary", exe)
                if os.path.isfile(path):
                    candidates.append((_version_key(entry), path))
    if candidates:
        return max(candidates)[1]

    raise BridgeError(
        "Could not find the Claude Code CLI.\n"
        "  Looked on PATH and inside the VS Code / Cursor extension folders.\n"
        "  Fix it either way:\n"
        "    - install the CLI so `claude` is on PATH, or\n"
        "    - pass --claude-bin with the full path to claude.exe"
    )


# ---------------------------------------------------------------- odoo io ---
def call_odoo(base_url, token, path, payload):
    """Odoo `type="json"` routes speak JSON-RPC 2.0, not plain JSON."""
    body = json.dumps({
        "jsonrpc": "2.0",
        "method": "call",
        "params": payload,
        "id": 1,
    }).encode()
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            envelope = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise BridgeError("Odoo returned HTTP %s for %s" % (exc.code, path)) from exc
    except urllib.error.URLError as exc:
        raise BridgeError("Cannot reach Odoo at %s: %s" % (base_url, exc.reason)) from exc

    if "error" in envelope:
        message = envelope["error"].get("data", {}).get("message") or envelope["error"]
        raise BridgeError("Odoo error on %s: %s" % (path, message))
    result = envelope.get("result") or {}
    if isinstance(result, dict) and result.get("error"):
        raise BridgeError(result["error"])
    return result


# ------------------------------------------------------------------- git ---
def git(repo, *args):
    done = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if done.returncode != 0:
        raise BridgeError("git %s failed: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout


def require_clean_tree(repo):
    if git(repo, "status", "--porcelain").strip():
        raise BridgeError(
            "The repository has uncommitted changes. Commit or stash them first so "
            "the bridge can tell which edits came from Claude."
        )


def changed_files(repo):
    """Every file Claude added or modified, as repo-relative paths."""
    tracked = git(repo, "diff", "--name-only").splitlines()
    untracked = git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    seen, paths = set(), []
    for path in tracked + untracked:
        path = path.strip()
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def find_module(repo, path):
    """Resolve a repo-relative file to (module_name, path_within_module).

    Walks up from the file to the nearest directory holding __manifest__.py,
    exactly as Odoo discovers modules. Assuming the module is the first path
    segment breaks on nested layouts such as
    `centric_claude_integration/centric_claude_integration/models/x.py`,
    where the real module directory sits one level down.
    """
    parts = path.split("/")
    for depth in range(len(parts) - 1, 0, -1):
        directory = os.path.join(repo, *parts[:depth])
        if os.path.isfile(os.path.join(directory, "__manifest__.py")):
            return parts[depth - 1], "/".join(parts[depth:])
    return None, None


def collect_changes(repo, prefix):
    """Turn the working-tree diff into the payload Odoo stages.

    Files outside an approved module are reported but never sent.
    """
    staged, skipped = [], []
    for path in changed_files(repo):
        module, relative = find_module(repo, path)
        if not module:
            skipped.append((path, "not inside an Odoo module (no __manifest__.py above it)"))
            continue
        if not module.startswith(prefix):
            skipped.append((path, "outside an approved %s* module" % prefix))
            continue
        absolute = os.path.join(repo, path)
        try:
            size = os.path.getsize(absolute)
        except OSError:
            skipped.append((path, "deleted files are not staged"))
            continue
        if size > MAX_FILE_BYTES:
            skipped.append((path, "larger than 500 KB"))
            continue
        try:
            with open(absolute, encoding="utf-8") as handle:
                content = handle.read()
        except (OSError, UnicodeDecodeError):
            skipped.append((path, "not readable as UTF-8 text"))
            continue
        staged.append({
            "module": module,
            "path": relative,
            "new_content": content,
            "summary": "Edited by Claude Code via the Odoo workspace",
        })
    return staged, skipped


def revert(repo):
    """Return the checkout to a clean state after handing the edits to Odoo."""
    git(repo, "checkout", "--", ".")
    git(repo, "clean", "-fd")


# ----------------------------------------------------------------- claude ---
def build_prompt(turn):
    lines = []
    history = turn.get("history") or []
    if len(history) > 1:
        lines.append("Earlier in this conversation:")
        for message in history[:-1][-10:]:
            who = "Developer" if message["role"] == "user" else "You"
            lines.append("%s: %s" % (who, message["content"][:2000]))
        lines.append("")
    lines.append(turn["prompt"])
    return "\n".join(lines)


def run_claude(repo, turn, timeout, claude_bin, extra_args):
    developer_mode = bool(turn.get("developer_mode"))
    system = SYSTEM_PROMPT.format(
        prefix=turn.get("allowed_module_prefix") or "centric_",
        branch=turn.get("base_branch") or "unknown",
        mode="ON" if developer_mode else "OFF",
        permission=(
            "You may edit files in approved modules."
            if developer_mode
            else "Developer Mode is OFF: answer and investigate only, do not edit any file."
        ),
    )
    command = [
        claude_bin, "-p", build_prompt(turn),
        "--output-format", "json",
        "--append-system-prompt", system,
    ]
    # Without Developer Mode, deny the editing tools outright rather than relying
    # on the prompt alone.
    command += ["--allowedTools", "Read,Grep,Glob,Edit,Write,Bash" if developer_mode
                else "Read,Grep,Glob"]
    command += extra_args

    try:
        done = subprocess.run(
            command, cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except OSError as exc:
        raise BridgeError("Could not run %r: %s" % (claude_bin, exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise BridgeError("Claude did not finish within %s seconds." % timeout) from exc

    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip()[:2000]
        raise BridgeError("claude exited %s: %s" % (done.returncode, detail))
    try:
        payload = json.loads(done.stdout)
    except ValueError as exc:
        raise BridgeError("Could not parse the Claude Code JSON output.") from exc
    return (payload.get("result") or "").strip()


# ------------------------------------------------------------------- loop ---
def handle_turn(config, turn):
    repo, prefix = config.repo, (turn.get("allowed_module_prefix") or "centric_")
    print("  turn %s: %s" % (turn["turn_id"], turn["prompt"][:70].replace("\n", " ")))
    require_clean_tree(repo)
    text = run_claude(repo, turn, config.timeout, config.claude_bin, config.claude_args)

    changes, skipped = [], []
    if turn.get("developer_mode"):
        changes, skipped = collect_changes(repo, prefix)
        if changes or skipped:
            revert(repo)
    for path, reason in skipped:
        print("    skipped %s (%s)" % (path, reason))
        text += "\n\nNot sent to Odoo - %s: %s" % (path, reason)

    result = call_odoo(config.url, config.token, "/centric_claude/agent/complete", {
        "turn_id": turn["turn_id"],
        "assistant_text": text,
        "changes": changes,
    })
    print("    done, staged %s file(s)" % len(result.get("staged") or []))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default=os.environ.get("CENTRIC_CLAUDE_URL"),
                        help="Odoo base URL, e.g. https://centric.odoo.com")
    parser.add_argument("--token", default=os.environ.get("CENTRIC_CLAUDE_TOKEN"),
                        help="Agent token generated in Odoo settings")
    parser.add_argument("--repo", default=os.environ.get("CENTRIC_CLAUDE_REPO", "."),
                        help="Path to your local clone of the addons repository")
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL_SECONDS,
                        help="Seconds between polls when the queue is empty")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS,
                        help="Seconds to allow a single Claude run")
    parser.add_argument("--claude-bin", default=os.environ.get("CLAUDE_BIN", "claude"),
                        help="Path to the Claude Code CLI. Found automatically if "
                             "it is on PATH or installed as a VS Code extension.")
    parser.add_argument("--name", default=os.environ.get("COMPUTERNAME")
                        or os.environ.get("HOSTNAME") or "bridge")
    parser.add_argument("--once", action="store_true",
                        help="Handle at most one turn, then exit")
    parser.add_argument("claude_args", nargs="*",
                        help="Extra flags passed through to claude, after --")
    config = parser.parse_args(argv)

    if not config.url or not config.token:
        parser.error("Set --url/--token or CENTRIC_CLAUDE_URL/CENTRIC_CLAUDE_TOKEN.")
    config.repo = os.path.abspath(config.repo)
    if not os.path.isdir(os.path.join(config.repo, ".git")):
        parser.error("%s is not a git checkout." % config.repo)

    try:
        config.claude_bin = find_claude(config.claude_bin)
    except BridgeError as exc:
        parser.error(str(exc))
    print("Using Claude Code at %s" % config.claude_bin)

    hello = call_odoo(config.url, config.token, "/centric_claude/agent/ping",
                      {"agent_name": config.name})
    print("Connected to %s as %s (repo %s on %s, %s pending)"
          % (config.url, hello.get("user"), hello.get("repository"),
             hello.get("branch", "?"), hello.get("pending")))
    for warning in hello.get("warnings") or []:
        print("  WARNING: %s" % warning)
    print("Watching %s. Ctrl-C to stop." % config.repo)

    while True:
        try:
            claimed = call_odoo(config.url, config.token,
                                "/centric_claude/agent/claim",
                                {"agent_name": config.name})
        except BridgeError as exc:
            print("  %s" % exc, file=sys.stderr)
            time.sleep(max(config.poll, 5))
            continue

        turn = claimed.get("turn")
        if not turn:
            if config.once:
                print("Queue empty.")
                return 0
            time.sleep(config.poll)
            continue

        try:
            handle_turn(config, turn)
        except BridgeError as exc:
            print("    failed: %s" % exc, file=sys.stderr)
            try:
                call_odoo(config.url, config.token, "/centric_claude/agent/fail",
                          {"turn_id": turn["turn_id"], "error": str(exc)})
            except BridgeError as report_failure:
                print("    could not report the failure: %s" % report_failure,
                      file=sys.stderr)
        if config.once:
            return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
