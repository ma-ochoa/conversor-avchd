# Bitácora — eclipse del 12 de agosto de 2026

Registro del proceso completo: qué se hizo, qué falló, por qué falló y cómo se
arregló. Escrito para poder repetirlo con material parecido —astrofotografía, un
objeto que hay que centrar, secuencias largas que hay que acelerar— sin volver a
tropezar en lo mismo.

**Material de partida:** dos tarjetas Sony. a6400 (139 JPG + 123 ARW a 240 mm, más un
vídeo 4K de 7:58) y a66 (142 JPG a 300 mm, más un AVCHD de 52 s). En total 281 fotos y
dos vídeos, sin ordenar y mezclados con material ajeno al eclipse.

---

## 1. Centrar el objeto: el error que parece obvio y no lo es

**Lo primero que uno intenta:** detectar la zona más brillante y centrar ahí.

**Por qué está mal:** durante la fase parcial el brillo se concentra en el **cuerno del
creciente**, que va girando alrededor del disco conforme avanza el eclipse. Centrar en
el brillo hace que el Sol salte de un lado a otro del encuadre justo en el momento más
vistoso. Medido: el centroide de brillo cae a ~60 px del centro real en un creciente
fino, y ese desplazamiento *rota* a lo largo de la secuencia.

**Lo correcto:** ajustar una **circunferencia de radio conocido al limbo**. El radio se
calcula de la óptica:

```
radio_px = focal_mm · radio_angular / (ancho_sensor_mm / ancho_px)
```

Con 0,004650 rad para el Sol: 281,6 px en las fotos de la a6400 (240 mm, APS-C, 6000 px)
y 352,0 px en las de la a66 (300 mm). Confirmado midiendo sobre las imágenes.

**Resultado:** desvío mediano de **1,4–2,8 px** sobre recortes de 2000–2500 px.

### El sub-problema: hay dos limbos, no uno

Un creciente fino tiene **dos arcos fuertes**: el limbo solar (borde exterior) y el
limbo lunar (borde interior, el terminador). Un ajuste genérico se engancha al que
tenga más contraste, que muchas veces es el equivocado.

Se vio en `DSC02424`, `DSC02436` y `DSC09403`: el círculo salía sobre el disco lunar y
el creciente quedaba **fuera** de la circunferencia. Físicamente imposible.

**Solución** (`detect.py::refine_sun_limb`): exigir que justo por dentro del borde haya
**fotosfera** — brillo cercano al máximo de la escena — y que el brillo caiga hacia
fuera. Eso descarta el terminador, donde la fotosfera queda por el otro lado.

Durante la **totalidad** no hay fotosfera, así que ahí se ajusta al limbo lunar con el
método genérico (máximo gradiente radial). El salto entre ambos centros es de 11–14 px
como mucho: despreciable en un recorte de 2000 px.

### El sub-problema del velo atmosférico

Con el Sol bajo y mucho velo, el criterio de "caída de brillo hacia fuera" fallaba: el
cielo alrededor estaba casi tan brillante como el creciente. Se resolvió probando tres
umbrales de fotosfera (0,90 / 0,75 / 0,55 del percentil 99,9) y quedándose con el ajuste
de **menor dispersión** respecto a la circunferencia.

---

## 2. Agrupar por exposición: la velocidad no basta

Todo se disparó con horquillas. Para separar «las claras» de «las oscuras» lo natural
es ordenar por velocidad de obturación. **No funciona**, porque la apertura y el ISO no
eran fijos: la a66 alternó f/8 y f/10 con ISO 100 y 1600; la a6400, f/6,3 y f/7,1 con
ISO 100, 200, 8000 y 12800.

Una foto a 1/160 y f/6,3 es un paso más clara que otra a 1/160 y f/10, y ambos casos
existían con 8 segundos de diferencia.

**Lo correcto:** exposición total.

```
EV = log2(tiempo · ISO / f²)
```

Con eso se reconstruyeron las 103 horquillas. La cámara escribe **siempre la toma base
primero** y luego las desviaciones, cada vez más extremas — esa regla es lo que permite
detectar dónde empieza cada horquilla.

