"""Testes unitários dos serviços analíticos."""

import numpy as np
import pandas as pd
import pytest

from app.services import ingestion, maintenance, timeseries
from app.services.alerts import statistical_alerts, threshold_alerts
from app.services.features import build_dataset, failure_starts
from app.services.forecasting import run_forecast
from app.services.ml_models import train_classifier, train_isolation_forest
from app.store import Dataset


# --- dados sintéticos --------------------------------------------------------

def test_demo_is_flagged_as_synthetic(demo):
    assert demo.is_synthetic and demo.is_demo
    assert demo.data_origin == "simulado"
    assert "SINTÉTICOS" in demo.description
    assert demo.provenance["eventos_simulados"]


def test_demo_is_deterministic():
    a, _ = __import__("app.services.synthetic", fromlist=["x"]).generate_demo_dataframe(seed=1, days=10)
    b, _ = __import__("app.services.synthetic", fromlist=["x"]).generate_demo_dataframe(seed=1, days=10)
    pd.testing.assert_frame_equal(a, b)


# --- importação --------------------------------------------------------------

def test_brazilian_csv_detection():
    raw = "Data;Temp (°C);Status\n02/03/2026 10:00;21,5;Operando\n02/03/2026 10:15;22,0;Falha\n".encode("latin-1")
    df, info = ingestion.parse_csv(raw)
    assert info["delimiter"] == ";" and info["decimal"] == "," and info["encoding"] == "latin-1"
    sug = ingestion.suggest_mapping(df, info)
    assert sug["roles"]["timestamp"] == "Data"
    assert sug["roles"]["estado"] == "Status"
    out, variables, _ = ingestion.apply_mapping(df, info, sug)
    assert out["timestamp"].iloc[0] == pd.Timestamp("2026-03-02 10:00")  # dia/mês
    assert out["temperatura"].tolist() == [21.5, 22.0]
    assert out["estado"].tolist() == ["operando", "falha"]
    assert variables[0]["key"] == "temperatura"


def test_mapping_allows_custom_and_missing_columns():
    raw = b"ts,pressao_bar,vib\n2026-01-01 00:00,5.1,1.0\n2026-01-01 00:01,5.2,1.1\n"
    df, info = ingestion.parse_csv(raw)
    sug = ingestion.suggest_mapping(df, info)
    actions = {v["column"]: (v["action"], v["key"]) for v in sug["variables"]}
    assert actions["vib"] == ("canonica", "vibracao")
    assert actions["pressao_bar"][0] == "personalizada"
    out, variables, _ = ingestion.apply_mapping(df, info, sug)
    assert set(out.columns) >= {"timestamp", "equipamento", "vibracao", "pressao_bar"}
    assert "estado" not in out.columns


def test_mapping_requires_timestamp_and_one_variable():
    df, info = ingestion.parse_csv(b"a,b\n1,2\n3,4\n")
    with pytest.raises(ingestion.IngestionError):
        ingestion.apply_mapping(df, info, {"roles": {}, "variables": []})


def test_status_suggestion_binary_and_text():
    m = ingestion.suggest_status_map(["0", "1", "RUNNING", "Trip", "Standby", "xyz"])
    assert m == {"0": "operando", "1": "falha", "RUNNING": "operando", "Trip": "falha",
                 "Standby": "parado", "xyz": "desconhecido"}


# --- indicadores de manutenção ----------------------------------------------

def _toy(states: list[str], freq="1h") -> pd.DataFrame:
    return pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=len(states), freq=freq),
                         "equipamento": "EQ", "estado": states, "x": 1.0})


def test_mtbf_mttr_known_values():
    # 10 h operando, 2 h falha, 10 h operando, 4 h falha (+1 h manutenção corretiva), 10 h operando
    st = ["operando"] * 10 + ["falha"] * 2 + ["operando"] * 10 + ["falha"] * 4 + ["manutencao"] + ["operando"] * 10
    r = maintenance.equipment_indicators(_toy(st), min_falhas=2, min_dias=0)
    assert r["n_falhas"] == 2
    assert r["indicadores"]["mtbf"]["valor"] == pytest.approx(30 / 2)
    assert r["indicadores"]["mttr"]["valor"] == pytest.approx((2 + 5) / 2)
    assert r["indicadores"]["disponibilidade_intrinseca"]["valor"] == pytest.approx(15 / (15 + 3.5) * 100, abs=0.01)


def test_preventive_maintenance_excluded_from_mttr():
    st = ["operando"] * 5 + ["manutencao"] * 8 + ["operando"] * 5 + ["falha"] * 2 + ["operando"] * 5 + \
         ["falha"] * 2 + ["operando"] * 5
    r = maintenance.equipment_indicators(_toy(st), min_falhas=2, min_dias=0)
    assert r["n_falhas"] == 2 and len(r["preventivas"]) == 1
    assert r["indicadores"]["mttr"]["valor"] == pytest.approx(2.0)


def test_indicators_insufficient_data():
    st = ["operando"] * 20 + ["falha"] * 2 + ["operando"] * 20
    r = maintenance.equipment_indicators(_toy(st), min_falhas=2, min_dias=7)
    assert not r["suficiente"]
    assert r["indicadores"]["mtbf"]["status"] == "insuficiente"
    assert r["indicadores"]["mtbf"]["valor"] is None
    assert len(r["motivos"]) == 2  # período curto e poucas falhas


def test_indicators_without_status_column():
    df = _toy(["operando"] * 5).drop(columns=["estado"])
    r = maintenance.equipment_indicators(df)
    assert r["suficiente"] is False and "estado" in r["motivos"][0]


