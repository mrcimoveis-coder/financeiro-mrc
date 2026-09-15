from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials

from finance_core import (
    MESES,
    format_brl,
    make_recurrence_rows,
    monthly_forecast,
    new_id,
    normalize_launches,
    open_launches,
    parse_money,
    projection,
    safe_day,
    variance,
)


SHEET_ID = "1WaIP5FJpudjKvOXw0pQe7YfJlTPrISAmaBDZswuCsxM"
MAIN_HEADERS = [
    "Mês", "Tipo de Operação", "Categoria", "Corretor / Envolvido", "Histórico",
    "Valor (R$)", "Status", "Observação", "ID", "Competência", "Vencimento",
    "Valor Previsto (R$)", "Valor Realizado (R$)", "Data Quitação", "Conta",
    "Natureza", "Série ID", "Criado Em", "Atualizado Em", "Moeda",
    "Valor na Moeda", "Cotação Utilizada", "Percentual Considerado",
]
BALANCE_HEADERS = ["Conta", "Valor"]
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
    "percentual_usd": (95.0, "Percentual da reserva em dólar considerado no forecast"),
    "cotacao_manual_usd": (0.0, "Cotação manual; zero utiliza a PTAX de venda"),
}


st.set_page_config(page_title="Previsão Financeira | MRC Imóveis", page_icon="💰", layout="wide")

