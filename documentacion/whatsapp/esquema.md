# Esquema de `msgstore.db` — qué tabla guarda qué

Recuentos medidos sobre la base real del proyecto (611.637 mensajes, 5.188 chats).
La columna «fusión» dice si el archivo histórico la conserva.

## Núcleo

| Tabla | Filas | Fusión | Qué es |
|---|---:|---|---|
| `message` | 611.637 | sí | Un mensaje por fila. Llave estable: `key_id` |
| `chat` | 5.188 | sí | Una conversación por fila |
| `jid` | 120.011 | sí | Todo identificador visto alguna vez. **No es la agenda** |
| `message_media` | 98.887 | sí | Ruta y metadatos del fichero enviado |
| `message_quoted` | 8.540 | sí | El mensaje al que se responde |
| `message_revoked` | 1.660 | sí | Mensajes eliminados por quien los envió |

## Tablas hijas de `message` (todas por `message_row_id`)

Belkasoft nombra varias que faltaban. Estas son las que **tienen datos aquí**:

| Tabla | Filas | Qué guarda |
|---|---:|---|
| `receipt_user` | 385.853 | Quién recibió y leyó cada mensaje, y cuándo |
| `message_system` | 13.906 | Avisos del sistema («fulano se unió al grupo») |
| `message_link` | 13.375 | Enlaces compartidos |
| `message_add_on` | 12.648 | Reacciones y ediciones. `message_add_on_type`: 56 emoji, 68 fijado, 74 editado |
| `message_forwarded` | 12.341 | Marca de reenviado y cuántas veces |
| `message_add_on_reaction` | 11.519 | El emoji concreto de cada reacción |
| `message_mentions` | 10.243 | Menciones `@` dentro de un mensaje |
| `message_text` | 10.154 | Texto extendido |
| `message_thumbnail` | 8.683 | **Miniatura JPEG incrustada** del mensaje |
| `message_quoted_media` | 8.540 | Miniatura y datos del medio citado |
| `message_system_group` | 3.040 | Cambios de grupo |
| `call_log` | 2.357 | Llamadas de voz y vídeo |
| `message_vcard` | 1.126 | Contactos compartidos |
| `message_vcard_jid` | 899 | Identificadores de esos contactos |
| `message_edit_info` | 861 | Ediciones de mensajes |
| `message_location` | 856 | Ubicaciones compartidas |
| `message_streaming_sidecar` | 583 | Datos de reproducción en curso |
| `message_quoted_text` | 555 | Texto del mensaje citado |
| `message_system_photo_change` | 287 | **Fotos de grupo antiguas y nuevas, en BLOB** |
| `message_ephemeral` | 285 | Mensajes temporales |
| `message_media_interactive_annotation` | 165 | Anotaciones sobre el medio |
| `message_poll_option` | 70 | Opciones de encuesta |
| `message_poll` | 26 | Encuestas |

**El dato importante**: `message_quoted` conserva el contenido de mensajes que después se
borraron, si alguien los había citado. Es de las pocas vías para recuperar un texto
eliminado.

## Columnas BLOB con imagen dentro

Barrido de las 299 tablas buscando firmas de fichero:

| Tabla.columna | Filas | Formato |
|---|---:|---|
| `message_thumbnail.thumbnail` | 8.683 | JPEG |
| `message_quoted_media.thumbnail` | 6.288 | JPEG |
| `media_hash_thumbnail.thumbnail` | 1.757 | PNG |
| `message_quoted_text.thumbnail` | 555 | JPEG |
| `message_system_photo_change.old_photo` | 99 | JPEG |
| `message_system_photo_change.new_photo` | 68 | JPEG |
| `message_quoted_location.thumbnail` | 8 | JPEG |
| `mms_thumbnail_metadata.micro_thumbnail` | 5 | JPEG |

`message_system_photo_change` es lo único parecido a una foto de perfil, y **son solo de
grupos** (los 287 cambios están todos en chats `g.us`): el histórico de «X cambió la foto
del grupo». No hay ni una foto de contacto.

## Correcciones a la documentación publicada

**`key_id` no es único**, aunque las fuentes lo den por identificador único. En esta base
12 de sus 611.637 mensajes comparten `key_id` con otro: son mensajes enviados a varias
conversaciones a la vez (encuestas, difusiones), y cada copia lleva el mismo. La llave
que sí distingue una fila es la pareja **(`key_id`, `chat_row_id`)**.

**Hay mensajes huérfanos.** 503 filas de `message` apuntan con `chat_row_id` a un chat que
no existe. No es corrupción provocada por la copia: vienen así del móvil.

**Los LID no aparecen en la documentación** y hoy son la mitad del tráfico de grupos. Un
remitente llega como `239423019081732@lid`, sin teléfono dentro; la correspondencia con su
número está en **`jid_map`** (`lid_row_id` → `jid_row_id`), 5.827 pares aquí.
