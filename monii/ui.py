"""Spanish UI. Every page uses the same user-scoped Finance service."""
from datetime import date
import io
import json
import os
import zipfile
import pandas as pd
import streamlit as st
from .finance import CATEGORIES, KINDS, ENTITIES, CURRENCIES, money, amount_text, month_bounds
from .data_io import preview_import, commit_import, export_csv, restore_backup, read_backup
from .assistant import answer_local, answer_gemini

today = date.today


def navigate(page):
    st.session_state.navigation = page


def success(message):
    st.session_state.flash = message
    st.session_state.form_epoch = st.session_state.get("form_epoch", 0) + 1
    st.rerun()


def form_key(name):
    # Retain values on validation errors; reset only after a successful write.
    return f"{name}_{st.session_state.get('form_epoch', 0)}"


def scoped_accounts(finance, entity, currency=None):
    return [a for a in finance.balances() if a["entity"] == entity and (currency is None or a["currency"] == currency)]


def account_picker(label, accounts, key=None):
    lookup = {a["id"]: a for a in accounts}
    return st.selectbox(label, list(lookup), format_func=lambda i: f"{lookup[i]['name']} · {lookup[i]['currency']}", key=key)


def need_account(accounts):
    if accounts:
        return False
    st.info("Crea una cuenta en este espacio y moneda para empezar.")
    st.button("Crear mi primera cuenta", on_click=navigate, args=("Cuentas",), type="primary")
    return True


def display_transactions(rows):
    if not rows:
        st.info("No hay movimientos con estos filtros.")
        return
    data = [{"Fecha": r["date"], "Tipo": r["kind"], "Cuenta": r["account"], "Monto": money(r["amount_minor"], r["currency"]), "Categoría": r["category"], "Concepto": r["note"], "Destino": r["destination"] or "", "Recibido": money(r["destination_minor"], r["destination_currency"]) if r["destination_minor"] else ""} for r in rows]
    st.dataframe(pd.DataFrame(data), hide_index=True, width="stretch")


def home(finance, entity, currency, month):
    st.title("Tu dinero, de un vistazo")
    st.write("Entiende dónde estás y decide tu próximo paso.")
    accounts = scoped_accounts(finance, entity, currency)
    if need_account(accounts):
        return
    s = finance.summary(entity, currency, month)
    cols = st.columns(4)
    for col, label, value in zip(cols, ("Saldo actual", "Ingresos del mes", "Gastos del mes", "Resultado del mes"), (s["balance"], s["income"], s["expense"], s["result"])):
        col.metric(label, money(value, currency))
    st.caption("El saldo incluye los saldos iniciales y todos los movimientos registrados. El resultado corresponde únicamente al mes seleccionado; excluye transferencias.")
    left, right = st.columns(2)
    with left:
        st.subheader("En qué estás gastando")
        if s["categories"]:
            chart = pd.DataFrame({"Categoría": list(s["categories"]), "Gasto": [v / 100 for v in s["categories"].values()]}).set_index("Categoría")
            st.bar_chart(chart, color="#37846a", horizontal=True)
        else:
            st.info("Tus categorías aparecerán cuando registres gastos este mes.")
    with right:
        st.subheader("Tus presupuestos")
        if not s["budgets"]:
            st.write("Asigna un límite a tus categorías para saber cuánto te queda.")
            st.button("Crear presupuesto", on_click=navigate, args=("Presupuestos",))
        for b in s["budgets"]:
            spent = s["categories"].get(b["category"], 0)
            st.write(f"**{b['category']}** · {money(spent, currency)} de {money(b['amount_minor'], currency)}")
            st.progress(min(spent / b["amount_minor"], 1.0))
            if spent > b["amount_minor"]:
                st.warning(f"Superaste el límite por {money(spent - b['amount_minor'], currency)}.")
    pending = [o for o in finance.obligations() if o["entity"] == entity and o["currency"] == currency and o["remaining_minor"] > 0]
    schedules = [r for r in finance.all("schedules") if r["active"] and r["account_id"] in {a["id"] for a in accounts}]
    if pending or schedules:
        st.subheader("Pendientes y próximos pagos")
        for o in pending[:5]:
            label = "Vencido" if o["due"] < today().isoformat() else "Vence"
            st.write(f"{o['direction']} · **{o['name']}** · {money(o['remaining_minor'], currency)} · {label} {o['due']}")
        for r in sorted(schedules, key=lambda x: x["next_due"])[:5]:
            st.write(f"Recurrente · **{r['note']}** · {money(r['amount_minor'], currency)} · {r['next_due']}")
    st.subheader("Últimos movimientos del mes")
    start, end = month_bounds(month)
    display_transactions(finance.transactions(entity, currency, start, end)[:10])


