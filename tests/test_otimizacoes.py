# -*- coding: utf-8 -*-
"""Rodada D: Central de Otimizações (detecção nos três sistemas, ganho, nota simulada, aplicar e desfazer)."""
import copy
import json
import os
import shutil
import tempfile
import unittest

import ficha
import otimizacoes as O

AQUI = os.path.dirname(os.path.abspath(__file__))


def ficha_win():
    with open(os.path.join(AQUI, "fixtures", "win10_hd.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    return ficha.normalizar_windows(d["raw"], d["medidas"])


class Windows(unittest.TestCase):
    def setUp(self):
        self.f = ficha_win()
        self.sug = {s["id"]: s for s in O.sugestoes(self.f, {"tam_temp_mb": 1500})}

    def test_inicializacao_igual_ao_gerenciador(self):
        ini = self.f["inicializacao_todos"]
        self.assertEqual(len(ini), 6)
        self.assertEqual(len(self.f["inicializacao"]), 5, "a nota conta só os ativos")
        nomes = {x["nome"] for x in ini}
        self.assertIn("MSTeams", nomes, "app da Store aparece")
        self.assertIn("Send to OneNote", nomes, "pasta Inicializar aparece")
        spot = [s for s in self.sug.values() if s["titulo"].endswith("Spotify")][0]
        self.assertTrue(spot["aplicavel"] and spot["recomendado"] and spot["marcado"])
        self.assertIn("300 MB", spot["ganho"]["texto"])
        self.assertIn("4.2 s no boot", spot["ganho"]["texto"])
        one = [s for s in self.sug.values() if s["titulo"].endswith("Send to OneNote")][0]
        self.assertTrue(one["aplicavel"], "item da pasta Inicializar agora desativa pelo programa")
        seg = [s for s in self.sug.values() if s["titulo"].endswith("SecurityHealth")][0]
        self.assertTrue(seg["onus"] and not seg["marcado"], "antivírus: aparece, mas com ⚠ e desmarcado")
        adobe = [s for s in self.sug.values() if "Adobe" in s["titulo"]][0]
        self.assertEqual(adobe["estado"], "desativado")
        self.assertTrue(adobe["acao"]["ligar"])

    def test_catalogo(self):
        for i in ("win.visual", "win.temp", "win.energia", "win.hiber", "win.sysmain", "win.wsearch", "win.bgapps", "win.dicas", "win.gamedvr",
                  "win.p2p", "win.sensor", "win.tarefas", "win.disco", "win.dism", "win.onedrive", "dados"):
            self.assertIn(i, self.sug, i)
        self.assertIsNone(self.sug["win.dicas"]["onus"])
        self.assertTrue(self.sug["win.dicas"]["marcado"])
        self.assertTrue(self.sug["win.hiber"]["onus"])
        self.assertFalse(self.sug["win.hiber"]["marcado"], "com ônus nunca vem marcado")
        self.assertIn("3.2 GB", self.sug["win.hiber"]["ganho"]["texto"])
        self.assertFalse(self.sug["win.temp"]["reversivel"])
        self.assertEqual(self.sug["dados"]["botao"]["nav"], "dados")

    def test_pontos_e_resumo(self):
        sug = list(self.sug.values())
        r = O.com_pontos(self.f, sug)
        self.assertGreater(r["n"], 3)
        self.assertGreater(r["pontos"], 0)
        spot = [s for s in sug if s["titulo"].endswith("Spotify")][0]
        self.assertGreater(spot["pontos"], 0)
        self.assertRegex(spot["ganho"]["texto"], r"\+\d+ pontos? na nota")

    def test_ficha_antiga_ainda_funciona(self):
        f = copy.deepcopy(self.f)
        for k in ("inicializacao_todos", "otim"):
            f.pop(k)
        f["inicializacao"] = [{"nome": "Spotify", "comando": "\"C:\\x\\Spotify.exe\"", "local": "HKU\\S-1-5\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"}]
        s = [x for x in O.sugestoes(f) if x["titulo"].endswith("Spotify")][0]
        self.assertTrue(s["aplicavel"])
        self.assertEqual(s["acao"]["item"]["hive"], "HKCU:")


class MacELinux(unittest.TestCase):
    def ficha(self, familia, otim, **kw):
        f = {"so": {"familia": familia, "live": kw.get("live", False)}, "ram": {"total_gb": 4, "livre_gb": 1}, "discos": [{"tipo": kw.get("disco", "SSD"), "tam_gb": 250}],
             "volumes": [{"id": "/", "tam_gb": 250, "livre_gb": 20}], "medidas": {"cpu_ms": 400}, "inicializacao": [], "inicializacao_todos": kw.get("ini", []), "otim": otim, "gpu": []}
        return f

    def test_mac_armazenamento(self):
        f = self.ficha("mac", {"movimento": {"reduceMotion": "0", "reduceTransparency": None}, "purgavel": 6e9, "snapshots": 3,
                               "iphone": [{"nome": "iPhone da Ana", "data": "2026-09-01", "bytes": 28e9, "path": "/x"}], "icloud": 4e9,
                               "xcode": {"path": "/y", "bytes": 9e9}, "brew": None, "docker": {"bytes": 30e9}, "spotlight": [{"vol": "/Volumes/HD", "ligado": True}]},
                       ini=[{"id": "a", "nome": "com.google.keystone.agent", "comando": "/x/GoogleSoftwareUpdateAgent", "fonte": "agente", "ativo": True, "arquivo": "/p.plist", "label": "com.google.keystone.agent"}])
        sug = {s["id"].split(":")[0] if s["id"].startswith("mac.spotlight") else s["id"]: s for s in O.sugestoes(f)}
        for i in ("mac.movimento", "mac.snapshots", "mac.iphone", "mac.icloud", "mac.armazenamento", "mac.xcode", "mac.docker", "mac.spotlight", "dados"):
            self.assertIn(i, sug, i)
        self.assertIn("28.0 GB", sug["mac.iphone"]["ganho"]["texto"])
        self.assertFalse(sug["mac.iphone"]["aplicavel"], "backup de iPhone: move pela aba Dados")
        self.assertEqual(sug["mac.icloud"]["botao"]["abrir"], "ajustes_armazenamento")
        agente = [s for s in O.sugestoes(f) if "keystone" in s["titulo"]][0]
        self.assertTrue(agente["aplicavel"])

    def test_linux_zram_e_live(self):
        f = self.ficha("linux", {"zramctl": True, "zram_ativo": False, "animacoes": "true", "tracker": "enabled", "fstrim": "disabled", "apt_cache": 4e8, "journal": 9e8}, disco="HDD")
        sug = {s["id"]: s for s in O.sugestoes(f)}
        self.assertTrue(sug["lin.zram"]["recomendado"])
        self.assertTrue(sug["lin.zram"]["onus"])
        self.assertIn("estimado", sug["lin.zram"]["ganho"]["origem"])
        self.assertTrue(sug["lin.tracker"]["recomendado"], "HD: indexador atrapalha")
        self.assertNotIn("lin.fstrim", sug, "TRIM é para SSD")
        live = O.sugestoes(self.ficha("linux", {"live": True}, live=True))
        self.assertEqual([s["id"] for s in live], ["lin.live"])
        self.assertFalse(live[0]["aplicavel"])


class AplicarEDesfazer(unittest.TestCase):
    """Sem mexer no computador: o PowerShell é trocado por um dublê."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_otim_")
        self._store, self._win, self._psj = ficha.STORE, O.IS_WIN, O._ps_json
        ficha.STORE = self.tmp
        O.IS_WIN = True
        self.chamadas = []
        self.f = ficha_win()
        self.mid = "DD-TEST-OTIM"

    def tearDown(self):
        ficha.STORE, O.IS_WIN, O._ps_json = self._store, self._win, self._psj
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dubla(self, resposta):
        def fake(script, env=None, timeout=90):
            self.chamadas.append((script, env))
            return resposta(script, env) if callable(resposta) else resposta
        O._ps_json = fake

    def test_desligar_item_da_store_e_desfazer(self):
        self.dubla({"ok": True, "prev": 2})
        teams = [s for s in O.sugestoes(self.f) if s["titulo"].endswith("MSTeams")][0]
        r = ficha.aplicar(self.mid, [teams["id"]], self.f)
        self.assertTrue(r[0]["ok"])
        self.assertEqual(self.chamadas[0][1]["estado"], 1, "State=1 (desativado pelo usuário), como o Gerenciador de Tarefas")
        self.assertEqual([a["id"] for a in ficha.aplicadas(self.mid)], [teams["id"]])
        self.assertEqual(ficha.desfazer(self.mid, [teams["id"]]), 1)
        self.assertEqual(self.chamadas[-1][1]["estado"], 2, "volta ao estado anterior")
        self.assertEqual(ficha.aplicadas(self.mid), [])

    def test_reversao_que_falha_continua_na_lista(self):
        self.dubla(lambda script, env: {"ok": True, "prev": [{"k": "HKCU:\\x", "n": "y", "t": "DWord", "v": 1, "existe": True}]})
        ficha.aplicar(self.mid, ["win.dicas"], self.f)
        self.dubla(None)  # o Windows não respondeu ao desfazer
        self.assertEqual(ficha.desfazer(self.mid), 0)
        self.assertEqual(len(ficha.aplicadas(self.mid)), 1, "dá para tentar desfazer de novo")
        self.dubla({"ok": True})
        self.assertEqual(ficha.desfazer(self.mid), 1)

    def test_indisponivel(self):
        r = ficha.aplicar(self.mid, ["dados", "nao-existe"], self.f)
        self.assertEqual([x["ok"] for x in r], [False, False])


if __name__ == "__main__":
    unittest.main()
