# Painel-Home — Home com painel do trabalho

Branch criada a partir de `Registro-Maquinas`. Plano das 5 partes: `~/.claude/plans/planeja-em-partes-pra-cozy-ullman.md`.

## Checagem de existência

**Já existia (não refeito)**
- O registro da Parte 2: `listar_maquinas()` já trazia etapa, pendência, nota antes/depois, espaço e melhorias; `pendencia()` e a aba Pendentes também já existiam.
- Home: `drawHomeVazia()` (boas-vindas e 4 passos) e `renderFicha()` (ficha desta máquina). Continuam iguais.

**Não existia (criado)**
- Resumo do painel, rota, tela do painel, faixa "Ver painel" e filtros que o painel liga na tela Máquinas.

## O que ficou pronto

**`nucleo/ficha.py`**
- `painel_resumo(atual, agora)`: calcula tudo a partir das linhas de `listar_maquinas()`. Sem ler arquivo extra, funciona igual no modo servidor.
  - Máquinas atendidas e quantas estão em andamento (etapa diferente de entregue).
  - Serviços concluídos = marcações "entregue", no total e no mês, e em quantas máquinas.
  - Nota média antes → depois, só nas máquinas com as duas notas no serviço atual.
  - Taxa de otimização (decisão adotada): entre as máquinas com melhorias aplicadas **e** nota antes e depois, a % em que a nota depois é maior, e a média de pontos ganhos.
  - Espaço recuperado (eventos de limpeza) e dados protegidos (soma dos backups), com quantas máquinas.
  - Pendências (a mesma regra da aba Pendentes) e as 5 últimas máquinas.
  - `compacto`: nenhuma **outra** máquina teve evento hoje. O termo aceito na máquina atual não tira o modo compacto.
- Cada linha do registro ganhou `backups` e `protegido`. Backups antigos, de antes do campo `bytes`, entram pelo tamanho escrito no resumo, ex. "(212,40 GB)", em base 1024 como o `fmt_bytes`.

**Rota**: `GET /api/painel`.

**Tela (`nucleo/web/app.html`)**
- Home:
  - Sem nenhuma máquina no registro: a tela de boas-vindas de antes. Ela é o "estado vazio" e não mostra números zerados.
  - Com máquinas e esta máquina ainda sem ficha: o **Painel**. Primeiro o cartão "Pronto para o próximo atendimento", com o botão grande **Atender nova máquina** (mesmo fluxo de antes: termo e análise) e "Ver permissões". Depois 7 números clicáveis e, embaixo, "Últimas máquinas" e "Pendências".
  - Modo compacto (primeiro atendimento do dia): só o cartão e os números, com o botão "Mostrar últimas máquinas e pendências".
  - Esta máquina já com ficha: a ficha continua sendo a Home (os fluxos de analisar e melhorar voltam para ela). Em cima entra uma faixa "Painel · N máquinas · X pendências · **Ver painel**". O painel aberto por ali troca o cartão de atendimento por "Esta máquina" com "Voltar para a ficha desta máquina". Qualquer navegação volta para a ficha.
- Cada número abre a tela Máquinas com exatamente as máquinas que formam o número:

  | Número | Filtro na tela Máquinas |
  |---|---|
  | Máquinas atendidas | todas |
  | Serviços concluídos | com serviço concluído |
  | Nota média | com nota antes e depois |
  | Taxa de otimização | com melhorias medidas antes e depois |
  | Espaço recuperado | com espaço recuperado, ordenado por espaço |
  | Dados protegidos | com backup |
  | Pendências | aba Pendentes |

  - O filtro do painel aparece como um selo "Do painel: … ✕" acima das abas. "Limpar busca e filtros" também tira o selo.
- Na lista e no painel aparecem só o código e o modelo, nunca o nome do dono (mesma decisão da Parte 2).

## Testes

- `python3 -m unittest discover tests`: **80 ok** (75 antigos + 5 novos; 14 do Django pulados sem Django instalado).
- Novo `tests/test_painel.py`:
  - zero máquinas → tudo vazio, sem número inventado;
  - 3 máquinas sintéticas conferidas à mão (critério de aceite 4):
    - A: 40 → 70, 2 melhorias, 3 GB limpos, backup de 100 GB, entregue;
    - B: 50 → 45, 1 melhoria, backup antigo de 10 GB só no texto;
    - C: só o termo;
    - resultado: 3 máquinas e 2 em andamento, 1 concluído, nota 45 → 57,5, taxa 50% com +12,5 pontos, 3 GB recuperados, 110 GB protegidos em 2 backups;
  - um serviço concluído em outro mês não conta no mês;
  - pendência de backup sem entrega aparece e some depois de entregue (critério de aceite 5);
  - modo compacto quando só a máquina atual mexeu hoje, e completo quando outra máquina já foi atendida.
- Com o agente rodando numa pasta temporária (máquinas sintéticas), prints do Chrome headless:
  - painel compacto e completo;
  - número clicado → lista filtrada com o selo;
  - faixa "Ver painel" em cima da ficha, e o painel com "Voltar para a ficha".
- Medido num iframe de 390px (o headless não desce abaixo de 500px): sem rolagem lateral.
- Conferência à mão: "Dados protegidos" mostrou 277,82 GB para backups de 212 000 000 000 e 65 820 373 811 bytes. A tela usa GB decimal (como o Finder), e a soma bate.

## Não testado

- Clique de verdade (a extensão do Chrome não estava conectada): os botões foram exercitados pelos prints com a página abrindo direto em cada estado, não por clique.
- Máquina real: o "Atender nova máquina" chama o mesmo fluxo de antes (`/api/ficha/coletar` → termo → análise), mas não rodou numa máquina de cliente.
- Modo servidor: o painel usa o índice do servidor (`listar_maquinas` lá), que só traz `backups`/`protegido` depois de o servidor rodar este `nucleo/`.
