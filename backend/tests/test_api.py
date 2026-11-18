"""Testes de integração da API (fluxo completo)."""

from conftest import EXAMPLES


def test_health_and_demo(client):
    r = client.get("/api/health").json()
    assert r["status"] == "ok"
    ds = client.get("/api/datasets").json()
    demo = next(d for d in ds if d["is_demo"])
    assert demo["is_synthetic"] and demo["data_origin"] == "simulado"


def test_dashboard(client):
    r = client.get("/api/dashboard/demo-sintetico")
    assert r.status_code == 200
    d = r.json()
    assert d["dataset"]["is_synthetic"]
    assert len(d["equipamentos"]) == 4
    assert {"monitoramento", "valores", "sparkline"} <= set(d["equipamentos"][0])


def test_series_downsampled(client):
    r = client.get("/api/datasets/demo-sintetico/series", params={"equipamento": "MTR-01", "max_points": 500}).json()
    assert r["reamostrado"] and len(r["timestamps"]) <= 520
    assert "vibracao" in r["series"]


def test_upload_import_flow(client):
    path = EXAMPLES / "sintetico_inversores_padrao_br.csv"
    with open(path, "rb") as f:
        up = client.post("/api/datasets/upload", files={"file": (path.name, f, "text/csv")})
    assert up.status_code == 200, up.text
    u = up.json()
    sug = u["sugestao"]
    assert sug["roles"]["timestamp"] == "Data/Hora"
    body = {"upload_id": u["upload_id"], "nome": "Teste inversores", "origem": "simulado",
            "roles": sug["roles"], "variables": sug["variables"], "status_map": sug["status_map"]}
    r = client.post("/api/datasets/import", json=body)
    assert r.status_code == 200, r.text
    meta = r.json()["dataset"]
    assert meta["is_synthetic"] and meta["equipment"] == ["INV-01", "INV-02"]
    ds_id = meta["id"]
    m = client.get(f"/api/maintenance/{ds_id}").json()
    assert m["possui_estado"]
    assert client.delete(f"/api/datasets/{ds_id}").status_code == 200


def test_import_requires_declared_origin(client):
    path = EXAMPLES / "sintetico_compressor_sem_estado.csv"
    with open(path, "rb") as f:
        u = client.post("/api/datasets/upload", files={"file": (path.name, f, "text/csv")}).json()
    body = {"upload_id": u["upload_id"], "nome": "x", "roles": u["sugestao"]["roles"],
            "variables": u["sugestao"]["variables"]}
    assert client.post("/api/datasets/import", json=body).status_code == 422
    body["origem"] = "simulado"
    r = client.post("/api/datasets/import", json=body).json()
    ds_id = r["dataset"]["id"]
    # sem estado: indicadores marcados como insuficientes, sem valores inventados
    m = client.get(f"/api/maintenance/{ds_id}").json()
    assert m["possui_estado"] is False
    assert m["equipamentos"][0]["indicadores"]["mtbf"]["valor"] is None
    # modelo supervisionado deve recusar
    assert client.post(f"/api/ml/{ds_id}/classification", json={"modelo": "random_forest"}).status_code == 422
    client.delete(f"/api/datasets/{ds_id}")


def test_upload_rejects_garbage(client):
    r = client.post("/api/datasets/upload", files={"file": ("x.csv", b"", "text/csv")})
    assert r.status_code == 422


def test_demo_cannot_be_deleted(client):
    assert client.delete("/api/datasets/demo-sintetico").status_code == 400


def test_thresholds_crud_and_alert_origins(client):
    r = client.put("/api/alerts/demo-sintetico/thresholds/INV-01/potencia", json={"max": 40, "severidade": "baixa"})
    assert r.status_code == 200
    a = client.get("/api/alerts/demo-sintetico", params={"equipamento": "INV-01", "origens": "limite"}).json()
    assert a["alertas"] and all(x["origem"] == "limite" for x in a["alertas"])
    assert client.put("/api/alerts/demo-sintetico/thresholds/INV-01/potencia",
                      json={"min": 5, "max": 1}).status_code == 422
    assert client.delete("/api/alerts/demo-sintetico/thresholds/INV-01/potencia").status_code == 200


def test_ml_runs_and_model_alerts(client):
    r = client.post("/api/ml/demo-sintetico/classification",
                    json={"modelo": "xgboost", "equipamentos": ["MTR-01"], "horizonte_h": 24})
    assert r.status_code == 200, r.text
    run = r.json()
    assert "_model" not in run and run["dataset_sintetico"] is True
    runs = client.get("/api/ml/runs", params={"dataset_id": "demo-sintetico"}).json()
    assert any(x["id"] == run["id"] for x in runs)
    al = client.get("/api/alerts/demo-sintetico", params={"origens": "modelo"}).json()
    assert all(x["origem"] == "modelo" for x in al["alertas"])
    assert al["resumo"]["por_origem"]["modelo"] >= 1


def test_forecast_endpoint(client):
    r = client.post("/api/ml/demo-sintetico/forecast",
                    json={"equipamento": "MTR-01", "variavel": "temperatura", "horizonte_h": 24})
    assert r.status_code == 200, r.text
    assert r.json()["melhor_modelo"]


def test_report_marks_simulation(client):
    r = client.post("/api/reports/demo-sintetico", json={"equipamento": "MTR-01"})
    assert r.status_code == 200
    html = r.text
    assert "SIMULAÇÃO" in html and "Dados simulados" in html
    assert "Indicadores de manutenção" in html and "Metodologia" in html
