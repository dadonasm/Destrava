# -*- coding: utf-8 -*-
"""Inventário de programas: leitura das saídas de cada sistema, duplicados agrupados, runtimes escondidos e programas.json."""
import datetime
import json
import os
import plistlib
import shutil
import tempfile
import unittest

from nucleo import ficha
from nucleo import perfil
from nucleo import programas as P

AQUI = os.path.dirname(os.path.abspath(__file__))


def win():
    with open(os.path.join(AQUI, "fixtures", "win10_programas.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    return P.organizar(P.de_windows(d["progs"], d["appx"], d["winget"]))


def grupo(grupos, nome):
    return next(g for g in grupos if g["nome"] == nome)


class Windows(unittest.TestCase):
    def test_winget_em_portugues_com_nome_cortado(self):
        with open(os.path.join(AQUI, "fixtures", "win10_programas.json"), encoding="utf-8") as fh:
            wg = P.ler_winget(json.load(fh)["winget"])
        self.assertEqual(wg["Google Chrome"], "winget:Google.Chrome")
        self.assertEqual(wg["Microsoft 365 Apps para Grandes Empresa…"], "winget:Microsoft.Office")
        self.assertEqual(wg["WhatsApp"], "msstore:9NKSQGP7F2NH")
        self.assertNotIn("AnyDesk", wg, "ARP\\... não é identificador de instalador")
        self.assertNotIn("Realtek High Definition Audio Driver", wg)

    def test_winget_em_ingles_sem_coluna_disponivel(self):
        t = "Name           Id                  Version  Source\n" + "-" * 50 + "\nNotepad++      Notepad++.Notepad++ 8.6      winget\n"
        self.assertEqual(P.ler_winget(t), {"Notepad++": "winget:Notepad++.Notepad++"})
        self.assertEqual(P.ler_winget("winget não encontrou nada"), {})

    def test_duplicados_agrupados(self):
        g = win()
        z = grupo(g, "7-Zip")
        self.assertEqual((z["versoes"], z["arch"], z["variantes"]), (["22.01", "23.01"], ["32", "64"], 2), "32 e 64 bits, duas versões")
        self.assertEqual(z["ids"], {"winget": "7zip.7zip"})
        py = grupo(g, "Python")
        self.assertEqual(py["versoes"], ["3.11.4150.0", "3.12.150.0"])
        self.assertEqual(len([x for x in g if x["nome"].startswith("Microsoft Visual C++ 2015-2022 Redistributable")]), 1)

    def test_identificadores_de_instalador(self):
        g = win()
        self.assertEqual(grupo(g, "Google Chrome")["ids"], {"winget": "Google.Chrome"})
        self.assertEqual(grupo(g, "Microsoft 365 Apps para Grandes Empresas - pt-br")["ids"], {"winget": "Microsoft.Office"}, "nome cortado pelo winget")
        self.assertEqual(grupo(g, "Adobe Acrobat Reader DC")["ids"], {"winget": "Adobe.Acrobat.Reader.64-bit"})
        self.assertEqual(grupo(g, "WhatsAppDesktop")["ids"], {"msstore": "9NKSQGP7F2NH"})
        self.assertEqual(grupo(g, "AnyDesk")["ids"], {}, "sem identificador: reinstala à mão")
        self.assertEqual(grupo(g, "Microsoft Edge Update")["ids"], {}, "não pega o id do Edge só pelo começo do nome")
        self.assertEqual(grupo(g, "WhatsAppDesktop")["fabricante"], "", "CN que é só um GUID não vira fabricante")

    def test_runtimes_drivers_e_componentes_escondidos(self):
        g = win()
        esperado = {"Microsoft Visual C++ 2015-2022 Redistributable": "runtime", "Microsoft Visual C++ 2022 Minimum Runtime": "componente do sistema",
                    "Intel® Graphics Driver": "driver", "Realtek High Definition Audio Driver": "driver",
                    "Update for Windows 10 for x64-based Systems (KB5001716)": "atualização", "Dell SupportAssist": "componente da fabricante",
                    "Office 16 Click-to-Run Extensibility Component": "componente do sistema", "Python Core Interpreter": "componente do sistema",
                    "Componente filho": "componente do sistema", "Microsoft Edge Update": "componente do sistema", "WindowsCalculator": "vem com o sistema"}
        for nome, motivo in esperado.items():
            x = grupo(g, nome)
            self.assertEqual((x["oculto"], x["motivo"]), (True, motivo), nome)
        vis = {x["nome"] for x in P.visiveis(g)}
        self.assertEqual(vis, {"7-Zip", "Google Chrome", "Microsoft 365 Apps para Grandes Empresas - pt-br", "Adobe Acrobat Reader DC", "AnyDesk",
                               "Python", "Microsoft Edge", "Spotify", "WhatsAppDesktop"})
        self.assertEqual(len(P.visiveis(g, tudo=True)), len(g), "mostrar tudo devolve a lista inteira")
        self.assertEqual([x["oculto"] for x in g], sorted(x["oculto"] for x in g), "visíveis primeiro")

    def test_nada_de_licenca_nem_senha(self):
        d = P.documento(P.de_windows([{"n": "Programa", "v": "1", "p": "X", "k": "K", "ProductID": "XXXXX-12345", "senha": "123", "s": 0}]), "windows")
        self.assertEqual(set(d["itens"][0]), {"nome", "versoes", "fabricante", "origens", "ids", "arch", "oculto", "motivo", "variantes"})
        self.assertNotIn("12345", json.dumps(d))
        self.assertNotIn("123\"", json.dumps(d))


class Mac(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_apps_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self, pasta, nome, info, loja=False):
        c = os.path.join(self.tmp, pasta, nome + ".app", "Contents")
        os.makedirs(c)
        with open(os.path.join(c, "Info.plist"), "wb") as fh:
            plistlib.dump(info, fh)
        if loja:
            os.makedirs(os.path.join(c, "_MASReceipt"))

    def test_aplicativos_com_versao_fabricante_e_origem(self):
        self.app("A", "Google Chrome", {"CFBundleIdentifier": "com.google.Chrome", "CFBundleShortVersionString": "120.0", "NSHumanReadableCopyright": "Copyright 2023 Google LLC. All rights reserved."})
        self.app("A", "Pages", {"CFBundleIdentifier": "com.apple.iWork.Pages", "CFBundleShortVersionString": "13.2"}, loja=True)
        self.app("A", "Safari", {"CFBundleIdentifier": "com.apple.Safari", "CFBundleShortVersionString": "17.1"})
        self.app("A", "Gemini", {"CFBundleIdentifier": "com.apple.Safari.WebApp.ABC"})
        self.app("A/Adobe Photoshop 2024", "Adobe Photoshop 2024", {"CFBundleIdentifier": "com.adobe.Photoshop", "CFBundleShortVersionString": "25.0"})
        g = P.organizar(P.de_mac([os.path.join(self.tmp, "A")]))
        c = grupo(g, "Google Chrome")
        self.assertEqual((c["versoes"], c["fabricante"], c["origens"], c["oculto"]), (["120.0"], "Google LLC", ["Aplicativos"], False))
        self.assertEqual((grupo(g, "Pages")["origens"], grupo(g, "Pages")["oculto"]), (["App Store"], False), "app da Apple pela App Store aparece")
        self.assertEqual(grupo(g, "Safari")["motivo"], "vem com o sistema")
        self.assertEqual(grupo(g, "Gemini")["motivo"], "atalho de site (Safari)")
        self.assertEqual(grupo(g, "Adobe Photoshop 2024")["fabricante"], "Adobe", "dentro de uma pasta; fabricante pelo identificador")

    def test_homebrew(self):
        self.app("A", "Visual Studio Code", {"CFBundleIdentifier": "com.microsoft.VSCode"})
        e = P.de_mac([os.path.join(self.tmp, "A")])
        casks, formulas = P.ler_brew("visual-studio-code 1.85.1\nfirefox 121.0\n", "git 2.43.0\nopenssl@3 3.2.0\n", "git\n")
        g = P.organizar(P.com_brew(e, casks, formulas))
        self.assertEqual(grupo(g, "Visual Studio Code")["ids"], {"brew": "visual-studio-code"}, "cask casa com o .app")
        self.assertEqual(grupo(g, "firefox")["origens"], ["Homebrew"])
        self.assertEqual(grupo(g, "git")["ids"], {"brew": "git"})
        self.assertFalse(any(x["nome"].startswith("openssl") for x in g), "dependência do Homebrew não entra")


class Linux(unittest.TestCase):
    def test_apt_so_o_que_foi_instalado_a_mao_e_tem_janela(self):
        q = "gimp\t2.10.34-1\tii \nlibgimp2.0\t2.10.34-1\tii \nfirefox\t120.0\tii \nhtop\t3.2.2-2\tii \nvlc\t3.0.20\trc \n"
        e = P.de_dpkg(q, P.ler_auto("Package: libgimp2.0\nArchitecture: amd64\nAuto-Installed: 1\n"), P.ler_pacotes_status("Package: firefox\nStatus: install ok installed\n"),
                      {"gimp": ["GNU Image Manipulation Program"], "firefox": ["Firefox Web Browser"]})
        g = {x["nome"]: x for x in P.organizar(e)}
        self.assertEqual((g["GNU Image Manipulation Program"]["oculto"], g["GNU Image Manipulation Program"]["ids"]), (False, {"apt": "gimp"}))
        self.assertEqual(g["libgimp2.0"]["motivo"], "dependência")
        self.assertEqual(g["Firefox Web Browser"]["motivo"], "vem com o sistema")
        self.assertEqual(g["htop"]["motivo"], "sem janela (linha de comando ou biblioteca)")
        self.assertNotIn("vlc", g, "removido (rc) não conta")

    def test_flatpak_e_snap(self):
        f = P.ler_flatpak("org.telegram.desktop\tTelegram Desktop\t4.14.2\tflathub\ncom.spotify.Client\tSpotify\t1.2.25\tflathub\n")
        self.assertEqual([(x["nome"], x["id"]) for x in f], [("Telegram Desktop", "flatpak:org.telegram.desktop"), ("Spotify", "flatpak:com.spotify.Client")])
        s = P.ler_snap("Name      Version   Rev    Tracking       Publisher   Notes\ncore22    20231123  1033   latest/stable  canonical✓  base\n"
                       "firefox   121.0     3504   latest/stable  mozilla✓    -\nsnapd     2.60.4    20290  latest/stable  canonical✓  snapd\n")
        g = {x["nome"]: x for x in P.organizar(s)}
        self.assertEqual((g["firefox"]["oculto"], g["firefox"]["ids"], g["firefox"]["fabricante"]), (False, {"snap": "firefox"}, "mozilla"))
        self.assertTrue(g["core22"]["oculto"] and g["snapd"]["oculto"])


class Gravacao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_prog_")
        self._store, self._pasta = ficha.STORE, perfil.PASTA
        ficha.STORE, perfil.PASTA = os.path.join(self.tmp, "maquinas"), self.tmp

    def tearDown(self):
        ficha.STORE, perfil.PASTA = self._store, self._pasta
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_analise_grava_programas_json_e_a_ficha_fica_leve(self):
        with open(os.path.join(AQUI, "fixtures", "win10_hd.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        with open(os.path.join(AQUI, "fixtures", "win10_programas.json"), encoding="utf-8") as fh:
            p = json.load(fh)
        raw = dict(d["raw"], progs=p["progs"], appx=p["appx"], winget=p["winget"])
        f = ficha.normalizar_windows(raw, d["medidas"])
        f.update(mid="DD-TESTE-0001", quando=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        ficha.salvar_ficha(f, "antes")
        doc = ficha.programas_de("DD-TESTE-0001")
        self.assertEqual((doc["familia"], doc["visiveis"]), ("windows", 9))
        self.assertEqual(doc["com_instalador"], 6)
        arq = [x for x in os.listdir(ficha.pasta("DD-TESTE-0001")) if x.startswith("ficha-")][0]
        with open(os.path.join(ficha.pasta("DD-TESTE-0001"), arq), encoding="utf-8") as fh:
            self.assertNotIn("programas", json.load(fh))
        self.assertEqual(ficha.visao("DD-TESTE-0001")["programas"]["visiveis"], 9)
        ficha.salvar_ficha(dict(f, programas=[P.entrada("Só depois", "1")]), "depois")
        self.assertEqual(ficha.programas_de("DD-TESTE-0001")["visiveis"], 9, "a medição depois das melhorias não troca a lista")

    def test_fixture_antigo_continua_igual(self):
        with open(os.path.join(AQUI, "fixtures", "win10_hd.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        self.assertNotIn("programas", ficha.normalizar_windows(d["raw"], d["medidas"]), "coleta antiga, sem progs: sem lista")


if __name__ == "__main__":
    unittest.main()
