# -*- coding: utf-8 -*-
"""Modo Superusuário: só funciona ligado, corrige o certificado guardando o original e deixando a edição marcada."""
import hashlib
import json
import os
import shutil
import tempfile
import unittest

from nucleo import dd_backup as D


def mapa_falso(pasta):
    cert = {"status": "ressalvas", "cliente": "Ana", "tecnico": "", "equipamento": "PC-1", "data": "2026-10-26", "hora": "10:00", "codigo": "AAAA-BBBB-CCCC-DDDD"}
    body = "window.BKP=" + json.dumps({"meta": {"cert": cert}, "f": []}, ensure_ascii=False, separators=(",", ":")) + ";"
    with open(os.path.join(pasta, "dados.js"), "w", encoding="utf-8") as fh:
        fh.write(body)
    with open(os.path.join(pasta, "certificado.json"), "w", encoding="utf-8") as fh:
        json.dump({"codigo": cert["codigo"], "dados_js_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "cert": cert}, fh)


class Superusuario(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_su_")
        mapa_falso(self.tmp)
        self._mapa, self._cert = D.APP.mapa_dir, D.APP.cert
        D.APP.mapa_dir, D.APP.cert = self.tmp, None
        self._store = D.FICHA.STORE
        D.FICHA.STORE = os.path.join(self.tmp, "maquinas")  # o histórico da máquina vai para a pasta de teste

    def tearDown(self):
        D.SU["ligado"] = False
        D.FICHA.STORE = self._store
        D.APP.mapa_dir, D.APP.cert = self._mapa, self._cert
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_desligado_recusa(self):
        D.SU["ligado"] = False
        with self.assertRaises(ValueError):
            D.su_certificado_ler()
        with self.assertRaises(ValueError):
            D.su_certificado_salvar({"cliente": "Outro"})

    def test_edita_guarda_original_e_marca(self):
        D.SU["ligado"] = True
        self.assertEqual(D.su_certificado_salvar({"cliente": "Ana Souza", "status": "sem_falhas", "hora": "10:00"})["mudou"], 2)
        for nm in ("certificado.json.bak", "dados.js.bak"):
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, nm)))
        with open(os.path.join(self.tmp, "certificado.json.bak"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["cert"]["cliente"], "Ana")
        with open(os.path.join(self.tmp, "certificado.json"), encoding="utf-8") as fh:
            c = json.load(fh)
        self.assertEqual(c["cert"]["cliente"], "Ana Souza")
        self.assertEqual(c["codigo"], "AAAA-BBBB-CCCC-DDDD")  # o código original não muda
        self.assertEqual(sorted(c["cert"]["editado"][0]["campos"]), ["cliente", "status"])
        self.assertEqual(D.cli_verificar(self.tmp), 0)  # dados.js e certificado.json continuam batendo
        with open(os.path.join(self.tmp, "dados.js"), encoding="utf-8") as fh:
            self.assertIn("Ana Souza", fh.read())

    def test_situacao_invalida(self):
        D.SU["ligado"] = True
        with self.assertRaises(ValueError):
            D.su_certificado_salvar({"status": "perfeito"})

    def test_formatar_forcado_so_com_superusuario(self):
        D.APP.cert = None
        with self.assertRaises(ValueError):
            D.APP.firmware_reboot(True)  # desligado: o bloqueio vale
        D.SU["ligado"] = True
        if D.sys.platform == "darwin":
            with self.assertRaises(ValueError) as cm:  # no Mac o botão não existe, mas já passou do bloqueio
                D.APP.firmware_reboot(True)
            self.assertIn("Mac", str(cm.exception))
        else:
            os.environ["DD_TEST"] = "1"
            self.assertTrue(D.APP.firmware_reboot(True)["simulado"])


if __name__ == "__main__":
    unittest.main()
