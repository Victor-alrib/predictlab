# Arquitetura

## Visão geral

```
┌──────────────────────────── Navegador ────────────────────────────┐
│ React + TypeScript + Tailwind CSS                                 │
│  pages/  Painel · Importação · Análise · Manutenção · ML ·        │
│          Alertas · Relatórios · Metodologia                       │
│  components/Plot.tsx  → Plotly.js carregado sob demanda           │
│  api/client.ts        → tipos e chamadas HTTP                     │
└───────────────────────────────┬───────────────────────────────────┘
                                │ JSON (REST)  /api/*
┌───────────────────────────────▼───────────────────────────────────┐
│ FastAPI (app/main.py)                                             │
│  api/datasets.py   upload → mapeamento → importação, séries       │
│  api/analysis.py   tendência, sazonalidade, perfil, comparação,   │
│                    indicadores de manutenção                      │
│  api/ml.py         classificação, anomalia, previsão, execuções   │
│  api/ops.py        painel, alertas e limites, relatórios          │
├───────────────────────────────────────────────────────────────────┤
│ services/  (Pandas, NumPy, SciPy, scikit-learn, XGBoost,          │
│             statsmodels, Plotly) — sem dependência de HTTP        │
├───────────────────────────────────────────────────────────────────┤
│ store.py   DatasetStore: datasets (memória + pickle em            │
│            backend/data/), uploads pendentes, execuções de ML     │
└───────────────────────────────────────────────────────────────────┘
```

## Fluxo de um CSV

```
arquivo.csv
   │  parse_csv: codificação, separador, decimal
   ▼
DataFrame de texto ──► suggest_mapping (aliases + inspeção dos valores)
   │                         │
   │   usuário revisa/edita  ▼
   └────────────────► apply_mapping ──► Dataset (esquema interno)
                                          │
              ┌─────────────┬─────────────┼──────────────┬─────────────┐
              ▼             ▼             ▼              ▼             ▼
          quality      timeseries    maintenance    features → ml   alerts
                                                                       │
                                     dashboard ◄───────────────────────┤
                                     reports   ◄───────────────────────┘
```

O upload é feito em duas etapas: o arquivo fica em *staging* (`stage_upload`) enquanto o usuário revisa o mapeamento; só então `apply_mapping` gera o dataset. Isso permite reabrir a sugestão de categorias de estado ao trocar a coluna de estado sem reenviar o arquivo.

## Decisões técnicas

| Decisão | Motivo |
|---|---|
| Serviços puros em `services/`, rotas finas em `api/` | Toda a lógica é testável sem servidor; a mesma função alimenta API, painel e relatório |
| Esquema interno fixo (timestamp/equipamento/estado + variáveis) | Datasets heterogêneos viram uma estrutura única; módulos não precisam conhecer o CSV original |
| Variáveis presentes por equipamento calculadas dinamicamente | Um mesmo dataset pode ter equipamentos com sensores diferentes (ex.: inversor sem vibração) |
| `data_origin` obrigatório no modelo de dados | A distinção simulação × medição não depende de disciplina do usuário; ela é estrutural |
| Treinos em `run_in_threadpool` | Treinos de alguns segundos não bloqueiam o loop assíncrono do FastAPI |
| Cache de alertas por hash (dataset, limites, execuções) | Painel e tela de alertas reutilizam o mesmo cálculo |
| Downsampling por janela de tempo no servidor | Gráficos recebem no máximo alguns milhares de pontos, preservando a forma da série |
| Plotly no frontend e no relatório | Mesma biblioteca de gráficos interativos nos dois lugares; relatório embute a biblioteca e abre offline |
| Plotly carregado com `import()` dinâmico | A primeira tela renderiza sem esperar ~3,5 MB de JavaScript |
| API serve `frontend/dist` quando existe | Um único processo para demonstração; em desenvolvimento, Vite faz proxy de `/api` |

## Linguagem visual

A interface segue princípios de IHM de alto desempenho (ANSI/ISA-101): fundo cinza neutro, processo em tons de cinza e aço, e cor saturada reservada a condições anormais. Estado "normal" não é verde — é ausência de destaque. As origens de alerta usam cor **e** forma (▲ ◆ ◉), para não depender só de cor. Dados simulados recebem uma faixa de sinalização âmbar/preta fixa no topo, inspirada em sinalização de segurança.

Tipografia: IBM Plex Sans para interface e IBM Plex Mono com algarismos tabulares para valores numéricos, que alinham verticalmente em tabelas e faceplates.

## Limites de escala

O armazenamento em memória é adequado para datasets de até algumas centenas de milhares de linhas por instância. Para escalar, `DatasetStore` pode ser reimplementado sobre um banco de séries temporais (TimescaleDB, InfluxDB) sem alterar os serviços, que recebem e devolvem DataFrames.

## Extensões previstas

- **Ingestão Modbus/OPC UA**: um coletor (`pymodbus`, `asyncua`) gravando no mesmo esquema interno permitiria monitoramento quase em tempo real.
- **Deep Learning**: autoencoder como mais um detector de anomalia em `ml_models.py`, e LSTM para RUL, com a mesma divisão temporal e avaliação por evento.
- **MLOps**: registrar execuções no MLflow em vez de `store._runs`.
