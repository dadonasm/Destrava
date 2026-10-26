# Gerenciamento de dados — cockpit navegável, Sugestão de varredura e Gerenciamento completo

Branch criada a partir de `Sem-OS`. A aba "Dados" virou **Gerenciamento de dados**. O Marlos queria poderes completos sobre o armazenamento:
navegar por tudo o que o cockpit mostra, com um filtro que diga em que parte do cockpit ele está, e manter a
varredura como sugestão.

## A. Tela
- **Cockpit no topo, sempre**: a barra e a legenda viram botões.
  - Mídias, Documentos, Dados de apps e Limpável abrem o Gerenciamento completo já filtrado.
  - Clicar de novo limpa o filtro.
  - "Sistema e fora da sua pasta" e "Livre" são só número, porque não ficam nas pastas dos usuários.
- **Cabeçalho do cockpit**: botão **Atualizar** e a linha "Última varredura: há 3 dias (25/10, 14:02) · 444 mil
  arquivos · você mexeu em N itens desde então".
- **Abas**:
  - **Visão geral** abre sempre que se entra pelo menu:
    - faixa âmbar com Atualizar quando a varredura tem mais de 7 dias ou mais de 10 itens mudaram desde então;
    - os 3 cartões de sugestão em números (cada um abre a sua faixa na aba Sugestão);
    - três listas curtas: maiores pastas (descendo até onde o peso se concentra), maiores arquivos e
      arquivos de 50 MB ou mais parados há mais tempo. Clicar abre a pasta no Gerenciamento completo, com o
      arquivo destacado.
  - **Sugestão de varredura** traz a lista da faixa na grade.
  - **Gerenciamento completo** mostra todos os arquivos das pastas dos usuários.
- **Primeira vez** (nunca varreu): tela enxuta com "Fazer a primeira varredura" e "Explorar pastas".
- **Atualizar** abre um diálogo com "considerar parado após" e "arquivos grandes a partir de" (lembrados no
  navegador, em `dd_varrer`) e "Esquecer esta varredura". Atualizar não apaga nada antes: o resultado atual
  vale até a varredura nova terminar.
- **Trilha**: `Disco › Mídias › Vídeos › teste › Movies`. Cada parte volta àquele ponto; o ✕ limpa tudo.
- **Grade** (mesmas peças nas duas abas):
  - colunas Nome, Usuário, Parado, Tamanho e ações;
  - grupos recolhíveis com caixa do grupo (estado parcial);
  - marcar não redesenha a página.
- **Gerenciamento completo**:
  - visão **Arquivos** (agrupada por tipo) ou **Pastas** (entra e sai pela trilha);
  - busca sem acento no nome do arquivo e no caminho da pasta;
  - ordem por Maior, Menor, Mais parado ou Nome;
  - filtro por usuário, chips por bloco e por tipo;
  - "Carregar mais" a cada 200 itens;
  - a seleção continua ao trocar de filtro ou de pasta.
- **Itens trancados (🔒)** mostram o motivo escrito embaixo do nome, e uma legenda aparece acima das
  colunas quando a página tem algum.
  - Os motivos são específicos: "Cópia local do OneDrive…", "Dados internos de aplicativos…", "Chaves e senhas
    do macOS", "E-mails do Mail", "Mensagens", "Dados do Safari"; o resto fica com o texto genérico.
  - O motivo é calculado na hora da consulta, então índices antigos também mostram o texto novo.
  - **OneDrive**: os arquivos baixados ficam em `~/Library/Group Containers/UBF8T346G9.OneDriveSyncClientSuite/…`,
    a área interna do OneDrive, e continuam trancados (mexer por fora confunde a sincronização e pode apagar
    na nuvem). A linha ganha "Abrir pasta do OneDrive", que abre `~/Library/CloudStorage/OneDrive-*` (no
    Windows, `%OneDrive%`); lá se libera o espaço com o botão direito > "Liberar espaço".
- **Menu ⋯** de cada linha: Ver, Abrir, Mostrar na pasta, Entrar, Renomear (na própria linha: Enter
  confirma, Esc cancela), Mover para… e Copiar para….
- **Faixa de ações no cabeçalho da lista** (`dgBarraHtml`), fixa no topo ao rolar, nas duas abas:
  - contador curto ("12 selecionados · 3,2 GB");
  - Gerenciamento: Desmarcar, Mover para…, Copiar para…, Disco externo…;
  - Sugestão: Disco externo…;
  - em ambas, "Apagar de vez" e o botão principal (Lixeira; fica vermelho "Apagar de vez · sem volta" com a
    caixa marcada). A confirmação é a de antes, com APAGAR.
- Estado lembrado no navegador (`dd_dados`): aba, bloco, tipo, visão, ordem, usuário e grupos fechados.

## B. Índice de arquivos (`dados.py`)
- Gravado **durante a varredura**, num SQLite na pasta temporária **deste computador**. Nunca vai para o
  pendrive, porque são os caminhos dos arquivos do cliente.
- Grava num arquivo novo e só troca o antigo no fim; cancelar deixa o índice marcado como parcial.
  "Esquecer esta varredura" (reset) apaga o índice.
- **A última varredura sobrevive ao reiniciar o programa**: o índice guarda na `meta` o cockpit, as
  sugestões, os campos da tela, os parâmetros e o contador `mexidas`. `restaurar()` traz tudo de volta na
  primeira consulta de `estado()`, sem reaproveitar ids. Um índice parcial volta como "cancelado".
