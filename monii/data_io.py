"""User-scoped backups and validated transaction imports."""
import csv
import io
import json
from datetime import date
from .auth import now
from .finance import TABLES, KINDS, minor, amount_text, scope, valid_date, month_bounds, clean


def fingerprint(row):
    return tuple(row.get(k) for k in ("account_id", "destination_id", "kind", "amount_minor", "destination_minor", "date", "category", "note"))


def preview_import(finance, records, account_id):
    if not records or len(records) > 5000:
        raise ValueError("El archivo debe contener entre 1 y 5.000 movimientos.")
    accepted, errors = [], []
    seen = {fingerprint(r) for r in finance.all("transactions")}
    with finance.db.connect() as conn:
        default_account = finance.owned(conn, "accounts", account_id)
        accounts = conn.rows("SELECT * FROM accounts WHERE user_id=?", (finance.uid,))
        for line, raw in enumerate(records, 2):
            try:
                row = {str(k).strip(): str(v).strip() if v is not None else "" for k, v in raw.items()}
                if not {"Fecha", "Tipo", "Monto"}.issubset(row):
                    raise ValueError("Faltan columnas Fecha, Tipo o Monto.")
                entity = row.get("Entidad") or default_account["entity"]
                account = default_account
                if row.get("Cuenta"):
                    matches = [a for a in accounts if a["name"] == row["Cuenta"] and a["entity"] == entity]
                    if not matches:
                        raise ValueError("La cuenta indicada no existe en ese espacio. Créala antes de importar.")
                    account = matches[0]
                if account["entity"] != entity:
                    raise ValueError("La entidad no coincide con la cuenta seleccionada.")
                if row.get("Moneda") and account["currency"] != row["Moneda"]:
                    raise ValueError("La moneda no coincide con la cuenta.")
                dest_id = None
                if row["Tipo"] == "Transferencia":
                    dests = [a for a in accounts if a["name"] == row.get("CuentaDestino") and a["entity"] == entity]
                    if not dests:
                        raise ValueError("La cuenta de destino no existe.")
                    dest_id = dests[0]["id"]
                when = row["Fecha"][:10] if len(row["Fecha"]) > 10 and row["Fecha"][10] in (" ", "T") else row["Fecha"]
                values = finance._transaction(conn, account["id"], row["Tipo"], row["Monto"], when, row.get("Categoria") or "Otros", row.get("Concepto") or "", dest_id, row.get("MontoDestino") or None)
                key = fingerprint(values)
                accepted.append({"line": line, "duplicate": key in seen, "values": values})
                seen.add(key)
            except (ValueError, TypeError) as exc:
                errors.append(f"Fila {line}: {exc}")
    return accepted, errors


def commit_import(finance, records, account_id, include_duplicates=False):
    # Revalidate the raw data when committing; never trust a stale UI preview.
    with finance.db.connect(write=True) as conn:
        if finance.db.postgres:
            conn.one("SELECT id FROM users WHERE id=? FOR UPDATE", (finance.uid,))
        preview, errors = preview_import(finance, records, account_id)
        if errors:
            raise ValueError("Corrige todas las filas con errores antes de importar.")
        seen = {fingerprint(r) for r in conn.rows("SELECT * FROM transactions WHERE user_id=?", (finance.uid,))}
        count, skipped = 0, 0
        for row in preview:
            key = fingerprint(row["values"])
            if key in seen and not include_duplicates:
                skipped += 1
                continue
            conn.insert("transactions", row["values"])
            seen.add(key)
            count += 1
        return count, skipped


def export_csv(finance, entity=None):
    output = io.StringIO(newline="")
    columns = ["Fecha", "Tipo", "Monto", "Categoria", "Concepto", "Cuenta", "Moneda", "Entidad", "CuentaDestino", "MontoDestino"]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in finance.transactions(entity=entity):
        writer.writerow(dict(Fecha=row["date"], Tipo=row["kind"], Monto=amount_text(row["amount_minor"]), Categoria=safe_cell(row["category"]), Concepto=safe_cell(row["note"]), Cuenta=safe_cell(row["account"]), Moneda=row["currency"], Entidad=row["entity"], CuentaDestino=safe_cell(row["destination"] or ""), MontoDestino=amount_text(row["destination_minor"]) if row["destination_minor"] is not None else ""))
    return output.getvalue().encode("utf-8-sig")


def safe_cell(value):
    # Prevent spreadsheet formula execution when a CSV is opened in Excel.
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value


def read_backup(payload):
    if len(payload) > 10_000_000:
        raise ValueError("El respaldo supera 10 MB.")
    try:
        backup = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("El archivo no es un respaldo JSON válido.") from None
    if not isinstance(backup, dict) or backup.get("format") != "monii" or backup.get("version") != 1:
        raise ValueError("Formato o versión de respaldo no compatible.")
    data = backup.get("data")
    if not isinstance(data, dict) or set(data) != set(TABLES):
        raise ValueError("El respaldo está incompleto.")
    if any(not isinstance(rows, list) or len(rows) > 50_000 for rows in data.values()):
        raise ValueError("El respaldo contiene demasiados registros o una estructura inválida.")
    for rows in data.values():
        ids = set()
        for row in rows:
            if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0 or row["id"] in ids:
                raise ValueError("El respaldo contiene identificadores inválidos o repetidos.")
            ids.add(row["id"])
    return data


