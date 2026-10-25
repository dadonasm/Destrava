# Inventario-Programas — lista estruturada dos programas instalados

Branch criada a partir de `Painel-Home`. Plano das 5 partes: `~/.claude/plans/planeja-em-partes-pra-cozy-ullman.md`.

## Situação por sistema (critério de aceite 6)

| Sistema | Estado |
|---|---|
| **Mac** | **Testado neste Mac (real)**: 29 itens, 26 visíveis, 6 com instalador (Homebrew), em ~3 s. Bate com `/Applications` + `~/Applications` + fórmulas do Homebrew pedidas pelo usuário. |
| **Windows** | **Não testado em máquina real.** Escrito sobre o mesmo PowerShell da ficha (chaves de Uninstall que já eram contadas) e coberto por um fixture sintético. |
| **Linux/Zorin** | **Não testado em máquina real.** Leitura das saídas coberta por testes com textos sintéticos de apt, Flatpak e Snap. |

## Checagem de existência

**Já existia (não refeito)**
- Contagem de programas por sistema (`medidas.prog_instalados`, usada na nota e nos alertas): continua igual.
- `dados._apps_instalados()`: continua só com nomes, para achar "restos" de programas. O inventário novo é um módulo à parte, para não mexer no que a aba Dados usa.
- `Mapa/programas_instalados.txt` do backup no Windows: intocado.

**Não existia (criado)**
- `nucleo/programas.py`: nome, versão, fabricante, origem e identificador de instalador; duplicados agrupados; runtimes, drivers e componentes escondidos.

## O que ficou pronto

**`nucleo/programas.py`** (só biblioteca padrão). A leitura do sistema fica em `coletar_*`; as funções que leem as saídas são puras e testáveis em qualquer sistema.

- **Mac**
  - `/Applications`, um nível de subpasta (ex. "Adobe Photoshop 2024/…app"), `/Applications/Utilities` e `~/Applications`.
  - Versão vem de `CFBundleShortVersionString`. Fabricante vem do copyright do `Info.plist` ou, sem ele, do identificador (`com.google.Chrome` → Google).
  - "App Store" quando há `_MASReceipt`.
  - Escondidos: apps da Apple que vêm com o sistema (Safari etc.) e atalhos de site do Safari. Os da Apple instalados pela App Store (Pages…) aparecem.
  - Homebrew: um cask que casa com um .app vira o identificador dele. Entram só as fórmulas pedidas pelo usuário (`brew leaves`), não as dependências. Rodando como root, o Homebrew é chamado como `SUDO_USER`; sem isso, é pulado.
- **Windows**
  - `PS_PROGS` entra no PowerShell da ficha: as 3 chaves de Uninstall (com versão, fabricante, nome da chave, 32/64 bits, usuário) e os apps da Microsoft Store que não são framework.
  - `winget list` só roda se o winget existir, com stdin fechado e **sem aceitar termos por ninguém**. Se ele pedir confirmação, a lista sai sem ids.
  - A tabela do winget é lida pelas posições do cabeçalho (inglês ou português). Nome cortado com "…" casa pelo começo. Só valem ids do winget e da Microsoft Store, nunca `ARP\…`/`MSIX\…`.
  - Escondidos: `SystemComponent`, subcomponentes (`ParentKeyName`) e apps `Microsoft.*` da Store.
- **Linux**
  - apt: aparece o pacote que tem atalho (.desktop) e foi instalado à mão.
    - Dependência (`/var/lib/apt/extended_states`) fica escondida.
    - O que veio na instalação do sistema (`/var/log/installer/initial-status.gz`) e o que não tem janela também ficam escondidos.
    - O nome mostrado é o do atalho ("GNU Image Manipulation Program" para `gimp`). O mapa pacote → atalho sai de `/var/lib/dpkg/info/*.list`, sem chamar o dpkg por arquivo.
  - Flatpak: só `--app`. Snap: bases e snapd ficam escondidos. rpm onde não há dpkg. Atalhos soltos em `~/.local/share/applications` (AppImage).
