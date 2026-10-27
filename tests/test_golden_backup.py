# -*- coding: utf-8 -*-
"""Régua da unificação Gerenciamento + Backup: congela o que o backup e o índice do Gerenciamento devolvem hoje
na mesma árvore de mentira. Mudar o motor (catálogo único) não pode mudar estes resultados sem explicação.

Para regravar depois de uma mudança aprovada:  GOLDEN_ATUALIZAR=1 DD_TEST=1 python3 -m unittest tests.test_golden_backup
e conferir o diff de tests/fixtures/golden_backup.json no git."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from nucleo import dados
from nucleo import dd_backup

from tests import test_backup_mapa as tbm

AQUI = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(AQUI, "fixtures", "golden_backup.json")
EPOCA = 1768478400  # 2026-01-15 12:00 UTC (meio do mês: o mesmo dia em qualquer fuso): data fixa para todos os arquivos (o modo Ordenado usa ano/mês)
# o que muda de uma execução para outra (relógio, máquina, disco, ordem do sistema de arquivos)
VOLATIL = {"free", "total", "data", "hora", "codigo", "base_hash", "dados_js_sha256", "maquina_id", "maquina_nome", "sistema", "versao",
           "eventos", "tecnico", "tecnico_perfil", "recuperado_bytes", "os", "autorizou", "dono", "dono_nome", "raiz", "dias", "uso",
           "no", "id", "quando", "equipamento", "pc", "metodo", "verificacao", "idade", "mexidas", "duracao", "inicio", "fim", "atual",
           "tamanho"}  # tamanho: o arquivo do índice (SQLite) muda de tamanho de uma execução para outra


def normaliza(x, tmp):
    if isinstance(x, dict):
        return {k: normaliza(v, tmp) for k, v in sorted(x.items()) if k not in VOLATIL and not k.endswith("_no")}  # *_no: número interno do nó
    if isinstance(x, (list, tuple)):
        return [normaliza(v, tmp) for v in x]
    if isinstance(x, str):
        return x.replace(tmp, "<TMP>").replace("\\", "/")
    return x


def data_fixa(raiz):
    for d, _, fs in os.walk(raiz):
        for n in fs:
            os.utime(os.path.join(d, n), (EPOCA, EPOCA))


def instantaneo_backup(caso):
    """Escaneia a árvore do EscolhaTotal e fotografa tudo o que a tela do backup consome, nos três modos."""
    data_fixa(caso.disco)
    caso.escanear()
    app, tmp = caso.app, caso.tmp
    g = lambda f: app.files({k: [str(v)] for k, v in f.items()})
    out = {"groups": app.groups(), "totals": app.totals(),
           "files_nome": g({"ord": "nome", "limit": 500}), "files_docs_p2": g({"cat": "Documentos", "ord": "nome", "offset": 1, "limit": 2}),
           "files_facetas": g({"facets": 1, "limit": 0}), "layout_sem_modo": app.layout_resumo()}
    for modo in ("espelho", "ordenado", "misto"):
        out["layout_" + modo] = app.set_modo(modo)
        out["rels_" + modo] = sorted(it.rel for it in app.items)
    app.copia({"copia": "ordenar", "filter": {"cat": ["Fotos"]}})
    out["layout_misto_fotos_ordenadas"] = app.layout_resumo()
    out["rels_misto_fotos_ordenadas"] = sorted(it.rel for it in app.items)
    app.select({"filter": {"cat": ["Documentos"]}, "on": False})
    out["totals_sem_documentos"] = app.totals()
    app.select({"padrao": True})
    out["totals_padrao"] = app.totals()
    # backup até o fim, no Misto com fotos ordenadas
    app.start_copy()
    caso.assertEqual(tbm.espera(app, ("copied", "error")), "copied", app.error)
    app.start_verify("completa")
    caso.assertEqual(tbm.espera(app, ("verified", "error")), "verified", app.error)
    cert = app.finish()
    with open(os.path.join(app.mapa_dir, "dados.js"), encoding="utf-8") as fh:
        d = json.loads(fh.read().strip()[len("window.BKP="):].rstrip(";"))
    meta = {k: v for k, v in d["meta"].items() if k != "cert"}
    out.update(cert=cert, mapa_meta=meta, mapa_f=sorted(d["f"], key=lambda e: (e[0], e[1])))
    return normaliza(out, tmp)


def instantaneo_dados(h, idx):
    """O índice do Gerenciamento numa pasta de usuário de mentira: panorama, consultas por bloco, pasta e busca."""
    data_fixa(h)
    with mock.patch.object(dados, "pastas_usuarios", lambda: [("teste", h)]):
        dados.set_helpers(user_home=lambda: h, indice_dir=idx)
        dados.CANCEL.clear()
        dados._varrer(90, 100)
        try:
            ordena = lambda r: dict(r, rows=sorted(r.get("rows") or [], key=lambda x: (x.get("tipo", ""), x.get("nome", ""))))
            out = {"fase": dados.ST["fase"], "panorama": dados.indice_panorama(""),
                   "tudo": ordena(dados.indice_consulta(limit=500)), "midias": ordena(dados.indice_consulta(faixa="fotos|videos|audios", limit=500, facetas=True)),
                   "pastas": ordena(dados.indice_consulta(visao="pastas", limit=500)), "busca_pdf": ordena(dados.indice_consulta(q="pdf", limit=500))}
        finally:
            dados.MEDIR["cancel"].set()
            dados.set_helpers(user_home=None, indice_dir=None)
            dados.ITENS.clear()
    return normaliza(out, h)


class Golden(unittest.TestCase):
    escanear = tbm.BackupCompleto.escanear

    def setUp(self):
        tbm.EscolhaTotal.setUp(self)
        self.h = tempfile.mkdtemp(prefix="destrava_casa_")
        self.idx = tempfile.mkdtemp(prefix="destrava_idx_")
        j = lambda *p: os.path.join(self.h, *p)
        for p, c in ((("Movies", "férias.mp4"), b"v" * 40000), (("Movies", "Viagem", "praia.mov"), b"v" * 20000), (("Pictures", "foto.jpg"), b"f" * 9000),
                     (("Documents", "contrato.pdf"), b"%PDF" + b"d" * 7000), (("Documents", "50%_desconto.pdf"), b"%PDF" + b"d" * 3000),
                     (("Projetos", "notas.txt"), b"t" * 5000), (("Downloads", "setup.exe"), b"MZ" * 4000), ((".ssh", "id_rsa"), b"-----BEGIN KEY-----")):
            tbm.escreve(j(*p), c)

    def tearDown(self):
        shutil.rmtree(self.h, ignore_errors=True)
        shutil.rmtree(self.idx, ignore_errors=True)
        tbm.EscolhaTotal.tearDown(self)

    def test_resultados_iguais_ao_golden(self):
        atual = {"backup": instantaneo_backup(self), "dados": instantaneo_dados(self.h, self.idx)}
        texto = json.dumps(atual, ensure_ascii=False, indent=1, sort_keys=True)
        if os.environ.get("GOLDEN_ATUALIZAR"):
            with open(GOLDEN, "w", encoding="utf-8") as fh:
                fh.write(texto + "\n")
            self.skipTest("golden regravado")
        with open(GOLDEN, encoding="utf-8") as fh:
            esperado = json.load(fh)
        for parte in ("backup", "dados"):
            for k in sorted(set(esperado[parte]) | set(atual[parte])):
                self.assertEqual(atual[parte].get(k), esperado[parte].get(k), "mudou: %s.%s (regrave só se a mudança foi aprovada)" % (parte, k))


if __name__ == "__main__":
    unittest.main()
