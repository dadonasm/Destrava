# Manter-Programas — etapa "O que manter", receita.json e "Programas a reinstalar" no certificado

Branch criada a partir de `Inventario-Programas`. É a última das 5 partes do plano (`~/.claude/plans/planeja-em-partes-pra-cozy-ullman.md`).

## Checagem de existência

**Já existia (não refeito)**
- `programas.json` com os programas agrupados e o identificador de instalador (Parte 4).
- Etapas da máquina e o botão "Marcar como formatada" (Parte 2).
- Trava de formatar do Backup (`firmware_gate`), que já exigia certificado sem falhas, outro disco e verificação completa.
- Bloco opcional no certificado, no mesmo molde do "Técnico responsável" (Parte 1).

**Não existia (criado)**
- Escolha do que manter, `receita.json`, a trava nova e o bloco no certificado.

## O que ficou pronto

**Onde a etapa entra (decisão desta parte)**
- O plano sugeria uma tela separada, mas o certificado é gerado ao concluir o backup. Para "Programas a reinstalar" sair nele, a etapa precisa vir **antes** de concluir.
- Por isso ela virou um passo do Backup: Verificação → **O que manter** → Conclusão (agora são 7 passos). O botão do fim da Verificação virou "Continuar: o que manter →". O passo novo tem:
  - **Gravar e concluir o backup →**: grava a escolha, gera o certificado já com a lista e vai para a Conclusão.
  - **Pular por agora**: pede confirmação, conclui sem a lista e deixa a formatação bloqueada até a etapa ser feita.
  - **← Voltar**: volta para a Verificação.
- A mesma tela abre pela ficha da máquina (`view="manter"`), para fazer depois ou editar. Feita depois de gerado o certificado, ela libera a formatação, mas o certificado não muda (a tela avisa).
- Na Conclusão, se a formatação estiver bloqueada só por falta da etapa, aparece o botão "Definir o que manter".

**Tela "O que manter" (`nucleo/web/app.html`)**
- Lista de `programas.json` com:
  - caixa de seleção e busca;
  - filtro Todos / Só recomendados / Só marcados, e "Incluir escondidos";
  - categoria sugerida (navegador, escritório, leitor de PDF, e-mail, antivírus);
  - coluna "Reinstala sozinho?" ("sim · winget/Homebrew/…" ou "não · à mão");
  - nota livre em cada programa marcado.
- Primeira vez: os recomendados vêm marcados. Com uma escolha já gravada, reabre exatamente ela. Escolhidos e sugeridos ficam no topo.
- Barra de baixo: "N programas para reinstalar · X reinstalam sozinhos · Y à mão". Sem nenhum marcado, aparece a caixa "Não manter nenhum programa (combinado com o cliente)".
- Aviso fixo "Não anote senhas nem chaves de licença". Se uma nota parecer chave (`XXXXX-XXXXX-…`) ou tiver "senha/password", uma janela pede confirmação antes de gravar (D.8: só no campo livre, com aviso).
- Sem `programas.json` (máquina não analisada), a tela explica de onde vem a lista e deixa seguir só com "não manter nenhum".

**Dados (`nucleo/ficha.py`, `nucleo/programas.py`)**
- `salvar_receita(mid, escolhas, nenhum)` grava `maquinas/<código>/receita.json` com `versao`, `quando`, `tecnico` (de Meu perfil ou do termo), `nenhum` e `itens`.
  - Cada item tem `nome`, `fabricante`, `versao`, `instalador`, `automatico` e `nota`.
  - **Da tela só vêm nome e nota.** Fabricante, versão e instalador saem do `programas.json`; nome desconhecido é ignorado, e um "instalador" mandado pela tela não é usado.
  - Lista vazia só com `nenhum=True`.
  - Grava também um evento `receita` na linha do tempo.