- Tabela `arq`: uma linha por arquivo, mais uma por pasta medida como bloco (caches, backups de iPhone,
  CapCut, restos de programas, bibliotecas de apps).
  - Não guarda o caminho inteiro: guarda a pasta e o nome. No Windows guarda também a pasta como está no
    disco, porque a chave fica em minúsculas.
  - `busca` é o nome sem acento.
- Tabela `pasta`: tamanho de cada pasta somado com o de todas as de dentro, por bloco. É dela que vêm a
  visão por pastas e os totais sem busca.
- **Bloco** de cada arquivo, a mesma conta do cockpit:
  - `midias`: Vídeos, Fotos e Áudios;
  - `documentos`: as demais categorias;
  - `apps`: "Outros" e as pastas medidas;
  - `limpavel`: o que a varredura pôs na Limpeza imediata.
- **Correção no cockpit**: um instalador já usado contava duas vezes, em Documentos e em Limpável.
  Agora conta só em Limpável.
- Credenciais e bibliotecas entram travadas (🔒, só ver). As pastas de credenciais que a varredura já
  pulava continuam fora.
- **Medido neste Mac** (444 mil arquivos):
  - a varredura levou 80 s e o índice ocupa 206 MB;
  - filtros e pastas respondem em até 0,25 s; a busca, em ~1,9 s;
  - os totais por bloco batem com o cockpit.

## C. Operações (`dados.py`, rotas em `dd_backup.py`)
- `renomear`, `nova_pasta`, `preflight_destino`, `mover`, `copiar`, `marcar_nos`. Rotas
  `/api/dados/renomear`, `/nova_pasta`, `/preflight_destino`, `/mover`, `/copiar` (termo com escopo
  `limpeza`), `/marcar_nos` e `GET /api/dados/indice`.
- **Regras**:
  - só dentro das pastas dos usuários;
  - a origem não pode ser travada nem ser pasta principal ou a pasta do usuário;
  - o destino pode ser pasta principal, mas não credenciais nem sistema;
  - nunca põe uma pasta dentro dela mesma.
- **Nunca sobrescreve**: o conflito de nome vira pergunta, "manter os dois" (ganha um número) ou "pular".
- **Mover**:
  - no mesmo disco é `rename`, instantâneo;
  - em outro disco, copia e confere cada arquivo (SHA-256) e só então o original vai para a Lixeira.
- **Copiar**: confere cada arquivo e o original fica.
- Rodam em segundo plano como limpar e offload (`ST["acao"]`), com progresso na ilha ("Movendo arquivos",
  "Copiando arquivos") e registro no histórico da máquina.
- O índice é atualizado depois de cada operação, inclusive limpar e offload, sem nova varredura.

## D. Ajustes junto
- Ilha recolhida mostra a **porcentagem** no anel. Com mais de uma atividade, um selo com o número.
- Barra de selecionados cortada: a barra fixa ganhou camada própria e o contador começa vazio.
- `dialog()` ganhou `livre` (texto qualquer) e `valor`. O "Nova pasta" do escolhedor de pasta do backup pedia
  texto vazio para liberar o botão e agora funciona.

## Limites conhecidos
- O sistema (fora das pastas dos usuários) não entra no índice.
- Arquivos criados depois da varredura só aparecem depois de varrer de novo, ou se vierem de uma operação
  feita pelo próprio programa.
- Limpar ou mandar ao disco externo pelo Gerenciamento põe os itens na lista de "Arquivos parados" ("Escolhido
  pelo técnico"), como já acontecia no explorador, mesmo que a confirmação seja cancelada.
- Os números do cockpit e das sugestões são os da última varredura: mover, copiar e limpar atualizam a
  lista de arquivos, mas o cockpit só muda ao Atualizar (por isso o contador "você mexeu em N itens").
- Uma varredura feita antes desta versão não guardou o cockpit: depois de reiniciar o programa, a tela
  inicial aparece até a próxima varredura.

## Conferência (26/10)
- Testes: 198 passando, inclusive os do backup (varredura, cópia, verificação completa e rápida, Mapa, retomar).
- `dd_backup.py`: só rotas `/api/dados/*` acrescentadas; nada da lógica do backup mudou.
- Peças divididas com o backup: `dialog()` ganhou `livre`/`valor` (os usos antigos seguem iguais) e o "Nova
  pasta" do escolhedor de destino do backup voltou a funcionar (antes nunca liberava o botão). A sobra de CSS
  que mexia nas barras `.actbar` (inclusive "O que manter") foi retirada.
- **Não conferido no navegador**: a extensão do Chrome não estava conectada; a tela foi checada só pela
  sintaxe (`jsc`) e pelos prints do Marlos.

## Mapa no navegador (pergunta do Marlos, 26/10)
- O HTML já existe: todo backup grava `Mapa/visualizador.html` na pasta do backup, junto de `dados.js`, `logo.js`,
  `Relatorio.csv` e `certificado.json`. Abre offline com duplo clique (Chrome, Edge ou Firefox). Para levar a outro
  computador, copie a pasta `Mapa` inteira: o HTML lê o `dados.js` ao lado.
- Depois de formatar: o código da máquina vem do UUID/serial da placa, então a aba **Mapas** acha o backup no
  histórico. Sem o disco ligado, abre pela cópia guardada no pendrive (`maquinas/<código>/mapas/<código do backup>/Mapa`);
  "Abrir outro Mapa" aceita qualquer pasta de backup. Abrir os arquivos de verdade pede o disco do backup.
- A aba Mapas ganhou **"Abrir no navegador"** (rota `/api/mapa/offline`, que já existia sem botão); antes só a
  conclusão do backup tinha "Visualizador offline".
