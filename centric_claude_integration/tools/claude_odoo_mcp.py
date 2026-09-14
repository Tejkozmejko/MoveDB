#!/usr/bin/env python3
"""An MCP server that lets Claude Code read and propose changes to Odoo data.

The bridge starts this for the duration of one turn. Claude Code speaks MCP to
it over stdin/stdout; it speaks JSON-RPC over HTTPS to the Odoo instance, using
the agent token and the id of the turn currently being worked on.

Two things are deliberately *not* decided here:

* which records are visible - Odoo answers that, using the permissions of the
  person who asked the question, not this process's;
* whether a change happens - a proposal only queues a confirmation for that
  person to accept in the Odoo chat.

So this file is a transport. It must not be trusted as a security boundary, and
it does not try to be one.

Configured entirely through the environment, because command lines are visible
to other processes on the machine and the token must not be:

    CENTRIC_CLAUDE_URL     https://your-instance.odoo.com
    CENTRIC_CLAUDE_TOKEN   the agent token from Odoo settings
    CENTRIC_CLAUDE_TURN    the turn id being handled
    CENTRIC_CLAUDE_LEVEL   user | intermediate | admin
"""
import json
import os
import sys
import urllib.error
import urllib.request

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "odoo"
SERVER_VERSION = "1.0.0"
TIMEOUT = 60


def log(message):
    """Diagnostics go to stderr; stdout carries the protocol and nothing else."""
    sys.stderr.write("[odoo-mcp] %s\n" % message)
    sys.stderr.flush()


class OdooError(Exception):
    pass


class Odoo:
    def __init__(self, url, token, turn_id):
        self.url = (url or "").rstrip("/")
        self.token = token or ""
        self.turn_id = turn_id

    def call(self, op, params):
        body = json.dumps({
            "jsonrpc": "2.0",
            "method": "call",
            "id": 1,
            "params": {"turn_id": self.turn_id, "op": op, "params": params},
        }).encode("utf-8")
        request = urllib.request.Request(
            self.url + "/centric_claude/agent/odoo",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise OdooError("Odoo returned HTTP %s" % exc.code) from exc
        except urllib.error.URLError as exc:
            raise OdooError("Could not reach Odoo: %s" % exc.reason) from exc
        except ValueError as exc:
            raise OdooError("Odoo sent a reply that was not JSON.") from exc

        if "error" in payload:
            message = payload["error"]
            if isinstance(message, dict):
                message = (message.get("data") or {}).get("message") or message.get("message")
            raise OdooError(str(message))
        result = payload.get("result") or {}
        if result.get("error"):
            raise OdooError(result["error"])
        return result.get("result", result)


# --------------------------------------------------------------------- tools
def read_tools():
    return [
        {
            "name": "odoo_find_models",
            "description": (
                "Find Odoo models by technical or human name, for example 'helpdesk', "
                "'invoice' or 'sale order'. Use this first when you are not certain of "
                "a model's technical name. Only models the user may read are returned."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Words to look for."},
                },
                "required": ["query"],
            },
        },
        {
            "name": "odoo_describe_model",
            "description": (
                "List the fields of one Odoo model with their types, labels and "
                "selection options. Read this before filtering on, or setting, a field "
                "you have not already seen."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "e.g. helpdesk.ticket"},
                },
                "required": ["model"],
            },
        },
        {
            "name": "odoo_search",
            "description": (
                "Search real records in the live Odoo database. Runs with the "
                "permissions of the user who asked the question, so an empty result may "
                "mean 'none visible to them' rather than 'none exist'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "domain": {
                        "type": "string",
                        "description": 'An Odoo domain as JSON, e.g. [["state","=","open"]]. Use [] for all.',
                    },
                    "fields": {
                        "type": "string",
                        "description": "Comma-separated field names. Leave empty to let Odoo choose useful ones.",
                    },
                    "limit": {"type": "integer", "description": "1 to 200. Default 40."},
                    "order": {"type": "string", "description": "e.g. 'create_date desc'."},
                },
                "required": ["model"],
            },
        },
        {
            "name": "odoo_read",
            "description": "Read one record in full by id, when a search result lacked the detail you need.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "id": {"type": "integer"},
                    "fields": {"type": "string", "description": "Comma-separated, or empty for all readable fields."},
                },
                "required": ["model", "id"],
            },
        },
        {
            "name": "odoo_count",
            "description": "Count matching records without fetching them. Use this for 'how many' questions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "domain": {"type": "string", "description": "An Odoo domain as JSON. Use [] for all."},
                },
                "required": ["model"],
            },
        },
    ]


