# -*- coding: utf-8 -*-
"""Destrava! - relatório do backup em PDF, sem bibliotecas de fora.

Escrito no fim do backup, ao lado do Mapa: capa, resumo, índice clicável e as seções do que foi mantido, dos
programas para reinstalar, do que ficou de fora, dos erros e das checagens, com gráficos e ícones desenhados
(vetor). O PDF é montado à mão: páginas A4, fontes padrão Helvetica (texto em cp1252, que cobre o português),
links internos e marcadores do leitor. Recebe as linhas do Mapa (meta e f de dados.js), sem ler o disco.
"""
import collections
import datetime
import math
import os
import struct
import unicodedata
import zlib

W, H = 595.28, 841.89  # A4 em pontos
MX = 44  # margem lateral
TOPO, PE = 64, 50  # área útil: do cabeçalho ao rodapé

# cores (0-1)
TINTA = (0.12, 0.14, 0.19)
MUT = (0.42, 0.44, 0.49)
LINHA = (0.86, 0.87, 0.9)
FUNDO = (0.965, 0.97, 0.985)
AZUL = (0.23, 0.49, 0.96)
AZUL2 = (0.16, 0.36, 0.84)
VERDE = (0.18, 0.56, 0.36)
AMBAR = (0.9, 0.64, 0.23)
VERMELHO = (0.78, 0.26, 0.23)
OURO = (0.88, 0.7, 0.29)
BRANCO = (1, 1, 1)
PALETA = [(0.23, 0.49, 0.96), (0.18, 0.56, 0.36), (0.9, 0.64, 0.23), (0.55, 0.36, 0.86), (0.85, 0.35, 0.55),
          (0.18, 0.62, 0.7), (0.55, 0.47, 0.35), (0.42, 0.44, 0.49), (0.95, 0.45, 0.25), (0.3, 0.3, 0.55)]

