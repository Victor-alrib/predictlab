"""Modelos de Machine Learning: Random Forest, XGBoost, Isolation Forest e linha de base.

Princípios de avaliação (ligados ao item 2 do roadmap — validação estatística):

* **Divisão temporal**, nunca aleatória: o modelo é treinado no passado e
  testado no futuro. Embaralhar amostras de série temporal vaza informação,
  porque amostras vizinhas são quase idênticas.
* **Validação cruzada temporal** (``TimeSeriesSplit``) no conjunto de treino,
  para estimar a variabilidade do desempenho.
* **Métricas por amostra** (precisão, recall, F1, ROC-AUC, PR-AUC) e
  **métricas por evento** (quantas falhas do teste foram antecipadas e com
  quanta antecedência; quantos alarmes falsos por 30 dias), que são as que
  importam na operação.
* Comparação obrigatória com uma **linha de base** ingênua.
"""

from __future__ import annotations

import time
import warnings

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                             precision_recall_curve, precision_score, recall_score,
                             roc_auc_score)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline

from ..config import COL_EQUIPMENT, COL_TIMESTAMP
from ..store import Dataset
from .features import build_dataset
from .quality import clean_float, series_to_list, ts_to_list

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except Exception:  # pragma: no cover - xgboost opcional
    HAS_XGB = False


MODEL_INFO = {
    "random_forest": {"nome": "Random Forest", "tipo": "classificacao",
                      "descricao": "Conjunto de árvores de decisão com bagging. Robusto e pouco sensível a hiperparâmetros."},
    "xgboost": {"nome": "XGBoost", "tipo": "classificacao",
                "descricao": "Gradient boosting de árvores. Costuma ter bom desempenho em dados tabulares."},
    "baseline": {"nome": "Linha de base (aleatória estratificada)", "tipo": "classificacao",
                 "descricao": "Prevê falha aleatoriamente na proporção observada no treino. Qualquer modelo útil deve superá-la."},
    "isolation_forest": {"nome": "Isolation Forest", "tipo": "anomalia",
                         "descricao": "Não supervisionado: isola pontos raros. Não usa os rótulos de falha no treino."},
}


class MLError(ValueError):
    pass


def available_models() -> dict:
    info = {k: dict(v) for k, v in MODEL_INFO.items()}
    info["xgboost"]["disponivel"] = HAS_XGB
    for k in info:
        info[k].setdefault("disponivel", True)
    return info


def _make_classifier(modelo: str, pos_weight: float, params: dict, seed: int):
    if modelo == "random_forest":
        clf = RandomForestClassifier(
            n_estimators=int(params.get("n_estimators", 200)),
            max_depth=params.get("max_depth") or None,
            min_samples_leaf=int(params.get("min_samples_leaf", 3)),
            class_weight="balanced_subsample", n_jobs=-1, random_state=seed)
        return make_pipeline(SimpleImputer(strategy="median"), clf)
    if modelo == "xgboost":
        if not HAS_XGB:
            raise MLError("XGBoost não está instalado no servidor.")
        clf = XGBClassifier(
            n_estimators=int(params.get("n_estimators", 300)),
            max_depth=int(params.get("max_depth") or 4),
            learning_rate=float(params.get("learning_rate", 0.05)),
            subsample=0.8, colsample_bytree=0.8, scale_pos_weight=pos_weight,
            eval_metric="aucpr", n_jobs=-1, random_state=seed, tree_method="hist")
        return clf  # trata NaN nativamente
    if modelo == "baseline":
        return make_pipeline(SimpleImputer(strategy="median"),
                             DummyClassifier(strategy="stratified", random_state=seed))
    raise MLError(f"Modelo desconhecido: {modelo}")


def _sample_metrics(y_true, y_pred, y_score) -> dict:
    y_true = np.asarray(y_true)
    out = {
        "precisao": clean_float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": clean_float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": clean_float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": None, "pr_auc": None,
        "prevalencia": clean_float(y_true.mean()),
    }
    if len(np.unique(y_true)) == 2 and y_score is not None:
        out["roc_auc"] = clean_float(roc_auc_score(y_true, y_score))
        out["pr_auc"] = clean_float(average_precision_score(y_true, y_score))
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    out["matriz_confusao"] = {"vn": int(cm[0, 0]), "fp": int(cm[0, 1]), "fn": int(cm[1, 0]), "vp": int(cm[1, 1])}
    return out


