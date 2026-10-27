# Bkp-flow — etapas com um clique e modo Superusuário (v3.4, BUILD 2026-10-26.3)

Branch criada a partir de `Layout-do-Backup` (já em `main`). O Marlos pediu para abrir cada etapa do backup com um
clique e para editar "como superusuário": pular travas, editar valores/estado, editar certificado e registros,
rodar como administrador. O modo é ligado por uma chave na engrenagem (Configurações), sem senha.

## Etapas com um clique
- `renderSteps()` vira botões. Sem Superusuário, abrem só as etapas já alcançadas (`maxStep`). Com ele, todas, e um
  aviso diz que pode faltar o que as anteriores preparam. Saltar adiante no Superusuário não conta como alcançado.

## Modo Superusuário
- Estado: `SU` no `localStorage` (`dd_su`) e `SU["ligado"]` no servidor (`POST /api/su`), sincronizado na abertura.
  Faixa `#suband` no topo enquanto ligado, com "Painel" e "Desligar". Ligar pede confirmação ("Entendo os riscos").
- Pular travas:
  - Pré-voo com erro: oferece "Seguir mesmo assim".
  - `/api/copy` sem jeito de guardar escolhido: usa Espelho e registra.
  - Verificação: botão "Pular verificação"; `finish()` aceita a fase `copied` e o certificado sai
    "Não verificado (pulado no modo Superusuário)".
  - Formatar com bloqueio: botão "Formatar mesmo assim", que mostra o motivo e exige digitar FORMATAR.
    `firmware_reboot(forcar=True)` grava no registro e no histórico da máquina (tipo `superusuario`).
    O `firmware_gate` continua igual: o bloqueio não some, só pode ser passado conscientemente.
- Painel (`suPainel`): fase e verificação atuais, troca do jeito de guardar (enquanto a cópia não começou),
  situação do administrador com o passo para reabrir elevado, e edição do certificado.
- Certificado (`/api/su/certificado`): cliente, técnico, equipamento, data, hora e situação. Guarda
  `certificado.json.bak` e `dados.js.bak` (o original emitido, só na primeira edição), mantém o código original
  e acrescenta `cert.editado` (quando, por, campos antes/depois). `--verificar` passa e avisa "editado manualmente".
- Administrador: o processo aberto não se eleva sozinho; o painel mostra como reabrir (sudo, Iniciar-Windows.bat,
  Acesso Total ao Disco no Mac).

## v3.5 (BUILD 2026-10-26.4) — Mac como origem e Seleção que escaneia sozinha
- O "Macintosh HD" era reconhecido como Linux (tem etc/usr/home) e o scan procurava usuários em `/home`: achava 0
  arquivos. Agora `detect_kind` devolve `mac` (volume com `Users` e `System`/`Library`), e `plan_roots` faz um plano
  por usuário de `/Users` (sem Shared, Guest e ocultos), contexto `macuser`.
- `macuser`: `Library` na raiz do usuário fica de fora ("Dados do macOS e dos apps"); favoritos de Chrome, Edge,
  Brave e Firefox vêm de `Library/Application Support`. A pasta pessoal no Mac também usa `macuser`.
- Ler outros usuários exige Acesso Total ao Disco; sem ele, entram como "Sem acesso" na lista do que ficou de fora.
- Seleção aberta sem escaneamento (Superusuário): `sel3Escanear` usa a origem/destino da etapa 1, escaneia e
  mostra o progresso; ao terminar abre a Seleção. Cancelado, oferece "Escanear de novo" (sem laço).

## Unificação Gerenciamento + Backup (plano em fases; 0 e 1 feitas)
- Fase 0: `tests/test_golden_backup.py` congela o que o backup (grupos, totais, lista, os 3 modos, certificado, Mapa)
  e o índice do Gerenciamento devolvem numa árvore de mentira (`tests/fixtures/golden_backup.json`). Regravar só
  com mudança aprovada: `GOLDEN_ATUALIZAR=1`. `test_app_html` agora checa a sintaxe do JS pelo osascript.
