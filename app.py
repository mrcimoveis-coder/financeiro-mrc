from __future__ import annotations

import io
import importlib
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

import finance_core as _finance_core

# O Streamlit Cloud pode manter o módulo em memória enquanto sincroniza um novo
# commit. Recarregar aqui evita que app.py novo tente usar uma versão anterior
# de finance_core durante a publicação.
_finance_core = importlib.reload(_finance_core)

from finance_core import (
    MESES,
    construction_payables,
    distributable_balance,
    format_brl,
    fx_balance_brl,
    is_advance_customer_payment_balance,
    is_caution_interest_reserve,
    is_customer_pass_through_balance,
    is_distribution_liability_balance,
    is_pending_construction_adjustment_balance,
    is_profit_withdrawal_nature,
    make_recurrence_rows,
    monthly_forecast,
    monthly_realized_history,
    monthly_work_summary,
    new_id,
    normalize_label,
    normalize_launches,
    normalize_withdrawals,
    normalize_works,
    open_launches,
    parse_money,
    projection,
    realization_tracking,
    safe_day,
    settlement_amount,
    suggest_next_year_forecast,
    variance,
    withdrawal_summary,
)


SHEET_ID = "1WaIP5FJpudjKvOXw0pQe7YfJlTPrISAmaBDZswuCsxM"
CAUCOES_SHEET_ID = "1OE3lN6bLUAemM_PyrsrVtN4BqMc-zrH1sCy5qzWGmrk"
MAIN_HEADERS = [
    "Mês", "Tipo de Operação", "Categoria", "Corretor / Envolvido", "Histórico",
    "Valor (R$)", "Status", "Observação", "ID", "Competência", "Vencimento",
    "Valor Previsto (R$)", "Valor Realizado (R$)", "Data Quitação", "Conta",
    "Natureza", "Série ID", "Criado Em", "Atualizado Em", "Moeda",
    "Valor na Moeda", "Cotação Utilizada", "Percentual Considerado", "Revisão ID",
]
BALANCE_HEADERS = ["Conta", "Valor"]
WORK_HEADERS = [
    "ID", "Competência", "Obra / Histórico", "Locador / Cliente",
    "Valor Cobrado (R$)", "Valor Recebido (R$)", "Prestador",
    "PIX do Prestador", "Custo Previsto (R$)", "Valor Pago (R$)",
    "Status", "Observação", "Criado Em", "Atualizado Em",
]
PARAM_HEADERS = ["Chave", "Valor", "Descrição", "Atualizado Em"]
QUOTE_HEADERS = ["Data", "Moeda", "Compra", "Venda", "Fonte", "Consultado Em"]
CLOSE_HEADERS = [
    "Competência", "Saldo Bancário", "Receitas Pendentes", "Despesas Pendentes",
    "Saldo Projetado", "Cauções", "Reserva", "Distribuível", "Fechado Em",
]
FORECAST_REVIEW_HEADERS = [
    "Revisão ID", "Ano Origem", "Ano Destino", "Chave Origem", "Decisão",
    "Tipo", "Categoria", "Lançamento", "Envolvido", "Conta", "Natureza",
    "Valor Sugerido (R$)", "Periodicidade", "Primeiro Vencimento",
    "Ocorrências", "Dia do Vencimento", "Observação", "Status",
    "Criado Em", "Atualizado Em",
]
GOAL_HEADERS = [
    "ID", "Ano", "Data da Reunião", "Meta", "Tipo de Apuração",
    "Filtro do Lançamento", "Valor da Meta (R$)", "Valor Manual Atingido (R$)",
    "Criado Em", "Atualizado Em",
]
WITHDRAWAL_HEADERS = [
    "Competência", "Pró-labore (R$)", "Retirada de Lucros (R$)",
    "Retirada Adicional (R$)", "Observação", "Atualizado Em",
]
CORRECTION_LOG_HEADERS = [
    "Corrigido Em", "Usuário", "Origem", "Linha", "ID", "Tipo",
    "Lançamento", "Antes", "Depois", "Motivo",
]
DELETED_LAUNCH_HEADERS = [
    "Excluído Em", "Usuário", "Origem", "Linha Original", "Motivo", *MAIN_HEADERS,
]
LOAN_HEADERS = ["ID", "Data", "Histórico", "Valor (R$)", "Criado Em", "Atualizado Em"]
PARTNER_SETTLEMENT_HEADERS = [
    "ID", "Competência", "Data", "Sócio", "Tipo", "Histórico", "Valor (R$)", "Criado Em", "Atualizado Em",
]

STABILIZED_RENT_GOAL_TYPE = "Renda mensal estabilizada (manual)"
MANUAL_GOAL_TYPES = {"Manual", STABILIZED_RENT_GOAL_TYPE}
NATURE_OPTIONS = [
    "Operacional",
    "Retirada de lucros",
    "Empréstimo a receber",
    "Investimento",
    "Reserva",
    "Outro",
]

DEFAULT_PARAMETERS = {
    "caucoes_protegidas": (0.0, "Total de cauções que não pode ser distribuído"),
    "reserva_mrc": (0.0, "Reserva mínima mantida pela MRC"),
    "percentual_socio_1": (50.0, "Percentual do primeiro sócio"),
    "percentual_socio_2": (50.0, "Percentual do segundo sócio"),
    "reserva_usd": (0.0, "Saldo da reserva mantido em dólar"),
    "percentual_usd": (95.0, "Percentual da reserva em dólar considerado no saldo"),
    "cotacao_manual_usd": (0.0, "Cotação manual; zero utiliza a PTAX de venda"),
    "ultima_cotacao_usd": (0.0, "Última cotação utilizada na reserva em dólar"),
}


st.set_page_config(page_title="Previsão Financeira | MRC Imóveis", page_icon="💰", layout="wide")

st.markdown(
    """
    <style>
    #MainMenu, footer {visibility:hidden}
    .block-container {padding-top:1.2rem; max-width:1450px}
    div[data-testid="stMetric"] {background:#fff; border:1px solid #e5e7eb; border-top:4px solid #c4001a; padding:14px; border-radius:10px; container-type:inline-size; min-width:0}
    div[data-testid="stMetric"] [data-testid="stMetricLabel"],
    div[data-testid="stMetric"] [data-testid="stMetricValue"],
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] p,
    div[data-testid="stMetric"] [data-testid="stMetricValue"] div {color:#172033 !important; opacity:1 !important}
    div[data-testid="stMetric"] [data-testid="stMetricValue"],
    div[data-testid="stMetric"] [data-testid="stMetricValue"] > div,
    div[data-testid="stMetric"] [data-testid="stMetricValue"] div,
    div[data-testid="stMetric"] [data-testid="stMetricValue"] p,
    div[data-testid="stMetric"] [data-testid="stMetricValue"] span {
        width:100% !important;
        max-width:none !important;
        min-width:0 !important;
        font-size:clamp(.95rem, 9cqi, 2rem) !important;
        line-height:1.2 !important;
        white-space:nowrap !important;
        overflow:visible !important;
        text-overflow:clip !important;
    }
    .annual-summary-grid {display:grid; grid-template-columns:repeat(5, minmax(0, 1fr)); gap:14px; margin:.35rem 0 .65rem}
    .annual-summary-card {background:#fff; border:1px solid #e5e7eb; border-top:4px solid #c4001a; padding:12px 14px; border-radius:10px; min-width:0}
    .annual-summary-label {color:#172033; font-size:.78rem; line-height:1.25; min-height:2rem; margin-bottom:.25rem}
    .annual-summary-value {color:#172033; font-size:clamp(1.05rem, 1.65vw, 1.55rem); line-height:1.2; white-space:nowrap; letter-spacing:-.02em}
    @media (max-width: 1050px) {
        .annual-summary-grid {grid-template-columns:repeat(2, minmax(0, 1fr))}
        .annual-summary-value {font-size:1.35rem}
    }
    @media (max-width: 768px) {
        div[data-testid="stMetric"] {min-height:104px; padding:12px}
        div[data-testid="stMetric"] [data-testid="stMetricValue"],
        div[data-testid="stMetric"] [data-testid="stMetricValue"] > div,
        div[data-testid="stMetric"] [data-testid="stMetricValue"] div,
        div[data-testid="stMetric"] [data-testid="stMetricValue"] p,
        div[data-testid="stMetric"] [data-testid="stMetricValue"] span {
            font-size:clamp(.95rem, 8cqi, 1.45rem) !important;
        }
        .annual-summary-grid {grid-template-columns:1fr; gap:10px}
        .annual-summary-label {min-height:0}
        .annual-summary-value {font-size:1.3rem}
    }
    .status-note {padding:.7rem 1rem; border-radius:8px; background:#f7f3fb; border-left:4px solid #8064a2}
    </style>
    """,
    unsafe_allow_html=True,
)


def secret_users() -> dict[str, str]:
    try:
        return {str(k).lower().strip(): str(v) for k, v in dict(st.secrets["usuarios_financeiro"]).items()}
    except Exception:
        return {}


def login() -> None:
    if st.session_state.get("autenticado_fin"):
        return
    users = secret_users()
    st.title("🔒 Acesso ao módulo financeiro")
    if not users:
        st.error("Os usuários do módulo ainda não foram configurados nos segredos do Streamlit.")
        st.caption("Crie a seção [usuarios_financeiro] nas configurações do aplicativo antes do primeiro acesso.")
        st.stop()
    with st.form("login"):
        user = st.text_input("Usuário").lower().strip()
        password = st.text_input("Senha", type="password")
        submit = st.form_submit_button("Entrar", type="primary", use_container_width=True)
    if submit:
        if users.get(user) == password:
            st.session_state.autenticado_fin = True
            st.session_state.usuario_fin = user
            st.rerun()
        st.error("Usuário ou senha incorretos.")
    st.stop()


def clean_editor_text(value: object, default: str = "") -> str:
    """Return clean text for optional cells edited in a Streamlit table."""
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if normalize_label(text) in {"", "none", "nan", "nat"}:
        return default
    return text


def clean_editor_date(value: object) -> date | None:
    """Convert an optional editor value to date without raising on blank cells."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    return parsed.date() if pd.notna(parsed) else None


@st.cache_resource
def spreadsheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    info = dict(st.secrets["gcp_service_account"])
    info["private_key"] = info.get("private_key", "").replace("\\n", "\n")
    credentials = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(credentials).open_by_key(SHEET_ID)


@st.cache_resource(show_spinner=False)
def worksheet(name: str, headers: list[str], rows: int = 1000):
    book = spreadsheet()
    try:
        ws = book.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=name, rows=rows, cols=max(20, len(headers) + 2))
    current = ws.row_values(1)
    if not current:
        ws.update("A1", [headers])
    else:
        missing = [header for header in headers if header not in current]
        if missing:
            ws.update_cell(1, len(current) + 1, missing[0])
            if len(missing) > 1:
                ws.update(
                    range_name=f"{gspread.utils.rowcol_to_a1(1, len(current) + 1)}:{gspread.utils.rowcol_to_a1(1, len(current) + len(missing))}",
                    values=[missing],
                )
    return ws


@st.cache_resource(show_spinner=False)
def main_sheet():
    ws = spreadsheet().sheet1
    current = ws.row_values(1)
    missing = [header for header in MAIN_HEADERS if header not in current]
    if not current:
        ws.update("A1", [MAIN_HEADERS])
    elif missing:
        start = len(current) + 1
        ws.update(
            range_name=f"{gspread.utils.rowcol_to_a1(1, start)}:{gspread.utils.rowcol_to_a1(1, start + len(missing) - 1)}",
            values=[missing],
        )
    return ws


def load_records(ws) -> list[dict]:
    cache = st.session_state.setdefault("_sheet_records_cache", {})
    cache_key = f"{spreadsheet().id}:{ws.id}"
    cached = cache.get(cache_key)
    if cached and time.monotonic() - cached["loaded_at"] < 20:
        return [dict(row) for row in cached["records"]]

    for attempt in range(5):
        try:
            records = ws.get_all_records(numericise_ignore=["all"])
            cache[cache_key] = {"loaded_at": time.monotonic(), "records": records}
            return [dict(row) for row in records]
        except gspread.exceptions.APIError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            error_text = str(exc).lower()
            temporary = status in {429, 500, 502, 503, 504} or any(
                term in error_text for term in ("quota", "resource_exhausted", "rate limit")
            )
            if not temporary:
                raise
            if attempt < 4:
                time.sleep(2 ** attempt)
    if cached:
        st.warning("O Google Sheets está respondendo lentamente. Exibindo a última leitura salva; tente novamente em alguns segundos.")
        return [dict(row) for row in cached["records"]]
    st.warning("O Google Sheets atingiu um limite temporário de consultas. Aguarde alguns segundos e recarregue a página.")
    st.stop()


def invalidate_records(ws) -> None:
    cache = st.session_state.get("_sheet_records_cache", {})
    cache.pop(f"{spreadsheet().id}:{ws.id}", None)


def append_dicts(ws, headers: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    ws.append_rows([[row.get(header, "") for header in headers] for row in rows], value_input_option="USER_ENTERED")
    invalidate_records(ws)


def update_row(ws, row_number: int, updates: dict) -> None:
    headers = ws.row_values(1)
    values = ws.row_values(row_number)
    values += [""] * (len(headers) - len(values))
    for key, value in updates.items():
        if key in headers:
            values[headers.index(key)] = value
    ws.update(
        range_name=f"A{row_number}:{gspread.utils.rowcol_to_a1(row_number, len(headers))}",
        values=[values],
        value_input_option="USER_ENTERED",
    )
    invalidate_records(ws)


def batch_update_rows(ws, changes: list[tuple[int, dict]]) -> None:
    if not changes:
        return
    headers = ws.row_values(1)
    records = load_records(ws)
    payload = []
    for row_number, updates in changes:
        record_index = int(row_number) - 2
        current = records[record_index] if 0 <= record_index < len(records) else {}
        values = [current.get(header, "") for header in headers]
        for key, value in updates.items():
            if key in headers:
                values[headers.index(key)] = value
        payload.append({
            "range": f"A{int(row_number)}:{gspread.utils.rowcol_to_a1(int(row_number), len(headers))}",
            "values": [values],
        })
    ws.batch_update(payload, value_input_option="USER_ENTERED")
    invalidate_records(ws)


def delete_sheet_rows(ws, row_numbers: list[int]) -> None:
    """Delete worksheet rows in descending contiguous groups so indexes stay valid."""
    rows = sorted({int(row) for row in row_numbers if int(row) >= 2}, reverse=True)
    if not rows:
        return
    groups: list[tuple[int, int]] = []
    high = low = rows[0]
    for row in rows[1:]:
        if row == low - 1:
            low = row
        else:
            groups.append((low, high))
            high = low = row
    groups.append((low, high))
    for start_row, end_row in groups:
        ws.delete_rows(start_row, end_row)
    invalidate_records(ws)


@st.cache_data(ttl=1800, show_spinner=False)
def ptax_sale(reference: date) -> tuple[float, date] | tuple[None, None]:
    for offset in range(0, 10):
        candidate = reference - timedelta(days=offset)
        formatted = candidate.strftime("%m-%d-%Y")
        endpoint = (
            "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
            "CotacaoDolarDia(dataCotacao=@dataCotacao)?"
            + urllib.parse.urlencode({"@dataCotacao": f"'{formatted}'", "$format": "json"})
        )
        try:
            with urllib.request.urlopen(endpoint, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            values = payload.get("value", [])
            if values:
                return float(values[-1]["cotacaoVenda"]), candidate
        except Exception:
            continue
    return None, None


def load_parameters(ws) -> dict[str, float]:
    records = load_records(ws)
    existing = {str(item.get("Chave", "")): parse_money(item.get("Valor")) for item in records}
    missing_rows = []
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    for key, (value, description) in DEFAULT_PARAMETERS.items():
        if key not in existing:
            existing[key] = value
            missing_rows.append({"Chave": key, "Valor": value, "Descrição": description, "Atualizado Em": now})
    append_dicts(ws, PARAM_HEADERS, missing_rows)
    return existing


def save_parameters(ws, values: dict[str, float]) -> None:
    records = load_records(ws)
    rows_by_key = {str(item.get("Chave", "")): index for index, item in enumerate(records, start=2)}
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    new_rows = []
    for key, value in values.items():
        description = DEFAULT_PARAMETERS.get(key, (0, key))[1]
        if key in rows_by_key:
            update_row(ws, rows_by_key[key], {"Valor": value, "Descrição": description, "Atualizado Em": now})
        else:
            new_rows.append({"Chave": key, "Valor": value, "Descrição": description, "Atualizado Em": now})
    append_dicts(ws, PARAM_HEADERS, new_rows)


@st.cache_data(ttl=300, show_spinner=False)
def caution_projected_balance(year: int) -> float:
    """Return the December projection for active deposits in the Cauções app."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    info = dict(st.secrets["gcp_service_account"])
    info["private_key"] = info.get("private_key", "").replace("\\n", "\n")
    credentials = Credentials.from_service_account_info(info, scopes=scopes)
    records = gspread.authorize(credentials).open_by_key(CAUCOES_SHEET_ID).sheet1.get_all_records(
        numericise_ignore=["all"]
    )
    exponent = max(0, int(year) - 2026)
    total = 0.0
    for record in records:
        if str(record.get("Status", "")).strip().upper() != "ATIVA":
            continue
        base = parse_money(record.get("Projeção Dez/26 (R$)", 0))
        rate_text = str(record.get("% Taxa Anual", "2")).replace("%", "").replace(",", ".").strip()
        try:
            rate = float(rate_text) / 100.0
        except (TypeError, ValueError):
            rate = 0.02
        total += round(base * ((1.0 + rate) ** exponent), 2)
    return round(total, 2)


