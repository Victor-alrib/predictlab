import { PageHeader, Panel } from "../components/ui";

const ROADMAP = [
  { item: "SQL", onde: "Esquema interno tabular (timestamp, equipamento, estado, variáveis); próximo passo: trocar o armazenamento em memória por SQLite/TimescaleDB." },
  { item: "Validação estatística de modelos", onde: "Divisão temporal, validação cruzada temporal, matriz de confusão, PR-AUC, comparação com linha de base, alerta de sobreajuste." },
  { item: "Deep Learning (PyTorch)", onde: "Ainda não implementado. Encaixe natural: LSTM para RUL e autoencoder como detector de anomalia, lado a lado com o Isolation Forest." },
  { item: "Séries temporais", onde: "Médias móveis, Mann-Kendall, ACF, decomposição STL, Holt-Winters e ARIMA com termos de Fourier." },
  { item: "Git e versionamento", onde: "Repositório organizado com README no formato problema → dado → abordagem → resultado → aprendizado." },
  { item: "Protocolos e indicadores O&M", onde: "MTBF, MTTR e disponibilidade a partir de log de estados; o mapeamento de colunas simula a saída de um historian/SCADA." },
  { item: "Noções de MLOps", onde: "Modelos servidos por API FastAPI; histórico de execuções com parâmetros, semente e métricas." },
];

export default function About() {
  return (
    <div className="space-y-4 max-w-[1000px]">
      <PageHeader title="Metodologia">
        Como cada número da plataforma é calculado, o que ele significa e onde estão os limites. As mesmas definições aparecem
        na seção de metodologia dos relatórios e em <code>docs/METODOLOGIA.md</code>.
      </PageHeader>

      <Panel title="Dados simulados e dados reais">
        <div className="space-y-2 text-[13.5px] max-w-[80ch]">
          <p>Todo dataset carrega uma origem declarada: medição real, dataset público ou simulação. A origem é obrigatória na importação e aparece no cabeçalho, nos resultados de modelos e nos relatórios.</p>
          <p>O ambiente de demonstração é inteiramente sintético. Quatro equipamentos simulados recebem falhas injetadas: algumas precedidas por degradação gradual (temperatura ou vibração subindo), outras súbitas, sem sinal precursor. As súbitas existem de propósito, para mostrar o que nenhum modelo baseado nessas variáveis consegue antecipar.</p>
          <p>Como os padrões foram injetados de forma limpa, métricas obtidas na demonstração são otimistas e não devem ser citadas como desempenho esperado em campo.</p>
        </div>
      </Panel>

      <Panel title="Indicadores de manutenção">
        <dl className="grid gap-x-6 gap-y-2 md:grid-cols-[180px_1fr] text-[13.5px]">
          <dt className="font-semibold">Tempo de cada amostra</dt><dd>Intervalo até a próxima leitura, limitado a 3× o intervalo mediano. Lacunas maiores contam como "sem dados", não como operação.</dd>
          <dt className="font-semibold">Falha</dt><dd>Sequência contínua de estados "falha", incluindo a manutenção corretiva imediatamente posterior. Manutenção isolada é preventiva.</dd>
          <dt className="font-semibold">MTBF</dt><dd>Tempo em operação ÷ número de falhas.</dd>
          <dt className="font-semibold">MTTR</dt><dd>Média das durações de falhas completas. Falhas cortadas pelo início ou fim do dataset ficam de fora.</dd>
          <dt className="font-semibold">Disponibilidade</dt><dd>Intrínseca: MTBF ÷ (MTBF + MTTR). Observada: 1 − (falha + reparo + preventiva) ÷ tempo com estado conhecido.</dd>
          <dt className="font-semibold">Dados suficientes</dt><dd>Por padrão, ao menos 2 falhas e 7 dias observados (ajustável). Abaixo disso o valor não é exibido.</dd>
        </dl>
      </Panel>

      <Panel title="Alertas: três origens">
        <ul className="space-y-2 text-[13.5px] max-w-[85ch]">
          <li><b>Limite configurado.</b> Episódios contínuos fora da faixa definida pelo usuário, com duração mínima opcional. Determinístico e auditável.</li>
          <li><b>Anomalia estatística.</b> z-score robusto: (x − mediana) ÷ (1,4826 × MAD) sobre janela móvel passada de 7 dias, só com amostras em operação. Para variáveis com ciclo diário, a referência é a mesma hora nos dias anteriores. Inclui também o Isolation Forest. Indica comportamento incomum, não falha.</li>
          <li><b>Previsão de modelo.</b> Probabilidade de falha acima do limiar no período de teste de um classificador, ou cruzamento de limite projetado por uma previsão temporal.</li>
        </ul>
      </Panel>

      <Panel title="Modelos de falha">
        <div className="space-y-2 text-[13.5px] max-w-[85ch]">
          <p><b>Rótulo:</b> 1 se uma falha começa nas próximas H horas. Amostras já em falha ou manutenção são excluídas, pois o objetivo é antecipar e não reconhecer a falha em curso.</p>
          <p><b>Atributos:</b> por variável, valor atual, média e desvio em 1 h, 6 h e 24 h, mínimo e máximo em 24 h, tendência curta (média 6 h − média 24 h) e desvio em relação à linha de base robusta de 7 dias. Todas as janelas olham só para o passado; um teste automatizado garante que alterar dados futuros não muda atributos passados.</p>
          <p><b>Avaliação:</b> divisão temporal sem embaralhamento, validação cruzada temporal no treino e linha de base aleatória estratificada. Além de precisão, recall, F1 e PR-AUC por amostra, a avaliação por evento conta falhas antecipadas, antecedência e alarmes falsos por 30 dias.</p>
          <p><b>Previsão temporal:</b> série horária com holdout final; MAE, RMSE, WAPE e cobertura do intervalo de 95%, sempre comparados ao modelo ingênuo sazonal.</p>
        </div>
      </Panel>

      <Panel title="Ligação com o roteiro de estudos" bodyClass="p-0">
        <table className="tbl text-[13px]">
          <thead><tr><th className="w-56">Item do roteiro</th><th>Onde aparece no PredictLab</th></tr></thead>
          <tbody>{ROADMAP.map((r) => <tr key={r.item}><td className="font-medium">{r.item}</td><td>{r.onde}</td></tr>)}</tbody>
        </table>
      </Panel>

      <p className="text-[12px] text-ink-3">Plataforma educacional e experimental. Não substitui análise de engenharia de confiabilidade nem deve orientar decisões operacionais reais.</p>
    </div>
  );
}
