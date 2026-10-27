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

## Medição de apps e sistema que travava em 0% (parte A do plano da 3.8)
- **Causa:** o Backup media antes de tudo /Applications, /System… (`medir_fora`) sem mexer no `pct`, com um prazo só
  de 240 s para tudo. **Correção:** `dados.medir_fora(raiz, so, parar, prazo, progresso)` mede **região por região**,
  cada uma com prazo próprio (`FORA_PRAZO` = 90 s); a que estoura fica em `estimadas` e as outras seguem. O progresso
  (`pct`, região atual, quanto já foi lido) sobe a cada região e durante ela.
- **Medição única:** `dados.medicao_fora` serve Backup e Gerenciamento; quem chega com outra em andamento acompanha
  o progresso dela; o resultado fica em `FORA["ultimo"]` e no índice (meta `fora`) por `FORA_IDADE` (30 min), então
  reabrir a tela não mede de novo. As pastas puladas do Backup também têm prazo próprio (60 s cada).
- **Bug achado no teste real:** no Mac, `/System/Volumes/Data` (o disco das pessoas) tem o mesmo `st_dev` de `/` e
  entrava como "OS" (77 GB em vez de 16,8 GB). Agora `PULAR_FORA` tira `/System/Volumes`. Mac real: 31 s, nada estimado.
- Tela: ilha e cockpit mostram "medindo /System… 12 GB lidos · 25%" (`medTexto`); "estimado" diz qual região
  passou do tempo. O Gerenciamento ganhou a sua atividade na ilha ("Medindo apps e sistema").

## Varredura completa do disco (parte B do plano da 3.8)
- **Disco inteiro:** depois das pastas dos usuários, `_varrer_sistema(raiz, so)` lê o resto do disco arquivo a arquivo
  (sem sair do volume, sem seguir atalhos, sem junções do Windows, sem `/System/Volumes` no Mac), região por região
  (pasta do topo) com progresso. No índice o dono é **"Sistema"** (`SIS`) com raiz no disco: `donos()`/`dono_idx()`
  servem só para o índice e a navegação; `dono()` e as travas não mudam. Faixa pela região (`REGIOES_FORA`), grupo
  Sistema. Com a varredura completa o cockpit não mede mais nada depois (`ck["completa"]`, sem "medindo"/"estimado").
  Índice **v3** (coluna de pasta para `os`; meta `sistema` com a raiz). Testes: `H["raiz_sistema"]`/`H["so_sistema"]`
  dão um disco de mentira; sem eles, teste com pasta de mentira não lê o disco de verdade.
- **O que era pulado agora aparece** (pasta numa linha, com tamanho, sem ler por dentro, grupo Bloqueado): `.git`,
  `node_modules`, `.ssh` e chaves, `Library/Keychains|Mail|Messages|Safari|Cookies|Preferences`. Atalhos: linha de 0 B
  (tipo `atalho`). Só na nuvem: linha de 0 B, grupo "Só na nuvem", travada. Hard link: a 2ª vez com 0 B.
- **Travas com tipo** (`_trava` → motivo e tipo): `nucleo_so` (System, usr, bin, sbin, etc; Windows; no Linux também
  lib e boot) nunca destrava; `fixo` (atalho, a pasta do usuário inteira, as pastas principais) também não;
  `protegido` (o resto, inclusive programas fora das pastas) destrava com confirmação. O disco ou um usuário inteiro
  não destrava de uma vez. `zona_vermelha` continua sendo o portão de toda ação e respeita `DESBLOQ` (sessão).
- **Cadeado:** `POST /api/dados/desbloquear {no}` devolve o risco (`risco_trava`); com `confirmo: true` destrava e
  grava no histórico da máquina; `POST /api/dados/bloquear {no}` trava de novo. Na lista o 🔒 dos protegidos é botão
  (`dgDestravar`: pop-up com motivo, risco e caixa "Entendo o risco"); destravado mostra "Liberado por você · Travar de novo".
- O painel inicial (maiores pastas/arquivos) deixa o Sistema de fora, a não ser que o filtro de usuário peça.
- O Backup não muda (`plan_roots`/`walk_plan`): continua levando só o do cliente.