def account_balances(ws) -> tuple[pd.DataFrame, float]:
    records = load_records(ws)
    frame = pd.DataFrame(records)
    if frame.empty:
        frame = pd.DataFrame(columns=BALANCE_HEADERS)
    for column in BALANCE_HEADERS:
        if column not in frame:
            frame[column] = ""
    frame["Valor Num"] = frame["Valor"].map(parse_money)
    actual = frame[~frame["Conta"].astype(str).str.lower().str.startswith("retirada_")]
    return frame, float(actual["Valor Num"].sum())


def ensure_balance_rows(ws) -> None:
    records = load_records(ws)
    existing = {normalize_label(record.get("Conta")) for record in records}
    defaults = ["Boletos pagos adiantados"]
    missing = [[label, 0] for label in defaults if normalize_label(label) not in existing]
    if missing:
        ws.append_rows(missing, value_input_option="USER_ENTERED")


def ensure_initial_work_rows(ws) -> None:
    if load_records(ws):
        return
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    initial = [
        ("Reparo Cruzeiro", 4800.0, 3200.0, 3200.0, "Concluída"),
        ("SQS 211 (Mauvi)", 1850.0, 1450.0, 725.0, "Parcial"),
        ("Reparo Anderson Cruzeiro", 1850.0, 1200.0, 600.0, "Parcial"),
    ]
    append_dicts(ws, WORK_HEADERS, [{
        "ID": new_id("OBR"),
        "Competência": "09/2026",
        "Obra / Histórico": description,
        "Locador / Cliente": "",
        "Valor Cobrado (R$)": format_brl(charged),
        "Valor Recebido (R$)": "",
        "Prestador": "Solange",
        "PIX do Prestador": "",
        "Custo Previsto (R$)": format_brl(cost),
        "Valor Pago (R$)": format_brl(paid),
        "Status": status,
        "Observação": "Preencher cliente e chave PIX do prestador.",
        "Criado Em": now,
        "Atualizado Em": now,
    } for description, charged, cost, paid, status in initial])


def ensure_initial_goals(ws) -> None:
    records = load_records(ws)
    existing = {
        (str(record.get("Ano") or "").strip(), normalize_label(record.get("Meta")))
        for record in records
    }
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    initial = [
        ("Faturamento", "Receitas realizadas no ano", "", 1_800_000.0),
        ("Aluguel Mensal", STABILIZED_RENT_GOAL_TYPE, "", 100_000.0),
    ]
    rows = []
    for goal_name, calculation_type, launch_filter, target in initial:
        if ("2026", normalize_label(goal_name)) in existing:
            continue
        rows.append({
            "ID": new_id("META"), "Ano": 2026, "Data da Reunião": "23/10/2025",
            "Meta": goal_name, "Tipo de Apuração": calculation_type,
            "Filtro do Lançamento": launch_filter, "Valor da Meta (R$)": format_brl(target),
            "Valor Manual Atingido (R$)": "", "Criado Em": now, "Atualizado Em": now,
        })
    append_dicts(ws, GOAL_HEADERS, rows)


def ensure_stabilized_rent_goal(ws) -> None:
    """Keep the monthly rent goal manual without changing its saved current value."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    changes = []
    for row_number, goal in enumerate(load_records(ws), start=2):
        if normalize_label(goal.get("Meta")) != "aluguel mensal":
            continue
        if str(goal.get("Tipo de Apuração") or "").strip() == STABILIZED_RENT_GOAL_TYPE:
            continue
        changes.append((row_number, {
            "Tipo de Apuração": STABILIZED_RENT_GOAL_TYPE,
            "Filtro do Lançamento": "",
            "Atualizado Em": now,
        }))
    batch_update_rows(ws, changes)


def standardize_monthly_rent_labels(ws, label_field: str) -> None:
    """Rename the former generic monthly revenue label without touching its values."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    changes = []
    for row_number, record in enumerate(load_records(ws), start=2):
        if normalize_label(record.get(label_field)) == "receita mensal":
            changes.append((row_number, {
                label_field: "Receita Mensal de Aluguel",
                "Atualizado Em": now,
            }))
    batch_update_rows(ws, changes)


def ensure_withdrawal_year(ws, year: int) -> None:
    records = load_records(ws)
    existing = {
        str(record.get("Competência") or "").strip()
        for record in records
    }
    profit_2026 = [44_000, 52_000, 50_000, 40_000, 44_000, 32_000, 26_000, 30_000, 32_000, 0, 0, 0]
    additional_2026 = [122_200, 37_000, 38_450, 1_250, 0, 26_800, 93_550, 27_800, 0, 0, 0, 0]
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    rows = []
    for month in range(1, 13):
        competence = f"{month:02d}/{int(year)}"
        if competence in existing:
            continue
        is_initial_2026 = int(year) == 2026
        rows.append({
            "Competência": competence,
            "Pró-labore (R$)": format_brl(28_000) if is_initial_2026 and month <= 9 else "",
            "Retirada de Lucros (R$)": format_brl(profit_2026[month - 1]) if is_initial_2026 and profit_2026[month - 1] else "",
            "Retirada Adicional (R$)": format_brl(additional_2026[month - 1]) if is_initial_2026 and additional_2026[month - 1] else "",
            "Observação": "Valores históricos informados pelo usuário." if is_initial_2026 and month <= 9 else "",
            "Atualizado Em": now,
        })
    append_dicts(ws, WITHDRAWAL_HEADERS, rows)


def sync_construction_balance(ws, amount: float) -> None:
    records = load_records(ws)
    for row_number, record in enumerate(records, start=2):
        if is_pending_construction_adjustment_balance(record.get("Conta")):
            if abs(parse_money(record.get("Valor")) - amount) > 0.005:
                update_row(ws, row_number, {"Conta": "Acertos de obras pendentes", "Valor": format_brl(amount)})
            return
    append_dicts(ws, BALANCE_HEADERS, [{"Conta": "Acertos de obras pendentes", "Valor": format_brl(amount)}])


def display_money_table(frame: pd.DataFrame, columns: list[str]) -> None:
    view = frame.copy()
    for column in columns:
        if column in view:
            view[column] = view[column].map(format_brl)
    st.dataframe(view, use_container_width=True, hide_index=True)


def loan_ledger(records: list[dict]) -> pd.DataFrame:
    """Return a chronological loan ledger with its running balance calculated from movements."""
    rows = []
    for sheet_row, record in enumerate(records, start=2):
        movement_date = clean_editor_date(record.get("Data"))
        rows.append({
            "sheet_row": sheet_row,
            "ID": str(record.get("ID") or ""),
            "Data": movement_date,
            "Histórico": clean_editor_text(record.get("Histórico")),
            "Valor": parse_money(record.get("Valor (R$)")),
        })
    frame = pd.DataFrame(rows, columns=["sheet_row", "ID", "Data", "Histórico", "Valor"])
    if frame.empty:
        frame["Saldo"] = pd.Series(dtype=float)
        return frame
    frame["_ordem"] = range(len(frame))
    frame = frame.sort_values(["Data", "_ordem"], na_position="last").drop(columns="_ordem")
    frame["Saldo"] = frame["Valor"].cumsum().round(2)
    return frame.reset_index(drop=True)


def partner_settlement_ledger(records: list[dict], competence: str | None = None) -> pd.DataFrame:
    """Keep personal partner adjustments separate from the corporate financial forecast."""
    rows = []
    for sheet_row, record in enumerate(records, start=2):
        row_competence = clean_editor_text(record.get("Competência"))
        if competence and row_competence != competence:
            continue
        movement_date = clean_editor_date(record.get("Data"))
        rows.append({
            "sheet_row": sheet_row,
            "ID": str(record.get("ID") or ""),
            "Competência": row_competence,
            "Data": movement_date,
            "Sócio": clean_editor_text(record.get("Sócio")),
            "Tipo": clean_editor_text(record.get("Tipo")),
            "Histórico": clean_editor_text(record.get("Histórico")),
            "Valor": parse_money(record.get("Valor (R$)")),
        })
    frame = pd.DataFrame(rows, columns=["sheet_row", "ID", "Competência", "Data", "Sócio", "Tipo", "Histórico", "Valor"])
    if frame.empty:
        frame["Saldo"] = pd.Series(dtype=float)
        return frame
    frame["_ordem"] = range(len(frame))
    frame = frame.sort_values(["Sócio", "Data", "_ordem"], na_position="last")
    frame["Saldo"] = frame.groupby("Sócio")["Valor"].cumsum().round(2)
    return frame.drop(columns="_ordem").reset_index(drop=True)


