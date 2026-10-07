# Monii · Finanzas personales y de negocio

Versión actualizada del prototipo en Streamlit. Incluye cuentas independientes por usuario, espacios Personal y Empresa, datos persistentes, transferencias, presupuestos, metas, recurrentes, pendientes, importación y respaldos.

La captura `vista-previa.png` muestra el dashboard con datos ficticios. La instalación comienza vacía, lista para crear tus propias cuentas.

## Empezar en Windows

Requisitos: Python 3.12 o superior y conexión a Internet para instalar dependencias la primera vez. Abre PowerShell en esta carpeta:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

También puedes ejecutar `iniciar.ps1`. Se abrirá http://localhost:8501. El servidor local escucha únicamente en este equipo por defecto.

**Para volver a abrir la app:** después de instalarla, haz doble clic en `Abrir Monii.cmd`. Inicia el servidor en segundo plano y abre el navegador. El enlace local solo funciona mientras el servidor está activo; después de reiniciar el equipo, vuelve a usar ese archivo. Si el inicio falla, consulta `data/servidor.log`.

El iniciador también puede usar el Python incluido en Codex si está instalado en este equipo. Si usas otra instalación, puedes indicar su ruta en la variable `MONII_PYTHON`. Para reproducir las versiones verificadas, instala `requirements-lock.txt`; `requirements.txt` conserva rangos de versiones compatibles.

1. Crea tu usuario con correo y contraseña de al menos 12 caracteres.
2. En **Cuentas**, crea tu banco, efectivo o billetera y registra su saldo inicial.
3. En **Movimientos**, añade un ingreso o gasto.
4. En **Inicio**, verifica el saldo y el resultado mensual. Elige espacio, moneda y mes en el lateral.
5. En **Tus datos**, descarga un respaldo JSON de forma periódica.

Cerrar el navegador no borra los datos: se guardan en `data/monii.db`. El archivo contiene información de todos los usuarios locales y no debe compartirse. La exportación JSON desde la app contiene únicamente los datos del usuario conectado.

`python -m streamlit run 1inicio.py` sigue disponible como entrada alternativa. Esta versión se instala en su propia carpeta; no mezcles las páginas antiguas con el nuevo proyecto.

## Qué incluye

| Sección | Funcionalidad |
|---|---|
| Acceso | Registro y acceso local con contraseñas derivadas mediante PBKDF2, sal individual y bloqueo temporal tras intentos fallidos; integración OIDC para publicar |
| Inicio | Saldo actual, ingresos, gastos, resultado mensual, gastos por categoría, presupuestos y próximos pagos |
| Cuentas | Cuentas en USD, EUR, VES, MXN y COP; saldo inicial; cambio de nombre; espacios Personal/Empresa |
| Movimientos | Ingresos, gastos, transferencias, filtros, búsqueda, edición y eliminación |
| Presupuestos | Límites por mes, categoría, espacio y moneda; progreso y excesos |
| Metas | Objetivo, ahorro acumulado manual y fecha opcional |
| Pagos y cobros | Recurrentes semanales/mensuales/anuales; pausa; confirmación de vencidos; pendientes con abonos parciales |
| Monii | Consultas predefinidas calculadas con datos reales; Gemini opcional con consentimiento |
| Tus datos | Vista previa CSV/Excel, validación, omisión de posibles duplicados, exportación CSV, respaldo JSON y restauración en un perfil vacío |

## Reglas financieras

