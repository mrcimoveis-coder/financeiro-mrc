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
import plotly.graph_objects as go
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
    normalize_works,
    open_launches,
    parse_money,
    projection,
    realization_tracking,
    safe_day,
    variance,
)


SHEET_ID = "1WaIP5FJpudjKvOXw0pQe7YfJlTPrISAmaBDZswuCsxM"
CAUCOES_SHEET_ID = "1OE3lN6bLUAemM_PyrsrVtN4BqMc-zrH1sCy5qzWGmrk"
MAIN_HEADERS = [
    "Mês", "Tipo de Operação", "Categoria", "Corretor / Envolvido", "Histórico",
    "Valor (R$)", "Status", "Observação", "ID", "Competência", "Vencimento",
    "Valor Previsto (R$)", "Valor Realizado (R$)", "Data Quitação", "Conta",
    "Natureza", "Série ID", "Criado Em", "Atualizado Em", "Moeda",
    "Valor na Moeda", "Cotação Utilizada", "Percentual Considerado",
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
    for attempt in range(4):
        try:
            return ws.get_all_records(numericise_ignore=["all"])
        except gspread.exceptions.APIError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status != 429 or attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return []


def append_dicts(ws, headers: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    ws.append_rows([[row.get(header, "") for header in headers] for row in rows], value_input_option="USER_ENTERED")


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
except Exception as exc:
    st.error(f"Não foi possível abrir a base Financeiro_MRC: {exc}")
    st.stop()

records = load_records(ws_forecast)
launches = normalize_launches(records)
history_launches = normalize_launches(load_records(ws_history))
ensure_balance_rows(ws_balances)
ensure_initial_work_rows(ws_works)
works = normalize_works(load_records(ws_works))
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
    available_years = sorted(
        {today.year, 2026, *([int(y) for y in launches["competencia"].dropna().dt.year.unique()] if not launches.empty else [])}
    )
    selected_year = st.selectbox("Ano do forecast", available_years, index=available_years.index(today.year) if today.year in available_years else 0)
    if st.button("Sair"):
        st.session_state.autenticado_fin = False
        st.rerun()

st.title("💰 Previsão financeira — MRC Imóveis")
st.caption("O saldo bancário representa o que já aconteceu. Somente receitas e despesas ainda abertas alteram a projeção futura.")

tab_summary, tab_pending, tab_launch, tab_forecast, tab_works, tab_balances, tab_history, tab_settings = st.tabs(
    ["Resumo", "Pendências", "Novo lançamento", "Forecast", "Obras", "Saldos", "Histórico", "Configurações"]
)

monthly = monthly_forecast(launches, selected_year)
projected = projection(monthly, bank_balance, today)
try:
    synced_caution = caution_projected_balance(selected_year)
    caution_sync_error = None
except Exception as exc:
    synced_caution = float(parameters["caucoes_protegidas"])
    caution_sync_error = str(exc)

if caution_sync_error is None and abs(float(parameters["caucoes_protegidas"]) - synced_caution) > 0.005:
    save_parameters(ws_parameters, {"caucoes_protegidas": synced_caution})
    parameters["caucoes_protegidas"] = synced_caution
open_df = open_launches(launches)
future_open = open_df[open_df["competencia"] >= pd.Timestamp(today.year, today.month, 1)] if not open_df.empty else open_df
pending_income = float(future_open.loc[future_open["tipo"] == "Receita", "pendente"].sum()) if not future_open.empty else 0.0
pending_expense = float(future_open.loc[future_open["tipo"] == "Despesa", "pendente"].sum()) if not future_open.empty else 0.0
year_end = float(projected.iloc[-1]["saldo_projetado"]) if not projected.empty else bank_balance
protected = synced_caution + parameters["reserva_mrc"] + interest_reserve
distributable = distributable_balance(year_end, protected, distribution_liabilities)
combined_history = pd.concat([history_launches, launches], ignore_index=True) if not history_launches.empty else launches

with tab_summary:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saldos atualizados", format_brl(bank_balance))
    c2.metric("Receitas pendentes", format_brl(pending_income))
    c3.metric("Despesas pendentes", format_brl(pending_expense))
    c4.metric("Sobra / falta projetada", format_brl(distributable))

    st.subheader("Receitas e despesas realizadas - meses anteriores")
    previous_month = pd.Timestamp(today.year, today.month, 1) - pd.offsets.MonthBegin(1)
    quick_history = monthly_realized_history(combined_history, selected_year)
    if selected_year == today.year:
        quick_history = quick_history[quick_history["competencia"] <= previous_month]
    quick_history_view = quick_history[[
        "mes", "receitas_realizadas", "despesas_realizadas", "resultado_realizado"
    ]].rename(columns={
        "mes": "Mês",
        "receitas_realizadas": "Receitas realizadas",
        "despesas_realizadas": "Despesas realizadas",
        "resultado_realizado": "Resultado realizado",
    })
    display_money_table(
        quick_history_view,
        ["Receitas realizadas", "Despesas realizadas", "Resultado realizado"],
    )
    st.caption("O detalhamento completo continua disponível na aba Histórico.")

    st.markdown('<div class="status-note">Ao quitar um lançamento, ele deixa de afetar a projeção. O valor realizado fica apenas no histórico, pois o débito ou crédito já estará refletido no saldo bancário atualizado.</div>', unsafe_allow_html=True)
    st.subheader(f"Projeção mensal de {selected_year}")
    fig = go.Figure()
    fig.add_bar(x=projected["mes"], y=projected["receitas"], name="Receitas pendentes", marker_color="#2e7d32")
    fig.add_bar(x=projected["mes"], y=projected["despesas"], name="Despesas pendentes", marker_color="#c4001a")
    fig.add_scatter(x=projected["mes"], y=projected["saldo_projetado"], name="Saldo projetado", mode="lines+markers", line={"color": "#8064a2", "width": 3}, yaxis="y2")
    fig.update_layout(
        barmode="group", height=460, legend={"orientation": "h"}, margin={"l": 20, "r": 20, "t": 20, "b": 20},
        yaxis={"title": "Movimentação"}, yaxis2={"title": "Saldo", "overlaying": "y", "side": "right"},
    )
    st.plotly_chart(fig, use_container_width=True)

    view = projected[["mes", "receitas", "despesas", "resultado", "saldo_projetado"]].rename(
        columns={"mes": "Mês", "receitas": "Receitas", "despesas": "Despesas", "resultado": "Resultado", "saldo_projetado": "Saldo projetado"}
    )
    display_money_table(view, ["Receitas", "Despesas", "Resultado", "Saldo projetado"])

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