def accounts_page(finance, entity, currency, month):
    st.title("Tus cuentas")
    st.write("Separa efectivo, bancos y billeteras. Cada cuenta conserva su moneda.")
    accounts = scoped_accounts(finance, entity)
    if accounts:
        st.dataframe(pd.DataFrame([{"Cuenta": a["name"], "Moneda": a["currency"], "Saldo inicial": money(a["opening_minor"], a["currency"]), "Saldo actual": money(a["balance_minor"], a["currency"])} for a in accounts]), hide_index=True, width="stretch")
    with st.form(form_key("new_account")):
        st.subheader("Nueva cuenta")
        name = st.text_input("Nombre de la cuenta", placeholder="Ej. Efectivo, Banco, Billetera", max_chars=60)
        new_currency = st.selectbox("Moneda de la cuenta", CURRENCIES, index=CURRENCIES.index(currency))
        opening = st.text_input("Saldo inicial", value="0.00", help="Saldo que tenías antes del primer movimiento que vas a registrar.")
        if st.form_submit_button("Crear cuenta", type="primary"):
            finance.create_account(name, entity, new_currency, opening)
            success("Cuenta creada. Ya puedes registrar movimientos.")
    if accounts:
        with st.expander("Cambiar el nombre de una cuenta"):
            ident = account_picker("Cuenta", accounts, "rename_account")
            with st.form("rename"):
                name = st.text_input("Nuevo nombre", max_chars=60)
                if st.form_submit_button("Guardar nombre"):
                    finance.rename_account(ident, name)
                    success("Nombre actualizado.")
    st.caption("Los saldos iniciales no se modifican después de crear la cuenta. Las correcciones se registran como movimientos para conservar su rastro.")


def transaction_form(finance, entity, currency):
    accounts = scoped_accounts(finance, entity, currency)
    kind = st.radio("Tipo de movimiento", KINDS, horizontal=True, key="new_kind")
    aid = account_picker("Cuenta de origen" if kind == "Transferencia" else "Cuenta", accounts, "new_account_id")
    destination = None
    dest_account = None
    if kind == "Transferencia":
        destinations = [a for a in scoped_accounts(finance, entity) if a["id"] != aid]
        if not destinations:
            st.info("Necesitas otra cuenta en este espacio para transferir.")
            return
        destination = account_picker("Cuenta de destino", destinations, "new_destination")
        dest_account = next(a for a in destinations if a["id"] == destination)
    with st.form(form_key("new_transaction")):
        col1, col2 = st.columns(2)
        with col1:
            amount = st.text_input(f"Monto ({currency})", placeholder="0.00")
            category = st.selectbox("Categoría", CATEGORIES, disabled=kind == "Transferencia")
        with col2:
            when = st.date_input("Fecha", value=today(), max_value=today())
            note = st.text_input("Concepto (opcional)", max_chars=300)
        received = None
        if dest_account and dest_account["currency"] != currency:
            received = st.text_input(f"Monto recibido ({dest_account['currency']})", help="Introduce el importe real recibido. Monii no consulta tasas de cambio.")
        if st.form_submit_button("Guardar movimiento", type="primary"):
            finance.add_transaction(aid, kind, amount, when, category, note, destination, received)
            success("Movimiento guardado y saldos actualizados.")