def _alert_episodes(meta: pd.DataFrame, flag: np.ndarray, gap: pd.Timedelta = pd.Timedelta("2h")) -> list[dict]:
    """Agrupa amostras positivas consecutivas (por equipamento) em episódios de alerta."""
    eps = []
    df = meta[[COL_TIMESTAMP, COL_EQUIPMENT]].copy()
    df["flag"] = flag
    for eq, g in df[df["flag"]].groupby(COL_EQUIPMENT):
        ts = g[COL_TIMESTAMP].sort_values()
        new = ts.diff() > gap
        grp = new.cumsum()
        for _, t in ts.groupby(grp.values):
            eps.append({"equipamento": eq, "inicio": t.iloc[0], "fim": t.iloc[-1], "amostras": int(len(t))})
    return eps


def _event_metrics(meta: pd.DataFrame, y_true: np.ndarray, flag: np.ndarray, horizonte_h: float) -> dict:
    """Avaliação por evento de falha (o que um operador perceberia)."""
    events = meta.loc[y_true == 1, "evento"].dropna().unique()
    detected, leads = 0, []
    details = []
    for ev in events:
        m = (meta["evento"] == ev).to_numpy()
        hits = m & flag
        ttf = meta.loc[m, "horas_ate_falha"]
        if hits.any():
            detected += 1
            lead = float(meta.loc[hits, "horas_ate_falha"].max())
            leads.append(lead)
        else:
            lead = None
        fail_time = (meta.loc[m, COL_TIMESTAMP].iloc[0] + pd.Timedelta(hours=float(ttf.iloc[0])))
        details.append({"evento": ev, "equipamento": ev.split("#")[0], "inicio_falha": fail_time.isoformat(),
                        "antecipada": bool(hits.any()),
                        "antecedencia_h": round(lead, 2) if lead is not None else None})
    episodes = _alert_episodes(meta, flag & (y_true == 0))
    span_days = 0.0
    for _, g in meta.groupby(COL_EQUIPMENT):
        span_days += (g[COL_TIMESTAMP].max() - g[COL_TIMESTAMP].min()).total_seconds() / 86400
    return {
        "falhas_no_teste": int(len(events)),
        "falhas_antecipadas": int(detected),
        "taxa_deteccao_eventos": clean_float(detected / len(events)) if len(events) else None,
        "antecedencia_media_h": clean_float(np.mean(leads)) if leads else None,
        "alarmes_falsos": len(episodes),
        "alarmes_falsos_por_30d": clean_float(len(episodes) / span_days * 30) if span_days > 0 else None,
        "horizonte_h": horizonte_h,
        "detalhes": details,
    }


def _temporal_split(meta: pd.DataFrame, test_frac: float) -> tuple[np.ndarray, np.ndarray, pd.Timestamp]:
    t0, t1 = meta[COL_TIMESTAMP].min(), meta[COL_TIMESTAMP].max()
    cutoff = t0 + (t1 - t0) * (1 - test_frac)
    train = (meta[COL_TIMESTAMP] < cutoff).to_numpy()
    return train, ~train, cutoff


def _importances(model, features: list[str], top: int = 20) -> list[dict]:
    est = model.steps[-1][1] if hasattr(model, "steps") else model
    imp = getattr(est, "feature_importances_", None)
    if imp is None:
        return []
    order = np.argsort(imp)[::-1][:top]
    return [{"atributo": features[i], "importancia": round(float(imp[i]), 5)} for i in order if imp[i] > 0]


def _prob_series(meta: pd.DataFrame, score: np.ndarray, max_points_per_eq: int = 1500) -> dict:
    out = {}
    df = meta[[COL_TIMESTAMP, COL_EQUIPMENT]].copy()
    df["score"] = score
    df["y"] = meta["_y"].to_numpy() if "_y" in meta else 0
    for eq, g in df.groupby(COL_EQUIPMENT):
        g = g.set_index(COL_TIMESTAMP).sort_index()
        span = (g.index.max() - g.index.min()).total_seconds()
        bin_s = max(900, int(np.ceil(span / max_points_per_eq)))
        r = g[["score", "y"]].resample(f"{bin_s}s").max().dropna(how="all")
        out[eq] = {"timestamps": ts_to_list(r.index), "score": series_to_list(r["score"]),
                   "rotulo": series_to_list(r["y"], 0)}
    return out


