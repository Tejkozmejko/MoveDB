# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    @api.model
    def _centric_negative_lot_name(self, product):
        base = (product.default_code or product.name or "PRODUCT").strip()
        return "%s-N" % base

    @api.model
    def _centric_is_negative_lot_name(self, name):
        return (name or "").endswith("-N")

    @api.model
    def _centric_source_lot_expiry(self, product, source_lots):
        """The expiry carried by the real stock this shortfall is drawn from.

        When a move ships 150 of a product that has 100 on hand, those 100 are
        already assigned to the move as real lots by the time the shortfall is
        parked on the ``<code>-N`` bucket. Their date is the authoritative
        answer to "what is the customer actually receiving": the missing 50 are
        the same goods, only not arrived yet, so they must print the same
        expiry as the 100 that went out alongside them.

        Returned separately from the on-hand fallback in
        ``_centric_negative_lot_expiry`` because the two carry different
        weight: this one overwrites whatever the shared bucket happened to be
        holding, the fallback only repairs a missing or already-past date.
        """
        if not product.use_expiration_date:
            return False
        dates = [
            lot.expiration_date
            for lot in (source_lots or self.browse())
            if lot.expiration_date and not self._centric_is_negative_lot_name(lot.name)
        ]
        return max(dates) if dates else False

    @api.model
    def _centric_negative_lot_expiry(self, product, company, source_lots=None):
        """The expiration date a negative-stock lot should carry.

        A ``<code>-N`` lot stands in for stock that has been sold but has not
        arrived yet, so it has no expiry of its own. Left alone, Odoo stamps a
        new lot with ``now() + product.expiration_time`` (product_expiry's
        ``_compute_expiration_date``) — and with no expiration time configured
        on the product that is *right now*, so the lot is born already expired
        and then prints an expired date on the customer's invoice.

        The honest date is the one carried by the stock it stands in for: the
        real lots already assigned on the same move, or failing that whatever is
        on hand for the product. The *latest* of those is used rather than the
        earliest, because the replacement stock is still to arrive — taking the
        earliest would recreate the very problem of shipping something marked
        expired.
        """
        if not product.use_expiration_date:
            return False

        dates = [
            lot.expiration_date
            for lot in (source_lots or self.browse())
            if lot.expiration_date and not self._centric_is_negative_lot_name(lot.name)
        ]
        if not dates:
            quants = self.env["stock.quant"].sudo().search([
                ("product_id", "=", product.id),
                ("location_id.usage", "=", "internal"),
                ("company_id", "in", (False, company.id)),
                ("quantity", ">", 0),
                ("lot_id", "!=", False),
            ])
            dates = [
                quant.lot_id.expiration_date
                for quant in quants
                if quant.lot_id.expiration_date
                and not self._centric_is_negative_lot_name(quant.lot_id.name)
            ]
        return max(dates) if dates else False

    def _centric_refresh_negative_lot_expiry(self, expiry, authoritative=False):
        """Correct a negative-stock lot's expiry.

        The ``-N`` lot is a single bucket reused for the life of the product, so
        one created before there was any stock to copy from would otherwise keep
        its bad date for ever.

        ``authoritative`` marks the date as coming from the real lots on the
        move being processed rather than from the weaker on-hand fallback. That
        date always wins, because the bucket has to describe the goods going out
        *now*: a future date left over from a previous shipment is not wrong in
        the way an expired one is, but it is still not what the customer is
        being handed. Without it, the shared bucket keeps the first plausible
        date it is ever given and later shipments silently print the wrong one.

        For the fallback a future date is still left alone -- it was either
        derived from real stock already or set deliberately by a user, and
        on-hand quants are not evidence about this particular move.
        """
        if not expiry:
            return
        now = fields.Datetime.now()
        for lot in self:
            if lot.expiration_date == expiry:
                continue
            if not authoritative and lot.expiration_date and lot.expiration_date > now:
                continue
            lot.expiration_date = expiry

    @api.model
    def _centric_get_or_create_negative_lot(self, product, company, source_lots=None):
        name = self._centric_negative_lot_name(product)
        lot = self.search(
            [
                ("product_id", "=", product.id),
                ("name", "=", name),
                "|", ("company_id", "=", False), ("company_id", "=", company.id),
            ],
            limit=1,
        )
        expiry = self._centric_source_lot_expiry(product, source_lots)
        authoritative = bool(expiry)
        if not expiry:
            expiry = self._centric_negative_lot_expiry(product, company, source_lots)
        if lot:
            lot._centric_refresh_negative_lot_expiry(expiry, authoritative=authoritative)
            return lot

        vals = {
            "name": name,
            "product_id": product.id,
            "company_id": company.id,
        }
        if expiry:
            vals["expiration_date"] = expiry
        return self.create(vals)
