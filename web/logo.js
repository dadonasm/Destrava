/* D&D Technology - selo e monograma em SVG puro (sem imagens, sem dependências).
   Uso:  DD.seal({variant:'original'|'ouro'|'claro', bg:true|false, size:240, bottom:'rot'|'flat', bottomText:'BACKUP VERIFICADO'})
         DD.mono({variant:'ouro', size:48})                                                                          */
(function (w) {
  var n = 0;
  var P = {
    original: { bg: '#4a4a4a', line: '#ffffff', txt: '#ffffff', d1: '#ffffff', d2: '#1b1b1b', d2o: 1, dot: '#1b1b1b' },
    ouro:     { bg: '#0d0d10', line: 'url(#g@)', txt: 'url(#g@)', d1: 'url(#g@)', d2: '#7a5c14', d2o: .85, dot: 'url(#g@)', gold: true },
    claro:    { bg: '#ffffff', line: '#1b1b1b', txt: '#1b1b1b', d1: '#1b1b1b', d2: '#8a8a8a', d2o: .9, dot: '#1b1b1b' }
  };
  var FONT = "Optima,Candara,'Segoe UI','Trebuchet MS','DejaVu Sans',Verdana,sans-serif";
  var D_OUT = 'M180 200H212C250 200 266 224 266 250C266 276 250 300 212 300H180Z';
  var D_IN = 'M196 212V288H210C236 288 248 272 248 250C248 228 236 212 210 212Z';

  function pal(v, id) {
    var p = P[v] || P.original, o = {};
    for (var k in p) { o[k] = (typeof p[k] === 'string') ? p[k].replace('@', id) : p[k]; }
    return o;
  }
  function grad(c, id) {
    return c.gold ? '<defs><linearGradient id="g' + id + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f3d98b"/><stop offset=".5" stop-color="#d4a73a"/><stop offset="1" stop-color="#9a7418"/></linearGradient></defs>' : '';
  }
  function monoGroup(c) {
    return '<g fill-rule="evenodd">' +
      '<g fill="' + c.d1 + '"><path d="' + D_OUT + D_IN + '"/></g>' +
      '<g fill="' + c.d2 + '" fill-opacity="' + c.d2o + '" transform="translate(500 0) scale(-1 1)"><path d="' + D_OUT + D_IN + '"/></g></g>';
  }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

  w.DD = {
    seal: function (o) {
      o = o || {}; var id = 'dd' + (++n), c = pal(o.variant, id), size = o.size || 240;
      var top = 'D&amp;D TECHNOLOGY', flat = o.bottom === 'flat';
      var bt = flat ? esc(o.bottomText || 'D&D TECHNOLOGY') : top;
      var ring = '<circle cx="250" cy="250" r="181" fill="none" stroke="' + c.line + '" stroke-width="1.8"/>' +
                 '<circle cx="250" cy="250" r="121" fill="none" stroke="' + c.line + '" stroke-width="1.8"/>';
      var tx = 'font-family="' + FONT + '" font-size="21" font-weight="500" letter-spacing="7.5" fill="' + c.txt + '"';
      var topT = '<path id="a' + id + '" d="M107 250A143 143 0 0 1 393 250" fill="none"/>' +
                 '<text ' + tx + '><textPath href="#a' + id + '" startOffset="50%" text-anchor="middle">' + top + '</textPath></text>';
      var botT;
      if (flat) {
        botT = '<path id="b' + id + '" d="M91 250A159 159 0 0 0 409 250" fill="none"/>' +
               '<text ' + tx + '><textPath href="#b' + id + '" startOffset="50%" text-anchor="middle">' + bt + '</textPath></text>';
      } else {
        botT = '<g transform="rotate(180 250 250)">' + topT.replace('a' + id, 'c' + id).replace('#a' + id, '#c' + id) + '</g>';
      }
      var dots = '<circle cx="99" cy="250" r="3.2" fill="' + c.dot + '"/><circle cx="401" cy="250" r="3.2" fill="' + c.dot + '"/>';
      var bg = (o.bg === false) ? '' : '<rect width="500" height="500" fill="' + c.bg + '"/>';
      return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 500" width="' + size + '" height="' + size + '" role="img" aria-label="D&amp;D Technology">' +
             grad(c, id) + bg + ring + topT + botT + dots + monoGroup(c) + '</svg>';
    },
    mono: function (o) {
      o = o || {}; var id = 'dm' + (++n), c = pal(o.variant, id), size = o.size || 48;
      return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="165 185 170 130" width="' + size + '" height="' + Math.round(size * 130 / 170) + '" role="img" aria-label="D&amp;D">' +
             grad(c, id) + (o.bg ? '<rect x="165" y="185" width="170" height="130" fill="' + c.bg + '"/>' : '') + monoGroup(c) + '</svg>';
    }
  };
})(window);
