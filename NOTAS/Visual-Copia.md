# Visual-Copia — "de onde → para onde" na etapa 1 do Backup

Branch criada a partir de `Conta-Tecnico`. Só visual: nenhuma rota, nenhum arquivo além de `nucleo/web/app.html`.

## O que mudou

- Referência: a janela de instalação de apps do Mac (ícone → seta → pasta Aplicativos).
- Topo da etapa "Origem e destino": faixa `#fluxo` (função `drawFluxo()`) com a legenda "Copiando do computador para o disco do backup. A origem só é lida: nada é apagado." e três partes:
  - **Origem**: ícone de computador, nome da 1ª origem marcada (+N se houver mais) e "X GB usados · só leitura" (ou "N origens · só leitura"). Clicar rola até a lista de origens.
  - **Seta**: triângulo com três pontos animados da esquerda para a direita. Fica azul quando origem e destino estão prontos e apagada (sem animação) quando falta um dos dois. Com "menos movimento" ligado no sistema, a regra global já para a animação.
  - **Destino**: pasta azul com o símbolo de salvar, o nome da pasta do backup e "em <disco> · X GB livres". Sem destino: bloco tracejado "Escolher destino", que abre o mesmo seletor do botão "Escolher…". Pasta inexistente: aviso em vermelho.
- Embaixo, os cartões "De onde vamos copiar?" (ORIGEM) e "Para onde vai o backup?" (DESTINO) ficam lado a lado (grid `.od`) e empilham abaixo de 900px. A lógica é a mesma de antes.
- A faixa se atualiza sozinha: `drawSrcs()` e `destInfo()` chamam `drawFluxo()`, e o resultado do `/api/ls` do destino fica em `S.destLs`. O campo "Nome da pasta do backup" também atualiza a faixa.
- Identificação, Continuar e o que vai para `/api/config` não mudaram.

## Testes

- `python3 -m unittest discover tests`: 65 ok (14 do Django pulados).
- Sintaxe do script conferida com o JavaScriptCore (`osascript -l JavaScript`).
- Prints com o Chrome headless (agente com `--dados` numa pasta temporária, cópia temporária da página abrindo direto no Backup): sem destino (tracejado + seta apagada), com destino e 2 origens (pasta azul, "+1", espaço livre, seta azul), tema escuro e largura de 390px.

## Não testado / observações

- Clique de verdade nos blocos e a animação ao vivo: os prints são estáticos (a extensão do Chrome não estava conectada).
- Em 390px a página inteira já transbordava para os lados antes desta mudança (cabeçalho e barra de etapas). Não mexi nisso, porque o pedido era só a etapa da cópia.
