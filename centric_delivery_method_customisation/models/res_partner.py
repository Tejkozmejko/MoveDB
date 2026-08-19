import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ------------------------------------------------------------------
    # Centric custom delivery address fields
    # ------------------------------------------------------------------
    # These char fields capture the customer's delivery address directly on
    # the parent contact and remain the user-facing "source of truth" that
    # staff edit in the Contacts form. On their own they are invisible to
    # native Odoo delivery logic (sale.order.partner_shipping_id, pickings,
    # ...), because that logic only resolves real ``res.partner`` records of
    # ``type='delivery'`` via ``address_get(['delivery'])``. To bridge the
    # gap we mirror these fields into a managed native child contact (see
    # ``_centric_sync_delivery_child`` below).
    centric_delivery_name = fields.Char(
        string="Delivery Name",
        help="Name/label of the delivery location (e.g. the trading name used "
        "at the delivery site). Used as the name of the synced native "
        "delivery contact. Falls back to the customer name when empty.",
    )
    centric_delivery_street = fields.Char(string="Delivery Street")
    centric_delivery_street2 = fields.Char(string="Delivery Street 2")
    centric_delivery_city = fields.Char(string="Delivery City")
    centric_delivery_state_id = fields.Many2one(
        "res.country.state",
        string="Delivery State",
        domain="[('country_id', '=?', centric_delivery_country_id)]",
    )
    centric_delivery_zip = fields.Char(string="Delivery ZIP")
    centric_delivery_country_id = fields.Many2one(
        "res.country",
        string="Delivery Country",
    )
    centric_secondary_delivery_carrier_id = fields.Many2one(
        "delivery.carrier",
        company_dependent=True,
        string="Secondary Delivery Method",
        help="Fallback delivery method used for sales orders when no primary delivery method is set.",
    )
    centric_salesperson_id = fields.Many2one(
        "res.users",
        # Distinct label (not just "Salesperson") to avoid a duplicate-label
        # warning with the native res.partner.user_id, which is also
        # "Salesperson". Reads clearly as the salesperson for this location.
        string="Delivery Salesperson",
        # Only real salespeople may be picked, matching sale.order.user_id's own
        # domain (a Sales-group, non-portal user) - otherwise a non-sales /
        # cross-company user could be pushed onto the order as its salesperson.
        # A belt-and-suspenders guard in sale_order.py::_compute_user_id also
        # skips an out-of-scope user at assignment time (a Many2one domain is a
        # UI filter only, never re-validated on write).
        domain=lambda self: [
            ("all_group_ids", "in", self.env.ref("sales_team.group_sale_salesman").ids),
            ("share", "=", False),
        ],
        help="Salesperson responsible for this delivery location. When this "
             "contact is the Delivery Address on a sales order, the order's "
             "Salesperson is set to this user - and it updates automatically if "
             "the delivery address is changed to another location.",
    )

    # ------------------------------------------------------------------
    # Plumbing for the native delivery-contact mirror
    # ------------------------------------------------------------------
    centric_delivery_partner_id = fields.Many2one(
        "res.partner",
        string="Synced Delivery Contact",
        copy=False,
        index=True,
        help="Native child contact (type=Delivery) automatically generated "
        "from the Centric delivery address fields. This is the record native "
        "Odoo uses as the sales order Delivery Address (partner_shipping_id).",
    )
    centric_is_managed_delivery_address = fields.Boolean(
        string="Managed Delivery Address",
        copy=False,
        help="Set on contacts auto-generated from a parent's Centric delivery "
        "address fields. Used to keep the mirror in sync and to prevent "
        "recursive syncing.",
    )

    # Source fields whose change must refresh the mirrored delivery contact.
    _CENTRIC_DELIVERY_SOURCE_FIELDS = (
        "centric_delivery_name",
        "centric_delivery_street",
        "centric_delivery_street2",
        "centric_delivery_city",
        "centric_delivery_state_id",
        "centric_delivery_zip",
        "centric_delivery_country_id",
    )

    def _centric_has_delivery_address(self):
        """Return True when at least one delivery *address* component is set.

        The delivery name alone does not constitute an address, so it is
        intentionally excluded here.
        """
        self.ensure_one()
        return any(
            (
                self.centric_delivery_street,
                self.centric_delivery_street2,
                self.centric_delivery_city,
                self.centric_delivery_state_id,
                self.centric_delivery_zip,
                self.centric_delivery_country_id,
            )
        )

    # ------------------------------------------------------------------
    # Native delivery-contact mirror
    # ------------------------------------------------------------------
    def _centric_delivery_child_values(self):
        """Build create/write values for the managed native delivery contact
        mirrored from this partner's Centric delivery fields."""
        self.ensure_one()
        return {
            "name": self.centric_delivery_name or self.name or _("Delivery Address"),
            "type": "delivery",
            # Parent it under this partner so its commercial_partner_id resolves
            # to the customer's company. This keeps it (a) discoverable by
            # address_get's descendant scan and (b) visible to restricted sales
            # reps via the "commercial_partner_id.user_id == user" record rule.
            "parent_id": self.id,
            # Align the multi-company restriction with the parent so the contact
            # satisfies sale.order.partner_shipping_id's check_company domain.
            "company_id": self.company_id.id or False,
            "street": self.centric_delivery_street or False,
            "street2": self.centric_delivery_street2 or False,
            "city": self.centric_delivery_city or False,
            "state_id": self.centric_delivery_state_id.id or False,
            "zip": self.centric_delivery_zip or False,
            "country_id": self.centric_delivery_country_id.id or False,
            "centric_is_managed_delivery_address": True,
        }

    def _centric_sync_delivery_child(self):
        """Mirror the Centric delivery address fields into a managed native
        child contact of ``type='delivery'``.

        This makes the address a real ``res.partner`` record so it becomes
        selectable/auto-filled as the sales order Delivery Address
        (``partner_shipping_id``) and usable by every native Odoo delivery
        flow. The method is idempotent and safe to call repeatedly.
        """
        # Use sudo for the mirror upsert so the sync never fails on partner
        # access rights (e.g. a sales user editing an assigned customer). The
        # company_id is set explicitly, so multi-company integrity is preserved.
        Partner = self.env["res.partner"].sudo()
        for partner in self:
            # Never mirror a managed mirror onto itself (recursion guard).
            if partner.centric_is_managed_delivery_address:
                continue

            child = partner.centric_delivery_partner_id.sudo()

            if partner._centric_has_delivery_address():
                values = partner._centric_delivery_child_values()
                if child:
                    # Reactivate if it had been archived after a previous clear.
                    if not child.active:
                        values["active"] = True
                    child.write(values)
                    _logger.debug(
                        "Centric delivery: updated mirror contact %s for partner %s",
                        child.id,
                        partner.id,
                    )
                else:
                    # Create the mirror without re-triggering the sync chain.
                    child = Partner.with_context(
                        centric_skip_delivery_sync=True
                    ).create(values)
                    partner.with_context(centric_skip_delivery_sync=True).write(
                        {"centric_delivery_partner_id": child.id}
                    )
                    _logger.info(
                        "Centric delivery: created mirror contact %s for partner %s",
                        child.id,
                        partner.id,
                    )
            elif child and child.active:
                # Delivery address cleared: archive the mirror. We archive rather
                # than delete to avoid breaking existing documents that may still
                # reference it; address_get only scans *active* children, so an
                # archived mirror is correctly ignored for new orders.
                child.write({"active": False})
                _logger.info(
                    "Centric delivery: archived mirror contact %s for partner %s "
                    "(delivery address cleared)",
                    child.id,
                    partner.id,
                )

    # ------------------------------------------------------------------
    # Overrides that keep the mirror in sync
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        if not self.env.context.get("centric_skip_delivery_sync"):
            partners._centric_sync_delivery_child()
        return partners

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("centric_skip_delivery_sync"):
            return result
        # Only resync when a delivery source field actually changed, to avoid
        # unnecessary work on unrelated partner writes.
        if any(field_name in vals for field_name in self._CENTRIC_DELIVERY_SOURCE_FIELDS):
            self._centric_sync_delivery_child()
        return result
