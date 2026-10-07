import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monii.auth import register, login, oidc_user
from monii.db import Database
from monii.finance import Finance, minor, next_occurrence
from monii.data_io import preview_import, commit_import, restore_backup, export_csv
from monii.assistant import answer_local


class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(os.environ.get("MONII_TEST_POSTGRES_URL") or Path(self.temp.name) / "test.db")
        self.user = register(self.db, "Ana", f"{uuid4()}@test.invalid", "una frase larga 123")
        self.other = register(self.db, "Luis", f"{uuid4()}@test.invalid", "otra frase larga 456")
        self.f = Finance(self.db, self.user["id"])
        self.g = Finance(self.db, self.other["id"])
        self.a = self.f.create_account("Banco", "Personal", "USD", "1000.00")
        self.b = self.f.create_account("Efectivo", "Personal", "USD")
        self.foreign = self.g.create_account("Privada", "Personal", "USD", "9999.00")

    def tearDown(self):
        if self.db.postgres:
            with self.db.connect(write=True) as conn:
                for uid in (self.user["id"], self.other["id"]):
                    for table in ("transactions", "obligations", "schedules", "goals", "budgets", "accounts", "users"):
                        column = "id" if table == "users" else "user_id"
                        conn.execute(f"DELETE FROM {table} WHERE {column}=?", (uid,))
        self.temp.cleanup()

    def test_money_exact_and_invalid(self):
        self.assertEqual(minor("0.29"), 29)
        self.assertEqual(minor("10,25"), 1025)
        for invalid in ("nan", "inf", "1.001", "1,234.56", "", "1000000000001"):
            with self.assertRaises(ValueError):
                minor(invalid)
        for invalid in ("0", "-1"):
            with self.assertRaises(ValueError):
                minor(invalid, True)

    def test_balance_result_and_persistence(self):
        self.f.add_transaction(self.a, "Ingreso", "200", "2026-01-10", "Salario")
        self.f.add_transaction(self.a, "Gasto", "10.29", "2026-01-11", "Alimentación")
        self.f.add_transaction(self.a, "Transferencia", "50", "2026-01-12", destination_id=self.b)
        reopened = Finance(Database(self.db.location), self.user["id"])
        s = reopened.summary("Personal", "USD", "2026-01")
        self.assertEqual(s["income"], 20000)
        self.assertEqual(s["expense"], 1029)
        self.assertEqual(s["result"], 18971)
        self.assertEqual(s["balance"], 118971)
        self.assertEqual(reopened.summary("Personal", "USD", "2026-02")["result"], 0)
        self.assertEqual(self.g.transactions(), [])

    def test_owner_isolation(self):
        tx = self.f.add_transaction(self.a, "Gasto", "10", "2026-01-01")
        with self.assertRaises(ValueError):
            self.g.delete_transaction(tx, 1)
        with self.assertRaises(ValueError):
            self.f.add_transaction(self.foreign, "Ingreso", "10", "2026-01-01")
        with self.assertRaises(ValueError):
            self.f.add_transaction(self.a, "Transferencia", "10", "2026-01-01", destination_id=self.foreign)
        self.assertEqual(len(self.f.transactions()), 1)
        self.assertEqual(self.g.snapshot()["data"]["transactions"], [])

    def test_currency_transfer_no_mixing(self):
        eur = self.f.create_account("Euros", "Personal", "EUR")
        self.f.add_transaction(self.a, "Transferencia", "100", "2026-01-01", destination_id=eur, destination_amount="90")
        self.assertEqual(self.f.summary("Personal", "USD", "2026-01")["balance"], 90000)
        self.assertEqual(self.f.summary("Personal", "EUR", "2026-01")["balance"], 9000)
        self.assertEqual(self.f.summary("Personal", "EUR", "2026-01")["income"], 0)
        business = self.f.create_account("Empresa", "Empresa", "USD")
        with self.assertRaises(ValueError):
            self.f.add_transaction(self.a, "Transferencia", "10", "2026-01-01", destination_id=business)

    def test_edit_delete_and_stale_version(self):
        ident = self.f.add_transaction(self.a, "Gasto", "10", "2026-01-01")
        changes = dict(account_id=self.a, kind="Gasto", amount="20", when="2026-01-01")
        self.f.edit_transaction(ident, 1, **changes)
        with self.assertRaises(ValueError):
            self.f.edit_transaction(ident, 1, **changes)
        with self.assertRaises(ValueError):
            self.f.delete_transaction(ident, 1)
        self.f.delete_transaction(ident, 2)
        self.assertEqual(self.f.summary("Personal", "USD", "2026-01")["balance"], 100000)

    def test_budgets_goals(self):
        self.f.set_budget("Personal", "USD", "2026-01", "Alimentación", "100")
        self.f.set_budget("Personal", "USD", "2026-01", "Alimentación", "150")
        self.f.add_transaction(self.a, "Gasto", "160", "2026-01-01", "Alimentación")
        s = self.f.summary("Personal", "USD", "2026-01")
        self.assertEqual(len(s["budgets"]), 1)
        self.assertEqual(s["budget_remaining"], -1000)
        goal = self.f.create_goal("Personal", "USD", "Viaje", "500", "10")
        self.f.update_goal(goal, 1, "100")
        with self.assertRaises(ValueError):
            self.g.update_goal(goal, 2, "999")
        with self.assertRaises(ValueError):
            self.f.update_goal(goal, 1, "999")
        self.assertEqual(self.f.summary("Personal", "USD", "2026-01")["balance"], 84000)

    def test_recurring_anchor_and_idempotence(self):
        self.assertEqual(next_occurrence("2026-01-31", "Mensual", 31), "2026-02-28")
        self.assertEqual(next_occurrence("2026-02-28", "Mensual", 31), "2026-03-31")
        sid = self.f.create_schedule(self.a, "Gasto", "9.99", "Suscripciones", "Servicio", "2026-01-31", "Mensual")
        self.assertEqual(self.f.post_schedule(sid, "2026-03-31"), 3)
        self.assertEqual(self.f.post_schedule(sid, "2026-03-31"), 0)
        self.assertEqual(len(self.f.transactions()), 3)
        self.assertEqual(self.f.all("schedules")[0]["next_due"], "2026-04-30")

    def test_concurrent_recurring(self):
        sid = self.f.create_schedule(self.a, "Gasto", "10", "Otros", "Pago", "2026-01-01", "Mensual")
        with ThreadPoolExecutor(max_workers=2) as pool:
            counts = list(pool.map(lambda _: self.f.post_schedule(sid, "2026-01-01"), range(2)))
        self.assertEqual(sum(counts), 1)

    def test_obligation_partial_and_overpayment(self):
        oid = self.f.create_obligation("Personal", "USD", "Por pagar", "Factura", "100", "2026-01-31")
        tx = self.f.settle_obligation(oid, self.a, "40", "2026-01-15")
        self.assertEqual(self.f.obligations()[0]["remaining_minor"], 6000)
        with self.assertRaises(ValueError):
            self.f.settle_obligation(oid, self.a, "61", "2026-01-15")
        with self.assertRaises(ValueError):
            self.g.settle_obligation(oid, self.foreign, "10", "2026-01-15")
        self.f.delete_transaction(tx, 1)
        self.assertEqual(self.f.obligations()[0]["remaining_minor"], 10000)

    def test_concurrent_debt_no_overpayment(self):
        oid = self.f.create_obligation("Personal", "USD", "Por pagar", "Factura", "100", "2026-01-31")
        def pay(_):
            try:
                self.f.settle_obligation(oid, self.a, "80", "2026-01-01")
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(pay, range(2)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.f.obligations()[0]["remaining_minor"], 2000)

    def test_import_dedup_and_atomic_validation(self):
        row = dict(Fecha="2026-01-01", Tipo="Gasto", Monto="12.50", Categoria="Ocio", Concepto="Cine")
        preview, errors = preview_import(self.f, [row, row], self.a)
        self.assertFalse(errors)
        self.assertTrue(preview[1]["duplicate"])
        self.assertEqual(commit_import(self.f, [row, row], self.a), (1, 1))
        self.assertEqual(commit_import(self.f, [row], self.a), (0, 1))
        with self.assertRaises(ValueError):
            commit_import(self.f, [dict(row, Monto="20"), dict(row, Monto="invalid")], self.a)
        self.assertEqual(len(self.f.transactions()), 1)
        with self.assertRaises(ValueError):
            commit_import(self.f, [row], self.foreign)

    def test_import_original_entity_mismatch(self):
        records = [dict(Fecha="2026-01-01", Tipo="Gasto", Monto="10", Entidad="Empresa")]
        preview, errors = preview_import(self.f, records, self.a)
        self.assertTrue(errors)
        self.assertFalse(preview)

    def test_backup_roundtrip_remaps_ownership(self):
        self.f.add_transaction(self.a, "Transferencia", "10", "2026-01-01", destination_id=self.b)
        self.f.set_budget("Personal", "USD", "2026-01", "Otros", "50")
        self.f.create_goal("Personal", "USD", "Meta", "500", "10")
        sid = self.f.create_schedule(self.a, "Gasto", "10", "Otros", "Servicio", "2026-01-01", "Mensual")
        self.f.post_schedule(sid, "2026-01-01")
        oid = self.f.create_obligation("Personal", "USD", "Por cobrar", "Cliente", "100", "2026-01-31")
        self.f.settle_obligation(oid, self.b, "40", "2026-01-01")
        payload = json.dumps(self.f.snapshot()).encode()
        self.assertNotIn(b"password_hash", payload)
        with self.db.connect(write=True) as conn:
            conn.execute("DELETE FROM accounts WHERE id=? AND user_id=?", (self.foreign, self.other["id"]))
        restore_backup(self.g, payload)
        self.assertEqual(self.f.summary("Personal", "USD", "2026-01")["balance"], self.g.summary("Personal", "USD", "2026-01")["balance"])
        self.assertEqual(self.g.obligations()[0]["remaining_minor"], 6000)
        self.assertNotEqual(self.f.transactions()[0]["id"], self.g.transactions()[0]["id"])
        with self.assertRaises(ValueError):
            restore_backup(self.g, payload)

    def test_corrupt_restore_rolls_back(self):
        self.f.add_transaction(self.a, "Gasto", "10", "2026-01-01")
        data = self.f.snapshot()
        data["data"]["transactions"][0]["account_id"] = 999999
        with self.db.connect(write=True) as conn:
            conn.execute("DELETE FROM accounts WHERE id=? AND user_id=?", (self.foreign, self.other["id"]))
        with self.assertRaises(ValueError):
            restore_backup(self.g, json.dumps(data).encode())
        self.assertEqual(self.g.all("accounts"), [])

    def test_authentication_and_lockout(self):
        self.assertIsNotNone(login(self.db, self.user["email"], "una frase larga 123"))
        for _ in range(5):
            self.assertIsNone(login(self.db, self.user["email"], "incorrecta"))
        with self.assertRaises(ValueError):
            login(self.db, self.user["email"], "una frase larga 123")
        with self.db.connect() as conn:
            stored = conn.one("SELECT password_hash FROM users WHERE id=?", (self.user["id"],))["password_hash"]
        self.assertNotIn("una frase larga", stored)

    def test_csv_formula_neutralization(self):
        self.f.add_transaction(self.a, "Ingreso", "10", "2026-01-01", note="=SUM(1,2)")
        self.assertIn("'=SUM", export_csv(self.f).decode("utf-8-sig"))

    def test_assistant_uses_real_month(self):
        self.f.add_transaction(self.a, "Gasto", "12.34", "2026-01-01", "Alimentación")
        answer = answer_local("¿En qué categoría gasté más?", self.f.summary("Personal", "USD", "2026-01"), [])
        self.assertIn("12.34", answer)
        self.assertIn("Alimentación", answer)
        self.assertNotIn("850", answer)

    def test_invalid_date_and_future_transactions(self):
        for when in ("2026-02-31", "01/01/2026", "2999-01-01"):
            with self.assertRaises(ValueError):
                self.f.add_transaction(self.a, "Ingreso", "10", when)
        self.assertEqual(self.f.transactions(), [])


if __name__ == "__main__":
    unittest.main()
