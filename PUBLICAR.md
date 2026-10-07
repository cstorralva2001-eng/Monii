# Publicar Monii para varias personas

El código admite PostgreSQL y OpenID Connect (OIDC). No se ha creado ni publicado ningún servicio externo. El despliegue requiere credenciales y un dominio del propietario.

## 1. Base de datos

Crea un PostgreSQL dedicado con TLS y respaldos automáticos. Guarda su URL en el secreto `DATABASE_URL`, por ejemplo:

```text
postgresql://USUARIO:CLAVE@HOST:5432/monii?sslmode=require
```

La cuenta de servicio necesita permisos para crear las tablas inicialmente y consultar/modificar los registros. Las consultas filtran por usuario; la aplicación usa una cuenta de servicio de base de datos, no roles PostgreSQL por persona. No expongas la base directamente al navegador.

Activa el respaldo y la recuperación del proveedor, define una retención y realiza una prueba de restauración. La descarga JSON de la app es un respaldo individual complementario.

## 2. Identidad

Configura un cliente web OIDC en Google u otro proveedor compatible. Registra exactamente:

```text
https://TU-DOMINIO/oauth2callback
```

El dominio debe ser el mismo que usará la app. Para el registro abierto con Google, configura la audiencia y publica la pantalla de consentimiento del proveedor según sus requisitos. Para un piloto, limita la audiencia a las personas de prueba.

Copia `.streamlit/secrets.example.toml` a un archivo privado `secrets.toml` y completa los valores. En una plataforma gestionada usa su interfaz de secretos. Genera un secreto de cookie, por ejemplo con:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Configura también:

```text
MONII_ENV=production
MONII_AUTH=oidc
```

En producción, Monii se detiene si falta OIDC o PostgreSQL. OIDC identifica al usuario por la pareja estable `iss` + `sub`; no mezcla cuentas por coincidencia de correo. El primer inicio crea automáticamente el perfil vacío. La recuperación de acceso depende del proveedor de identidad.

Documentación oficial: [autenticación de Streamlit](https://docs.streamlit.io/develop/concepts/connections/authentication) y [configuración con Google](https://docs.streamlit.io/develop/tutorials/authentication/google).

## 3. Servidor

Puedes usar un servidor compatible con Python/Streamlit o construir el contenedor incluido:

```text
docker build -t monii .
docker run --rm -p 127.0.0.1:8501:8501 --mount type=bind,source=/RUTA/PRIVADA/secrets.toml,target=/app/.streamlit/secrets.toml,readonly monii
```

Usa una ruta absoluta al archivo privado. El comando es un ejemplo de servidor con Docker, no una instrucción para guardar secretos en el repositorio. El Dockerfile no copia claves, datos ni archivos de pruebas.

Pon un proxy HTTPS delante del servicio y habilita WebSocket. El acceso público debe usar el dominio HTTPS registrado. Mantén una instancia inicialmente; cualquier despliegue con réplicas necesita enrutamiento de sesiones apropiado para Streamlit. Dimensiona la base y prueba la carga esperada antes de crecer.

La configuración local escucha en 127.0.0.1; en un servicio gestionado usa `python -m streamlit run app.py --server.address=0.0.0.0 --server.headless=true`, el puerto indicado por tu plataforma y su terminación HTTPS.

## 4. Verificación del despliegue

1. Entra con dos identidades distintas, cada una en su navegador/sesión.
2. Crea cuentas y operaciones con la primera. Confirma que la segunda no las ve.
3. Reinicia la app y comprueba que los movimientos siguen guardados.
4. Comprueba la transferencia, los límites mensuales y un abono parcial.
5. Descarga un JSON y restáuralo en una identidad de prueba vacía.
6. Verifica el cierre de sesión, redirección OIDC y acceso mediante HTTPS.
7. Comprueba el respaldo de PostgreSQL y su recuperación en un entorno de prueba.

El piloto público sigue requiriendo estos pasos: las pruebas locales no validan las credenciales ni la configuración externa. OIDC, Gemini y PostgreSQL externos no se pueden comprobar sin sus servicios configurados.

## Operación

- Conserva los secretos en el gestor de la plataforma. No los incluyas en Git, archivos ZIP ni imágenes Docker.
- Informa a los usuarios dónde se alojan sus datos y cómo solicitar su exportación o eliminación. Esta versión exporta desde la app; la eliminación completa de una cuenta requiere intervención administrativa en el servidor.
- Los datos no están cifrados por la aplicación en SQLite. Para producción configura el cifrado en reposo del proveedor PostgreSQL y TLS.
- El asistente local no utiliza proveedores externos. Gemini solo se usa cuando el usuario activa el modo y autoriza el envío del resumen.
- Los recordatorios se ven dentro de Monii. No existe un proceso de tareas en segundo plano ni envío por correo/WhatsApp.
- Conserva las versiones de dependencias verificadas y programa actualizaciones con pruebas antes de desplegarlas.
