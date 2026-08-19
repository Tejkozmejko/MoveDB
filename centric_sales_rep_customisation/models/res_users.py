from odoo import api, models
from odoo.fields import Command


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _centric_sync_sales_rep_role(self):
        """Keep the sales representative roles consistent on every install/upgrade.

        Two things are enforced here that plain XML data cannot guarantee on an
        already-populated database:

        1. Re-assert the implied Salesperson group. Writing ``implied_ids`` always
           clears the ``groups`` registry cache, which is what fixes the symptom we
           saw on a stale deployment (a rep hitting "not allowed to access
           delivery.carrier" even though the role implies the Salesperson group that
           grants it). In Odoo 19 implied groups are resolved live from that cache,
           so refreshing it is enough.
        2. Strip the full Invoicing (billing) group from restricted reps. Reps are
           meant to take orders and *view* their customers' invoices, while the
           office does the actual invoicing. The Invoicing group would otherwise
           grant create/edit on account.move and defeat the read-only invoice access
           this module sets up.

        Both points cover the "Sales Representative" level too: it implies the
        restricted role, so it inherits the Salesperson group through it, and its
        members are reached below through ``all_user_ids`` (implied members
        included) rather than ``user_ids`` (explicit members only) - picking the
        higher level in the Sales dropdown leaves a user out of the lower group's
        explicit membership.
        """
        rep_group = self.env.ref(
            "centric_sales_rep_customisation.group_centric_sales_representative",
            raise_if_not_found=False,
        )
        if not rep_group:
            return

        salesman_group = self.env.ref("sales_team.group_sale_salesman", raise_if_not_found=False)
        if salesman_group:
            # Idempotent: re-linking an existing implied group is a no-op for the
            # relation but still refreshes the groups cache.
            rep_group.write({"implied_ids": [Command.link(salesman_group.id)]})

        create_group = self.env.ref(
            "centric_sales_rep_customisation.group_centric_sales_representative_create",
            raise_if_not_found=False,
        )
        if create_group:
            create_group.write({"implied_ids": [Command.link(rep_group.id)]})

        invoicing_group = self.env.ref("account.group_account_invoice", raise_if_not_found=False)
        members = rep_group.all_user_ids
        if invoicing_group and members:
            members.write({"group_ids": [Command.unlink(invoicing_group.id)]})