## 4 cards da Visão geral (parte C do plano da 3.8)
- `dgGeral` ganhou 4 cards acima dos cartões de Sugestão: **Espaço livre** (com "dá para liberar até X"), **Pessoal** (tamanho/arquivos
  do grupo, pela consulta do índice) , **Espaço já liberado** e **Ações rápidas** (Limpar o que é Limpável = abre o filtro e já marca, a
  confirmação continua na faixa; Fazer backup; Esvaziar a Lixeira; Atualizar a varredura).
- **Liberado** (`dd_backup.dados_liberado`): soma do histórico da máquina. Eventos de limpeza gravam `extra.liberado`: Lixeira só conta
  quando é esvaziada; copiar não conta; mover e apagar de vez contam. Eventos antigos entram pelo texto do resumo. Vem em `/api/dados/estado`.
- Não conferido no navegador.

## Finder no Gerenciamento (D1–D3 do plano da 3.8)
- **Barra lateral** (`dgLateral`): Favoritos (Mesa, Documentos, Downloads, Imagens, Filmes, Músicas da conta em uso), Locais (cada conta,
  Disco do sistema, Aplicativos/Programas, Lixeira, discos externos — estes abrem no explorador ao vivo), Etiquetas (= Grupos, com
  contagem; clique filtra) e Filtros (resumo + "Filtrar…" abre o modo detalhado, que ocupa a barra toda até "Concluir"). Seções
  recolhíveis, lembradas em `DG.fechF`. Rota nova `GET /api/dados/locais` (`dados.indice_locais`, tamanhos pelo índice).
- **Navegação**: voltar/avançar (`DG.hist`/`dgHist`, Alt+←/→), migalhas acima do título (Cmd/Ctrl+↑ sobe), "Pastas | Todos os arquivos".
  `dgGerenciar` tem contador de geração: cliques rápidos não desenham resposta velha.
- **Lista**: seta (SVG) abre a pasta no lugar (`dgAbre`, filhos do índice guardados em `DG.ab` e recarregados a cada redesenho; até 300
  arquivos por pasta, depois "… e mais N"). Clique seleciona o foco, clique duplo/Enter abre (pasta entra, arquivo mostra a prévia ou
  abre), espaço = prévia (sem prévia, marca), →/← abrem e fecham, clique direito abre o menu onde está o mouse.
- **Ícones** (`DG.modo`): grade com miniatura das imagens (cai no ícone se a imagem não abre), pasta com nº de arquivos, caixa de marcar.
- **Cockpit minimizável** (`DG.ckMin`): só a barra de 14px; passar o mouse mostra a legenda com os GB; "Expandir" volta.
- `tests/test_dados.py` usava o índice real do TMPDIR (falhava com uma varredura de verdade na máquina): agora usa pasta temporária.

## Etapas do backup na ordem nova (D4, parte 1)
- **Seleção · Origem e destino · Checagens · Cópia · Verificação · Programas · Conclusão.** Ids: Seleção 0, Origem e destino 1, Checagens 2;
  3 a 6 iguais (Retomar, ilha e certificado não mudam). O "Termo ✓" saiu da faixa de etapas.
- A Seleção escaneia sozinha com os discos de sistema desta máquina (`sel3Escanear` pega `/api/sources`); o destino não é exigido para
  escanear (`App.set_config` aceita sem destino; `totals().cabe` = None até haver destino). Origem e destino: se a origem mudou, escaneia
  de novo e volta à Seleção; senão vai às Checagens. Destino escolhido dentro da origem tira esses itens da lista.
- Checagens: só as checagens (o escaneamento saiu daqui) + resumo e "Iniciar cópia" (pré-voo de sempre). Exigem destino; `start_copy` também.
- Harness `bk.py`: a jornada inteira em ordem, sem erro de JS.

## Configurações › Termos (D5)
- O termo saiu da faixa de etapas; continua exigido antes de usar a ferramenta (o portão `openGate` abre ao iniciar sem aceite).
- `cfgTermos` em Configurações: termo aceito (versão, selo), quem aceitou e quando, máquina, dono (particular/terceiros), OS aberta,
  integridade do registro (`log_verificar`), as cláusulas para ler, "Abrir o termo para imprimir ou salvar em PDF" (`/api/doc/abrir`).
  Sem aceite: aviso e "Ler e aceitar o termo". Sem rota nova (`/api/termo`).

