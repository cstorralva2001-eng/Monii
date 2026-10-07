# Validación de la versión entregada

Fecha: 22 de septiembre de 2026. Entorno: Windows, Python 3.12.14, Streamlit 1.64.0, pandas 2.3.3 y SQLite. Versiones instaladas registradas en `requirements-lock.txt`.

## Resultado

- **23 pruebas automatizadas aprobadas**: 18 de reglas financieras, persistencia, identidad y aislamiento, más 5 de interfaz Streamlit.
- Compilación de los módulos Python sin errores.
- `pip check`: sin dependencias incompatibles.
- Comprobación en Chrome de inicio de sesión y dashboard con datos ficticios; sin errores JavaScript registrados.
- Inspección del dashboard a 1440 px y a 390 px. Se ajustaron las tarjetas para mostrar los importes completos; sin desbordamiento horizontal de la página.

## Casos comprobados

- Registro real de usuario, acceso, salida, contraseñas derivadas y bloqueo de intentos fallidos.
- Persistencia al abrir una nueva conexión de base de datos.
- Operaciones de otros usuarios rechazadas, incluidas cuentas y abonos.
- Cálculos exactos con centavos, separación de moneda y espacio.
- Saldos iniciales, resultado mensual y transferencias entre monedas.
- Edición, borrado y rechazo de versiones obsoletas de movimientos.
- Presupuestos por período y metas que no alteran el saldo.
- Fechas de fin de mes y recurrencias sin duplicados, incluso con dos confirmaciones simultáneas.
- Abonos parciales y rechazo de sobrepagos, incluso en concurrencia.
- Validación de importaciones, duplicados y cancelación completa ante errores.
- Restauración con reasignación de identificadores, conservación de relaciones y reversión ante archivos corruptos.
- Respuestas locales a partir de los importes registrados.
- Registro, cuenta, gasto, dashboard, presupuesto y renderizado de todas las secciones con datos.
- Bloqueo del modo de producción cuando faltan PostgreSQL u OIDC.

## Límites de esta validación

No se probó una conexión real a PostgreSQL, un inicio de sesión OIDC ni una respuesta de Gemini: requieren los servicios y credenciales del propietario. Tampoco se hizo una prueba de carga ni una auditoría independiente de seguridad. El soporte de esos servicios está implementado y documentado, pero la publicación debe comprobarse siguiendo `PUBLICAR.md`.

Las pruebas usan bases temporales y datos ficticios. El paquete no contiene usuarios de prueba, contraseñas reales, claves de API ni datos financieros del proyecto original.
