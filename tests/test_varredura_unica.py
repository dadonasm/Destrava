# -*- coding: utf-8 -*-
"""Uma varredura vale para os dois modos: a lista da Seleção fica guardada (trocar de modo ou reabrir o programa não varre de novo)
e o Gerenciamento, ao terminar de varrer, puxa a Seleção deste computador (e vice-versa, sem ficar um puxando o outro)."""
import os
import unittest
from unittest import mock

from nucleo import dd_backup

from tests import test_backup_mapa as tbm


class VarreduraGuardada(unittest.TestCase):
    escanear = tbm.BackupCompleto.escanear

    def setUp(self):
        tbm.BackupCompleto.setUp(self)
        self.snap = os.path.join(self.tmp, "selecao.json.gz")
        self._p = mock.patch.object(dd_backup.App, "snap_arquivo", staticmethod(lambda: self.snap))
        self._p.start()
        self.app.persistir = True
        self.cfg = {"sources": [{"path": self.disco, "kind": "windows", "letter": "C"}], "dest": self.dest, "folder": "Backup_Ana", "cliente": "Ana"}

    def tearDown(self):
        self._p.stop()
        tbm.BackupCompleto.tearDown(self)

    def reaberto(self, cfg=None):
        """O programa fechado e aberto de novo: memória vazia, mesma configuração."""
        novo = dd_backup.App()
        novo.persistir = True
        novo.set_config(cfg or self.cfg)
        return novo

    def test_reabrir_nao_varre_de_novo(self):
        antes = self.escanear()
        self.assertTrue(os.path.isfile(self.snap), "guardada no fim da varredura")
        novo = self.reaberto()
        self.assertEqual(novo.start_scan(reaproveitar=True), "restaurado")
        self.assertEqual(novo.phase, "scanned")
        depois = {os.path.basename(it.src): it for it in novo.items}
        self.assertEqual(sorted(depois), sorted(antes))
        for k, it in antes.items():
            for campo in dd_backup.SNAP_CAMPOS:
                self.assertEqual(getattr(depois[k], campo), getattr(it, campo), "%s.%s" % (k, campo))
        self.assertEqual(novo.scan_quando, self.app.scan_quando, "a hora é a da varredura original")
        self.assertEqual(novo.totals()["sel_n"], self.app.totals()["sel_n"])

    def test_marcacoes_e_jeito_de_guardar_voltam(self):
        it = self.escanear()
        i = self.app.items.index(it["contrato.pdf"])
        self.app.select({"idx": [i], "on": False})
        self.app.set_modo("misto")
        self.assertTrue(self.app.salvar_varredura())
        novo = self.reaberto()
        novo.start_scan(reaproveitar=True)
        x = next(y for y in novo.items if y.src == it["contrato.pdf"].src)
        self.assertFalse(x.inc, "desmarcado continua desmarcado")
        self.assertEqual(novo.layout_modo, "misto")

    def test_outra_origem_ou_outra_versao_varre(self):
        self.escanear()
        outro = os.path.join(self.tmp, "D")
        tbm.escreve(os.path.join(outro, "Users", "Bia", "Documents", "x.pdf"), b"%PDF")
        os.makedirs(os.path.join(outro, "Windows"))
        novo = self.reaberto(dict(self.cfg, sources=[{"path": outro, "kind": "windows", "letter": "D"}]))
        self.assertEqual(novo.start_scan(reaproveitar=True), "varrendo")
        self.assertEqual(tbm.espera(novo, ("scanned", "error")), "scanned")
        with mock.patch.object(dd_backup, "BUILD", "outra-versao"):
            v = self.reaberto()
            self.assertEqual(v.start_scan(reaproveitar=True), "varrendo", "outra versão pode classificar diferente")
            self.assertEqual(tbm.espera(v, ("scanned", "error")), "scanned")

    def test_sem_reaproveitar_varre(self):
        self.escanear()
        novo = self.reaberto()
        self.assertEqual(novo.start_scan(), "varrendo", "Escanear de novo continua varrendo")
        self.assertEqual(tbm.espera(novo, ("scanned", "error")), "scanned")

    def test_destino_dentro_da_origem_fica_de_fora(self):
        self.escanear()
        dentro = os.path.join(self.disco, "Users", "Ana", "Documents")
        novo = self.reaberto(dict(self.cfg, dest=dentro))
        novo.start_scan(reaproveitar=True)
        self.assertFalse(any(dd_backup._dentro(it.src, novo.dest_root) for it in novo.items))

    def test_so_o_programa_de_verdade_guarda(self):
        self.app.persistir = False
        self.escanear()
        self.assertFalse(os.path.exists(self.snap))
        novo = self.reaberto()
        self.assertEqual(novo.start_scan(reaproveitar=True), "varrendo")
        self.assertEqual(tbm.espera(novo, ("scanned", "error")), "scanned")

    def test_nao_guarda_depois_que_a_copia_comeca(self):
        it = self.escanear()
        it["contrato.pdf"].status = "ok"
        self.assertFalse(self.app.salvar_varredura())

    def test_novo_backup_apaga(self):
        self.escanear()
        self.app.apagar_varredura()
        self.assertFalse(os.path.exists(self.snap))


