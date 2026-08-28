# Avatares y nombres: por qué no salen de la copia

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