- `receita_valida(mid)`: só vale a receita feita **no serviço atual**, depois do primeiro marco do serviço aberto ou depois da última entrega. A de um atendimento anterior não libera formatar.
- `programas.categoria()` e `com_sugestao()`: listas `CATEGORIAS` e `NUNCA_SUGERIR` (barras de ferramentas, "booster", "cleaner", "optimizer"…). Escondido nunca é sugerido. A sugestão é calculada na hora de mostrar, então listas antigas também a ganham.

**Travas**
- `marcar_etapa("formatada")` exige a receita válida (a etapa da Parte 2). Os testes da Parte 2 foram atualizados para fazer a receita antes.
- `firmware_gate()` (botão "Reiniciar para a BIOS/UEFI") também exige a receita. `/api/firmware_gate` devolve `falta_receita`.
- Ficha da máquina: quadro "O que manter depois de formatar" com "N programas a reinstalar (X sozinhos) · data · técnico" (verde) ou "ainda não definido neste serviço" com o botão "Definir o que manter". "Marcar como formatada" fica desabilitado até lá.

**Certificado**
- `cert.programas_resumo = {"n", "nomes"}` (só nomes, sem versão), quando a receita do serviço existe ao concluir.
  - Aparece na tela do certificado (`certificadoMapa`) e no `visualizador.html` (ES5) como "Programas a reinstalar: N", com os nomes. Com "nenhum", aparece "nenhum".
- Mapa antigo no visualizador novo: sem o campo, nada muda. Mapa novo no visualizador antigo: o campo é ignorado (cada Mapa leva sua cópia do visualizador).

**Rotas**: `GET /api/programas?mid=` agora traz também `receita` e `receita_valida`; nova `POST /api/maquina/receita {mid, itens:[{nome, nota}], nenhum}`; `/api/maquina` traz o resumo da receita no registro.

## Testes

- `python3 -m unittest discover tests`: **100 ok** (92 antigos + 8 novos; 14 do Django pulados sem Django instalado).
- Novo `tests/test_manter_programas.py`:
  - **Critério 8**: receita com 5 programas, relida em **outro processo**; tem os 5, a data e o técnico.
  - Nome desconhecido e repetido ignorados; o id vem do `programas.json`, não da tela; a nota é limpa.
  - Lista vazia recusada sem confirmação e aceita com ela.
  - "Formatada" bloqueada sem receita e liberada com receita vazia + confirmação.
  - Receita de atendimento anterior não libera, nem depois de entregue.
  - Sugestão: Chrome/Edge/Office/Acrobat sugeridos; "Avast Cleanup" e "Ask Toolbar" nunca; escondido nunca.
  - **Critério 9**: `receita.json` e `programas.json` só com os campos permitidos, sem "senha", "licen", "serial", "chave"…
  - Backup completo real (pasta temporária):
    - com a etapa feita antes de concluir, o certificado traz `{"n": 5, "nomes": [...]}` sem versões e a formatação libera;
    - pulando a etapa, o certificado sai como antes e a formatação fica bloqueada até a receita.
- Telas (Chrome headless, agente numa pasta temporária com a análise real deste Mac):
  - a etapa 6 de 7 no Backup (tema escuro) e a tela aberta pela ficha;
  - o quadro na ficha antes e depois de gravar pela API (formatada desabilitada → liberada);
  - 390px sem rolagem lateral (a tabela rola dentro do cartão).
- Visualizador offline de um Mapa gerado de verdade: "Programas a reinstalar: 5" com os nomes, abaixo de "Técnico responsável".

## Não testado

- Clique de verdade (a extensão do Chrome não estava conectada): marcar, escrever nota, a janela de "parece chave", "Pular por agora" e "Gravar e concluir" foram exercitados pela API e pelos testes, não pelo clique.
- O fluxo inteiro numa máquina de cliente: análise → backup → O que manter → certificado → reiniciar para a BIOS.
- Windows e Linux: valem as ressalvas da Parte 4 (lista de programas ainda sem teste real).
