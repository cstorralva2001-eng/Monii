"""Monii entry point: python -m streamlit run app.py"""
import logging
import os
from pathlib import Path
import streamlit as st
from monii.auth import login, register, oidc_user
from monii.db import Database
from monii.finance import Finance, ENTITIES, CURRENCIES
from monii import ui
from monii.config import setting

st.set_page_config(page_title="Monii · Tu dinero, en orden", page_icon="🌱", layout="wide", initial_sidebar_state="auto")
st.markdown("""<style>
.stApp {background: #f6f8f5;}
[data-testid="stSidebar"] {background:#eaf0e8;}
[data-testid="stMetric"] {background:white;border:1px solid #dfe7df;border-radius:14px;padding:18px;}
[data-testid="stMetricValue"] {font-size:clamp(1rem,1.6vw,1.6rem);}
[data-testid="stMetricValue"] > div {white-space:normal;overflow-wrap:anywhere;}
.block-container {max-width:1240px;padding-top:4rem;padding-bottom:3rem;}
h1,h2,h3 {color:#183c31;}
.monii-brand {font-size:2rem;font-weight:800;letter-spacing:-1px;color:#205c47;}
button[kind="primary"] {border-radius:10px;}
@media(max-width:640px) {.block-container {padding-left:1rem;padding-right:1rem;}}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def database(location):
    return Database(location)


def signed_out():
    st.markdown('<div class="monii-brand">monii 🌱</div>', unsafe_allow_html=True)
    st.title("Tu dinero, en orden.")
    st.write("Un solo lugar para tus cuentas, gastos, metas y negocio.")


def authenticate(db, mode):
    if mode == "oidc":
        if not st.user.is_logged_in:
            signed_out()
            st.button("Entrar o crear cuenta", on_click=st.login, type="primary")
            st.caption("El acceso y la recuperación de tu cuenta se gestionan con el proveedor de identidad.")
            st.stop()
        return oidc_user(db, dict(st.user))
    if st.session_state.get("user"):
        return st.session_state.user
    signed_out()
    st.caption("Acceso local · Tus datos se guardan en esta instalación de Monii.")
    enter, signup = st.tabs(["Iniciar sesión", "Crear cuenta"])
    with enter:
        with st.form("login"):
            email = st.text_input("Correo", key="login_email", max_chars=254)
            password = st.text_input("Contraseña", type="password", key="login_password", max_chars=128)
            submit = st.form_submit_button("Entrar", type="primary")
        if submit:
            try:
                user = login(db, email, password)
                if user:
                    st.session_state.clear()
                    st.session_state.user = user
                    st.rerun()
                st.error("Correo o contraseña incorrectos.")
            except ValueError as exc:
                st.error(str(exc))
    with signup:
        with st.form("signup"):
            name = st.text_input("Tu nombre", max_chars=80)
            email = st.text_input("Correo electrónico", max_chars=254)
            password = st.text_input("Crea una contraseña", type="password", help="Entre 12 y 128 caracteres.", max_chars=128)
            confirm = st.text_input("Repite la contraseña", type="password", max_chars=128)
            submit = st.form_submit_button("Crear mi cuenta", type="primary")
        if submit:
            try:
                if password != confirm:
                    raise ValueError("Las contraseñas no coinciden.")
                user = register(db, name, email, password)
                st.session_state.clear()
                st.session_state.user = user
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.stop()


def main():
    mode = setting("MONII_AUTH", "local")
    production = setting("MONII_ENV", "local") == "production"
    location = setting("DATABASE_URL", str(Path(__file__).parent / "data" / "monii.db"))
    if mode not in ("local", "oidc"):
        st.error("MONII_AUTH debe ser local u oidc.")
        st.stop()
    if production and (mode != "oidc" or not location.startswith(("postgres://", "postgresql://"))):
        st.error("Para producción configura MONII_AUTH=oidc y DATABASE_URL con PostgreSQL. Consulta PUBLICAR.md.")
        st.stop()
    if mode == "oidc":
        try:
            configured = all(st.secrets["auth"].get(key) for key in ("redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url"))
        except (KeyError, FileNotFoundError):
            configured = False
        if not configured:
            st.error("Falta configurar el proveedor de acceso en .streamlit/secrets.toml. Consulta PUBLICAR.md.")
            st.stop()
    try:
        db = database(location)
    except Exception:
        st.error("No se pudo abrir la base de datos. Revisa la configuración y la conectividad.")
        st.stop()
    user = authenticate(db, mode)
    finance = Finance(db, user["id"])
    with st.sidebar:
        st.markdown('<div class="monii-brand">monii 🌱</div>', unsafe_allow_html=True)
        st.caption(f"Hola, {user['name']}")
        entity = st.selectbox("Espacio", ENTITIES, key="entity")
        currency = st.selectbox("Moneda", CURRENCIES, key="currency")
        month_date = st.date_input("Mes de análisis", value=ui.today().replace(day=1), key="month")
        month = month_date.strftime("%Y-%m")
        st.button("＋ Añadir movimiento", on_click=ui.navigate, args=("Movimientos",), width="stretch", type="primary")
        section = st.radio("Tu Monii", list(ui.PAGES), key="navigation", label_visibility="collapsed")
        st.divider()
        st.caption("Almacenamiento: PostgreSQL" if db.postgres else "Almacenamiento: este equipo")
        if st.button("Cerrar sesión", width="stretch"):
            st.session_state.clear()
            if mode == "oidc":
                st.logout()
            st.rerun()
    if message := st.session_state.pop("flash", None):
        st.success(message)
    st.caption(f"{entity.upper()} / {currency} / {month}")
    try:
        ui.PAGES[section](finance, entity, currency, month)
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        # Avoid exposing DSNs, credentials, or financial payloads in UI and logs.
        logging.error("Monii operation failed: %s", type(exc).__name__)
        st.error("No se pudo completar la operación. Tus cambios no confirmados no se guardaron. Actualiza e inténtalo de nuevo.")


if __name__ == "__main__":
    main()
