# Resultados

> **Todos os resultados abaixo foram obtidos com dados SINTÉTICOS** (modo demonstração, semente 42). Não representam medições de equipamentos reais nem o desempenho esperado em campo.

Os números foram gerados rodando o código final do repositório sem nenhum ajuste manual (Python 3.13.17, pandas 3.0.5, scikit-learn 1.9.1, xgboost 3.4.1, statsmodels 0.15.0). Para reproduzir, basta treinar os mesmos modelos pela interface ou pela API. O código é determinístico (sementes fixas), mas versões diferentes das bibliotecas podem mudar levemente os números.

## Arquivos desta pasta

| Arquivo | Conteúdo |
|---|---|
| `metricas_demo.json` | Todas as métricas abaixo, em formato bruto, incluindo matrizes de confusão e atributos mais importantes |
| `testes_pytest.txt` | Saída dos 35 testes automatizados do backend (todos passando) |
| `relatorio_exemplo_demo.html` | Relatório técnico gerado pela própria plataforma (abre no navegador, sem internet; ~6 MB) |
| `capturas/` | Capturas de tela da interface feitas durante o desenvolvimento |

## Dataset de demonstração

- 4 equipamentos simulados, 90 dias, amostragem de 15 min, **34.560 linhas**
- 12 falhas: 9 com sinal precursor e 3 súbitas (sem precursor)
- 5 lacunas de comunicação e 1 manutenção preventiva

## 1. Previsão de falha (horizonte de 24 h)

Divisão temporal: treino nos primeiros 70 % do período e teste nos 30 % finais.

### Só o motor MTR-01 (3 falhas no treino, 2 no teste)

| Modelo | Precisão | Recall | F1 | PR-AUC | ROC-AUC | F1 treino | F1 CV (média ± desvio) | Falhas antecipadas | Antecedência média | Alarmes falsos / 30 d |
|---|---|---|---|---|---|---|---|---|---|---|
| Linha de base | 0,045 | 0,038 | 0,041 | 0,052 | 0,496 | 0,039 | 0,027 ± 0,010 | 2/2 | 9,6 h | 85,6 |
| Random Forest | 0,992 | 1,000 | 0,996 | 1,000 | 1,000 | 0,996 | 0,931 ± 0,063 | 2/2 | 16,5 h | 1,1 |
| XGBoost | 0,992 | 0,985 | 0,989 | 1,000 | 1,000 | 1,000 | 0,923 ± 0,066 | 2/2 | 16,3 h | 1,1 |

Prevalência de positivos no teste: 5,3 %. Aviso emitido: *"Apenas 2 falha(s) no teste: as métricas por evento têm alta incerteza."*
Atributos mais importantes (RF): `vibracao__media_6h`, `vibracao__min_24h`, `vibracao__media_1h`.

**Leitura:** o desempenho quase perfeito vem da degradação de vibração injetada de forma limpa no gerador sintético; não é um resultado generalizável.

### Os 4 equipamentos (8 falhas no treino, 5 no teste)

| Modelo | Precisão | Recall | F1 | PR-AUC | ROC-AUC | F1 treino | F1 CV (média ± desvio) | Falhas antecipadas | Antecedência média | Alarmes falsos / 30 d |
|---|---|---|---|---|---|---|---|---|---|---|
| Linha de base | 0,060 | 0,040 | 0,048 | 0,042 | 0,507 | 0,036 | 0,021 ± 0,013 | 5/5 | 12,7 h | 57,8 |
| Random Forest | 0,994 | 0,388 | 0,558 | 0,612 | 0,826 | 0,995 | 0,292 ± 0,413 | 3/5 | 18,8 h | 0,3 |
| XGBoost | 0,887 | 0,502 | 0,641 | 0,555 | 0,763 | 0,999 | 0,299 ± 0,406 | 4/5 | 14,4 h | 0,6 |
| Isolation Forest* | 0,085 | 0,162 | 0,111 | 0,085 | 0,673 | — | — | 1/5 | 22,5 h | 12,2 |

Prevalência de positivos no teste: 4,1 %. Aviso emitido para RF e XGBoost: *"F1 no treino muito maior que no teste: indício de sobreajuste (overfitting)."*
\* O Isolation Forest não usa os rótulos no treino (contaminação 0,02); a comparação com eles é só referência. Ele marcou 7,9 % das amostras do teste como anômalas.

**Matrizes de confusão (teste, 4 equipamentos)**

