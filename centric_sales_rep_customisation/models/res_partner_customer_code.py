from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    centric_customer_code = fields.Char(
        string="Customer Code",
        index=True,
        copy=False,
        help="Unique customer code carried over from the client's previous "
             "system. Searchable from the Contacts search and any customer "
             "selector, so a contact can be found by typing its code.",
    )

    # Extend the fields Odoo uses for partner name search, so typing the code in
    # the Contacts search or any customer field (orders, invoices, ...) finds the
    # contact. Mirrors the base res.partner list plus our field; keep in sync if
    # the base list changes.
    _rec_names_search = [
        "complete_name",
        "email",
        "ref",
        "vat",
        "company_registry",
        "centric_customer_code",
    ]
