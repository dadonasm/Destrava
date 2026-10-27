# -*- coding: utf-8 -*-
"""Lista do backup (painel "Ver lista"): tipo, busca por tipo ou caminho, ordem, totais, marcar tudo e prévia por índice."""
import os
import time
import unittest

from nucleo import dd_backup

from tests import test_backup_mapa as tbm


class Lista(unittest.TestCase):
    escanear = tbm.BackupCompleto.escanear

    def setUp(self):
        tbm.BackupCompleto.setUp(self)
        docs = os.path.join(self.disco, "Users", "Ana", "Documents")
        hoje = time.time()
        for nome, tam, dias in (("b_relatorio.docx", 500, 30), ("a_orcamento.xlsx", 50, 400), ("c_apresentacao.pptx", 5000, 2)):
            p = os.path.join(docs, nome)
            tbm.escreve(p, b"x" * tam)
            os.utime(p, (hoje - dias * 86400, hoje - dias * 86400))
        self.itens = self.escanear()

    def tearDown(self):
        tbm.BackupCompleto.tearDown(self)

    def lista(self, **f):
        return self.app.files({k: [str(v)] for k, v in f.items()})

    def nomes(self, r):
        return [x[10] for x in r["rows"]]

    def test_tipo_do_arquivo(self):
        self.assertEqual([dd_backup.tipo_de(n) for n in ("a.PDF", "b.docx", "c.xlsx", "d.pptx", "e.jpg", "f.mov", "g.mp3", "h.zip", "i.psd", "sem_extensao")],
                         ["PDF", "Word", "Planilha", "Apresentação", "Imagem", "Vídeo", "Áudio", "Compactado", "PSD", "Arquivo"])
        self.assertEqual(dd_backup.nome_de("C:\\Users\\Ana\\Documents\\x.pdf"), "x.pdf")

    def test_ordem_por_nome_tamanho_e_data(self):
        docs = dict(cat="Documentos", ord="nome")
        self.assertEqual(self.nomes(self.lista(**docs)), ["a_orcamento.xlsx", "b_relatorio.docx", "c_apresentacao.pptx", "contrato.pdf"])
        self.assertEqual(self.nomes(self.lista(dir="desc", **docs))[0], "contrato.pdf")
        self.assertEqual(self.nomes(self.lista(cat="Documentos", ord="tamanho", dir="desc"))[0], "c_apresentacao.pptx")
        datas = self.nomes(self.lista(cat="Documentos", ord="data", dir="asc"))
        self.assertLess(datas.index("a_orcamento.xlsx"), datas.index("b_relatorio.docx"))
        self.assertLess(datas.index("b_relatorio.docx"), datas.index("c_apresentacao.pptx"))
        r = self.lista(cat="Documentos", ord="nome", offset=1, limit=2)
        self.assertEqual((self.nomes(r), r["total"]), (["b_relatorio.docx", "c_apresentacao.pptx"], 4), "pagina depois de ordenar")

    def test_ordem_por_categoria_e_situacao(self):
        pos = lambda c: dd_backup.PRIORIDADE.index(c) if c in dd_backup.PRIORIDADE else 99
        cats = [pos(x[4]) for x in self.lista(ord="categoria")["rows"]]
        self.assertEqual(cats, sorted(cats), "na ordem de importância, a mesma da cópia")
        self.assertEqual([pos(x[4]) for x in self.lista(ord="categoria", dir="desc")["rows"]], sorted(cats, reverse=True))
        self.app.select({"idx": [self.app.items.index(self.itens["b_relatorio.docx"])], "on": False})
        sts = [x[8] for x in self.lista(ord="situacao")["rows"]]
        self.assertEqual(sts, sorted(sts))
        self.assertIn("desmarcado", sts)

    def test_filtro_por_situacao_e_so_selecionados(self):
        self.app.select({"idx": [self.app.items.index(self.itens["b_relatorio.docx"])], "on": False})
        self.assertNotIn("b_relatorio.docx", self.nomes(self.lista(cat="Documentos", inc=1)))
        self.assertEqual(self.nomes(self.lista(cat="Documentos", status="desmarcado")), ["b_relatorio.docx"])
        r = self.lista(cat="Documentos", inc=1, limit=0)
        self.assertEqual(r["total"], r["sel_n"], "só selecionados: tudo que aparece está marcado")

    def test_facetas_contam_com_os_outros_filtros(self):
        tudo = self.lista(cat="Documentos", facets=1, limit=0)
        tipos = tudo["facets"]["tipo"]
        self.assertEqual((tipos.get("PDF"), tipos.get("Word"), tipos.get("Planilha")), (1, 1, 1))
        so_pdf = self.lista(cat="Documentos", tipo="PDF", facets=1, limit=0)
        self.assertEqual(so_pdf["total"], 1)
        self.assertEqual(so_pdf["facets"]["tipo"], tipos, "marcar PDF não zera as outras opções do mesmo filtro")
        self.assertEqual(so_pdf["facets"]["cat"].get("Documentos"), 1, "as outras facetas já contam só os PDFs")
        self.assertEqual(self.lista(cat="Documentos", tipo="PDF|Word")["total"], 2, "OU dentro do filtro")
        self.assertEqual(self.lista(cat="Documentos|Fotos", tipo="PDF")["total"], 1, "E entre filtros")

    def test_faixas_de_data_e_tamanho(self):
        f = self.lista(cat="Documentos", facets=1, limit=0)["facets"]
        self.assertEqual(f["data"].get("d30"), 3, "contrato.pdf (hoje), b_relatorio (30 dias) e c_apresentacao (2 dias)")
        self.assertEqual(f["data"].get("a3"), 1, "a_orcamento de 400 dias")
        self.assertEqual(self.nomes(self.lista(cat="Documentos", data="a3")), ["a_orcamento.xlsx"])
        self.assertEqual(self.nomes(self.lista(cat="Documentos", smin=1000, ord="nome")), ["c_apresentacao.pptx"])
        self.assertEqual(sorted(self.nomes(self.lista(cat="Documentos", smax=100))), ["a_orcamento.xlsx", "contrato.pdf"])
        self.assertEqual(f["tam"].get("p"), 4, "todos abaixo de 100 KB")

    def test_marcar_todos_respeita_os_filtros_novos(self):
        self.app.select({"filter": {"cat": "Documentos"}, "on": False})
        self.app.select({"filter": {"cat": "Documentos", "tipo": "PDF|Planilha"}, "on": True})
        marcados = sorted(dd_backup.nome_de(it.disp) for it in self.app.items if it.cat == "Documentos" and it.inc)
        self.assertEqual(marcados, ["a_orcamento.xlsx", "contrato.pdf"])
        self.assertEqual(self.lista(cat="Documentos", inc=0, facets=1, limit=0)["facets"]["inc"], {"1": 2, "0": 2})

    def test_linha_traz_nome_tipo_local_e_previa(self):
        x = next(x for x in self.lista(cat="Documentos", ord="nome")["rows"] if x[10] == "contrato.pdf")
        self.assertEqual((x[11], x[12], x[13]), ("PDF", self.itens["contrato.pdf"].local, "pdf"))
        y = next(x for x in self.lista(cat="Documentos")["rows"] if x[10] == "b_relatorio.docx")
        self.assertEqual(y[13], "", "Word não tem prévia")

    def test_totais_do_filtro_e_limit_zero(self):
        r = self.lista(cat="Documentos", limit=0)
        docs = [it for it in self.app.items if it.cat == "Documentos"]
        self.assertEqual(r["rows"], [])
        self.assertEqual((r["total"], r["bytes"]), (len(docs), sum(it.size for it in docs)))
        self.assertEqual((r["sel_n"], r["sel_bytes"]), (sum(1 for it in docs if it.inc), sum(it.size for it in docs if it.inc)))

    def test_busca_por_tipo_ou_caminho(self):
        self.assertEqual(self.nomes(self.lista(q="pdf")), ["contrato.pdf"])
        self.assertEqual(self.nomes(self.lista(q="planilha", cat="Documentos")), ["a_orcamento.xlsx"], "pelo tipo, não pelo nome")
        self.assertIn("foto.jpg", self.nomes(self.lista(q="pictures")))

    def test_marcar_tudo_com_busca_marca_so_o_que_a_lista_mostra(self):
        self.app.select({"filter": {"cat": "Documentos"}, "on": False})
        self.app.select({"filter": {"cat": "Documentos", "q": "Word"}, "on": True})
        marcados = sorted(dd_backup.nome_de(it.disp) for it in self.app.items if it.cat == "Documentos" and it.inc)
        self.assertEqual(marcados, ["b_relatorio.docx"])

    def test_filtro_de_usuario_pega_as_subpastas(self):
        it = self.itens["contrato.pdf"]
        it.local = "TEMP/Ana"
        self.assertIn("contrato.pdf", self.nomes(self.lista(local="TEMP")))
        self.assertNotIn("contrato.pdf", self.nomes(self.lista(local="TEM")))

    def test_previa_so_pelo_indice(self):
        i = self.app.items.index(self.itens["foto.jpg"])
        arq, mime, tipo, limite = self.app.previa(str(i))
        self.assertEqual((arq, mime, tipo, limite), (self.itens["foto.jpg"].src, "image/jpeg", "imagem", None))
        for ruim in ("-1", str(len(self.app.items)), "abc", "", "../etc/passwd"):
            with self.assertRaises(ValueError, msg=ruim):
                self.app.previa(ruim)
        with self.assertRaises(ValueError):
            self.app.previa(str(self.app.items.index(self.itens["planilha.xyz"])))
        self.itens["foto.jpg"].nuvem = True
        with self.assertRaises(ValueError, msg="só na nuvem: abrir baixaria"):
            self.app.previa(str(i))


    def test_destino_de_um_arquivo_nos_jeitos_de_guardar(self):
        """A prévia da faixa de baixo: onde o arquivo fica no Espelho e no Ordenado, e qual vale agora."""
        i = self.app.items.index(self.itens["b_relatorio.docx"])
        d = self.app.destino(i)
        self.assertEqual(d["espelho"], "Pastas_origem/Ana/Documents/b_relatorio.docx")
        self.assertTrue(d["ordenado"].startswith("Ana/Documentos/") and d["ordenado"].endswith("/b_relatorio.docx"), d["ordenado"])
        self.assertEqual((d["atual"], d["copia"]), (d["ordenado"], "ordenar"), "sem modo escolhido vale o ordenado")
        self.app.set_modo("misto")
        self.assertEqual((self.app.destino(i)["atual"], self.app.destino(i)["copia"]), (d["espelho"], "espelhar"), "no Misto começa espelhado")
        with self.assertRaises(ValueError):
            self.app.destino(len(self.app.items))


if __name__ == "__main__":
    unittest.main()
