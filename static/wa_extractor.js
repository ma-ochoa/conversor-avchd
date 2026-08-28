/* Extractor de fotos de perfil de WhatsApp Web.
 *
 * Se pega en la consola del navegador (F12 → Console) con WhatsApp Web abierto. No se
 * puede hacer desde el servidor: las fotos solo existen dentro de esa página.
 *
 * **Los avatares NO son <img>.** Son elementos <image> dentro de un <svg> con máscara
 * circular, y su xlink:href apunta al CDN de WhatsApp. Buscarlos con img[src] devuelve
 * uno de cada setenta, que es el error que cuesta media tarde descubrir.
 *
 * La lista de chats solo llega hasta donde WhatsApp Web haya sincronizado, así que
 * además se busca por vocales y por «+34»: el buscador filtra por «contiene», y con eso
 * asoman los contactos que no tienen conversación reciente. En una cuenta real esto pasó
 * de 410 a 1.045.
 *
 * No automatiza nada de WhatsApp: solo lee lo que la página ya ha pintado y escribe en su
 * buscador, al ritmo de una persona. No envía mensajes ni abre conversaciones.
 */
(async () => {
  const PANEL = '#pane-side';
  const panel = document.querySelector(PANEL);
  if (!panel) { alert('Abre WhatsApp Web y espera a que cargue la lista de chats.'); return; }

  const encontrados = new Map();
  const aviso = document.createElement('div');
  aviso.style.cssText = 'position:fixed;top:12px;right:12px;z-index:99999;background:#111b21;' +
    'color:#e9edef;padding:14px 18px;border-radius:10px;font:14px system-ui;box-shadow:0 4px 18px #0008';
  aviso.textContent = 'Preparando…';
  document.body.appendChild(aviso);
  const di = (t) => { aviso.firstChild.textContent = t; };

  const recoge = () => {
    panel.querySelectorAll('[role="row"], [role="listitem"], [role="button"]').forEach(f => {
      const im = f.querySelector('image');
      const href = im && (im.getAttribute('xlink:href') || im.getAttribute('href'));
      if (!href || !/^https/.test(href)) return;
      const t = f.querySelector('[title]');
      const nombre = ((t && t.getAttribute('title')) || (f.innerText || '').split('\n')[0] || '').trim();
      if (nombre && !encontrados.has(nombre)) encontrados.set(nombre, href);
    });
  };

  // Baja hasta el fondo de verdad. El tope por número de pantallas no vale: los contactos
  // aparecen DESPUÉS de los chats, y la lista crece mientras se baja.
  const hastaElFondo = async (etiqueta) => {
    let sinAvance = 0, altoAnterior = -1, vueltas = 0;
    panel.scrollTop = 0;
    await new Promise(r => setTimeout(r, 900));
    while (sinAvance < 4 && vueltas < 200) {
      recoge();
      const antes = panel.scrollTop;
      panel.scrollTop = antes + Math.floor(panel.clientHeight * 0.85);
      await new Promise(r => setTimeout(r, 700));
      if (panel.scrollTop <= antes + 2 && panel.scrollHeight === altoAnterior) sinAvance++;
      else sinAvance = 0;
      altoAnterior = panel.scrollHeight;
      vueltas++;
      di(`${etiqueta} · ${encontrados.size} fotos`);
    }
    recoge();
  };

  const escribe = (txt) => {
    const inp = document.querySelector('input[type="text"][role="textbox"]');
    if (!inp) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(inp, txt);
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  };

  await hastaElFondo('Lista de chats');

  // «+34» saca a quien no está en la agenda y aparece con su propio número por nombre.
  for (const termino of ['a', 'e', 'i', 'o', 'u', '+34']) {
    if (!escribe(termino)) break;
    await new Promise(r => setTimeout(r, 1800));
    await hastaElFondo(`Buscando «${termino}»`);
  }
  escribe('');

  const datos = [...encontrados].map(([nombre, url]) => ({ nombre, url }));
  aviso.textContent = '';
  const b = document.createElement('button');
  b.textContent = `Descargar ${datos.length} fotos`;
  b.style.cssText = 'background:#25D366;color:#111;border:0;border-radius:8px;padding:12px 18px;' +
    'font:600 15px system-ui;cursor:pointer';
  // Chrome exige un clic de verdad para descargar: no se puede disparar por código.
  b.onclick = () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(datos)], { type: 'application/json' }));
    a.download = 'avatares-whatsapp.json';
    a.click();
    b.textContent = 'Descargado ✓  (súbelo en la app)';
  };
  aviso.append(`${datos.length} fotos encontradas. `, b);
})();