def stored_amount(row, key, positive=False):
    value = row[key]
    if type(value) is not int:
        raise ValueError("El respaldo contiene un monto inválido.")
    return minor(amount_text(value), positive)


def restore_backup(finance, payload):
    """Restore into an empty financial profile, remapping every ID atomically."""
    data = read_backup(payload)
    maps = {table: {} for table in TABLES}
    try:
        with finance.db.connect(write=True) as conn:
            if finance.db.postgres:
                conn.one("SELECT id FROM users WHERE id=? FOR UPDATE", (finance.uid,))
            if any(conn.one(f"SELECT id FROM {table} WHERE user_id=? LIMIT 1", (finance.uid,)) for table in TABLES):
                raise ValueError("La restauración requiere un perfil financiero vacío para evitar sobrescribir tus datos. Usa una cuenta nueva.")
            for table in TABLES:
                for r in data[table]:
                    v = {"user_id": finance.uid}
                    if table == "accounts":
                        scope(r["entity"], r["currency"])
                        v.update(name=clean(r["name"], "Cuenta", 60), entity=r["entity"], currency=r["currency"], opening_minor=stored_amount(r, "opening_minor"), created_at=now())
                    elif table in ("budgets", "goals", "obligations"):
                        scope(r["entity"], r["currency"])
                        v.update(entity=r["entity"], currency=r["currency"])
                        if table == "budgets":
                            month_bounds(r["month"])
                            v.update(month=r["month"], category=clean(r["category"], "Categoría", 60), amount_minor=stored_amount(r, "amount_minor", True))
                        elif table == "goals":
                            saved = stored_amount(r, "saved_minor")
                            if saved < 0:
                                raise ValueError("El ahorro no puede ser negativo.")
                            v.update(name=clean(r["name"], "Meta"), target_minor=stored_amount(r, "target_minor", True), saved_minor=saved, deadline=valid_date(r["deadline"]) if r.get("deadline") else None)
                        else:
                            if r["direction"] not in ("Por pagar", "Por cobrar"):
                                raise ValueError("Tipo de pendiente no válido.")
                            v.update(name=clean(r["name"], "Pendiente"), direction=r["direction"], total_minor=stored_amount(r, "total_minor", True), due=valid_date(r["due"]))
                    elif table == "schedules":
                        if r["kind"] not in ("Ingreso", "Gasto") or r["cadence"] not in ("Semanal", "Mensual", "Anual") or type(r["anchor_day"]) is not int or not 1 <= r["anchor_day"] <= 31 or r["active"] not in (0, 1):
                            raise ValueError("Recurrencia inválida en el respaldo.")
                        v.update(account_id=maps["accounts"][r["account_id"]], kind=r["kind"], amount_minor=stored_amount(r, "amount_minor", True), category=clean(r["category"], "Categoría", 60), note=clean(r["note"], "Concepto", 300), next_due=valid_date(r["next_due"]), cadence=r["cadence"], anchor_day=r["anchor_day"], active=r["active"])
                    else:
                        v = finance._transaction(conn, maps["accounts"][r["account_id"]], r["kind"], amount_text(stored_amount(r, "amount_minor", True)), r["date"], r["category"], r["note"], maps["accounts"].get(r.get("destination_id")), amount_text(stored_amount(r, "destination_minor", True)) if r.get("destination_id") else None)
                        if r.get("schedule_id"):
                            sid = maps["schedules"][r["schedule_id"]]
                            schedule = finance.owned(conn, "schedules", sid)
                            occurrence = valid_date(r["occurrence"])
                            if schedule["account_id"] != v["account_id"] or schedule["kind"] != v["kind"] or occurrence != v["date"]:
                                raise ValueError("El pago recurrente no coincide con su movimiento.")
                            v.update(schedule_id=sid, occurrence=occurrence)
                        if r.get("obligation_id"):
                            oid = maps["obligations"][r["obligation_id"]]
                            obligation = finance.owned(conn, "obligations", oid)
                            account = finance.owned(conn, "accounts", v["account_id"])
                            kind = "Gasto" if obligation["direction"] == "Por pagar" else "Ingreso"
                            if v["kind"] != kind or (account["entity"], account["currency"]) != (obligation["entity"], obligation["currency"]) or r.get("schedule_id"):
                                raise ValueError("El abono no coincide con su pendiente.")
                            paid = conn.one("SELECT COALESCE(SUM(amount_minor),0) AS total FROM transactions WHERE user_id=? AND obligation_id=?", (finance.uid, oid))["total"]
                            if int(paid) + v["amount_minor"] > obligation["total_minor"]:
                                raise ValueError("El respaldo contiene abonos superiores a la deuda.")
                            v["obligation_id"] = oid
                    maps[table][r["id"]] = conn.insert(table, v)
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("El respaldo contiene campos faltantes o referencias inválidas.") from exc
    return sum(len(rows) for rows in data.values())