**Trampa:** cuando la velocidad topa en 1/4000, dos pasos distintos de la horquilla dan
la **misma exposición real**. Hay que agrupar por niveles de EV *distintos*, no por
posición en la horquilla.

**Verificación:** la superficie quemada del disco crece limpiamente entre grupos
(0 % → 0 % → 3 % → 20 % → 30 %), que es la prueba de que la clasificación es correcta.

---

## 3. Vídeo: reducción 3:1 eligiendo el mejor de cada grupo

7 minutos de ocultación a 25 fps → dos minutos. Un `fps=` normal habría cogido
fotogramas movidos y caídas a negro.

**Arquitectura en tres pasadas:**

1. Medir los 9.813 fotogramas por tubería (2 min a 83 fps en gris 4K)
2. Agrupar de 3 en 3 y ordenar cada grupo por calidad
3. Decodificar en color y escribir el mejor de cada grupo

**Lo que se encontró:** 164 caídas a negro del propio vídeo, 155 fotogramas movidos y
31 con el objeto fuera de encuadre.

### Dos fallos propios que costaron encontrar

**Los negros se colaban.** El filtro tenía una regla que aceptaba «sin señal» pensada
para el fundido final del clip. Resultado: 26 caídas intermedias pasaban por buenas.
Arreglo: solo se admite oscuro a partir del instante en que empieza el apagado real.

**El umbral de nitidez no puede ser fijo.** El indicador (píxeles en transición sobre
píxeles de núcleo) sube por sí solo cuando el objeto se afina: un fotograma nítido daba
0,19 al principio y 2,13 al final, y los dos eran buenos. Arreglo: comparar con la
**mediana local** de ~100 fotogramas.

**Y aun así se colaron 21 movidos**, porque el filtro de nitidez solo pesaba en el
*orden de preferencia*: si ninguno de los tres candidatos era bueno, acababa aceptando
el menos malo. Se detectaron auditando el resultado.

---

## 4. Estabilización: cuatro versiones y tres fallos encadenados

Vídeo de 52 s grabado a pulso a 300 mm. Recorrido de la cámara: **514 × 456 px** sobre
1920×1080, con el estabilizador óptico activado.

### v1 — ventana de suavizado
Temblor mediano 6,3 → 4,0 px. Insuficiente: se pedía efecto trípode.

### v2 — bloqueo total, trayectoria integrada
Temblor entre consecutivos **0,0 px de mediana**… y sin embargo se movía a partir del
segundo 25. El número decía que estaba perfecto y el ojo decía que no.

**Causa:** la trayectoria se construía **sumando** el desplazamiento fotograma a
fotograma. Con 1.313 sumas y 1–2 px de error en cada una, el desvío acumulado llegaba a
**133 px**. Cada paso era correcto; el conjunto, no.

*Lección: medir entre consecutivos no detecta la deriva. Hay que medir contra una
referencia absoluta.*

### v3 — medir contra el primer fotograma
Elimina la acumulación, pero al ponerse el Sol la escena cambia tanto que la calidad de
la correlación cae **de 220 a 9**. Medidas inservibles en el último tercio.

### v4 — anclas encadenadas (el bueno)
Anclas cada 5 s. Las anclas se encadenan entre sí (12 sumas, no 1.313) y cada fotograma
se mide contra **su** ancla, que está a menos de 2,5 s y se le parece mucho.

Más dos correcciones necesarias:
- **Descartar medidas no fiables** por calidad de pico y por desviación de la mediana
  local. Había saltos de 350 px en 0,8 s, imposibles. Fueron 148 de 1.313.
- **Recortar el clip**: el primer segundo era un paneo de encuadre y la cola ya no tenía
  objeto que seguir.

**Resultado final:** desvío de **2–4 px** entre los segundos 5 y 35, frente a los 133 px
de la v2.

### Límite que no se puede pasar
El **rolling shutter** no se corrige por traslación. Los 106 fotogramas con sacudidas
bruscas quedan internamente deformados. Es el suelo del método.