- Fase 1: tokens num lugar só (um `:root`, um tema claro; antes o 2º bloco sobrescrevia o 1º), `.card`, `button`,
  `header`, `.shell` e `.content` definidos uma vez, tokens de raio/espaço/tipo, facetas da lista renomeadas de
  `fx*` para `fc-*` (o `fx-` é do fluxo da etapa 1). Sem mudança visual (valores finais iguais).
- Mock para aprovar: `NOTAS/mock-escolher.html` (abre no navegador; `#escuro`, `#lista`, `#misto`, `#ordenado`,
  `#gerenciar` combináveis no endereço). Tela única: cockpit do disco, facetas à esquerda, grade por categoria
  (a da Seleção) e o "Ver lista" aberto no lugar da grade; chave Gerenciar dados | Fazer backup; faixa de baixo
  com Espelho/Ordenado/Misto e o caminho do arquivo em foco do jeito que vai ficar no destino.

## Fase 2 (v3.6, BUILD 2026-10-26.5) — a "mescla" aprovada nas duas telas
- **Seleção do backup** (`draw3`): disco no topo (`selCockpit`, juntou os 4 cartões e o "Onde está o resto do
  disco?", com a legenda abrindo a lista de marcados/não marcados e as pastas de fora); filtros do "Ver lista"
  sempre à esquerda (`selFacetas` + `lstSide`; na grade, escolher um filtro abre a lista); a lista abre **no lugar
  da grade** (não é mais janela; "← Visão geral" ou Esc volta; rolagem infinita pela página); faixa de baixo
  (`selBarra`) com Espelho/Ordenado/Misto, a prévia do caminho (`sbPrevia`/`trilho`: passar o mouse num jeito
  mostra onde o arquivo fica; clicar numa linha da lista usa aquele arquivo, via `GET /api/destino?i=`), o destino
  (clique volta à etapa 1), os totais, os avisos (não cabe, FAT32, falta escolher) e "Iniciar cópia". Saíram
  `layCard`, `drawTot`, `selKpis`, `medicaoCard` e o CSS deles.
- **Gerenciamento completo** (`dgGerenciar`): o mesmo molde — filtros à esquerda (onde você está, categoria do
  disco, tipo, usuário), a lista na mesma tabela do "Ver lista" (`dgTabela`/`dgCabeca`/`dgGrupo`/`dgLinha` em
  `<tr>`, também na aba Sugestão). A faixa de ações continua **fixa no topo da lista** (decisão antiga do Marlos:
  nunca barra solta embaixo); a faixa de baixo é só do backup. Tela larga (`setWide(true)`).
- Toast sobe acima da faixa de baixo; busca (`type=search`) com o visual dos outros campos no tema escuro.
- Conferido com um harness (servidor de verdade numa árvore de mentira + Chrome headless pelo DevTools):
  grade, Misto, prévia, lista, foco, filtros, Esc, escuro, estreito; Gerenciamento com filtros, seleção,
  pastas, renomear, menu ⋯ e Sugestão. Sem erro de JS. **Falta o Marlos ver na máquina dele.**

## Fase 3 — uma tabela só de tipos (`nucleo/classe.py`)
- Extensão → classe, e cada classe diz o que vira no backup (categoria/pasta do Ordenado), no Gerenciamento
  (rótulo do índice), o bloco do cockpit e o ícone. `dd_backup` (EXT2CAT, PROG_EXT, CONF_EXT, ARCH) e `dados`
  (EXT) montam as suas listas dela; `GET /api/classes` dá os ícones para a tela. `classe` entrou em
  `nucleo/__init__.py` (LEVES); o pacote do pendrive já pega todo `.py` da pasta.
- Decisão do Marlos: **juntar o que cada um sabia**. O Gerenciamento passou a reconhecer documentos (.doc .xls
  .txt .csv .ppt .odt…), e-mails/contatos, contas e senhas e projetos (antes caíam em "Outros"/Dados de apps); o
  backup passou a reconhecer .webm/.mts/.prproj_proxy (Vídeos), .aiff (Áudios) e .blend/.sketch/.fig/.drp/.fcp
  (Projetos). Compactados, imagens de disco e máquinas virtuais seguem como antes no backup (.xz agora conta
  como compactado). Golden regravado: só o `notas.txt` do teste mudou de "Outros" para "Documentos e projetos".

## v3.7 (BUILD 2026-10-27.1) — cockpit, gaveta, Grupo e Sugestão iguais nas duas telas
Pedidos do Marlos depois de ver a v3.6, todos no mesmo padrão para Gerenciamento e Backup:
- **Cockpit** (`cockpit()` no app.html): um componente só, barra de **14px**. Título = **nome da máquina e
  modelo** e, abaixo, **de quem é** (Particular/Terceiros, técnico ou cliente) e as **contas** achadas (a em uso
  marcada), por `GET /api/identidade?para=dados|backup` (cadastro + ficha; sem ficha, modelo pelo hw.model/DMI;
  no Mac, o nome dado ao computador). **Faixas** (classe.py `FAIXAS`): Fotos · Vídeos · Áudios · Documentos ·
  Outros arquivos · Apps instalados · Caches e temporários · Dados do Sistema · OS (macOS/Windows/Linux) · Livre.
  Clicar numa faixa de arquivos filtra a lista. Enquanto Apps/OS são medidos, a parte ainda sem dono fica listrada.
- **Medição fora das pastas dos usuários** (`dados.medir_fora`, regiões por sistema em `REGIOES_FORA`, sem sair
  do volume: no Mac `/System/Volumes/Data` não conta duas vezes): no Gerenciamento roda em segundo plano depois da
  varredura e fica no índice; no Backup entra na medição que já existia (pastas puladas + Applications/System do
  disco de Mac). O que ninguém mediu vira Dados do Sistema (como o Ajustes do Mac). Testes e harness (pasta de
  usuário de mentira) não medem o disco de verdade.
- **Grupo** (classe.py `GRUPOS`, `grupo_arquivo`, `grupo_backup`): Pessoal · Dados de programas · Cache
  temporário · Instaladores · Sistema · Só na nuvem · Bloqueado. Coluna nas duas listas, filtro na gaveta e, no
  backup, os blocos da grade (antes Pessoal/Você decide/Sistema).
- **Sugestão de varredura** virou filtro da gaveta (Limpável · Com ressalva · Não recomendado), gravado no
  índice para todo arquivo (`sug`); a aba Sugestão saiu (ficam Visão geral e Gerenciamento completo). Os 3
  cartões da Visão geral abrem o Gerenciamento já filtrado. A faixa de ações ganhou **"Marcar tudo que é
  Limpável"** (dentro do filtro atual). O explorador (sem índice) ganhou Lixeira/Disco externo na própria faixa.
- **Gaveta de filtros retrátil** (`gavCab`/`gavTroca`, estado em `dd_gaveta` por tela): recolhida vira um trilho
  de 48px; botão no topo dela, tecla **F** alterna, Esc com o foco nela recolhe. Gerenciamento: Onde você está,
  Categoria (faixas), Grupo, Sugestão, Tipo, Último uso, Tamanho, Usuário (contagens com os outros filtros
  aplicados, `indice_consulta(..., facetas=True)`). Backup: a do "Ver lista" + Grupo. Filtros ativos ficam como
  etiquetas acima da lista mesmo com a gaveta recolhida.
- **Colunas iguais**: Nome · Tipo · Categoria · Grupo · Situação (No disco/Selecionado/Bloqueado no Gerenciamento)
  · Parado · Criado em · Tamanho · Caminho. O backup mostra a data dele e mantém "No backup".
- **Índice v2** (`PRAGMA user_version=2`): colunas `faixa`, `grupo`, `sug`, `trot` (tipo), `criado`; somas das
  pastas por faixa. Índice antigo é ignorado e a tela pede para varrer de novo.
- Golden regravado: no backup só ganhou Grupo e a data de modificação nas linhas; no Gerenciamento, os mesmos
  arquivos e categorias com os campos novos. 223 testes. Harness: Seleção e Gerenciamento sem erro de JS.
- "Limpo" (na Situação) não aparece: o que é limpo/movido sai do índice na hora.

## Não feito ainda
- Editar o histórico/registro da máquina (só o certificado e o Mapa).
- Telas abertas fora de ordem não mostram aviso próprio de "sem dados"; algumas podem ficar vazias.
- Não conferido no navegador. Testes: `tests/test_superusuario.py` e a suíte toda (206, OK).
- Ideia em aberto: levar o backup para dentro do Gerenciamento de dados.
