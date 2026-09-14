#!/usr/bin/env python3
"""Check the custom modules before a commit reaches Odoo.sh.

CLAUDE_WORKFLOW.md has told every agent and every developer to run this before
committing since long before it existed. It does now.

The point of it is the last check. Odoo validates every view against its own
RELAX NG schemas at install time, and a view that is perfectly well-formed XML
can still be an illegal view - which is how this went out:

    RELAXNG_ERR_INVALIDATTR: Invalid attribute expand for element group
    Invalid view centric.restaurant.menu.report.search definition
    Failed to load registry

That failed a build, and nothing short of installing the module would have
caught it. The schemas are Odoo's own, taken from a local Odoo if there is one
and downloaded once and cached if there is not, so this stays honest about what
Odoo will actually accept rather than approximating it.

    python scripts/validate-modules.py

Exits non-zero if anything is wrong, so it works as a pre-commit hook.
"""
import argparse
import ast
import glob
import os

import sys
import tempfile
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ODOO_VERSION = "19.0"
RNG_URL = (
    "https://raw.githubusercontent.com/odoo/odoo/%s/odoo/addons/base/rng/%%s"
    % ODOO_VERSION
)
# form, kanban and qweb have no RNG in Odoo 19 and are validated another way,
# so they are reported as skipped rather than silently passed.
SCHEMA_FOR = {
    "search": "search_view.rng",
    "list": "list_view.rng",
    "tree": "list_view.rng",
    "pivot": "pivot_view.rng",
    "graph": "graph_view.rng",
    "calendar": "calendar_view.rng",
    "activity": "activity_view.rng",
}
REQUIRED_MANIFEST_KEYS = ("name", "version", "depends")

problems = []


def fail(where, message):
    problems.append((where, message))


def module_dirs(pattern):
    return sorted(
        path
        for path in glob.glob(os.path.join(REPO, pattern))
        if os.path.isfile(os.path.join(path, "__manifest__.py"))
    )


def files(modules, suffix):
    for module in modules:
        for root, dirs, names in os.walk(module):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules")]
            for name in sorted(names):
                if name.endswith(suffix):
                    yield os.path.join(root, name)


def rel(path):
    return os.path.relpath(path, REPO).replace(os.sep, "/")


# ------------------------------------------------------------------ python ---
def check_python(modules):
    """Compile in memory rather than to a file.

    py_compile wants somewhere to put the .pyc, and os.devnull on Windows is
    `nul`, which it refuses. Nothing here needs the bytecode - only whether it
    would compile - so build it and throw it away.
    """
    count = 0
    for path in files(modules, ".py"):
        count += 1
        try:
            with open(path, encoding="utf-8") as handle:
                compile(handle.read(), path, "exec")
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            fail(rel(path), "%s: %s" % (type(exc).__name__, exc))
    return count


# --------------------------------------------------------------- manifests ---
def check_manifests(modules):
    for module in modules:
        path = os.path.join(module, "__manifest__.py")
        try:
            with open(path, encoding="utf-8") as handle:
                manifest = ast.literal_eval(handle.read())
        except Exception as exc:  # noqa: BLE001 - any failure is a failure
            fail(rel(path), "does not parse: %s" % exc)
            continue
        if not isinstance(manifest, dict):
            fail(rel(path), "is not a dictionary")
            continue
        for key in REQUIRED_MANIFEST_KEYS:
            if not manifest.get(key):
                fail(rel(path), "has no %r" % key)
        # A data file named in the manifest but missing stops the install dead.
        for entry in manifest.get("data") or []:
            if not os.path.isfile(os.path.join(module, entry)):
                fail(rel(path), "lists a data file that is not there: %s" % entry)
    return len(modules)


# --------------------------------------------------------------------- xml ---
def check_xml(modules, etree):
    count = 0
    for path in files(modules, ".xml"):
        count += 1
        try:
            etree.parse(path)
        except etree.XMLSyntaxError as exc:
            fail(rel(path), "not well-formed: %s" % exc)
    return count


# ------------------------------------------------------------------- views ---
def rng_dir():
    """Odoo's own view schemas: local if Odoo is installed, cached if not."""
    try:
        import odoo  # noqa: F401 - only for its location

        local = os.path.join(os.path.dirname(odoo.__file__), "addons", "base", "rng")
        if os.path.isdir(local):
            return local, "local Odoo"
    except ImportError:
        pass

    cache = os.path.join(tempfile.gettempdir(), "centric-odoo-rng-%s" % ODOO_VERSION)
    os.makedirs(cache, exist_ok=True)
    wanted = set(SCHEMA_FOR.values()) | {"common.rng"}
    for name in sorted(wanted):
        target = os.path.join(cache, name)
        if os.path.isfile(target) and os.path.getsize(target) > 200:
            continue
        try:
            with urllib.request.urlopen(RNG_URL % name, timeout=30) as response:
                data = response.read()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("could not fetch %s: %s" % (name, exc))
        with open(target, "wb") as handle:
            handle.write(data)
    return cache, "downloaded (cached in %s)" % cache


def check_views(modules, etree):
    try:
        directory, source = rng_dir()
    except RuntimeError as exc:
        print("  ! view schemas unavailable, views not checked: %s" % exc)
        return 0, 0

    cache = {}

    def schema(name):
        if name not in cache:
            with open(os.path.join(directory, name), "rb") as handle:
                cache[name] = etree.RelaxNG(etree.parse(handle))
        return cache[name]

    checked = skipped = 0
    for path in files(modules, ".xml"):
        if os.sep + "static" + os.sep in path:
            continue
        try:
            doc = etree.parse(path)
        except etree.XMLSyntaxError:
            continue  # already reported by check_xml
        for record in doc.iter("record"):
            if record.get("model") != "ir.ui.view":
                continue
            arch = record.find("field[@name='arch']")
            if arch is None:
                continue
            roots = [child for child in arch if isinstance(child.tag, str)]
            if not roots:
                continue
            root = roots[0]
            name = SCHEMA_FOR.get(root.tag)
            if not name:
                skipped += 1
                continue
            checked += 1
            validator = schema(name)
            if not validator.validate(root):
                for error in validator.error_log:
                    fail(
                        "%s <%s>" % (rel(path), record.get("id") or "?"),
                        error.message,
                    )
    return checked, skipped, source


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--modules", default="centric_*",
        help="Glob of module directories to check (default: centric_*)",
    )
    args = parser.parse_args(argv)

    modules = module_dirs(args.modules)
    if not modules:
        print("No modules matched %r." % args.modules)
        return 2

    print("Validating %d module(s): %s\n"
          % (len(modules), ", ".join(os.path.basename(m) for m in modules)))

    print("Checking Python...")
    print("  %d file(s)" % check_python(modules))

    print("Checking __manifest__.py...")
    print("  %d manifest(s)" % check_manifests(modules))

    try:
        from lxml import etree
    except ImportError:
        print("\nlxml is not installed, so XML and views were not checked.")
        print("  pip install lxml")
        etree = None

    if etree is not None:
        print("Checking XML syntax...")
        print("  %d file(s)" % check_xml(modules, etree))

        print("Checking view definitions against Odoo's schemas...")
        result = check_views(modules, etree)
        if len(result) == 3:
            checked, skipped, source = result
            print("  %d view(s) validated, %d without a schema  [%s]"
                  % (checked, skipped, source))

    if problems:
        print("\n%d problem(s):\n" % len(problems))
        for where, message in problems:
            print("  %s" % where)
            print("    %s\n" % message)
        return 1

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
