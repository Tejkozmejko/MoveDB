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
3. Save your settings once, so no credential ever sits on a command line:

     python claude_bridge.py --url URL --token TOKEN --repo PATH --save

   After that, `python claude_bridge.py` is enough.

4. To have it always there, start it at login and forget about it:

     python claude_bridge.py --install

   That registers a login task running without a console window, logging to
   ~/.centric_claude/bridge.log. Undo with --uninstall.

   Nothing can start the bridge *on demand*: Odoo calls nothing on your
   machine, which is the whole reason this design needs no inbound port. What
   --install buys is that it is already running by the time you ask.

Safety
------
* Only files under an approved module directory are sent back to Odoo.
* Nothing is committed or pushed. Odoo stages the changes; a human clicks Commit.
* The bridge refuses to run if the repository has uncommitted changes, so it can
  tell which edits belong to Claude.
* Only one bridge runs at a time. Two would both claim turns, and a question
  would be answered twice - possibly from different checkouts.
"""
import argparse
import atexit
import json
import os
import re
import shutil
import subprocess
import tempfile
import sys
import time
import urllib.error
import urllib.request

DEFAULT_POLL_SECONDS = 3
DEFAULT_TIMEOUT_SECONDS = 900
MAX_FILE_BYTES = 512000

# Where an unattended bridge keeps its settings, lock and log. Credentials live
# in a file rather than on the command line: a scheduled task shows its
# arguments in the task list, and any local process can read another's argv.
HOME_DIR = os.path.join(os.path.expanduser("~"), ".centric_claude")
CONFIG_PATH = os.path.join(HOME_DIR, "bridge.json")
LOCK_PATH = os.path.join(HOME_DIR, "bridge.lock")
LOG_PATH = os.path.join(HOME_DIR, "bridge.log")
TASK_NAME = "Centric Claude Bridge"
# The lock is taken on a byte past the PID text, so the PID stays readable.
LOCK_BYTE_OFFSET = 1024

# An idle bridge should be quiet. Polling stretches out while nothing is queued
# and snaps back the moment work appears, so an always-on process is not
# hammering Odoo every few seconds all day.
IDLE_BACKOFF_AFTER = 60          # seconds of empty queue before slowing down
IDLE_POLL_SECONDS = 15

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
{data}
"""


DATA_PROMPT_NONE = """\
Odoo database: no access. You cannot look up tickets, invoices or any other
records. If asked, say the administrator has not given this account a Claude
data level."""

DATA_PROMPT_READ = """\
Odoo database: read only, through the odoo_* tools.
- Call odoo_find_models first when unsure of a model's technical name, and
  odoo_describe_model before filtering on a field you have not seen.
- Queries run with the permissions of the person asking. An empty result may
  mean they cannot see those records, not that none exist. Say which.
- Quote what the database returns. Never invent or estimate a record.
- You cannot change anything: that needs the Intermediate level."""

DATA_PROMPT_WRITE = """\
Odoo database: read, and propose changes, through the odoo_* tools.
- Call odoo_find_models first when unsure of a model's technical name, and
  odoo_describe_model before filtering on or setting a field you have not seen.
- Queries run with the permissions of the person asking. An empty result may
  mean they cannot see those records, not that none exist. Say which.
- odoo_propose_change and odoo_propose_action DO NOT change anything. They put a
  confirmation in the Odoo chat for the user to accept. After calling one, say
  what you proposed and that it is waiting for their Yes. Never state that a
  record was created, updated or deleted."""


def data_prompt(turn):
    if not turn.get("can_read_data"):
        return DATA_PROMPT_NONE
    return DATA_PROMPT_WRITE if turn.get("can_propose_data") else DATA_PROMPT_READ


# Claude Code takes the same five levels as the Messages API, so the choice made
# in Odoo means the same thing whichever backend answers.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def effort_for(turn):
    """The effort level for this turn, ignoring anything unrecognised."""
    level = (turn.get("effort") or "").strip().lower()
    return level if level in EFFORT_LEVELS else ""


