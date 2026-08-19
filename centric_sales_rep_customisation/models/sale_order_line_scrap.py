"""Wastage recorded against a sales order line.

Fish is cut to size before it goes out, and what the knife takes off never
reaches the customer: an order for 100 kg of salmon can mean 105 kg leaving the
fridge. Those five kilos are real stock and have to come off the shelf, but
they are not something the customer bought, so they must never reach the
invoice.

That is what a scrap line is. It is an ordinary order line -- same product, its
own quantity, zero price -- carrying ``centric_is_scrap`` and pointing at the
line it belongs to. Being ordinary is the whole trick: Odoo already turns an
order line into a stock move, so the delivery takes the extra kilos out of
stock without a line of inventory code here. The flag only changes two things:
the line is made permanently uninvoiceable, and its price is pinned to zero so
the order total does not move.

Wastage is always entered in kilograms, whatever unit the product is sold in --
see ``_centric_scrap_uom_and_qty`` for how kilograms become a quantity the
stock move can use, and ``centric_scrap_qty_kg`` for the way back.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

#: Label appended to a scrap line's description. It reaches the warehouse too:
#: ``centric_delivery_method_customisation`` copies whatever was typed under the
#: generated description into the move's ``description_picking``, which is also
#: one of the fields Odoo refuses to merge moves on -- so the wastage stays a
#: line of its own on the delivery instead of silently inflating the customer's.
SCRAP_LABEL = "Wastage - not invoiced"

KG_XMLID = "uom.product_uom_kgm"

#: Unit names that mean kilograms.
#:
#: Odoo's own kilogram is called "kg" and hangs off the gram tree. A database
#: that has been through a migration usually has its own instead -- this one
#: sells fish in a unit called "kilo" that sits in a conversion tree of its own,
#: with no relation to ``uom.product_uom_kgm`` whatsoever. No amount of tree
#: walking will ever connect the two, but to everyone using it that unit *is*
#: kilograms, and refusing to record wastage against it would rule out very
#: nearly every product in the catalogue.
KG_NAMES = frozenset({
    "kg", "kgs", "kgm", "kilo", "kilos", "kilogram", "kilograms", "kilogramme",
    "kilogrammes",
})


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    centric_is_scrap = fields.Boolean(
        string="Wastage",
        default=False,
        copy=True,
        help="This line records product lost in preparation. It leaves stock "
             "with the rest of the order but is never invoiced.",
    )
    centric_scrap_line_id = fields.Many2one(
        comodel_name="sale.order.line",
        string="Wastage For",
        ondelete="cascade",
        index="btree_not_null",
        copy=False,
        help="The order line this wastage was recorded against.",
    )
    centric_scrap_ids = fields.One2many(
        comodel_name="sale.order.line",
        inverse_name="centric_scrap_line_id",
        string="Wastage Lines",
    )
    centric_scrap_qty_kg = fields.Float(
        string="Wastage (kg)",
        compute="_compute_centric_scrap_qty_kg",
        digits="Product Unit",
        help="This line's quantity expressed in kilograms.",
    )

    # === UNIT HANDLING === #

    def _centric_kg_uom(self):
        """The Kilogram unit, or an empty recordset if it has been removed."""
        return self.env.ref(KG_XMLID, raise_if_not_found=False) or self.env["uom.uom"]

    def _centric_is_kilogram(self, uom):
        """Whether this unit means kilograms.

        The canonical Kilogram is recognised by its record, anything else by
        its name -- see ``KG_NAMES`` for why the name has to count. The name is
        read in English as well as in the user's language, because a unit
        renamed through a translated interface keeps its English source and
        only one of the two is guaranteed to be the word someone typed.
        """
        if not uom:
            return False
        if uom == self._centric_kg_uom():
            return True
        names = {uom.name, uom.with_context(lang="en_US").name}
        return any(
            (name or "").strip().casefold().rstrip(".") in KG_NAMES
            for name in names
        )

    def _centric_kilogram_uom_for(self, product):
        """The unit to record this product's wastage in, when it has one.

        The product's own selling unit wins, so a line that is already in
        kilograms keeps the unit it had; a packaging unit is only used when the
        product does not sell by weight at all.
        """
        for uom in (product.uom_id, *product.uom_ids):
            if self._centric_is_kilogram(uom):
                return uom
        return self.env["uom.uom"]

    @api.model
    def _centric_uoms_convert(self, from_uom, to_uom):
        """Whether ``from_uom`` can be converted into ``to_uom``.

        ``_has_common_reference`` walks ``parent_path``, which is empty on a
        record that has not been stored yet, so the pair is checked for one
        before asking.
        """
        if not from_uom or not to_uom:
            return False
        if from_uom == to_uom:
            return True
        if not from_uom.parent_path or not to_uom.parent_path:
            return False
        return from_uom._has_common_reference(to_uom)

    @api.model
    def _centric_scrap_uom_and_qty(self, product, qty_kg):
        """Express ``qty_kg`` kilograms as a (unit, quantity) for ``product``.

        Three cases, in order of how faithful they are to what was typed:

        * the product already sells in kilograms (or lists them as an extra
          unit) -- the number is kept exactly as entered;
        * the product sells in another weight unit, grams or tonnes -- the
          kilograms are converted, no information lost;
        * the product sells by unit, box or piece -- there is no conversion
          between a count and a weight, so the product's own weight is the only
          bridge. Without one the wastage cannot be expressed at all, and
          guessing would put a wrong quantity into stock.
        """
        kg = self._centric_kg_uom()
        product_uom = product.uom_id

        kilogram_uom = self._centric_kilogram_uom_for(product)
        if kilogram_uom:
            return kilogram_uom, qty_kg

        if not kg:
            return product_uom, qty_kg

        if self._centric_uoms_convert(kg, product_uom):
            return product_uom, kg._compute_quantity(
                qty_kg, product_uom, round=False, rounding_method="HALF-UP",
            )

        if not product.weight:
            raise UserError(_(
                "%(product)s is sold in %(unit)s, not by weight, and has no "
                "weight set on its product form. Wastage is recorded in "
                "kilograms, so there is no way to tell how much of it that is.\n\n"
                "Set the weight on the product, or add Kilogram as one of its "
                "units, and record the wastage again.",
                product=product.display_name,
                unit=product_uom.display_name,
            ))
        return product_uom, qty_kg / product.weight

    @api.depends("centric_is_scrap", "product_uom_qty", "product_uom_id", "product_id")
    def _compute_centric_scrap_qty_kg(self):
        """The line quantity read back in kilograms -- the inverse of the above.

        Computed rather than stored so that editing the quantity straight in
        the order line list keeps it honest: there is one quantity, and this is
        a different way of looking at it.
        """
        kg = self._centric_kg_uom()
        for line in self:
            product = line.product_id
            uom = line.product_uom_id
            if not line.centric_is_scrap or not product:
                line.centric_scrap_qty_kg = 0.0
            elif self._centric_is_kilogram(uom):
                # The line is already measured in kilograms, whatever this
                # database happens to call them.
                line.centric_scrap_qty_kg = line.product_uom_qty
            elif not kg:
                line.centric_scrap_qty_kg = 0.0
            elif self._centric_uoms_convert(uom, kg):
                line.centric_scrap_qty_kg = uom._compute_quantity(
                    line.product_uom_qty, kg, round=False, rounding_method="HALF-UP",
                )
            else:
                qty = line.product_uom_qty
                if self._centric_uoms_convert(uom, product.uom_id):
                    qty = uom._compute_quantity(
                        qty, product.uom_id, round=False, rounding_method="HALF-UP",
                    )
                line.centric_scrap_qty_kg = qty * product.weight

    # === LINE BEHAVIOUR === #

    def _compute_name(self):
        """Keep the wastage label under the generated description.

        Appended here rather than written once at creation so it survives
        anything that recomputes the description, and so the warehouse note
        stays attached to the line for as long as the line is a scrap line.
        """
        super()._compute_name()
        for line in self:
            name = line.name or ""
            if line.centric_is_scrap and SCRAP_LABEL not in name:
                line.name = f"{name.rstrip()}\n{SCRAP_LABEL}" if name.strip() else SCRAP_LABEL

    def _compute_price_unit(self):
        """Wastage is free.

        Nothing is being sold, so the line must not move the order total, and
        it must stay at zero when the pricelist is reapplied.
        """
        scrap_lines = self.filtered("centric_is_scrap")
        super(SaleOrderLine, self - scrap_lines)._compute_price_unit()
        for line in scrap_lines:
            line = line.with_context(sale_write_from_compute=True)
            line.price_unit = 0.0
            # Kept in step so the "price was edited by hand" guard in the
            # native compute does not read the zero as a manual override.
            line.technical_price_unit = 0.0

    def _compute_qty_to_invoice(self):
        scrap_lines = self.filtered("centric_is_scrap")
        super(SaleOrderLine, self - scrap_lines)._compute_qty_to_invoice()
        scrap_lines.qty_to_invoice = 0.0

    def _compute_invoice_status(self):
        """A scrap line is settled the moment the order is confirmed.

        Leaving it at ``no`` would be the honest-looking answer but it is the
        wrong one: the order status is the *lowest* of its lines, so a single
        never-invoiced line would hold a fully invoiced order open forever.
        """
        scrap_lines = self.filtered("centric_is_scrap")
        super(SaleOrderLine, self - scrap_lines)._compute_invoice_status()
        for line in scrap_lines:
            line.invoice_status = "invoiced" if line.state == "sale" else "no"