def edit_panel(finance, rows):
    if not rows:
        return
    lookup = {r["id"]: r for r in rows}
    selected = st.selectbox("Selecciona un movimiento", list(lookup), format_func=lambda i: f"#{i} · {lookup[i]['date']} · {lookup[i]['note'] or lookup[i]['kind']} · {money(lookup[i]['amount_minor'], lookup[i]['currency'])}")
    if st.session_state.get("edit_selected") != selected:
        st.session_state.edit_selected = selected
        st.session_state.edit_snapshot = dict(lookup[selected])
    row = st.session_state.edit_snapshot
    if row["schedule_id"] or row["obligation_id"]:
        st.info("Este movimiento está vinculado a un pago. Para corregirlo, elimínalo y vuelve a registrarlo desde su sección. Eliminar un abono reabre el pendiente; eliminar un recurrente no retrocede su próxima fecha.")
    else:
        with st.form(f"edit_{selected}_{row['version']}"):
            amount = st.text_input("Nuevo monto", value=amount_text(row["amount_minor"]))
            when = st.date_input("Fecha del movimiento", value=date.fromisoformat(row["date"]), max_value=today())
            categories = list(dict.fromkeys([row["category"], *CATEGORIES]))
            category = st.selectbox("Categoría del movimiento", categories, disabled=row["kind"] == "Transferencia")
            note = st.text_input("Concepto del movimiento", value=row["note"], max_chars=300)
            received = st.text_input("Monto recibido en destino", value=amount_text(row["destination_minor"])) if row["destination_id"] else None
            if st.form_submit_button("Guardar cambios"):
                finance.edit_transaction(selected, row["version"], account_id=row["account_id"], kind=row["kind"], amount=amount, when=when, category=category, note=note, destination_id=row["destination_id"], destination_amount=received)
                st.session_state.pop("edit_selected", None)
                success("Movimiento actualizado.")
    confirm = st.checkbox("Confirmo que quiero eliminar este movimiento", key=f"delete_tx_{selected}")
    if st.button("Eliminar movimiento", disabled=not confirm):
        finance.delete_transaction(selected, row["version"])
        st.session_state.pop("edit_selected", None)
        success("Movimiento eliminado; los saldos se recalcularon.")


def movements(finance, entity, currency, month):
    st.title("Movimientos")
    if need_account(scoped_accounts(finance, entity, currency)):
        return
    with st.expander("＋ Registrar movimiento", expanded=True):
        transaction_form(finance, entity, currency)
    st.subheader("Historial")
    all_dates = st.checkbox("Ver todos los meses")
    start, end = (None, None) if all_dates else month_bounds(month)
    rows = finance.transactions(entity, currency, start, end)
    term = st.text_input("Buscar por concepto, categoría o cuenta", placeholder="Ej. supermercado").strip().casefold()
    kind = st.selectbox("Filtrar tipo", ("Todos", *KINDS))
    rows = [r for r in rows if (kind == "Todos" or r["kind"] == kind) and (not term or term in f"{r['note']} {r['category']} {r['account']}".casefold())]
    display_transactions(rows)
    st.caption(f"{len(rows)} movimientos · Moneda de origen {currency}. Las transferencias recibidas en otra moneda se reflejan en Cuentas.")
    with st.expander("Editar o eliminar"):
        edit_panel(finance, rows)


def budgets_page(finance, entity, currency, month):
    st.title("Presupuestos")
    st.write(f"Pon límites claros a tus gastos de {month}.")
    summary = finance.summary(entity, currency, month)
    for b in summary["budgets"]:
        used = summary["categories"].get(b["category"], 0)
        with st.container(border=True):
            st.subheader(b["category"])
            st.write(f"{money(used, currency)} gastados de {money(b['amount_minor'], currency)}")
            st.progress(min(used / b["amount_minor"], 1.0))
            remaining = b["amount_minor"] - used
            st.write(f"{'Disponible' if remaining >= 0 else 'Exceso'}: **{money(abs(remaining), currency)}**")
            if st.button("Quitar presupuesto", key=f"budget_delete_{b['id']}"):
                finance.delete_simple("budgets", b["id"])
                success("Presupuesto eliminado.")
    categories = list(dict.fromkeys([*CATEGORIES, *summary["categories"]]))
    with st.form("budget"):
        st.subheader("Crear o actualizar un límite")
        category = st.selectbox("Categoría", categories)
        amount = st.text_input(f"Límite mensual ({currency})", placeholder="0.00")
        if st.form_submit_button("Guardar presupuesto", type="primary"):
            finance.set_budget(entity, currency, month, category, amount)
            success("Presupuesto actualizado para el mes seleccionado.")
    st.caption("Cada categoría tiene un único límite por mes, espacio y moneda. Guardarla otra vez actualiza ese límite.")


