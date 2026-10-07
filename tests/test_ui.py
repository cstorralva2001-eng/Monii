"""UI smoke and end-to-end tests use a temporary SQLite file."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streamlit.testing.v1 import AppTest
from monii.db import Database
from monii.auth import register
from monii.finance import Finance

APP = Path(__file__).resolve().parents[1] / "app.py"


def widget(elements, label):
    return next(item for item in elements if item.label == label)


class UITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DATABASE_URL": str(Path(self.temp.name) / "ui.db"), "MONII_AUTH": "local", "MONII_ENV": "local"})
        self.env.start()
        self.db = Database()
        self.user = register(self.db, "Prueba", "ui@example.invalid", "una clave de prueba 123")
        self.finance = Finance(self.db, self.user["id"])

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def app(self, logged=True):
        at = AppTest.from_file(str(APP), default_timeout=30)
        if logged:
            at.session_state["user"] = self.user
        at.run()
        self.healthy(at)
        return at

    def healthy(self, at):
        self.assertFalse(at.exception, [e.message for e in at.exception])
        self.assertFalse(at.error, [e.value for e in at.error])

    def page(self, at, label):
        at.sidebar.radio[0].set_value(label).run()
        self.healthy(at)

    def test_login_and_logout(self):
        at = self.app(False)
        at.text_input(key="login_email").set_value("ui@example.invalid")
        at.text_input(key="login_password").set_value("una clave de prueba 123")
        widget(at.button, "Entrar").click().run()
        self.healthy(at)
        self.assertEqual(at.title[0].value, "Tu dinero, de un vistazo")
        widget(at.button, "Cerrar sesión").click().run()
        self.healthy(at)
        self.assertEqual(at.title[0].value, "Tu dinero, en orden.")

    def test_registration_creates_real_user(self):
        at = self.app(False)
        widget(at.text_input, "Tu nombre").set_value("Nueva")
        widget(at.text_input, "Correo electrónico").set_value("new@example.invalid")
        widget(at.text_input, "Crea una contraseña").set_value("mi nueva contraseña 123")
        widget(at.text_input, "Repite la contraseña").set_value("mi nueva contraseña 123")
        widget(at.button, "Crear mi cuenta").click().run()
        self.healthy(at)
        self.assertEqual(at.session_state["user"]["name"], "Nueva")

    def test_create_account_transaction_budget_and_pages(self):
        at = self.app()
        self.page(at, "Cuentas")
        widget(at.text_input, "Nombre de la cuenta").set_value("Efectivo")
        widget(at.text_input, "Saldo inicial").set_value("500.00")
        widget(at.button, "Crear cuenta").click().run()
        self.healthy(at)
        self.page(at, "Movimientos")
        at.radio(key="new_kind").set_value("Gasto").run()
        widget(at.text_input, "Monto (USD)").set_value("20.25")
        widget(at.text_input, "Concepto (opcional)").set_value("Compra de prueba")
        widget(at.button, "Guardar movimiento").click().run()
        self.healthy(at)
        self.assertEqual(len(self.finance.transactions()), 1)
        self.page(at, "Inicio")
        self.assertEqual(at.metric[0].value, "USD 479.75")
        self.page(at, "Presupuestos")
        widget(at.text_input, "Límite mensual (USD)").set_value("100")
        widget(at.button, "Guardar presupuesto").click().run()
        self.healthy(at)
        self.assertEqual(len(self.finance.all("budgets")), 1)
        for label in ("Metas", "Pagos y cobros", "Monii", "Tus datos", "Inicio"):
            self.page(at, label)

    def test_all_pages_with_nonempty_data_and_assistant(self):
        aid = self.finance.create_account("Banco", "Personal", "USD", "1000")
        bid = self.finance.create_account("Efectivo", "Personal", "USD")
        self.finance.add_transaction(aid, "Gasto", "15.50", date.today(), "Alimentación", "Compra")
        self.finance.add_transaction(aid, "Transferencia", "25", date.today(), destination_id=bid)
        month = date.today().strftime("%Y-%m")
        self.finance.set_budget("Personal", "USD", month, "Alimentación", "100")
        self.finance.create_goal("Personal", "USD", "Viaje", "500", "50")
        self.finance.create_schedule(aid, "Gasto", "10", "Otros", "Servicio", date.today(), "Mensual")
        self.finance.create_obligation("Personal", "USD", "Por pagar", "Factura", "20", date.today())
        at = self.app()
        for label in ("Movimientos", "Cuentas", "Presupuestos", "Metas", "Pagos y cobros", "Tus datos", "Monii"):
            self.page(at, label)
        at.chat_input[0].set_value("¿En qué categoría gasté más?").run()
        self.healthy(at)
        self.assertIn("15.50", at.session_state["chat_history"][-1]["text"])
        self.page(at, "Inicio")
        at.sidebar.selectbox(key="entity").set_value("Empresa").run()
        self.healthy(at)
        self.assertFalse(at.metric)

    def test_production_requires_oidc_and_postgres(self):
        with patch.dict(os.environ, {"MONII_ENV": "production"}):
            at = AppTest.from_file(str(APP), default_timeout=30).run()
            self.assertFalse(at.exception)
            self.assertTrue(at.error)
            self.assertIn("producción", at.error[0].value)
            self.assertFalse(at.text_input)


if __name__ == "__main__":
    unittest.main()
