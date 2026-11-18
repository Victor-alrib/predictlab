# Metodologia

Este documento descreve como cada número do PredictLab é calculado. As mesmas definições aparecem na tela **Metodologia** e na seção de metodologia dos relatórios.

## 1. Esquema interno e pré-processamento

Todo dataset é convertido para o esquema:

| Coluna | Tipo | Observação |
|---|---|---|
| `timestamp` | datetime (sem fuso) | Fusos são convertidos e descartados |
| `equipamento` | texto | Valor padrão quando o arquivo não tem a coluna |
| `estado` | categoria | `operando`, `parado`, `falha`, `manutencao`, `desconhecido` |
| variáveis | float | Chaves canônicas (`temperatura`, `corrente`, `tensao`, `potencia`, `vibracao`) ou personalizadas |

Regras de conversão:

- Linhas com timestamp inválido são descartadas e contabilizadas.
- Valores não numéricos viram vazio e são contabilizados por coluna.
- Registros duplicados (mesmo equipamento e timestamp) são agregados pela média; o estado mantém o último valor.
- Nenhuma interpolação é aplicada aos dados armazenados. Ela ocorre apenas dentro da decomposição sazonal (até 6 h) e da previsão temporal (até 12 h), e é declarada no resultado.

**Datas ambíguas.** Em formatos `xx/xx/aaaa`, se algum segundo componente for maior que 12 e nenhum primeiro for, o arquivo é lido como mês/dia; caso contrário, como dia/mês (padrão brasileiro).

## 2. Qualidade dos dados

Por equipamento: intervalo de amostragem mediano, número de lacunas (intervalos maiores que 3× a mediana), maior lacuna, linhas sem nenhuma leitura e percentual de faltantes por variável.

## 3. Indicadores de manutenção

**Tempo de cada amostra.** Cada leitura representa o intervalo até a leitura seguinte, limitado a 3× o intervalo mediano. O excedente conta como *sem dados*, nunca como operação. Isso evita que uma perda de comunicação de dois dias infle o MTBF.

**Episódio de falha (corretiva).** Sequência contínua de amostras `falha`, incluindo a `manutencao` imediatamente posterior (reparo). Episódios de `manutencao` que não começam com falha são **preventivos** e não entram no MTTR.

**Falha truncada.** Episódio que começa na primeira ou termina na última amostra do equipamento. Sua duração real é desconhecida; ele conta para o número de falhas, mas não para o MTTR.

| Indicador | Definição |
|---|---|
| MTBF | tempo em `operando` ÷ número de falhas |
| MTTR | média da duração (falha + reparo) das falhas completas |
| Disponibilidade intrínseca | MTBF ÷ (MTBF + MTTR) |
| Disponibilidade observada | 1 − (falha + reparo + preventiva) ÷ tempo com estado conhecido |
| Frequência | falhas ÷ dias observados × 30 |

O tempo em `parado` (standby) não entra no MTBF: equipamento parado por falta de demanda não está acumulando desgaste da mesma forma que em operação.

**Suficiência.** Por padrão, MTBF e MTTR exigem pelo menos **2 falhas** e **7 dias** com estado conhecido (ambos configuráveis na interface e na API). Abaixo disso, o indicador retorna `status = "insuficiente"` e o motivo, e a interface exibe "dados insuficientes" em vez de um número. Também é exibida a dispersão dos tempos entre falhas, para deixar visível a incerteza quando há poucos intervalos.

## 4. Análise temporal

- **Reamostragem.** Para cada equipamento, a frequência é arredondada a partir do intervalo mediano de amostragem.
- **Médias móveis.** Janelas baseadas em tempo (`6h`, `24h`, `7D`), com mínimo de metade da janela em pontos válidos.
- **Tendência.** Regressão linear (inclinação em unidades/dia e R²) e τ de Kendall contra o tempo (forma simplificada do teste de Mann-Kendall). A direção é declarada "crescente/decrescente" somente se p < 0,01 e |τ| > 0,1.
- **Sazonalidade.** Série horária; autocorrelação nos períodos candidatos de 8, 12, 24 e 168 h. O período com ACF > 0,3 (e acima do limiar 1,96/√n) é usado numa decomposição STL robusta. Força sazonal e de tendência seguem Wang, Smith & Hyndman (2006): `max(0, 1 − Var(R) / Var(S + R))`.
- **Comparação entre períodos.** Estatísticas descritivas, teste de Mann-Whitney (não paramétrico), d de Cohen como tamanho de efeito, perfis horários e histogramas sobrepostos. A interface lembra que, com muitas amostras, até diferenças irrelevantes ficam significativas.

## 5. Alertas

As três origens são calculadas e exibidas separadamente.

### 5.1 Limite configurado

Episódios contínuos acima de `max` ou abaixo de `min` definidos pelo usuário (por equipamento ou para todos). Violações separadas por menos de 1 h são agrupadas no mesmo episódio. Duração mínima opcional. A sugestão automática (percentis 0,5 % e 99,5 % da operação ± 10 % da faixa) é rotulada como ponto de partida estatístico, não como limite de engenharia.

