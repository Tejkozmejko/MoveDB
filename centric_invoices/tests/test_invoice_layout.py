from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestInvoiceLayout(TransactionCase):

    def test_action_opens_the_invoice_version_of_the_chooser(self):
        action = self.env.ref("centric_invoices.action_invoice_layout")
        self.assertEqual(action.res_model, "base.document.layout")
        self.assertEqual(action.target, "new")
        self.assertEqual(action.view_id, self.env.ref("account.view_base_document_layout"))
        self.assertTrue(safe_eval(action.context)["default_from_invoice"])

    def test_menu_is_under_invoicing_for_administrators_only(self):
        menu = self.env.ref("centric_invoices.menu_invoice_layout")
        self.assertEqual(menu.parent_id, self.env.ref("account.menu_finance_configuration"))
        accountant = new_test_user(
            self.env, login="invoice_layout_accountant", groups="account.group_account_manager"
        )
        Menu = self.env["ir.ui.menu"]
        self.assertNotIn(menu.id, Menu.with_user(accountant)._visible_menu_ids())
        self.assertIn(menu.id, Menu.with_user(self.env.ref("base.user_admin"))._visible_menu_ids())

    def test_choosing_a_layout_previews_an_invoice_and_saves_it(self):
        company = self.env.company
        wizard = self.env["base.document.layout"].with_context(default_from_invoice=True).create({})
        self.assertTrue(wizard.from_invoice)
        layout = self.env["report.layout"].search(
            [("view_id", "!=", company.external_report_layout_id.id)], limit=1
        )
        wizard.report_layout_id = layout
        wizard._onchange_report_layout_id()
        self.assertTrue(wizard.preview)
        wizard.document_layout_save()
        self.assertEqual(company.external_report_layout_id, layout.view_id)

    def test_standard_document_layout_is_untouched(self):
        self.assertTrue(self.env.ref("web.action_base_document_layout_configurator").exists())
        self.assertTrue(self.env.ref("account.action_base_document_layout_configurator").exists())