## Medição real da varredura completa (Mac do Marlos, 27/10/2026)
- MacBook Air M2, 245 GB: **1.119.902 arquivos, 200 GB, 281 mil pastas** (565 mil da conta, 555 mil do Sistema), 269 pastas sem permissão,
  162 arquivos só na nuvem. **Até 3 min 41 s** (programa aberto 16:47:05, varredura gravada 16:50:46). Índice: **726 MB** no TMPDIR.
- A partir de agora o índice guarda a duração (`params.duracao`) e o tamanho (`indice_estado().tamanho`), e o aviso de "Atualizar a
  varredura" mostra os dois da última vez.

## Não feito ainda
- (feito) Corrigir o histórico da máquina, só no Superusuário: "Corrigir" em cada evento da linha do tempo (`FICHA.hist_corrigir`,
  `POST /api/maquina/historico/corrigir`). Nada é apagado: o original, quem corrigiu e quando ficam em `extra.corrigido`, a marca
  "corrigido por X em …" aparece no evento (original no título) e a correção entra no log de consentimentos (`historico_corrigido`).
- (feito) Telas abertas fora de ordem: Cópia, Verificação e Conclusão dizem o que falta e levam à etapa certa (`semDados`).
- Não conferido no navegador. Testes: `tests/test_superusuario.py` e a suíte toda (206, OK).
- Ideia em aberto: levar o backup para dentro do Gerenciamento de dados.

## D4b — a Seleção virou o Finder (v3.9, BUILD 2026-10-27.3, branch `Finder-Bkp`)
- E0/E0b (commit b9cb253): interruptor **BKP Mode** (disquete, paleta `[data-modo=bkp]`), seção Destino na lateral e cartão origem → destino.
- **Guia "Vai no backup"** (`selGuia`, alimentado por `/api/groups`): uma etiqueta por categoria, agrupada pelos Grupos. A caixa leva ou
  tira a categoria inteira; o nome filtra o Finder (o `title` traz o `CAT_INFO` e os exemplos reais). Apagada = não vai. Total à direita
  (arquivos · tamanho · livres no destino). "Tipo desconhecido" e "Do sistema" entram como etiquetas de situação (`act`).
- **Finder do backup** (`bfCarrega`, `bfDesenha`, `bfCorpo`, `bfLinha`, `bfIcone`, `bfAbre`, `bfMenu`, `bfFoco`, teclado): começa em
  "Esta máquina" (usuários, WhatsApp, Pastas de origem, Disco C) e desce; voltar/avançar, migalhas, seta que abre no lugar, Pastas |
  Todos os arquivos, Lista | Ícones, ordem. Caixa da pasta = Levar tudo o que é pessoal dentro dela (com os filtros); caixa do arquivo =
  só ele. Faixa do topo: "X de Y vão", Levar tudo daqui, Não levar nada daqui, Voltar ao padrão, Pastas puladas. Misto: "Como copiar o que
  está aqui" (lote) e no menu ⋯ (pasta ou arquivo). Barra lateral (`lstSide`): Destino, Locais, Marcados e os filtros de sempre (`LST.f`).
- Não foi feito o `finder()` genérico do plano (E2): os dois Finders compartilham CSS, `menuAbre`, `dgTabela`, `FND_SETA`, `lstLinha`,
  `cpPill`, `grupoPill`; os dados são diferentes demais (seleção no servidor × no navegador) e o Gerenciamento ficou intacto.
- Backend: `direto=1` no filtro (`parse_filtro`) = só o que está na própria pasta; a chave da pasta no filtro passou a ser a mesma de
  `subpastas()` (`pk or local0 or local`). Sem rota nova. Teste `test_finder_pasta_direto_so_o_que_esta_nela`.
- Saíram a grade (`selGrade`, `selCorpo`, `SEL`) e a lista antiga (`abrirLista`, `lstCarrega`, `lstTr`, `lstBloco`…), mais 81 regras de CSS mortas.
- Conferido no harness (`fsel.py`, `bk.py`, `ger.py`): Finder, guia somando igual ao rodapé, marcar/desmarcar pasta e arquivo, chip
  filtrando, seta, teclado, ícones, Misto, claro/escuro/estreito, jornada inteira até a Conclusão e Gerenciamento. Sem erro de JS.
  **Falta o Marlos ver na máquina dele** (e com a varredura grande: cada clique refaz o filtro no servidor).
