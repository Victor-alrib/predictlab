"""Importação de CSV e sistema de mapeamento de variáveis.

Fluxo em duas etapas:

1. ``parse_csv`` + ``suggest_mapping``: o arquivo é lido (detectando
   separador, separador decimal e codificação — CSVs brasileiros costumam usar
   ``;`` e vírgula decimal) e o sistema sugere qual coluna corresponde a cada
   papel (timestamp, equipamento, estado) e a cada variável canônica.
2. ``apply_mapping``: o usuário confirma/edita o mapeamento e o DataFrame é
   convertido para o esquema interno. Nenhuma coluna é obrigatória além do
   timestamp; datasets diferentes podem ter conjuntos de variáveis diferentes.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from difflib import SequenceMatcher

import numpy as np
import pandas as pd

from ..config import (CANONICAL_VARIABLES, COL_EQUIPMENT, COL_STATUS, COL_TIMESTAMP,
                      ROLE_ALIASES, STATUS_CATEGORIES, STATUS_KEYWORDS)


class IngestionError(ValueError):
    """Erro de importação com mensagem pronta para o usuário."""


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.strip().lower()
    s = re.sub(r"[\s\-\.]+", "_", s)
    return s


def slugify(name: str) -> str:
    s = normalize_name(name)
    s = re.sub(r"[^a-z0-9_]", "", s).strip("_")
    return s or "variavel"


# --- leitura -----------------------------------------------------------------

def _decode(raw: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise IngestionError("Não foi possível decodificar o arquivo (UTF-8 ou Latin-1).")


def _detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in (";", ",", "\t", "|")}
        return max(counts, key=counts.get)


def _detect_decimal(df: pd.DataFrame, delimiter: str) -> str:
    """Se o separador é ';' e há muitos valores do tipo '12,5', usa vírgula decimal."""
    if delimiter == ",":
        return "."
    pat = re.compile(r"^-?\d+,\d+$")
    hits = total = 0
    for col in df.columns:
        vals = df[col].dropna().astype(str).head(200)
        total += len(vals)
        hits += vals.map(lambda v: bool(pat.match(v.strip()))).sum()
    return "," if total and hits / total > 0.05 else "."


def parse_csv(raw: bytes) -> tuple[pd.DataFrame, dict]:
    if not raw or not raw.strip():
        raise IngestionError("O arquivo está vazio.")
    text, encoding = _decode(raw)
    sample = text[:20000]
    delimiter = _detect_delimiter(sample)
    try:
        df_str = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str,
                             keep_default_na=True, skipinitialspace=True)
    except Exception as exc:  # pandas.errors.ParserError e afins
        raise IngestionError(f"Falha ao ler o CSV: {exc}") from exc
    df_str.columns = [str(c).strip() for c in df_str.columns]
    if df_str.shape[1] < 2:
        raise IngestionError("O CSV precisa ter ao menos duas colunas (timestamp e uma variável).")
    if len(df_str) == 0:
        raise IngestionError("O CSV não contém linhas de dados.")
    decimal = _detect_decimal(df_str, delimiter)
    info = {"encoding": encoding, "delimiter": delimiter, "decimal": decimal,
            "rows": int(len(df_str)), "columns": list(df_str.columns)}
    return df_str, info


def to_numeric(series: pd.Series, decimal: str) -> pd.Series:
    s = series.astype(str).str.strip()
    if decimal == ",":
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def parse_timestamp(series: pd.Series, fmt: str | None = None) -> pd.Series:
    """Interpreta timestamps em formatos comuns (ISO, brasileiro, epoch).

    Datas com barra/traço no formato dd/mm/aaaa vs mm/dd/aaaa são
    desambiguadas pelos próprios dados (um componente > 12 decide); se todas
    forem ambíguas, assume-se dia/mês (padrão brasileiro).
    """
    s = series.astype(str).str.strip()
    if fmt:
        return pd.to_datetime(s, format=fmt, errors="coerce")
    # números puros: epoch em segundos ou milissegundos
    numeric = pd.to_numeric(s, errors="coerce")
    if numeric.notna().mean() > 0.95:
        unit = "ms" if numeric.median() > 1e11 else "s"
        return pd.to_datetime(numeric, unit=unit, errors="coerce")
    sample = s.dropna().head(2000)
    dmy = sample.str.extract(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})")
    if dmy[0].notna().mean() > 0.9:
        a = pd.to_numeric(dmy[0], errors="coerce")
        b = pd.to_numeric(dmy[1], errors="coerce")
        dayfirst = not ((b > 12).any() and not (a > 12).any())
        parsed = pd.to_datetime(s, errors="coerce", format="mixed", dayfirst=dayfirst)
    elif sample.str.match(r"^\d{4}-\d{2}-\d{2}").mean() > 0.9:
        parsed = pd.to_datetime(s, errors="coerce", format="ISO8601", utc=False)
        if parsed.isna().mean() > 0.5:
            parsed = pd.to_datetime(s, errors="coerce", format="mixed")
    else:
        try:
            parsed = pd.to_datetime(s, errors="coerce", format="mixed")
        except (ValueError, TypeError):
            parsed = pd.Series(pd.NaT, index=series.index)
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_convert(None)
    return parsed


# --- sugestão de mapeamento ----------------------------------------------------

def _similarity(col: str, aliases: list[str]) -> float:
    n = normalize_name(col)
    n_clean = re.sub(r"_?\(?\[?(c|a|v|kw|w|mm_s|mms|k|degc)\]?\)?$", "", n)
    best = 0.0
    for a in aliases:
        a_n = normalize_name(a)
        if n == a_n or n_clean == a_n:
            return 1.0
        tokens = set(re.split(r"_+", n))
        if a_n in tokens and len(a_n) > 2:
            best = max(best, 0.85)
        elif len(a_n) > 3 and a_n in n:
            best = max(best, 0.75)
        best = max(best, SequenceMatcher(None, n, a_n).ratio() * 0.8)
    return best


def _numeric_ratio(series: pd.Series, decimal: str) -> float:
    vals = series.dropna().head(500)
    if not len(vals):
        return 0.0
    return float(to_numeric(vals, decimal).notna().mean())


def suggest_status_map(values: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for v in values:
        n = normalize_name(v)
        cat = "desconhecido"
        if n in ("0", "false", "nao", "no"):
            cat = "operando"  # convenção comum em colunas binárias de falha
        elif n in ("1", "true", "sim", "yes"):
            cat = "falha"
        else:
            for c, kws in STATUS_KEYWORDS.items():
                if any(n == k or n.startswith(k) or k in n.split("_") for k in kws):
                    cat = c
                    break
        out[v] = cat
    return out


def suggest_mapping(df_str: pd.DataFrame, info: dict) -> dict:
    decimal = info["decimal"]
    cols = list(df_str.columns)
    used: set[str] = set()
    roles: dict[str, str | None] = {COL_TIMESTAMP: None, COL_EQUIPMENT: None, COL_STATUS: None}

    # timestamp: alias + parse bem-sucedido
    ts_scores = []
    for c in cols:
        score = _similarity(c, ROLE_ALIASES[COL_TIMESTAMP])
        parsed_ok = parse_timestamp(df_str[c].head(300)).notna().mean()
        if _numeric_ratio(df_str[c], decimal) > 0.95 and score < 0.9:
            parsed_ok *= 0.3  # números puros só são timestamp se o nome indicar
        ts_scores.append((score * 0.5 + parsed_ok * 0.5, c))
    ts_scores.sort(reverse=True)
    if ts_scores and ts_scores[0][0] > 0.45:
        roles[COL_TIMESTAMP] = ts_scores[0][1]
        used.add(ts_scores[0][1])

    # equipamento e estado: colunas preferencialmente não numéricas
    for role in (COL_EQUIPMENT, COL_STATUS):
        best = (0.0, None)
        for c in cols:
            if c in used:
                continue
            score = _similarity(c, ROLE_ALIASES[role])
            nunique = df_str[c].nunique(dropna=True)
            if role == COL_EQUIPMENT and nunique > 200:
                score *= 0.3
            if role == COL_STATUS and nunique > 30:
                score *= 0.3
            if score > best[0]:
                best = (score, c)
        if best[0] >= 0.75:
            roles[role] = best[1]
            used.add(best[1])

    # variáveis
    variables = []
    taken_keys: set[str] = set()
    for c in cols:
        if c in used:
            continue
        num = _numeric_ratio(df_str[c], decimal)
        if num < 0.8:
            variables.append({"column": c, "key": None, "action": "ignorar",
                              "reason": "coluna não numérica", "label": c, "unit": ""})
            continue
        best_key, best_score = None, 0.0
        for key, meta in CANONICAL_VARIABLES.items():
            if key in taken_keys:
                continue
            s = _similarity(c, meta["aliases"])
            if s > best_score:
                best_key, best_score = key, s
        if best_key and best_score >= 0.75:
            meta = CANONICAL_VARIABLES[best_key]
            taken_keys.add(best_key)
            variables.append({"column": c, "key": best_key, "action": "canonica",
                              "confidence": round(best_score, 2),
                              "label": meta["label"], "unit": meta["unit"]})
        else:
            variables.append({"column": c, "key": slugify(c), "action": "personalizada",
                              "label": c, "unit": _guess_unit(c)})

    status_values: list[str] = []
    status_map: dict[str, str] = {}
    if roles[COL_STATUS]:
        status_values = df_str[roles[COL_STATUS]].dropna().astype(str).str.strip().value_counts().head(30).index.tolist()
        status_map = suggest_status_map(status_values)

    return {"roles": roles, "variables": variables, "status_values": status_values,
            "status_map": status_map, "equipamento_padrao": "EQ-01"}


def _guess_unit(col: str) -> str:
    m = re.search(r"[\[\(]([^\]\)]{1,8})[\]\)]\s*$", col)
    return m.group(1) if m else ""


def describe_status_values(df_str: pd.DataFrame, col: str) -> list[str]:
    return df_str[col].dropna().astype(str).str.strip().value_counts().head(30).index.tolist()


# --- aplicação do mapeamento ---------------------------------------------------

def apply_mapping(df_str: pd.DataFrame, info: dict, mapping: dict) -> tuple[pd.DataFrame, list[dict], dict]:
    """Converte o CSV bruto para o esquema interno.

    ``mapping`` = {
      "roles": {"timestamp": col, "equipamento": col|None, "estado": col|None},
      "equipamento_padrao": "EQ-01",
      "timestamp_format": None | "%d/%m/%Y %H:%M",
      "status_map": {valor_bruto: categoria},
      "variables": [{"column", "key", "action": canonica|personalizada|ignorar, "label", "unit"}]
    }
    Retorna (df, variáveis, relatório de conversão).
    """
    roles = mapping.get("roles") or {}
    ts_col = roles.get(COL_TIMESTAMP)
    if not ts_col or ts_col not in df_str.columns:
        raise IngestionError("Selecione a coluna de timestamp — ela é a única obrigatória.")

    decimal = mapping.get("decimal") or info.get("decimal", ".")
    report: dict = {"linhas_lidas": int(len(df_str)), "avisos": []}

    out = pd.DataFrame(index=df_str.index)
    out[COL_TIMESTAMP] = parse_timestamp(df_str[ts_col], mapping.get("timestamp_format"))
    bad_ts = int(out[COL_TIMESTAMP].isna().sum())
    if bad_ts == len(out):
        raise IngestionError("Nenhum timestamp pôde ser interpretado. Informe o formato manualmente "
                             "(ex.: %d/%m/%Y %H:%M).")
    if bad_ts:
        report["avisos"].append(f"{bad_ts} linha(s) descartada(s) por timestamp inválido.")

    eq_col = roles.get(COL_EQUIPMENT)
    if eq_col:
        out[COL_EQUIPMENT] = df_str[eq_col].astype(str).str.strip().replace({"": np.nan, "nan": np.nan})
        out[COL_EQUIPMENT] = out[COL_EQUIPMENT].fillna(mapping.get("equipamento_padrao") or "EQ-01")
    else:
        out[COL_EQUIPMENT] = (mapping.get("equipamento_padrao") or "EQ-01").strip() or "EQ-01"

    st_col = roles.get(COL_STATUS)
    if st_col:
        smap = mapping.get("status_map") or suggest_status_map(describe_status_values(df_str, st_col))
        invalid = {v for v in smap.values() if v not in STATUS_CATEGORIES}
        if invalid:
            raise IngestionError(f"Categoria de estado inválida: {', '.join(sorted(invalid))}")
        raw = df_str[st_col].astype(str).str.strip()
        out[COL_STATUS] = raw.map(smap)
        out.loc[df_str[st_col].isna(), COL_STATUS] = None
        unmapped = raw[out[COL_STATUS].isna() & df_str[st_col].notna()].unique()
        if len(unmapped):
            report["avisos"].append(
                f"{len(unmapped)} valor(es) de estado sem mapeamento tratados como 'desconhecido'.")
            out.loc[out[COL_STATUS].isna() & df_str[st_col].notna(), COL_STATUS] = "desconhecido"

    variables: list[dict] = []
    keys_seen: set[str] = set()
    reserved = {COL_TIMESTAMP, COL_EQUIPMENT, COL_STATUS}
    for v in mapping.get("variables") or []:
        if v.get("action") == "ignorar" or not v.get("column"):
            continue
        col = v["column"]
        if col not in df_str.columns:
            raise IngestionError(f"Coluna '{col}' não existe no arquivo.")
        if col in {ts_col, eq_col, st_col}:
            continue
        key = v.get("key") or slugify(col)
        if v.get("action") == "canonica":
            if key not in CANONICAL_VARIABLES:
                raise IngestionError(f"Variável canônica desconhecida: {key}")
        else:
            key = slugify(key)
            if key in CANONICAL_VARIABLES:
                key = f"{key}_x"
        if key in reserved:
            key = f"{key}_var"
        if key in keys_seen:
            raise IngestionError(f"A variável '{key}' foi mapeada para mais de uma coluna.")
        keys_seen.add(key)
        values = to_numeric(df_str[col], decimal)
        n_bad = int((values.isna() & df_str[col].notna()).sum())
        if n_bad:
            report["avisos"].append(f"'{col}': {n_bad} valor(es) não numérico(s) convertido(s) em vazio.")
        out[key] = values
        canon = CANONICAL_VARIABLES.get(key)
        variables.append({
            "key": key,
            "label": (v.get("label") or (canon["label"] if canon else col)).strip(),
            "unit": (v.get("unit") if v.get("unit") is not None else (canon["unit"] if canon else "")).strip(),
            "canonical": v.get("action") == "canonica",
            "source_column": col,
        })

    if not variables:
        raise IngestionError("Mapeie pelo menos uma variável numérica.")

    out = out.dropna(subset=[COL_TIMESTAMP])
    dups = int(out.duplicated(subset=[COL_EQUIPMENT, COL_TIMESTAMP]).sum())
    if dups:
        report["avisos"].append(f"{dups} registro(s) duplicado(s) (mesmo equipamento e timestamp) agregados pela média.")
        agg = {k["key"]: "mean" for k in variables}
        if COL_STATUS in out.columns:
            agg[COL_STATUS] = "last"
        out = out.groupby([COL_EQUIPMENT, COL_TIMESTAMP], as_index=False).agg(agg)
    out = out.sort_values([COL_EQUIPMENT, COL_TIMESTAMP]).reset_index(drop=True)
    report["linhas_importadas"] = int(len(out))
    report["equipamentos"] = sorted(out[COL_EQUIPMENT].unique().tolist())
    return out, variables, report