class Encadeamento(unittest.TestCase):
    def setUp(self):
        tbm.BackupCompleto.setUp(self)
        self.app.persistir = True
        self._p = [mock.patch.object(dd_backup.App, "snap_arquivo", staticmethod(lambda: os.path.join(self.tmp, "s.json.gz"))),
                   mock.patch.object(dd_backup, "TERMO", None)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()
        dd_backup.ENCADEADO["dados"] = False
        tbm.BackupCompleto.tearDown(self)

    def test_gerenciamento_nao_puxa_backup_de_outro_disco(self):
        self.assertFalse(self.app._fontes_locais(), "o disco de mentira não é o deste computador")
        self.assertFalse(self.app.encadear_selecao())
        self.assertEqual(self.app.phase, "idle")

    def test_gerenciamento_puxa_a_selecao_sem_origem_escolhida(self):
        app = dd_backup.App()
        app.persistir = True
        fonte = {"path": self.disco, "kind": "windows", "letter": "C", "label": "C"}
        with mock.patch.object(dd_backup, "list_sources", lambda *a, **k: [fonte, {"path": self.dest, "kind": "plain", "letter": "", "label": "HD"}]):
            self.assertTrue(app.encadear_selecao())
        self.assertEqual(tbm.espera(app, ("scanned", "error")), "scanned", app.error)
        self.assertEqual([s["path"] for s in app.cfg["sources"]], [self.disco], "só os sistemas, como a Seleção escolheria")
        self.assertTrue(app.items)
        self.assertFalse(app.encadeado)

    def test_nao_mexe_em_backup_em_andamento(self):
        tbm.BackupCompleto.escanear(self)
        self.app.items[0].status = "ok"
        with mock.patch.object(self.app, "_fontes_locais", lambda: True):
            self.assertFalse(self.app.encadear_selecao(), "a cópia começou: a lista não pode ser trocada")

    def test_selecao_puxada_pelo_gerenciamento_nao_puxa_de_volta(self):
        with mock.patch.object(self.app, "_fontes_locais", lambda: True), mock.patch.object(self.app, "encadear_gerenciamento") as eg:
            self.assertTrue(self.app.encadear_selecao())
            self.assertEqual(tbm.espera(self.app, ("scanned", "error")), "scanned")
            eg.assert_not_called()
            self.app.start_scan()
            self.assertEqual(tbm.espera(self.app, ("scanned", "error")), "scanned")
            eg.assert_called_once_with()

    def test_gerenciamento_puxado_pela_selecao_nao_puxa_de_volta(self):
        with mock.patch.object(dd_backup.APP, "encadear_selecao") as es:
            dd_backup.ENCADEADO["dados"] = True
            dd_backup._gerenciamento_varreu()
            es.assert_not_called()
            self.assertFalse(dd_backup.ENCADEADO["dados"])
            dd_backup._gerenciamento_varreu()
            es.assert_called_once_with()

    def test_selecao_puxa_o_gerenciamento_so_se_o_indice_e_velho(self):
        self.app.scan_quando = 10000.0
        with mock.patch.object(self.app, "_fontes_locais", lambda: True), \
                mock.patch.object(dd_backup.DADOS, "iniciar_varredura") as iv, mock.patch.dict(dd_backup.DADOS.ST, {"fase": "pronto"}):
            with mock.patch.object(dd_backup.DADOS, "indice_estado", lambda: {"existe": True, "quando": 9500.0, "idle_dias": 60, "min_mb": 50}):
                self.assertFalse(self.app.encadear_gerenciamento(), "índice de 8 min antes: ainda vale")
            with mock.patch.object(dd_backup.DADOS, "indice_estado", lambda: {"existe": True, "quando": 1000.0, "idle_dias": 60, "min_mb": 50}):
                self.assertTrue(self.app.encadear_gerenciamento())
            iv.assert_called_once_with(60, 50)
            self.assertTrue(dd_backup.ENCADEADO["dados"], "no fim, o Gerenciamento não puxa a Seleção de volta")


if __name__ == "__main__":
    unittest.main()