- Los importes se almacenan en centavos enteros. No se utiliza `float` para cálculos financieros. Se admiten dos decimales y un máximo de un billón por importe.
- El saldo actual incluye el saldo inicial y todas las operaciones. El resultado del mes es ingresos menos gastos de ese mes.
- Las transferencias no afectan los ingresos/gastos. Entre monedas distintas se captura el importe real recibido; no se consulta una tasa externa ni se consolida el patrimonio en una moneda base.
- Las transferencias son entre cuentas del mismo espacio. Un aporte/retiro entre Personal y Empresa se registra como operaciones explícitas de cada espacio.
- El saldo puede ser negativo: representa sobregiros o datos pendientes de completar; no bloquea el registro.
- Las operaciones futuras se manejan como recurrentes o pendientes. Los movimientos confirmados usan fechas hasta hoy, según la fecha del servidor.
- Un pendiente no afecta el saldo hasta que se registra el abono. Los abonos se contabilizan como ingresos/gastos de caja; no hay separación contable de capital e intereses.
- Una meta es seguimiento manual, no una reserva de fondos. Actualizarla no cambia el saldo.
- Confirmar un recurrente registra las fechas vencidas hasta hoy, con un máximo de 60 por clic. Volver a confirmar no duplica los vencimientos ya procesados. Reactivar conserva la fecha pendiente, incluso durante el tiempo pausado.
- Eliminar un abono reabre su pendiente. Eliminar un movimiento recurrente no retrocede la programación: una corrección posterior se registra manualmente.
- El CSV de salida neutraliza las celdas de texto que podrían ejecutar fórmulas en una hoja de cálculo. Para conservar el contenido exacto y los vínculos de pagos usa el respaldo JSON.

## Asistente

El modo local no requiere claves ni hace llamadas externas. Ofrece resúmenes, categoría con más gastos, presupuestos y simulación simple de compras. Usa siempre los filtros laterales; no interpreta automáticamente otros períodos o monedas escritos en la pregunta.

Para habilitar Gemini configura `GEMINI_API_KEY` y `GEMINI_MODEL` como variables de entorno o en `.streamlit/secrets.toml`. Usa un modelo disponible en tu cuenta de Google. La integración usa el endpoint REST oficial y no depende del nombre de modelo del prototipo. No se copió ninguna clave del proyecto anterior.

Cada usuario debe activar el modo Gemini y autorizar el envío. Se envían su pregunta y el resumen agregado; no el listado de movimientos ni los nombres de las cuentas. Las categorías pueden contener texto introducido por el usuario. El historial visual no se envía al modelo, y las respuestas no pueden modificar datos. Si la API falla, aparece el resumen local.

## Publicación

Consulta **PUBLICAR.md**. La aplicación incluye el adaptador PostgreSQL, acceso OIDC y Dockerfile, pero un despliegue público necesita configurar la base de datos, proveedor de identidad, HTTPS y respaldos del servidor. El acceso local no incluye verificación de correo, recuperación de contraseña ni administración de usuarios; para el servicio público se delegan estas funciones al proveedor OIDC.

Cada identidad tiene su propio espacio de datos. No se implementan equipos, invitaciones, colaboradores de una empresa ni roles compartidos. No hay conexiones bancarias, OCR de recibos, pagos bancarios, notificaciones externas, facturación fiscal o funciones sin conexión. La interfaz funciona en el navegador; no es una app nativa ni una PWA instalable.

## Estructura

```text
app.py                 Entrada y acceso
monii/db.py            SQLite / PostgreSQL y esquema
monii/auth.py          Credenciales locales e identidad OIDC
monii/finance.py       Reglas financieras y consultas por usuario
monii/data_io.py       Importación, exportación y restauración
monii/assistant.py     Respuestas locales y Gemini opcional
monii/ui.py            Pantallas
tests/                 Pruebas de reglas, aislamiento e interfaz
.streamlit/            Tema y ejemplo de configuración
```

La versión 1 crea el esquema inicial de forma idempotente. No contiene un sistema de migraciones para futuras alteraciones del esquema; antes de cambiar columnas, crea una migración y un respaldo.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Las pruebas financieras usan bases temporales. Para repetir esas pruebas contra un PostgreSQL de pruebas exclusivo, configura `MONII_TEST_POSTGRES_URL` y ejecuta `python -m unittest discover -s tests -p test_finance.py -v`. No uses una base de producción.

## Migrar el prototipo

El prototipo guardaba movimientos solo en la sesión del navegador. Si aún están disponibles, expórtalos a CSV desde esa sesión antes de cerrarla. No se pueden recuperar datos de sesiones ya perdidas. El importador admite las columnas originales Fecha, Concepto, Tipo, Monto, Categoria y Entidad. Selecciona una cuenta predeterminada del espacio correspondiente; para archivos mixtos crea las cuentas y añade la columna Cuenta.

Para mover esta versión local a una identidad OIDC: exporta el JSON, entra con la identidad nueva en un perfil vacío y restaura el respaldo. Las contraseñas no se migran.