st.markdown(
    """
    <style>
    #MainMenu, footer {visibility:hidden}
    .block-container {padding-top:1.2rem; max-width:1450px}
    div[data-testid="stMetric"] {background:#fff; border:1px solid #e5e7eb; border-top:4px solid #c4001a; padding:14px; border-radius:10px}
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
    try:
        return ws.get_all_records(numericise_ignore=["all"])
    except Exception:
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
except Exception as exc:
    st.error(f"Não foi possível abrir a base Financeiro_MRC: {exc}")
    st.stop()

records = load_records(ws_forecast)
launches = normalize_launches(records)
history_launches = normalize_launches(load_records(ws_history))
balances_df, bank_balance = account_balances(ws_balances)
parameters = load_parameters(ws_parameters)
today = date.today()

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

tab_summary, tab_pending, tab_launch, tab_forecast, tab_balances, tab_history, tab_settings = st.tabs(
    ["Resumo", "Pendências", "Novo lançamento", "Forecast", "Saldos", "Histórico", "Configurações"]
)

monthly = monthly_forecast(launches, selected_year)
projected = projection(monthly, bank_balance, today)
open_df = open_launches(launches)
future_open = open_df[open_df["competencia"] >= pd.Timestamp(today.year, today.month, 1)] if not open_df.empty else open_df
pending_income = float(future_open.loc[future_open["tipo"] == "Receita", "previsto"].sum()) if not future_open.empty else 0.0
pending_expense = float(future_open.loc[future_open["tipo"] == "Despesa", "previsto"].sum()) if not future_open.empty else 0.0
year_end = float(projected.iloc[-1]["saldo_projetado"]) if not projected.empty else bank_balance
protected = parameters["caucoes_protegidas"] + parameters["reserva_mrc"]
distributable = year_end - protected

with tab_summary:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saldos atualizados", format_brl(bank_balance))
    c2.metric("Receitas pendentes", format_brl(pending_income))
    c3.metric("Despesas pendentes", format_brl(pending_expense))
    c4.metric("Sobra / falta projetada", format_brl(distributable))

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
    st.caption("Edite o previsto quando necessário e marque Quitado quando o pagamento ou recebimento já estiver refletido no saldo bancário.")
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
                "Quitado": False,
                "Vencimento": filtered["vencimento"].dt.strftime("%d/%m/%Y"),
                "Tipo": filtered["tipo"],
                "Lançamento": filtered["historico"],
                "Previsto": filtered["previsto"].astype(float),
                "Pago / recebido": filtered["previsto"].astype(float),
                "sheet_row": filtered["sheet_row"].astype(int),
                "serie_id": filtered["serie_id"],
                "competencia": filtered["competencia"],
            })
            edited = st.data_editor(
                editor_source,
                use_container_width=True,
                hide_index=True,
                disabled=["Vencimento", "Tipo", "Lançamento", "sheet_row", "serie_id", "competencia"],
                column_config={
                    "Quitado": st.column_config.CheckboxColumn("Quitado"),
                    "Previsto": st.column_config.NumberColumn("Valor previsto", min_value=0.0, format="R$ %.2f"),
                    "Pago / recebido": st.column_config.NumberColumn("Valor pago / recebido", min_value=0.0, format="R$ %.2f"),
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
                for index, edited_row in edited.iterrows():
                    original = editor_source.iloc[index]
                    updates = {}
                    planned_changed = abs(float(edited_row["Previsto"]) - float(original["Previsto"])) > 0.005
                    if planned_changed:
                        updates.update({
                            "Valor (R$)": format_brl(edited_row["Previsto"]),
                            "Valor Previsto (R$)": format_brl(edited_row["Previsto"]),
                        })
                        changed += 1
                        if propagate and str(edited_row["serie_id"]).strip():
                            later = open_df[
                                (open_df["serie_id"] == edited_row["serie_id"])
                                & (open_df["competencia"] > edited_row["competencia"])
                            ]
                            for _, later_row in later.iterrows():
                                update_row(ws_forecast, int(later_row["sheet_row"]), {
                                    "Valor (R$)": format_brl(edited_row["Previsto"]),
                                    "Valor Previsto (R$)": format_brl(edited_row["Previsto"]),
                                    "Atualizado Em": datetime.now().strftime("%d/%m/%Y %H:%M"),
                                })
                    if bool(edited_row["Quitado"]):
                        updates.update({
                            "Status": "Recebido" if edited_row["Tipo"] == "Receita" else "Pago",
                            "Valor Realizado (R$)": format_brl(edited_row["Pago / recebido"]),
                            "Data Quitação": today.strftime("%d/%m/%Y"),
                        })
                        settled += 1
                    if updates:
                        updates["Atualizado Em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                        update_row(ws_forecast, int(edited_row["sheet_row"]), updates)
                st.success(f"Alterações salvas: {changed} valor(es) ajustado(s) e {settled} lançamento(s) quitado(s).")
                if settled:
                    st.warning("Atualize os saldos reais das contas depois que os pagamentos ou recebimentos aparecerem no banco.")
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
    open_series = open_launches(launches)
    year_series = open_series[open_series["competencia"].dt.year == selected_year].copy() if not open_series.empty else open_series
    if year_series.empty:
        st.info("O forecast deste ano ainda não foi carregado.")
    else:
        year_series["mes_num"] = year_series["competencia"].dt.month
        matrix = year_series.pivot_table(
            index=["tipo", "historico"], columns="mes_num", values="previsto", aggfunc="sum", fill_value=0.0
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

with tab_balances:
    st.subheader("Saldos bancários e investimentos")
    st.caption("Informe o saldo real atual. Não desconte novamente os lançamentos já quitados: eles já estão refletidos nesses saldos.")
    edit = balances_df[BALANCE_HEADERS].copy()
    edited = st.data_editor(edit, use_container_width=True, hide_index=True, num_rows="dynamic")
    if st.button("Salvar todos os saldos", type="primary"):
        now = datetime.now().strftime("%d/%m/%Y às %H:%M")
        ws_balances.clear()
        ws_balances.update("A1", [BALANCE_HEADERS] + edited.fillna("").values.tolist(), value_input_option="USER_ENTERED")
        st.success(f"Saldos atualizados em {now}.")
        st.cache_data.clear()

with tab_history:
    st.subheader("Histórico e diferenças")
    combined_history = pd.concat([history_launches, launches], ignore_index=True) if not history_launches.empty else launches
    history = variance(combined_history)
    if history.empty:
        st.info("Ainda não existem quitações com valor realizado.")
    else:
        history = history[history["competencia"].dt.year == selected_year].copy()
        view = history[["competencia", "tipo", "categoria", "historico", "previsto", "realizado", "variacao", "conta"]]
        display_money_table(view, ["previsto", "realizado", "variacao"])
        if not history.empty:
            summary = history.groupby("historico", dropna=False).agg(previsto=("previsto", "sum"), realizado=("realizado", "sum"), variacao=("variacao", "sum")).reset_index()
            st.subheader("Diferenças acumuladas por lançamento")
            display_money_table(summary.sort_values("variacao", key=lambda s: s.abs(), ascending=False), ["previsto", "realizado", "variacao"])

with tab_settings:
    st.subheader("Reservas, distribuição e dólar")
    quote, quote_date = ptax_sale(today)
    if quote:
        st.info(f"PTAX de venda disponível: R$ {quote:.4f} em {quote_date.strftime('%d/%m/%Y')}.")
    else:
        st.warning("Não foi possível consultar a PTAX agora. A cotação manual poderá ser usada.")
    with st.form("parameters_form"):
        a, b = st.columns(2)
        caution = a.number_input("Cauções protegidas", min_value=0.0, value=float(parameters["caucoes_protegidas"]), step=1000.0)
        reserve = b.number_input("Reserva MRC", min_value=0.0, value=float(parameters["reserva_mrc"]), step=1000.0)
        c, d = st.columns(2)
        partner1 = c.number_input("Percentual sócio 1", min_value=0.0, max_value=100.0, value=float(parameters["percentual_socio_1"]), step=1.0)
        partner2 = d.number_input("Percentual sócio 2", min_value=0.0, max_value=100.0, value=float(parameters["percentual_socio_2"]), step=1.0)
        e, f = st.columns(2)
        usd_percent = e.number_input("Percentual considerado para USD", min_value=0.0, max_value=100.0, value=float(parameters["percentual_usd"]), step=1.0)
        usd_manual = f.number_input("Cotação manual do dólar (zero = PTAX)", min_value=0.0, value=float(parameters["cotacao_manual_usd"]), step=0.01, format="%.4f")
        save = st.form_submit_button("Salvar configurações", type="primary")
    if save:
        if abs(partner1 + partner2 - 100.0) > 0.01:
            st.error("Os percentuais dos dois sócios devem totalizar 100%.")
        else:
            save_parameters(ws_parameters, {
                "caucoes_protegidas": caution, "reserva_mrc": reserve,
                "percentual_socio_1": partner1, "percentual_socio_2": partner2,
                "percentual_usd": usd_percent, "cotacao_manual_usd": usd_manual,
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
