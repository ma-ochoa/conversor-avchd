# Fusión acumulativa — fase 2

> **Estado: implementado en `archivo.py`.** Se fusiona sola tras cada descifrado. Lo que
> sigue describe el diseño; al final, en «Lo que cambió al escribirlo», está lo que se
> demostró falso al llevarlo a la práctica — que no es poco.

## El problema

La copia del ordenador **no debe ser un espejo del móvil, sino un histórico**.

El móvil se limpia: se borran conversaciones enteras, grupos y fotos para liberar espacio.
La sincronización trae la base tal como está *ahora*, así que la copia de la vuelta N+1
puede contener **menos** que la de la vuelta N. Sobrescribir sin más iría destruyendo el
archivo poco a poco, y justo en el material más antiguo — el que más interesa conservar.

```
vuelta 1:  msgstore.db  →  611.637 mensajes,  5.188 chats
           (el usuario borra 3 grupos y un año de fotos para hacer sitio)
vuelta 2:  msgstore.db  →  480.000 mensajes,  5.185 chats
                            ↑ sobrescribir aquí = perder 131.637 mensajes para siempre
```

## Qué ya está resuelto (fase 1)

| Pieza | Dónde | Qué hace |
|---|---|---|
| Registro de medios | `history.py` | Solo apunta lo copiado; **nunca se poda** contra lo que hay hoy en el móvil. Un archivo borrado del teléfono sigue en el ordenador y en el registro. |
| Generación anterior | `config.ANTERIOR` | Antes de traer una base nueva, la descifrada actual se aparta a `msgstore.anterior.db`. |
| Instantáneas | `config.INSTANTANEAS` | Un JSON por sincronización con los recuentos (mensajes, chats, medios, eliminados). Permite ver *qué* desapareció sin guardar 330 MB por vuelta. |

Con eso, cuando se implemente la fusión habrá **dos generaciones reales** contra las que
programarla y probarla, en vez de tener que hacerlo a ciegas.

## Diseño de la fusión

### La llave de identidad

`message.key_id` es el identificador que asigna WhatsApp a cada mensaje y **es estable
entre copias**: el mismo mensaje tiene el mismo `key_id` en la vuelta 1 y en la 2. Es la
llave natural para la unión.

`message._id` **no sirve**: es un autonumérico local que WhatsApp reasigna al restaurar.

Para el resto de tablas:

| Tabla | Llave estable | Nota |
|---|---|---|
| `message` | `key_id` | Único global |
| `chat` | `jid.raw_string` del `jid_row_id` | El `_id` del chat cambia |
| `jid` | `raw_string` | |
| `message_media` | `message_row_id` → resolver vía `key_id` | |
| `message_revoked` | `revoked_key_id` | |
| `message_quoted` | `message_row_id` → vía `key_id` | |

### El algoritmo

```
archivo = base acumulada (la que se conserva y crece)
nueva   = base recién traída del móvil

1. Reindexar `nueva` por key_id.
2. Para cada chat de `nueva` que no esté en `archivo` (por raw_string): insertarlo.
3. Para cada mensaje de `nueva` cuyo key_id no esté en `archivo`: insertarlo,
   remapeando chat_row_id y sender_jid_row_id a los ids de `archivo`.
4. NUNCA borrar de `archivo` lo que no aparezca en `nueva`: esa es la razón de existir
   de todo esto.
5. Registrar en la instantánea qué había en `archivo` y ya no está en `nueva`
   («desaparecido del móvil el <fecha>»), que es información útil por sí misma.
```

La dirección importa: se **añade** de la nueva al archivo, nunca al revés.

### Marcar lo desaparecido

Además de no borrar, conviene **saber** qué se fue. Una columna añadida por nosotros en
el archivo (`wa_visto_por_ultima_vez`, con la fecha de la última sincronización en que el
mensaje seguía en el móvil) permitiría luego:

- enseñar en el visor «esta conversación ya no está en tu teléfono»;
- distinguir un mensaje que nunca tuvimos de uno que tuvimos y el móvil perdió;
- decidir con criterio qué medios locales conviene conservar.

Como es una columna nuestra sobre una base ajena, va con prefijo `wa_` igual que los
índices de `chats.py`, para que se distinga a simple vista de lo que trae WhatsApp.

## Lo que hay que verificar antes de escribir nada

Estas son las preguntas abiertas. **Ninguna se puede contestar razonando: hay que borrar
cosas en el móvil de verdad, sincronizar y comparar.**

1. **Al borrar una conversación en el móvil, ¿desaparece la fila de `chat` o se queda
   marcada?** Hay columnas candidatas (`hidden`, `participation_status`) que podrían
   indicar «borrada» en vez de eliminarse la fila. Cambia el algoritmo por completo:
   si se marca, basta leer la marca; si se borra, hay que deducirlo por ausencia.

2. **¿Se borran los mensajes de esa conversación, o quedan huérfanos?** Determina si hace
   falta recorrer `message` o basta con `chat`.

