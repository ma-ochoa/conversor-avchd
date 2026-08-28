# Avatares y nombres: por qué no salen de la copia

> **Los avatares sí se pueden conseguir, pero no de la copia: de WhatsApp Web.** Todo lo
> que sigue sobre el móvil se mantiene —ahí no están—; la vía que sí funciona está al
> final, en «De dónde salen entonces».

Las tres fuentes coinciden, y coincide con lo medido aquí. Este fichero existe para no
volver a buscarlo.

## Dónde están los avatares

| Ruta | Qué hay | ¿Se puede leer? |
|---|---|---|
| `/data/data/com.whatsapp/files/Avatars/` | Miniaturas de perfil (`.j`, en realidad JPEG) | **No** — almacenamiento privado |
| `/data/data/com.whatsapp/cache/Profile Pictures/` | Fotos de contactos | **No** — almacenamiento privado |
| `Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Profile Photos/` | La carpeta clásica en almacenamiento compartido | Sí, pero **está vacía** |

`/data/data/…` es almacenamiento interno: cada app de Android corre bajo su propio usuario
de Linux y el sistema corta la lectura antes de mirar ningún permiso. Ni MTP, ni `adb`, ni
el modo desarrollador cambian eso. Y **no viaja en la copia de seguridad**: las copias
cifradas son bases de datos, no el directorio de la aplicación.

Comprobado en el móvil, además de la carpeta oficial vacía:

- `Android/data/com.whatsapp/files/` → vacía
- `Android/data/com.whatsapp/cache/` → `map_cache.db` (mapas) y bloques de caché
- `WhatsApp/.Thumbs` → vacía
- `WhatsApp/.Links` → miniaturas de previsualización de enlaces
- `WhatsApp/.Shared` → temporales cifrados de transferencias

Lo único con imágenes de perfil dentro de la base es `message_system_photo_change`
(287 filas), y **son fotos de grupo**, no de personas.

> **Cuidado con la confusión de nombres**: `Android/data/com.whatsapp/` (almacenamiento
> externo de la app) **sí** se ve por USB, y no es lo mismo que `/data/data/com.whatsapp/`
> (interno privado), que no. Haber podido mirar la primera no significa poder leer la
> segunda.

## Dónde están los nombres

La documentación dice —correctamente— que los nombres viven en `wa.db`, tabla
`wa_contacts`, columnas `display_name` y `wa_name`, y que se cruzan con `ATTACH DATABASE`.
**Esta aplicación ya lo hace** (`chats.py::_nombres_wa_db`, probando también `given_name`
y `nickname` porque WhatsApp ha ido cambiando las columnas).

El problema es que **aquí esa tabla viene vacía**:

```
wa_contacts:            0 filas   (y tiene la columna display_name)
wa_contact_details:     0 filas
wa_org_contacts:        0 filas
… las 25 tablas de contactos de wa.db: 0 filas
wa_trusted_contacts:  208 filas   ← esta sí trae datos
PRAGMA integrity_check: ok
```

Que `wa_trusted_contacts` tenga 208 filas y el `integrity_check` pase demuestra que **no
es un descifrado defectuoso**: la base está bien y la tabla está vacía. WhatsApp moderno
lee la agenda del sistema al vuelo en vez de copiarla a `wa.db`.

El *push name* —el `~Mariina` que WhatsApp enseña cuando no tienes a alguien en la
agenda— tampoco está: buscado ese nombre concreto por las 299 tablas de `msgstore.db` y
las 95 de `wa.db`, no aparece ni una vez.

**Conclusión**: la agenda importada de fuera (vCard o CSV) no es un apaño, es la única
fuente de nombres disponible. Para los remitentes con LID, el número se recupera por
`jid_map` y con él se busca en esa agenda.

## Otras bases que menciona la documentación

| Base | Qué tiene | ¿Está en la copia? |
|---|---|---|
| `msgstore.db` | Mensajes | Sí (`msgstore.db.crypt15`) |
| `wa.db` | Contactos | Sí (`wa.db.crypt15`), pero vacía de contactos |
| `axolotl.db` | Claves de cifrado e identidad | No |
| `chatsettings.db` | Ajustes | Parcial: `chatsettingsbackup.db.crypt15` en `Backups/` |
| `companion_devices.db` | Dispositivos vinculados | No |
| `shared_prefs/com.whatsapp_preferences_light.xml` | Teléfono registrado, cuenta de Google | No |

Las que faltan viven en el directorio privado de la aplicación, igual que los avatares.


---

# De dónde salen entonces: WhatsApp Web

La lista de chats de WhatsApp Web pinta las fotos, y de ahí sí se pueden leer. Está
implementado en `whatsapp/avatares.py` y `static/wa_extractor.js`.

## Lo que costó descubrir

**Los avatares no son `<img>`.** Son elementos `<image>` **dentro de un `<svg>`** con una
máscara circular:

```html
<svg height="48" width="48">
  <mask id="…"><circle cx="50%" cy="50%" r="calc(50% - 0px)"/></mask>
  <g mask="url(#…)"><image xlink:href="https://media-…cdn.whatsapp.net/v/t61…"/></g>
</svg>
```

`querySelectorAll('img')` no los encuentra —`<image>` de SVG es otro elemento— y devuelve
solo las dos o tres imágenes sueltas de la interfaz. En la cuenta de prueba eso daba
**1 de 73**, lo que parecía «casi nadie tiene foto» cuando en realidad la tenían todos.

## Las URLs se descargan sin sesión

Comprobado con `curl` sin cookies, sin *referer* y con user-agent de curl: **200 y JPEG
válido**. La autorización va en la propia URL —`oh` es la firma y `oe` la caducidad, con
unos **10 días** de margen—, no en la sesión. Por eso las descarga el servidor en Python
y no hace falta automatizar el navegador.

Cuidado con confundirlas: la foto **grande** que se ve al pinchar el avatar sí es un
`blob:https://web.whatsapp.com/…`, que solo existe dentro de esa pestaña. Pegar *esa* URL
en una ventana de incógnito lleva al código QR, y hace pensar que hace falta sesión.

**No se puede pedir más resolución tocando la URL.** El parámetro `stp` la lleva dentro
(`dst-jpg_s96x96_tt6`), pero cambiarlo a `s640x640` devuelve **403**: la firma lo cubre.

| Vía | Resolución | Coste |
|---|---|---|
| Lista de chats y buscador | 96×96 (~2,8 KB) | Gratis, sin abrir nada |
| Panel de info del contacto | 640×640 (~35 KB) | Un clic **por contacto** |

## La lista de chats no basta

WhatsApp Web solo sincroniza los chats recientes (en la cuenta de prueba, hasta feb-2025).
Pero **el buscador filtra por «contiene»**, así que buscando las vocales y `+34` asoman los
contactos sin conversación reciente. El efecto medido:

| Paso | Avatares |
|---|---|
| Solo la lista de chats | 410 |
| Barrido por letras | 710 |
| Con el scroll bajando **hasta el fondo** | **1.045** |

El salto final importa: la lista está virtualizada y los **contactos aparecen después de
los chats**, así que un bucle de scroll con tope de pantallas se queda a mitad y nunca
llega a ellos.

## El casado

El jid **no aparece en el DOM**, así que se cruza por el nombre visible, normalizado sin
acentos ni signos, contra `chat.subject` y la agenda importada. Quien no está en la agenda
sale con su propio número por nombre, y esos se casan por teléfono.

Resultado sobre la cuenta de prueba: **907 emparejados de 1.045 (87%)**. El resto son el
perfil propio, servicios y empresas sin conversación.