def write_tools():
    return [
        {
            "name": "odoo_propose_change",
            "description": (
                "Propose creating, updating or deleting Odoo records. THIS DOES NOT "
                "CHANGE ANYTHING. It puts a confirmation in the Odoo chat that the user "
                "must accept. After calling it, tell the user plainly what you proposed "
                "and that it is waiting for their Yes. Never say a record was created, "
                "updated or deleted."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["create", "write", "unlink"]},
                    "model": {"type": "string"},
                    "record_ids": {
                        "type": "string",
                        "description": "Comma-separated ids for update or delete. Empty when creating.",
                    },
                    "values": {
                        "type": "string",
                        "description": 'Field values as a JSON object, e.g. {"name": "ACME"}. Empty when deleting.',
                    },
                    "summary": {
                        "type": "string",
                        "description": "One plain sentence the user will read before deciding.",
                    },
                },
                "required": ["kind", "model", "summary"],
            },
        },
        {
            "name": "odoo_propose_action",
            "description": (
                "Propose running a built-in Odoo action on records, such as action_post "
                "on an invoice or action_confirm on a sales order. Like odoo_propose_change, "
                "this only asks the user; nothing runs until they accept."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "record_ids": {"type": "string", "description": "Comma-separated ids."},
                    "method": {"type": "string", "description": "Public method name, e.g. action_post."},
                    "summary": {"type": "string"},
                },
                "required": ["model", "record_ids", "method", "summary"],
            },
        },
    ]


def tools_for(level):
    if level not in ("user", "intermediate", "admin"):
        return []
    tools = read_tools()
    if level in ("intermediate", "admin"):
        tools += write_tools()
    return tools


DISPATCH = {
    "odoo_find_models": ("find_models", ("query",)),
    "odoo_describe_model": ("describe_model", ("model",)),
    "odoo_search": ("search", ("model", "domain", "fields", "limit", "order")),
    "odoo_read": ("read", ("model", "id", "fields")),
    "odoo_count": ("count", ("model", "domain")),
}


def call_tool(odoo, name, arguments):
    arguments = arguments or {}
    if name in DISPATCH:
        op, keys = DISPATCH[name]
        return odoo.call(op, {key: arguments.get(key) for key in keys})
    if name == "odoo_propose_change":
        return odoo.call("propose", {
            "kind": arguments.get("kind"),
            "model": arguments.get("model"),
            "record_ids": arguments.get("record_ids") or "",
            "values": arguments.get("values") or "",
            "summary": arguments.get("summary"),
        })
    if name == "odoo_propose_action":
        return odoo.call("propose", {
            "kind": "method",
            "model": arguments.get("model"),
            "record_ids": arguments.get("record_ids") or "",
            "values": "",
            "method": arguments.get("method"),
            "summary": arguments.get("summary"),
        })
    raise OdooError("Unknown tool: %s" % name)


# ---------------------------------------------------------------- transport
def respond(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def handle(message, odoo, level):
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method in ("notifications/initialized", "initialized"):
        return None  # A notification carries no id and takes no reply.

    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {"tools": tools_for(level)},
        }

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        allowed = {tool["name"] for tool in tools_for(level)}
        if name not in allowed:
            # Refusing here as well as in Odoo means a mis-set level cannot be
            # talked around, but Odoo remains the authority.
            return tool_error(request_id,
                              "'%s' is not available at the '%s' data level." % (name, level))
        try:
            result = call_tool(odoo, name, params.get("arguments"))
        except OdooError as exc:
            return tool_error(request_id, str(exc))
        except Exception as exc:  # noqa: BLE001 - report, never crash the server.
            log("tool %s failed: %r" % (name, exc))
            return tool_error(request_id, "%s: %s" % (type(exc).__name__, exc))
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}]
            },
        }

    if request_id is None:
        return None  # Unknown notification: ignore.
    return {
        "jsonrpc": "2.0", "id": request_id,
        "error": {"code": -32601, "message": "Method not found: %s" % method},
    }


def tool_error(request_id, text):
    """An error Claude should read and work around, not a protocol failure."""
    return {
        "jsonrpc": "2.0", "id": request_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": True},
    }


def main():
    url = os.environ.get("CENTRIC_CLAUDE_URL")
    token = os.environ.get("CENTRIC_CLAUDE_TOKEN")
    turn_id = os.environ.get("CENTRIC_CLAUDE_TURN")
    level = os.environ.get("CENTRIC_CLAUDE_LEVEL", "none")
    if not url or not token or not turn_id:
        log("CENTRIC_CLAUDE_URL, _TOKEN and _TURN must all be set.")
        return 2

    odoo = Odoo(url, token, turn_id)
    log("ready at level %s for turn %s" % (level, turn_id))

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            log("ignoring non-JSON input")
            continue
        try:
            reply = handle(message, odoo, level)
        except Exception as exc:  # noqa: BLE001 - a bad message must not end the session.
            log("handler error: %r" % exc)
            reply = {
                "jsonrpc": "2.0", "id": message.get("id"),
                "error": {"code": -32603, "message": str(exc)},
            }
        if reply is not None:
            respond(reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