def goals_page(finance, entity, currency, month):
    st.title("Tus metas")
    st.write("Dale un propósito a tu ahorro.")
    st.info("El avance es un seguimiento manual: no retira ni reserva dinero de tus cuentas.")
    goals = [g for g in finance.all("goals") if g["entity"] == entity and g["currency"] == currency]
    for g in goals:
        with st.container(border=True):
            st.subheader(g["name"])
            st.progress(min(g["saved_minor"] / g["target_minor"], 1.0))
            st.write(f"{money(g['saved_minor'], currency)} de {money(g['target_minor'], currency)}")
            if g["deadline"]:
                st.caption(f"Fecha objetivo: {g['deadline']}")
            with st.form(f"goal_update_{g['id']}_{g['version']}"):
                saved = st.text_input("Ahorro acumulado", value=amount_text(g["saved_minor"]))
                if st.form_submit_button("Actualizar avance"):
                    finance.update_goal(g["id"], g["version"], saved)
                    success("Avance actualizado.")
            if st.checkbox("Quiero eliminar esta meta", key=f"goal_confirm_{g['id']}"):
                if st.button("Eliminar meta", key=f"goal_delete_{g['id']}"):
                    finance.delete_simple("goals", g["id"])
                    success("Meta eliminada.")
    with st.form(form_key("goal")):
        st.subheader("Nueva meta")
        name = st.text_input("Nombre de la meta", placeholder="Ej. Fondo de emergencia", max_chars=120)
        target = st.text_input(f"Monto objetivo ({currency})")
        saved = st.text_input("Ya tengo ahorrado", value="0.00")
        deadline = st.date_input("Fecha objetivo (opcional)", value=None)
        if st.form_submit_button("Crear meta", type="primary"):
            finance.create_goal(entity, currency, name, target, saved, deadline)
            success("Meta creada.")


def payments(finance, entity, currency, month):
    st.title("Pagos y cobros")
    accounts = scoped_accounts(finance, entity, currency)
    if need_account(accounts):
        return
    recurring, pending = st.tabs(["Recurrentes", "Por pagar y por cobrar"])
    with recurring:
        st.caption("Los recurrentes son recordatorios internos. Confirma los vencidos para registrarlos; no se ejecutan pagos bancarios ni se envían notificaciones externas.")
        records = [r for r in finance.all("schedules") if r["account_id"] in {a["id"] for a in accounts}]
        for r in records:
            with st.container(border=True):
                st.write(f"**{r['note']}** · {r['kind']} · {money(r['amount_minor'], currency)}")
                st.caption(f"{r['cadence']} · Próxima fecha: {r['next_due']} · {'Activo' if r['active'] else 'Pausado'}")
                c1, c2 = st.columns(2)
                if c1.button("Confirmar vencidos hasta hoy", key=f"post_{r['id']}", disabled=not r["active"] or r["next_due"] > today().isoformat()):
                    count = finance.post_schedule(r["id"])
                    success(f"{count} movimientos registrados. Máximo 60 por confirmación.")
                if c2.button("Pausar" if r["active"] else "Reactivar", key=f"toggle_{r['id']}"):
                    finance.toggle_schedule(r["id"], not r["active"])
                    success("Recurrencia actualizada. Reactivar conserva su próxima fecha pendiente.")
        with st.form(form_key("recurring")):
            st.subheader("Nuevo recurrente")
            note = st.text_input("Concepto recurrente", max_chars=300)
            aid = account_picker("Cuenta del recurrente", accounts)
            kind = st.selectbox("Tipo", ("Gasto", "Ingreso"))
            amount = st.text_input(f"Monto recurrente ({currency})")
            category = st.selectbox("Categoría recurrente", CATEGORIES)
            cadence = st.selectbox("Frecuencia", ("Mensual", "Semanal", "Anual"))
            due = st.date_input("Primera fecha pendiente", value=today())
            if st.form_submit_button("Crear recurrente", type="primary"):
                finance.create_schedule(aid, kind, amount, category, note, due, cadence)
                success("Recurrente creado.")
    with pending:
        st.caption("Control de caja: un pendiente afecta el saldo y los ingresos/gastos solamente cuando registras un abono. No es contabilidad fiscal ni calcula intereses.")
        records = [o for o in finance.obligations() if o["entity"] == entity and o["currency"] == currency]
        show_paid = st.checkbox("Mostrar pendientes liquidados")
        for o in records:
            if not show_paid and o["remaining_minor"] <= 0:
                continue
            with st.expander(f"{o['direction']} · {o['name']} · Restan {money(o['remaining_minor'], currency)}"):
                st.write(f"Total: {money(o['total_minor'], currency)} · Vence: {o['due']}")
                if o["remaining_minor"] > 0:
                    with st.form(f"settle_{o['id']}"):
                        aid = account_picker("Cuenta para el abono", accounts, f"settle_account_{o['id']}")
                        amount = st.text_input("Importe del abono", value=amount_text(o["remaining_minor"]))
                        when = st.date_input("Fecha del abono", value=today(), max_value=today())
                        if st.form_submit_button("Registrar abono"):
                            finance.settle_obligation(o["id"], aid, amount, when)
                            success("Abono registrado. El movimiento ya aparece en tu historial.")
        with st.form(form_key("obligation")):
            st.subheader("Nuevo pendiente")
            direction = st.selectbox("Pendiente", ("Por pagar", "Por cobrar"))
            name = st.text_input("Descripción del pendiente", max_chars=120)
            amount = st.text_input(f"Total pendiente ({currency})")
            due = st.date_input("Vencimiento", value=today())
            if st.form_submit_button("Guardar pendiente", type="primary"):
                finance.create_obligation(entity, currency, direction, name, amount, due)
                success("Pendiente creado.")


