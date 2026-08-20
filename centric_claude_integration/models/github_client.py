import base64
import logging
import re
from collections import Counter
from urllib.parse import quote

import requests

from odoo import _, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class CentricClaudeGithubClient(models.AbstractModel):
    _name = "centric.claude.github.client"
    _description = "Centric Claude GitHub Client"

    API_ROOT = "https://api.github.com"
    API_VERSION = "2026-03-10"
    TEXT_EXTENSIONS = {
        ".py", ".xml", ".csv", ".js", ".scss", ".css", ".json", ".md", ".txt",
        ".po", ".pot", ".html", ".jinja", ".yml", ".yaml",
    }
    NEVER_ALLOW = {
        ".env", ".git", ".github", "odoo.conf", "requirements.txt",
    }

    def _param(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _config(self):
        return {
            "owner": self._param("centric_claude.github_owner"),
            "repo": self._param("centric_claude.github_repo"),
            "token": self._param("centric_claude.github_token"),
            "branch": self._param("centric_claude.default_branch", "testing"),
            "prefix": self._param("centric_claude.allowed_module_prefix", "centric_"),
        }

    def _repo_label(self, owner, repo):
        return f"{owner}/{repo}"

    def _headers(self, token=None):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.API_VERSION,
            "User-Agent": "Centric-Odoo-Claude-Integration",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request(self, method, path, *, token=None, params=None, payload=None, expected=(200,)):
        url = f"{self.API_ROOT}{path}"
        try:
            response = requests.request(
                method,
                url,
                headers=self._headers(token),
                params=params,
                json=payload,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise UserError(_("GitHub request failed: %s") % exc) from exc

        if response.status_code not in expected:
            try:
                detail = response.json().get("message") or response.text
            except ValueError:
                detail = response.text
            _logger.warning("GitHub API error %s on %s: %s", response.status_code, path, detail)
            raise UserError(_("GitHub returned HTTP %(status)s: %(detail)s") % {
                "status": response.status_code,
                "detail": detail[:1000],
            })
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise UserError(_("GitHub returned an invalid JSON response.")) from exc

    def _require_repository(self, owner=None, repo=None):
        config = self._config()
        owner = owner or config["owner"]
        repo = repo or config["repo"]
        if not owner or not repo:
            raise UserError(_("GitHub owner and repository are not configured."))
        return owner, repo

    def _test_connection(self, owner=None, repo=None, token=None, branch=None):
        """Check the repo AND that the branch Claude will actually read exists.

        Checking only the repository is misleading: a Default Base Branch that
        does not exist still passes, then every read fails with a 404 later.
        """
        config = self._config()
        owner, repo = self._require_repository(owner, repo)
        token = token if token is not None else config["token"]
        data = self._request("GET", f"/repos/{quote(owner)}/{quote(repo)}", token=token)
        label = data.get("full_name") or self._repo_label(owner, repo)
        github_default = data.get("default_branch") or "unknown"
        branch = branch or config["branch"]

        if not branch:
            raise UserError(_("Set a Default Base Branch before testing."))
        try:
            self._get_branch_ref(branch, owner, repo, token)
        except UserError as exc:
            raise UserError(_(
                "Connected to %(repo)s, but the branch Claude is configured to read, "
                "'%(branch)s', does not exist there.\n\n"
                "GitHub's own default branch is '%(default)s'. Either create "
                "'%(branch)s' or change Default Base Branch.\n\n%(detail)s"
            ) % {
                "repo": label, "branch": branch,
                "default": github_default, "detail": exc,
            }) from exc

        # A branch that exists but holds no approved modules looks fine here and
        # then shows an empty Code tab. Say so now instead.
        modules = self._list_allowed_modules(branch=branch)
        prefix = config["prefix"] or "centric_"
        if modules:
            found = _("\nFound %(count)s approved module(s): %(names)s") % {
                "count": len(modules),
                "names": ", ".join(m["name"] for m in modules[:8]),
            }
        else:
            found = _(
                "\n\nWARNING: branch '%(branch)s' contains no modules starting with "
                "'%(prefix)s'. Claude will see nothing. Check you picked the right branch."
            ) % {"branch": branch, "prefix": prefix}

        note = ""
        if not token:
            note = _("\n\nNo GitHub token is set. Reads work because this repository "
                     "is public, but committing needs a token with Contents: write.")
        return _(
            "Connected to %(repo)s.\nClaude will read branch '%(branch)s' - it exists.\n"
            "(GitHub's own default branch is '%(default)s'; that is separate.)"
            "%(found)s%(note)s"
        ) % {"repo": label, "branch": branch, "default": github_default,
             "found": found, "note": note}

    def _get_branch_ref(self, branch, owner=None, repo=None, token=None):
        owner, repo = self._require_repository(owner, repo)
        token = token if token is not None else self._config()["token"]
        return self._request(
            "GET",
            f"/repos/{quote(owner)}/{quote(repo)}/git/ref/heads/{quote(branch, safe='/')}",
            token=token,
        )

    def _get_commit(self, sha, owner=None, repo=None, token=None):
        owner, repo = self._require_repository(owner, repo)
        token = token if token is not None else self._config()["token"]
        return self._request(
            "GET",
            f"/repos/{quote(owner)}/{quote(repo)}/git/commits/{quote(sha)}",
            token=token,
        )

    def _get_tree(self, branch=None, owner=None, repo=None, token=None):
        config = self._config()
        owner, repo = self._require_repository(owner, repo)
        branch = branch or config["branch"]
        token = token if token is not None else config["token"]
        ref = self._get_branch_ref(branch, owner, repo, token)
        commit_sha = ref["object"]["sha"]
        commit = self._get_commit(commit_sha, owner, repo, token)
        tree_sha = commit["tree"]["sha"]
        tree = self._request(
            "GET",
            f"/repos/{quote(owner)}/{quote(repo)}/git/trees/{quote(tree_sha)}",
            token=token,
            params={"recursive": "1"},
        )
        if tree.get("truncated"):
            raise UserError(_("The GitHub repository tree is too large to browse safely."))
        return {
            "branch": branch,
            "commit_sha": commit_sha,
            "tree_sha": tree_sha,
            "entries": tree.get("tree", []),
        }

    def _list_allowed_modules(self, branch=None, tree=None):
        config = self._config()
        prefix = config["prefix"] or "centric_"
        # Callers that already walked the tree pass it in; each walk is 3 API calls.
        tree = tree if tree is not None else self._get_tree(branch=branch)
        modules = []
        for item in tree["entries"]:
            path = item.get("path", "")
            if item.get("type") != "blob" or not path.endswith("/__manifest__.py"):
                continue
            root = path.rsplit("/", 1)[0]
            module_name = root.rsplit("/", 1)[-1]
            if not module_name.startswith(prefix):
                continue
            modules.append({
                "name": module_name,
                "root": root,
                "manifest_path": path,
            })
        modules.sort(key=lambda item: item["name"].lower())
        return modules

    MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

    def _module_root(self, module_name, branch=None, tree=None):
        for module in self._list_allowed_modules(branch=branch, tree=tree):
            if module["name"] == module_name:
                return module["root"]
        raise UserError(_("Module '%s' is not an approved repository module.") % module_name)

    def _new_module_root(self, module_name, branch=None, tree=None):
        """Where a module that does not exist yet should be created.

        Odoo only recognises a directory as a module once it holds a manifest,
        so a new module has no root to look up - it has to be chosen. Sit it
        beside the existing approved modules rather than assuming the repository
        root: layouts that keep addons under a subdirectory are common, and this
        repository already has one module nested a level down.
        """
        prefix = self._config()["prefix"] or "centric_"
        name = (module_name or "").strip().strip("/")
        if not self.MODULE_NAME_RE.match(name):
            raise UserError(_(
                "'%s' is not a valid module name. Use lowercase letters, digits "
                "and underscores, starting with a letter."
            ) % (module_name or ""))
        if not name.startswith(prefix):
            raise UserError(_(
                "New modules must start with '%(prefix)s', so '%(name)s' is not allowed."
            ) % {"prefix": prefix, "name": name})
        modules = self._list_allowed_modules(branch=branch, tree=tree)
        if any(module["name"] == name for module in modules):
            raise UserError(_("Module '%s' already exists on this branch.") % name)
        parents = [
            module["root"].rsplit("/", 1)[0] if "/" in module["root"] else ""
            for module in modules
        ]
        parent = Counter(parents).most_common(1)[0][0] if parents else ""
        return f"{parent}/{name}" if parent else name

    def _resolve_module_root(self, module_name, branch=None, tree=None, allow_new=False):
        """Return (root, is_new) for an approved module, creating a root if asked."""
        tree = tree if tree is not None else self._get_tree(branch=branch)
        for module in self._list_allowed_modules(branch=branch, tree=tree):
            if module["name"] == module_name:
                return module["root"], False
        if not allow_new:
            raise UserError(
                _("Module '%s' is not an approved repository module.") % module_name
            )
        return self._new_module_root(module_name, branch=branch, tree=tree), True

    def _validate_module_file(self, module_name, relative_path, branch=None, require_text=True, root=None):
        relative_path = (relative_path or "").strip().lstrip("/")
        if not relative_path or relative_path.startswith("../") or "/../" in relative_path:
            raise UserError(_("Invalid repository file path."))
        # `root` lets callers that already resolved the module skip three API calls.
        root = root or self._module_root(module_name, branch=branch)
        full_path = f"{root}/{relative_path}" if relative_path else root
        path_parts = set(full_path.split("/"))
        if path_parts & self.NEVER_ALLOW:
            raise UserError(_("Access to this repository path is blocked."))
        if require_text:
            filename = full_path.rsplit("/", 1)[-1]
            if "." in filename:
                ext = "." + filename.rsplit(".", 1)[-1].lower()
                if ext not in self.TEXT_EXTENSIONS and filename not in {"__manifest__.py", "__init__.py"}:
                    raise UserError(_("Only text source files can be opened in the Claude workspace."))
        return root, full_path

    def _list_module_files(self, module_name, branch=None, tree=None):
        tree = tree if tree is not None else self._get_tree(branch=branch)
        root = self._module_root(module_name, branch=branch, tree=tree)
        prefix = root + "/"
        result = []
        for item in tree["entries"]:
            path = item.get("path", "")
            if not path.startswith(prefix) or item.get("type") != "blob":
                continue
            relative = path[len(prefix):]
            if not relative or any(part in self.NEVER_ALLOW for part in relative.split("/")):
                continue
            result.append({
                "path": relative,
                "size": item.get("size", 0),
                "sha": item.get("sha"),
            })
        result.sort(key=lambda item: item["path"].lower())
        return result

    def _read_module_file(self, module_name, relative_path, branch=None, root=None,
                          allow_missing=False):
        """Read one file. With allow_missing, a file absent from the branch gives None.

        The sandbox rules still apply either way: a blocked, non-text or
        out-of-module path raises rather than returning None.
        """
        branch = branch or self._config()["branch"]
        _root, full_path = self._validate_module_file(
            module_name, relative_path, branch=branch, root=root
        )
        data = self._read_path(full_path, branch=branch, allow_missing=allow_missing)
        if data is None:
            return None
        data.update({"module": module_name, "path": relative_path})
        return data

    def _read_path(self, full_path, branch=None, allow_missing=False):
        """Read one already-validated repository path.

        Callers must have run the path through `_validate_module_file` first;
        this deliberately performs no sandbox checks of its own.
        """
        config = self._config()
        branch = branch or config["branch"]
        owner, repo = self._require_repository()
        data = self._request(
            "GET",
            f"/repos/{quote(owner)}/{quote(repo)}/contents/{quote(full_path, safe='/')}",
            token=config["token"],
            params={"ref": branch},
            expected=(200, 404) if allow_missing else (200,),
        )
        if not isinstance(data, dict):
            # A directory comes back as a list.
            raise UserError(_("The requested repository path is not a file."))
        if allow_missing and "content" not in data:
            return None
        if data.get("type") != "file":
            raise UserError(_("The requested repository path is not a file."))
        if data.get("size", 0) > 512000:
            raise UserError(_("The file is larger than the 500 KB workspace safety limit."))
        try:
            content = base64.b64decode(data.get("content", "")).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise UserError(_("The requested file is not valid UTF-8 text.")) from exc
        return {
            "full_path": full_path,
            "sha": data.get("sha"),
            "content": content,
            "branch": branch,
        }

    def _search_module_code(self, module_name, query, branch=None, max_files=60, max_results=80):
        query = (query or "").strip()
        if not query:
            return []
        # Walk the tree once and reuse it: without this every file re-walks it.
        tree = self._get_tree(branch=branch)
        root = self._module_root(module_name, branch=branch, tree=tree)
        files = self._list_module_files(module_name, branch=branch, tree=tree)
        results = []
        scanned = 0
        for file_info in files:
            if scanned >= max_files or len(results) >= max_results:
                break
            path = file_info["path"]
            filename = path.rsplit("/", 1)[-1]
            if "." in filename:
                ext = "." + filename.rsplit(".", 1)[-1].lower()
                if ext not in self.TEXT_EXTENSIONS:
                    continue
            if file_info.get("size", 0) > 200000:
                continue
            scanned += 1
            try:
                file_data = self._read_module_file(module_name, path, branch=branch, root=root)
            except UserError:
                continue
            for line_no, line in enumerate(file_data["content"].splitlines(), 1):
                if query.lower() in line.lower():
                    results.append({
                        "path": path,
                        "line": line_no,
                        "text": line.strip()[:500],
                    })
                    if len(results) >= max_results:
                        break
        return results

    def _create_branch(self, branch, from_branch=None):
        config = self._config()
        owner, repo = self._require_repository()
        from_branch = from_branch or config["branch"]
        base_ref = self._get_branch_ref(from_branch, owner, repo, config["token"])
        base_sha = base_ref["object"]["sha"]
        self._request(
            "POST",
            f"/repos/{quote(owner)}/{quote(repo)}/git/refs",
            token=config["token"],
            payload={"ref": f"refs/heads/{branch}", "sha": base_sha},
            expected=(201,),
        )
        return {"branch": branch, "sha": base_sha}

    def _prepare_tree_entries(self, branch, changes):
        """Validate staged changes against `branch` and build the git tree entries.

        Runs the drift check, so callers can verify a commit will succeed before
        creating a review branch on GitHub.
        """
        tree = self._get_tree(branch=branch)
        roots = {}
        tree_entries = []
        for change in changes:
            module_name = change["module_name"]
            relative_path = change["file_path"]
            full_path = change.get("full_path")
            if not full_path:
                # Staged before full_path was recorded: resolve it the old way.
                if module_name not in roots:
                    roots[module_name] = self._module_root(
                        module_name, branch=branch, tree=tree
                    )
                _root, full_path = self._validate_module_file(
                    module_name, relative_path, branch=branch, root=roots[module_name]
                )
            current = self._read_path(full_path, branch=branch, allow_missing=True)
            # A staged new file has "" as its baseline, matching an absent file.
            current_content = current["content"] if current else ""
            if current_content != change["original_content"]:
                raise UserError(_(
                    "%(file)s changed on GitHub after Claude staged it. Refresh and review the file again before committing."
                ) % {"file": full_path})
            tree_entries.append({
                "path": full_path,
                "mode": "100644",
                "type": "blob",
                "content": change["proposed_content"],
            })
        return tree_entries

    def _commit_files(self, branch, changes, message, tree_entries=None):
        config = self._config()
        owner, repo = self._require_repository()
        token = config["token"]
        ref = self._get_branch_ref(branch, owner, repo, token)
        parent_sha = ref["object"]["sha"]
        parent_commit = self._get_commit(parent_sha, owner, repo, token)
        base_tree_sha = parent_commit["tree"]["sha"]

        if tree_entries is None:
            tree_entries = self._prepare_tree_entries(branch, changes)

        tree = self._request(
            "POST",
            f"/repos/{quote(owner)}/{quote(repo)}/git/trees",
            token=token,
            payload={"base_tree": base_tree_sha, "tree": tree_entries},
            expected=(201,),
        )
        commit = self._request(
            "POST",
            f"/repos/{quote(owner)}/{quote(repo)}/git/commits",
            token=token,
            payload={
                "message": message,
                "tree": tree["sha"],
                "parents": [parent_sha],
            },
            expected=(201,),
        )
        self._request(
            "PATCH",
            f"/repos/{quote(owner)}/{quote(repo)}/git/refs/heads/{quote(branch, safe='/')}",
            token=token,
            payload={"sha": commit["sha"], "force": False},
            expected=(200,),
        )
        return {"branch": branch, "commit_sha": commit["sha"]}

    def _create_pull_request(self, head_branch, base_branch, title, body=None):
        config = self._config()
        owner, repo = self._require_repository()
        result = self._request(
            "POST",
            f"/repos/{quote(owner)}/{quote(repo)}/pulls",
            token=config["token"],
            payload={
                "title": title,
                "head": head_branch,
                "base": base_branch,
                "body": body or "Created from Centric Claude Integration in Odoo.",
            },
            expected=(201,),
        )
        return {
            "number": result.get("number"),
            "url": result.get("html_url"),
            "title": result.get("title"),
        }
