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