def data_page(finance, entity, currency, month):
    st.title("Tus datos")
    st.write("Importa movimientos, exporta tu historial y conserva un respaldo de tu cuenta.")
    imp, backup = st.tabs(["Importar y exportar", "Respaldo y restauración"])
    with imp:
        st.download_button("Descargar historial CSV de este espacio", export_csv(finance, entity), file_name=f"monii-{entity.lower()}.csv", mime="text/csv")
        template = "Fecha,Tipo,Monto,Categoria,Concepto\n2026-01-15,Gasto,12.50,Alimentación,Compra de ejemplo\n"
        st.download_button("Descargar plantilla CSV", template.encode("utf-8-sig"), file_name="plantilla-monii.csv", mime="text/csv")
        st.caption("Columnas obligatorias: Fecha (AAAA-MM-DD), Tipo (Ingreso/Gasto/Transferencia), Monto. Opcionales: Categoria, Concepto, Entidad, Cuenta, Moneda, CuentaDestino y MontoDestino. Importes sin separadores de miles.")
        accounts = scoped_accounts(finance, entity, currency)
        if accounts:
            aid = account_picker("Cuenta predeterminada para el archivo", accounts, "import_account")
            upload = st.file_uploader("Archivo CSV o Excel (.xlsx), máximo 5 MB", type=["csv", "xlsx"])
            if upload:
                raw = upload.getvalue()
                if len(raw) > 5_000_000:
                    st.error("El archivo supera 5 MB.")
                else:
                    try:
                        if upload.name.lower().endswith(".xlsx"):
                            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                                if sum(i.file_size for i in archive.infolist()) > 50_000_000:
                                    raise ValueError("El Excel descomprimido supera el límite permitido.")
                            frame = pd.read_excel(io.BytesIO(raw), dtype=str, keep_default_na=False, nrows=5001)
                        else:
                            frame = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", dtype=str, keep_default_na=False, encoding="utf-8-sig", nrows=5001)
                        records = frame.to_dict("records")
                        preview, errors = preview_import(finance, records, aid)
                        st.dataframe(frame.head(100), hide_index=True, width="stretch")
                        duplicates = sum(r["duplicate"] for r in preview)
                        st.write(f"{len(preview)} filas válidas · {duplicates} posibles duplicados · {len(errors)} errores")
                        for error in errors[:20]:
                            st.error(error)
                        include_duplicates = st.checkbox("Importar también los posibles duplicados", value=False)
                        confirmed = st.checkbox("Revisé los montos, cuentas y monedas de la vista previa")
                        if st.button("Importar movimientos", disabled=bool(errors) or not preview or not confirmed, type="primary"):
                            count, skipped = commit_import(finance, records, aid, include_duplicates)
                            success(f"{count} movimientos importados; {skipped} duplicados omitidos.")
                    except (ValueError, UnicodeDecodeError, zipfile.BadZipFile, pd.errors.ParserError):
                        st.error("No se pudo interpretar el archivo. Usa la plantilla, guarda el CSV en UTF-8 y revisa las fechas y los importes.")
        else:
            st.info("Crea primero una cuenta en este espacio y moneda para importar.")
    with backup:
        payload = json.dumps(finance.snapshot(), ensure_ascii=False, indent=2)
        st.download_button("Descargar respaldo completo de mi cuenta", payload.encode(), file_name=f"monii-respaldo-{today()}.json", mime="application/json")
        st.caption("Incluye ambos espacios, todas las monedas, movimientos, metas, presupuestos y pendientes. No incluye contraseñas. El archivo contiene tus datos financieros; guárdalo en un lugar privado.")
        st.subheader("Restaurar en un perfil vacío")
        st.write("Para evitar sobrescribir movimientos, la restauración solo se permite si este usuario todavía no tiene datos financieros.")
        upload = st.file_uploader("Respaldo de Monii (.json)", type=["json"], key="restore_upload")
        if upload:
            content = upload.getvalue()
            data = read_backup(content)
            st.write({table: len(rows) for table, rows in data.items()})
            confirmed = st.checkbox("Confirmo que este respaldo es mío y quiero restaurarlo")
            if st.button("Restaurar respaldo", disabled=not confirmed):
                count = restore_backup(finance, content)
                success(f"Respaldo restaurado: {count} registros.")


