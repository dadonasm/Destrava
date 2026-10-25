# Registro-Maquinas — etapa por máquina, tela Máquinas no modelo de Leads e Ficha completa

Branch criada a partir de `Visual-Copia`. Plano das 5 partes: `~/.claude/plans/planeja-em-partes-pra-cozy-ullman.md`.

## Checagem de existência

**Já existia (não refeito)**
- Código `DD-XXXX-XXXX`, `meta.json` e `historico.json` por máquina (`nucleo/ficha.py`). O registro é uma visão montada desses arquivos, sem base nova.
- Rota `/api/maquinas` e `/api/maquina?mid=` (agora com mais campos).
- Ficha de diagnóstico de uma máquina (`renderFicha`): continua igual, embaixo do registro.

**Existia parcial (completado)**
- Tela Máquinas: era uma lista de cartões com nota. Virou a tela no modelo de Leads.
- Técnico: era só texto do termo. Agora cada evento do histórico grava `extra.tecnico` (nome de Meu perfil ou, sem perfil, o nome do termo).

**Não existia (criado)**
- Etapa da máquina, transições, importação das antigas, pendências, contato/observações, exportar planilha.

## O que ficou pronto

**Modelo de dados (`nucleo/ficha.py`, seção "registro")**
- `meta.json` ganha `etapa` e `etapa_historico` (`{"etapa","quando","tecnico","origem"}`, origem = `auto`, `manual` ou `importada`) e, editáveis, `telefone`, `email`, `observacoes`.
- Etapas: `recebida`, `diagnosticada`, `backup_verificado`, `otimizada`, `formatada`, `entregue`.
- Transições automáticas: um único ponto, `hist_add()`. Cada evento passa por `etapa_do_evento()`:
  termo → recebida; ficha (antes) → diagnosticada; backup **sem falhas** → backup verificado; melhorias com pelo menos 1 aplicada → otimizada.
- Manuais: `marcar_etapa(mid, "formatada"|"entregue", confirmar)`, que grava um evento `etapa` no histórico. Formatada sem backup verificado no serviço atual devolve `{"confirmar": ...}` e só grava com `confirmar=True`. Outras etapas à mão → erro.
- Regras:
  - Cada etapa entra uma vez por serviço. A etapa mostrada é a **mais adiantada** do serviço atual: se melhorar antes do backup, o backup ainda entra no histórico, e a etapa fica "Otimizada".
  - Depois de "entregue", qualquer marco abre um **serviço novo na mesma entrada** (a máquina voltou). `servicos` conta quantos.
- Pendências (`pendencia()`): "Backup feito e ainda não entregue" e "Diagnosticada há N dias sem backup" (`DIAS_PENDENTE = 7`). A Parte 3 pode reaproveitar.
- Máquinas antigas: sem `etapa_historico`, as etapas são refeitas pelo histórico, com técnico "desconhecido". Sem nenhum marco, ficam como "recebida". **Listar não grava nada**. A importação é gravada no `meta.json` no primeiro evento novo daquela máquina, com o histórico antigo entrando antes do evento novo.
- `listar_maquinas()` agora monta cada linha com `linha_registro()` e inclui máquinas só com termo, ainda sem ficha. Campos novos: etapa, serviços, pendência, técnico, sistema, família, série, contato, último serviço, nota antes/depois do serviço atual, espaço recuperado e melhorias.
- `exportar_csv(mids)`: CSV com BOM UTF-8 e **ponto e vírgula** (o Excel em português abre direto em colunas). Texto que começa com `= + - @` ganha `'` na frente, para não virar fórmula.
- Evento `backup` do histórico ganhou `status` e `bytes` (a Parte 3 pode somar os "dados protegidos").
- `perfil.checar_contato()`: a validação de e-mail e telefone do perfil, reaproveitada no contato do dono.

**Rotas (`nucleo/dd_backup.py`)**
- `GET /api/maquinas`: linhas novas + lista de etapas.
- `GET /api/maquina?mid=`: + `registro` (linha, etapas, histórico com a etapa de cada evento). Funciona também para máquina sem ficha.
- `POST /api/maquina/etapa {mid, etapa, confirmar}`, `POST /api/maquina/registro {mid, telefone, email, observacoes}`.
- `POST /api/maquinas/exportar {mids}`: devolve o CSV como download.
- A tela só manda códigos `DD-…`; nenhuma chamada nova recebe caminho de arquivo. Código desconhecido → "Máquina não encontrada".
- Diferença do plano: a rota manual ficou `/api/maquina/etapa` com `mid` no corpo, como `/api/maquina/nome` já fazia, e não `/api/maquina/<mid>/etapa`.

