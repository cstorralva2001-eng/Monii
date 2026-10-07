"""Financial rules. All monetary storage and sums use integer minor units."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from .auth import now

ENTITIES = ("Personal", "Empresa")
CURRENCIES = ("USD", "EUR", "VES", "MXN", "COP")
CATEGORIES = ("Alimentación", "Vivienda", "Transporte", "Salud", "Educación", "Suscripciones", "Ocio", "Cuidado Personal", "Honorarios", "Salario", "Ventas", "Servicios", "Proveedores", "Impuestos", "Otros")
KINDS = ("Ingreso", "Gasto", "Transferencia")
TABLES = ("accounts", "budgets", "goals", "schedules", "obligations", "transactions")


def minor(value, positive=False):
    try:
        number = Decimal(str(value).strip().replace(",", "."))
        if not number.is_finite() or abs(number) > Decimal("1000000000000"):
            raise ValueError("El monto está fuera del rango permitido.")
        cents = number * 100
        if cents != cents.to_integral_value():
            raise ValueError("Usa como máximo dos decimales.")
        if positive and cents <= 0:
            raise ValueError("El monto debe ser mayor que cero.")
        return int(cents)
    except (InvalidOperation, TypeError):
        raise ValueError("Escribe un monto válido, sin separadores de miles.") from None


def money(value, currency="USD"):
    return f"{currency} {Decimal(int(value)) / 100:,.2f}"


def amount_text(value):
    return f"{Decimal(int(value)) / 100:.2f}"


def valid_date(value):
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (ValueError, TypeError):
        raise ValueError("La fecha debe tener el formato AAAA-MM-DD.") from None


def month_bounds(month):
    try:
        start = date.fromisoformat(str(month) + "-01")
        end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
        return start.isoformat(), end.isoformat()
    except ValueError:
        raise ValueError("El mes debe tener el formato AAAA-MM.") from None


def clean(value, label, limit=120, required=True):
    value = str(value).strip()
    if (required and not value) or len(value) > limit:
        raise ValueError(f"{label}: escribe entre {1 if required else 0} y {limit} caracteres.")
    return value


def scope(entity, currency):
    if entity not in ENTITIES or currency not in CURRENCIES:
        raise ValueError("Selecciona un espacio y una moneda válidos.")


def next_occurrence(value, cadence, anchor):
    current = date.fromisoformat(value)
    if cadence == "Semanal":
        return (current + timedelta(days=7)).isoformat()
    if cadence == "Mensual":
        year = current.year + (current.month == 12)
        month = current.month % 12 + 1
    elif cadence == "Anual":
        year, month = current.year + 1, current.month
    else:
        raise ValueError("Frecuencia no válida.")
    return date(year, month, min(anchor, calendar.monthrange(year, month)[1])).isoformat()


class Finance:
    def __init__(self, db, user_id):
        self.db, self.uid = db, int(user_id)

    def owned(self, conn, table, ident, lock=False):
        if table not in TABLES:
            raise ValueError("Tipo de registro no válido.")
        suffix = " FOR UPDATE" if lock and self.db.postgres else ""
        row = conn.one(f"SELECT * FROM {table} WHERE id=? AND user_id=?" + suffix, (ident, self.uid))
        if not row:
            raise ValueError("El registro no existe o no pertenece a tu cuenta.")
        return row

    def all(self, table):
        if table not in TABLES:
            raise ValueError("Tipo de registro no válido.")
        with self.db.connect() as conn:
            return conn.rows(f"SELECT * FROM {table} WHERE user_id=? ORDER BY id", (self.uid,))

    def create_account(self, name, entity, currency, opening="0", conn=None):
        scope(entity, currency)
        values = dict(user_id=self.uid, name=clean(name, "Nombre", 60), entity=entity, currency=currency, opening_minor=minor(opening), created_at=now())
        if conn:
            return conn.insert("accounts", values)
        with self.db.connect(write=True) as conn:
            if conn.one("SELECT id FROM accounts WHERE user_id=? AND entity=? AND name=?", (self.uid, entity, values["name"])):
                raise ValueError("Ya existe una cuenta con ese nombre en este espacio.")
            return conn.insert("accounts", values)

    def rename_account(self, ident, name):
        name = clean(name, "Nombre", 60)
        with self.db.connect(write=True) as conn:
            row = self.owned(conn, "accounts", ident)
            if conn.one("SELECT id FROM accounts WHERE user_id=? AND entity=? AND name=? AND id<>?", (self.uid, row["entity"], name, ident)):
                raise ValueError("Ya existe otra cuenta con ese nombre.")
            conn.execute("UPDATE accounts SET name=? WHERE id=? AND user_id=?", (name, ident, self.uid))

    def _transaction(self, conn, account_id, kind, amount, when, category="Otros", note="", destination_id=None, destination_amount=None, **links):
        account = self.owned(conn, "accounts", account_id)
        if kind not in KINDS:
            raise ValueError("Tipo de movimiento no válido.")
        when = valid_date(when)
        if when > date.today().isoformat():
            raise ValueError("Para fechas futuras, crea un pago recurrente o un pendiente.")
        values = dict(user_id=self.uid, account_id=account["id"], kind=kind, amount_minor=minor(amount, True), date=when, category=clean(category, "Categoría", 60), note=clean(note, "Concepto", 300, False), destination_id=None, destination_minor=None, created_at=now())
        if kind == "Transferencia":
            dest = self.owned(conn, "accounts", destination_id)
            if dest["id"] == account["id"]:
                raise ValueError("Selecciona una cuenta de destino diferente.")
            if dest["entity"] != account["entity"]:
                raise ValueError("Las transferencias deben permanecer en el mismo espacio. Registra aportes o retiros para movimientos entre Personal y Empresa.")
            received = values["amount_minor"] if dest["currency"] == account["currency"] else minor(destination_amount, True)
            values.update(destination_id=dest["id"], destination_minor=received, category="Transferencia")
        for name in ("schedule_id", "occurrence", "obligation_id"):
            if links.get(name) is not None:
                values[name] = links[name]
        return values

    def add_transaction(self, account_id, kind, amount, when, category="Otros", note="", destination_id=None, destination_amount=None):
        with self.db.connect(write=True) as conn:
            values = self._transaction(conn, account_id, kind, amount, when, category, note, destination_id, destination_amount)
            return conn.insert("transactions", values)

    def edit_transaction(self, ident, version, **changes):
        with self.db.connect(write=True) as conn:
            old = self.owned(conn, "transactions", ident, lock=True)
            if old["schedule_id"] or old["obligation_id"]:
                raise ValueError("Este movimiento está vinculado a un pago. Puedes eliminarlo y registrar la corrección.")
            if old["version"] != version:
                raise ValueError("El movimiento cambió en otra sesión. Actualiza la página.")
            values = self._transaction(conn, **changes)
            values.pop("created_at")
            values.pop("user_id")
            columns = ",".join(f"{key}=?" for key in values)
            conn.execute(f"UPDATE transactions SET {columns},version=version+1 WHERE id=? AND user_id=?", (*values.values(), ident, self.uid))

    def delete_transaction(self, ident, version):
        with self.db.connect(write=True) as conn:
            row = self.owned(conn, "transactions", ident, lock=True)
            if row["version"] != version:
                raise ValueError("El movimiento cambió en otra sesión. Actualiza la página.")
            conn.execute("DELETE FROM transactions WHERE id=? AND user_id=?", (ident, self.uid))

    def transactions(self, entity=None, currency=None, start=None, end=None):
        sql = """SELECT t.*,a.name AS account,a.entity,a.currency,d.name AS destination,d.currency AS destination_currency
                 FROM transactions t JOIN accounts a ON a.id=t.account_id AND a.user_id=t.user_id
                 LEFT JOIN accounts d ON d.id=t.destination_id AND d.user_id=t.user_id WHERE t.user_id=?"""
        params = [self.uid]
        for column, value in (("a.entity", entity), ("a.currency", currency), ("t.date >=", start), ("t.date <=", end)):
            if value is not None:
                sql += f" AND {column}{'?' if column.endswith(('>=','<=')) else '=?'}"
                params.append(value)
        with self.db.connect() as conn:
            return conn.rows(sql + " ORDER BY t.date DESC,t.id DESC", params)

    def balances(self):
        # Opening balance + received amounts - sent amounts. Transfers count once per side.
        # One database statement also keeps a concurrent account/transfer consistent.
        with self.db.connect() as conn:
            rows = conn.rows("""SELECT a.*, a.opening_minor + COALESCE(s.total,0) + COALESCE(d.total,0) AS balance_minor
                FROM accounts a
                LEFT JOIN (SELECT account_id,SUM(CASE WHEN kind='Ingreso' THEN amount_minor ELSE -amount_minor END) AS total
                  FROM transactions WHERE user_id=? GROUP BY account_id) s ON s.account_id=a.id
                LEFT JOIN (SELECT destination_id,SUM(destination_minor) AS total FROM transactions
                  WHERE user_id=? AND destination_id IS NOT NULL GROUP BY destination_id) d ON d.destination_id=a.id
                WHERE a.user_id=? ORDER BY a.id""", (self.uid, self.uid, self.uid))
        for row in rows:
            row["balance_minor"] = int(row["balance_minor"])
        return rows

    def summary(self, entity, currency, month):
        scope(entity, currency)
        start, end = month_bounds(month)
        rows = self.transactions(entity, currency, start, end)
        income = sum(t["amount_minor"] for t in rows if t["kind"] == "Ingreso")
        expense = sum(t["amount_minor"] for t in rows if t["kind"] == "Gasto")
        balance = sum(a["balance_minor"] for a in self.balances() if a["entity"] == entity and a["currency"] == currency)
        categories = {}
        for t in rows:
            if t["kind"] == "Gasto":
                categories[t["category"]] = categories.get(t["category"], 0) + t["amount_minor"]
        budgets = [b for b in self.all("budgets") if (b["entity"], b["currency"], b["month"]) == (entity, currency, month)]
        remaining = sum(b["amount_minor"] - categories.get(b["category"], 0) for b in budgets)
        return dict(entity=entity, currency=currency, month=month, income=income, expense=expense, result=income-expense, balance=balance, categories=categories, budgets=budgets, budget_remaining=remaining)

    def set_budget(self, entity, currency, month, category, amount):
        scope(entity, currency)
        month_bounds(month)
        category = clean(category, "Categoría", 60)
        if category == "Transferencia":
            raise ValueError("Las transferencias no forman parte del presupuesto de gastos.")
        amount = minor(amount, True)
        with self.db.connect(write=True) as conn:
            conn.execute("""INSERT INTO budgets(user_id,entity,currency,month,category,amount_minor) VALUES(?,?,?,?,?,?)
                ON CONFLICT(user_id,entity,currency,month,category) DO UPDATE SET amount_minor=excluded.amount_minor""", (self.uid, entity, currency, month, category, amount))

    def delete_simple(self, table, ident):
        if table not in ("budgets", "goals"):
            raise ValueError("Operación no permitida.")
        with self.db.connect(write=True) as conn:
            self.owned(conn, table, ident)
            conn.execute(f"DELETE FROM {table} WHERE id=? AND user_id=?", (ident, self.uid))

    def create_goal(self, entity, currency, name, target, saved="0", deadline=None):
        scope(entity, currency)
        target, saved = minor(target, True), minor(saved)
        if saved < 0:
            raise ValueError("El ahorro acumulado no puede ser negativo.")
        with self.db.connect(write=True) as conn:
            return conn.insert("goals", dict(user_id=self.uid, entity=entity, currency=currency, name=clean(name, "Meta"), target_minor=target, saved_minor=saved, deadline=valid_date(deadline) if deadline else None))

    def update_goal(self, ident, version, saved):
        saved = minor(saved)
        if saved < 0:
            raise ValueError("El ahorro acumulado no puede ser negativo.")
        with self.db.connect(write=True) as conn:
            row = self.owned(conn, "goals", ident, lock=True)
            if row["version"] != version:
                raise ValueError("La meta cambió en otra sesión. Actualiza la página.")
            conn.execute("UPDATE goals SET saved_minor=?,version=version+1 WHERE id=? AND user_id=?", (saved, ident, self.uid))

    def create_schedule(self, account_id, kind, amount, category, note, next_due, cadence):
        if kind not in ("Ingreso", "Gasto") or cadence not in ("Semanal", "Mensual", "Anual"):
            raise ValueError("Tipo o frecuencia no válidos.")
        due = valid_date(next_due)
        with self.db.connect(write=True) as conn:
            self.owned(conn, "accounts", account_id)
            return conn.insert("schedules", dict(user_id=self.uid, account_id=account_id, kind=kind, amount_minor=minor(amount, True), category=clean(category, "Categoría", 60), note=clean(note, "Concepto", 300), next_due=due, cadence=cadence, anchor_day=date.fromisoformat(due).day))

    def toggle_schedule(self, ident, active):
        with self.db.connect(write=True) as conn:
            self.owned(conn, "schedules", ident, lock=True)
            conn.execute("UPDATE schedules SET active=? WHERE id=? AND user_id=?", (int(bool(active)), ident, self.uid))

    def post_schedule(self, ident, through=None):
        through = valid_date(through or date.today())
        if through > date.today().isoformat():
            raise ValueError("No puedes confirmar movimientos futuros.")
        with self.db.connect(write=True) as conn:
            schedule = self.owned(conn, "schedules", ident, lock=True)
            if not schedule["active"]:
                raise ValueError("La recurrencia está pausada.")
            due, count = schedule["next_due"], 0
            while due <= through and count < 60:
                values = self._transaction(conn, schedule["account_id"], schedule["kind"], amount_text(schedule["amount_minor"]), due, schedule["category"], schedule["note"], schedule_id=ident, occurrence=due)
                conn.insert("transactions", values)
                due = next_occurrence(due, schedule["cadence"], schedule["anchor_day"])
                count += 1
            conn.execute("UPDATE schedules SET next_due=? WHERE id=? AND user_id=?", (due, ident, self.uid))
            return count

    def create_obligation(self, entity, currency, direction, name, amount, due):
        scope(entity, currency)
        if direction not in ("Por pagar", "Por cobrar"):
            raise ValueError("Tipo de pendiente no válido.")
        with self.db.connect(write=True) as conn:
            return conn.insert("obligations", dict(user_id=self.uid, entity=entity, currency=currency, direction=direction, name=clean(name, "Descripción"), total_minor=minor(amount, True), due=valid_date(due)))

    def obligations(self):
        with self.db.connect() as conn:
            rows = conn.rows("""SELECT o.*,COALESCE(SUM(t.amount_minor),0) AS settled_minor
                FROM obligations o LEFT JOIN transactions t ON t.obligation_id=o.id AND t.user_id=o.user_id
                WHERE o.user_id=? GROUP BY o.id ORDER BY o.due,o.id""", (self.uid,))
        for row in rows:
            row["remaining_minor"] = row["total_minor"] - int(row["settled_minor"])
        return rows

    def settle_obligation(self, ident, account_id, amount, when):
        with self.db.connect(write=True) as conn:
            obligation = self.owned(conn, "obligations", ident, lock=True)
            account = self.owned(conn, "accounts", account_id)
            if (account["entity"], account["currency"]) != (obligation["entity"], obligation["currency"]):
                raise ValueError("La cuenta debe usar el mismo espacio y moneda que el pendiente.")
            paid = conn.one("SELECT COALESCE(SUM(amount_minor),0) AS total FROM transactions WHERE user_id=? AND obligation_id=?", (self.uid, ident))["total"]
            if minor(amount, True) > obligation["total_minor"] - int(paid):
                raise ValueError("El abono supera el importe pendiente.")
            kind = "Gasto" if obligation["direction"] == "Por pagar" else "Ingreso"
            values = self._transaction(conn, account_id, kind, amount, when, "Otros", obligation["name"], obligation_id=ident)
            return conn.insert("transactions", values)

    def snapshot(self):
        # One consistent snapshot per user. Credentials are never exported.
        with self.db.connect() as conn:
            if self.db.postgres:
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            else:
                conn.execute("BEGIN")
            result = {table: conn.rows(f"SELECT * FROM {table} WHERE user_id=? ORDER BY id", (self.uid,)) for table in TABLES}
        for rows in result.values():
            for row in rows:
                row.pop("user_id", None)
        return {"format": "monii", "version": 1, "exported_at": now(), "data": result}