- **Esconder** (D.3): lista `OCULTAR` por motivo. Os motivos são runtime, atualização, driver, componente da fabricante e componente do sistema, além de "vem com o sistema", "dependência", "sem janela" e "atalho de site (Safari)".
- **Agrupar** (D.4): a chave do nome tira versão e 32/64 bits.
  - "7-Zip 23.01 (x64)" e "7-Zip 22.01" viram "7-Zip" com as duas versões.
  - Os dois Visual C++ 2015-2022 viram um só; Python 3.11 e 3.12 viram "Python".
  - Um grupo só fica escondido se todas as variantes forem escondidas.
- **Nunca licença/senha** (D.8): cada entrada passa por `entrada()`, que só guarda os campos listados em `CAMPOS`. Um campo extra vindo do sistema (ex. `ProductID`) é descartado (há teste).

**Ligações**
- `ficha.coletar(cb, programas=True)`: Mac/Linux chamam `PROG.coletar()`; no Windows a lista vem do PowerShell e do winget. A medição "depois" das melhorias usa `programas=False` (winget e Homebrew demoram).
- `salvar_ficha()`: a lista sai da ficha e vai para `maquinas/<código>/programas.json` (já agrupada), **só na análise "antes"**. A medição depois das melhorias não troca a lista. Gravação atômica, e no modo servidor o arquivo sobe como os outros (`_gravou`).
- Coleta exportada / reproduzida: Windows guarda `progs`, `appx` e `winget` na saída bruta; Mac/Linux guardam a lista na cópia da ficha. Assim a reprodução refaz a lista.
- `visao(mid)` ganhou `programas` (resumo: total, visíveis, com instalador).
- Rota `GET /api/programas?mid=`.
- `nucleo/__init__.py`: `programas` em `LEVES`.

**Tela (`nucleo/web/app.html`)**
- Bloco "Programas instalados" na ficha, na Home e na Ficha completa: "N programas para decidir o que reinstalar · X reinstalam sozinhos · Y escondidos", com o botão **Ver lista**.
  - Máquina analisada antes desta parte: mostra a contagem antiga e avisa que a lista entra na próxima análise.
- Lista: busca por programa ou fabricante e "Mostrar tudo (+Y escondidos)". Os escondidos aparecem esmaecidos e com o motivo. Colunas:
  - versão (mais recente, "+N" com as outras ao passar o mouse, "32 e 64 bits");
  - origem;
  - "sozinho · winget/Homebrew/…" ou "à mão".

## Testes

- `python3 -m unittest discover tests`: **92 ok** (80 antigos + 12 novos; 14 do Django pulados sem Django instalado).
- Fixture novo `tests/fixtures/win10_programas.json`: chaves do registro, apps da Store e um `winget list` em português, com nome cortado e um id ARP. O `win10_hd.json` não foi mexido; há teste de que coleta antiga, sem lista, continua sem lista.
- Novo `tests/test_inventario_programas.py`:
  - winget em português e em inglês (sem a coluna "Disponível"), com nome cortado, ARP recusado e Store por começo de nome. O "Microsoft Edge Update" não pega o id do Edge;
  - duplicados (32/64 bits, versões) e o que fica escondido, por motivo; "mostrar tudo" devolve a lista inteira; visíveis primeiro;
  - nenhum campo além dos permitidos (licença e senha descartados);
  - Mac com `.app` falsos (Info.plist, App Store, Safari, atalho de site, subpasta) e Homebrew (cask casa com o .app, dependência fora);
  - Linux: apt (dependência, vem com o sistema, sem janela, removido), Flatpak e Snap;
  - `programas.json` gravado na análise, a ficha sem a lista, e a análise "depois" sem trocar a lista.
- Ponta a ponta neste Mac: análise real gravando numa pasta temporária, agente rodando nela.
  - O bloco da ficha mostrou "26 programas · 6 reinstalam sozinhos · 3 escondidos".
  - A lista abriu com busca e "Mostrar tudo", nos temas claro e escuro (prints do Chrome headless).

## Não testado

- **Windows e Linux/Zorin em máquina real** (ver a tabela no topo). Pontos a conferir no primeiro teste real:
  - Windows: o tempo do `winget list` na primeira vez; a lista bate com "Aplicativos e recursos"; os ids aparecem para Chrome, Office e 7-Zip; a codificação dos acentos na saída do winget.
  - Zorin: o `initial-status.gz` existe e esconde o que veio com o sistema; o nome dos atalhos.
- Clique de verdade na tela (a extensão do Chrome não estava conectada).
