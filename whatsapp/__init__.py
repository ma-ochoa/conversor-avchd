"""Todo lo de WhatsApp: copia de medios, copia de seguridad de la base de datos y
lectura de las conversaciones.

**Este paquete está pensado para salir de aquí.** La idea es extraerlo tal cual como
aplicación independiente, así que no importa nada de `converter/` ni de `importer/`
salvo por un único fichero: `dispositivo.py`, que es el que habla con el móvil. Todo lo
demás —configuración, registro de lo copiado, trabajos en segundo plano— vive dentro.

Si al tocar algo aquí te ves escribiendo `from importer...` o `from converter...`, va en
`dispositivo.py` o no va.
"""