### 5.2 Anomalia estatística

z-score robusto:

```
z = (x − mediana) / (1,4826 · MAD)
```

- Mediana e MAD vêm de uma janela móvel de **7 dias estritamente passada** (`shift(1)`).
- Apenas amostras em `operando` participam (quando há coluna de estado).
- Se a variável tem ciclo diário (autocorrelação em 24 h > 0,5), a referência é calculada **por hora do dia** — 12 h de hoje é comparado com 12 h dos dias anteriores, evitando alarmar todo pôr do sol num inversor fotovoltaico.
- Episódio = ao menos 3 amostras com |z| > k (padrão k = 4). Severidade alta se |z| > 2k.

O **Isolation Forest** também é uma técnica estatística não supervisionada; seus alertas são classificados nesta origem.

### 5.3 Previsão de modelo

- Classificador de falha: episódios em que a probabilidade no **período de teste** ultrapassa o limiar escolhido.
- Previsão temporal: cruzamento de um limite configurado pela trajetória prevista pelo melhor modelo.

Só a execução mais recente de cada combinação (modelo, equipamentos, variável) gera alertas.

## 6. Modelos de falha

### Rótulo

```
y(t) = 1  se uma falha começa em (t, t + H]
```

com H = horizonte (padrão 24 h). Amostras em `falha` ou `manutencao` são excluídas: o objetivo é antecipar, não reconhecer a falha em andamento.

### Atributos (por variável)

Valor atual; média e desvio em 1 h, 6 h e 24 h; mínimo e máximo em 24 h; tendência curta (média 6 h − média 24 h); desvio da média de 6 h em relação à linha de base robusta de 7 dias (mediana e MAD). Todas as janelas são para trás — testado em `test_features_do_not_use_future`.

### Treino e avaliação

1. **Divisão temporal**: corte no instante `início + (1 − fração_teste) × duração`. Treino antes, teste depois.
2. **Desbalanceamento**: `class_weight="balanced_subsample"` (Random Forest) e `scale_pos_weight` (XGBoost).
3. **Validação cruzada temporal** (`TimeSeriesSplit`, 4 dobras) dentro do treino; dobras sem falhas são reportadas como tal.
4. **Métricas por amostra no teste**: precisão, recall, F1, ROC-AUC, **PR-AUC** (mais informativa com classes raras; a prevalência é exibida como referência do acaso) e matriz de confusão.
5. **Métricas por evento**: falhas antecipadas (ao menos uma amostra acima do limiar dentro da janela H antes da falha), antecedência máxima de cada detecção, episódios de alarme falso e alarmes falsos por 30 dias.
6. **Avisos automáticos**: menos de 3 falhas no treino ou no teste; F1 de treino maior que o de teste em mais de 0,25 (sobreajuste); dataset simulado.

### Isolation Forest

Treinado somente com amostras em operação do período de treino (quando há estado). O escore é normalizado para 0–1 apenas para exibição. A comparação com rótulos de falha é apresentada como **referência**, já que o modelo não busca falhas, e sim comportamento raro.

## 7. Previsão temporal

- Série horária (média), últimos 30 dias + holdout.
- Holdout final (padrão 168 h) para medir o erro; depois, o modelo é reajustado com toda a série para projetar o horizonte.
- Modelos: **ingênuo sazonal** (linha de base), **Holt-Winters** (tendência amortecida, sazonalidade aditiva) e **ARIMA(2,0,1)** com 3 pares de termos de Fourier como regressores.
- Métricas: MAE, RMSE, WAPE, viés, **cobertura do intervalo de 95 %** e ganho de MAE sobre o ingênuo. Um modelo com ganho negativo não agrega valor sobre a repetição do ciclo anterior.

## 8. Dados simulados

O gerador (`backend/app/services/synthetic.py`) é determinístico (semente fixa) e cria:

| Equipamento | Comportamento | Eventos |
|---|---|---|
| `INV-01` | Inversor FV saudável | 2 falhas súbitas, sem precursor; lacunas de comunicação |
| `INV-02` | Inversor FV com degradação da ventilação | 3 trips por sobretemperatura com ~4 dias de precursor |
| `MTR-01` | Motor + bomba, 24/7 | 4 falhas de rolamento com ~6 dias de vibração crescente; 1 preventiva |
| `CMP-01` | Compressor carga/alívio | 2 falhas com precursor térmico; 1 falha súbita |

Os padrões físicos são plausíveis e didáticos, mas não reproduzem nenhum equipamento real. Métricas obtidas nesses dados são otimistas por construção.

## 9. Limitações conhecidas

- O rótulo de falha depende inteiramente da qualidade da coluna de estado.
- Com poucas falhas, todas as métricas têm intervalo de confiança largo; não são exibidos intervalos formais (bootstrap seria uma evolução natural).
- O limiar do classificador é fixo por execução; não há otimização de limiar por custo de falha × custo de parada.
- O armazenamento é em memória/disco local, sem controle de concorrência entre usuários.
