import os
import streamlit as st


def setting(name, default=""):
    if os.getenv(name):
        return os.environ[name]
    try:
        return str(st.secrets.get(name, default))
    except FileNotFoundError:
        return default
