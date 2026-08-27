# Paquete `whatsapp`

Copia de seguridad y consulta del WhatsApp de un móvil Android: los medios, la base de
datos de conversaciones y un visor parecido a la app.

**Está escrito para salir de aquí.** Vive dentro del Conversor de vídeo por ahora, pero la
intención es extraerlo como aplicación independiente y, más adelante, migrarlo a .NET. Todo
lo de abajo es consecuencia de eso.

## Capas

```
                    ┌──────────────────────────────────────────┐
   navegador  ────► │ app.py  (rutas /whatsapp, /api/whatsapp) │   ← se reescribe al migrar
                    └────────────────┬─────────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
   ┌─────────┐                 ┌──────────┐                 ┌───────────┐
   │ sync.py │  orquestación   │ chats.py │  consultas      │ galeria.py│  cruce
   │ jobs.py │  (casos de uso) │          │  (repositorio)  │           │  medios↔chats
   └────┬────┘                 └────┬─────┘                 └─────┬─────┘
        │                           │                             │
        ▼                           ▼                             ▼
   ┌──────────┐              ┌──────────────┐              ┌───────────┐
   │ media.py │              │  backup.py   │              │history.py │
   │ (escaneo)│              │(copia+cifrado)│             │ (registro)│
   └────┬─────┘              └──────┬───────┘              └───────────┘
        │                           │
        └───────────┬───────────────┘
                    ▼
            ┌────────────────┐
            │ dispositivo.py │  ← ÚNICO punto que mira fuera del paquete
            └────────────────┘
                    │
                    ▼  from importer import mtp   (gphoto2 / USB)
```

### La regla del paquete

**Ningún fichero salvo `dispositivo.py` importa nada de fuera de `whatsapp/`.**

Si al tocar algo te ves escribiendo `from importer...` o `from converter...`, va en
`dispositivo.py` o no va. Es lo que hace que extraer esto sea cambiar un fichero y no
desenredar dependencias.

| Fichero | Responsabilidad | Al migrar a .NET |
|---|---|---|
| `dispositivo.py` | Hablar con el móvil (USB/MTP) | Sustituir por libmtp/WPD/adb |
| `config.py` | Rutas y ajustes propios | Directo |
| `history.py` | Qué se ha copiado ya | Directo (o a SQLite) |
| `media.py` | Inventario y plan de los ficheros | Directo |
| `backup.py` | Buscar, traer y descifrar la base | `wadecrypt` → librería equivalente |
| `chats.py` | Consultas de lectura (repositorio) | SQL casi idéntico |
| `galeria.py` | Cruce medios ↔ conversaciones | Directo |
| `agenda.py` | Contactos importados de fuera (.vcf / .csv) | Directo |
| `miniaturas.py` | Miniaturas cacheadas de los medios | `ffmpeg` / `sips` → equivalente |
| `sync.py` | Orquestación de la sincronización | Directo; `FASES` es el contrato |
| `jobs.py` | Trabajos en segundo plano | Task/BackgroundService |

## Lo que hay que saber antes de tocar nada

Todo esto está comprobado sobre un Galaxy S25 real con WhatsApp 2.26 y una base de
611.637 mensajes. No es teoría.

1. **La base de datos no se puede leer del móvil directamente.** Vive en el
   almacenamiento privado de la app y ahí no llega nadie sin *root* — no es cuestión de
   permisos, es que cada app corre bajo su propio UID de Linux. Lo que sí sale son las
   copias de seguridad.

2. **Solo sirven las `.crypt15`.** Las `.crypt14` se cifran con una clave que está dentro
   del almacenamiento privado; las `.crypt15` con la clave de 64 dígitos que WhatsApp le
   enseña al usuario. Activar el cifrado de extremo a extremo es lo que hace que WhatsApp
   empiece a escribir `.crypt15`. Ver `backup.py`.

3. **Una clave equivocada no da error.** `wadecrypt` termina con éxito y escribe 150 MB de
   basura. Lo único que distingue un descifrado bueno es que el resultado empiece por la
   firma de SQLite. Ver `backup.descifra()`.

4. **Los nombres pueden no estar en ninguna base.** Se buscan en `wa.db` —otra base que
   WhatsApp guarda en `Backups/`, no en `Databases/`— pero en un Galaxy S25 real esa
   tabla `wa_contacts` estaba **vacía**: WhatsApp lee la agenda del sistema al vuelo en
   vez de copiarla. Y la agenda del sistema no sale por MTP. Por eso existe `agenda.py`,
   que importa un `.vcf` o un CSV de Google y cruza por número.

5. **La copia viene sin índices.** WhatsApp guarda la base con 30 índices pero ninguno
   sobre `message.chat_row_id`. Abrir un chat obligaba a recorrer los 611.637 mensajes:
   listar los chats tardaba **más de dos minutos**. Con `chats.prepara()` baja a **0,03 s**.
   Se crean sobre nuestra copia descifrada, que es un artefacto derivado.

6. **`jid` no es la agenda.** 120.011 filas porque guarda todo identificador que la base
   ha visto; solo 1.569 han escrito alguna vez. Y los `lid` duplican a cada persona.

7. **Los `message_type` no están documentados y WhatsApp sigue inventando.** En una base
   real había seis códigos sin identificar, todos con foto o vídeo. Por eso `tipo_de()`
   usa el **mime** como red de seguridad en vez de fiarse de una lista fija.

8. **Los mensajes eliminados dejan rastro pero no texto.** WhatsApp vacía `text_data` de
   verdad. El **fichero adjunto sí puede sobrevivir** si se había descargado antes: 38 de
   los 1.660 revocados conservan su medio.

9. **La mitad de los medios de la base no están en el móvil.** 98.887 registrados frente a
   53.125 ficheros. WhatsApp libera espacio por su cuenta. La interfaz enseña el hueco.

10. **El nombre del fichero es la llave de todo.** `IMG-20260819-WA0012.jpg` es lo único
    común entre la base y el disco, y es lo que permite cruzar una foto con su
    conversación. Por eso `media.py` **nunca renombra**, al revés que el importador de
    fotos de cámara.

## Dónde se guarda todo

```
~/.conversor-importador/whatsapp/
├── config.json              ajustes (destino, tipos elegidos)
├── copiado.json             registro de medios ya traídos
├── msgstore.db.crypt15      la copia tal cual sale del móvil
├── msgstore.db              descifrada + índices  ← se consulta esta
├── msgstore.anterior.db     la generación anterior (ver HISTORICO.md)
├── wa.db.crypt15 / wa.db    agenda de contactos
└── instantaneas/            recuentos por sincronización
```

Los medios van aparte, a la carpeta que elija el usuario (por defecto
`~/Pictures/WhatsApp`), organizados por tipo / dirección / mes.

## Estado

| Parte | Estado |
|---|---|
| Sincronización de medios | Funciona |
| Descarga y descifrado de la base | Funciona |
| Visor de conversaciones | Funciona |
| Galería por conversación + limpieza | Funciona |
| Contactos | Funciona |
| Mensajes eliminados (marca + interruptor) | Funciona |
| Búsqueda cruzada foto → conversaciones | Funciona, con salto al mensaje |
| Agenda importada (.vcf / CSV) | Funciona |
| Miniaturas cacheadas | Funciona |
| **Fusión acumulativa del histórico** | **Diseñada, sin implementar** — [HISTORICO.md](HISTORICO.md) |
| Guardar la clave con Fernet | Sin empezar |
| Búsqueda de texto en mensajes | Sin empezar |