ODOO_READ_TOOLS = (
    "mcp__odoo__odoo_find_models",
    "mcp__odoo__odoo_describe_model",
    "mcp__odoo__odoo_search",
    "mcp__odoo__odoo_read",
    "mcp__odoo__odoo_count",
)
ODOO_WRITE_TOOLS = (
    "mcp__odoo__odoo_propose_change",
    "mcp__odoo__odoo_propose_action",
)


def mcp_config_for(turn, config, directory):
    """Write the MCP server config for one turn, or None if data access is off.

    Returns (config_path, allowed_tool_names, environment_overrides). The token
    is passed through the environment rather than argv, because on most systems
    any local process can read another's command line.
    """
    if not turn.get("can_read_data"):
        return None, (), {}
    server = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "claude_odoo_mcp.py")
    if not os.path.isfile(server):
        print("    WARNING: %s is missing; Odoo data tools are unavailable."
              % server, file=sys.stderr)
        return None, (), {}
    environment = {
        "CENTRIC_CLAUDE_URL": config.url,
        "CENTRIC_CLAUDE_TOKEN": config.token,
        "CENTRIC_CLAUDE_TURN": str(turn["turn_id"]),
        "CENTRIC_CLAUDE_LEVEL": turn.get("data_level") or "none",
    }
    payload = {
        "mcpServers": {
            "odoo": {
                "command": sys.executable,
                "args": [server],
                "env": environment,
            }
        }
    }
    path = os.path.join(directory, "odoo-mcp.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    tools = list(ODOO_READ_TOOLS)
    if turn.get("can_propose_data"):
        tools += list(ODOO_WRITE_TOOLS)
    return path, tuple(tools), environment


class BridgeError(RuntimeError):
    pass


# ------------------------------------------------------ stored settings ---
def read_settings(path=None):
    """Load saved settings, or {} when there are none."""
    path = path or CONFIG_PATH
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise BridgeError("Could not read %s: %s" % (path, exc)) from exc


def write_settings(values, path=None):
    """Save settings with the tightest permissions the platform offers."""
    path = path or CONFIG_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(values, handle, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    user = os.environ.get("USERNAME")
    if os.name == "nt" and user:
        # chmod is close to meaningless on Windows, so drop inherited access and
        # grant this account alone. Best effort: a failure here must not stop the
        # bridge, but it is worth attempting for a file holding a token.
        subprocess.run(
            ["icacls", path, "/inheritance:r", "/grant:r", "%s:F" % user],
            capture_output=True, text=True,
        )
    return path


# --------------------------------------------------------- single instance ---
def acquire_lock(path=None):
    """Refuse to start when another bridge is already running.

    Two bridges both claim turns, so a question would be answered twice - or
    worse, answered by whichever checkout happened to be stale. The lock is held
    by the OS and released when the process dies, so a crash leaves nothing to
    clean up by hand.
    """
    path = path or LOCK_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            # Lock a byte past anything we write. Windows locks deny reads too,
            # so locking byte 0 would stop anyone opening the file to see which
            # process is holding it - exactly when they most want to know.
            handle.seek(LOCK_BYTE_OFFSET)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise BridgeError(
            "Another bridge is already running (lock: %s). Stop that one first; "
            "it may have been started at login rather than by you." % path
        )
    handle.seek(0)
    handle.write("%-16s" % os.getpid())
    handle.flush()
    atexit.register(handle.close)
    return handle


# ------------------------------------------------------------- autostart ---
def autostart_command(config, pythonw=None):
    """The command a scheduled task should run."""
    if pythonw is None:
        # pythonw runs without a console window; fall back to python if absent.
        candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        pythonw = candidate if os.path.isfile(candidate) else sys.executable
    return [pythonw, os.path.abspath(__file__), "--config", config, "--quiet"]


def install_autostart(config_path=None, task_name=TASK_NAME, run=True):
    """Register the bridge to start at login. Returns the command used."""
    config_path = config_path or CONFIG_PATH
    command = autostart_command(config_path)
    quoted = " ".join('"%s"' % part if " " in part else part for part in command)
    if os.name != "nt":
        raise BridgeError(
            "Automatic startup is only wired up for Windows. On macOS or Linux, "
            "run this command from your login items or a systemd user unit:" +
            chr(10) + chr(10) + "    " + quoted
        )
    argv = ["schtasks", "/Create", "/SC", "ONLOGON", "/TN", task_name,
            "/TR", quoted, "/F"]
    if not run:
        return argv, quoted
    done = subprocess.run(argv, capture_output=True, text=True)
    if done.returncode != 0:
        raise BridgeError(
            "Could not register the startup task: %s"
            % (done.stderr or done.stdout or "").strip()
        )
    return argv, quoted


def uninstall_autostart(task_name=TASK_NAME, run=True):
    argv = ["schtasks", "/Delete", "/TN", task_name, "/F"]
    if os.name != "nt":
        raise BridgeError("Automatic startup is only wired up for Windows.")
    if not run:
        return argv
    done = subprocess.run(argv, capture_output=True, text=True)
    if done.returncode != 0:
        raise BridgeError(
            "Could not remove the startup task: %s"
            % (done.stderr or done.stdout or "").strip()
        )
    return argv


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
    """Odoo `type="jsonrpc"` routes speak JSON-RPC 2.0, not plain JSON."""
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


def run_claude(repo, turn, timeout, claude_bin, extra_args, config=None):
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
        data=data_prompt(turn),
    )
    command = [
        claude_bin, "-p", build_prompt(turn),
        "--output-format", "json",
        "--append-system-prompt", system,
    ]
    level = effort_for(turn)
    if level:
        command += ["--effort", level]
    # Without Developer Mode, deny the editing tools outright rather than relying
    # on the prompt alone.
    allowed = ["Read", "Grep", "Glob"]
    if developer_mode:
        allowed += ["Edit", "Write", "Bash"]

    environment = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="centric-claude-") as workdir:
        mcp_path, odoo_tools, mcp_env = (None, (), {})
        if config is not None:
            mcp_path, odoo_tools, mcp_env = mcp_config_for(turn, config, workdir)
        if mcp_path:
            command += ["--mcp-config", mcp_path]
            allowed += list(odoo_tools)
            # Claude Code launches the server itself, so it must inherit these.
            environment.update(mcp_env)
        command += ["--allowedTools", ",".join(allowed)]
        command += extra_args
        return _invoke_claude(command, repo, timeout, claude_bin, environment)