---

## 5. Interpolación con FILM: dónde sirve y dónde no

Modelo `akhaliq/frame-interpolation-film-style` (Hugging Face, 148 MB, TensorFlow).
~24 s por fotograma a 1280² en CPU.

**Funciona muy bien** entre tomas separadas 1–3 s: el resultado es indistinguible de
metraje real, con el objeto en su forma intermedia exacta y sin fantasmas.

**Se rompe** cuando hay que inventar geometría. Entre dos tomas separadas 12 s, en las
que un aro se convierte en creciente, aparecen grumos oscuros cabalgando sobre el borde
de avance. No es un fallo del modelo: en ese hueco aparece luz que **nadie fotografió**,
y el flujo óptico solo sabe desplazar píxeles existentes.

### El intento de arreglo que empeoró otra cosa

Hipótesis: el flujo óptico asume brillo constante, y entre esas dos tomas la luz media
cambia ×2,95. Normalizando antes e igualando después, los grumos casi desaparecieron.

**Pero destrozó la corona.** Y al medir por zonas se vio el error del razonamiento:

| Zona | Cambio de brillo |
|---|---|
| Disco interior | ×33 |
| **Limbo (donde estaba el grumo)** | **×1,22** |
| Corona | ×2,15 |
| Cielo lejano | ×5,13 |
| *Media del cuadro* | *×2,95* |

El cambio **no es uniforme**. La ganancia global de ×2,95 era correcta para el promedio
y errónea para cada zona concreta. Y en el limbo —justo donde estaba el problema— las
dos tomas ya se parecían: el artefacto nunca fue de exposición. La corrección solo
bajaba el contraste, disimulando el síntoma.

*Lección: antes de aplicar una corrección global, comprobar si la magnitud que se
corrige es realmente global.*

**Solución adoptada:** densidad variable. 15 fotogramas intermedios donde FILM acierta,
3 donde tiene que inventar, para que el defecto pase rápido por pantalla.

---

## 6. Método: lo que de verdad marcó la diferencia

**Auditar el resultado, no los cálculos.** Es la práctica que más fallos encontró: los
21 movidos colados, la deriva de la v2, los descentrados de 86 y 96 px en dos fotos
concretas. Los datos intermedios los daban todos por buenos.

**Dibujar lo detectado encima de la imagen.** `verify.py` pinta el círculo ajustado
sobre el original. Casi todos los errores de detección se vieron ahí antes que en
ningún número.

**Desconfiar de un número que contradice al ojo.** «0,0 px de temblor» y una imagen que
se mueve significaba que se estaba midiendo la magnitud equivocada.

**Los umbrales relativos ganan a los absolutos** en cuanto el material evoluciona.
Nitidez, brillo, calidad de correlación: todos acabaron comparándose con su entorno.

**Medir antes de decidir.** Las decisiones de montaje se tomaron sobre números —brillo
del sujeto, salto en EV, desvío en píxeles— y no sobre impresiones.

---

## 7. Datos concretos de este material

Por si sirven de referencia para material parecido:

| | |
|---|---|
| Radio solar | 0,004650 rad (0,53° de diámetro aparente) |
| a6400, 240 mm, 6000 px | Sol de 563 px de diámetro |
| a66, 300 mm, 6000 px | Sol de 704 px |
| a6400 4K vídeo, 240 mm | Sol de 361 px |
| Encuadre usado | El Sol ocupa el 28 % del ancho del cuadro |
| Totalidad (a6400) | 20:31:19 → 20:31:41 |
| Desfase entre relojes | La a66 iba 67 s adelantada |

**Sobre los metadatos de vídeo:** la a6400 **no** escribe ISO, obturador ni diafragma en
XAVC-S — ni en el archivo ni en el XML de Sony. La a66 sí los escribe en AVCHD, dentro
del flujo H.264, y `exiftool` los lee. Cuando no están, se pueden estimar comparando el
brillo del sujeto en luz lineal con una foto de exposición conocida tomada en el mismo
momento; el margen es de ±0,5 EV.