def ensure_initial_adjustment_rows(ws_marcos, ws_torre, ws_partners) -> None:
    """Create the three independent ledgers once, seeded with the balances supplied by MRC."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    if not load_records(ws_marcos):
        marcos_rows = [
            ("01/04/2026", "Empréstimo para Marcos Veloso", 20_000.00),
            ("12/05/2026", "Juros de 1%", 200.00),
            ("12/05/2026", "Pagamento parcial", -752.93),
            ("12/06/2026", "Juros de 1%", 194.47),
            ("12/06/2026", "Pagamento parcial", -871.77),
            ("12/07/2026", "Juros de 1%", 187.70),
            ("12/07/2026", "Pagamento parcial", -928.65),
            ("12/08/2026", "Juros de 1%", 180.29),
            ("12/08/2026", "Devolução parcial", -1_269.63),
            ("10/08/2026", "Devolução parcial - Oceania", -2_687.50),
            ("12/09/2026", "Juros de 1%", 142.52),
            ("12/09/2026", "Devolução parcial", -142.52),
        ]
        append_dicts(ws_marcos, LOAN_HEADERS, [{
            "ID": new_id("EMP_MV"), "Data": item_date, "Histórico": description,
            "Valor (R$)": format_brl(amount), "Criado Em": now, "Atualizado Em": now,
        } for item_date, description, amount in marcos_rows])
    if not load_records(ws_torre):
        torre_rows = [
            ("10/04/2026", "Empréstimo para Torre Forte", 270_000.00),
            ("17/06/2026", "Devolução parcial", -10_000.00),
            ("22/06/2026", "Devolução parcial", -10_000.00),
            ("29/06/2026", "Devolução parcial", -13_000.00),
            ("03/07/2026", "Devolução parcial", -30_000.00),
            ("29/07/2026", "Devolução parcial", -5_500.00),
            ("10/08/2026", "Devolução parcial", -20_000.00),
        ]
        append_dicts(ws_torre, LOAN_HEADERS, [{
            "ID": new_id("EMP_TF"), "Data": item_date, "Histórico": description,
            "Valor (R$)": format_brl(amount), "Criado Em": now, "Atualizado Em": now,
        } for item_date, description, amount in torre_rows])
    if not load_records(ws_partners):
        partner_rows = [
            ("09/2026", "01/09/2026", "Marcelo", "Despesa", "Diarista MRC", 550.00),
            ("09/2026", "01/09/2026", "Marcelo", "Despesa", "CEB - MRC", 200.00),
            ("09/2026", "01/09/2026", "Marcelo", "Despesa", "Meta Verified (WhatsApp)", 54.90),
            ("09/2026", "01/09/2026", "Marcelo", "Despesa", "Café MRC", 48.00),
            ("09/2026", "01/09/2026", "Marcelo", "Despesa", "Reparo Janela CLSW 302", 220.00),
            ("09/2026", "01/09/2026", "Marcelo", "Crédito", "Recebimento Obra SQS 112", -850.00),
            ("09/2026", "01/09/2026", "Marcio", "Despesa", "Drone - Parcela 05/10", 219.90),
            ("09/2026", "01/09/2026", "Marcio", "Crédito", "Renda Seguro (particular)", -350.00),
        ]
        append_dicts(ws_partners, PARTNER_SETTLEMENT_HEADERS, [{
            "ID": new_id("ACERTO"), "Competência": competence, "Data": item_date,
            "Sócio": partner, "Tipo": kind, "Histórico": description,
            "Valor (R$)": format_brl(amount), "Criado Em": now, "Atualizado Em": now,
        } for competence, item_date, partner, kind, description, amount in partner_rows])


def render_loan_adjustment(title: str, ws, key: str, allow_interest: bool = False) -> None:
    ledger = loan_ledger(load_records(ws))
    balance = float(ledger["Saldo"].iloc[-1]) if not ledger.empty else 0.0
    st.subheader(title)
    st.metric("Saldo atualizado", format_brl(balance))
    st.caption("Valores positivos aumentam o saldo; valores negativos registram pagamentos ou devoluções. O saldo é calculado automaticamente e não altera o financeiro principal.")

    if ledger.empty:
        st.info("Ainda não há movimentos neste controle.")
    else:
        editor = st.data_editor(
            ledger[["sheet_row", "ID", "Data", "Histórico", "Valor", "Saldo"]],
            use_container_width=True,
            hide_index=True,
            disabled=["sheet_row", "ID", "Saldo"],
            column_config={
                "sheet_row": None,
                "ID": None,
                "Data": st.column_config.DateColumn(format="DD/MM/YYYY", required=True),
                "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", required=True),
                "Saldo": st.column_config.NumberColumn("Saldo calculado", format="R$ %.2f"),
            },
            key=f"{key}_editor",
        )
        if st.button("Salvar alterações da tabela", key=f"{key}_save", type="primary"):
            now = datetime.now().strftime("%d/%m/%Y %H:%M")
            for _, item in editor.iterrows():
                movement_date = clean_editor_date(item["Data"])
                update_row(ws, int(item["sheet_row"]), {
                    "Data": movement_date.strftime("%d/%m/%Y") if movement_date else "",
                    "Histórico": clean_editor_text(item["Histórico"]),
                    "Valor (R$)": format_brl(float(item["Valor"])),
                    "Atualizado Em": now,
                })
            st.success("Tabela atualizada.")
            st.rerun()

    with st.expander("Adicionar movimento", expanded=ledger.empty):
        with st.form(f"{key}_new_movement", clear_on_submit=True):
            c1, c2 = st.columns([1, 2])
            movement_date = c1.date_input("Data", value=today, format="DD/MM/YYYY", key=f"{key}_date")
            description = c2.text_input("Histórico", key=f"{key}_history")
            c3, c4 = st.columns(2)
            kind = c3.selectbox("Movimento", ["Novo empréstimo / acréscimo", "Pagamento / devolução"], key=f"{key}_kind")
            amount = c4.number_input("Valor", min_value=0.0, step=100.0, key=f"{key}_amount")
            save_movement = st.form_submit_button("Registrar movimento", type="primary")
        if save_movement:
            if not description.strip() or amount <= 0:
                st.error("Informe o histórico e um valor maior que zero.")
            else:
                signed_amount = amount if kind == "Novo empréstimo / acréscimo" else -amount
                now = datetime.now().strftime("%d/%m/%Y %H:%M")
                append_dicts(ws, LOAN_HEADERS, [{
                    "ID": new_id("MOV"), "Data": movement_date.strftime("%d/%m/%Y"),
                    "Histórico": description.strip(), "Valor (R$)": format_brl(signed_amount),
                    "Criado Em": now, "Atualizado Em": now,
                }])
                st.success("Movimento registrado.")
                st.rerun()

    if allow_interest:
        with st.expander("Lançar juros de 1% do mês"):
            st.caption(f"O cálculo será de 1% sobre o saldo atual: {format_brl(max(balance, 0) * 0.01)}.")
            with st.form(f"{key}_interest"):
                interest_date = st.date_input("Data dos juros", value=today, format="DD/MM/YYYY", key=f"{key}_interest_date")
                add_interest = st.form_submit_button("Adicionar juros de 1%")
            if add_interest:
                if balance <= 0:
                    st.warning("Não há saldo positivo para aplicar juros.")
                else:
                    now = datetime.now().strftime("%d/%m/%Y %H:%M")
                    append_dicts(ws, LOAN_HEADERS, [{
                        "ID": new_id("JUROS"), "Data": interest_date.strftime("%d/%m/%Y"),
                        "Histórico": "Juros de 1%", "Valor (R$)": format_brl(round(balance * 0.01, 2)),
                        "Criado Em": now, "Atualizado Em": now,
                    }])
                    st.success("Juros lançados.")
                    st.rerun()


def achieved_goal_value(goal: dict, launches_df: pd.DataFrame, year: int, reference: date) -> float:
    calculation_type = str(goal.get("Tipo de Apuração") or "Manual")
    if calculation_type in MANUAL_GOAL_TYPES:
        return parse_money(goal.get("Valor Manual Atingido (R$)"))
    if launches_df.empty:
        return 0.0
    selected = launches_df[
        launches_df["competencia"].notna()
        & (launches_df["competencia"].dt.year == year)
        & (launches_df["tipo"] == "Receita")
    ].copy()
    launch_filter = normalize_label(goal.get("Filtro do Lançamento"))
    if launch_filter:
        selected = selected[selected["historico"].map(normalize_label).str.contains(launch_filter, regex=False)]
    if calculation_type == "Receitas realizadas no mês":
        if year > reference.year:
            return 0.0
        month = reference.month if year == reference.year else 12
        selected = selected[selected["competencia"].dt.month == month]
    return float(selected["realizado"].sum())


login()

try:
    ws_history = main_sheet()
    ws_forecast = worksheet("Forecast", MAIN_HEADERS, 2000)
    ws_balances = worksheet("Saldos_Manuais", BALANCE_HEADERS, 100)
    ws_parameters = worksheet("Parametros", PARAM_HEADERS, 100)
    ws_quotes = worksheet("Cotacoes", QUOTE_HEADERS, 500)
    ws_closings = worksheet("Fechamentos", CLOSE_HEADERS, 500)
    ws_recurrences = worksheet(
        "Recorrencias",
        ["Série ID", "Descrição", "Tipo", "Categoria", "Início", "Ocorrências", "Intervalo em meses", "Valor", "Criado Em"],
        500,
    )
    ws_works = worksheet("Obras", WORK_HEADERS, 1000)
    ws_forecast_review = worksheet("Revisao_Forecast", FORECAST_REVIEW_HEADERS, 2000)
    ws_goals = worksheet("Metas_Anuais", GOAL_HEADERS, 500)
    ws_withdrawals = worksheet("Retiradas_Socios", WITHDRAWAL_HEADERS, 1000)
    ws_loan_marcos = worksheet("Emprestimo_MRC_Marcos", LOAN_HEADERS, 500)
    ws_loan_torre = worksheet("Emprestimo_MRC_Torre_Forte", LOAN_HEADERS, 500)
    ws_partner_settlements = worksheet("Acertos_Socios", PARTNER_SETTLEMENT_HEADERS, 1000)
    ws_correction_log = worksheet("Log_Correcoes", CORRECTION_LOG_HEADERS, 1000)
    ws_deleted_launches = worksheet("Lancamentos_Excluidos", DELETED_LAUNCH_HEADERS, 1000)
except Exception as exc:
    st.error(f"Não foi possível abrir a base Financeiro_MRC: {exc}")
    st.stop()

ensure_initial_goals(ws_goals)
ensure_stabilized_rent_goal(ws_goals)
standardize_monthly_rent_labels(ws_history, "Histórico")
standardize_monthly_rent_labels(ws_forecast, "Histórico")
standardize_monthly_rent_labels(ws_forecast_review, "Lançamento")
standardize_monthly_rent_labels(ws_recurrences, "Descrição")

records = load_records(ws_forecast)
launches = normalize_launches(records)
history_launches = normalize_launches(load_records(ws_history))
launches["origem"] = "Forecast"
history_launches["origem"] = "Histórico"
ensure_balance_rows(ws_balances)
ensure_initial_work_rows(ws_works)
ensure_withdrawal_year(ws_withdrawals, 2026)
ensure_initial_adjustment_rows(ws_loan_marcos, ws_loan_torre, ws_partner_settlements)
works = normalize_works(load_records(ws_works))
withdrawals = normalize_withdrawals(load_records(ws_withdrawals))
works_payable = construction_payables(works)
sync_construction_balance(ws_balances, works_payable)
balances_df, brl_balance = account_balances(ws_balances)
parameters = load_parameters(ws_parameters)
today = date.today()
interest_reserve_signed = float(
    balances_df.loc[
        balances_df["Conta"].map(is_caution_interest_reserve),
        "Valor Num",
    ].sum()
) if not balances_df.empty else 0.0
interest_reserve = abs(interest_reserve_signed)
brl_balance -= interest_reserve_signed
stored_distribution_liabilities = float(
    balances_df.loc[
        balances_df["Conta"].map(is_distribution_liability_balance),
        "Valor Num",
    ].sum()
) if not balances_df.empty else 0.0
stored_works_payable = float(
    balances_df.loc[balances_df["Conta"].map(is_pending_construction_adjustment_balance), "Valor Num"].sum()
) if not balances_df.empty else 0.0
brl_balance -= stored_distribution_liabilities
distribution_liabilities = stored_distribution_liabilities - stored_works_payable + works_payable
automatic_quote, automatic_quote_date = ptax_sale(today)
saved_quote = float(parameters["ultima_cotacao_usd"])
manual_quote = float(parameters["cotacao_manual_usd"])
used_usd_quote = manual_quote or automatic_quote or saved_quote
usd_balance_brl = fx_balance_brl(
    parameters["reserva_usd"],
    used_usd_quote,
    parameters["percentual_usd"],
)
bank_balance = brl_balance + usd_balance_brl

with st.sidebar:
    st.image("https://raw.githubusercontent.com/mrcimoveis-coder/portal-intranet/main/logo.jpeg", width=220)
    st.caption(f"Usuário: {st.session_state.get('usuario_fin', '')}")
    available_years = sorted({
        2026,
        *range(today.year, today.year + 6),
        *([int(y) for y in launches["competencia"].dropna().dt.year.unique()] if not launches.empty else []),
    })
    selected_year = st.selectbox("Ano do forecast", available_years, index=available_years.index(today.year) if today.year in available_years else 0)
    if st.button("Sair"):
        st.session_state.autenticado_fin = False
        st.rerun()

st.title("💰 Previsão financeira — MRC Imóveis")
st.caption("O saldo bancário representa o que já aconteceu. Somente receitas e despesas ainda abertas alteram a projeção futura.")

tab_summary, tab_pending, tab_launch, tab_forecast, tab_works, tab_withdrawals, tab_balances, tab_history, tab_adjustments, tab_settings = st.tabs(
    ["Resumo", "Pendências", "Novo lançamento", "Forecast", "Obras", "Retiradas", "Saldos", "Histórico", "Acertos", "Configurações"]
)

monthly = monthly_forecast(launches, selected_year)
is_current_year = selected_year == today.year
projection_base = bank_balance if is_current_year else 0.0
projection_date = today if is_current_year else date(selected_year, 1, 1)
projected = projection(monthly, projection_base, projection_date)
try:
    synced_caution = caution_projected_balance(selected_year)
    caution_sync_error = None
except Exception as exc:
    synced_caution = float(parameters["caucoes_protegidas"])
    caution_sync_error = str(exc)

if is_current_year and caution_sync_error is None and abs(float(parameters["caucoes_protegidas"]) - synced_caution) > 0.005:
    save_parameters(ws_parameters, {"caucoes_protegidas": synced_caution})
    parameters["caucoes_protegidas"] = synced_caution
open_df = open_launches(launches)
if not open_df.empty:
    year_open = open_df[open_df["competencia"].dt.year == selected_year]
    cutoff = pd.Timestamp(today.year, today.month, 1) if is_current_year else pd.Timestamp(selected_year, 1, 1)
    future_open = year_open[year_open["competencia"] >= cutoff]
else:
    future_open = open_df
pending_income = float(future_open.loc[future_open["tipo"] == "Receita", "pendente"].sum()) if not future_open.empty else 0.0
if not future_open.empty:
    future_withdrawals = future_open["natureza"].map(is_profit_withdrawal_nature)
    pending_expense = float(
        future_open.loc[(future_open["tipo"] == "Despesa") & ~future_withdrawals, "pendente"].sum()
    )
    pending_withdrawals = float(
        future_open.loc[(future_open["tipo"] == "Despesa") & future_withdrawals, "pendente"].sum()
    )
else:
    pending_expense = 0.0
    pending_withdrawals = 0.0
year_end = float(projected.iloc[-1]["saldo_projetado"]) if not projected.empty else projection_base
protected = (synced_caution + parameters["reserva_mrc"] + interest_reserve) if is_current_year else 0.0
active_liabilities = distribution_liabilities if is_current_year else 0.0
distributable = distributable_balance(year_end, protected, active_liabilities)
combined_history = pd.concat([history_launches, launches], ignore_index=True) if not history_launches.empty else launches
withdrawal_month_limit = today.month if selected_year == today.year else (12 if selected_year < today.year else 0)
withdrawal_totals = withdrawal_summary(withdrawals, selected_year, withdrawal_month_limit, partner_count=2)

with tab_summary:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Saldos atualizados" if is_current_year else "Saldo base do forecast", format_brl(projection_base))
    c2.metric("Receitas pendentes", format_brl(pending_income))
    c3.metric("Despesas pendentes", format_brl(pending_expense))
    c4.metric("Retiradas pendentes", format_brl(pending_withdrawals))
    c5.metric("Sobra / falta projetada", format_brl(distributable))
    if not is_current_year:
        st.info(
            f"{selected_year} está separado do ano corrente. O saldo base permanece zerado até {selected_year} "
            "se tornar o ano atual; lançamentos desse ano não alteram os cálculos do ano corrente."
        )

    goal_records = [
        goal for goal in load_records(ws_goals)
        if str(goal.get("Ano") or "").strip() == str(selected_year)
    ]
    st.subheader(f"Metas de {selected_year}")
    if not goal_records:
        st.info("Ainda não há metas cadastradas para este ano. Cadastre-as na aba Configurações.")
    else:
        meeting_dates = sorted({str(goal.get("Data da Reunião") or "").strip() for goal in goal_records if goal.get("Data da Reunião")})
        if meeting_dates:
            st.caption("Definidas na reunião de " + ", ".join(meeting_dates))
        goal_view = []
        for goal in goal_records:
            target = parse_money(goal.get("Valor da Meta (R$)"))
            achieved = achieved_goal_value(goal, combined_history, selected_year, today)
            calculation_type = str(goal.get("Tipo de Apuração") or "Manual")
            goal_view.append({
                "Meta": str(goal.get("Meta") or ""),
                "Período": "Mensal" if calculation_type in {
                    "Receitas realizadas no mês", STABILIZED_RENT_GOAL_TYPE,
                } else "Anual",
                "Valor da meta": target,
                "Atingido": achieved,
                "Falta atingir": max(target - achieved, 0.0),
                "% atingido": (achieved / target * 100.0) if target > 0 else 0.0,
            })
        goal_frame = pd.DataFrame(goal_view)
        goal_display = goal_frame.copy()
        for money_column in ["Valor da meta", "Atingido", "Falta atingir"]:
            goal_display[money_column] = goal_display[money_column].map(format_brl)
        st.dataframe(
            goal_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "% atingido": st.column_config.ProgressColumn(min_value=0.0, max_value=100.0, format="%.1f%%"),
            },
        )

    st.subheader(f"Retiradas dos sócios em {selected_year}")
    if withdrawal_month_limit == 0:
        st.info("O acompanhamento das retiradas começará quando este ano se tornar o ano corrente.")
    else:
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Pró-labore", format_brl(withdrawal_totals["pro_labore"]))
        r2.metric("Retirada de lucros", format_brl(withdrawal_totals["lucros"]))
        r3.metric("Retiradas adicionais", format_brl(withdrawal_totals["adicional"]))
        r4.metric("Total retirado", format_brl(withdrawal_totals["total"]))
        r5, r6 = st.columns(2)
        r5.metric("Média mensal total", format_brl(withdrawal_totals["media_mensal"]))
        r6.metric("Média por sócio / mês", format_brl(withdrawal_totals["media_socio_mes"]))
        st.caption(
            f"Cálculo até {MESES[int(withdrawal_totals['meses'])].title()}: "
            f"{int(withdrawal_totals['meses'])} mês(es) e 2 sócios. "
            "Esses valores são informativos e não reduzem novamente o saldo bancário."
        )

    st.subheader("Receitas e despesas realizadas até o momento")
    current_month = pd.Timestamp(today.year, today.month, 1)
    quick_history = monthly_realized_history(combined_history, selected_year)
    if selected_year == today.year:
        quick_history = quick_history[quick_history["competencia"] <= current_month]
    elif selected_year > today.year:
        quick_history = quick_history.iloc[0:0]
    quick_history_view = quick_history[[
        "mes", "receitas_realizadas", "despesas_realizadas", "resultado_realizado"
    ]].rename(columns={
        "mes": "Mês",
        "receitas_realizadas": "Receitas realizadas",
        "despesas_realizadas": "Despesas realizadas",
        "resultado_realizado": "Resultado realizado",
    })
    if quick_history_view.empty:
        st.info("Ainda não existem valores realizados neste ano.")
    else:
        total_realized = pd.DataFrame([{
            "Mês": "TOTAL REALIZADO",
            "Receitas realizadas": quick_history_view["Receitas realizadas"].sum(),
            "Despesas realizadas": quick_history_view["Despesas realizadas"].sum(),
            "Resultado realizado": quick_history_view["Resultado realizado"].sum(),
        }])
        quick_history_view = pd.concat([quick_history_view, total_realized], ignore_index=True)
        quick_history_display = quick_history_view.copy()
        for money_column in ["Receitas realizadas", "Despesas realizadas", "Resultado realizado"]:
            quick_history_display[money_column] = quick_history_display[money_column].map(format_brl)
        st.caption("Clique em um mês para ver os lançamentos que formam os valores realizados.")
        month_selection = st.dataframe(
            quick_history_display,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"summary_realized_month_{selected_year}",
        )
        selected_rows = month_selection.selection.rows
        if selected_rows:
            selected_label = str(quick_history_view.iloc[selected_rows[0]]["Mês"])
            if selected_label != "TOTAL REALIZADO":
                selected_month = next(
                    month_number for month_number, month_name in MESES.items()
                    if month_name == selected_label
                )
                realized_details = realization_tracking(combined_history)
                realized_details = realized_details[
                    realized_details["competencia"].notna()
                    & (realized_details["competencia"].dt.year == selected_year)
                    & (realized_details["competencia"].dt.month == selected_month)
                    & (realized_details["realizado"] > 0)
                ].copy()
                st.subheader(f"Detalhamento realizado de {selected_label.title()}/{selected_year}")
                if realized_details.empty:
                    st.info("Não há lançamentos detalhados disponíveis para este mês.")
                else:
                    withdrawal_mask = realized_details["natureza"].map(is_profit_withdrawal_nature)
                    detail_groups = [
                        ("Receitas", realized_details[realized_details["tipo"] == "Receita"]),
                        (
                            "Despesas operacionais",
                            realized_details[(realized_details["tipo"] == "Despesa") & ~withdrawal_mask],
                        ),
                        (
                            "Retiradas de lucros",
                            realized_details[(realized_details["tipo"] == "Despesa") & withdrawal_mask],
                        ),
                    ]
                    for group_title, group_frame in detail_groups:
                        if group_frame.empty:
                            continue
                        st.markdown(f"**{group_title} — {format_brl(float(group_frame['realizado'].sum()))}**")
                        detail_view = group_frame[[
                            "historico", "categoria", "previsto", "realizado", "status", "natureza"
                        ]].rename(columns={
                            "historico": "Lançamento",
                            "categoria": "Categoria",
                            "previsto": "Previsto",
                            "realizado": "Realizado",
                            "status": "Situação",
                            "natureza": "Natureza",
                        }).sort_values("Lançamento", key=lambda column: column.map(normalize_label))
                        display_money_table(detail_view, ["Previsto", "Realizado"])
    st.caption("O detalhamento completo continua disponível na aba Histórico.")

    st.markdown('<div class="status-note">Ao quitar um lançamento, ele deixa de afetar a projeção. O valor realizado fica apenas no histórico, pois o débito ou crédito já estará refletido no saldo bancário atualizado.</div>', unsafe_allow_html=True)
    st.subheader(f"Valores que ainda faltam em {selected_year}")
    remaining_view = projected[projected["aplicavel"]][
        ["mes", "receitas", "despesas", "retiradas", "movimento_caixa"]
    ].rename(
        columns={
            "mes": "Mês",
            "receitas": "Receitas a receber",
            "despesas": "Despesas a pagar",
            "retiradas": "Retiradas de lucros",
            "movimento_caixa": "Movimento no caixa",
        }
    )
    if remaining_view.empty:
        st.info("Não existem meses futuros para este ano.")
    else:
        total_remaining = pd.DataFrame([{
            "Mês": "TOTAL PENDENTE",
            "Receitas a receber": remaining_view["Receitas a receber"].sum(),
            "Despesas a pagar": remaining_view["Despesas a pagar"].sum(),
            "Retiradas de lucros": remaining_view["Retiradas de lucros"].sum(),
            "Movimento no caixa": remaining_view["Movimento no caixa"].sum(),
        }])
        remaining_view = pd.concat([remaining_view, total_remaining], ignore_index=True)
        display_money_table(
            remaining_view,
            ["Receitas a receber", "Despesas a pagar", "Retiradas de lucros", "Movimento no caixa"],
        )

with tab_pending:
    st.subheader("Lançamentos do mês")
    st.caption(
        "Informe o total pago ou recebido até agora. A projeção considera somente o saldo que ainda falta. "
        "Use Encerrar quando o lançamento terminou com valor diferente do previsto."
    )
    if open_df.empty:
        st.success("Não há lançamentos pendentes.")
    else:
        f1, f2 = st.columns(2)
        default_month = today.month if selected_year == today.year else 1
        month_filter = f1.selectbox(
            "Mês",
            list(MESES),
            index=default_month - 1,
            format_func=lambda item: MESES[item],
            key="pending_month",
        )
        type_filter = f2.selectbox("Tipo", ["Todos", "Receita", "Despesa"], key="pending_type")
        filtered = open_df[
            (open_df["competencia"].dt.year == selected_year)
            & (open_df["competencia"].dt.month == month_filter)
        ].copy()
        if type_filter != "Todos":
            filtered = filtered[filtered["tipo"] == type_filter]
        if filtered.empty:
            st.info("Nenhum lançamento aberto neste mês.")
        else:
            filtered = filtered.sort_values(["vencimento", "tipo", "historico"]).reset_index(drop=True)
            editor_source = pd.DataFrame({
                "Encerrar": False,
                "Vencimento": filtered["vencimento"].dt.strftime("%d/%m/%Y"),
                "Tipo": filtered["tipo"],
                "Lançamento": filtered["historico"],
                "Situação": filtered["status"],
                "Previsto": filtered["previsto"].astype(float),
                "Pago / recebido acumulado": filtered["realizado"].astype(float),
                "A pagar / receber": filtered["pendente"].astype(float),
                "sheet_row": filtered["sheet_row"].astype(int),
                "serie_id": filtered["serie_id"],
                "competencia": filtered["competencia"],
            })
            edited = st.data_editor(
                editor_source,
                use_container_width=True,
                hide_index=True,
                disabled=["Vencimento", "Tipo", "Lançamento", "Situação", "A pagar / receber", "sheet_row", "serie_id", "competencia"],
                column_config={
                    "Encerrar": st.column_config.CheckboxColumn("Encerrar"),
                    "Previsto": st.column_config.NumberColumn("Valor previsto", min_value=0.0, format="R$ %.2f"),
                    "Pago / recebido acumulado": st.column_config.NumberColumn(
                        "Pago / recebido acumulado", min_value=0.0, format="R$ %.2f"
                    ),
                    "A pagar / receber": st.column_config.NumberColumn("A pagar / receber", format="R$ %.2f"),
                    "sheet_row": None,
                    "serie_id": None,
                    "competencia": None,
                },
                key=f"month_editor_{selected_year}_{month_filter}",
            )
            propagate = st.checkbox("Aplicar mudanças no valor previsto também aos meses seguintes da mesma série")
            if st.button("Salvar alterações do mês", type="primary"):
                changed = 0
                settled = 0
                partial = 0
                for index, edited_row in edited.iterrows():
                    original = editor_source.iloc[index]
                    updates = {}
                    planned = float(edited_row["Previsto"])
                    close_requested = bool(edited_row["Encerrar"])
                    actual = settlement_amount(
                        planned,
                        float(edited_row["Pago / recebido acumulado"]),
                        close_requested,
                    )
                    planned_changed = abs(planned - float(original["Previsto"])) > 0.005
                    actual_changed = abs(actual - float(original["Pago / recebido acumulado"])) > 0.005
                    if planned_changed:
                        updates.update({
                            "Valor (R$)": format_brl(planned),
                            "Valor Previsto (R$)": format_brl(planned),
                        })
                        changed += 1
                        if propagate and str(edited_row["serie_id"]).strip():
                            later = open_df[
                                (open_df["serie_id"] == edited_row["serie_id"])
                                & (open_df["competencia"] > edited_row["competencia"])
                            ]
                            for _, later_row in later.iterrows():
                                update_row(ws_forecast, int(later_row["sheet_row"]), {
                                    "Valor (R$)": format_brl(planned),
                                    "Valor Previsto (R$)": format_brl(planned),
                                    "Atualizado Em": datetime.now().strftime("%d/%m/%Y %H:%M"),
                                })
                    close_launch = close_requested or (planned > 0 and actual >= planned)
                    if close_launch:
                        updates.update({
                            "Status": "Recebido" if edited_row["Tipo"] == "Receita" else "Pago",
                            "Valor Realizado (R$)": format_brl(actual),
                            "Data Quitação": today.strftime("%d/%m/%Y"),
                        })
                        settled += 1
                    elif actual > 0 and actual_changed:
                        updates.update({
                            "Status": "Parcial",
                            "Valor Realizado (R$)": format_brl(actual),
                            "Data Quitação": "",
                        })
                        if actual_changed:
                            partial += 1
                    elif actual_changed:
                        updates.update({
                            "Status": "Pendente",
                            "Valor Realizado (R$)": "",
                            "Data Quitação": "",
                        })
                    if updates:
                        updates["Atualizado Em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                        update_row(ws_forecast, int(edited_row["sheet_row"]), updates)
                st.success(
                    f"Alterações salvas: {changed} previsto(s) ajustado(s), "
                    f"{partial} parcial(is) e {settled} encerrado(s)."
                )
                if partial or settled:
                    st.warning("Confirme que os valores realizados já estão refletidos nos saldos reais das contas.")
                st.rerun()

with tab_launch:
    st.subheader("Cadastrar receita ou despesa")
    with st.form("new_launch", clear_on_submit=True):
        a, b, c = st.columns(3)
        launch_type = a.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        description = b.text_input("Descrição")
        category = c.text_input("Categoria", value="OUTRO")
        d, e, f = st.columns(3)
        due = d.date_input("Vencimento", value=today, format="DD/MM/YYYY")
        currency = e.selectbox("Moeda", ["BRL", "USD"])
        amount = f.number_input("Valor previsto", min_value=0.0, step=100.0)
        g, h, i = st.columns(3)
        nature = g.selectbox("Natureza", NATURE_OPTIONS)
        involved = h.text_input("Envolvido")
        account = i.text_input("Conta")
        launch_state = st.radio(
            "Situação do lançamento",
            ["Enviar para pendências", "Já pago / recebido"],
            horizontal=True,
            help=(
                "Use 'Já pago / recebido' quando o valor já estiver refletido no saldo bancário. "
                "O lançamento ficará no histórico e não entrará nas pendências."
            ),
        )
        notes = st.text_area("Observações")
        submit_launch = st.form_submit_button("Salvar lançamento", type="primary")
    if submit_launch:
        if not description or amount <= 0:
            st.error("Informe a descrição e um valor maior que zero.")
        else:
            quote, quote_date = ptax_sale(today)
            percent = parameters["percentual_usd"]
            manual_quote = parameters["cotacao_manual_usd"]
            used_quote = manual_quote or quote or 0.0
            planned_brl = amount if currency == "BRL" else amount * used_quote * percent / 100.0
            now = datetime.now().strftime("%d/%m/%Y %H:%M")
            already_realized = launch_state == "Já pago / recebido"
            launch_status = (
                "Recebido" if launch_type == "Receita" else "Pago"
            ) if already_realized else "Pendente"
            row = {
                "Mês": MESES[due.month], "Tipo de Operação": launch_type, "Categoria": category,
                "Corretor / Envolvido": involved, "Histórico": description, "Valor (R$)": format_brl(planned_brl),
                "Status": launch_status, "Observação": notes, "ID": new_id(), "Competência": due.strftime("%m/%Y"),
                "Vencimento": due.strftime("%d/%m/%Y"), "Valor Previsto (R$)": format_brl(planned_brl),
                "Valor Realizado (R$)": format_brl(planned_brl) if already_realized else "",
                "Data Quitação": today.strftime("%d/%m/%Y") if already_realized else "",
                "Conta": account, "Natureza": nature,
                "Série ID": "", "Criado Em": now, "Atualizado Em": now, "Moeda": currency,
                "Valor na Moeda": amount if currency == "USD" else "", "Cotação Utilizada": used_quote if currency == "USD" else "",
                "Percentual Considerado": percent if currency == "USD" else 100,
            }
            append_dicts(ws_forecast, MAIN_HEADERS, [row])
            if currency == "USD" and quote:
                append_dicts(ws_quotes, QUOTE_HEADERS, [{"Data": quote_date.strftime("%d/%m/%Y"), "Moeda": "USD", "Compra": "", "Venda": quote, "Fonte": "BCB PTAX", "Consultado Em": now}])
            if already_realized:
                st.success("Lançamento salvo como já realizado. Ele está no histórico e não foi enviado para as pendências.")
            else:
                st.success("Lançamento salvo e enviado para as pendências.")

with tab_forecast:
    review_source_year = selected_year
    review_target_year = selected_year + 1
    st.subheader(f"Preparar forecast de {review_target_year}")
    st.caption(
        f"O sistema analisa {review_source_year} e cria sugestões para sua conferência. "
        f"Nada entra em {review_target_year} antes da sua aprovação e esse forecast não altera {review_source_year}."
    )
    if st.button(f"Gerar sugestões para {review_target_year}", type="primary"):
        suggestions = suggest_next_year_forecast(combined_history, review_source_year, review_target_year)
        existing_reviews = load_records(ws_forecast_review)
        existing_keys = {
            str(row.get("Chave Origem") or "").strip()
            for row in existing_reviews
            if str(row.get("Ano Destino") or "").strip() == str(review_target_year)
        }
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        review_rows = []
        for _, suggestion in suggestions.iterrows():
            if suggestion["origem_chave"] in existing_keys:
                continue
            review_rows.append({
                "Revisão ID": new_id("REV"), "Ano Origem": review_source_year,
                "Ano Destino": review_target_year, "Chave Origem": suggestion["origem_chave"],
                "Decisão": "Pendente", "Tipo": suggestion["tipo"],
                "Categoria": suggestion["categoria"], "Lançamento": suggestion["historico"],
                "Envolvido": suggestion["envolvido"], "Conta": suggestion["conta"],
                "Natureza": suggestion["natureza"],
                "Valor Sugerido (R$)": format_brl(suggestion["valor_sugerido"]),
                "Periodicidade": suggestion["periodicidade"],
                "Primeiro Vencimento": suggestion["primeiro_vencimento"].strftime("%d/%m/%Y"),
                "Ocorrências": int(suggestion["ocorrencias"]),
                "Dia do Vencimento": int(suggestion["dia_vencimento"]),
                "Observação": suggestion["observacao"], "Status": "Aguardando revisão",
                "Criado Em": now, "Atualizado Em": now,
            })
        append_dicts(ws_forecast_review, FORECAST_REVIEW_HEADERS, review_rows)
        if review_rows:
            st.success(f"{len(review_rows)} sugestão(ões) criada(s) para revisão.")
            st.rerun()
        elif suggestions.empty:
            st.warning(f"Não encontrei lançamentos operacionais de {review_source_year} para sugerir.")
        else:
            st.info("As sugestões deste ano já foram geradas. Você pode revisá-las abaixo.")

    review_records = load_records(ws_forecast_review)
    target_reviews = [
        (row_number, row)
        for row_number, row in enumerate(review_records, start=2)
        if str(row.get("Ano Destino") or "").strip() == str(review_target_year)
        and normalize_label(row.get("Status")) not in {"aprovado", "nao incluido"}
    ]
    if target_reviews:
        review_source = pd.DataFrame([{
            "Decisão": clean_editor_text(row.get("Decisão"), "Pendente"),
            "Tipo": clean_editor_text(row.get("Tipo"), "Despesa"),
            "Lançamento": clean_editor_text(row.get("Lançamento")),
            "Categoria": clean_editor_text(row.get("Categoria"), "OUTRO"),
            "Valor sugerido": parse_money(row.get("Valor Sugerido (R$)")),
            "Periodicidade": clean_editor_text(row.get("Periodicidade"), "Anual"),
            "Primeiro vencimento": clean_editor_date(row.get("Primeiro Vencimento")),
            "Ocorrências": int(parse_money(row.get("Ocorrências")) or 1),
            "Dia do vencimento": int(parse_money(row.get("Dia do Vencimento")) or 1),
            "Envolvido": clean_editor_text(row.get("Envolvido")),
            "Conta": clean_editor_text(row.get("Conta")),
            "Natureza": clean_editor_text(row.get("Natureza"), "Operacional"),
            "Observação": clean_editor_text(row.get("Observação")),
            "sheet_row": row_number, "review_id": clean_editor_text(row.get("Revisão ID")),
        } for row_number, row in target_reviews])
        edited_reviews = st.data_editor(
            review_source, use_container_width=True, hide_index=True,
            disabled=["sheet_row", "review_id"],
            column_config={
                "Decisão": st.column_config.SelectboxColumn(
                    options=["Pendente", "Aprovar", "Não incluir"], required=True,
                ),
                "Valor sugerido": st.column_config.NumberColumn(min_value=0.0, format="R$ %.2f"),
                "Tipo": st.column_config.SelectboxColumn(options=["Receita", "Despesa"], required=True),
                "Periodicidade": st.column_config.SelectboxColumn(
                    options=["Mensal", "Trimestral", "Semestral", "Anual"], required=True,
                ),
                "Primeiro vencimento": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Ocorrências": st.column_config.NumberColumn(min_value=1, max_value=12, step=1),
                "Dia do vencimento": st.column_config.NumberColumn(min_value=1, max_value=31, step=1),
                "sheet_row": None, "review_id": None,
            },
            key=f"forecast_review_{review_target_year}",
        )
        st.caption(
            "Você pode ajustar os valores antes de aprovar. Mantenha a decisão como Pendente e salve "
            "periodicamente para guardar o rascunho."
        )
        if st.button("Salvar rascunho e processar decisões", type="primary"):
            intervals = {"Mensal": 1, "Trimestral": 3, "Semestral": 6, "Anual": 12}
            existing_forecast_review_ids = {
                str(row.get("Revisão ID") or "").strip() for row in load_records(ws_forecast)
            }
            approved = rejected = pending = invalid = 0
            now = datetime.now().strftime("%d/%m/%Y %H:%M")
            review_changes = []
            approved_forecast_rows = []
            for _, row in edited_reviews.iterrows():
                decision = clean_editor_text(row.get("Decisão"), "Pendente")
                launch_type = clean_editor_text(row.get("Tipo"), "Despesa")
                description = clean_editor_text(row.get("Lançamento"))
                category = clean_editor_text(row.get("Categoria"), "OUTRO")
                involved = clean_editor_text(row.get("Envolvido"))
                account = clean_editor_text(row.get("Conta"))
                nature = clean_editor_text(row.get("Natureza"), "Operacional")
                notes = clean_editor_text(row.get("Observação"))
                periodicity = clean_editor_text(row.get("Periodicidade"), "Anual")
                first_due = clean_editor_date(row.get("Primeiro vencimento"))
                value = parse_money(row.get("Valor sugerido"))
                occurrences_raw = parse_money(row.get("Ocorrências"))
                occurrences_value = int(occurrences_raw) if occurrences_raw >= 1 else 1
                due_day_raw = parse_money(row.get("Dia do vencimento"))
                due_day = safe_day(int(due_day_raw)) if due_day_raw >= 1 else 1
                interval = intervals.get(periodicity, 12)
                updates = {
                    "Decisão": decision, "Categoria": category,
                    "Lançamento": description,
                    "Envolvido": involved, "Conta": account,
                    "Natureza": nature, "Valor Sugerido (R$)": format_brl(value),
                    "Periodicidade": periodicity,
                    "Primeiro Vencimento": first_due.strftime("%d/%m/%Y") if first_due else "",
                    "Ocorrências": int(occurrences_raw) if occurrences_raw >= 1 else "",
                    "Dia do Vencimento": int(due_day_raw) if due_day_raw >= 1 else "",
                    "Observação": notes, "Atualizado Em": now,
                }
                review_id = clean_editor_text(row.get("review_id"))
                if decision == "Aprovar":
                    last_due = None if first_due is None else date(
                        first_due.year + ((first_due.month - 1 + (occurrences_value - 1) * interval) // 12),
                        ((first_due.month - 1 + (occurrences_value - 1) * interval) % 12) + 1, 1,
                    )
                    if (
                        not description or value <= 0 or first_due is None
                        or not 1 <= occurrences_raw <= 12 or periodicity not in intervals
                        or not 1 <= due_day_raw <= 31
                        or first_due.year != review_target_year or last_due.year != review_target_year
                    ):
                        updates["Status"] = "Revisão necessária"
                        invalid += 1
                    elif review_id not in existing_forecast_review_ids:
                        _, approved_rows = make_recurrence_rows(
                            description=description, launch_type=launch_type,
                            category=category, involved=involved,
                            planned_value=value, start_date=first_due, occurrences=occurrences_value,
                            interval_months=interval, due_day=due_day,
                            account=account, nature=nature,
                            notes=notes,
                        )
                        for approved_row in approved_rows:
                            approved_row["Revisão ID"] = review_id
                        approved_forecast_rows.extend(approved_rows)
                        existing_forecast_review_ids.add(review_id)
                        updates["Status"] = "Aprovado"
                        approved += 1
                    else:
                        updates["Status"] = "Aprovado"
                elif decision == "Não incluir":
                    updates["Status"] = "Não incluído"
                    rejected += 1
                else:
                    updates["Status"] = "Aguardando revisão"
                    pending += 1
                review_changes.append((int(row["sheet_row"]), updates))
            append_dicts(ws_forecast, MAIN_HEADERS, approved_forecast_rows)
            batch_update_rows(ws_forecast_review, review_changes)
            if invalid:
                st.warning(
                    f"{invalid} sugestão(ões) precisam de ajuste. Confira valor, data e quantidade; "
                    f"todas as ocorrências devem permanecer em {review_target_year}."
                )
            else:
                st.success(f"Processado: {approved} aprovado(s), {rejected} não incluído(s) e {pending} pendente(s).")
            st.rerun()
    else:
        st.info(f"Não há sugestões pendentes para {review_target_year}.")

    st.markdown("---")
    st.subheader("Programar lançamentos futuros")
    st.caption("Crie uma série mensal, trimestral, semestral ou anual. Cada ocorrência poderá ser quitada ou alterada individualmente.")
    with st.form("forecast_form", clear_on_submit=True):
        a, b, c = st.columns(3)
        description = a.text_input("Nome do lançamento")
        launch_type = b.selectbox("Tipo", ["Despesa", "Receita"])
        category = c.text_input("Categoria", value="OUTRO")
        d, e, f = st.columns(3)
        planned_value = d.number_input("Valor por ocorrência", min_value=0.0, step=100.0)
        start = e.date_input("Primeiro vencimento", value=date(selected_year, 1, 1), format="DD/MM/YYYY")
        frequency = f.selectbox("Periodicidade", {"Mensal": 1, "Trimestral": 3, "Semestral": 6, "Anual": 12}.keys())
        g, h, i = st.columns(3)
        occurrences = g.number_input("Quantidade de ocorrências", min_value=1, max_value=120, value=12, step=1)
        due_day = h.number_input("Dia do vencimento", min_value=1, max_value=31, value=start.day, step=1)
        nature = i.selectbox("Natureza", NATURE_OPTIONS, key="forecast_nature")
        j, k = st.columns(2)
        involved = j.text_input("Envolvido")
        account = k.text_input("Conta")
        notes = st.text_area("Observações da série")
        create_series = st.form_submit_button("Criar forecast", type="primary")
    if create_series:
        if not description or planned_value <= 0:
            st.error("Informe o nome e um valor maior que zero.")
        else:
            intervals = {"Mensal": 1, "Trimestral": 3, "Semestral": 6, "Anual": 12}
            series_id, series_rows = make_recurrence_rows(
                description=description, launch_type=launch_type, category=category, involved=involved,
                planned_value=planned_value, start_date=start, occurrences=int(occurrences),
                interval_months=intervals[frequency], due_day=safe_day(due_day), account=account,
                nature=nature, notes=notes,
            )
            append_dicts(ws_forecast, MAIN_HEADERS, series_rows)
            append_dicts(ws_recurrences, ws_recurrences.row_values(1), [{
                "Série ID": series_id, "Descrição": description, "Tipo": launch_type, "Categoria": category,
                "Início": start.strftime("%d/%m/%Y"), "Ocorrências": int(occurrences),
                "Intervalo em meses": intervals[frequency], "Valor": format_brl(planned_value),
                "Criado Em": datetime.now().strftime("%d/%m/%Y %H:%M"),
            }])
            st.success(f"Forecast criado com {int(occurrences)} ocorrências.")

    st.markdown("---")
    st.subheader(f"Matriz anual de {selected_year}")
    st.caption("A matriz mostra somente os valores que ainda faltam receber ou pagar em cada mês.")
    open_series = open_launches(launches)
    year_series = open_series[open_series["competencia"].dt.year == selected_year].copy() if not open_series.empty else open_series
    if year_series.empty:
        st.info("O forecast deste ano ainda não foi carregado.")
    else:
        year_series["mes_num"] = year_series["competencia"].dt.month
        year_series["_matrix_key"] = year_series.apply(
            lambda row: (
                f"SERIE:{row['serie_id']}"
                if str(row["serie_id"]).strip()
                else f"REGISTRO:{row['id'] or int(row['sheet_row'])}"
            ),
            axis=1,
        )
        matrix_details = (
            year_series.sort_values(["_matrix_key", "competencia", "sheet_row"])
            .groupby("_matrix_key", as_index=False)
            .first()[["_matrix_key", "tipo", "historico", "categoria", "envolvido", "natureza"]]
        )
        matrix_values = year_series.pivot_table(
            index="_matrix_key", columns="mes_num", values="pendente", aggfunc="sum", fill_value=0.0
        ).reset_index()
        matrix = matrix_details.merge(matrix_values, on="_matrix_key", how="left")
        for month_number in range(1, 13):
            if month_number not in matrix:
                matrix[month_number] = 0.0
        matrix = matrix[
            ["_matrix_key", "tipo", "historico", "categoria", "envolvido", "natureza", *range(1, 13)]
        ].rename(
            columns={
                "tipo": "Tipo",
                "historico": "Lançamento",
                "categoria": "Categoria",
                "envolvido": "Envolvido",
                "natureza": "Natureza",
                **MESES,
            }
        )
        matrix["_type_order"] = matrix["Tipo"].map(
            lambda value: 0 if normalize_label(value) == "receita" else 1
        )
        matrix["_launch_order"] = matrix["Lançamento"].map(normalize_label)
        matrix = (
            matrix.sort_values(["_type_order", "_launch_order"], kind="stable")
            .drop(columns=["_type_order", "_launch_order"])
            .reset_index(drop=True)
        )
        matrix_editor_key = f"annual_matrix_editor_{selected_year}"
        edited_matrix = st.data_editor(
            matrix,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            disabled=["_matrix_key"],
            column_config={
                "_matrix_key": None,
                "Tipo": st.column_config.SelectboxColumn(
                    options=["Receita", "Despesa"], required=True,
                ),
                "Natureza": st.column_config.SelectboxColumn(
                    options=NATURE_OPTIONS, required=True,
                ),
                **{
                    month_name: st.column_config.NumberColumn(
                        min_value=0.0,
                        step=100.0,
                        format="R$ %.2f",
                    )
                    for month_name in MESES.values()
                },
            },
            key=matrix_editor_key,
        )
        st.caption(
            "Edite o nome, tipo, categoria, envolvido ou natureza para corrigir a série inteira. "
            "Use Retirada de lucros para reduzir a sobra sem reduzir o resultado operacional. "
            "A alteração em um mês afeta somente aquele mês. Use a última linha vazia para incluir um lançamento. "
            "Para excluir uma série, remova a linha pelo controle da tabela ou apague seu conteúdo e deixe todos os meses zerados."
        )
        if st.button("Salvar alterações da matriz", type="primary"):
            original_by_key = matrix.set_index("_matrix_key")
            row_updates: dict[int, dict] = {}
            new_rows: list[dict] = []
            rows_to_delete: list[int] = []
            warnings: list[str] = []
            changed_cells = 0
            deleted_series = 0
            created_series = 0
            now = datetime.now().strftime("%d/%m/%Y %H:%M")
            generated_series_ids: dict[str, str] = {}

            def queue_update(sheet_row: int, updates: dict) -> None:
                row_updates.setdefault(int(sheet_row), {}).update(updates)

            edited_existing_keys = {
                clean_editor_text(row.get("_matrix_key"))
                for _, row in edited_matrix.iterrows()
                if clean_editor_text(row.get("_matrix_key")) in original_by_key.index
            }
            removed_keys = set(original_by_key.index) - edited_existing_keys
            for matrix_key in removed_keys:
                source_rows = year_series[year_series["_matrix_key"] == matrix_key]
                rows_to_delete.extend(source_rows["sheet_row"].astype(int).tolist())
                deleted_series += 1

            for _, edited_row in edited_matrix.iterrows():
                matrix_key = clean_editor_text(edited_row.get("_matrix_key"))
                month_values = {
                    month_number: max(parse_money(edited_row.get(month_name)), 0.0)
                    for month_number, month_name in MESES.items()
                }
                edited_description = clean_editor_text(edited_row.get("Lançamento"))
                edited_category_raw = clean_editor_text(edited_row.get("Categoria"))
                edited_involved = clean_editor_text(edited_row.get("Envolvido"))
                edited_nature = clean_editor_text(edited_row.get("Natureza"), "Operacional")
                row_is_empty = (
                    not edited_description
                    and not edited_category_raw
                    and not edited_involved
                    and not any(value > 0.005 for value in month_values.values())
                )

                if matrix_key not in original_by_key.index:
                    if row_is_empty:
                        continue
                    edited_type = clean_editor_text(edited_row.get("Tipo"), "Despesa")
                    edited_category = edited_category_raw or "OUTRO"
                    if not edited_description:
                        warnings.append("Uma nova linha não foi incluída porque está sem nome de lançamento.")
                        continue
                    positive_months = {
                        month_number: value
                        for month_number, value in month_values.items()
                        if value > 0.005
                    }
                    if not positive_months:
                        warnings.append(
                            f"{edited_description}: informe valor em pelo menos um mês para incluir o lançamento."
                        )
                        continue
                    series_id = new_id("SER")
                    for month_number, edited_value in positive_months.items():
                        due = date(selected_year, month_number, 1)
                        new_row = {header: "" for header in MAIN_HEADERS}
                        new_row.update({
                            "Mês": MESES[month_number],
                            "Tipo de Operação": edited_type,
                            "Categoria": edited_category,
                            "Corretor / Envolvido": edited_involved,
                            "Histórico": edited_description,
                            "Natureza": edited_nature,
                            "Valor (R$)": format_brl(edited_value),
                            "Status": "Previsto",
                            "ID": new_id(),
                            "Competência": f"{month_number:02d}/{selected_year}",
                            "Vencimento": due.strftime("%d/%m/%Y"),
                            "Valor Previsto (R$)": format_brl(edited_value),
                            "Série ID": series_id,
                            "Criado Em": now,
                            "Atualizado Em": now,
                            "Moeda": "BRL",
                            "Percentual Considerado": 100,
                        })
                        new_rows.append(new_row)
                    changed_cells += len(positive_months)
                    created_series += 1
                    continue

                original_row = original_by_key.loc[matrix_key]
                source_rows = year_series[year_series["_matrix_key"] == matrix_key].copy()
                if source_rows.empty:
                    continue

                edited_type = clean_editor_text(edited_row.get("Tipo"), "Despesa")
                edited_category = edited_category_raw or "OUTRO"
                if row_is_empty:
                    rows_to_delete.extend(source_rows["sheet_row"].astype(int).tolist())
                    deleted_series += 1
                    continue
                if not edited_description:
                    warnings.append("Há uma linha sem nome de lançamento; ela não foi alterada.")
                    continue

                common_updates = {}
                if edited_type != clean_editor_text(original_row.get("Tipo"), "Despesa"):
                    common_updates["Tipo de Operação"] = edited_type
                if edited_description != clean_editor_text(original_row.get("Lançamento")):
                    common_updates["Histórico"] = edited_description
                if edited_category != clean_editor_text(original_row.get("Categoria"), "OUTRO"):
                    common_updates["Categoria"] = edited_category
                if edited_involved != clean_editor_text(original_row.get("Envolvido")):
                    common_updates["Corretor / Envolvido"] = edited_involved
                if edited_nature != clean_editor_text(original_row.get("Natureza"), "Operacional"):
                    common_updates["Natureza"] = edited_nature
                if common_updates:
                    common_updates["Atualizado Em"] = now
                    for sheet_row in source_rows["sheet_row"]:
                        queue_update(int(sheet_row), common_updates)
                    changed_cells += len(common_updates) - 1

                for month_number, month_name in MESES.items():
                    original_value = parse_money(original_row.get(month_name))
                    edited_value = month_values[month_number]
                    if abs(edited_value - original_value) <= 0.005:
                        continue
                    month_rows = source_rows[source_rows["mes_num"] == month_number]
                    if len(month_rows) > 1:
                        warnings.append(
                            f"{edited_description} em {month_name}: existem registros duplicados; "
                            "o valor não foi alterado."
                        )
                        continue
                    if len(month_rows) == 1:
                        launch_row = month_rows.iloc[0]
                        planned_value = float(launch_row["realizado"]) + edited_value
                        queue_update(
                            int(launch_row["sheet_row"]),
                            {
                                "Valor (R$)": format_brl(planned_value),
                                "Valor Previsto (R$)": format_brl(planned_value),
                                "Atualizado Em": now,
                            },
                        )
                    elif edited_value > 0:
                        base_row = source_rows.iloc[0]
                        base_index = int(base_row["sheet_row"]) - 2
                        base_record = dict(records[base_index]) if 0 <= base_index < len(records) else {}
                        series_id = clean_editor_text(base_row.get("serie_id"))
                        if not series_id:
                            series_id = generated_series_ids.setdefault(str(matrix_key), new_id("SER"))
                            for sheet_row in source_rows["sheet_row"]:
                                queue_update(int(sheet_row), {"Série ID": series_id, "Atualizado Em": now})
                        due_values = source_rows["vencimento"].dropna()
                        due_day = int(due_values.iloc[0].day) if not due_values.empty else 1
                        first_day = pd.Timestamp(selected_year, month_number, 1)
                        due = date(selected_year, month_number, min(due_day, first_day.days_in_month))
                        new_row = {header: base_record.get(header, "") for header in MAIN_HEADERS}
                        new_row.update({
                            "Mês": MESES[month_number],
                            "Tipo de Operação": edited_type,
                            "Categoria": edited_category,
                            "Corretor / Envolvido": edited_involved,
                            "Histórico": edited_description,
                            "Natureza": edited_nature,
                            "Valor (R$)": format_brl(edited_value),
                            "Status": "Previsto",
                            "ID": new_id(),
                            "Competência": f"{month_number:02d}/{selected_year}",
                            "Vencimento": due.strftime("%d/%m/%Y"),
                            "Valor Previsto (R$)": format_brl(edited_value),
                            "Valor Realizado (R$)": "",
                            "Data Quitação": "",
                            "Série ID": series_id,
                            "Criado Em": now,
                            "Atualizado Em": now,
                            "Moeda": "BRL",
                            "Valor na Moeda": "",
                            "Cotação Utilizada": "",
                            "Percentual Considerado": 100,
                        })
                        new_rows.append(new_row)
                    changed_cells += 1

            batch_update_rows(ws_forecast, list(row_updates.items()))
            append_dicts(ws_forecast, MAIN_HEADERS, new_rows)
            delete_sheet_rows(ws_forecast, rows_to_delete)
            if warnings:
                st.warning(" ".join(dict.fromkeys(warnings)))
            if row_updates or new_rows or rows_to_delete:
                st.session_state.pop(matrix_editor_key, None)
                details = [f"{changed_cells} alteração(ões) salva(s)"]
                if created_series:
                    details.append(f"{created_series} nova(s) linha(s) incluída(s)")
                if deleted_series:
                    details.append(f"{deleted_series} linha(s) excluída(s)")
                st.success("Matriz atualizada: " + ", ".join(details) + ".")
                st.rerun()
            elif not warnings:
                st.info("Nenhuma alteração foi identificada na matriz.")

        st.subheader(f"Resumo mensal do forecast de {selected_year}")
        st.caption(
            "Os valores abaixo vêm dos mesmos lançamentos da matriz e são atualizados "
            "sempre que uma receita ou despesa é alterada."
        )
        monthly_summary = monthly[
            ["mes", "receitas", "despesas", "retiradas", "resultado", "movimento_caixa"]
        ].rename(
            columns={
                "mes": "Mês",
                "receitas": "Receitas previstas",
                "despesas": "Despesas previstas",
                "retiradas": "Retiradas de lucros",
                "resultado": "Resultado previsto",
                "movimento_caixa": "Resultado após retiradas",
            }
        )
        display_money_table(
            monthly_summary,
            [
                "Receitas previstas",
                "Despesas previstas",
                "Retiradas de lucros",
                "Resultado previsto",
                "Resultado após retiradas",
            ],
        )

        annual_income = float(monthly["receitas"].sum())
        annual_expense = float(monthly["despesas"].sum())
        annual_withdrawals = float(monthly["retiradas"].sum())
        annual_result = annual_income - annual_expense
        annual_after_withdrawals = annual_result - annual_withdrawals
        st.subheader(f"Fechamento anual de {selected_year}")
        annual_cards = [
            ("Receitas previstas no ano", annual_income),
            ("Despesas previstas no ano", annual_expense),
            ("Retiradas previstas no ano", annual_withdrawals),
            ("Resultado previsto no ano", annual_result),
            ("Resultado após retiradas", annual_after_withdrawals),
        ]
        cards_html = "".join(
            '<div class="annual-summary-card">'
            f'<div class="annual-summary-label">{label}</div>'
            f'<div class="annual-summary-value">{format_brl(value)}</div>'
            "</div>"
            for label, value in annual_cards
        )
        st.markdown(
            f'<div class="annual-summary-grid">{cards_html}</div>',
            unsafe_allow_html=True,
        )
        if annual_after_withdrawals >= 0:
            st.caption(
                "Sobra informativa após as retiradas de lucros programadas: "
                f"{format_brl(annual_after_withdrawals)}."
            )
        else:
            st.caption(
                "Falta informativa após as retiradas de lucros programadas: "
                f"{format_brl(abs(annual_after_withdrawals))}."
            )

    st.subheader("Alterar valores a partir de um mês")
    editable_series = year_series[year_series["serie_id"].astype(str).str.strip() != ""] if not year_series.empty else year_series
    if editable_series.empty:
        st.info("Não há séries editáveis neste ano.")
    else:
        series_labels = (
            editable_series.sort_values(["historico", "competencia"])
            .drop_duplicates("serie_id")
            .set_index("serie_id")["historico"]
            .to_dict()
        )
        with st.form("adjust_series"):
            selected_series = st.selectbox(
                "Lançamento",
                list(series_labels),
                format_func=lambda item: series_labels[item],
            )
            a, b = st.columns(2)
            change_month = a.selectbox("Alterar a partir do mês", list(MESES), format_func=lambda item: MESES[item])
            new_value = b.number_input("Novo valor por mês", min_value=0.0, step=100.0)
            apply_change = st.form_submit_button("Aplicar aos meses seguintes", type="primary")
        if apply_change:
            cutoff = pd.Timestamp(selected_year, change_month, 1)
            series_rows = editable_series[
                (editable_series["serie_id"] == selected_series)
                & (editable_series["competencia"].dt.year == selected_year)
            ].copy()
            now = datetime.now().strftime("%d/%m/%Y %H:%M")
            changes: list[tuple[int, dict]] = []
            missing_rows: list[dict] = []
            duplicate_months: list[str] = []
            base_row = series_rows.sort_values(["competencia", "sheet_row"]).iloc[0]
            base_index = int(base_row["sheet_row"]) - 2
            base_record = dict(records[base_index]) if 0 <= base_index < len(records) else {}
            due_values = series_rows["vencimento"].dropna()
            due_day = int(due_values.iloc[0].day) if not due_values.empty else 1

            for month_number in range(change_month, 13):
                month_rows = series_rows[series_rows["competencia"].dt.month == month_number]
                if len(month_rows) > 1:
                    duplicate_months.append(MESES[month_number])
                if not month_rows.empty:
                    for _, row in month_rows.iterrows():
                        changes.append((int(row["sheet_row"]), {
                            "Valor (R$)": format_brl(new_value),
                            "Valor Previsto (R$)": format_brl(new_value),
                            "Atualizado Em": now,
                        }))
                    continue
                if new_value <= 0:
                    continue
                first_day = pd.Timestamp(selected_year, month_number, 1)
                due = date(selected_year, month_number, min(due_day, first_day.days_in_month))
                new_row = {header: base_record.get(header, "") for header in MAIN_HEADERS}
                new_row.update({
                    "Mês": MESES[month_number],
                    "Valor (R$)": format_brl(new_value),
                    "Status": "Previsto",
                    "ID": new_id(),
                    "Competência": f"{month_number:02d}/{selected_year}",
                    "Vencimento": due.strftime("%d/%m/%Y"),
                    "Valor Previsto (R$)": format_brl(new_value),
                    "Valor Realizado (R$)": "",
                    "Data Quitação": "",
                    "Série ID": selected_series,
                    "Criado Em": now,
                    "Atualizado Em": now,
                })
                missing_rows.append(new_row)

            batch_update_rows(ws_forecast, changes)
            append_dicts(ws_forecast, MAIN_HEADERS, missing_rows)
            if duplicate_months:
                st.warning(
                    "A série possui mais de um registro em "
                    + ", ".join(duplicate_months)
                    + "; todos foram atualizados."
                )
            total_months = len({
                int(row["competencia"].month)
                for _, row in series_rows[series_rows["competencia"] >= cutoff].iterrows()
            }) + len(missing_rows)
            if changes or missing_rows:
                st.toast(
                    f"{total_months} mês(es) ajustado(s): "
                    f"{len(changes)} registro(s) atualizado(s) e {len(missing_rows)} criado(s)."
                )
                st.rerun()
            else:
                st.info("Nenhum registro precisou ser alterado.")

with tab_works:
    st.subheader("Controle de obras")
    st.caption(
        "O valor que falta pagar aos prestadores atualiza automaticamente o saldo "
        "Acertos de obras pendentes e reduz a sobra disponível para distribuição."
    )
    st.info(
        "Os pagamentos informados aqui não alteram o saldo bancário. Depois de pagar o prestador, "
        "atualize manualmente o banco na aba Saldos."
    )

    work_monthly = monthly_work_summary(works, selected_year)
    default_work_month = today.month if selected_year == today.year else 1
    work_month = st.selectbox(
        "Mês das obras",
        list(MESES),
        index=default_work_month - 1,
        format_func=lambda item: MESES[item],
        key="work_month",
    )
    work_summary = work_monthly.iloc[work_month - 1]
    w1, w2, w3, w4 = st.columns(4)
    w1.metric("Valor cobrado", format_brl(work_summary["cobrado"]))
    w2.metric("Custo previsto", format_brl(work_summary["custo_previsto"]))
    w3.metric("Lucro previsto", format_brl(work_summary["lucro_previsto"]))
    w4.metric("Falta pagar", format_brl(work_summary["falta_pagar"]))

    selected_works = works[
        works["competencia"].notna()
        & (works["competencia"].dt.year == selected_year)
        & (works["competencia"].dt.month == work_month)
    ].copy() if not works.empty else works.copy()

    st.subheader("Obras do mês")
    if selected_works.empty:
        st.info("Nenhuma obra cadastrada neste mês.")
    else:
        selected_works = selected_works.sort_values(["status", "obra"]).reset_index(drop=True)
        works_editor_source = pd.DataFrame({
            "Obra": selected_works["obra"],
            "Cliente": selected_works["cliente"],
            "Valor cobrado": selected_works["cobrado"].astype(float),
            "Valor recebido": selected_works["recebido"].astype(float),
            "A receber": selected_works["a_receber"].astype(float),
            "Prestador": selected_works["prestador"],
            "PIX do prestador": selected_works["pix"],
            "Custo previsto": selected_works["custo_previsto"].astype(float),
            "Valor pago": selected_works["pago"].astype(float),
            "Falta pagar": selected_works["falta_pagar"].astype(float),
            "Lucro previsto": selected_works["lucro_previsto"].astype(float),
            "Status": selected_works["status"],
            "Observação": selected_works["observacao"],
            "sheet_row": selected_works["sheet_row"].astype(int),
        })
        edited_works = st.data_editor(
            works_editor_source,
            use_container_width=True,
            hide_index=True,
            disabled=["A receber", "Falta pagar", "Lucro previsto", "sheet_row"],
            column_config={
                "Valor cobrado": st.column_config.NumberColumn(min_value=0.0, format="R$ %.2f"),
                "Valor recebido": st.column_config.NumberColumn(min_value=0.0, format="R$ %.2f"),
                "A receber": st.column_config.NumberColumn(format="R$ %.2f"),
                "Custo previsto": st.column_config.NumberColumn(min_value=0.0, format="R$ %.2f"),
                "Valor pago": st.column_config.NumberColumn(min_value=0.0, format="R$ %.2f"),
                "Falta pagar": st.column_config.NumberColumn(format="R$ %.2f"),
                "Lucro previsto": st.column_config.NumberColumn(format="R$ %.2f"),
                "Status": st.column_config.SelectboxColumn(
                    options=["Em andamento", "Parcial", "Concluída", "Cancelada"],
                    required=True,
                ),
                "sheet_row": None,
            },
            key=f"works_editor_{selected_year}_{work_month}",
        )
        if st.button("Salvar alterações das obras", type="primary"):
            now = datetime.now().strftime("%d/%m/%Y %H:%M")
            for _, row in edited_works.iterrows():
                update_row(ws_works, int(row["sheet_row"]), {
                    "Obra / Histórico": str(row["Obra"]).strip(),
                    "Locador / Cliente": str(row["Cliente"]).strip(),
                    "Valor Cobrado (R$)": format_brl(float(row["Valor cobrado"])),
                    "Valor Recebido (R$)": format_brl(float(row["Valor recebido"])),
                    "Prestador": str(row["Prestador"]).strip(),
                    "PIX do Prestador": str(row["PIX do prestador"]).strip(),
                    "Custo Previsto (R$)": format_brl(float(row["Custo previsto"])),
                    "Valor Pago (R$)": format_brl(float(row["Valor pago"])),
                    "Status": str(row["Status"]),
                    "Observação": str(row["Observação"]).strip(),
                    "Atualizado Em": now,
                })
            refreshed_works = normalize_works(load_records(ws_works))
            sync_construction_balance(ws_balances, construction_payables(refreshed_works))
            st.success("Obras atualizadas e saldo de acertos recalculado.")
            st.warning("Se houve pagamento ao prestador, atualize manualmente o saldo bancário na aba Saldos.")
            st.cache_data.clear()
            st.rerun()

    with st.expander("Cadastrar nova obra"):
        with st.form("new_work", clear_on_submit=True):
            a, b, c = st.columns(3)
            work_description = a.text_input("Obra / histórico")
            work_client = b.text_input("Locador / cliente")
            work_competence = c.date_input(
                "Competência",
                value=date(selected_year, work_month, 1),
                format="DD/MM/YYYY",
            )
            d, e, f = st.columns(3)
            work_charged = d.number_input("Valor cobrado", min_value=0.0, step=100.0)
            work_received = e.number_input("Valor recebido", min_value=0.0, step=100.0)
            work_cost = f.number_input("Custo previsto do prestador", min_value=0.0, step=100.0)
            g, h, i = st.columns(3)
            work_paid = g.number_input("Valor já pago", min_value=0.0, step=100.0)
            work_provider = h.text_input("Prestador")
            work_pix = i.text_input("PIX do prestador")
            work_notes = st.text_area("Observações", key="new_work_notes")
            save_work = st.form_submit_button("Salvar nova obra", type="primary")
        if save_work:
            if not work_description.strip():
                st.error("Informe a obra ou histórico.")
            elif work_charged <= 0 and work_cost <= 0:
                st.error("Informe o valor cobrado ou o custo previsto.")
            else:
                status = "Concluída" if work_cost > 0 and work_paid >= work_cost else (
                    "Parcial" if work_paid > 0 or work_received > 0 else "Em andamento"
                )
                now = datetime.now().strftime("%d/%m/%Y %H:%M")
                append_dicts(ws_works, WORK_HEADERS, [{
                    "ID": new_id("OBR"),
                    "Competência": work_competence.strftime("%m/%Y"),
                    "Obra / Histórico": work_description.strip(),
                    "Locador / Cliente": work_client.strip(),
                    "Valor Cobrado (R$)": format_brl(work_charged),
                    "Valor Recebido (R$)": format_brl(work_received),
                    "Prestador": work_provider.strip(),
                    "PIX do Prestador": work_pix.strip(),
                    "Custo Previsto (R$)": format_brl(work_cost),
                    "Valor Pago (R$)": format_brl(work_paid),
                    "Status": status,
                    "Observação": work_notes.strip(),
                    "Criado Em": now,
                    "Atualizado Em": now,
                }])
                refreshed_works = normalize_works(load_records(ws_works))
                sync_construction_balance(ws_balances, construction_payables(refreshed_works))
                st.success("Obra cadastrada e saldo de acertos atualizado.")
                if work_paid > 0:
                    st.warning("Atualize manualmente o saldo bancário na aba Saldos.")
                st.cache_data.clear()
                st.rerun()

    st.subheader(f"Resultado mensal das obras em {selected_year}")
    work_history_view = work_monthly[[
        "mes", "cobrado", "recebido", "custo_previsto", "pago", "falta_pagar", "lucro_previsto"
    ]].rename(columns={
        "mes": "Mês", "cobrado": "Valor cobrado", "recebido": "Valor recebido",
        "custo_previsto": "Custo previsto", "pago": "Valor pago",
        "falta_pagar": "Falta pagar", "lucro_previsto": "Lucro previsto",
    })
    display_money_table(
        work_history_view,
        ["Valor cobrado", "Valor recebido", "Custo previsto", "Valor pago", "Falta pagar", "Lucro previsto"],
    )

with tab_withdrawals:
    st.subheader(f"Retiradas dos sócios em {selected_year}")
    st.caption(
        "Registre aqui pró-labore, distribuição de lucros e retiradas adicionais por mês. "
        "Este controle é histórico e não altera novamente o saldo bancário nem a projeção."
    )
    ensure_withdrawal_year(ws_withdrawals, selected_year)
    selected_withdrawals = normalize_withdrawals(load_records(ws_withdrawals))
    selected_withdrawals = selected_withdrawals[
        selected_withdrawals["competencia"].notna()
        & (selected_withdrawals["competencia"].dt.year == selected_year)
    ].sort_values("competencia").reset_index(drop=True)
    withdrawals_editor_source = pd.DataFrame({
        "Mês": selected_withdrawals["competencia"].dt.month.map(MESES),
        "Pró-labore": selected_withdrawals["pro_labore"].astype(float),
        "Retirada de lucros": selected_withdrawals["lucros"].astype(float),
        "Retirada adicional": selected_withdrawals["adicional"].astype(float),
        "Total do mês": (
            selected_withdrawals["pro_labore"]
            + selected_withdrawals["lucros"]
            + selected_withdrawals["adicional"]
        ).astype(float),
        "Observação": selected_withdrawals["observacao"],
        "sheet_row": selected_withdrawals["sheet_row"].astype(int),
    })
    edited_withdrawals = st.data_editor(
        withdrawals_editor_source, use_container_width=True, hide_index=True,
        disabled=["Mês", "Total do mês", "sheet_row"],
        column_config={
            "Pró-labore": st.column_config.NumberColumn(min_value=0.0, format="R$ %.2f"),
            "Retirada de lucros": st.column_config.NumberColumn(min_value=0.0, format="R$ %.2f"),
            "Retirada adicional": st.column_config.NumberColumn(min_value=0.0, format="R$ %.2f"),
            "Total do mês": st.column_config.NumberColumn(format="R$ %.2f"),
            "sheet_row": None,
        },
        key=f"withdrawals_editor_{selected_year}",
    )
    if st.button("Salvar retiradas", type="primary"):
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        withdrawal_changes = []
        for _, row in edited_withdrawals.iterrows():
            withdrawal_changes.append((int(row["sheet_row"]), {
                "Pró-labore (R$)": format_brl(float(row["Pró-labore"])),
                "Retirada de Lucros (R$)": format_brl(float(row["Retirada de lucros"])),
                "Retirada Adicional (R$)": format_brl(float(row["Retirada adicional"])),
                "Observação": str(row["Observação"]).strip(),
                "Atualizado Em": now,
            }))
        batch_update_rows(ws_withdrawals, withdrawal_changes)
        st.success("Retiradas atualizadas.")
        st.rerun()

    selected_summary = withdrawal_summary(
        selected_withdrawals,
        selected_year,
        withdrawal_month_limit,
        partner_count=2,
    )
    st.subheader("Resumo acumulado")
    if withdrawal_month_limit == 0:
        st.info("O acumulado começará quando este ano se tornar corrente.")
    else:
        w1, w2, w3, w4 = st.columns(4)
        w1.metric("Pró-labore", format_brl(selected_summary["pro_labore"]))
        w2.metric("Lucros", format_brl(selected_summary["lucros"]))
        w3.metric("Adicionais", format_brl(selected_summary["adicional"]))
        w4.metric("Total", format_brl(selected_summary["total"]))
        w5, w6 = st.columns(2)
        w5.metric("Média mensal total", format_brl(selected_summary["media_mensal"]))
        w6.metric("Média por sócio / mês", format_brl(selected_summary["media_socio_mes"]))

with tab_balances:
    balance_saved_at = st.session_state.pop("_balance_saved_at", None)
    if balance_saved_at:
        st.success(f"Saldos atualizados em {balance_saved_at}. Os totais já foram recalculados.")

    st.subheader("Reserva em dólar")
    st.caption("Informe o saldo em USD. O equivalente em reais já compõe os saldos atualizados e não entra novamente no forecast.")
    mode_options = ["PTAX automática", "Cotação manual"]
    quote_mode = st.radio(
        "Cotação utilizada",
        mode_options,
        index=1 if manual_quote > 0 else 0,
        horizontal=True,
        key="usd_quote_mode",
    )
    u1, u2, u3 = st.columns(3)
    usd_amount = u1.number_input(
        "Saldo em dólar (USD)",
        min_value=0.0,
        value=float(parameters["reserva_usd"]),
        step=100.0,
        format="%.2f",
    )
    usd_manual_input = u2.number_input(
        "Cotação manual",
        min_value=0.0,
        value=manual_quote,
        step=0.01,
        format="%.4f",
        disabled=quote_mode == "PTAX automática",
    )
    usd_percent = u3.number_input(
        "Percentual considerado",
        min_value=0.0,
        max_value=100.0,
        value=float(parameters["percentual_usd"]),
        step=1.0,
    )
    selected_quote = (
        usd_manual_input
        if quote_mode == "Cotação manual"
        else (automatic_quote or saved_quote)
    )
    selected_usd_balance = fx_balance_brl(usd_amount, selected_quote, usd_percent)
    m1, m2 = st.columns(2)
    m1.metric("Cotação aplicada", f"R$ {selected_quote:.4f}" if selected_quote else "Indisponível")
    m2.metric("Saldo convertido para reais", format_brl(selected_usd_balance))
    if quote_mode == "PTAX automática" and automatic_quote and automatic_quote_date:
        st.caption(f"PTAX de venda do Banco Central em {automatic_quote_date.strftime('%d/%m/%Y')}.")
    elif quote_mode == "PTAX automática" and saved_quote:
        st.warning("A PTAX está temporariamente indisponível. O sistema está exibindo a última cotação salva.")
    elif quote_mode == "PTAX automática":
        st.warning("A PTAX está indisponível e ainda não existe uma cotação anterior salva.")

    if st.button("Salvar reserva em dólar", type="primary"):
        if quote_mode == "Cotação manual" and usd_manual_input <= 0:
            st.error("Informe uma cotação manual maior que zero.")
        elif selected_quote <= 0:
            st.error("Não foi possível obter uma cotação. Selecione Cotação manual e informe o valor.")
        else:
            save_parameters(ws_parameters, {
                "reserva_usd": usd_amount,
                "percentual_usd": usd_percent,
                "cotacao_manual_usd": usd_manual_input if quote_mode == "Cotação manual" else 0.0,
                "ultima_cotacao_usd": selected_quote,
            })
            now = datetime.now().strftime("%d/%m/%Y %H:%M")
            append_dicts(ws_quotes, QUOTE_HEADERS, [{
                "Data": (automatic_quote_date or today).strftime("%d/%m/%Y"),
                "Moeda": "USD",
                "Compra": "",
                "Venda": selected_quote,
                "Fonte": "Manual" if quote_mode == "Cotação manual" else "BCB PTAX",
                "Consultado Em": now,
            }])
            st.success("Reserva em dólar atualizada.")
            st.cache_data.clear()
            st.rerun()

    st.markdown("---")
    st.subheader("Saldos bancários e investimentos em reais")
    st.caption(
        "Informe o saldo real atual. A reserva para juros de cauções fica nesta lista, mas é protegida e não aumenta o valor distribuível."
    )
    if interest_reserve:
        st.info(f"Reserva protegida para juros de cauções: {format_brl(interest_reserve)}.")
    liability_labels = (
        (is_customer_pass_through_balance, "Superlógica — repasses a clientes", None),
        (is_pending_construction_adjustment_balance, "Acertos de obras pendentes", works_payable),
        (is_advance_customer_payment_balance, "Boletos pagos adiantados", None),
    )
    for checker, label, automatic_amount in liability_labels:
        amount = automatic_amount if automatic_amount is not None else float(
            balances_df.loc[balances_df["Conta"].map(checker), "Valor Num"].sum()
        )
        if amount:
            direction = "reduz" if amount > 0 else "aumenta"
            st.info(f"{label}: {format_brl(amount)}. Este valor {direction} a sobra disponível para distribuição.")
    st.caption("Acertos de obras pendentes é calculado na aba Obras e não pode ser alterado manualmente aqui.")
    edit = balances_df[~balances_df["Conta"].map(is_pending_construction_adjustment_balance)][BALANCE_HEADERS].copy()
    edit["Valor"] = edit["Valor"].map(
        lambda value: format_brl(parse_money(value)) if str(value).strip() else ""
    )
    edited = st.data_editor(
        edit,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "Valor": st.column_config.TextColumn(
                "Valor",
                help="Você pode digitar somente o número. Depois de salvar, ele será exibido como R$ 1.234,56.",
            ),
        },
    )
    if st.button("Salvar todos os saldos", type="primary"):
        now = datetime.now().strftime("%d/%m/%Y às %H:%M")
        ws_balances.clear()
        saved_balances = []
        for _, balance in edited.fillna("").iterrows():
            raw_value = str(balance["Valor"]).strip()
            saved_balances.append([
                str(balance["Conta"]).strip(),
                format_brl(parse_money(raw_value)) if raw_value else "",
            ])
        saved_balances.append(["Acertos de obras pendentes", format_brl(works_payable)])
        ws_balances.update("A1", [BALANCE_HEADERS] + saved_balances, value_input_option="USER_ENTERED")
        invalidate_records(ws_balances)
        st.session_state["_balance_saved_at"] = now
        st.cache_data.clear()
        st.rerun()

with tab_history:
    st.subheader("Histórico consolidado mensal")
    consolidated = monthly_realized_history(combined_history, selected_year)
    history_cutoff = pd.Timestamp(selected_year, 12, 1)
    if selected_year == today.year:
        history_cutoff = pd.Timestamp(today.year, today.month, 1)
    consolidated = consolidated[consolidated["competencia"] <= history_cutoff].copy()
    consolidated_view = consolidated[[
        "mes", "receitas_realizadas", "despesas_realizadas", "resultado_realizado"
    ]]
    display_money_table(
        consolidated_view,
        ["receitas_realizadas", "despesas_realizadas", "resultado_realizado"],
    )

    st.subheader("Lançamentos históricos")
    tracked = realization_tracking(combined_history)
    tracked = tracked[
        (tracked["competencia"].dt.year == selected_year)
        & (tracked["competencia"] <= history_cutoff)
        & ((tracked["realizado"] > 0) | (tracked["previsto"] > 0))
    ].copy() if not tracked.empty else tracked
    if tracked.empty:
        st.info("Ainda não existem pagamentos ou recebimentos informados.")
    else:
        tracking_view = tracked[[
            "competencia", "tipo", "categoria", "historico", "previsto", "realizado", "pendente", "status", "conta"
        ]].sort_values(["competencia", "tipo", "historico"])
        display_money_table(tracking_view, ["previsto", "realizado", "pendente"])

        correctable = tracked[tracked["realizado"] > 0].copy()
        if not correctable.empty:
            st.subheader("Corrigir receita ou despesa já baixada")
            st.caption(
                "A correção atualiza o histórico e o resultado realizado, mas não movimenta o saldo bancário. "
                "Use Reabrir somente quando a baixa tiver sido feita por engano."
            )
            correctable = correctable.sort_values(
                ["competencia", "tipo", "historico", "sheet_row"], kind="stable"
            ).reset_index(drop=True)
            correction_index = st.selectbox(
                "Lançamento realizado",
                options=list(range(len(correctable))),
                format_func=lambda index: (
                    f"{correctable.iloc[index]['competencia'].strftime('%m/%Y')} · "
                    f"{correctable.iloc[index]['tipo']} · {correctable.iloc[index]['historico']} · "
                    f"{format_brl(float(correctable.iloc[index]['realizado']))}"
                ),
                key=f"correction_record_{selected_year}",
            )
            correction = correctable.iloc[int(correction_index)]
            current_nature = clean_editor_text(correction.get("natureza"), "Operacional")
            correction_natures = list(NATURE_OPTIONS)
            if current_nature not in correction_natures:
                correction_natures.append(current_nature)
            settlement_value = correction.get("data_quitacao")
            if pd.isna(settlement_value):
                settlement_value = correction.get("competencia")
            settlement_default = settlement_value.date() if pd.notna(settlement_value) else date.today()

            correction_source_key = normalize_label(correction["origem"]).replace(" ", "_")
            with st.form(
                f"correct_realized_{selected_year}_{correction_source_key}_{int(correction['sheet_row'])}"
            ):
                c1, c2 = st.columns(2)
                corrected_type = c1.selectbox(
                    "Tipo", ["Receita", "Despesa"],
                    index=0 if correction["tipo"] == "Receita" else 1,
                )
                corrected_value = c2.number_input(
                    "Valor realizado correto",
                    min_value=0.0,
                    value=float(correction["realizado"]),
                    step=100.0,
                    format="%.2f",
                )
                c3, c4 = st.columns(2)
                corrected_description = c3.text_input("Lançamento", value=str(correction["historico"]))
                corrected_category = c4.text_input("Categoria", value=str(correction["categoria"]))
                c5, c6 = st.columns(2)
                corrected_nature = c5.selectbox(
                    "Natureza",
                    correction_natures,
                    index=correction_natures.index(current_nature),
                )
                corrected_date = c6.date_input(
                    "Data da quitação/recebimento",
                    value=settlement_default,
                    format="DD/MM/YYYY",
                )
                reopen_launch = st.checkbox(
                    "Reabrir este lançamento como pendente",
                    help="O saldo ainda não realizado voltará a afetar a projeção.",
                )
                delete_launch = st.checkbox(
                    "Excluir este lançamento incorreto",
                    help=(
                        "Ele deixará de aparecer e de afetar os cálculos. Uma cópia completa será guardada "
                        "em Lancamentos_Excluidos para possível recuperação."
                    ),
                )
                correction_reason = st.text_area(
                    "Motivo da correção",
                    placeholder="Exemplo: valor informado incorretamente na baixa.",
                )
                save_correction = st.form_submit_button("Salvar correção ou exclusão", type="primary")

            if save_correction:
                if not correction_reason.strip():
                    st.error("Informe o motivo da correção ou exclusão para manter a rastreabilidade.")
                elif delete_launch:
                    now = datetime.now().strftime("%d/%m/%Y %H:%M")
                    target_ws = ws_history if correction["origem"] == "Histórico" else ws_forecast
                    source_records = load_records(target_ws)
                    source_index = int(correction["sheet_row"]) - 2
                    if not 0 <= source_index < len(source_records):
                        st.error("O lançamento mudou de posição. Recarregue a página e tente novamente.")
                    else:
                        source_record = dict(source_records[source_index])
                        archived_record = {
                            header: source_record.get(header, "") for header in MAIN_HEADERS
                        }
                        archived_record.update({
                            "Excluído Em": now,
                            "Usuário": st.session_state.get("usuario_fin", ""),
                            "Origem": correction["origem"],
                            "Linha Original": int(correction["sheet_row"]),
                            "Motivo": correction_reason.strip(),
                        })
                        append_dicts(
                            ws_deleted_launches,
                            DELETED_LAUNCH_HEADERS,
                            [archived_record],
                        )
                        delete_sheet_rows(target_ws, [int(correction["sheet_row"])])
                        append_dicts(ws_correction_log, CORRECTION_LOG_HEADERS, [{
                            "Corrigido Em": now,
                            "Usuário": st.session_state.get("usuario_fin", ""),
                            "Origem": correction["origem"],
                            "Linha": int(correction["sheet_row"]),
                            "ID": correction["id"],
                            "Tipo": correction["tipo"],
                            "Lançamento": correction["historico"],
                            "Antes": json.dumps(source_record, ensure_ascii=False),
                            "Depois": json.dumps({
                                "Excluído": True,
                                "Arquivo": "Lancamentos_Excluidos",
                            }, ensure_ascii=False),
                            "Motivo": correction_reason.strip(),
                        }])
                        st.success(
                            "Lançamento excluído dos cálculos e guardado em Lancamentos_Excluidos."
                        )
                        st.rerun()
                elif not corrected_description.strip():
                    st.error("Informe o nome do lançamento.")
                elif corrected_value <= 0 and not reopen_launch:
                    st.error("Para zerar um valor realizado, marque a opção de reabrir o lançamento.")
                else:
                    corrected_status = (
                        "Parcial" if reopen_launch and corrected_value > 0
                        else "Previsto" if reopen_launch
                        else str(correction["status"])
                    )
                    before = {
                        "Tipo": str(correction["tipo"]),
                        "Lançamento": str(correction["historico"]),
                        "Categoria": str(correction["categoria"]),
                        "Natureza": current_nature,
                        "Valor realizado": float(correction["realizado"]),
                        "Data": settlement_default.strftime("%d/%m/%Y"),
                        "Status": str(correction["status"]),
                    }
                    after = {
                        "Tipo": corrected_type,
                        "Lançamento": corrected_description.strip(),
                        "Categoria": corrected_category.strip() or "OUTRO",
                        "Natureza": corrected_nature,
                        "Valor realizado": float(corrected_value),
                        "Data": corrected_date.strftime("%d/%m/%Y"),
                        "Status": corrected_status,
                    }
                    if before == after:
                        st.info("Nenhuma alteração foi identificada.")
                    else:
                        now = datetime.now().strftime("%d/%m/%Y %H:%M")
                        target_ws = ws_history if correction["origem"] == "Histórico" else ws_forecast
                        update_row(target_ws, int(correction["sheet_row"]), {
                            "Tipo de Operação": after["Tipo"],
                            "Histórico": after["Lançamento"],
                            "Categoria": after["Categoria"],
                            "Natureza": after["Natureza"],
                            "Valor Realizado (R$)": format_brl(after["Valor realizado"]),
                            "Data Quitação": after["Data"],
                            "Status": after["Status"],
                            "Atualizado Em": now,
                        })
                        append_dicts(ws_correction_log, CORRECTION_LOG_HEADERS, [{
                            "Corrigido Em": now,
                            "Usuário": st.session_state.get("usuario_fin", ""),
                            "Origem": correction["origem"],
                            "Linha": int(correction["sheet_row"]),
                            "ID": correction["id"],
                            "Tipo": after["Tipo"],
                            "Lançamento": after["Lançamento"],
                            "Antes": json.dumps(before, ensure_ascii=False),
                            "Depois": json.dumps(after, ensure_ascii=False),
                            "Motivo": correction_reason.strip(),
                        }])
                        st.success("Lançamento corrigido e registrado no histórico de alterações.")
                        st.rerun()

    st.subheader("Diferenças de lançamentos encerrados")
    history = variance(combined_history)
    if history.empty:
        st.info("Ainda não existem lançamentos encerrados com valor realizado.")
    else:
        history = history[history["competencia"].dt.year == selected_year].copy()
        view = history[["competencia", "tipo", "categoria", "historico", "previsto", "realizado", "variacao", "conta"]]
        display_money_table(view, ["previsto", "realizado", "variacao"])
        if not history.empty:
            summary = history.groupby("historico", dropna=False).agg(previsto=("previsto", "sum"), realizado=("realizado", "sum"), variacao=("variacao", "sum")).reset_index()
            st.subheader("Diferenças acumuladas por lançamento")
            display_money_table(summary.sort_values("variacao", key=lambda s: s.abs(), ascending=False), ["previsto", "realizado", "variacao"])

with tab_adjustments:
    st.header("Acertos")
    st.caption("Controles independentes do forecast, saldos bancários, obras e retiradas. Cada movimento fica salvo no Google Sheets para preservar o histórico.")

    render_loan_adjustment("Empréstimo MRC x Marcos Veloso", ws_loan_marcos, "loan_marcos", allow_interest=True)
    st.divider()
    render_loan_adjustment("Empréstimo MRC x Torre Forte", ws_loan_torre, "loan_torre")
    st.divider()

    st.subheader("Acertos particulares — Marcio e Marcelo")
    st.caption("Despesas pagas pessoalmente entram positivas (valor a reembolsar). Créditos, receitas e o acerto no salário entram negativos. Cada competência é encerrada manualmente, sem apagar o histórico.")
    partner_records = load_records(ws_partner_settlements)
    competences = sorted({clean_editor_text(item.get("Competência")) for item in partner_records if clean_editor_text(item.get("Competência"))}, reverse=True)
    current_competence = today.strftime("%m/%Y")
    if current_competence not in competences:
        competences.insert(0, current_competence)
    selected_settlement_competence = st.selectbox("Competência dos acertos", competences, key="partner_settlement_competence")
    partner_ledger = partner_settlement_ledger(partner_records, selected_settlement_competence)

    totals = {
        partner: float(partner_ledger.loc[partner_ledger["Sócio"] == partner, "Valor"].sum())
        for partner in ("Marcelo", "Marcio")
    }
    c1, c2 = st.columns(2)
    c1.metric("Saldo Marcelo", format_brl(totals["Marcelo"]), help="Positivo: complementar no salário. Negativo: abater no salário.")
    c2.metric("Saldo Marcio", format_brl(totals["Marcio"]), help="Positivo: complementar no salário. Negativo: abater no salário.")

    if partner_ledger.empty:
        st.info("Não há movimentos nesta competência.")
    else:
        partner_editor = st.data_editor(
            partner_ledger[["sheet_row", "ID", "Competência", "Data", "Sócio", "Tipo", "Histórico", "Valor", "Saldo"]],
            use_container_width=True,
            hide_index=True,
            disabled=["sheet_row", "ID", "Competência", "Saldo"],
            column_config={
                "sheet_row": None,
                "ID": None,
                "Data": st.column_config.DateColumn(format="DD/MM/YYYY", required=True),
                "Sócio": st.column_config.SelectboxColumn(options=["Marcelo", "Marcio"], required=True),
                "Tipo": st.column_config.SelectboxColumn(options=["Despesa", "Crédito", "Acerto salarial"], required=True),
                "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", required=True),
                "Saldo": st.column_config.NumberColumn("Saldo do sócio", format="R$ %.2f"),
            },
            key=f"partner_editor_{selected_settlement_competence}",
        )
        if st.button("Salvar alterações dos acertos", key="partner_settlement_save", type="primary"):
            now = datetime.now().strftime("%d/%m/%Y %H:%M")
            for _, item in partner_editor.iterrows():
                movement_date = clean_editor_date(item["Data"])
                update_row(ws_partner_settlements, int(item["sheet_row"]), {
                    "Data": movement_date.strftime("%d/%m/%Y") if movement_date else "",
                    "Sócio": clean_editor_text(item["Sócio"]),
                    "Tipo": clean_editor_text(item["Tipo"]),
                    "Histórico": clean_editor_text(item["Histórico"]),
                    "Valor (R$)": format_brl(float(item["Valor"])),
                    "Atualizado Em": now,
                })
            st.success("Acertos atualizados.")
            st.rerun()

    with st.expander("Adicionar gasto, receita ou crédito"):
        with st.form("partner_settlement_new", clear_on_submit=True):
            a, b, c = st.columns(3)
            movement_date = a.date_input("Data", value=today, format="DD/MM/YYYY")
            partner = b.selectbox("Sócio", ["Marcelo", "Marcio"])
            kind = c.selectbox("Tipo", ["Despesa", "Crédito"])
            description = st.text_input("Histórico")
            amount = st.number_input("Valor", min_value=0.0, step=10.0)
            add_partner_movement = st.form_submit_button("Registrar acerto", type="primary")
        if add_partner_movement:
            if not description.strip() or amount <= 0:
                st.error("Informe o histórico e um valor maior que zero.")
            else:
                now = datetime.now().strftime("%d/%m/%Y %H:%M")
                signed_amount = amount if kind == "Despesa" else -amount
                append_dicts(ws_partner_settlements, PARTNER_SETTLEMENT_HEADERS, [{
                    "ID": new_id("ACERTO"), "Competência": selected_settlement_competence,
                    "Data": movement_date.strftime("%d/%m/%Y"), "Sócio": partner, "Tipo": kind,
                    "Histórico": description.strip(), "Valor (R$)": format_brl(signed_amount),
                    "Criado Em": now, "Atualizado Em": now,
                }])
                st.success("Movimento de acerto registrado.")
                st.rerun()

    with st.expander("Zerar competência com o acerto salarial"):
        st.warning("Esta ação não exclui nada: ela cria um lançamento de acerto salarial que compensa o saldo atual de cada sócio nesta competência.")
        if st.button("Registrar acerto salarial e zerar saldos", key="partner_settlement_close"):
            rows = []
            now = datetime.now().strftime("%d/%m/%Y %H:%M")
            for partner, total in totals.items():
                if abs(total) > 0.005:
                    rows.append({
                        "ID": new_id("ACERTO_SALARIO"), "Competência": selected_settlement_competence,
                        "Data": today.strftime("%d/%m/%Y"), "Sócio": partner, "Tipo": "Acerto salarial",
                        "Histórico": "Acerto salarial da competência", "Valor (R$)": format_brl(-total),
                        "Criado Em": now, "Atualizado Em": now,
                    })
            if not rows:
                st.info("Os saldos desta competência já estão zerados.")
            else:
                append_dicts(ws_partner_settlements, PARTNER_SETTLEMENT_HEADERS, rows)
                st.success("Acerto salarial registrado; os saldos foram zerados sem apagar o histórico.")
                st.rerun()


with tab_settings:
    st.subheader("Reservas e distribuição")
    if caution_sync_error is None:
        st.success(
            f"Cauções protegidas sincronizadas com a Gestão de Cauções: {format_brl(synced_caution)} "
            f"(projeção de dezembro/{selected_year})."
        )
    else:
        st.warning("A Gestão de Cauções está temporariamente indisponível. O valor manual salvo será usado até a próxima sincronização.")
    with st.form("parameters_form"):
        a, b = st.columns(2)
        caution = a.number_input(
            "Cauções protegidas",
            min_value=0.0,
            value=float(synced_caution),
            step=1000.0,
            disabled=caution_sync_error is None,
            help="Sincronizado automaticamente com a projeção de dezembro da Gestão de Cauções. O campo fica editável apenas se a integração estiver indisponível.",
        )
        reserve = b.number_input("Reserva MRC", min_value=0.0, value=float(parameters["reserva_mrc"]), step=1000.0)
        c, d = st.columns(2)
        partner1 = c.number_input("Percentual sócio 1", min_value=0.0, max_value=100.0, value=float(parameters["percentual_socio_1"]), step=1.0)
        partner2 = d.number_input("Percentual sócio 2", min_value=0.0, max_value=100.0, value=float(parameters["percentual_socio_2"]), step=1.0)
        save = st.form_submit_button("Salvar configurações", type="primary")
    if save:
        if abs(partner1 + partner2 - 100.0) > 0.01:
            st.error("Os percentuais dos dois sócios devem totalizar 100%.")
        else:
            save_parameters(ws_parameters, {
                "caucoes_protegidas": caution, "reserva_mrc": reserve,
                "percentual_socio_1": partner1, "percentual_socio_2": partner2,
            })
            st.toast("Configurações salvas.")
            st.rerun()

    st.markdown("---")
    st.subheader(f"Metas anuais de {selected_year}")
    st.caption(
        "Cadastre as metas definidas na reunião dos sócios. Cada meta fica vinculada somente ao ano selecionado."
    )
    selected_goal_records = [
        (row_number, goal)
        for row_number, goal in enumerate(load_records(ws_goals), start=2)
        if str(goal.get("Ano") or "").strip() == str(selected_year)
    ]
    if selected_goal_records:
        goals_editor_source = pd.DataFrame([{
            "Meta": str(goal.get("Meta") or ""),
            "Data da reunião": pd.to_datetime(
                goal.get("Data da Reunião"), dayfirst=True, errors="coerce"
            ).date(),
            "Tipo de apuração": str(goal.get("Tipo de Apuração") or "Manual"),
            "Filtro do lançamento": str(goal.get("Filtro do Lançamento") or ""),
            "Valor da meta": parse_money(goal.get("Valor da Meta (R$)")),
            "Valor atual informado": parse_money(goal.get("Valor Manual Atingido (R$)")),
            "sheet_row": row_number,
        } for row_number, goal in selected_goal_records])
        edited_goals = st.data_editor(
            goals_editor_source, use_container_width=True, hide_index=True,
            column_config={
                "Data da reunião": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Tipo de apuração": st.column_config.SelectboxColumn(
                    options=[
                        "Receitas realizadas no ano",
                        "Receitas realizadas no mês",
                        STABILIZED_RENT_GOAL_TYPE,
                        "Manual",
                    ],
                    required=True,
                ),
                "Valor da meta": st.column_config.NumberColumn(min_value=0.0, format="R$ %.2f"),
                "Valor atual informado": st.column_config.NumberColumn(
                    "Renda estabilizada / valor manual",
                    min_value=0.0,
                    format="R$ %.2f",
                    help="Para a meta de aluguel, informe a renda mensal estabilizada atual da carteira.",
                ),
                "sheet_row": None,
            },
            key=f"goals_editor_{selected_year}",
        )
        if st.button("Salvar metas deste ano", type="primary"):
            now = datetime.now().strftime("%d/%m/%Y %H:%M")
            for _, goal in edited_goals.iterrows():
                meeting_date = goal["Data da reunião"]
                if isinstance(meeting_date, pd.Timestamp):
                    meeting_date = meeting_date.date()
                update_row(ws_goals, int(goal["sheet_row"]), {
                    "Meta": str(goal["Meta"]).strip(),
                    "Data da Reunião": meeting_date.strftime("%d/%m/%Y"),
                    "Tipo de Apuração": str(goal["Tipo de apuração"]),
                    "Filtro do Lançamento": str(goal["Filtro do lançamento"]).strip(),
                    "Valor da Meta (R$)": format_brl(float(goal["Valor da meta"])),
                    "Valor Manual Atingido (R$)": format_brl(float(goal["Valor atual informado"])),
                    "Atualizado Em": now,
                })
            st.success("Metas atualizadas.")
            st.rerun()
    else:
        st.info("Nenhuma meta cadastrada para este ano.")

    with st.expander("Cadastrar nova meta"):
        with st.form("new_annual_goal", clear_on_submit=True):
            a, b = st.columns(2)
            goal_name = a.text_input("Nome da meta")
            meeting_date = b.date_input("Data da reunião", value=date(selected_year - 1, 10, 1), format="DD/MM/YYYY")
            c, d = st.columns(2)
            goal_calculation = c.selectbox(
                "Tipo de apuração",
                [
                    "Receitas realizadas no ano",
                    "Receitas realizadas no mês",
                    STABILIZED_RENT_GOAL_TYPE,
                    "Manual",
                ],
            )
            goal_target = d.number_input("Valor da meta", min_value=0.0, step=1000.0)
            e, f = st.columns(2)
            goal_filter = e.text_input(
                "Filtro do lançamento",
                help="Exemplo: aluguel. Deixe em branco para considerar todas as receitas.",
            )
            manual_achieved = f.number_input(
                "Renda estabilizada / valor manual",
                min_value=0.0, step=1000.0,
                disabled=goal_calculation not in MANUAL_GOAL_TYPES,
            )
            add_goal = st.form_submit_button("Cadastrar meta", type="primary")
        if add_goal:
            if not goal_name or goal_target <= 0:
                st.error("Informe o nome e um valor de meta maior que zero.")
            else:
                now = datetime.now().strftime("%d/%m/%Y %H:%M")
                append_dicts(ws_goals, GOAL_HEADERS, [{
                    "ID": new_id("META"), "Ano": selected_year,
                    "Data da Reunião": meeting_date.strftime("%d/%m/%Y"),
                    "Meta": goal_name, "Tipo de Apuração": goal_calculation,
                    "Filtro do Lançamento": goal_filter,
                    "Valor da Meta (R$)": format_brl(goal_target),
                    "Valor Manual Atingido (R$)": (
                        format_brl(manual_achieved) if goal_calculation in MANUAL_GOAL_TYPES else ""
                    ),
                    "Criado Em": now, "Atualizado Em": now,
                }])
                st.success("Meta cadastrada.")
                st.rerun()

    st.markdown("---")
    st.subheader("Importar previsão")
    st.caption("Use este recurso apenas para trazer uma previsão inicial. Linhas cujo ID já exista não serão duplicadas.")
    forecast_file = st.file_uploader("Arquivo da previsão", type=["tsv", "csv"], key="forecast_import")
    if forecast_file is not None:
        raw = forecast_file.getvalue()
        separator = "\t" if forecast_file.name.lower().endswith(".tsv") else ";"
        try:
            imported = pd.read_csv(io.BytesIO(raw), sep=separator, dtype=str, keep_default_na=False)
        except Exception as exc:
            st.error(f"Não foi possível ler o arquivo: {exc}")
            imported = pd.DataFrame()
        missing_headers = [header for header in MAIN_HEADERS if header not in imported.columns]
        if missing_headers:
            st.error("O arquivo não tem todas as colunas esperadas.")
        elif not imported.empty:
            existing_ids = {str(item.get("ID", "")).strip() for item in load_records(ws_forecast)}
            new_records = imported[~imported["ID"].astype(str).str.strip().isin(existing_ids)].copy()
            st.info(f"{len(imported)} linhas lidas; {len(new_records)} novas linhas prontas para importar.")
            if st.button("Importar novas linhas", type="primary", disabled=new_records.empty):
                append_dicts(ws_forecast, MAIN_HEADERS, new_records.to_dict("records"))
                st.toast(f"{len(new_records)} lançamentos importados.")
                st.rerun()

    st.markdown("---")
    st.write("**Distribuição estimada no final do ano**")
    d1, d2, d3 = st.columns(3)
    d1.metric("Total distribuível", format_brl(distributable))
    d2.metric("Sócio 1", format_brl(max(distributable, 0) * parameters["percentual_socio_1"] / 100))
    d3.metric("Sócio 2", format_brl(max(distributable, 0) * parameters["percentual_socio_2"] / 100))
