FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py 1inicio.py ./
COPY monii/ ./monii/
COPY .streamlit/config.toml ./.streamlit/config.toml
RUN useradd --create-home monii && chown -R monii:monii /app
USER monii
ENV MONII_ENV=production MONII_AUTH=oidc PYTHONUNBUFFERED=1
EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')"
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.headless=true"]