**Tela (`nucleo/web/app.html`)**
- Máquinas: título com selo de contagem, botões "Meu perfil" e "Exportar para Excel".
  - Busca por código, dono, telefone (também só os números), modelo, série e e-mail, sem diferenciar acentos.
  - Filtros Sistema, Técnico e Período; ordenar por mais recentes, mais antigas, maior nota ou espaço recuperado. O cabeçalho da tabela também ordena.
  - Abas com contagem: Todas, as 6 etapas e Pendentes. Elas contam o que passa na busca e nos filtros. Uma aba "Sem situação" só aparece se existir máquina sem etapa (não deve acontecer).
  - Tabela com seleção, que se mantém ao trocar de página e de filtro, e paginação de 25 ("1 a N de N").
  - Exportar: só as marcadas, se houver; senão, as linhas da tela.
- Privacidade (decisão padrão do plano): a lista **não mostra o nome do dono**, só Particular/Terceiros, os 4 últimos dígitos do WhatsApp e o e-mail mascarado. A busca encontra pelo dono mesmo assim. Tudo aparece na Ficha completa.
- Ficha completa (clicar na linha): etapas do serviço atual com data e técnico, pendência, botões "Marcar como formatada/entregue" (formatada sem backup pede confirmação), números (serviços, nota, melhorias, espaço, backups), dono e contato editáveis com link para o WhatsApp, observações, tabela "Etapas de cada serviço" e linha do tempo de todo o histórico. Se a máquina tiver ficha de diagnóstico, ela continua embaixo.
- Cabeçalho em telas de até 520px: esconde "by D&D Technology" e pode quebrar linha. Medido num iframe de 390px: a Home, Máquinas, Ficha completa e Meu perfil ficam sem rolagem lateral; a tabela rola dentro do cartão.

## Testes

- `python3 -m unittest discover tests`: **75 ok** (65 antigos + 10 novos; 14 do Django pulados sem Django instalado).
- Novo `tests/test_registro_maquinas.py`:
  - fluxo completo com `termo.aceitar` + ficha real (fixture win10) + backup + melhorias: a etapa avança. Backup com ressalvas e 0 melhorias não contam; analisar de novo não repete a etapa; técnico do termo e do perfil;
  - melhorar antes do backup não perde o backup;
  - manual: etapa inválida e máquina inexistente recusadas; formatada sem backup pede confirmação; não marca duas vezes; com backup, formata direto;
  - importação de pasta antiga sem etapa: técnico "desconhecido", listar não grava, e o histórico antigo entra antes do evento novo;
  - a mesma máquina duas vezes vira uma entrada com 2 serviços, e a nota "antes" é a do serviço atual; duas máquinas viram duas linhas;
  - a soma das abas por etapa bate com o total;
  - pendência de diagnóstico parado; contato validado e gravado sem mexer na etapa;
  - CSV: BOM, `;`, acentos, só as marcadas, código desconhecido ignorado, fórmula neutralizada.
- Rotas testadas à mão com o agente (`--dados` numa pasta temporária, 4 máquinas sintéticas): listar, exportar (cabeçalhos e conteúdo), confirmação de formatada, telefone inválido → 400, `mid` com `../` → "Máquina não encontrada".
- Prints com o Chrome headless (cópia temporária da página, já apagada): lista no tema claro e no escuro, aba Pendentes com seleção, Ficha completa com e sem ficha de diagnóstico, e 390px (via iframe).
- Observação para as próximas partes: o Chrome headless não desce abaixo de 500px de largura. Para medir 390px, use a página dentro de um `<iframe>` de 390px.

## Não testado

- Clique de verdade na tela (a extensão do Chrome não estava conectada): baixar a planilha pelo navegador e abrir no Excel, digitar na busca, trocar de página, os diálogos de formatada e entregue. As funções foram exercitadas pela API e pelos prints, não pelo clique.
- Máquina real: nada depende do sistema, mas o fluxo completo termo → ficha → backup → melhorias com a etapa avançando só rodou nos testes.
- Modo servidor da loja: a lista vem de `listar_maquinas()` rodando no servidor (`apps/servidor/armazenamento.indice`), que usa o mesmo `ficha.py`. O servidor só mostra os campos novos depois de atualizado com este `nucleo/`. `apps/servidor/` não foi tocado.