3. **Al borrar solo *fotos* dentro de un chat (liberar espacio), ¿desaparece la fila de
   `message_media` o solo se vacía `file_path`?** Es la diferencia entre perder la
   referencia y conservarla. Sospecha razonable: se conserva la fila y se marca
   `transferred = 0`, porque WhatsApp sabe volver a descargar del servidor.

4. **¿`key_id` se conserva de verdad entre una copia y otra?** Es la premisa de todo el
   diseño. Se comprueba fácil: dos copias seguidas sin tocar nada, y cruzar.

5. **¿Qué pasa con los grupos de los que uno sale?** ¿Se conserva el historial o se poda?

### Cómo verificarlo sin arriesgar nada

El material para responderlas ya se está guardando:

```bash
# tras dos sincronizaciones con borrados en medio
python3 - <<'EOF'
import sqlite3
a = sqlite3.connect("~/.conversor-importador/whatsapp/msgstore.anterior.db")
b = sqlite3.connect("~/.conversor-importador/whatsapp/msgstore.db")
ka = {r[0] for r in a.execute("SELECT key_id FROM message")}
kb = {r[0] for r in b.execute("SELECT key_id FROM message")}
print("solo en la anterior (desaparecidos del móvil):", len(ka - kb))
print("solo en la nueva (nuevos):", len(kb - ka))
EOF
```

Si `len(ka - kb)` sale 0 tras borrar una conversación a mano, la respuesta a (1) es
«se marca, no se borra». Si sale igual al número de mensajes de esa conversación, se
borra de verdad y la fusión es imprescindible.

## Por qué no se implementa ya

Escribir una fusión sin conocer las respuestas de arriba daría un algoritmo que *parece*
correcto y corrompe el archivo en silencio la primera vez que WhatsApp haga algo distinto
de lo supuesto. Y el archivo es justamente lo que no se puede perder: es la única copia de
lo que ya no está en el móvil.

Mientras tanto, **no se destruye nada**, que es la parte que sí importa tener hoy.


---

# Lo que cambió al escribirlo

El diseño de arriba se escribió sin probarlo. Al implementarlo, tres cosas resultaron
distintas, y las tres se descubrieron ejecutando, no razonando.

## 1. `key_id` NO es único

Arriba dice «Único global». No lo es: en la base de prueba, **12 de sus 611.637 mensajes
comparten `key_id`** con otro. Son mensajes enviados a varias conversaciones a la vez
—encuestas y difusiones—, y cada copia lleva el mismo identificador.

Con `key_id` como llave, el mapa de equivalencias reventaba por clave duplicada. La llave
real es la pareja **(`key_id`, `chat_row_id`)**: cada copia del mensaje en su conversación
es una fila distinta, que es lo que de verdad son.

## 2. Hay mensajes sin conversación

**503 filas de `message` apuntan a un `chat_row_id` que no existe.** Vienen así del móvil,
no las produce la copia. Al fusionar no tienen dónde ir, y con un `JOIN` normal tumbaban
la inserción por `NOT NULL`.

Se descartan al insertar y se cuentan (`mensajes_sin_conversacion`). Y hay un efecto
secundario que costó ver: como no entran en el mapa, el sellado no los alcanzaba y salían
marcados como desaparecidos del móvil **sin haberse ido** — 503 falsos positivos frente a
449 bajas reales. Se sellan aparte, por `key_id`, que para ellos es lo único que hay.

## 3. Faltaba media base

El diseño enumeraba seis tablas. La base tiene **más de veinte tablas que cuelgan de
`message`** —reacciones, menciones, miniaturas incrustadas, ubicaciones, vCards, enlaces,
llamadas, acuses de recibo…— con **498.387 filas de contenido** que se habrían quedado
fuera. Se descubrieron leyendo documentación forense externa (ver
`documentacion/whatsapp/`), no mirando el código.

Ahora no se enumeran: se detectan solas por tener una columna `message_row_id`. Así la
fusión sigue funcionando cuando WhatsApp añada tablas en la próxima versión.

## Y una lección de rendimiento

La primera fusión completa tardó **482 segundos**. El 94 % se iba en un solo paso: buscar
cada uno de los 120.011 `jid` por `raw_string` **sin índice**, o sea 120.011 barridos
completos de la tabla. WhatsApp no lo trae porque su `jid` se consulta por `_id`.

Un `CREATE INDEX` lo dejó en **25 segundos**. Por eso `fusiona()` devuelve el tiempo de
cada paso: sin medir por fases se habría optimizado lo que no era.

## Cómo se comprobó

Sin tocar el móvil: se copió la base, se le borró una conversación entera (399 mensajes),
50 mensajes sueltos de otra y se le añadieron 3 nuevos. Fusionada contra el archivo, el
resultado fue exactamente el esperado — 3 insertados, 1 conversación y 449 mensajes
marcados como idos.

Y a la inversa, que es la prueba que de verdad importa: partiendo de un archivo al que le
faltaba todo eso, fusionar la base completa **recuperó los 449 mensajes, la conversación y
todas sus filas hijas** (1.057 acuses, 27 medios, 13 citados, 4 miniaturas, menciones,
encuestas, enlaces…). Nada se quedó por el camino.
