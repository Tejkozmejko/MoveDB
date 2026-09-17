{
    "name": "Centric Invoices",
    "summary": "Choose how your invoices look, with a live invoice preview, from Invoicing > Configuration.",
    "description": """
Adds Invoicing > Configuration > Invoice Layout, which opens Odoo's own layout
chooser in its invoice version: pick a layout (Light, Boxed, Bold, Striped, ...),
font, colours, logo, background, company details, header and footer, and see
the result on a sample invoice. The invoice version also offers the VAT
number, the bank account and the payment QR code.

It changes nothing else. The standard "Configure Document Layout" in Settings
and the layout screen Odoo shows before the first print stay exactly as they
are; this is only a second, easier-to-find way in. The chosen layout is the
company's document layout, so it applies to every printed document, not only
invoices.
""",
    "version": "19.0.1.0.0",
    "category": "Accounting/Accounting",
    "author": "Centric",
    "license": "LGPL-3",
    "depends": ["account"],
    "data": [
        "views/invoice_layout_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
