# Conta-Tecnico — perfil do técnico, engrenagem e bloco no certificado

Branch criada a partir de `Django`. Plano completo das 5 partes: `~/.claude/plans/planeja-em-partes-pra-cozy-ullman.md`.

## Checagem de existência

**Já existia (não refeito)**
- Campo texto livre `tecnico` por máquina: `termo.aceitar()` grava em `meta.json`; campo "Técnico" do backup (`S.tecnico`) vai para `cert["tecnico"]`.
- Certificado: `dd_backup._write_mapa()` monta `cert`; tela em `certificadoMapa()` (app.html); cópia autônoma em `visualizador.html`.
- Cabeçalho fixo (`<header>`) com botões à direita.

**Existia parcial (completado)**
- Técnico no certificado: era só um nome digitado. Agora o certificado também leva `tecnico_perfil`, uma cópia dos campos marcados do perfil.

**Não existia (criado)**
- Perfil salvo em arquivo, engrenagem e tela "Meu perfil".

## O que ficou pronto

- `nucleo/perfil.py`: `ler()`, `validar()`, `salvar()`, `snapshot()`. Arquivo `perfil.json` na pasta de dados (`--dados`; no pendrive fica na raiz). Gravação atômica (`.tmp` + `os.replace`).
  - Campos: nome, empresa (padrão "D&D Technology"), email, telefone, instagram, site, facebook, linkedin, outro, e a lista `no_certificado` com o que vai para o certificado (padrão: nome e empresa).
  - Validação simples: e-mail com `@` e domínio; telefone de 10 a 13 dígitos (aceita `+`, espaço, parênteses, hífen). Redes sociais nunca bloqueiam. Máximo de 120 letras por campo. Campos desconhecidos são descartados.
  - `snapshot()` retorna vazio se não houver nome: sem perfil, o certificado não ganha o bloco.
- Rotas `GET /api/perfil` e `POST /api/perfil` (`dd_backup.py`, no padrão de `api_get`/`api_post`; erro de validação volta 400 com a mensagem).
- Pasta de dados: `usar_pasta_dados()` também aponta o perfil. No modo servidor com cache próprio, o perfil continua na pasta local, porque o cache é apagado ao sair. Nada do perfil vai para o servidor da loja.
- Certificado: campo **opcional** `tecnico_perfil` em `cert`, gravado em `certificado.json` e `dados.js`. Se o campo "Técnico" do backup ficar vazio, `cert["tecnico"]` recebe o nome do perfil **só se o nome estiver marcado**. O evento `backup` do `historico.json` também guarda `tecnico` e `tecnico_perfil`, uma cópia daquele momento.
- Tela (`app.html`): engrenagem `#hperf` no cabeçalho, tela "Meu perfil" (`drawPerfil`) com caixa "no certificado" por campo e prévia ao vivo do bloco "Técnico responsável". O bloco aparece na tela do certificado (`certificadoMapa`). O nome do perfil é pré-preenchido no termo (`#gnm`) e no campo Técnico do backup (`#tec`, só se o nome estiver marcado).
- `visualizador.html`: bloco "Técnico responsável", em ES5 como o resto do arquivo, só quando `cert.tecnico_perfil` existe.
- `nucleo/__init__.py`: `perfil` entrou em `LEVES`, para não existir uma segunda cópia do módulo nos testes.
- `.gitignore`: `perfil.json` e `perfil.json.tmp`.

Diferença do plano: as marcações ficaram numa lista `no_certificado`, e não em um booleano `*_no_certificado` por campo; as redes ficaram planas, e não em `redes: {...}`. É mais simples e dá o mesmo resultado.

## Compatibilidade

- Mapa antigo no visualizador novo: sem `tecnico_perfil`, o bloco não aparece e o resto fica igual (`c.tecnico_perfil||{}`).
- Mapa novo no visualizador antigo: o campo extra é ignorado. Cada Mapa já leva sua própria cópia do `visualizador.html`.
- O código do certificado continua sendo o hash do `dados.js`; o campo novo entra antes do cálculo, como os demais.

## Testes

- `python3 -m unittest discover tests`: **65 ok** (57 antigos + 8 novos; 14 do Django pulados sem Django instalado).
- Novo `tests/test_perfil.py`:
  - sem perfil → sem bloco; salvar e ler de novo em **outro processo** (reabrir o programa);
  - snapshot só com os campos marcados; validação de e-mail/telefone/tamanho sem gravar nada quando falha; campos desconhecidos descartados;
  - backup completo com perfil: o certificado tem só nome e Instagram, sem e-mail e sem telefone; mudar o perfil depois **não altera** o certificado já gerado;
  - nome desmarcado não vaza em `cert["tecnico"]`; sem perfil, o certificado sai igual ao formato antigo.
- Teste manual das rotas com o agente rodando (`--dados` numa pasta temporária): GET vazio, POST com e-mail inválido → 400, POST válido → `perfil.json` na pasta de dados e snapshot correto.
- Sintaxe dos scripts de `app.html` e `visualizador.html` conferida com o JavaScriptCore do macOS.

## Não testado

- **Tela no navegador**: a extensão do Chrome não estava conectada nesta sessão. Falta abrir e conferir a engrenagem, a tela "Meu perfil" (salvar, erro de e-mail, prévia), o bloco no certificado da tela e no `visualizador.html` de um Mapa novo, e a largura de celular.
- Máquina real Windows/Linux: nada específico de sistema nesta parte, mas o fluxo completo (termo → backup → certificado) com perfil ainda não rodou fora dos testes.