| Modelo | VN | FP | FN | VP |
|---|---|---|---|---|
| Linha de base | 9.510 | 266 | 403 | 17 |
| Random Forest | 9.775 | 1 | 257 | 163 |
| XGBoost | 9.749 | 27 | 209 | 211 |
| Isolation Forest | 9.042 | 734 | 352 | 68 |

**Leitura:** o XGBoost troca um pouco de precisão por mais recall e antecipa uma falha a mais que o Random Forest. Os dois sobreajustam (F1 de treino ≈ 1,0) e variam muito entre dobras, consequência de haver só 8 falhas no treino. A linha de base "antecipa" todas as falhas apenas porque dispara alarmes aleatórios o tempo todo.

## 2. Previsão temporal (holdout das últimas 168 h, horizonte de 48 h)

| Série | Modelo | MAE | RMSE | WAPE | Cobertura IC 95 % | Ganho de MAE vs. ingênuo |
|---|---|---|---|---|---|---|
| INV-01 potência (kW) | Ingênuo sazonal | 4,32 | 7,45 | 45,0 % | 89 % | referência |
| | **Holt-Winters** | **2,31** | 3,99 | 24,0 % | 99 % | **+46,6 %** |
| | ARIMA + Fourier | 2,80 | 4,20 | 29,1 % | 88 % | +35,2 % |
| MTR-01 temperatura (°C) | Ingênuo sazonal | 5,21 | 8,75 | 8,6 % | 94 % | referência |
| | Holt-Winters | 5,68 | 9,19 | 9,4 % | 94 % | −9,1 % (pior) |
| | **ARIMA + Fourier** | **4,73** | 8,86 | 7,8 % | 82 % | +9,1 % |

## 3. Sazonalidade (INV-01, potência)

Período detectado: **diário (24 h)**, autocorrelação 0,92. Força da sazonalidade: 0,93; força da tendência: 0,09.
Candidatos: 24 h = 0,92 · 168 h = 0,86 · 8 h = −0,45 · 12 h = −0,63.

## 4. Indicadores de manutenção

| Equipamento | Falhas | MTBF (h) | MTTR (h) | Disp. intrínseca | Disp. observada | Falhas / 30 dias |
|---|---|---|---|---|---|---|
| CMP-01 | 3 | 535,0 | 7,0 | 98,71 % | 99,03 % | 1,00 |
| INV-01 | 2 | 525,9 | 2,5 | 99,53 % | 99,77 % | 0,67 |
| INV-02 | 3 | 346,4 | 9,0 | 97,47 % | 98,75 % | 1,00 |
| MTR-01 | 4 | 527,3 | 10,8 | 98,00 % | 97,64 % | 1,33 |
| **Frota** | **12** | **483,8** | **8,0** | **98,37 %** | **98,80 %** | — |

O INV-02 tem o menor MTBF, coerente com a degradação de ventilação simulada nele.

## 5. Alertas

Com os limites de exemplo do modo demonstração e os modelos acima treinados:

| Origem | Quantidade |
|---|---|
| Limite configurado | 28 |
| Anomalia estatística | 95 |
| Previsão de modelo | 358 |
| **Total** | **481** |

Os alertas de modelo somam as execuções treinadas acima, incluindo a linha de base aleatória (que dispara muito) e execuções que se sobrepõem no tempo. Os do Isolation Forest entram como anomalia estatística. Esse número **não** é a taxa de alarmes de um único modelo.

## 6. Testes automatizados

35 testes (pytest), todos passando: 11 de API (fluxo de importação, painel, alertas, ML, relatórios) e 24 de serviços (importação, MTBF/MTTR com valores conhecidos, ausência de vazamento temporal, modelo melhor que a linha de base, alertas). Lista completa em `testes_pytest.txt`.

## Próximas validações

- Desempenho com um dataset público (AI4I 2020, NASA C-MAPSS ou Solar Power Generation).
- Intervalos de confiança das métricas (por exemplo, por bootstrap), importantes com tão poucas falhas no teste.
- Tempo de treino e de resposta da API em datasets maiores.

## Sobre as capturas de tela

As imagens de `capturas/` foram feitas num navegador automatizado durante o desenvolvimento, todas com o dataset sintético. A `10_alertas_versao_anterior.png` é anterior aos ajustes finais de formatação (datas em inglês nos gráficos e números com ponto decimal); a funcionalidade é a mesma. As demais refletem a versão final.
