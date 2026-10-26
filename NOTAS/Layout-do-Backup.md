# Layout-do-Backup — Espelho, Ordenado ou Misto, escolhido a cada backup

Branch criada a partir de `Gerenciamento-de-Dados`. O Marlos avaliou que adivinhar as "Pastas de origem" pelo
nome próprio ("Wefix" sim, "motorista" não) ficou ruim. Pediu três jeitos de guardar, escolhidos a cada backup,
sem adivinhação, e a escolha do Misto feita na própria janela em que se está navegando.

## Os três modos
- **Espelho**: cada pasta como estava, em `Pastas_origem/<Usuário>/<caminho a partir da pasta do usuário>`
  (ex.: `Pastas_origem/Ana/Documents/motorista/cnh/planilha.xlsx`; disco solto: `Pastas_origem/Disco_D/…`).
- **Ordenado**: por tipo e data, com raiz no usuário, `<Usuário>/<Categoria>/<Ano>/<Mês>/<arquivo>` (o de sempre).
  Perde a pasta de onde veio; o Mapa lembra.
- **Misto**: começa espelhado e o técnico escolhe o que vai ordenado, em qualquer conjunto: uma categoria, um
  usuário, uma pasta ou qualquer filtro da lista. Vale a última ação.
- O espelho fica separado do ordenado (`Pastas_origem/`) para uma pasta original chamada "Fotos" nunca se misturar
  com a categoria Fotos. Dados de programas, ocultos, sistemas, favoritos e "incluídos por você" guardam sempre o
  caminho original e não entram na escolha ("📌 caminho fixo").
- O "local" do arquivo (usuário) não muda com o modo: só o destino. A grade continua por usuário.
- Sem modo escolhido o destino é o ordenado; a rota `/api/copy` recusa copiar até o modo ser escolhido.
  Depois que a cópia começa, o modo e as escolhas não mudam mais.

## Backend (`dd_backup.py`)
- `Item` ganhou `quem` (usuário/local antes de o WhatsApp virar "WhatsApp (Ana)"), `pk` (pasta a partir do
  usuário, a chave da navegação), `eleg` (entra na escolha) e `lay` (escolha do Misto).
- `rel_espelho`, `pasta_chave`, `App.copia_de`, `App.set_modo`, `App.copia` (filtro ou linhas, no molde do
  `select`), `App.layout_resumo` (espelhados × ordenados × fixos e um exemplo real), `App.subpastas`
  (navegação a partir dos usuários).
- Filtros novos `pasta` e `copia`; faceta `copia`; `/api/files?pastas=1` devolve as subpastas do caminho atual;
  cada linha traz como copia e o destino; `/api/groups` traz `esp`/`ord` por linha.
- Rotas: `GET/POST /api/layout`, `POST /api/layout/copia`. Saiu `/api/maes`.
- Saiu tudo da adivinhação: `parece_nome_proprio`, `sugestoes_maes`, `_chave_mae`, `_aplicar_maes`, `set_maes`,
  `_lembrar_origens`, `memoria_origens` (o `pastas_origem.json` não é mais lido nem gravado), `AUTO_ORIGEM` e as
  listas de nomes.
- Certificado e Mapa: `meta.layout = {modo, nome, espelhados, ordenados}`; o `maes` antigo continua sendo
  gravado e lido.

## Tela
- Seleção: cartão **"Como guardar este backup"** com os três modos e um diagrama "na máquina → no backup" usando
  um arquivo real da máquina; depois de escolhido, vira um resumo com "Mudar".
- No Misto:
  - grade com a coluna **Cópia** [Espelhar | Ordenar] em cada linha (e "x de y ordenados" quando dividido) e
    botões no cabeçalho de cada bloco;
  - lista ("Ver lista") com a barra **"Como copiar o que está nesta lista"**, que vale para o filtro inteiro;
  - faceta **Pasta** que parte dos usuários e desce, com trilha;
  - faceta "Como copiar" e, em cada arquivo, o selo Espelhado/Ordenado com o destino no balão.
- "Iniciar cópia" fica apagado até escolher o modo; a confirmação antes de copiar e o certificado dizem o modo.

## Mapa
- No visualizador, **Pasta original** (a partir do usuário) ou **Tipo e data** (Categoria › Ano › Mês),
  somando com a busca e os filtros. O LEIA-ME do Mapa explica os três formatos.

## Conferência
- Testes: modelo nos três modos, Misto por filtro e por pasta, última ação vale, navegação por pasta, cópia +
  verificação completa + Mapa apontando para `Pastas_origem/…`, bloqueio depois de copiar e as rotas pela camada
  HTTP. Saíram os testes da Wefix e do nome próprio.
- **Não conferido no navegador**: a extensão do Chrome não estava conectada; a tela foi checada pela sintaxe
  (`jsc`) e pelos testes das rotas.
- Versão 3.3 (BUILD 2026-10-26.2).
