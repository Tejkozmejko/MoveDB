from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class CentricClaudeProject(models.Model):
    """A named folder of conversations that share standing instructions.

    The same idea as a project on claude.ai: chats grouped by the piece of work
    they belong to, plus a block of context every chat in the group starts from,
    so the same background does not have to be retyped in each question.
    """

    _name = "centric.claude.project"
    _description = "Claude Project"
    _order = "sequence, name, id"

    MAX_NAME = 120
    MAX_INSTRUCTIONS = 8000

    name = fields.Char(required=True, default=lambda self: self._default_name())
    user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    instructions = fields.Text(
        help="Standing context added to the system prompt of every conversation "
             "in this project.",
    )
    conversation_ids = fields.One2many(
        "centric.claude.conversation", "project_id", string="Conversations",
    )
    conversation_count = fields.Integer(compute="_compute_conversation_count")

    @api.model
    def _default_name(self):
        return _("New project")

    @api.model
    def _default_names(self):
        """Every spelling of the placeholder name, so auto-naming survives translation."""
        return {"New project", _("New project")}

    @api.depends("conversation_ids")
    def _compute_conversation_count(self):
        for project in self:
            project.conversation_count = len(project.conversation_ids)

    def _check_owner(self):
        self.ensure_one()
        if self.user_id != self.env.user and not self.env.user.has_group(
            "centric_claude_integration.group_claude_admin"
        ):
            raise AccessError(_("You can only open your own Claude projects."))

    def _summary(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "instructions": self.instructions or "",
            "conversation_count": self.conversation_count,
        }

    @api.model
    def _workspace_projects(self):
        projects = self.search([("user_id", "=", self.env.user.id)])
        return [project._summary() for project in projects]

    @api.model
    def _require_access(self):
        access = self.env["centric.claude.conversation"]._workspace_access()
        if not access["can_chat"]:
            raise AccessError(_("You do not have access to the Claude workspace."))
        return access

    def _browse_own(self, project_id):
        project = self.browse(int(project_id)).exists()
        if not project:
            raise UserError(_("That Claude project no longer exists."))
        project._check_owner()
        return project

    # ------------------------------------------------------------ workspace
    @api.model
    def create_workspace_project(self, name=None):
        self._require_access()
        project = self.create({
            "name": (name or self._default_name()).strip()[:self.MAX_NAME],
            "user_id": self.env.user.id,
        })
        # The list is ordered by name, so the caller cannot work out which row
        # is the new one; hand back the id and let it select it.
        sidebar = self.env["centric.claude.conversation"]._workspace_sidebar()
        return sidebar | {"project_id": project.id}

    @api.model
    def rename_workspace_project(self, project_id, name):
        self._require_access()
        project = self._browse_own(project_id)
        clean = (name or "").strip()[:self.MAX_NAME]
        if not clean:
            raise ValidationError(_("A project needs a name."))
        project.name = clean
        return self.env["centric.claude.conversation"]._workspace_sidebar()

    @api.model
    def set_workspace_project_instructions(self, project_id, instructions):
        self._require_access()
        project = self._browse_own(project_id)
        text = (instructions or "").strip()
        if len(text) > self.MAX_INSTRUCTIONS:
            raise ValidationError(_(
                "Project instructions are limited to %s characters."
            ) % self.MAX_INSTRUCTIONS)
        project.instructions = text or False
        return self.env["centric.claude.conversation"]._workspace_sidebar()

    @api.model
    def delete_workspace_project(self, project_id):
        """Remove the folder. Its conversations survive, unfiled.

        Deleting a project must never destroy a transcript by implication -
        `project_id` is `ondelete="set null"` on the conversation for exactly
        that reason, and chats are deleted one at a time, deliberately.
        """
        self._require_access()
        project = self._browse_own(project_id)
        project.unlink()
        return self.env["centric.claude.conversation"]._workspace_sidebar()
