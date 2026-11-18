"""Gera CSVs de exemplo (SINTÉTICOS) para testar a importação e o mapeamento.

Cada arquivo usa uma convenção diferente de nomes de coluna e formatação, para
exercitar o sistema de mapeamento. Todos são dados simulados — o prefixo
``sintetico_`` no nome do arquivo deixa isso explícito.

Uso (a partir da raiz do repositório):
    python examples/gerar_exemplos.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.synthetic import generate_demo_dataframe  # noqa: E402

OUT = Path(__file__).resolve().parent


def main() -> None:
    df, _ = generate_demo_dataframe(seed=7, days=45)

    # 1) Motor com nomes em inglês, separador vírgula, estado textual em inglês
    m = df[df["equipamento"] == "MTR-01"].copy()
    m["status"] = m["estado"].map({"operando": "RUNNING", "falha": "FAULT", "manutencao": "MAINTENANCE"})
    m = m.rename(columns={"timestamp": "datetime", "equipamento": "asset_id", "temperatura": "temperature_c",
                          "corrente": "current_a", "tensao": "voltage_v", "potencia": "power_kw",
                          "vibracao": "vibration_mm_s"})
    m = m[["datetime", "asset_id", "status", "temperature_c", "current_a", "voltage_v", "power_kw", "vibration_mm_s"]]
    m.to_csv(OUT / "sintetico_motor_colunas_ingles.csv", index=False, float_format="%.3f")

    # 2) Inversores no padrão brasileiro: ';' como separador, vírgula decimal, data dd/mm/aaaa
    inv = df[df["equipamento"].isin(["INV-01", "INV-02"])].copy()
    inv["Data/Hora"] = inv["timestamp"].dt.strftime("%d/%m/%Y %H:%M")
    inv["Estado Operacional"] = inv["estado"].map({"operando": "Operando", "parado": "Standby",
                                                   "falha": "Falha", "manutencao": "Manutenção"})
    inv["Irradiância estimada (W/m²)"] = (inv["potencia"] / 50 * 1000).round(1)  # variável personalizada
    out = inv[["Data/Hora", "equipamento", "Estado Operacional", "temperatura", "corrente", "tensao", "potencia",
               "Irradiância estimada (W/m²)"]].rename(columns={
        "equipamento": "Inversor", "temperatura": "Temp. Dissipador (°C)", "corrente": "Corrente CA (A)",
        "tensao": "Tensão CA (V)", "potencia": "Potência Ativa (kW)"})
    out.to_csv(OUT / "sintetico_inversores_padrao_br.csv", index=False, float_format="%.3f", sep=";", decimal=",",
                        encoding="utf-8")

    # 3) Compressor sem coluna de estado e sem coluna de equipamento (só sensores)
    c = df[df["equipamento"] == "CMP-01"][["timestamp", "temperatura", "vibracao", "corrente"]].copy()
    c = c.rename(columns={"timestamp": "ts", "temperatura": "temp", "vibracao": "vib_rms", "corrente": "i_rms"})
    c.to_csv(OUT / "sintetico_compressor_sem_estado.csv", index=False, float_format="%.3f")

    for f in sorted(OUT.glob("sintetico_*.csv")):
        print(f"{f.name}: {f.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