def train_classifier(ds: Dataset, equipamentos: list[str], modelo: str = "random_forest",
                     horizonte_h: float = 24.0, test_frac: float = 0.3, limiar: float = 0.5,
                     params: dict | None = None, seed: int = 42, cv_splits: int = 4) -> dict:
    params = params or {}
    t_start = time.time()
    if not ds.has_status:
        raise MLError("Modelos supervisionados precisam da coluna de estado operacional para gerar "
                      "rótulos de falha. Use o Isolation Forest (não supervisionado) ou mapeie o estado.")
    X, y, meta, features = build_dataset(ds, equipamentos, horizonte_h)
    if y.sum() == 0:
        raise MLError("Nenhuma falha encontrada nos equipamentos selecionados — não há o que prever.")
    train, test, cutoff = _temporal_split(meta, test_frac)
    ev_train = meta.loc[train & (y == 1).to_numpy(), "evento"].nunique()
    ev_test = meta.loc[test & (y == 1).to_numpy(), "evento"].nunique()
    avisos = []
    if ev_train < 1:
        raise MLError("O período de treino não contém nenhuma falha. Reduza a fração de teste ou use mais dados.")
    if ev_test < 1:
        raise MLError("O período de teste não contém nenhuma falha; não é possível avaliar o modelo. "
                      "Aumente a fração de teste.")
    if ev_train < 3:
        avisos.append(f"Apenas {ev_train} falha(s) no treino: o modelo aprende com pouquíssimos exemplos; "
                      "trate os resultados como exploratórios.")
    if ev_test < 3:
        avisos.append(f"Apenas {ev_test} falha(s) no teste: as métricas por evento têm alta incerteza.")

    Xtr, ytr, Xte, yte = X[train], y[train], X[test], y[test]
    pos_weight = float((ytr == 0).sum() / max(1, (ytr == 1).sum()))
    model = _make_classifier(modelo, pos_weight, params, seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(Xtr, ytr)
        p_tr = model.predict_proba(Xtr)[:, 1]
        p_te = model.predict_proba(Xte)[:, 1]

    # validação cruzada temporal no treino
    cv = []
    tss = TimeSeriesSplit(n_splits=cv_splits)
    order = np.argsort(meta.loc[train, COL_TIMESTAMP].to_numpy(), kind="stable")
    Xtr_o, ytr_o = Xtr.iloc[order], ytr.iloc[order]
    for k, (a, b) in enumerate(tss.split(Xtr_o)):
        if ytr_o.iloc[a].sum() == 0 or ytr_o.iloc[b].sum() == 0:
            cv.append({"dobra": k + 1, "f1": None, "pr_auc": None, "observacao": "dobra sem falhas"})
            continue
        m = _make_classifier(modelo, pos_weight, params, seed)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m.fit(Xtr_o.iloc[a], ytr_o.iloc[a])
            pb = m.predict_proba(Xtr_o.iloc[b])[:, 1]
        cv.append({"dobra": k + 1, "f1": clean_float(f1_score(ytr_o.iloc[b], pb >= limiar, zero_division=0)),
                   "pr_auc": clean_float(average_precision_score(ytr_o.iloc[b], pb))})
    cv_f1 = [c["f1"] for c in cv if c["f1"] is not None]

    pred_te = p_te >= limiar
    m_test = _sample_metrics(yte, pred_te.astype(int), p_te)
    m_train = _sample_metrics(ytr, (p_tr >= limiar).astype(int), p_tr)
    meta_te = meta[test].reset_index(drop=True)
    ev = _event_metrics(meta_te, yte.to_numpy(), pred_te, horizonte_h)

    pr = None
    if len(np.unique(yte)) == 2:
        prec, rec, thr = precision_recall_curve(yte, p_te)
        step = max(1, len(thr) // 200)
        pr = {"precisao": [round(float(v), 4) for v in prec[:-1][::step]],
              "recall": [round(float(v), 4) for v in rec[:-1][::step]],
              "limiar": [round(float(v), 4) for v in thr[::step]]}

    if m_train["f1"] is not None and m_test["f1"] is not None and m_train["f1"] - m_test["f1"] > 0.25:
        avisos.append("F1 no treino muito maior que no teste: indício de sobreajuste (overfitting).")

    meta_te["_y"] = yte.to_numpy()
    info = MODEL_INFO[modelo]
    return {
        "tipo": "classificacao", "modelo": modelo, "modelo_nome": info["nome"],
        "dataset_id": ds.id, "dataset_sintetico": ds.is_synthetic, "dataset_origem": ds.data_origin,
        "equipamentos": equipamentos,
        "parametros": {"horizonte_h": horizonte_h, "fracao_teste": test_frac, "limiar": limiar,
                       "semente": seed, **params},
        "divisao": {"corte": cutoff.isoformat(), "amostras_treino": int(train.sum()),
                    "amostras_teste": int(test.sum()), "falhas_treino": int(ev_train), "falhas_teste": int(ev_test),
                    "positivos_treino": int(ytr.sum()), "positivos_teste": int(yte.sum())},
        "atributos": {"n": len(features), "lista": features},
        "metricas": {"teste": m_test, "treino": m_train, "eventos": ev,
                     "cv": {"dobras": cv, "f1_media": clean_float(np.mean(cv_f1)) if cv_f1 else None,
                            "f1_desvio": clean_float(np.std(cv_f1)) if len(cv_f1) > 1 else None}},
        "curva_pr": pr,
        "importancias": _importances(model, features),
        "series": _prob_series(meta_te, p_te),
        "avisos": avisos,
        "duracao_s": round(time.time() - t_start, 2),
        "_model": model, "_features": features,
    }


def train_isolation_forest(ds: Dataset, equipamentos: list[str], contaminacao: float = 0.02,
                           horizonte_h: float = 24.0, test_frac: float = 0.3, seed: int = 42,
                           n_estimators: int = 200) -> dict:
    t_start = time.time()
    X, y, meta, features = build_dataset(ds, equipamentos, horizonte_h)
    train, test, cutoff = _temporal_split(meta, test_frac)
    # treina apenas com operação aparentemente normal do período de treino
    normal = train.copy()
    if ds.has_status:
        normal &= (meta["estado"] == "operando").to_numpy()
    imp = SimpleImputer(strategy="median")
    Xtr = imp.fit_transform(X[normal])
    iso = IsolationForest(n_estimators=n_estimators, contamination=contaminacao, random_state=seed, n_jobs=-1)
    iso.fit(Xtr)
    Xte = imp.transform(X[test])
    score_te = -iso.score_samples(Xte)  # maior = mais anômalo
    flag_te = iso.predict(Xte) == -1
    meta_te = meta[test].reset_index(drop=True)
    yte = y[test].to_numpy()

    avisos = ["Isolation Forest detecta comportamento incomum, não necessariamente falha. A comparação com "
              "os rótulos de falha abaixo é apenas uma referência."]
    metrics = {"taxa_anomalias_teste": clean_float(flag_te.mean())}
    ev = None
    if ds.has_status and yte.sum() > 0:
        metrics["referencia_rotulos"] = _sample_metrics(yte, flag_te.astype(int), score_te)
        ev = _event_metrics(meta_te, yte, flag_te, horizonte_h)
    elif not ds.has_status:
        avisos.append("Sem coluna de estado: não há rótulos para comparar as anomalias encontradas.")

    meta_te["_y"] = yte
    # normaliza o score para 0–1 apenas para exibição
    lo, hi = np.percentile(score_te, [1, 99.9]) if len(score_te) else (0, 1)
    disp = np.clip((score_te - lo) / (hi - lo + 1e-9), 0, 1)
    thr_disp = None
    if flag_te.any() and (~flag_te).any():
        thr_raw = (score_te[flag_te].min() + score_te[~flag_te].max()) / 2
        thr_disp = clean_float(np.clip((thr_raw - lo) / (hi - lo + 1e-9), 0, 1))
    return {
        "tipo": "anomalia", "modelo": "isolation_forest", "modelo_nome": MODEL_INFO["isolation_forest"]["nome"],
        "dataset_id": ds.id, "dataset_sintetico": ds.is_synthetic, "dataset_origem": ds.data_origin,
        "equipamentos": equipamentos,
        "parametros": {"contaminacao": contaminacao, "horizonte_h_referencia": horizonte_h,
                       "fracao_teste": test_frac, "semente": seed, "n_estimators": n_estimators},
        "divisao": {"corte": cutoff.isoformat(), "amostras_treino_normais": int(normal.sum()),
                    "amostras_teste": int(test.sum())},
        "atributos": {"n": len(features), "lista": features},
        "metricas": {"teste": metrics.get("referencia_rotulos"), "eventos": ev, "anomalia": metrics},
        "limiar_exibicao": thr_disp,
        "series": _prob_series(meta_te, disp),
        "avisos": avisos,
        "duracao_s": round(time.time() - t_start, 2),
        "_flags": {"meta": meta_te[[COL_TIMESTAMP, COL_EQUIPMENT]], "flag": flag_te, "score": disp},
    }