def assistant_page(finance, entity, currency, month):
    st.title("Habla con Monii")
    st.write("Respuestas basadas en tus movimientos, con el espacio, moneda y mes seleccionados.")
    st.caption("Prueba: «¿En qué categoría gasté más?», «¿Cómo va mi presupuesto?» o «¿Me alcanza para comprar algo de 100?».")
    use_ai = st.checkbox("Usar Gemini para preguntas abiertas", value=False)
    consent = False
    if use_ai:
        consent = st.checkbox("Autorizo enviar a Google mi pregunta y el resumen financiero de este período (saldos, totales y categorías)")
        st.caption("No se envían nombres de cuentas ni el listado de movimientos. El texto que escribas sí se comparte. La API puede tener costos.")
    context = (finance.uid, entity, currency, month, use_ai)
    if st.session_state.get("chat_context") != context:
        st.session_state.chat_context = context
        st.session_state.chat_history = []
    if st.button("Limpiar conversación"):
        st.session_state.chat_history = []
        st.rerun()
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["text"])
    question = st.chat_input("Pregúntale a Monii", max_chars=1000, disabled=use_ai and not consent)
    if question:
        summary = finance.summary(entity, currency, month)
        with st.chat_message("user"):
            st.write(question)
        answer = answer_local(question, summary, finance.obligations())
        if use_ai:
            try:
                from .config import setting
                key, model = setting("GEMINI_API_KEY"), setting("GEMINI_MODEL")
                if not key or not model:
                    raise ValueError("Falta configurar GEMINI_API_KEY y GEMINI_MODEL.")
                with st.spinner("Monii está consultando tu resumen…"):
                    answer = answer_gemini(question, summary, key, model)
            except Exception:
                st.warning("Gemini no está disponible o falta configurarlo. Te muestro el resumen local.")
        with st.chat_message("assistant"):
            st.markdown(answer)
        st.session_state.chat_history.extend([{"role": "user", "text": question}, {"role": "assistant", "text": answer}])
        st.session_state.chat_history = st.session_state.chat_history[-20:]
    st.caption("El modo local responde consultas predefinidas sin enviar tus datos fuera del servidor. Cada pregunta se calcula de nuevo; el historial visual no se envía al proveedor.")


PAGES = {"Inicio": home, "Movimientos": movements, "Cuentas": accounts_page, "Presupuestos": budgets_page, "Metas": goals_page, "Pagos y cobros": payments, "Monii": assistant_page, "Tus datos": data_page}
