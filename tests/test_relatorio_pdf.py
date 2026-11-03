# -*- coding: utf-8 -*-
"""Relatório do backup em PDF (nucleo/relatorio_pdf.py): o arquivo sai inteiro, com capa, resumo, índice clicável e marcadores."""
import os
import re
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nucleo"))
import relatorio_pdf as R  # noqa: E402


def linha(origem, cat, tam, sit, motivo="", causa=""):
    return [origem, ("Pastas_origem/" + origem.lstrip("/")) if sit in ("ok", "falha") else "", cat, tam, "2026-05-01", sit, "", "ana", motivo, "", 0, causa]


META = {"pc": "PC-1", "data": "2026-11-03", "raiz": "/Volumes/HD/Backup_Ana", "verificacao": "SHA-256 (completa)",
        "checagens": [{"nivel": "ok", "titulo": "Origem lida", "detalhe": "Só leitura."}], "layout": {"espelhados": 2, "ordenados": 1},
        "ign_dirs": [["/Users/ana/Library/Caches", "Cache: se recria sozinho."]], "ign_dirs_total": 1,
        "cert": {"status": "ressalvas", "cliente": "Ana", "tecnico": "Téc", "equipamento": "PC-1", "hora": "10:00", "codigo": "AAAA-BBBB-CCCC-DDDD",
                 "metodo": "SHA-256", "eventos": [], "sweep": {"n_novos": 0, "n_alterados": 0, "n_sumiram": 0}}}
F = [linha("/Users/ana/Fotos/praia ção.jpg", "Fotos", 2000000, "ok"), linha("/Users/ana/Docs/contrato (1).pdf", "Documentos", 300000, "ok"),
     linha("/Users/ana/Docs/velho.doc", "Documentos", 1000, "desmarcado", "Desmarcado por você na seleção"),
     linha("/Users/ana/Docs/travado.xlsx", "Documentos", 5000, "falha", "ERRO: Permissão negada", "permissao")]


class Relatorio(unittest.TestCase):
    def gera(self, f=F, **kw):
        d = tempfile.mkdtemp()
        p = R.gerar(os.path.join(d, "r.pdf"), META, f, [{"nome": "Google Chrome", "fabricante": "Google", "auto": True, "nota": ""}], **kw)
        with open(p, "rb") as fh:
            return fh.read()

    def test_arquivo_pdf_valido(self):
        b = self.gera()
        self.assertTrue(b.startswith(b"%PDF-1.4"))
        self.assertTrue(b.rstrip().endswith(b"%%EOF"))
        xref = int(re.search(rb"startxref\n(\d+)\n", b).group(1))
        self.assertEqual(b[xref:xref + 4], b"xref", "startxref aponta para a tabela xref")
        n = int(re.search(rb"/Type /Pages /Kids \[[^\]]*\] /Count (\d+)", b).group(1))
        self.assertEqual(n, len(re.findall(rb"/Type /Page ", b)))
        self.assertGreaterEqual(n, 8, "capa, resumo, índice e as seções")
        self.assertIn(b"/Outlines", b, "marcadores do leitor")
        self.assertIn(b"/Subtype /Link", b, "índice clicável")

    def test_texto_com_acentos_e_parenteses(self):
        b = self.gera()
        txt = b"".join(zlib.decompress(m) for m in re.findall(rb"stream\n(.*?)\nendstream", b, re.S))
        self.assertIn("Relatório do backup".encode("cp1252"), txt)
        self.assertIn(b"contrato \\(1\\).pdf", txt, "parênteses escapados")
        self.assertIn("Sem permissão de leitura".encode("cp1252"), txt, "falha agrupada pela causa, com nome legível")

    def test_lista_grande_respeita_o_limite(self):
        muitos = [linha("/Users/ana/x/a%05d.txt" % i, "Outros", 10, "ok") for i in range(400)]
        b = self.gera(muitos, limite_apendice=50)
        txt = b"".join(zlib.decompress(m) for m in re.findall(rb"stream\n(.*?)\nendstream", b, re.S))
        self.assertIn(b"a00049.txt", txt)
        self.assertNotIn(b"a00399.txt", txt.split(b"Ap\xeandice A")[-1].split(b"Ap\xeandice B")[0], "passou do limite do apêndice")

    def test_largura_e_corte(self):
        self.assertAlmostEqual(R.largura("a", 10), 5.56)
        self.assertEqual(R.largura("á", 10), R.largura("a", 10), "acento usa a largura da letra-base")
        c = R.corta("/Users/ana/uma/pasta/muito/longa/arquivo.txt", 80, 9)
        self.assertIn("…", c)
        self.assertLessEqual(R.largura(c, 9), 80)


if __name__ == "__main__":
    unittest.main()
