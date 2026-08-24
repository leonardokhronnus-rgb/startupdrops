# Backend do StartupDrops

Esta versao usa backend real com Netlify Functions e Netlify Blobs. O site continua abrindo como pagina estatica, mas newsletter, analytics e curadoria online funcionam quando o projeto estiver publicado no Netlify.

## Onde publicar

1. Conecte o repositorio `leonardokhronnus-rgb/startupdrops` no Netlify.
2. Use as configuracoes que ja estao em `netlify.toml`.
3. Defina o dominio principal no Netlify quando quiser trocar do GitHub Pages para a versao com backend.

## Variaveis obrigatorias

Configure no Netlify:

- `OPENAI_API_KEY`: chave recomendada para reescrever e traduzir materias com a OpenAI.
- `ANTHROPIC_API_KEY`: opcional, usada como alternativa se `OPENAI_API_KEY` nao existir.
- `ADMIN_TOKEN`: uma senha longa para acessar dados privados e atualizar curadoria.

## Endpoints

### Newsletter

Cadastro publico:

```http
POST /.netlify/functions/newsletter
Content-Type: application/json

{
  "email": "nome@email.com",
  "source": "newsletter-form",
  "page": "https://..."
}
```

Exportar inscritos:

```http
GET /.netlify/functions/newsletter
Authorization: Bearer ADMIN_TOKEN
```

Remover um inscrito:

```http
DELETE /.netlify/functions/newsletter
Authorization: Bearer ADMIN_TOKEN
Content-Type: application/json

{
  "email": "nome@email.com"
}
```

### Analytics

O site envia automaticamente eventos de visualizacao, cliques, buscas, filtros, newsletter e branded content.

Consultar dados do dia:

```http
GET /.netlify/functions/analytics?day=2026-08-20
Authorization: Bearer ADMIN_TOKEN
```

### Curadoria editorial

O site carrega primeiro `data/editorial-overrides.json` e depois tenta carregar a curadoria online:

```http
GET /.netlify/functions/editorial
```

Atualizar curadoria online:

```http
POST /.netlify/functions/editorial
Authorization: Bearer ADMIN_TOKEN
Content-Type: application/json

{
  "hiddenUrls": ["https://exemplo.com/noticia-ruim"],
  "hiddenIds": [],
  "pinnedUrls": ["https://exemplo.com/noticia-importante"],
  "overrides": {
    "https://exemplo.com/noticia": {
      "title": "Titulo revisado",
      "summary": "Resumo revisado para aparecer no card."
    }
  }
}
```

## Observacao importante

No GitHub Pages, o site segue funcionando, mas as URLs `/.netlify/functions/...` nao existem. Para ter backend de verdade, a URL final precisa ser a do Netlify ou um dominio apontado para o Netlify.
