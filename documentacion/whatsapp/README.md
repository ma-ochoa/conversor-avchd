# Documentación externa sobre las bases de WhatsApp

Apuntes de análisis forense de terceros, resumidos aquí para no depender de que esas
páginas sigan en pie. **Cada afirmación está contrastada contra la base real de este
proyecto** (Galaxy S25, WhatsApp 2.26, 611.637 mensajes): lo que no coincide se dice.

| Fuente | Qué aporta |
|---|---|
| [Group-IB — WhatsApp Forensic Artifacts](https://www.group-ib.com/blog/whatsapp-forensic-artifacts/) | Esquema clásico, rutas de avatares, formatos de copia |
| [Belkasoft — Android WhatsApp Forensics Analysis](https://belkasoft.com/android-whatsapp-forensics-analysis) | Esquema moderno: `message_add_on`, citados, reacciones |
| [Belkasoft — Android WhatsApp Acquisition](https://belkasoft.com/android-whatsapp-acquisition) | Qué se puede extraer y qué no, crypt14/15 |

Ficheros: [`esquema.md`](esquema.md) · [`avatares-y-nombres.md`](avatares-y-nombres.md)

## Lo que cambió en el proyecto a raíz de esto

1. **La fusión se dejaba fuera 498.387 filas de contenido.** Belkasoft nombra tablas que
   no estaban contempladas —`message_add_on` (reacciones), `message_thumbnail`,
   `message_mentions`, `message_location`, `message_vcard`, `call_log`, `message_link`…—
   y todas tienen datos aquí. Ver [`esquema.md`](esquema.md).
2. **Se confirma que los avatares no se pueden recuperar.** Las tres fuentes coinciden en
   que viven en `/data/data/com.whatsapp/files/Avatars` y `cache/Profile Pictures/`, o
   sea en almacenamiento privado. Ver [`avatares-y-nombres.md`](avatares-y-nombres.md).

## Dónde la documentación se queda vieja

Group-IB describe el esquema **anterior** de WhatsApp y conviene no seguirlo a ciegas:

| Documentación antigua | Base real de hoy |
|---|---|
| tabla `messages` | tabla `message` |
| `key_remote_jid` (texto) | `chat_row_id` → `chat` → `jid` |
| `remote_resource` | `sender_jid_row_id` → `jid` |
| `data` | `text_data` |
| `media_wa_type` | `message_type` |
| `chat_list` | `chat` |
| `raw_data` (BLOB en el mensaje) | `message_thumbnail.thumbnail` |

Los códigos de `status` sí siguen valiendo: 0 recibido, 4 en cola, 5 entregado, 13 leído.
