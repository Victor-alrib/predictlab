"""Gerador de dados SINTÉTICOS para o modo demonstração.

Tudo que sai deste módulo é simulação. O dataset gerado é marcado com
``data_origin = "simulado"`` e a interface exibe uma faixa de aviso
permanente. Os padrões físicos foram escolhidos para serem plausíveis e
didáticos, não para reproduzir um equipamento real específico.

Equipamentos simulados (resolução de 15 min, 90 dias):

* ``INV-01`` — inversor fotovoltaico saudável, com duas falhas súbitas de
  comunicação/trip sem sinal precursor (para mostrar o limite dos modelos).
* ``INV-02`` — inversor fotovoltaico com degradação do sistema de ventilação:
  a temperatura sobe e a eficiência cai antes de trips por sobretemperatura.
  Relaciona-se ao Projeto 1 do roadmap (queda de performance em inversor).
* ``MTR-01`` — motor de indução acionando bomba, 24/7, com desgaste de
  rolamento: a vibração cresce de forma exponencial nos dias que antecedem
  cada falha. Inclui uma manutenção preventiva programada.
* ``CMP-01`` — compressor com ciclo carga/alívio, duas falhas com precursor
  térmico e uma falha súbita.

Os eventos injetados ficam registrados em ``provenance["eventos_simulados"]``
para que qualquer avaliação de modelo possa ser conferida contra o
"gabarito" da simulação.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import COL_EQUIPMENT, COL_STATUS, COL_TIMESTAMP, DEMO_DATASET_ID
from ..store import Dataset

FREQ = "15min"
STEPS_PER_HOUR = 4
SIM_START = "2026-03-02 00:00"  # data arbitrária, só para eixo de tempo
SIM_DAYS = 90


def _time_index(days: int) -> pd.DatetimeIndex:
    return pd.date_range(SIM_START, periods=days * 24 * STEPS_PER_HOUR, freq=FREQ)


def _precursor(n: int, start_idx: int, lead_steps: int, rng_shape: float = 3.0) -> np.ndarray:
    """Curva de degradação 0→1 que cresce exponencialmente até ``start_idx``."""
    curve = np.zeros(max(n, start_idx))
    a = max(0, start_idx - lead_steps)
    if start_idx <= a:
        return curve[:n]
    x = np.linspace(0, 1, start_idx - a)
    curve[a:start_idx] = (np.exp(rng_shape * x) - 1) / (np.exp(rng_shape) - 1)
    return curve[:n]  # falhas além da janela simulada só deixam o início do precursor


def _apply_failures(status: np.ndarray, failures: list[dict], n: int) -> None:
    for f in failures:
        a = f["idx"]
        b = min(n, a + f["repair_steps"])
        status[a:b] = "falha"
        m = f.get("maint_after_steps", 0)
        if m:
            status[b:min(n, b + m)] = "manutencao"


def _solar_inverter(idx: pd.DatetimeIndex, rng: np.random.Generator, name: str,
                    degraded: bool) -> tuple[pd.DataFrame, list[dict]]:
    n = len(idx)
    hour = np.asarray(idx.hour + idx.minute / 60.0, dtype=float)
    day = np.asarray((idx - idx[0]).days)
    n_days = day.max() + 1

    # irradiância relativa: senoide diurna x nebulosidade diária + ruído rápido
    sun = np.clip(np.sin(np.pi * (hour - 6.0) / 12.0), 0, None)
    clouds_day = rng.uniform(0.45, 1.0, n_days)[day]
    flicker = np.clip(1 + rng.normal(0, 0.06, n), 0.6, 1.2)
    irr = np.clip(sun * clouds_day * flicker, 0, 1.05)

    p_nom = 50.0  # kW
    eff = np.full(n, 0.97)
    temp_extra = np.zeros(n)

    failures: list[dict] = []
    events: list[dict] = []
    if degraded:
        # três trips por sobretemperatura, cada um precedido por ~4 dias de
        # degradação do ventilador (temperatura sobe, eficiência cai)
        for d_fail, h_fail, repair_h in [(31, 13, 5), (58, 12, 7), (80, 14, 9)]:
            fi = (d_fail * 24 + h_fail) * STEPS_PER_HOUR
            if fi >= n:  # falha fora da janela simulada
                continue
            pre = _precursor(n, fi, lead_steps=4 * 24 * STEPS_PER_HOUR, rng_shape=2.5)
            temp_extra += 22 * pre
            eff -= 0.07 * pre
            failures.append({"idx": fi, "repair_steps": repair_h * STEPS_PER_HOUR,
                             "maint_after_steps": 2 * STEPS_PER_HOUR})
            events.append({"equipamento": name, "tipo": "falha_com_precursor",
                           "descricao": "Trip por sobretemperatura após degradação da ventilação",
                           "inicio": idx[fi].isoformat(), "duracao_h": repair_h})
    else:
        # duas falhas súbitas (sem precursor) — difíceis de prever por design
        for d_fail, h_fail, repair_h in [(22, 10, 2), (67, 15, 3)]:
            fi = (d_fail * 24 + h_fail) * STEPS_PER_HOUR
            if fi >= n:  # falha fora da janela simulada
                continue
            failures.append({"idx": fi, "repair_steps": repair_h * STEPS_PER_HOUR})
            events.append({"equipamento": name, "tipo": "falha_subita",
                           "descricao": "Trip súbito (falha de comunicação/proteção), sem precursor",
                           "inicio": idx[fi].isoformat(), "duracao_h": repair_h})

    potencia = p_nom * irr * eff + rng.normal(0, 0.25, n)
    potencia = np.clip(potencia, 0, None)
    tensao = 380 + rng.normal(0, 2.5, n) + 3 * irr
    corrente = potencia * 1000 / (np.sqrt(3) * tensao * 0.98)
    amb = 18 + 9 * np.clip(np.sin(np.pi * (hour - 8.0) / 14.0), 0, None) + rng.normal(0, 0.6, n)
    temperatura = amb + 24 * irr + temp_extra * np.clip(irr * 1.4, 0.25, 1) + rng.normal(0, 0.8, n)

    status = np.where(irr > 0.02, "operando", "parado").astype(object)
    _apply_failures(status, failures, n)

    off = np.isin(status, ["falha", "manutencao"])
    potencia[off] = 0.0
    corrente[off] = 0.0
    # temperatura decai após trip (equipamento desligado)
    for f in failures:
        a, b = f["idx"], min(n, f["idx"] + f["repair_steps"])
        decay = np.exp(-np.arange(b - a) / 8.0)
        temperatura[a:b] = amb[a:b] + (temperatura[a] - amb[a]) * decay

    # perda de comunicação: lacunas sem dados (NaN em tudo, estado desconhecido)
    n_gaps = 3 if degraded else 2
    for _ in range(n_gaps):
        g = int(rng.integers(5, max(6, n_days - 5))) * 24 * STEPS_PER_HOUR + int(rng.integers(0, 90))
        if g + 12 >= n:
            continue
        length = int(rng.integers(3, 12))
        if status[g:g + length].tolist().count("falha") == 0:
            potencia[g:g + length] = np.nan
            corrente[g:g + length] = np.nan
            tensao[g:g + length] = np.nan
            temperatura[g:g + length] = np.nan
            status[g:g + length] = None
            events.append({"equipamento": name, "tipo": "perda_comunicacao",
                           "descricao": "Lacuna de dados simulando perda de comunicação",
                           "inicio": idx[g].isoformat(), "duracao_h": length / STEPS_PER_HOUR})

    df = pd.DataFrame({
        COL_TIMESTAMP: idx, COL_EQUIPMENT: name, COL_STATUS: status,
        "temperatura": temperatura, "corrente": corrente,
        "tensao": tensao, "potencia": potencia,
    })
    return df, events


def _motor_pump(idx: pd.DatetimeIndex, rng: np.random.Generator, name: str) -> tuple[pd.DataFrame, list[dict]]:
    n = len(idx)
    hour = np.asarray(idx.hour + idx.minute / 60.0, dtype=float)
    weekday = np.asarray(idx.dayofweek)

    # carga: maior em dias úteis e horário de produção
    load = 0.72 + 0.12 * (weekday < 5) + 0.08 * np.sin(2 * np.pi * (hour - 9) / 24) + rng.normal(0, 0.025, n)
    load = np.clip(load, 0.4, 1.0)

    wear = np.zeros(n)
    failures, events = [], []
    for d_fail, h_fail, repair_h in [(16, 3, 6), (39, 20, 10), (63, 9, 8), (85, 1, 7)]:
        fi = (d_fail * 24 + h_fail) * STEPS_PER_HOUR
        if fi >= n:  # falha fora da janela simulada
            continue
        wear += _precursor(n, fi, lead_steps=6 * 24 * STEPS_PER_HOUR, rng_shape=3.2)
        failures.append({"idx": fi, "repair_steps": repair_h * STEPS_PER_HOUR,
                         "maint_after_steps": 3 * STEPS_PER_HOUR})
        events.append({"equipamento": name, "tipo": "falha_com_precursor",
                       "descricao": "Falha de rolamento com aumento progressivo de vibração",
                       "inicio": idx[fi].isoformat(), "duracao_h": repair_h})

    tensao = 380 + rng.normal(0, 3.0, n) - 4 * load
    corrente = 22 + 26 * load + 3.5 * wear + rng.normal(0, 0.6, n)
    potencia = np.sqrt(3) * tensao * corrente * 0.86 / 1000
    vibracao = 1.8 + 0.4 * load + 6.5 * wear ** 1.3 + np.abs(rng.normal(0, 0.18, n))
    temperatura = 48 + 14 * load + 16 * wear + rng.normal(0, 0.9, n)

    status = np.full(n, "operando", dtype=object)
    _apply_failures(status, failures, n)
    # manutenção preventiva programada (não é falha — não entra no MTTR)
    pm = (50 * 24 + 7) * STEPS_PER_HOUR
    if pm < n:
        status[pm:pm + 8 * STEPS_PER_HOUR] = "manutencao"
        events.append({"equipamento": name, "tipo": "manutencao_preventiva",
                       "descricao": "Manutenção preventiva programada (8 h)",
                       "inicio": idx[pm].isoformat(), "duracao_h": 8})

    off = np.isin(status, ["falha", "manutencao"])
    corrente[off] = 0
    potencia[off] = 0
    vibracao[off] = np.abs(rng.normal(0.05, 0.02, off.sum()))
    temperatura[off] = 30 + rng.normal(0, 0.5, off.sum())

    df = pd.DataFrame({
        COL_TIMESTAMP: idx, COL_EQUIPMENT: name, COL_STATUS: status,
        "temperatura": temperatura, "corrente": corrente, "tensao": tensao,
        "potencia": potencia, "vibracao": vibracao,
    })
    return df, events


def _compressor(idx: pd.DatetimeIndex, rng: np.random.Generator, name: str) -> tuple[pd.DataFrame, list[dict]]:
    n = len(idx)
    # ciclo carga/alívio: ~45 min carregando, ~15 min em alívio, com jitter
    cycle = np.zeros(n, dtype=bool)
    i = 0
    while i < n:
        on = int(rng.integers(2, 5))
        off = int(rng.integers(1, 2))
        cycle[i:i + on] = True
        i += on + off

    heat = np.zeros(n)
    failures, events = [], []
    plan = [(27, 11, 5, True), (52, 4, 4, False), (74, 16, 6, True)]
    for d_fail, h_fail, repair_h, has_precursor in plan:
        fi = (d_fail * 24 + h_fail) * STEPS_PER_HOUR
        if fi >= n:  # falha fora da janela simulada
            continue
        if has_precursor:
            heat += _precursor(n, fi, lead_steps=3 * 24 * STEPS_PER_HOUR, rng_shape=2.8)
        failures.append({"idx": fi, "repair_steps": repair_h * STEPS_PER_HOUR,
                         "maint_after_steps": 2 * STEPS_PER_HOUR})
        events.append({"equipamento": name,
                       "tipo": "falha_com_precursor" if has_precursor else "falha_subita",
                       "descricao": ("Falha por superaquecimento (resfriador obstruído)" if has_precursor
                                     else "Falha súbita de válvula, sem precursor"),
                       "inicio": idx[fi].isoformat(), "duracao_h": repair_h})

    tensao = 440 + rng.normal(0, 3.5, n)
    corrente = np.where(cycle, 61, 18) + 6 * heat + rng.normal(0, 1.2, n)
    potencia = np.sqrt(3) * tensao * corrente * 0.84 / 1000
    vibracao = np.where(cycle, 3.1, 1.6) + 1.2 * heat + np.abs(rng.normal(0, 0.22, n))
    temperatura = 72 + np.where(cycle, 9, 0) + 24 * heat + rng.normal(0, 1.1, n)

    status = np.where(cycle, "operando", "parado").astype(object)
    _apply_failures(status, failures, n)
    off = np.isin(status, ["falha", "manutencao"])
    corrente[off] = 0
    potencia[off] = 0
    vibracao[off] = 0.05
    temperatura[off] = 35 + rng.normal(0, 0.6, off.sum())

    df = pd.DataFrame({
        COL_TIMESTAMP: idx, COL_EQUIPMENT: name, COL_STATUS: status,
        "temperatura": temperatura, "corrente": corrente, "tensao": tensao,
        "potencia": potencia, "vibracao": vibracao,
    })
    return df, events


DEMO_VARIABLES = [
    {"key": "temperatura", "label": "Temperatura", "unit": "°C", "canonical": True},
    {"key": "corrente", "label": "Corrente", "unit": "A", "canonical": True},
    {"key": "tensao", "label": "Tensão", "unit": "V", "canonical": True},
    {"key": "potencia", "label": "Potência", "unit": "kW", "canonical": True},
    {"key": "vibracao", "label": "Vibração", "unit": "mm/s", "canonical": True},
]

# Limites de alarme de exemplo para o modo demo (didáticos, não normativos).
DEMO_THRESHOLDS = {
    "INV-01": {"temperatura": {"max": 60, "severidade": "alta"}},
    "INV-02": {"temperatura": {"max": 60, "severidade": "alta"}},
    "MTR-01": {"vibracao": {"max": 4.5, "severidade": "alta"},
               "temperatura": {"max": 72, "severidade": "media"}},
    "CMP-01": {"temperatura": {"max": 100, "severidade": "alta"},
               "vibracao": {"max": 4.2, "severidade": "media"}},
}


def generate_demo_dataframe(seed: int = 42, days: int = SIM_DAYS) -> tuple[pd.DataFrame, list[dict]]:
    rng = np.random.default_rng(seed)
    idx = _time_index(days)
    parts, events = [], []
    for fn in (lambda: _solar_inverter(idx, rng, "INV-01", degraded=False),
               lambda: _solar_inverter(idx, rng, "INV-02", degraded=True),
               lambda: _motor_pump(idx, rng, "MTR-01"),
               lambda: _compressor(idx, rng, "CMP-01")):
        df, ev = fn()
        parts.append(df)
        events.extend(ev)
    df = pd.concat(parts, ignore_index=True)
    # eventos fora da janela simulada (quando days < SIM_DAYS) são descartados
    end = idx[-1]
    events = [e for e in events if pd.Timestamp(e["inicio"]) <= end]
    return df, events


def build_demo_dataset(seed: int = 42) -> Dataset:
    df, events = generate_demo_dataframe(seed)
    return Dataset(
        id=DEMO_DATASET_ID,
        name="Planta simulada (demonstração)",
        description=("Dados SINTÉTICOS gerados pelo PredictLab para demonstração. "
                     "Não representam medições de nenhum equipamento real."),
        data_origin="simulado",
        df=df,
        variables=[dict(v) for v in DEMO_VARIABLES],
        is_demo=True,
        thresholds={k: {vk: dict(vv) for vk, vv in v.items()} for k, v in DEMO_THRESHOLDS.items()},
        provenance={
            "gerador": "app/services/synthetic.py",
            "semente": seed,
            "resolucao": FREQ,
            "dias": SIM_DAYS,
            "eventos_simulados": events,
            "equipamentos": {
                "INV-01": "Inversor fotovoltaico 50 kW (simulado) — saudável, falhas súbitas",
                "INV-02": "Inversor fotovoltaico 50 kW (simulado) — degradação da ventilação",
                "MTR-01": "Motor de indução + bomba (simulado) — desgaste de rolamento",
                "CMP-01": "Compressor de ar (simulado) — ciclo carga/alívio",
            },
        },
    )