# larguras AFM das fontes padrão (caracteres 32 a 126); o resto usa a letra-base (á = a) ou 556
_HV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
      [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667,
       611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
       556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_HB = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
      [333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667,
       611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889,
       611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]
_ESP = {"·": 278, "–": 556, "—": 1000, "“": 333, "”": 333, "‘": 222, "’": 222, "•": 350, "…": 1000, "×": 584, "º": 365, "ª": 370, "€": 556}

CAT_NOME = {"Fotos": "Fotos", "Videos": "Vídeos", "Audios": "Áudios", "Documentos": "Documentos", "Projetos": "Projetos (Photoshop, CAD...)",
            "Email_Contatos": "E-mail e contatos", "Conversas": "Conversas", "Contas_Senhas": "Contas e senhas", "Outros": "Outros",
            "Navegadores": "Favoritos dos navegadores", "Dados_de_apps": "Dados de programas", "Sistemas": "Sistemas da empresa",
            "Nuvem": "Só na nuvem", "Ocultos": "Ocultos", "Programas": "Programas", "Configuracoes": "Configurações",
            "Temporarios": "Temporários", "Extras": "Incluídos por você"}
CAT_ICO = {"Fotos": "foto", "Videos": "video", "Audios": "musica", "Documentos": "doc", "Projetos": "regua", "Email_Contatos": "carta",
           "Conversas": "balao", "Contas_Senhas": "cadeado", "Navegadores": "globo", "Dados_de_apps": "apps", "Sistemas": "apps",
           "Nuvem": "nuvem", "Programas": "apps", "Configuracoes": "engrenagem", "Extras": "pasta"}
SIT_NOME = {"desmarcado": "Desmarcado por você", "ignorado": "Deixado de fora pela varredura", "revisar": "Ficou para revisar (não marcado)",
            "em_uso": "Em uso por um programa", "falha": "Falha na cópia"}
SIT_EXPLICA = {"desmarcado": "Você tirou da seleção: não vai para o backup.",
               "ignorado": "Sistema, programas e temporários que se recriam sozinhos depois de formatar.",
               "revisar": "A varredura não marcou sozinha (dados de programas, arquivos grandes ou incomuns) e ninguém marcou.",
               "em_uso": "Arquivos de programas abertos durante a cópia (navegador, serviços). É normal e não são arquivos pessoais."}
CAUSA_NOME = {"sumiu": "Sumiu da origem", "em_uso": "Em uso por outro programa", "permissao": "Sem permissão de leitura", "espaco": "Sem espaço no destino",
              "caminho_longo": "Caminho longo demais", "io": "Erro de leitura do disco", "divergente": "Cópia não conferiu", "somente_leitura": "Destino somente leitura",
              "outro": "Outro erro"}
COMO_RESOLVER = {"sumiu": "Foi apagado ou movido durante o backup; se precisar dele, restaure na origem e refaça.",
                 "em_uso": "Feche o programa que usa o arquivo e refaça só os que falharam.",
                 "permissao": "Abra o Destrava! como administrador (no Mac, libere o Acesso Total ao Disco) e refaça.",
                 "espaco": "Libere espaço no destino ou escolha outro e refaça.",
                 "caminho_longo": "Caminho longo demais: copie esse arquivo à mão para uma pasta mais curta.",
                 "io": "Possível setor defeituoso: tente de novo; se persistir, o arquivo pode estar corrompido na origem.",
                 "divergente": "A cópia não conferiu com o original: refaça (a cópia ruim é apagada e copiada de novo).",
                 "somente_leitura": "O destino está somente leitura: remonte com escrita ou escolha outro."}


def fmt(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or u == "TB":
            return ("%d %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u)).replace(".", ",")
        n /= 1000.0
    return ""


def nf(n):
    return "{:,}".format(int(n or 0)).replace(",", ".")


def _cp(s):
    """Texto para o PDF: normalizado, em cp1252 (o que não existe vira ?), com \\ ( ) escapados."""
    s = unicodedata.normalize("NFC", str(s if s is not None else ""))
    b = s.encode("cp1252", "replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)").replace(b"\r", b"").replace(b"\n", b" ")


def largura(s, tam, negrito=False):
    tab = _HB if negrito else _HV
    t = 0
    for ch in unicodedata.normalize("NFC", str(s)):
        o = ord(ch)
        if 32 <= o <= 126:
            t += tab[o - 32]
        elif ch in _ESP:
            t += _ESP[ch]
        else:
            base = unicodedata.normalize("NFD", ch)[0]
            ob = ord(base)
            t += tab[ob - 32] if 32 <= ob <= 126 else 556
    return t * tam / 1000.0


def corta(s, larg, tam, negrito=False):
    """Encurta com … no meio (caminhos ficam com o começo e o fim)."""
    s = str(s or "")
    if largura(s, tam, negrito) <= larg:
        return s
    a, b = 0, len(s)
    while a < b:  # maior n tal que o começo e o fim cabem
        m = (a + b + 1) // 2
        x = s[:m // 2] + "…" + s[len(s) - (m - m // 2):]
        if largura(x, tam, negrito) <= larg:
            a = m
        else:
            b = m - 1
    return s[:a // 2] + "…" + s[len(s) - (a - a // 2):] if a else "…"


def quebra(s, larg, tam, negrito=False):
    out, linha = [], ""
    for p in str(s or "").split():
        t = (linha + " " + p).strip()
        if largura(t, tam, negrito) <= larg or not linha:
            linha = t
        else:
            out.append(linha)
            linha = p
    if linha:
        out.append(linha)
    return out or [""]


def ler_png(caminho):
    """PNG de 8 bits RGB ou RGBA, sem entrelaçamento (os ícones que o Destrava! grava): (largura, altura, rgb, alfa ou None).
    Qualquer outro formato devolve None e o relatório segue sem a imagem."""
    try:
        with open(caminho, "rb") as fh:
            b = fh.read()
    except OSError:
        return None
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    i, idat, w = 8, [], 0
    while i + 8 <= len(b):
        n, tipo = struct.unpack(">I4s", b[i:i + 8])
        dados = b[i + 8:i + 8 + n]
        if tipo == b"IHDR":
            w, h, prof, cor, _c, _f, entr = struct.unpack(">IIBBBBB", dados)
            if prof != 8 or cor not in (2, 6) or entr:
                return None
        elif tipo == b"IDAT":
            idat.append(dados)
        elif tipo == b"IEND":
            break
        i += 12 + n
    if not w:
        return None
    bpp = 4 if cor == 6 else 3
    raw, linha = zlib.decompress(b"".join(idat)), w * bpp
    ant, out, pos = bytearray(linha), bytearray(), 0
    for _ in range(h):
        f, cur = raw[pos], bytearray(raw[pos + 1:pos + 1 + linha])
        pos += 1 + linha
        for x in range(linha):
            a = cur[x - bpp] if x >= bpp else 0
            c = ant[x - bpp] if x >= bpp else 0
            up = ant[x]
            if f == 1:
                cur[x] = (cur[x] + a) & 255
            elif f == 2:
                cur[x] = (cur[x] + up) & 255
            elif f == 3:
                cur[x] = (cur[x] + ((a + up) >> 1)) & 255
            elif f == 4:
                pa, pb, pc = abs(up - c), abs(a - c), abs(a + up - 2 * c)
                cur[x] = (cur[x] + (a if pa <= pb and pa <= pc else up if pb <= pc else c)) & 255
        out += cur
        ant = cur
    if bpp == 3:
        return w, h, bytes(out), None
    return w, h, bytes(out[i] for i in range(len(out)) if i % 4 != 3), bytes(out[3::4])


class Pagina(object):
    def __init__(self):
        self.ops = []
        self.links = []  # (x, y, w, h, chave) em coordenadas de cima para baixo


class Pdf(object):
    """Desenho em coordenadas de cima para baixo (y cresce para baixo), como numa tela."""

    def __init__(self):
        self.paginas = []
        self.p = None
        self.destinos = {}  # chave -> (índice da página, y)
        self.marcadores = []  # (título, chave)
        self.imagens = {}  # caminho do PNG -> (nome no PDF, dados) ou None (não deu para ler)

    def imagem(self, caminho, x, y, w, h):
        """Desenha o PNG (ícone de programa) na caixa; se não der para ler, não desenha nada e devolve False."""
        if caminho not in self.imagens:
            png = ler_png(caminho)
            self.imagens[caminho] = ("Im%d" % (len(self.imagens) + 1), png) if png else None
        im = self.imagens[caminho]
        if not im:
            return False
        self._op("q %.2f 0 0 %.2f %.2f %.2f cm /%s Do Q" % (w, h, x, H - y - h, im[0]))
        return True

    def nova(self):
        self.p = Pagina()
        self.paginas.append(self.p)
        return len(self.paginas) - 1

    def _op(self, s):
        self.p.ops.append(s)

    @staticmethod
    def _c(c):
        return "%.3f %.3f %.3f" % c

    def ret(self, x, y, w, h, fill=None, stroke=None, r=0, lw=0.8):
        if not fill and not stroke:
            return
        ops = []
        if fill:
            ops.append(self._c(fill) + " rg")
        if stroke:
            ops.append(self._c(stroke) + " RG %.2f w" % lw)
        Y = H - y - h
        if r:
            r = min(r, w / 2.0, h / 2.0)
            k = 0.5523 * r
            x2, y2 = x + w, Y + h
            ops.append("%.2f %.2f m %.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c "
                       "%.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c h" % (
                           x + r, Y, x2 - r, Y, x2 - r + k, Y, x2, Y + r - k, x2, Y + r, x2, y2 - r, x2, y2 - r + k, x2 - r + k, y2, x2 - r, y2,
                           x + r, y2, x + r - k, y2, x, y2 - r + k, x, y2 - r, x, Y + r, x, Y + r - k, x + r - k, Y, x + r, Y))
        else:
            ops.append("%.2f %.2f %.2f %.2f re" % (x, Y, w, h))
        ops.append("B" if fill and stroke else "f" if fill else "S")
        self._op(" ".join(ops))

    def linha(self, x1, y1, x2, y2, cor=LINHA, lw=0.8, tracejado=False):
        self._op("%s RG %.2f w %s %.2f %.2f m %.2f %.2f l S [] 0 d" % (self._c(cor), lw, "[2 2] 0 d" if tracejado else "", x1, H - y1, x2, H - y2))

    def poli(self, pts, fill=None, stroke=None, lw=0.8, fechar=True):
        if not pts:
            return
        s = (self._c(fill) + " rg " if fill else "") + (self._c(stroke) + " RG %.2f w " % lw if stroke else "")
        s += "%.2f %.2f m " % (pts[0][0], H - pts[0][1]) + " ".join("%.2f %.2f l" % (a, H - b) for a, b in pts[1:])
        s += (" h" if fechar else "") + (" B" if fill and stroke else " f" if fill else " S")
        self._op(s)

    def circulo(self, cx, cy, r, fill=None, stroke=None, lw=0.8):
        self.poli([(cx + r * math.cos(a * math.pi / 24), cy + r * math.sin(a * math.pi / 24)) for a in range(48)], fill, stroke, lw)

    def arco(self, cx, cy, r1, r2, a0, a1, cor):
        """Fatia de rosca de a0 a a1 (graus, 0 = topo, sentido horário)."""
        n = max(2, int(abs(a1 - a0) / 4) + 1)
        f = lambda r, a: (cx + r * math.sin(math.radians(a)), cy - r * math.cos(math.radians(a)))
        pts = [f(r2, a0 + (a1 - a0) * i / float(n)) for i in range(n + 1)] + [f(r1, a1 - (a1 - a0) * i / float(n)) for i in range(n + 1)]
        self.poli(pts, fill=cor)

    def texto(self, x, y, s, tam=10, negrito=False, cor=TINTA, alinha="e"):
        s = str(s if s is not None else "")
        if alinha != "e":
            w = largura(s, tam, negrito)
            x = x - w if alinha == "d" else x - w / 2.0
        self._op("BT /%s %.2f Tf %s rg %.2f %.2f Td (%s) Tj ET" % ("F2" if negrito else "F1", tam, self._c(cor), x, H - y,
                                                                   _cp(s).decode("latin-1")))

    def link(self, x, y, w, h, chave):
        self.p.links.append((x, y, w, h, chave))

    def destino(self, chave, y):
        self.destinos[chave] = (len(self.paginas) - 1, y)

    # ---- montagem do arquivo
    def salvar(self, caminho):
        objs = []

        def novo(b):
            objs.append(b)
            return len(objs)

        cat = novo(b"")  # 1 catálogo (preenchido no fim)
        pags = novo(b"")  # 2 árvore de páginas
        f1 = novo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = novo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        xobj = []
        for nome, (w, h, rgb, alfa) in [v for v in self.imagens.values() if v]:
            sm = ""
            if alfa:
                za = zlib.compress(alfa)
                sid = novo(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n" % (w, h, len(za)) + za + b"\nendstream")
                sm = " /SMask %d 0 R" % sid
            zr = zlib.compress(rgb)
            iid = novo(("<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode%s /Length %d >>\nstream\n" % (w, h, sm, len(zr))).encode("latin-1") + zr + b"\nendstream")
            xobj.append("/%s %d 0 R" % (nome, iid))
        rec_x = (" /XObject << %s >>" % " ".join(xobj)) if xobj else ""
        ids = []
        for pg in self.paginas:  # reserva o número de cada página antes, para os links
            ids.append((novo(b""), novo(b"")))
        dest = lambda ch: "[%d 0 R /XYZ 0 %.2f 0]" % (ids[self.destinos[ch][0]][0], H - self.destinos[ch][1] + 12) if ch in self.destinos else None
        for (pid, cid), pg in zip(ids, self.paginas):
            dados = zlib.compress("\n".join(pg.ops).encode("latin-1"))
            objs[cid - 1] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(dados) + dados + b"\nendstream"
            an = []
            for x, y, w, h, ch in pg.links:
                d = dest(ch)
                if d:
                    an.append("<< /Type /Annot /Subtype /Link /Rect [%.2f %.2f %.2f %.2f] /Border [0 0 0] /Dest %s >>" % (x, H - y - h, x + w, H - y, d))
            objs[pid - 1] = ("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >>%s >> "
                             "/Contents %d 0 R%s >>" % (pags, W, H, f1, f2, rec_x, cid, (" /Annots [%s]" % " ".join(an)) if an else "")).encode("latin-1")
        objs[pags - 1] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % p for p, _ in ids), len(ids))).encode("latin-1")
        marc = [(t, ch) for t, ch in self.marcadores if ch in self.destinos]
        out_ref = ""
        if marc:
            raiz = novo(b"")
            itens = [novo(b"") for _ in marc]
            for i, ((t, ch), oid) in enumerate(zip(marc, itens)):
                s = "<< /Title (%s) /Parent %d 0 R /Dest %s" % (_cp(t).decode("latin-1"), raiz, dest(ch))
                if i:
                    s += " /Prev %d 0 R" % itens[i - 1]
                if i < len(itens) - 1:
                    s += " /Next %d 0 R" % itens[i + 1]
                objs[oid - 1] = (s + " >>").encode("latin-1")
            objs[raiz - 1] = ("<< /Type /Outlines /First %d 0 R /Last %d 0 R /Count %d >>" % (itens[0], itens[-1], len(itens))).encode("latin-1")
            out_ref = " /Outlines %d 0 R /PageMode /UseOutlines" % raiz
        objs[cat - 1] = ("<< /Type /Catalog /Pages %d 0 R%s >>" % (pags, out_ref)).encode("latin-1")
        buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        pos = []
        for i, o in enumerate(objs, 1):
            pos.append(len(buf))
            buf += b"%d 0 obj\n" % i + o + b"\nendobj\n"
        xref = len(buf)
        buf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % p for p in pos)
        buf += b"trailer\n<< /Size %d /Root %d 0 R /Info << /Title (Relatorio do backup) /Producer (Destrava!) >> >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, xref)
        tmp = caminho + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(bytes(buf))
        os.replace(tmp, caminho)
        return caminho


# ---- ícones vetoriais (caixa de lado t, canto superior esquerdo em x,y)
def icone(d, nome, x, y, t, cor=AZUL, interno=BRANCO):
    """interno: a cor dos detalhes por dentro (o "!" do alerta, o ✓), para ícones brancos sobre fundo colorido."""
    u = t / 24.0
    P = lambda a, b: (x + a * u, y + b * u)
    lw = max(0.8, 1.6 * u)
    if nome == "pasta":
        d.poli([P(2, 6), P(9, 6), P(11, 8.5), P(22, 8.5), P(22, 20), P(2, 20)], fill=cor)
    elif nome == "foto":
        d.ret(x + 2 * u, y + 4 * u, 20 * u, 16 * u, fill=cor, r=2.5 * u)
        d.poli([P(4, 18), P(10, 11), P(14, 15), P(16, 13), P(20, 18)], fill=BRANCO)
        d.circulo(x + 16 * u, y + 8.5 * u, 1.8 * u, fill=BRANCO)
    elif nome == "video":
        d.ret(x + 2 * u, y + 5 * u, 20 * u, 14 * u, fill=cor, r=2.5 * u)
        d.poli([P(10, 8.5), P(16, 12), P(10, 15.5)], fill=BRANCO)
    elif nome == "musica":
        d.poli([P(9, 5), P(20, 3), P(20, 16), P(18.5, 16), P(18.5, 6), P(10.5, 7.5), P(10.5, 18), P(9, 18)], fill=cor)
        d.circulo(x + 7 * u, y + 18 * u, 3 * u, fill=cor)
        d.circulo(x + 16.5 * u, y + 16 * u, 3 * u, fill=cor)
    elif nome == "doc":
        d.poli([P(5, 2), P(15, 2), P(20, 7), P(20, 22), P(5, 22)], fill=cor)
        d.poli([P(15, 2), P(15, 7), P(20, 7)], fill=(0.85, 0.9, 1))
        for k in (11, 14.5, 18):
            d.linha(x + 8 * u, y + k * u, x + 17 * u, y + k * u, BRANCO, lw)
    elif nome == "carta":
        d.ret(x + 2 * u, y + 5 * u, 20 * u, 14 * u, fill=cor, r=2 * u)
        d.poli([P(3, 6.5), P(12, 13), P(21, 6.5)], stroke=BRANCO, lw=lw, fechar=False)
    elif nome == "balao":
        d.ret(x + 2 * u, y + 3 * u, 20 * u, 14 * u, fill=cor, r=5 * u)
        d.poli([P(7, 16), P(6, 21), P(12, 16)], fill=cor)
    elif nome == "cadeado":
        d.poli([P(7, 11), P(7, 7.5), P(9, 4), P(15, 4), P(17, 7.5), P(17, 11)], stroke=cor, lw=2.2 * u, fechar=False)
        d.ret(x + 4.5 * u, y + 10.5 * u, 15 * u, 11 * u, fill=cor, r=2 * u)
    elif nome == "globo":
        d.circulo(x + 12 * u, y + 12 * u, 9.5 * u, fill=cor)
        d.linha(x + 2.5 * u, y + 12 * u, x + 21.5 * u, y + 12 * u, BRANCO, lw)
        d.poli([P(12, 2.5), P(8, 7), P(7, 12), P(8, 17), P(12, 21.5), P(16, 17), P(17, 12), P(16, 7)], stroke=BRANCO, lw=lw)
    elif nome == "apps":
        for a, b in ((3, 3), (13, 3), (3, 13), (13, 13)):
            d.ret(x + a * u, y + b * u, 8 * u, 8 * u, fill=cor, r=2 * u)
    elif nome == "nuvem":
        for cx, cy, r in ((8, 14, 5), (13, 10, 6), (17.5, 14, 4.5)):
            d.circulo(x + cx * u, y + cy * u, r * u, fill=cor)
        d.ret(x + 8 * u, y + 13 * u, 10 * u, 5.5 * u, fill=cor)
    elif nome == "engrenagem":
        d.circulo(x + 12 * u, y + 12 * u, 7 * u, fill=cor)
        for k in range(8):
            a = k * math.pi / 4
            d.circulo(x + (12 + 8 * math.cos(a)) * u, y + (12 + 8 * math.sin(a)) * u, 2.2 * u, fill=cor)
        d.circulo(x + 12 * u, y + 12 * u, 3 * u, fill=BRANCO)
    elif nome == "regua":
        d.poli([P(3, 20), P(20, 3), P(22, 5), P(5, 22)], fill=cor)
    elif nome == "alerta":
        d.poli([P(12, 2.5), P(22.5, 21), P(1.5, 21)], fill=cor)
        d.ret(x + 11 * u, y + 8.5 * u, 2 * u, 7 * u, fill=interno)
        d.ret(x + 11 * u, y + 17 * u, 2 * u, 2 * u, fill=interno)
    elif nome == "ok":
        d.circulo(x + 12 * u, y + 12 * u, 10 * u, fill=cor)
        d.poli([P(7, 12.5), P(10.5, 16), P(17, 8.5)], stroke=interno, lw=2.4 * u, fechar=False)
    elif nome == "x":
        d.circulo(x + 12 * u, y + 12 * u, 10 * u, fill=cor)
        d.linha(x + 8 * u, y + 8 * u, x + 16 * u, y + 16 * u, interno, 2.4 * u)
        d.linha(x + 16 * u, y + 8 * u, x + 8 * u, y + 16 * u, interno, 2.4 * u)
    elif nome == "disco":
        d.ret(x + 2 * u, y + 6 * u, 20 * u, 12 * u, fill=cor, r=3 * u)
        d.circulo(x + 17.5 * u, y + 12 * u, 1.6 * u, fill=BRANCO)
        d.linha(x + 5 * u, y + 12 * u, x + 12 * u, y + 12 * u, BRANCO, lw)
    elif nome == "caixa":
        d.poli([P(3, 8), P(12, 4), P(21, 8), P(21, 19), P(12, 22), P(3, 19)], fill=cor)
        d.poli([P(3, 8), P(12, 12), P(21, 8)], stroke=BRANCO, lw=lw, fechar=False)
        d.linha(x + 12 * u, y + 12 * u, x + 12 * u, y + 22 * u, BRANCO, lw)
    elif nome == "espelho":
        d.ret(x + 3 * u, y + 3 * u, 8 * u, 18 * u, fill=cor, r=2 * u)
        d.ret(x + 13 * u, y + 3 * u, 8 * u, 18 * u, stroke=cor, r=2 * u, lw=lw)
    elif nome == "ordem":
        for k, w in ((4, 18), (10, 13), (16, 8)):
            d.ret(x + 3 * u, y + k * u, w * u, 4 * u, fill=cor, r=1.5 * u)
    else:
        d.circulo(x + 12 * u, y + 12 * u, 9 * u, fill=cor)


# ---- documento com fluxo (cabeçalho, rodapé e quebra de página)
class Doc(object):
    def __init__(self, cab):
        self.d = Pdf()
        self.cab = cab
        self.y = 0
        self.secoes = []  # (título, chave, página)

    def pagina(self, cabecalho=True):
        self.d.nova()
        self.y = TOPO
        if cabecalho:
            self.d.texto(MX, 34, "Destrava!", 9, True, AZUL)
            self.d.texto(MX + 52, 34, "Relatório do backup · " + self.cab, 9, False, MUT)
            self.d.linha(MX, 42, W - MX, 42, LINHA)

    def cabe(self, h):
        if self.y + h > H - PE:
            self.pagina()

    def secao(self, titulo, chave, sub="", icon="pasta", cor=AZUL):
        if self.y > TOPO + 4:
            self.pagina()
        self.d.destino(chave, self.y)
        self.secoes.append((titulo, chave, len(self.d.paginas)))
        self.d.marcadores.append((titulo, chave))
        self.d.ret(MX, self.y, W - 2 * MX, 54, fill=cor, r=10)
        icone(self.d, icon, MX + 14, self.y + 13, 28, BRANCO, cor)
        self.d.texto(MX + 54, self.y + 26, titulo, 18, True, BRANCO)
        if sub:
            self.d.texto(MX + 54, self.y + 42, corta(sub, W - 2 * MX - 70, 9.5), 9.5, False, (0.9, 0.93, 1))
        self.y += 72

    def titulo(self, t, sub=""):
        self.cabe(44)
        self.d.texto(MX, self.y + 12, t, 13, True)
        self.y += 18
        if sub:
            for ln in quebra(sub, W - 2 * MX, 9):
                self.d.texto(MX, self.y + 9, ln, 9, False, MUT)
                self.y += 12
        self.y += 6

    def paragrafo(self, t, tam=10, cor=TINTA, negrito=False):
        for ln in quebra(t, W - 2 * MX, tam, negrito):
            self.cabe(tam + 5)
            self.d.texto(MX, self.y + tam, ln, tam, negrito, cor)
            self.y += tam + 4
        self.y += 4

    def tabela(self, cols, linhas, tam=8.5, zebra=True, icones=None):
        """cols: [(título, largura, alinhamento)]; linhas: listas de textos. icones: função(linha) -> (nome, cor) para a 1ª coluna."""
        def cab():
            self.d.ret(MX, self.y, W - 2 * MX, 18, fill=FUNDO, r=4)
            x = MX + 6
            for t, w, a in cols:
                self.d.texto(x + (w - 8 if a == "d" else 0), self.y + 12, t, 8, True, MUT, a)
                x += w
            self.y += 20
        self.cabe(40)
        cab()
        for i, ln in enumerate(linhas):
            if self.y + 15 > H - PE:
                self.pagina()
                cab()
            if zebra and i % 2:
                self.d.ret(MX, self.y - 1, W - 2 * MX, 15, fill=(0.985, 0.985, 0.99))
            x = MX + 6
            for j, ((t, w, a), v) in enumerate(zip(cols, ln)):
                dx = 0
                if j == 0 and icones:
                    nm, cor = icones(ln)
                    if nm == "@img":  # PNG (ícone do programa); sem ele, o ícone desenhado
                        if not self.d.imagem(cor, x, self.y - 0.5, 12, 12):
                            icone(self.d, "apps", x, self.y + 1, 11, AZUL)
                    else:
                        icone(self.d, nm, x, self.y + 1, 11, cor)
                    dx = 15
                txt = corta(v, w - 10 - dx, tam, False)
                self.d.texto(x + dx + (w - 8 - dx if a == "d" else 0), self.y + 10, txt, tam, False, TINTA, a)
                x += w
            self.y += 15
        self.y += 8

    def kpis(self, itens, h=70):
        """Cartões de números grandes: [(rótulo, valor, sub, cor, ícone)]."""
        self.cabe(h + 10)
        n = len(itens)
        gap = 10
        w = (W - 2 * MX - gap * (n - 1)) / float(n)
        for i, (rot, val, sub, cor, ic) in enumerate(itens):
            x = MX + i * (w + gap)
            self.d.ret(x, self.y, w, h, fill=FUNDO, r=10)
            self.d.ret(x, self.y, 4, h, fill=cor)
            icone(self.d, ic, x + w - 30, self.y + 10, 18, cor)
            self.d.texto(x + 14, self.y + 20, corta(rot, w - 52, 8.5, True), 8.5, True, MUT)
            self.d.texto(x + 14, self.y + 44, corta(val, w - 24, 19, True), 19, True, TINTA)
            if sub:
                self.d.texto(x + 14, self.y + 60, corta(sub, w - 24, 8.5), 8.5, False, MUT)
        self.y += h + 14

    def barras(self, itens, total, larg_rot=170):
        """Barras horizontais: [(ícone, rótulo, valor, texto à direita, cor)]."""
        for i, (ic, rot, v, txt, cor) in enumerate(itens):
            self.cabe(22)
            icone(self.d, ic, MX, self.y + 2, 14, cor)
            self.d.texto(MX + 20, self.y + 12, corta(rot, larg_rot - 24, 9.5), 9.5)
            x0, wb = MX + larg_rot, W - 2 * MX - larg_rot - 110
            self.d.ret(x0, self.y + 4, wb, 9, fill=FUNDO, r=4.5)
            if total and v:
                self.d.ret(x0, self.y + 4, max(4, wb * v / float(total)), 9, fill=cor, r=4.5)
            self.d.texto(W - MX, self.y + 12, txt, 9, True, TINTA, "d")
            self.y += 20
        self.y += 6

    def rosca(self, cx, cy, r, partes, centro="", sub=""):
        """partes: [(valor, cor)]."""
        tot = float(sum(v for v, _ in partes)) or 1
        a = 0.0
        for v, cor in partes:
            if v <= 0:
                continue
            b = a + 360.0 * v / tot
            self.d.arco(cx, cy, r * 0.62, r, a, min(b, a + 359.9) if b - a > 359.9 else b, cor)
            a = b
        if centro:
            self.d.texto(cx, cy + 4, centro, 18, True, TINTA, "c")
        if sub:
            self.d.texto(cx, cy + 18, sub, 8, False, MUT, "c")


def _pasta_de(p, niveis=3):
    partes = [x for x in str(p).replace("\\", "/").split("/") if x]
    return "/".join(partes[:-1][-niveis:]) or "/"


def gerar(caminho, meta, f, programas=None, limite_apendice=2500):
    """Escreve o PDF. meta e f: os de dados.js do Mapa; programas: [{nome, nota, auto, fabricante}] do "O que manter"."""
    cert = meta.get("cert") or {}
    programas = programas or []
    ok = [r for r in f if r[5] == "ok"]
    falhas = [r for r in f if r[5] == "falha"]
    fora = [r for r in f if r[5] not in ("ok", "falha")]
    b_ok, b_fora = sum(r[3] for r in ok), sum(r[3] for r in fora)
    cats = collections.defaultdict(lambda: [0, 0])
    for r in ok:
        cats[r[2]][0] += 1
        cats[r[2]][1] += r[3]
    cats = sorted(cats.items(), key=lambda kv: -kv[1][1])
    cor_cat = {c: PALETA[i % len(PALETA)] for i, (c, _) in enumerate(cats)}
    nome = cert.get("maquina_nome") or cert.get("equipamento") or meta.get("pc") or "Esta máquina"
    if nome == cert.get("maquina_id") and (cert.get("host") or cert.get("modelo")):  # sem apelido: o id não serve de título
        nome = cert.get("host") or cert.get("modelo")
    modelo = cert.get("modelo") if cert.get("modelo") != nome else ""
    disco = cert.get("disco") or {}
    codigo = cert.get("codigo", "")
    data = cert.get("data") or meta.get("data") or datetime.date.today().isoformat()
    try:
        data_br = datetime.date.fromisoformat(data).strftime("%d/%m/%Y")
    except ValueError:
        data_br = data
    sem_falhas = cert.get("status") == "sem_falhas"
    doc = Doc("%s · %s%s" % (nome, data_br, (" · código " + codigo) if codigo else ""))
    d = doc.d

    # ---------------- 1. capa
    doc.pagina(False)
    d.ret(0, 0, W, 360, fill=AZUL2)
    d.ret(0, 300, W, 60, fill=AZUL)
    for i in range(9):  # padrão de arquivos ao fundo
        icone(d, ["pasta", "foto", "doc", "musica", "video", "carta", "apps", "nuvem", "globo"][i], 380 + (i % 3) * 62, 60 + (i // 3) * 70, 40, (0.32, 0.55, 0.97))
    d.texto(MX, 80, "Destrava!", 14, True, BRANCO)
    d.texto(MX, 150, "Relatório do backup", 32, True, BRANCO)
    d.texto(MX, 182, corta(nome, 330, 20, False), 20, False, (0.88, 0.92, 1))
    if modelo:
        d.texto(MX, 206, corta(modelo, 330, 13, False), 13, False, (0.88, 0.92, 1))
    d.texto(MX, 232 if modelo else 210, "%s às %s" % (data_br, cert.get("hora", "")), 12, False, (0.88, 0.92, 1))
    cor_selo = VERDE if sem_falhas else AMBAR
    d.circulo(W - 120, 330, 62, fill=BRANCO)
    d.circulo(W - 120, 330, 55, fill=cor_selo)
    icone(d, "ok" if sem_falhas else "alerta", W - 140, 290, 40, BRANCO, cor_selo)
    d.texto(W - 120, 352, "VERIFICADO" if sem_falhas else "COM RESSALVAS", 9 if sem_falhas else 7.5, True, BRANCO, "c")
    y = 390
    campos = [("Cliente", cert.get("dono_nome") or cert.get("cliente") or "—"), ("Técnico", cert.get("tecnico") or "—"),
              ("Equipamento", cert.get("equipamento") or meta.get("pc") or "—"), ("Modelo", cert.get("modelo") or "—"), ("Sistema", cert.get("sistema") or "—")]
    if disco.get("total"):
        campos.append(("Disco da máquina", "%s no total · %s usados · %s livres" % (fmt(disco["total"]), fmt(disco.get("usado")), fmt(disco.get("livre")))))
    campos += [("Destino do backup", meta.get("raiz") or "—"), ("Conferência", cert.get("metodo") or meta.get("verificacao") or "—"),
               ("Código do certificado", codigo or "—")]
    passo = min(40, 300 // len(campos))  # os cartões de baixo ainda cabem na capa
    for rot, val in campos:
        d.texto(MX, y, rot.upper(), 8, True, MUT)
        d.texto(MX, y + 16, corta(val, W - 2 * MX, 12), 12, rot == "Código do certificado")
        y += passo
    doc.y = y + 10
    doc.kpis([("MANTIDOS", nf(len(ok)), fmt(b_ok), VERDE, "ok"), ("FICARAM DE FORA", nf(len(fora)), fmt(b_fora), MUT, "caixa"),
              ("FALHAS", nf(len(falhas)), "nenhuma" if not falhas else "veja a seção de erros", VERMELHO if falhas else VERDE, "x" if falhas else "ok")])

    # ---------------- 2. resumo
    doc.pagina()
    d.destino("resumo", doc.y)
    d.marcadores.append(("Resumo", "resumo"))
    doc.secoes.append(("Resumo", "resumo", len(d.paginas)))
    d.texto(MX, doc.y + 20, "Resumo", 24, True)
    doc.y += 36
    frase = ("Foram copiados e conferidos %s arquivos (%s). %s ficaram de fora de propósito (sistema, programas, temporários ou "
             "desmarcados por você)%s." % (nf(len(ok)), fmt(b_ok), nf(len(fora)), (" e %s tiveram falha na cópia" % nf(len(falhas))) if falhas else ", sem nenhuma falha"))
    if disco.get("total"):
        frase += " O disco tinha %s no total (%s usados)." % (fmt(disco["total"]), fmt(disco.get("usado", 0)))
    doc.paragrafo(frase, 11)
    doc.kpis([("MANTIDOS", nf(len(ok)), fmt(b_ok), VERDE, "ok"), ("DE FORA", nf(len(fora)), fmt(b_fora), MUT, "caixa"),
              ("FALHAS", nf(len(falhas)), "", VERMELHO if falhas else VERDE, "x" if falhas else "ok"),
              ("PROGRAMAS", nf(len(programas)), "para reinstalar", AZUL, "apps")])
    y0 = doc.y
    doc.cabe(190)
    y0 = doc.y
    doc.rosca(MX + 85, y0 + 85, 80, [(len(ok), VERDE), (len(fora), (0.75, 0.77, 0.82)), (len(falhas), VERMELHO)],
              "%d%%" % round(100.0 * len(ok) / max(1, len(ok) + len(fora) + len(falhas))), "dos arquivos mantidos")
    ly = y0 + 40
    for rot, v, cor in (("Mantidos e conferidos", "%s · %s" % (nf(len(ok)), fmt(b_ok)), VERDE), ("Ficaram de fora", "%s · %s" % (nf(len(fora)), fmt(b_fora)), (0.75, 0.77, 0.82)),
                        ("Falhas", nf(len(falhas)), VERMELHO)):
        d.ret(MX + 200, ly - 8, 10, 10, fill=cor, r=2)
        d.texto(MX + 218, ly, rot, 10.5, True)
        d.texto(MX + 218, ly + 14, v, 9.5, False, MUT)
        ly += 38
    doc.y = y0 + 185
    if disco.get("total"):  # o disco inteiro, para não confundir "pessoal" com tudo o que a máquina tinha
        tot, usado, pessoal = disco["total"], disco.get("usado", 0), disco.get("pessoal", 0)
        doc.titulo("O disco da máquina")
        doc.paragrafo("O disco tinha %s no total, com %s usados. Desse uso, %s eram arquivos pessoais (o que o backup procura); "
                      "o resto é o sistema, os programas e arquivos temporários." % (fmt(tot), fmt(usado), fmt(pessoal)), 10)
        doc.barras([("disco", "Capacidade total", tot, fmt(tot), AZUL),
                    ("disco", "Usado", usado, fmt(usado), (0.45, 0.48, 0.55)),
                    ("disco", "Livre", disco.get("livre", 0), fmt(disco.get("livre", 0)), (0.75, 0.77, 0.82)),
                    ("pasta", "Arquivos pessoais", pessoal, fmt(pessoal), AMBAR),
                    ("ok", "Mantidos e conferidos", b_ok, fmt(b_ok), VERDE),
                    ("engrenagem", "Sistema e programas", max(0, usado - pessoal), fmt(max(0, usado - pessoal)), MUT)], tot)
    doc.titulo("O que foi mantido, por tipo")
    topo = cats[:10]
    doc.barras([(CAT_ICO.get(c, "caixa"), CAT_NOME.get(c, c), v[1], "%s · %s" % (nf(v[0]), fmt(v[1])), cor_cat[c]) for c, v in topo], max([v[1] for _, v in topo] or [1]))
    lay = meta.get("layout") or {}
    if lay.get("espelhados") or lay.get("ordenados"):
        doc.titulo("Como foi organizado no backup")
        doc.barras([("espelho", "Espelhado (como estava)", lay.get("espelhados", 0), nf(lay.get("espelhados", 0)) + " arquivos", AZUL),
                    ("ordem", "Ordenado (tipo e data)", lay.get("ordenados", 0), nf(lay.get("ordenados", 0)) + " arquivos", AMBAR)],
                   max(lay.get("espelhados", 0), lay.get("ordenados", 0), 1))

    # ---------------- 3. índice (preenchido no fim, quando as páginas já existem)
    doc.pagina()
    pag_indice = len(d.paginas) - 1
    doc.y = H  # a próxima seção começa noutra página

    # ---------------- 4. mantido
    doc.secao("O que foi mantido", "mantido", "%s arquivos · %s, copiados e conferidos um a um" % (nf(len(ok)), fmt(b_ok)), "ok", VERDE)
    doc.titulo("Por tipo de arquivo")
    doc.tabela([("Tipo", 250, "e"), ("Arquivos", 110, "d"), ("Tamanho", 147, "d")],
               [[CAT_NOME.get(c, c), nf(v[0]), fmt(v[1]), c] for c, v in cats], icones=lambda ln: (CAT_ICO.get(ln[3], "caixa"), cor_cat.get(ln[3], AZUL)))
    por_pasta = collections.defaultdict(lambda: [0, 0])
    for r in ok:
        k = _pasta_de(r[0])
        por_pasta[k][0] += 1
        por_pasta[k][1] += r[3]
    pp = sorted(por_pasta.items(), key=lambda kv: -kv[1][1])[:20]
    if pp:
        doc.titulo("Pastas de origem com mais conteúdo", "As 20 pastas que mais ocupam no backup.")
        doc.barras([("pasta", k, v[1], "%s · %s" % (nf(v[0]), fmt(v[1])), AZUL) for k, v in pp], pp[0][1][1], 230)
    maiores = sorted(ok, key=lambda r: -r[3])[:15]
    if maiores:
        doc.titulo("Os maiores arquivos mantidos")
        doc.tabela([("Arquivo", 330, "e"), ("Tipo", 100, "e"), ("Tamanho", 77, "d")],
                   [[os.path.basename(r[0].replace("\\", "/")), CAT_NOME.get(r[2], r[2]), fmt(r[3]), r[2]] for r in maiores],
                   icones=lambda ln: (CAT_ICO.get(ln[3], "doc"), cor_cat.get(ln[3], AZUL)))

    # ---------------- 5. programas
    doc.secao("Programas para reinstalar", "programas", "%s programa(s) escolhidos para manter depois da formatação" % nf(len(programas)), "apps", AZUL)
    if programas:
        auto = sum(1 for p in programas if p.get("auto"))
        doc.kpis([("PARA REINSTALAR", nf(len(programas)), "", AZUL, "apps"), ("REINSTALAM SOZINHOS", nf(auto), "pelo instalador automático", VERDE, "ok"),
                  ("À MÃO", nf(len(programas) - auto), "site da fabricante ou mídia", AMBAR, "alerta")])
        doc.tabela([("Programa", 200, "e"), ("Fabricante", 120, "e"), ("Reinstala sozinho?", 95, "e"), ("Nota", 92, "e")],
                   [[p.get("nome", ""), p.get("fabricante", ""), "sim" if p.get("auto") else "não, à mão", p.get("nota", ""), p.get("icone") or ""] for p in programas],
                   icones=lambda ln: ("@img", ln[4]) if ln[4] else ("apps", VERDE if ln[2] == "sim" else AMBAR))
    else:
        doc.paragrafo("Nenhum programa foi escolhido para reinstalar neste backup.", 11, MUT)

    # ---------------- 6. ficou de fora
    doc.secao("O que ficou de fora", "fora", "%s arquivos · %s que não foram para o backup, e por quê" % (nf(len(fora)), fmt(b_fora)), "caixa", (0.42, 0.44, 0.52))
    por_sit = collections.defaultdict(lambda: [0, 0])
    por_mot = collections.defaultdict(lambda: [0, 0])
    for r in fora:
        por_sit[r[5]][0] += 1
        por_sit[r[5]][1] += r[3]
        por_mot[(r[5], r[8] or SIT_NOME.get(r[5], r[5]))][0] += 1
        por_mot[(r[5], r[8] or SIT_NOME.get(r[5], r[5]))][1] += r[3]
    if por_sit:
        cor_sit = {"desmarcado": AZUL, "ignorado": MUT, "revisar": AMBAR, "em_uso": (0.55, 0.36, 0.86)}
        ico_sit = {"desmarcado": "x", "ignorado": "caixa", "revisar": "alerta", "em_uso": "cadeado"}
        for s, v in sorted(por_sit.items(), key=lambda kv: -kv[1][1]):
            exp = quebra(SIT_EXPLICA.get(s, ""), W - 2 * MX - 170, 8.5)[:2]
            hc = 30 + 11 * len(exp)
            doc.cabe(hc + 6)
            d.ret(MX, doc.y, W - 2 * MX, hc, fill=FUNDO, r=8)
            icone(d, ico_sit.get(s, "caixa"), MX + 10, doc.y + 9, 22, cor_sit.get(s, MUT))
            d.texto(MX + 42, doc.y + 17, SIT_NOME.get(s, s), 11, True)
            for k, ln in enumerate(exp):
                d.texto(MX + 42, doc.y + 31 + 11 * k, ln, 8.5, False, MUT)
            d.texto(W - MX - 10, doc.y + 17, nf(v[0]) + " arquivos", 10, True, TINTA, "d")
            d.texto(W - MX - 10, doc.y + 31, fmt(v[1]), 9, False, MUT, "d")
            doc.y += hc + 6
        doc.y += 6
        doc.titulo("Por motivo")
        doc.tabela([("Motivo", 330, "e"), ("Arquivos", 80, "d"), ("Tamanho", 97, "d")],
                   [[m, nf(v[0]), fmt(v[1])] for (s, m), v in sorted(por_mot.items(), key=lambda kv: -kv[1][1])[:40]])
    pul = meta.get("ign_dirs") or []
    if pul:
        doc.titulo("Pastas puladas pela varredura", "%s pastas de sistema, caches e lixeira não foram lidas (se recriam sozinhas). Algumas delas:" % nf(meta.get("ign_dirs_total") or len(pul)))
        doc.tabela([("Pasta", 330, "e"), ("Por quê", 177, "e")], [[p[0], p[1]] for p in pul[:60]], icones=lambda ln: ("pasta", MUT))

    # ---------------- 7. erros e avisos
    sw = cert.get("sweep") or {}
    nsw = sum(int(sw.get(k, 0) or 0) for k in ("n_novos", "n_alterados", "n_sumiram"))
    doc.secao("Erros e avisos", "erros", ("%s falha(s) na cópia" % nf(len(falhas))) if falhas else "Nenhuma falha na cópia",
              "x" if falhas else "ok", VERMELHO if falhas else VERDE)
    if falhas:
        doc.paragrafo("Cada arquivo abaixo não chegou ao backup ou não conferiu com o original. A coluna ao lado diz o que fazer.", 10, MUT)
        por_causa = collections.defaultdict(list)
        for r in falhas:
            por_causa[r[11] or "outro"].append(r)
        for causa, rs in sorted(por_causa.items(), key=lambda kv: -len(kv[1])):
            doc.titulo("%s · %s arquivo(s)" % (CAUSA_NOME.get(causa, causa.replace("_", " ").capitalize()), nf(len(rs))), COMO_RESOLVER.get(causa, "Veja a mensagem e tente refazer."))
            doc.tabela([("Arquivo", 300, "e"), ("Mensagem", 140, "e"), ("Tamanho", 67, "d")], [[r[0], r[8], fmt(r[3])] for r in rs[:150]],
                       icones=lambda ln: ("x", VERMELHO))
    else:
        doc.cabe(60)
        d.ret(MX, doc.y, W - 2 * MX, 50, fill=(0.92, 0.97, 0.94), r=10)
        icone(d, "ok", MX + 14, doc.y + 13, 24, VERDE)
        d.texto(MX + 50, doc.y + 22, "Nada se perdeu.", 12, True, VERDE)
        d.texto(MX + 50, doc.y + 37, "Todos os arquivos escolhidos foram copiados e conferidos.", 9.5, False, MUT)
        doc.y += 62
    if nsw:
        doc.titulo("Varredura final na origem", "%s arquivo(s) novo(s), %s alterado(s) e %s que sumiram desde o escaneamento: confira se algum precisa entrar." % (
            nf(sw.get("n_novos")), nf(sw.get("n_alterados")), nf(sw.get("n_sumiram"))))
    ev = cert.get("eventos") or []
    if ev:
        doc.titulo("Avisos durante o backup")
        doc.tabela([("Quando", 90, "e"), ("Aviso", 417, "e")], [[str(e.get("quando", ""))[11:16] or str(e.get("quando", "")), e.get("texto", "")] for e in ev],
                   icones=lambda ln: ("alerta", AMBAR))

    # ---------------- 8. checagens
    chk = meta.get("checagens") or []
    doc.secao("Checagens e conferência", "checagens", cert.get("metodo") or meta.get("verificacao") or "", "engrenagem", (0.3, 0.3, 0.55))
    if chk:
        cor_n = {"ok": VERDE, "aviso": AMBAR, "erro": VERMELHO}
        for c in chk:
            linhas = quebra(c.get("detalhe", ""), W - 2 * MX - 50, 8.5)[:3]
            doc.cabe(24 + 11 * len(linhas))
            icone(d, "ok" if c.get("nivel") == "ok" else "alerta" if c.get("nivel") == "aviso" else "x", MX, doc.y + 2, 16, cor_n.get(c.get("nivel"), MUT))
            d.texto(MX + 24, doc.y + 13, corta(c.get("titulo", ""), W - 2 * MX - 30, 10.5, True), 10.5, True)
            doc.y += 18
            for ln in linhas:
                d.texto(MX + 24, doc.y + 8, ln, 8.5, False, MUT)
                doc.y += 11
            doc.y += 6
    doc.paragrafo("Conferência: %s. Cada arquivo copiado foi relido do disco do backup e comparado com o original; o código do certificado "
                  "é calculado sobre a lista completa (dados.js do Mapa)." % (cert.get("metodo") or meta.get("verificacao") or "—"), 9.5, MUT)

    # ---------------- 9. apêndices
    doc.secao("Apêndice A · Arquivos mantidos", "apendice_a", "Origem na máquina e onde ficou no backup", "doc", (0.2, 0.45, 0.4))
    lista = sorted(ok, key=lambda r: r[0].lower())
    if len(lista) > limite_apendice:
        doc.paragrafo("A lista tem %s arquivos; aqui vão os primeiros %s em ordem alfabética. A lista completa está no Relatorio.csv e no Mapa, na pasta do backup." % (
            nf(len(lista)), nf(limite_apendice)), 9.5, MUT)
    doc.tabela([("Origem", 260, "e"), ("No backup", 187, "e"), ("Tamanho", 60, "d")], [[r[0], r[1], fmt(r[3])] for r in lista[:limite_apendice]], tam=7.5)
    doc.secao("Apêndice B · O que ficou de fora, por pasta", "apendice_b", "Pastas com arquivos que não foram para o backup", "pasta", (0.42, 0.44, 0.52))
    pf = collections.defaultdict(lambda: [0, 0, collections.Counter()])
    for r in fora:
        k = _pasta_de(r[0], 4)
        pf[k][0] += 1
        pf[k][1] += r[3]
        pf[k][2][SIT_NOME.get(r[5], r[5])] += 1
    lf = sorted(pf.items(), key=lambda kv: -kv[1][1])
    doc.tabela([("Pasta", 280, "e"), ("Principal motivo", 117, "e"), ("Arquivos", 50, "d"), ("Tamanho", 60, "d")],
               [[k, v[2].most_common(1)[0][0], nf(v[0]), fmt(v[1])] for k, v in lf[:1500]], tam=7.5, icones=lambda ln: ("pasta", MUT))

    # ---------------- índice e rodapés
    d.p = d.paginas[pag_indice]
    d.destino("indice", TOPO)
    d.texto(MX, TOPO + 20, "Índice", 24, True)
    y = TOPO + 56
    for i, (t, ch, pg) in enumerate(doc.secoes):
        d.ret(MX, y - 14, 26, 20, fill=AZUL if i else (0.3, 0.3, 0.55), r=5)
        d.texto(MX + 13, y, str(i + 1), 10, True, BRANCO, "c")
        d.texto(MX + 38, y, t, 12, True)
        wt = largura(t, 12, True)
        d.linha(MX + 44 + wt, y - 2, W - MX - 32, y - 2, (0.75, 0.77, 0.82), 0.8, True)
        d.texto(W - MX, y, str(pg), 12, True, AZUL, "d")
        d.link(MX, y - 15, W - 2 * MX, 22, ch)
        y += 34
    y += 10
    d.ret(MX, y, W - 2 * MX, 70, fill=FUNDO, r=10)
    d.texto(MX + 16, y + 22, "Como ler este relatório", 11, True)
    for k, ln in enumerate(quebra("Clique num item para ir à seção. No leitor de PDF, os marcadores laterais também levam a cada parte. "
                                  "A lista completa de arquivos fica no Mapa e no Relatorio.csv, na pasta do backup.", W - 2 * MX - 32, 9)):
        d.texto(MX + 16, y + 38 + k * 12, ln, 9, False, MUT)
    tot = len(d.paginas)
    for i, pg in enumerate(d.paginas):
        if i == 0:
            continue
        d.p = pg
        d.linha(MX, H - 34, W - MX, H - 34, LINHA)
        d.texto(MX, H - 22, "Gerado pelo Destrava! em %s" % datetime.datetime.now().strftime("%d/%m/%Y %H:%M"), 8, False, MUT)
        d.texto(W - MX, H - 22, "Página %d de %d" % (i + 1, tot), 8, True, MUT, "d")
        if i > 2:
            d.texto(W / 2.0, H - 22, "Índice", 8, True, AZUL, "c")
            d.link(W / 2.0 - 20, H - 32, 40, 14, "indice")
    d.marcadores.insert(0, ("Índice", "indice"))
    return d.salvar(caminho)
