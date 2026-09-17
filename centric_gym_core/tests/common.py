from odoo.tests import TransactionCase, new_test_user


class GymCoreCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.Partner = cls.env["res.partner"]
        cls.Assignment = cls.env["gym.pin.assignment"]
        cls.reception = new_test_user(
            cls.env, login="gym_test_reception", groups="centric_gym_core.group_gym_reception"
        )
        cls.manager = new_test_user(
            cls.env, login="gym_test_manager", groups="centric_gym_core.group_gym_manager"
        )
        cls.health_officer = new_test_user(
            cls.env,
            login="gym_test_health",
            groups="centric_gym_core.group_gym_reception,centric_gym_core.group_gym_health",
        )

    def make_member(self, name="Maria Borg", **vals):
        return self.Partner.create({"name": name, "gym_member_state": "member", **vals})

    def set_param(self, key, value):
        self.env["ir.config_parameter"].sudo().set_param(key, value)
