# CSVs de exemplo (sintéticos)

Todos os arquivos desta pasta são **dados simulados**, gerados por `gerar_exemplos.py` a partir do mesmo gerador do modo demonstração (semente 7, 45 dias). Ao importá-los, declare a origem como **Simulação**.

| Arquivo | O que exercita |
|---|---|
| `sintetico_motor_colunas_ingles.csv` | Nomes de colunas em inglês (`datetime`, `asset_id`, `temperature_c`…) e estados `RUNNING` / `FAULT` / `MAINTENANCE` |
| `sintetico_inversores_padrao_br.csv` | Padrão brasileiro: `;` como separador, vírgula decimal, data `dd/mm/aaaa`, dois inversores no mesmo arquivo e uma variável personalizada (irradiância) |
| `sintetico_compressor_sem_estado.csv` | Sem coluna de estado e sem coluna de equipamento: indicadores de manutenção ficam indisponíveis e só o Isolation Forest pode ser treinado |

Para regenerar: `python examples/gerar_exemplos.py` (a partir da raiz do repositório).

## Datasets públicos sugeridos

Para validar a plataforma com dados reais, bons candidatos são:

- **AI4I 2020 Predictive Maintenance Dataset** (UCI) — temperaturas, rotação, torque, desgaste e coluna `Machine failure`. Não tem timestamp: crie um a partir do índice (amostras sequenciais) e declare isso na descrição.
- **NASA C-MAPSS (Turbofan Engine Degradation)** — ciclos em vez de tempo; útil para a futura regressão de RUL.
- **Solar Power Generation Data** (Kaggle) — geração e sensores de usinas FV a cada 15 min.
