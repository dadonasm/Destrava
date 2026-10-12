# -*- coding: utf-8 -*-
"""Registro de máquinas: etapa por máquina (automática e manual), máquinas antigas importadas, serviço repetido e planilha."""
import csv
import datetime
import io
import json
import os
import shutil
import tempfile
import unittest

from nucleo import ficha
from nucleo import perfil
from nucleo import termo

AQUI = os.path.dirname(os.path.abspath(__file__))
A, B = "DD-TESTE-0001", "DD-TESTE-0002"


def etapas(mid):
    return [e["etapa"] for e in ficha.meta_ler(mid).get("etapa_historico", [])]


class Registro(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_registro_")
        self._store, self._log, self._pasta, self._det = ficha.STORE, termo.LOG, perfil.PASTA, termo.detectar_corporativa
        ficha.STORE = os.path.join(self.tmp, "maquinas")
        termo.LOG = os.path.join(self.tmp, "consentimentos.log")
        perfil.PASTA = self.tmp
        termo.detectar_corporativa = lambda: {"corporativa": False, "sinais": []}

    def tearDown(self):
        ficha.STORE, termo.LOG, perfil.PASTA, termo.detectar_corporativa = self._store, self._log, self._pasta, self._det
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ficha_win10(self, mid, fase="antes"):
        with open(os.path.join(AQUI, "fixtures", "win10_hd.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        f = ficha.normalizar_windows(d["raw"], d["medidas"])
        f.update(mid=mid, quando=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        return ficha.salvar_ficha(f, fase)

    def backup(self, mid, status="sem_falhas"):
        ficha.hist_add(mid, "backup", "Backup %s: 10 arquivos" % ("sem falhas" if status == "sem_falhas" else "com ressalvas"), {"status": status, "bytes": 2 * 10 ** 9})

    def linha(self, mid):
        return next(x for x in ficha.listar_maquinas("") if x["mid"] == mid)

    def historico_antigo(self, mid, eventos, meta=None):
        os.makedirs(ficha.pasta(mid), exist_ok=True)
        with open(os.path.join(ficha.pasta(mid), "historico.json"), "w", encoding="utf-8") as fh:
            json.dump([{"quando": q, "tipo": t, "resumo": r, "extra": x} for q, t, r, x in eventos], fh)
        if meta is not None:
            with open(os.path.join(ficha.pasta(mid), "meta.json"), "w", encoding="utf-8") as fh:
                json.dump(meta, fh)

    # ------------------------------------------------------------------ automático
    def test_etapa_avanca_sozinha_com_o_fluxo(self):
        perfil.salvar({"nome": "Marlos"})
        termo.aceitar(A, "Marlos Dadonas", "terceiros", "Ana Lúcia")
        self.assertEqual(ficha.meta_ler(A)["etapa"], "recebida")
        self.assertEqual(self.linha(A)["etapa"], "recebida", "recebida e ainda sem ficha já aparece na lista")
        self.ficha_win10(A)
        self.assertEqual(ficha.meta_ler(A)["etapa"], "diagnosticada")
        self.backup(A, "ressalvas")
        self.assertEqual(ficha.meta_ler(A)["etapa"], "diagnosticada", "backup com ressalvas não é backup verificado")
        self.backup(A)
        self.assertEqual(ficha.meta_ler(A)["etapa"], "backup_verificado")
        ficha.hist_add(A, "otimizacao", "Melhorias aplicadas: 0 de 2", {"itens": []})
        self.assertEqual(ficha.meta_ler(A)["etapa"], "backup_verificado", "nenhuma melhoria aplicada não muda a etapa")
        ficha.hist_add(A, "otimizacao", "Melhorias aplicadas: 2 de 2", {"itens": ["Inicialização", "Temporários"]})
        m = ficha.meta_ler(A)
        self.assertEqual(m["etapa"], "otimizada")
        self.assertEqual(etapas(A), ["recebida", "diagnosticada", "backup_verificado", "otimizada"])
        self.assertEqual(m["etapa_historico"][0]["tecnico"], "Marlos Dadonas", "quem aceitou o termo")
        self.assertEqual({e["tecnico"] for e in m["etapa_historico"][1:]}, {"Marlos"}, "nome de Meu perfil")
        self.assertTrue(all(e["quando"] and e["origem"] == "auto" for e in m["etapa_historico"]))
        ficha.salvar_ficha(dict(ficha.ler_ficha(A, ficha.listar_fichas(A)[-1]), quando="x"), "antes")
        self.assertEqual(etapas(A).count("diagnosticada"), 1, "analisar de novo no mesmo serviço não repete a etapa")
        L = self.linha(A)
        self.assertIn("Windows 10", L["sistema"])
        self.assertEqual((L["dono_nome"], L["tecnico"], L["melhorias"], L["servicos"]), ("Ana Lúcia", "Marlos", 2, 1))

    def test_melhorar_antes_do_backup_nao_perde_o_backup(self):
        ficha.hist_add(A, "ficha", "Ficha coletada: nota 40", {"nota": 40})
        ficha.hist_add(A, "otimizacao", "Melhorias aplicadas: 1 de 1", {"itens": ["x"]})
        self.backup(A)
        self.assertEqual(ficha.meta_ler(A)["etapa"], "otimizada", "a etapa é a mais adiantada do serviço")
        self.assertIn("backup_verificado", etapas(A))
        self.assertEqual(self.linha(A)["pendencia"], "Backup feito e ainda não entregue")

    # ------------------------------------------------------------------ manual
    def test_formatada_e_entregue_sao_marcadas_pelo_tecnico(self):
        ficha.hist_add(A, "ficha", "Ficha coletada: nota 40", {"nota": 40})
        with self.assertRaises(ValueError):
            ficha.marcar_etapa(A, "otimizada")
        with self.assertRaises(ValueError):
            ficha.marcar_etapa("DD-NAO-EXISTE", "entregue")
        with self.assertRaises(ValueError, msg="sem a etapa O que manter, não formata"):
            ficha.marcar_etapa(A, "formatada", confirmar=True)
        ficha.salvar_receita(A, [], nenhum=True)
        r = ficha.marcar_etapa(A, "formatada")
        self.assertIn("confirmar", r, "formatar sem backup verificado pede confirmação")
        self.assertEqual(ficha.meta_ler(A)["etapa"], "diagnosticada", "sem confirmar, nada muda")
        r = ficha.marcar_etapa(A, "formatada", confirmar=True)
        self.assertEqual(r["registro"]["etapa"], "formatada")
        with self.assertRaises(ValueError):
            ficha.marcar_etapa(A, "formatada", confirmar=True)
        self.assertEqual(ficha.marcar_etapa(A, "entregue")["registro"]["etapa"], "entregue")
        with self.assertRaises(ValueError):
            ficha.marcar_etapa(A, "entregue")
        ult = ficha.meta_ler(A)["etapa_historico"][-1]
        self.assertEqual((ult["etapa"], ult["origem"]), ("entregue", "manual"))
        self.assertEqual(ficha.hist_get(A)[-1]["tipo"], "etapa", "fica na linha do tempo")

    def test_com_backup_verificado_formata_sem_perguntar(self):
        self.backup(A)
        ficha.salvar_receita(A, [], nenhum=True)
        self.assertEqual(ficha.marcar_etapa(A, "formatada")["registro"]["etapa"], "formatada")

    # ------------------------------------------------------------------ máquinas antigas e serviço repetido
    def test_importa_maquina_antiga_sem_etapa(self):
        self.historico_antigo(A, [("2025-03-01 10:00", "termo", "Termo aceito", {}), ("2025-03-01 10:05", "ficha", "Ficha coletada: nota 50", {"nota": 50}),
                                  ("2025-03-01 11:00", "backup", "Backup sem falhas: 9 arquivos (1 GB) · código X", {"codigo": "X"}),
                                  ("2025-03-01 12:00", "limpeza", "Lixeira esvaziada", {"bytes": 3 * 10 ** 9})],
                              {"codigo": A, "criado": "2025-03-01 10:00", "dono": "particular"})
        self.historico_antigo(B, [("2025-04-01 09:00", "nota", "Anotação solta", {})], {"codigo": B, "criado": "2025-04-01 09:00"})
        L = self.linha(A)
        self.assertEqual(L["etapa"], "backup_verificado")
        self.assertEqual([(e["etapa"], e["tecnico"], e["origem"]) for e in L["etapa_historico"]],
                         [("recebida", "desconhecido", "importada"), ("diagnosticada", "desconhecido", "importada"), ("backup_verificado", "desconhecido", "importada")])
        self.assertEqual((L["espaco"], L["nota_antes"]), (3 * 10 ** 9, 50))
        self.assertEqual(self.linha(B)["etapa"], "recebida", "sem nada que indique outra etapa")
        self.assertNotIn("etapa", ficha.meta_ler(A), "listar não grava nada")
        ficha.marcar_etapa(A, "entregue")
        self.assertEqual(etapas(A), ["recebida", "diagnosticada", "backup_verificado", "entregue"], "o histórico antigo entra antes do evento novo")

    def test_mesma_maquina_duas_vezes_e_uma_entrada_com_dois_servicos(self):
        termo.aceitar(A, "Marlos Dadonas", "particular")
        ficha.hist_add(A, "ficha", "Ficha coletada: nota 40", {"nota": 40})
        ficha.marcar_etapa(A, "entregue")
        termo.aceitar(B, "Marlos Dadonas", "particular")
        ficha.hist_add(A, "ficha", "Ficha coletada: nota 70", {"nota": 70})  # a máquina A voltou
        self.assertEqual(ficha.meta_ler(A)["etapa"], "diagnosticada")
        lst = ficha.listar_maquinas("")
        self.assertEqual([x["mid"] for x in lst], [A, B], "duas máquinas, nenhuma duplicada")
        self.assertEqual(self.linha(A)["servicos"], 2)
        self.assertEqual(self.linha(A)["nota_antes"], 70, "a nota antes é a do serviço atual")
        self.assertEqual(etapas(A), ["recebida", "diagnosticada", "entregue", "diagnosticada"])

    def test_abas_somam_igual_a_todas(self):
        termo.aceitar(A, "Marlos Dadonas", "particular")
        self.backup(B)
        self.historico_antigo("DD-TESTE-0003", [("2025-01-01 08:00", "otimizacao", "Melhorias aplicadas: 1 de 1", {"itens": ["x"]})])
        lst = ficha.listar_maquinas("")
        self.assertEqual(len(lst), 3)
        por = {e: sum(1 for x in lst if x["etapa"] == e) for e in ficha.ORDEM}
        self.assertEqual(sum(por.values()), len(lst))

    # ------------------------------------------------------------------ pendências e contato
    def test_pendencia_de_diagnostico_parado(self):
        velho = (datetime.datetime.now() - datetime.timedelta(days=ficha.DIAS_PENDENTE + 3)).strftime("%Y-%m-%d %H:%M")
        self.historico_antigo(A, [(velho, "ficha", "Ficha coletada: nota 40", {"nota": 40})])
        self.assertIn("sem backup", self.linha(A)["pendencia"])
        self.historico_antigo(B, [(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "ficha", "Ficha", {"nota": 40})])
        self.assertEqual(self.linha(B)["pendencia"], "")

    def test_contato_e_observacoes(self):
        termo.aceitar(A, "Marlos Dadonas", "terceiros", "Ana Lúcia")
        with self.assertRaises(ValueError):
            ficha.salvar_contato(A, telefone="123")
        with self.assertRaises(ValueError):
            ficha.salvar_contato(A, email="ana@")
        r = ficha.salvar_contato(A, "(27) 99999-1234", "ana@exemplo.com", "Cliente pediu para manter o Office.")
        self.assertEqual((r["telefone"], r["email"]), ("(27) 99999-1234", "ana@exemplo.com"))
        self.assertEqual(ficha.meta_ler(A)["observacoes"], "Cliente pediu para manter o Office.")
        self.assertEqual(ficha.meta_ler(A)["etapa"], "recebida", "editar o contato não mexe na etapa")

    # ------------------------------------------------------------------ planilha
    def test_planilha_abre_no_excel_com_acentos(self):
        termo.aceitar(A, "Marlos Dadonas", "terceiros", "Ana Lúcia")
        ficha.salvar_contato(A, "+55 27 99999-1234", "", "=HYPERLINK(\"x\")")
        termo.aceitar(B, "José Conceição", "terceiros", "Padaria São João")
        dados = ficha.exportar_csv()
        self.assertTrue(dados.startswith(b"\xef\xbb\xbf"), "BOM UTF-8: o Excel reconhece os acentos")
        linhas = list(csv.reader(io.StringIO(dados.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(linhas[0][:3], ["Código", "Modelo", "Dono"])
        self.assertIn("Situação", linhas[0])
        self.assertEqual([x[0] for x in linhas[1:]], [A, B])
        a = dict(zip(linhas[0], linhas[1]))
        self.assertEqual((a["Dono"], a["Situação"], a["Técnico"]), ("Ana Lúcia", "Recebida", "Marlos Dadonas"))
        self.assertEqual(a["Observações"][:1], "'", "texto que começa com = não vira fórmula")
        so_b = list(csv.reader(io.StringIO(ficha.exportar_csv([B, "DD-NAO-EXISTE"]).decode("utf-8-sig")), delimiter=";"))
        self.assertEqual([x[0] for x in so_b[1:]], [B], "só as marcadas; código desconhecido é ignorado")
        self.assertEqual(dict(zip(so_b[0], so_b[1]))["Dono"], "Padaria São João")


if __name__ == "__main__":
    unittest.main()
