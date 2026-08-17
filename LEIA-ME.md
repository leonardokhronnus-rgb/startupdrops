# StartupDrops — Portal com reescrita automática

Portal de notícias que busca matérias das fontes por RSS, reescreve cada uma
com texto próprio da Redação (via API Anthropic) e publica sozinho, 3x ao dia.
Você não precisa colar nada à mão.

## Como funciona

- `netlify/functions/reescrever.mjs` roda automaticamente 3x ao dia (08h, 14h e 20h de Brasília).
  Puxa o RSS das fontes, detecta matérias novas, reescreve e salva no Netlify Blobs.
- `netlify/functions/materias.mjs` entrega as matérias prontas para o site.
- `collector.py` mantém o arquivo `data/news.json` com notícias de veículos brasileiros selecionados.
- `data/articles.json` reúne artigos autorais publicados no LinkedIn para a seção "Artigos".
- `index.html` é o portal: lê as matérias já reescritas e exibe na identidade StartupDrops.

## Artigos do LinkedIn

Adicione seus artigos em `data/articles.json` neste formato:

```json
{
  "profileUrl": "https://www.linkedin.com/in/seu-perfil/",
  "articles": [
    {
      "title": "Título do artigo",
      "excerpt": "Resumo curto para aparecer no card.",
      "url": "https://www.linkedin.com/pulse/...",
      "publishedAt": "2026-08-17T12:00:00-03:00",
      "source": "LinkedIn"
    }
  ]
}
```

## Deploy (passo a passo)

1. Crie um repositório no GitHub e suba estes arquivos (mantendo a estrutura de pastas).
2. No Netlify: "Add new site" → "Import from Git" → escolha o repositório.
3. Build settings: pode deixar em branco. Publish directory: `.` (ponto). Functions: `netlify/functions`.
4. Depois do primeiro deploy, vá em: Site settings → Environment variables → adicione:
   - Chave: `ANTHROPIC_API_KEY`
   - Valor: sua chave da API da Anthropic (começa com `sk-ant-...`)
5. Refaça o deploy (Deploys → Trigger deploy → Deploy site) para a variável valer.

## Testar sem esperar o horário

Funções agendadas não rodam em deploy preview, só em produção. Para forçar a primeira
rodada agora, abra no navegador (logado no Netlify, com o site publicado):

  https://SEU-SITE.netlify.app/.netlify/functions/reescrever

Aguarde uns segundos. Ela vai retornar um JSON tipo:
  {"ok":true,"candidatos":24,"publicadas":6,"total":6}

Depois abra o site normalmente e as matérias vão aparecer.

## Ajustes rápidos (em reescrever.mjs, no topo)

- `FONTES`: adicione ou remova feeds RSS.
- `MAX_POR_RODADA`: quantas matérias reescrever por execução (padrão 6). Mais = mais custo de API.
- `ITENS_POR_FEED`: quantos itens olhar por feed (padrão 4).
- `config.schedule`: o horário. Está em UTC. `0 11,17,23 * * *` = 08h/14h/20h Brasília.

## Custo

Cada matéria reescrita usa 1 chamada à API (Claude Sonnet). Com 6 por rodada e 3 rodadas,
são até 18 chamadas/dia. Ajuste `MAX_POR_RODADA` conforme seu orçamento.

## Observação sobre RSS

Alguns veículos mudam a URL do feed ou bloqueiam robôs. Se uma fonte parar de trazer
matérias, confira a URL do RSS dela e atualize em `FONTES`.
