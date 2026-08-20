import logging

import requests

from odoo import _, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class CentricClaudeClient(models.AbstractModel):
    _name = "centric.claude.client"
    _description = "Centric Claude API Client"

    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"
    REQUEST_TIMEOUT = 300

    def _param(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _config(self):
        return {
            "enabled": self._param("centric_claude.enabled", "False") == "True",
            "api_key": self._param("centric_claude.api_key"),
            "model": self._param("centric_claude.model", "claude-opus-5"),
            "max_tokens": int(self._param("centric_claude.max_tokens", "16000") or 16000),
        }

    def _headers(self, api_key):
        return {
            "x-api-key": api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
            "user-agent": "Centric-Odoo-Claude-Integration",
        }

    def _create_message(
        self, messages, *, system=None, tools=None, api_key=None, model=None,
        max_tokens=None, effort="high",
    ):
        config = self._config()
        api_key = api_key or config["api_key"]
        model = model or config["model"]
        max_tokens = max_tokens or config["max_tokens"]
        if not api_key:
            raise UserError(_("The Anthropic API key is not configured."))
        if not model:
            raise UserError(_("The Claude model is not configured."))

        payload = {
            "model": model,
            "max_tokens": max(1, int(max_tokens)),
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = tools
            # Cache the tools + system prefix; it is identical on every tool round.
            payload["cache_control"] = {"type": "ephemeral"}
        # Adaptive thinking suits multi-step repository investigation and lets Claude
        # decide how much reasoning each turn needs. Never send {"type": "disabled"}:
        # it is rejected on some current models and degrades tool use on others.
        payload["thinking"] = {"type": "adaptive"}
        if effort:
            payload["output_config"] = {"effort": effort}

        try:
            response = requests.post(
                self.API_URL,
                headers=self._headers(api_key),
                json=payload,
                timeout=self.REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise UserError(_("Claude API request failed: %s") % exc) from exc

        if response.status_code != 200:
            try:
                data = response.json()
                detail = data.get("error", {}).get("message") or data.get("message") or response.text
            except ValueError:
                detail = response.text
            _logger.warning("Anthropic API error %s: %s", response.status_code, detail)
            raise UserError(_("Claude API returned HTTP %(status)s: %(detail)s") % {
                "status": response.status_code,
                "detail": detail[:1200],
            })
        try:
            return response.json()
        except ValueError as exc:
            raise UserError(_("Claude API returned an invalid JSON response.")) from exc

    def _test_connection(self, api_key=None, model=None):
        # Thinking tokens count against max_tokens, so leave headroom even for "OK".
        response = self._create_message(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            api_key=api_key,
            model=model,
            max_tokens=1024,
            effort="low",
        )
        text = "".join(
            block.get("text", "")
            for block in response.get("content", [])
            if block.get("type") == "text"
        ).strip()
        return _("Connected successfully. Claude replied: %s") % (text or "OK")
