# Lista-e-Topo — painel "Ver lista", menu do topo estilo Dock e "Dynamic Island"

Branch criada a partir de `Manter-Programas`. Veio do primeiro teste em Windows real: o "Ver lista" do passo
Seleção não respondia, e o Marlos pediu, junto da correção, o painel do desenho dele, o menu como o Dock do
Mac e uma ilha que mostra o que está rodando.

## A. Painel "Ver lista" (commit `a384404`)

**O bug**: os botões "Ver lista" chamavam `syncF()`, apagada por engano no commit `bcd7ac7` ("Backup com
escolha total…"). O clique dava `ReferenceError` e nada acontecia, em qualquer sistema.

**O que mudou**
- A Seleção virou **resumo**:
  - sai o cartão "Lista de arquivos" (`loadList`, `syncF` e os filtros `#fcat`, `#fact`, `#floc` e `#fq`);
  - "Ver lista" nos cartões de categoria, no "Tipo desconhecido" e nos cartões de usuários e grupos;
  - "Ver todos os arquivos" e "Ver o que não vai (do sistema)" mantêm o acesso que a lista antiga dava.
- **Painel `abrirLista()`**, no desenho do Marlos:
  - título "Lista: <filtro>", selo "Filtro: … ✕" (tira o filtro) e Fechar;
  - totais da categoria e do selecionado, com o anel de %;
  - busca por nome, tipo ou caminho;
  - Bloco (miniaturas das imagens) ou Lista (a escolha fica lembrada);
  - colunas Nome, Tipo, Categoria, Data de criação, Tamanho e Caminho; Nome, Tipo, Data e Tamanho ordenam;
  - marcar um ou todos;
  - rolagem infinita (páginas de 200) só dentro da lista;
  - clique no nome abre a prévia.
- **Servidor**:
  - `tipo_de()` / `nome_de()`;
  - a busca também casa pelo tipo;
  - `/api/files` com `ord`/`dir`, totais do filtro (`limit=0` devolve só os totais) e nome/tipo/local/prévia
    no fim de cada linha;
  - o filtro de usuário pega subpastas (o cartão "TEMP" junta `TEMP/<usuário>`), o que corrige também o
    liga/desliga desses cartões;
  - nova `GET /api/files/ver?i=` com a prévia do arquivo de origem **só pelo índice**. Recusa índice
    inválido, tipo sem prévia e arquivo só na nuvem (abrir baixaria).
- `verArquivo()` virou `verPrevia()` genérica, usada pela aba Dados e pelo painel.
- "Data de criação" é a data que o backup já usa para organizar: a da foto (JPEG, EXIF), a do nome do
  arquivo ou a do arquivo. No Windows é a mais antiga entre criação e alteração.

## B. Menu do topo estilo Dock (commit `6066da6`)

- **Ampliação**: com o mouse, o ícone cresce pela distância (44 a 68px, curva cosseno, alcance de 150px);
  os vizinhos se afastam e só o ícone sob o mouse mostra o nome embaixo.
- **Encolher**: ao sair do menu (350ms), as outras abas deslizam e somem **atrás** da aba atual, que fica
  sozinha e centralizada. Voltam ao passar o mouse ou ao navegar com Tab. O selo "falta" da OS vira um
  ponto vermelho na pílula encolhida.
- **Abertura e telas sem aba**: o programa abre com o menu aberto por 1,5s e então encolhe. Meu perfil não
  tem aba, então o menu fica aberto. "O que manter" acende a aba Máquinas.
- **Estrutura**: invólucro novo `#topo`, fixo e sem `transform`. No celular e com toque, o menu continua
  como antes: barra completa embaixo, sem ampliar nem encolher.

## C. "Dynamic Island" (commit `653ef25`)

**Servidor**: `GET /api/atividades` junta o que está rodando:
- análise ou "Aplicando melhorias";
- backup: escaneando, copiando, conferindo ou gerando o Mapa, e se está pausado;
- Dados: varredura e limpeza ou movimentação;
- conferência do Mapa;
- envios pendentes no modo servidor.

Cada item traz %, arquivo atual, "N de M", velocidade e tempo restante. `fim` diz como cada fonte terminou.
A velocidade e o tempo restante do backup vêm de `App._ritmo()`, o mesmo cálculo que já existia no
`status()`.

**Tela**
- **Cápsula**: preta, ao lado da aba atual (a ilha dividida do iPhone), com anel de progresso, título, % e
  "faltam N min".
- **Várias atividades**: a principal na cápsula (backup > análise > Dados > conferência > envios) e um
  círculo "+1".
- **Clique**: abre um cartão com todas, cada uma com barra, contagem, velocidade, tempo restante, o caminho
  do arquivo atual e o botão "Ver" (vai à tela, ou ao passo certo do Backup). Esc ou clique fora fecha.
- **Ao terminar**: "✓ Cópia concluída", "✓ Análise pronta", "✕ A análise falhou"… por 6s. O aviso passa
  na frente mesmo se outra coisa continuar rodando.
- **Atualização**: a cada 1s com algo rodando e a cada 4s parado, sem mexer nas atualizações próprias de
  cada tela.
- **Acessibilidade**: `aria-live` só no começo e no fim de cada atividade.
- **Celular**: a ilha fica logo acima do menu de baixo e abre para cima, sem cobrir o cabeçalho; o "+1"
  some (a lista aberta mostra tudo).

## Testes

- `python3 -m unittest discover tests`: **113 ok** (100 antigos + 13 novos; 14 do Django pulados sem Django
  instalado).
- `tests/test_lista_backup.py` (8):
  - tipo e nome;
  - ordem por nome, tamanho e data, nos dois sentidos, paginando depois de ordenar;
  - totais com `limit=0`;
  - busca por tipo e por caminho;
  - "marcar tudo" com busca;
  - filtro de usuário com subpastas;
  - prévia só por índice, com recusas.
- `tests/test_atividades.py` (5):
  - nada rodando;
  - análise e melhorias;
  - backup em cada fase, incluindo pausado e verificação rápida sem bytes;
  - Dados, conferência e envios, na ordem;
  - como terminou.
- Prints do Chrome headless, com o agente numa pasta temporária. O backup escaneou de verdade uma pasta de
  exemplo com documentos e PNGs gerados.
  - **Painel**: Lista e Bloco, ordenação, desmarcar atualizando os números (94%), tema escuro.
  - **Dock**: ampliado, com as transições desligadas só na cópia para ver o tamanho final de 68px; no meio
    do encolhimento (animação congelada); encolhido.
  - **Ilha com cópia real** (400MB gerados, cópia pausada em 86%): fechada, aberta e com o menu aberto.
  - **Ilha simulada** (resposta falsa só na cópia): duas atividades com "+1", o cartão com as duas e o aviso
    "✓ Cópia concluída".
  - **390px** (no iframe): sem rolagem lateral; ilha e cartão acima do menu.
- A sintaxe do script foi conferida com o JavaScriptCore a cada parte.

## Observações

- O Chrome headless não roda `requestAnimationFrame` no `--dump-dom` e tira o print num instante qualquer
  das transições. Por isso a cópia de prévia desliga as transições para medir o Dock.
- As miniaturas do modo Bloco leem a foto original do disco de origem (com carregamento preguiçoso). Em
  pastas com milhares de fotos grandes, rolar rápido pode pesar; se pesar no Windows, dá para gerar
  miniaturas reduzidas.

## Não testado

- **Clique e mouse de verdade** (a extensão do Chrome não estava conectada): a sensação da ampliação, o
  encolher ao sair e o painel com rolagem real ainda precisam ser vistos pelo Marlos.
- **Windows real**: o painel e a ilha ainda não rodaram lá. O pendrive BKP Pro ainda tem a versão anterior;
  quando voltar ao Mac, copiar `dd_backup.py` e `web/app.html`.