def _invoke_claude(command, repo, timeout, claude_bin, environment):
    try:
        done = subprocess.run(
            command, cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            env=environment,
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


def _start_logging(path):
    """Send stdout and stderr to a log file as well, for unattended runs."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    stream = open(path, "a", encoding="utf-8", buffering=1)

    class _Tee:
        def __init__(self, *targets):
            self.targets = [t for t in targets if t is not None]

        def write(self, text):
            for target in self.targets:
                try:
                    target.write(text)
                except (ValueError, OSError):
                    pass
            return len(text)

        def flush(self):
            for target in self.targets:
                try:
                    target.flush()
                except (ValueError, OSError):
                    pass

    # Under pythonw there is no console at all, so sys.stdout may be None.
    sys.stdout = _Tee(sys.stdout, stream)
    sys.stderr = _Tee(sys.stderr, stream)
    print(chr(10) + "=== bridge started %s ==="
          % time.strftime("%Y-%m-%d %H:%M:%S"))


# ------------------------------------------------------------------- loop ---
def handle_turn(config, turn):
    repo, prefix = config.repo, (turn.get("allowed_module_prefix") or "centric_")
    print("  turn %s [%s]: %s" % (
        turn["turn_id"], effort_for(turn) or "default",
        turn["prompt"][:70].replace(chr(10), " "),
    ))
    require_clean_tree(repo)
    text = run_claude(repo, turn, config.timeout, config.claude_bin,
                      config.claude_args, config=config)

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
    parser.add_argument("--serve", default=None,
                        help="Comma-separated Odoo logins this bridge answers "
                             "for. Leave unset to answer everyone. Set it when "
                             "more than one person runs a bridge, or they will "
                             "take each other's questions and answer them from "
                             "the wrong checkout.")
    parser.add_argument("--config", default=CONFIG_PATH,
                        help="Settings file holding url/token/repo "
                             "(default: %s)" % CONFIG_PATH)
    parser.add_argument("--save", action="store_true",
                        help="Write the given --url/--token/--repo to the "
                             "settings file and exit")
    parser.add_argument("--install", action="store_true",
                        help="Start the bridge automatically at login, then exit")
    parser.add_argument("--uninstall", action="store_true",
                        help="Stop starting the bridge at login, then exit")
    parser.add_argument("--log-file", default=None,
                        help="Append output here as well as to the console")
    parser.add_argument("--quiet", action="store_true",
                        help="Log to the default log file instead of the console. "
                             "Used by the login task, which has no console.")
    parser.add_argument("claude_args", nargs="*",
                        help="Extra flags passed through to claude, after --")
    config = parser.parse_args(argv)

    # Stored settings fill in whatever was not given, so an unattended run needs
    # no arguments and no credentials on the command line.
    try:
        stored = read_settings(config.config)
    except BridgeError as exc:
        parser.error(str(exc))
    for key in ("url", "token", "repo", "name", "serve"):
        if not getattr(config, key, None) and stored.get(key):
            setattr(config, key, stored[key])

    if config.uninstall:
        try:
            uninstall_autostart()
        except BridgeError as exc:
            parser.error(str(exc))
        print("The bridge will no longer start at login.")
        return 0

    if not config.url or not config.token:
        parser.error(
            "No Odoo URL or agent token. Give them as --url/--token, or as "
            "CENTRIC_CLAUDE_URL/CENTRIC_CLAUDE_TOKEN, or save them once so you "
            "never have to pass them again:" + chr(10) + chr(10) +
            "    python claude_bridge.py --url <url> --token <token> "
            "--repo <path> --save"
        )

    if config.save:
        path = write_settings({
            "url": config.url, "token": config.token,
            "repo": os.path.abspath(config.repo), "name": config.name,
            "serve": config.serve,
        }, config.config)
        print("Saved to %s" % path)
        print("From now on you can just run:  python claude_bridge.py")
        return 0

    if config.install:
        try:
            write_settings({
                "url": config.url, "token": config.token,
                "repo": os.path.abspath(config.repo), "name": config.name,
                "serve": config.serve,
            }, config.config)
            _argv, quoted = install_autostart(config.config)
        except BridgeError as exc:
            parser.error(str(exc))
        print("The bridge will now start automatically when you log in.")
        print("  command: %s" % quoted)
        print("  log:     %s" % LOG_PATH)
        print("  undo:    python claude_bridge.py --uninstall")
        print(chr(10) + "Starting it now so you do not have to log out...")
        config.install = False

    log_path = config.log_file or (LOG_PATH if config.quiet else None)
    if log_path:
        _start_logging(log_path)
    config.repo = os.path.abspath(config.repo)
    if not os.path.isdir(os.path.join(config.repo, ".git")):
        parser.error("%s is not a git checkout." % config.repo)

    # One bridge at a time: a second would claim turns the first should answer.
    if not config.once:
        try:
            acquire_lock()
        except BridgeError as exc:
            parser.error(str(exc))

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
    if config.serve:
        print("Answering only for: %s" % config.serve)
    else:
        print("Answering for everyone. If a colleague also runs a bridge, give "
              "each one --serve <their-login> so they do not take each other's "
              "questions.")
    print("Watching %s. Ctrl-C to stop." % config.repo)

    idle_since = time.monotonic()
    while True:
        try:
            claimed = call_odoo(config.url, config.token,
                                "/centric_claude/agent/claim",
                                {"agent_name": config.name,
                                 "serve": config.serve or ""})
        except BridgeError as exc:
            print("  %s" % exc, file=sys.stderr)
            time.sleep(max(config.poll, 5))
            continue

        turn = claimed.get("turn")
        if not turn:
            if config.once:
                print("Queue empty.")
                return 0
            # Ease off while nothing is queued, so a bridge left running all day
            # is not asking every few seconds for hours.
            idle_for = time.monotonic() - idle_since
            time.sleep(config.poll if idle_for < IDLE_BACKOFF_AFTER
                       else max(config.poll, IDLE_POLL_SECONDS))
            continue
        idle_since = time.monotonic()

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