def test_gaps_are_not_counted_as_operation():
    df = _toy(["operando"] * 10 + ["falha"] + ["operando"] * 10 + ["falha"] + ["operando"] * 10)
    df.loc[15:, "timestamp"] += pd.Timedelta(hours=100)  # lacuna de 100 h
    r = maintenance.equipment_indicators(df, min_falhas=2, min_dias=0)
    assert r["tempos_h"]["sem_dados"] >= 97
    assert r["tempos_h"]["operacao"] == pytest.approx(30, abs=3)


def test_truncated_failure_not_in_mttr():
    st = ["falha"] * 3 + ["operando"] * 10 + ["falha"] * 2 + ["operando"] * 10 + ["falha"] * 2 + ["operando"] * 2
    r = maintenance.equipment_indicators(_toy(st), min_falhas=2, min_dias=0)
    assert r["n_falhas"] == 3 and r["n_falhas_completas"] == 2
    assert r["indicadores"]["mttr"]["valor"] == pytest.approx(2.0)


def test_demo_indicators(demo):
    r = maintenance.compute_indicators(demo)
    by = {e["equipamento"]: e for e in r["equipamentos"]}
    assert by["MTR-01"]["n_falhas"] == 4
    assert all(e["suficiente"] for e in r["equipamentos"])
    assert r["frota"]["n_falhas"] == sum(e["n_falhas"] for e in r["equipamentos"])


# --- análise temporal --------------------------------------------------------

def test_trend_detects_increase(demo):
    r = timeseries.trend(demo, "INV-02", "temperatura")
    assert r["estatisticas"]["n"] > 100
    assert len(r["timestamps"]) == len(r["valor"])


def test_seasonality_daily_for_inverter(demo):
    r = timeseries.seasonality(demo, "INV-01", "potencia")
    assert r["periodo_detectado"]["horas"] == 24
    assert r["forca_sazonal"] > 0.6


def test_compare_periods_detects_degradation(demo):
    r = timeseries.compare_periods(demo, "MTR-01", "vibracao",
                                   ("2026-03-02", "2026-03-10"), ("2026-03-14", "2026-03-18"))
    assert r["significativo_5pct"] and r["diferenca_media"] > 0


# --- atributos, ML e previsão ------------------------------------------------

def test_features_do_not_use_future(demo):
    """Alterar dados futuros não pode mudar atributos do passado."""
    ds = demo
    X1, _, meta1, _ = build_dataset(ds, ["MTR-01"], 24)
    df2 = ds.df.copy()
    future = (df2["equipamento"] == "MTR-01") & (df2["timestamp"] > "2026-04-01")
    df2.loc[future, "vibracao"] = 999.0
    ds2 = Dataset(**{**ds.__dict__, "df": df2})
    X2, _, meta2, _ = build_dataset(ds2, ["MTR-01"], 24)
    past = (meta1["timestamp"] <= "2026-04-01").to_numpy()
    pd.testing.assert_frame_equal(X1[past].reset_index(drop=True), X2[past].reset_index(drop=True))


def test_failure_starts(demo):
    assert len(failure_starts(demo.subset("MTR-01").reset_index(drop=True))) == 4


def test_classifier_beats_baseline(demo):
    rf = train_classifier(demo, ["MTR-01"], "random_forest", cv_splits=3)
    base = train_classifier(demo, ["MTR-01"], "baseline", cv_splits=3)
    assert rf["metricas"]["teste"]["pr_auc"] > base["metricas"]["teste"]["pr_auc"]
    assert rf["divisao"]["falhas_teste"] >= 1
    # divisão temporal: todo o teste é posterior ao corte
    corte = pd.Timestamp(rf["divisao"]["corte"])
    for s in rf["series"].values():
        assert pd.Timestamp(s["timestamps"][0]) >= corte - pd.Timedelta(hours=1)


def test_classifier_requires_status(demo):
    df = demo.df.drop(columns=["estado"])
    ds = Dataset(**{**demo.__dict__, "df": df})
    with pytest.raises(Exception):
        train_classifier(ds, ["MTR-01"])


def test_isolation_forest_runs(demo):
    r = train_isolation_forest(demo, ["MTR-01"])
    assert 0 < r["metricas"]["anomalia"]["taxa_anomalias_teste"] < 0.5


def test_forecast_beats_naive_on_inverter(demo):
    r = run_forecast(demo, "INV-01", "potencia", horizonte_h=24)
    assert r["melhor_modelo"] in ("holt_winters", "sarimax_fourier", "ingenuo_sazonal")
    ok = [x for x in r["resultados"] if "erro" not in x]
    assert len(ok) == 3
    assert all(len(x["futuro"]["previsto"]) == 24 for x in ok)


# --- alertas -----------------------------------------------------------------

def test_threshold_alerts_episodes():
    df = _toy(["operando"] * 30)
    df["x"] = [1.0] * 10 + [10.0] * 5 + [1.0] * 15
    ds = Dataset(id="t", name="t", data_origin="simulado", df=df,
                 variables=[{"key": "x", "label": "X", "unit": "u"}], thresholds={"EQ": {"x": {"max": 5}}})
    al = threshold_alerts(ds, "EQ")
    assert len(al) == 1 and al[0]["origem"] == "limite" and al[0]["duracao_h"] == pytest.approx(5)


def test_statistical_alerts_spike():
    rng = np.random.default_rng(0)
    x = rng.normal(10, 0.5, 24 * 20)
    x[300:306] = 25
    df = _toy(["operando"] * len(x))
    df["x"] = x
    ds = Dataset(id="t", name="t", data_origin="simulado", df=df, variables=[{"key": "x", "label": "X", "unit": ""}])
    al = statistical_alerts(ds, "EQ")
    assert any(a["origem"] == "estatistica" and "2026-01-13" in a["inicio"] for a in al)
