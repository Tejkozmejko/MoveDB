# Centric Claude Integration for Odoo 19

This addon puts a controlled Claude developer workspace inside Odoo.

## What it does

- Chat with Claude from Odoo, or from the Claude mark in the Odoo navbar.
- Group chats into projects, each with its own standing instructions, added
  to the system prompt of every chat filed under that project.
- Rename and delete chats.
- Discover approved custom modules in one GitHub repository.
- Browse source files without opening VS Code.
- Let Claude read code through Anthropic client tools.
- Let authorised developers enable Developer Mode per conversation.
- Stage complete-file code changes in Odoo for review, including new files.
- Show unified diffs before committing.
- Commit staged changes to a new `claude/...` GitHub review branch.
- Create a pull request from Odoo.
- Keep repository and code-change audit logs.

## Safety model

Code writing requires all of the following:

1. Global `Allow Code Modifications` is enabled in Odoo Settings.
2. The current user belongs to `Centric Claude / Developer` or `Administrator`.
3. Developer Mode is enabled on that specific conversation.

Claude itself cannot commit, merge, deploy, or modify the running Odoo filesystem.
Only a user action can commit staged changes to GitHub.

Only modules whose technical name starts with the configured prefix, default `centric_`, are exposed to the repository tools.

## How Claude is reached

There are two backends, chosen in Settings.

### Local Claude Code agent (default, no API key)

Odoo.sh cannot run the Claude Code CLI, so a small bridge runs on a developer
machine instead. It polls Odoo over HTTPS for queued turns, runs each one with
`claude -p` against the local checkout, and posts the reply plus any changed files
back to Odoo for review.

    Browser (Odoo workspace) --> queues a turn
                                      |
                                    Odoo.sh   (queue, staging, audit, GitHub)
                                      ^ |
      laptop bridge ---- poll --------' |  claims the turn
           |  runs `claude -p`          |
           '--- posts reply + files ----'

Because the bridge calls out to Odoo, it needs no inbound port, no CORS and no
browser permission for local network access. It uses the developer's own Claude
Code login, so there is no Anthropic API key and no per-token billing.

Setup:

1. Settings > Centric Claude: set **Claude Backend** to *Local Claude Code agent*,
   set **Agent Runs As** to a user with the Claude Developer group, then click
   **Generate Agent Token** and copy the token.
2. On the developer machine, make sure `claude` is on PATH and logged in.
3. Run the bridge from `tools/claude_bridge.py`:

       export CENTRIC_CLAUDE_URL=https://your-odoo.odoo.com
       export CENTRIC_CLAUDE_TOKEN=<generated token>
       export CENTRIC_CLAUDE_REPO=/path/to/your/local/clone
       python claude_bridge.py

The workspace shows *Local agent* in its header, and a queued message waits until
the bridge picks it up. Claude > Agent Queue shows every turn and its state.

The bridge refuses to run with a dirty working tree, never commits or pushes, and
reverts the checkout after handing the edits to Odoo. Only files inside an
approved module are sent; anything else is reported and dropped.

### Anthropic API

Odoo calls `api.anthropic.com` directly with its own API key, billed per token.
Use this when no developer machine is available to run the bridge.

## Configuration

Open Odoo Settings and configure the Centric Claude section:

- Enable Claude
- Claude Backend, plus either the agent token or the Anthropic API key
- Claude model
- GitHub owner
- GitHub repository
- GitHub fine-grained token
- Default base branch, usually `testing`
- Allowed module prefix, usually `centric_`
- Allow Source Code Reading
- Allow Code Modifications
- Allow Pull Request Creation

Assign users one of these access levels:

- Centric Claude / User
- Centric Claude / Code Reader
- Centric Claude / Developer
- Centric Claude / Administrator

## GitHub token permissions

For read-only use, the token needs repository Contents read access.
For Developer commits, it needs repository Contents write access.
For pull requests, it also needs permission to create pull requests for the repository.

Use a fine-grained token restricted to the single repository whenever possible.

## Development workflow

1. A developer opens Claude > Developer Workspace.
2. The developer selects or creates a conversation.
3. Developer Mode is enabled when code changes are required.
4. Claude inspects the approved repository source and stages proposed changes.
5. The developer reviews the Changes tab and unified diff.
6. The developer clicks Commit to Review Branch.
7. The module creates a new `claude/...` branch and commits the reviewed changes.
8. The developer can create a pull request.
9. Odoo.sh can then build/test the branch through the normal GitHub integration.

## Current scope

This first version intentionally does not:

- edit the production filesystem;
- merge pull requests;
- push directly to production;
- expose secrets to Claude;
- run arbitrary shell commands on the Odoo server;
- embed the desktop VS Code application.

The Code tab is the in-Odoo source browser/editor, while GitHub remains the source of truth.
