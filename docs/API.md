# API

A documentação completa e interativa (OpenAPI) fica em `http://localhost:8000/docs` com a API rodando. Abaixo, as rotas principais. O dataset de demonstração tem id `demo-sintetico`.

## Datasets e importação

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/datasets` | Lista datasets com metadados e origem declarada |
| POST | `/api/datasets/upload` | Envia um CSV (`multipart/form-data`, campo `file`); retorna prévia e sugestão de mapeamento |
| GET | `/api/datasets/upload/{upload_id}/status-values?coluna=` | Valores distintos de uma coluna e categorias sugeridas |
| POST | `/api/datasets/import` | Aplica o mapeamento e cria o dataset |
| GET | `/api/datasets/{id}/quality` | Relatório de qualidade por equipamento |
| GET | `/api/datasets/{id}/series?equipamento=&variaveis=&inicio=&fim=&max_points=` | Séries (reamostradas) e faixas de estado |
| DELETE | `/api/datasets/{id}` | Remove um dataset importado |

Exemplo de corpo para `/api/datasets/import`:

```json
{
  "upload_id": "3f2a9c1d0b7e",
  "nome": "Motor da bomba P-101",
  "origem": "medicao_real",
  "roles": { "timestamp": "datetime", "equipamento": "asset_id", "estado": "status" },
  "status_map": { "RUNNING": "operando", "FAULT": "falha", "MAINTENANCE": "manutencao" },
  "variables": [
    { "column": "temperature_c", "action": "canonica", "key": "temperatura", "label": "Temperatura", "unit": "°C" },
    { "column": "pressure_bar", "action": "personalizada", "key": "pressao", "label": "Pressão", "unit": "bar" },
    { "column": "notes", "action": "ignorar" }
  ]
}
```

`origem` aceita `medicao_real`, `dataset_publico` ou `simulado` e é obrigatório.

## Análise e manutenção

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/analysis/{id}/trend?equipamento=&variavel=&janelas=6h,24h,7D&apenas_operando=` | Médias móveis, regressão e Mann-Kendall |
| GET | `/api/analysis/{id}/seasonality?equipamento=&variavel=` | ACF e decomposição STL |
| GET | `/api/analysis/{id}/profile?equipamento=&variavel=` | Perfis horário/semanal, histograma, envelope diário |
| POST | `/api/analysis/{id}/compare` | Compara dois períodos (`periodo_a`, `periodo_b` como `[início, fim]`) |
| GET | `/api/maintenance/{id}?equipamento=&min_falhas=2&min_dias=7` | MTBF, MTTR, disponibilidade, falhas |

Indicadores sem dados suficientes vêm assim:

```json
{ "valor": null, "unidade": "h", "status": "insuficiente", "motivo": "dados insuficientes (ver motivos)" }
```

## Machine Learning

| Método | Rota | Corpo (principais campos) |
|---|---|---|
| POST | `/api/ml/{id}/classification` | `modelo` (`random_forest`, `xgboost`, `baseline`), `equipamentos`, `horizonte_h`, `fracao_teste`, `limiar` |
| POST | `/api/ml/{id}/anomaly` | `equipamentos`, `contaminacao`, `fracao_teste` |
| POST | `/api/ml/{id}/forecast` | `equipamento`, `variavel`, `modelos`, `horizonte_h`, `holdout_h`, `periodo_h` |
| GET | `/api/ml/runs?dataset_id=` | Execuções (resumo) para comparação |
| GET / DELETE | `/api/ml/runs/{run_id}` | Detalhe completo / exclusão |

```bash
curl -X POST localhost:8000/api/ml/demo-sintetico/classification \
  -H "Content-Type: application/json" \
  -d '{"modelo": "xgboost", "equipamentos": ["MTR-01"], "horizonte_h": 24}'
```

Toda execução traz `dataset_sintetico` e `avisos` (poucas falhas, sobreajuste, dados simulados).

## Painel, alertas e relatórios

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/dashboard/{id}?referencia=` | Painel; `referencia` reconstrói o estado em um instante passado |
| GET | `/api/alerts/{id}?equipamento=&origens=limite,estatistica,modelo&severidade=&k=4` | Alertas e resumo por origem |
| GET | `/api/alerts/{id}/thresholds` | Limites configurados e efetivos |
| PUT / DELETE | `/api/alerts/{id}/thresholds/{equipamento\|*}/{variavel}` | Cria/edita (`min`, `max`, `severidade`, `duracao_min_min`) ou remove |
| GET | `/api/alerts/{id}/thresholds/suggest?equipamento=&variavel=` | Sugestão estatística de limites |
| POST | `/api/reports/{id}` | Relatório HTML (`equipamento`, `secoes`, `run_ids`, `titulo`, `autor`, `embutir_plotly`) |
