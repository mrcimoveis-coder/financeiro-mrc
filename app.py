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
    div[data-testid="stMetric"] {background:#fff; border:1px solid #e5e7eb; border-top:4px solid #c4001a; padding:14px; border-radius:10px}
    div[data-testid="stMetric"] [data-testid="stMetricLabel"],
    div[data-testid="stMetric"] [data-testid="stMetricValue"],
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] p,
    div[data-testid="stMetric"] [data-testid="stMetricValue"] div {color:#172033 !important; opacity:1 !important}
    @media (max-width: 768px) {
        div[data-testid="stMetric"] {min-height:104px; padding:12px}
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {font-size:1.45rem !important}
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
        ("Aluguel Mensal", "Receitas realizadas no mês", "aluguel", 100_000.0),
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


def achieved_goal_value(goal: dict, launches_df: pd.DataFrame, year: int, reference: date) -> float:
    calculation_type = str(goal.get("Tipo de Apuração") or "Manual")
    if calculation_type == "Manual":
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
except Exception as exc:
    st.error(f"Não foi possível abrir a base Financeiro_MRC: {exc}")
    st.stop()

records = load_records(ws_forecast)
launches = normalize_launches(records)
history_launches = normalize_launches(load_records(ws_history))
ensure_balance_rows(ws_balances)
ensure_initial_work_rows(ws_works)
ensure_initial_goals(ws_goals)
ensure_withdrawal_year(ws_withdrawals, 2026)
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

tab_summary, tab_pending, tab_launch, tab_forecast, tab_works, tab_withdrawals, tab_balances, tab_history, tab_settings = st.tabs(
    ["Resumo", "Pendências", "Novo lançamento", "Forecast", "Obras", "Retiradas", "Saldos", "Histórico", "Configurações"]
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
pending_expense = float(future_open.loc[future_open["tipo"] == "Despesa", "pendente"].sum()) if not future_open.empty else 0.0
year_end = float(projected.iloc[-1]["saldo_projetado"]) if not projected.empty else projection_base
protected = (synced_caution + parameters["reserva_mrc"] + interest_reserve) if is_current_year else 0.0
active_liabilities = distribution_liabilities if is_current_year else 0.0
distributable = distributable_balance(year_end, protected, active_liabilities)
combined_history = pd.concat([history_launches, launches], ignore_index=True) if not history_launches.empty else launches
withdrawal_month_limit = today.month if selected_year == today.year else (12 if selected_year < today.year else 0)
withdrawal_totals = withdrawal_summary(withdrawals, selected_year, withdrawal_month_limit, partner_count=2)

with tab_summary:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saldos atualizados" if is_current_year else "Saldo base do forecast", format_brl(projection_base))
    c2.metric("Receitas pendentes", format_brl(pending_income))
    c3.metric("Despesas pendentes", format_brl(pending_expense))
    c4.metric("Sobra / falta projetada", format_brl(distributable))
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
            goal_view.append({
                "Meta": str(goal.get("Meta") or ""),
                "Período": "Mensal" if goal.get("Tipo de Apuração") == "Receitas realizadas no mês" else "Anual",
                "Valor da meta": target,
                "Atingido": achieved,
                "Falta atingir": max(target - achieved, 0.0),
                "% atingido": (achieved / target * 100.0) if target > 0 else 0.0,
            })
        goal_frame = pd.DataFrame(goal_view)
        st.dataframe(
            goal_frame,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Valor da meta": st.column_config.NumberColumn(format="R$ %.2f"),
                "Atingido": st.column_config.NumberColumn(format="R$ %.2f"),
                "Falta atingir": st.column_config.NumberColumn(format="R$ %.2f"),
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
        display_money_table(
            quick_history_view,
            ["Receitas realizadas", "Despesas realizadas", "Resultado realizado"],
        )
    st.caption("O detalhamento completo continua disponível na aba Histórico.")

    st.markdown('<div class="status-note">Ao quitar um lançamento, ele deixa de afetar a projeção. O valor realizado fica apenas no histórico, pois o débito ou crédito já estará refletido no saldo bancário atualizado.</div>', unsafe_allow_html=True)
    st.subheader(f"Valores que ainda faltam em {selected_year}")
    remaining_view = projected[projected["aplicavel"]][["mes", "receitas", "despesas", "resultado"]].rename(
        columns={
            "mes": "Mês",
            "receitas": "Receitas a receber",
            "despesas": "Despesas a pagar",
            "resultado": "Resultado pendente",
        }
    )
    if remaining_view.empty:
        st.info("Não existem meses futuros para este ano.")
    else:
        total_remaining = pd.DataFrame([{
            "Mês": "TOTAL PENDENTE",
            "Receitas a receber": remaining_view["Receitas a receber"].sum(),
            "Despesas a pagar": remaining_view["Despesas a pagar"].sum(),
            "Resultado pendente": remaining_view["Resultado pendente"].sum(),
        }])
        remaining_view = pd.concat([remaining_view, total_remaining], ignore_index=True)
        display_money_table(
            remaining_view,
            ["Receitas a receber", "Despesas a pagar", "Resultado pendente"],
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
                    actual = float(edited_row["Pago / recebido acumulado"])
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
                    close_launch = bool(edited_row["Encerrar"]) or (planned > 0 and actual >= planned)
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
        nature = g.selectbox("Natureza", ["Operacional", "Empréstimo a receber", "Investimento", "Reserva", "Retirada de sócios", "Outro"])
        involved = h.text_input("Envolvido")
        account = i.text_input("Conta")
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
            row = {
                "Mês": MESES[due.month], "Tipo de Operação": launch_type, "Categoria": category,
                "Corretor / Envolvido": involved, "Histórico": description, "Valor (R$)": format_brl(planned_brl),
                "Status": "Pendente", "Observação": notes, "ID": new_id(), "Competência": due.strftime("%m/%Y"),
                "Vencimento": due.strftime("%d/%m/%Y"), "Valor Previsto (R$)": format_brl(planned_brl),
                "Valor Realizado (R$)": "", "Data Quitação": "", "Conta": account, "Natureza": nature,
                "Série ID": "", "Criado Em": now, "Atualizado Em": now, "Moeda": currency,
                "Valor na Moeda": amount if currency == "USD" else "", "Cotação Utilizada": used_quote if currency == "USD" else "",
                "Percentual Considerado": percent if currency == "USD" else 100,
            }
            append_dicts(ws_forecast, MAIN_HEADERS, [row])
            if currency == "USD" and quote:
                append_dicts(ws_quotes, QUOTE_HEADERS, [{"Data": quote_date.strftime("%d/%m/%Y"), "Moeda": "USD", "Compra": "", "Venda": quote, "Fonte": "BCB PTAX", "Consultado Em": now}])
            st.success("Lançamento salvo.")

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
        nature = i.selectbox("Natureza", ["Operacional", "Empréstimo a receber", "Investimento", "Reserva", "Retirada de sócios", "Outro"], key="forecast_nature")
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
        matrix = year_series.pivot_table(
            index=["tipo", "historico"], columns="mes_num", values="pendente", aggfunc="sum", fill_value=0.0
        ).reset_index()
        for month_number in range(1, 13):
            if month_number not in matrix:
                matrix[month_number] = 0.0
        matrix = matrix[["tipo", "historico", *range(1, 13)]].rename(
            columns={"tipo": "Tipo", "historico": "Lançamento", **MESES}
        )
        display_money_table(matrix, list(MESES.values()))

        st.subheader(f"Resumo mensal do forecast de {selected_year}")
        st.caption(
            "Os valores abaixo vêm dos mesmos lançamentos da matriz e são atualizados "
            "sempre que uma receita ou despesa é alterada."
        )
        monthly_summary = monthly[["mes", "receitas", "despesas", "resultado"]].rename(
            columns={
                "mes": "Mês",
                "receitas": "Receitas previstas",
                "despesas": "Despesas previstas",
                "resultado": "Resultado previsto",
            }
        )
        display_money_table(
            monthly_summary,
            ["Receitas previstas", "Despesas previstas", "Resultado previsto"],
        )

        annual_income = float(monthly["receitas"].sum())
        annual_expense = float(monthly["despesas"].sum())
        annual_result = annual_income - annual_expense
        st.subheader(f"Fechamento anual de {selected_year}")
        total_income, total_expense, total_result = st.columns(3)
        total_income.metric("Receitas previstas no ano", format_brl(annual_income))
        total_expense.metric("Despesas previstas no ano", format_brl(annual_expense))
        total_result.metric("Resultado previsto no ano", format_brl(annual_result))

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
            affected = editable_series[
                (editable_series["serie_id"] == selected_series)
                & (editable_series["competencia"] >= cutoff)
            ]
            for _, row in affected.iterrows():
                update_row(
                    ws_forecast,
                    int(row["sheet_row"]),
                    {
                        "Valor (R$)": format_brl(new_value),
                        "Valor Previsto (R$)": format_brl(new_value),
                        "Atualizado Em": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    },
                )
            st.success(f"{len(affected)} mês(es) atualizado(s).")
            st.rerun()

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
    edited = st.data_editor(edit, use_container_width=True, hide_index=True, num_rows="dynamic")
    if st.button("Salvar todos os saldos", type="primary"):
        now = datetime.now().strftime("%d/%m/%Y às %H:%M")
        ws_balances.clear()
        saved_balances = edited.fillna("").values.tolist()
        saved_balances.append(["Acertos de obras pendentes", format_brl(works_payable)])
        ws_balances.update("A1", [BALANCE_HEADERS] + saved_balances, value_input_option="USER_ENTERED")
        st.success(f"Saldos atualizados em {now}.")
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
            "Valor manual atingido": parse_money(goal.get("Valor Manual Atingido (R$)")),
            "sheet_row": row_number,
        } for row_number, goal in selected_goal_records])
        edited_goals = st.data_editor(
            goals_editor_source, use_container_width=True, hide_index=True,
            column_config={
                "Data da reunião": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Tipo de apuração": st.column_config.SelectboxColumn(
                    options=["Receitas realizadas no ano", "Receitas realizadas no mês", "Manual"],
                    required=True,
                ),
                "Valor da meta": st.column_config.NumberColumn(min_value=0.0, format="R$ %.2f"),
                "Valor manual atingido": st.column_config.NumberColumn(min_value=0.0, format="R$ %.2f"),
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
                    "Valor Manual Atingido (R$)": format_brl(float(goal["Valor manual atingido"])),
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
                ["Receitas realizadas no ano", "Receitas realizadas no mês", "Manual"],
            )
            goal_target = d.number_input("Valor da meta", min_value=0.0, step=1000.0)
            e, f = st.columns(2)
            goal_filter = e.text_input(
                "Filtro do lançamento",
                help="Exemplo: aluguel. Deixe em branco para considerar todas as receitas.",
            )
            manual_achieved = f.number_input(
                "Valor atingido manual",
                min_value=0.0, step=1000.0,
                disabled=goal_calculation != "Manual",
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
                    "Valor Manual Atingido (R$)": format_brl(manual_achieved) if goal_calculation == "Manual" else "",
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

