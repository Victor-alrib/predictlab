"""Configurações e registro de variáveis canônicas do PredictLab.

O registro de variáveis define o "vocabulário" interno da plataforma. Qualquer
CSV importado é traduzido para esse vocabulário pelo sistema de mapeamento
(ver ``services/ingestion.py``). Colunas que não correspondem a nenhuma
variável canônica podem ser importadas como variáveis personalizadas.
"""

from __future__ import annotations

from pathlib import Path

APP_NAME = "PredictLab"
APP_VERSION = "0.1.0"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATASETS_DIR = DATA_DIR / "datasets"
DATASETS_DIR.mkdir(parents=True, exist_ok=True)

# Limite de tamanho de upload (bytes). CSVs maiores devem ser pré-agregados.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Colunas internas reservadas (papéis estruturais, não variáveis de processo).
COL_TIMESTAMP = "timestamp"
COL_EQUIPMENT = "equipamento"
COL_STATUS = "estado"

# Variáveis canônicas de processo: chave interna -> metadados.
# ``aliases`` alimenta a sugestão automática de mapeamento (comparação por
# nome normalizado, sem acentos e em minúsculas).
CANONICAL_VARIABLES: dict[str, dict] = {
    "temperatura": {
        "label": "Temperatura",
        "unit": "°C",
        "aliases": ["temperatura", "temp", "temperature", "t", "tmp", "temp_c",
                    "module_temperature", "ambient_temperature", "temperatura_c",
                    "air temperature [k]", "process temperature [k]"],
    },
    "corrente": {
        "label": "Corrente",
        "unit": "A",
        "aliases": ["corrente", "current", "i", "amps", "ampere", "corrente_a",
                    "current_a", "i_rms", "irms", "dc_current", "ac_current"],
    },
    "tensao": {
        "label": "Tensão",
        "unit": "V",
        "aliases": ["tensao", "voltage", "v", "volts", "tensao_v", "voltage_v",
                    "v_rms", "vrms", "dc_voltage", "ac_voltage"],
    },
    "potencia": {
        "label": "Potência",
        "unit": "kW",
        "aliases": ["potencia", "power", "p", "kw", "potencia_kw", "power_kw",
                    "ac_power", "dc_power", "active_power", "potencia_ativa"],
    },
    "vibracao": {
        "label": "Vibração",
        "unit": "mm/s",
        "aliases": ["vibracao", "vibration", "vib", "vibracao_rms", "vib_rms",
                    "velocity_rms", "vibration_mm_s", "vibracao_mm_s"],
    },
}

# Papéis estruturais e seus aliases para sugestão automática.
ROLE_ALIASES: dict[str, list[str]] = {
    COL_TIMESTAMP: ["timestamp", "datetime", "date_time", "data_hora", "datahora",
                    "data", "date", "time", "hora", "ts", "date time"],
    COL_EQUIPMENT: ["equipamento", "equipment", "equipment_id", "id_equipamento",
                    "tag", "asset", "ativo", "machine", "maquina", "source_key",
                    "unit", "unidade", "inverter_id", "device", "dispositivo",
                    "inversor", "motor", "compressor", "bomba", "id"],
    COL_STATUS: ["estado", "status", "state", "estado_operacional",
                 "operational_state", "machine_status", "condicao", "modo",
                 "machine failure", "failure", "falha"],
}

# Categorias normalizadas de estado operacional.
STATUS_CATEGORIES: dict[str, str] = {
    "operando": "Operando",
    "parado": "Parado / standby",
    "falha": "Falha",
    "manutencao": "Manutenção",
    "desconhecido": "Desconhecido",
}

# Palavras-chave para sugerir a categoria de um valor bruto de estado.
STATUS_KEYWORDS: dict[str, list[str]] = {
    "falha": ["falha", "fault", "failure", "fail", "erro", "error", "trip",
              "alarme", "alarm", "defeito", "quebra", "breakdown", "down"],
    "manutencao": ["manut", "maint", "service", "reparo", "repair", "pm"],
    "parado": ["parado", "stop", "stopped", "idle", "standby", "off",
               "desligado", "ocioso"],
    "operando": ["operando", "run", "running", "on", "ok", "normal", "ligado",
                 "operation", "operating", "producao", "production", "ativo"],
}

# Origem declarada do dado. É obrigatória na importação e aparece em todos os
# painéis e relatórios — o objetivo é nunca confundir simulação com medição.
DATA_ORIGINS: dict[str, str] = {
    "medicao_real": "Medição real de campo",
    "dataset_publico": "Dataset público (terceiros)",
    "simulado": "Dados simulados / sintéticos",
}

DEMO_DATASET_ID = "demo-sintetico"
