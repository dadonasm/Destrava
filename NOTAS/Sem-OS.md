# Sem-OS — sem ordem de serviço, máquina = cliente, Home de apresentação, fechamento do backup

Branch criada a partir de `Lista-e-Topo`. Pedido do Marlos depois do teste no Windows: a OS (ordem de
serviço) travava tudo em máquina de terceiros. Decisão: tirar a OS por enquanto e registrar por máquina.

## A. Sem OS (commit `492dd83`)
- `termo.exigir` só pede o termo aceito; não pede OS nem escopo. O código de OS fica dormente.
- Aba OS mostra "Em breve" (botão para Máquinas). Saíram o aviso "falta", o diálogo de OS e "Encerrar a OS".
- Ficha da máquina = perfil do cliente: dono editável (`salvar_contato(..., dono_nome)` grava `terceiro_nome`),
  contato e observações; o nome do dono aparece na lista de Máquinas e na Home.
- Engrenagem = **Configurações**: Permissões do sistema (`permCorpo`, `/api/permissoes`) + dados do técnico.
- Checagens do backup mostram o erro e "Tentar de novo" (antes ficavam em "Verificando…").

## B. Home de apresentação (commit `211f447`)
- `painel_resumo` ganhou `formatacoes` (o evento `formatacao` agora leva à etapa "formatada") e `melhor`
  (maior nota, com máquina e dono).
- `drawApresentacao`: 4 números (backups, espaço otimizado, formatações, melhor nota), 6 atalhos com ícone
  (backup, análise/ficha, otimizar, máquinas, mapa, configurações), últimas máquinas e pendências.
- A ficha desta máquina abre pelo atalho e sozinha ao fim de cada análise (`HOMEP`).

## C. Fechamento do backup
- "Iniciar cópia" roda o `/api/preflight` de novo: erro bloqueia; senão mostra o que cabe e os avisos.
- Conclusão: "Checagem final: nada se perdeu… Pode seguir com o objetivo" (ou as falhas), botão Certificado.
- Mapa guardado também em `maquinas/<id>/mapas/<código>/Mapa` (`_guardar_mapa`, histórico `mapa_registro`);
  `mapas_conhecidos` abre essa cópia quando o disco do backup não está ligado.
- O certificado abre sozinho na primeira vez que cada Mapa é aberto (`dd_cert_vistos` no navegador).

## Fica para depois
- OS de verdade (padronizar para o comercial).
- Certificado de formatação/restauração como documento (hoje só o evento `formatacao` no histórico).
- Instalar o sistema novo: o fluxo continua só reiniciando para a BIOS/UEFI.

## D. Processo parado: retomar ou encerrar como incompleto
- Aviso de pendência no perfil da máquina com ⚠ e dois botões: **Retomar de onde parou** e **Encerrar como incompleto**.
- `App.retomar(mid)` (`POST /api/backup/retomar`): depois de reiniciar o programa, recarrega o último backup da máquina a
  partir do `Mapa` (certificado, método de verificação, checagens/"mesmo disco") e só segue se o disco está conectado e
  todos os arquivos copiados existem com o mesmo tamanho. Abre o passo a passo em "O que manter" (ou em "Conclusão" se a
  receita já vale). "Definir o que manter" faz o mesmo quando há backup pendente; a tela avulsa só serve sem backup.
- Etapa terminal `encerrada` ("Encerrado incompleto") em `ficha.py`, como `entregue` (`TERMINAIS`): fecha o serviço, some a
  pendência, o próximo backup/análise abre serviço novo; a sessão do backup em memória é zerada.

## E. Passo 1 e Seleção mais limpos
- Identificação do certificado (cliente, técnico, equipamento) vem do cadastro: `App.identificacao()` (dono da máquina, perfil do
  técnico, nome da máquina); no passo 1 aparece só para leitura, com atalhos para editar no cadastro/perfil.
- Origens: some a "Pasta pessoal" quando um disco listado já a contém, e o pendrive do próprio programa (só como origem; continua
  como destino). Origem dentro de outra é descartada (tela avisa, servidor garante).
- **Pastas de origem** (antes "pastas-mãe", agora `Pastas_origem/<Nome>/`): `parece_nome_proprio()` soma 30 pontos; pastas com nome
  próprio direto na pasta do usuário também viram candidatas; nota ≥ 65 já vem marcada; memória em `pastas_origem.json` na pasta de
  dados (aceita/recusada por nome, contada ao iniciar a cópia). Mapas antigos com `Pastas_mae/` continuam abrindo.

## F. Disco explicado e filtros estilo e-commerce
- "Onde está o resto do disco?" na Seleção: depois da varredura, `App.iniciar_medicao()` mede em segundo plano as pastas puladas
  (Windows, programas, caches, lixeira; `add_ign(..., real)` guarda o caminho real) e compara com o usado do disco
  (`/api/medicao`). Para ao copiar, varrer de novo ou reset. "Encontrado" virou "Arquivos pessoais encontrados · de X usados no disco".
- "Ver lista" com barra lateral de filtros (Marcados, Categoria, Tipo, Situação, Data, Tamanho, Usuário/pasta de origem, Etiqueta), contagem
  em cada opção (calculada com os outros filtros, `App.filtrar`), "Ver mais", busca interna, intervalos de data/tamanho, etiquetas dos
  filtros ativos com "Limpar tudo", ordenação na linha da busca; no celular vira "Filtros (n)". Listas na URL separadas por `|`
  (`parse_filtro`), e o "marcar todos" respeita os mesmos filtros.

## G. Seleção que se explica e inclui tudo
- Categorias em 3 blocos (Pessoal · Você decide · Sistema e programas) com o catálogo `CAT_INFO` (o que é, para que serve, recomendação),
  exemplos reais de cada categoria (`groups()` → `ex`), "Marcar tudo o que foi encontrado" e "Voltar ao padrão" (`select({padrao})`, `Item.inc0`).
- WhatsApp por usuário: `local = "WhatsApp (<usuário>)"` e pasta própria no backup.
- Incluir o que a varredura não lê: `App.incluir_pastas` (categoria `Extras`, caminho original em `Disco_C/Extras/...`, pula pagefile/hiberfil/
  swapfile), `tirar_extras`; a varredura final repassa as pastas incluídas (`extras_planos`). Cada pasta de fora tem explicação (`EXPLICA_PASTA`).

## H. Erros do Windows sem ruído, Otimização nas máquinas e Seleção em grade
- Print do Windows (`BKP-Pro/Erros/`): milhares de "Acesso negado" no cache do Edge e no `Comms` do Windows, e `Errno 22` nos atalhos de
  `WindowsApps`. Agora: atalho de aplicativo (`APPEXECLINK`) não entra; falha por permissão/em uso fora do pessoal (`NAO_PESSOAIS`) vira
  `em_uso` (não é falha, não dá ressalva, fica no Mapa e no certificado em `nao_copiados_em_uso`); Verificação mostra as falhas pessoais primeiro
  e as de programas agrupadas por programa (`/api/falhas`, `/api/falhas/desmarcar`); dica de permissão certa quando já é administrador.
- Perfil da máquina em abas (`perfilAbas`, blocos com `data-aba`): Visão geral · Otimização · Diagnóstico · Histórico e backups. Home tem
  "Otimizar o desempenho" (abre a aba Otimização).
- Seleção: painel único em grade (`selGrade`/`selCorpo`/`selAtualiza`): abas Por categoria / Por usuário e pasta, filtro por bloco, busca, ordem,
  grupos recolhíveis, linha com detalhe; marcar atualiza só números (sem redesenhar). Estado em `localStorage` (`dd_sel`).
