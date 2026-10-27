# -*- coding: utf-8 -*-
"""Uma tabela só de tipos de arquivo (classe.py) para o Backup e o Gerenciamento de dados."""
import os
import re
import unittest

from nucleo import classe, dados, dd_backup

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nucleo", "web", "app.html")


class Tabela(unittest.TestCase):
    def test_backup_e_gerenciamento_concordam(self):
        """Toda extensão com categoria pessoal no backup cai no mesmo grupo no Gerenciamento (nada de .doc em "Outros")."""
        par = {"Fotos": "Fotos", "Videos": "Vídeos", "Audios": "Áudios", "Documentos": "Documentos e projetos", "Projetos": "Documentos e projetos",
               "Email_Contatos": "E-mails e contatos", "Contas_Senhas": "Contas e senhas"}
        for ext, cat in dd_backup.EXT2CAT.items():
            self.assertEqual(dados.categoria("a" + ext), par[cat], ext)
        for ext in dd_backup.PROG_EXT - classe.exts("dados", "Outros"):
            self.assertEqual(dados.categoria("a" + ext), "Instaladores e imagens de disco", ext)

    def test_o_que_cada_um_aprendeu_com_o_outro(self):
        c = lambda n: dd_backup.classify_file(n, 10, False)[:2]
        self.assertEqual(c("video.webm"), ("Videos", "copiar"))
        self.assertEqual(c("show.aiff"), ("Audios", "copiar"))
        self.assertEqual(c("casa.blend"), ("Projetos", "copiar"))
        self.assertEqual(c("backup.zip"), ("Outros", "copiar"), "compactado continua como era no backup")
        self.assertEqual(c("windows.iso"), ("Outros", "revisar"), "imagem de disco continua como era no backup")
        self.assertEqual((dados.categoria("relatorio.doc"), classe.faixa_arquivo("relatorio.doc")), ("Documentos e projetos", "documentos"))
        self.assertEqual(dados.categoria("contatos.vcf"), "E-mails e contatos")
        self.assertEqual(dados.categoria("config.ini"), "Outros")

    def test_icones_iguais_aos_da_tela(self):
        """A tela ainda tem o ícone de cada categoria do backup (CATICO): tem de ser o mesmo da tabela."""
        with open(APP, encoding="utf-8") as fh:
            m = re.search(r"const CATICO=\{(.*?)\};", fh.read())
        tela = dict(re.findall(r'(\w+):"([^"]+)"', m.group(1)))
        for cat, v in classe.para_tela()["backup"].items():
            if "ico" in v:
                self.assertEqual(tela.get(cat), v["ico"], cat)


    def test_faixa_e_grupo_pelo_lugar(self):
        self.assertEqual((classe.faixa_arquivo("foto.jpg", "cache"), classe.grupo_arquivo("foto.jpg", "cache")), ("caches", "Cache temporário"))
        self.assertEqual((classe.faixa_arquivo("x.plist", "dados"), classe.grupo_arquivo("x.plist", "dados")), ("dados", "Dados de programas"))
        self.assertEqual(classe.grupo_arquivo("foto.jpg", trava=True), "Bloqueado", "Bloqueado vem antes de tudo")
        self.assertEqual(classe.grupo_arquivo("foto.jpg", nuvem=True), "Só na nuvem")
        self.assertEqual((classe.faixa_arquivo("setup.exe"), classe.grupo_arquivo("setup.exe")), ("outros", "Instaladores"))
        self.assertEqual(classe.grupo_arquivo("Thumbs.db"), "Sistema")
        self.assertEqual(classe.contexto(["Library", "Caches", "x"]), "cache")
        self.assertEqual(classe.contexto(["AppData", "Roaming"]), "dados")
        self.assertEqual(classe.contexto(["Documents"]), "")

    def test_toda_categoria_do_backup_tem_faixa_e_grupo(self):
        t = classe.para_tela()["backup"]
        for cat in dd_backup.CATS_PESSOAIS + ("Outros", "Programas", "Temporarios", "Dados_de_apps", "Ocultos", "Configuracoes", "Sistemas", "Nuvem"):
            self.assertIn(cat, t)
            self.assertIn(t[cat]["grupo"], [g for g, _ in classe.GRUPOS])


if __name__ == "__main__":
    unittest.main()
