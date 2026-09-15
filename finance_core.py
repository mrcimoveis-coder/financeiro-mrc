from __future__ import annotations

import calendar
import re
import uuid
from datetime import date, datetime
import unicodedata
from decimal import Decimal, InvalidOperation

import pandas as pd


MESES = {
    1: "JANEIRO",
    2: "FEVEREIRO",
    3: "MARÇO",
    4: "ABRIL",
    5: "MAIO",
    6: "JUNHO",
    7: "JULHO",
    8: "AGOSTO",
    9: "SETEMBRO",
    10: "OUTUBRO",
    11: "NOVEMBRO",
    12: "DEZEMBRO",
}
MESES_NUM = {nome: numero for numero, nome in MESES.items()}

STATUS_ABERTOS = {"pendente", "previsto", "atrasado", "parcial"}
STATUS_QUITADOS = {"quitado", "recebido", "confirmado", "pago"}


def parse_money(value) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    text = str(value).strip().replace("R$", "").replace("US$", "").replace(" ", "")
    if not text:
        return 0.0
    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return 0.0


def format_brl(value: float) -> str:
    return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def parse_date(value, default_year: int = 2026) -> pd.Timestamp:
    if value is None or str(value).strip() == "":
        return pd.NaT
    text = str(value).strip().upper()
    if text in MESES_NUM:
        return pd.Timestamp(default_year, MESES_NUM[text], 1)
    for dayfirst in (True, False):
        parsed = pd.to_datetime(value, dayfirst=dayfirst, errors="coerce")
        if pd.notna(parsed):
            return pd.Timestamp(parsed)
    return pd.NaT


def month_start(value, default_year: int = 2026) -> pd.Timestamp:
    parsed = parse_date(value, default_year)
    if pd.isna(parsed):
        return pd.NaT
    return parsed.to_period("M").to_timestamp()


def add_months(start: date, months: int, day: int | None = None) -> date:
    base_index = start.year * 12 + start.month - 1 + months
    year, month_zero = divmod(base_index, 12)
    month = month_zero + 1
    requested_day = day or start.day
    return date(year, month, min(requested_day, calendar.monthrange(year, month)[1]))


def normalize_status(value: str) -> str:
    text = str(value or "Pendente").strip().lower()
    if text in STATUS_QUITADOS:
        return "Quitado"
    if text == "cancelado":
        return "Cancelado"
    if text == "atrasado":
        return "Atrasado"
    if text == "parcial":
        return "Parcial"
    if text == "previsto":
        return "Previsto"
    return "Pendente"


def normalize_type(value: str) -> str:
    text = str(value or "Despesa").strip().lower()
    return "Receita" if text in {"receita", "entrada", "crédito", "credito"} else "Despesa"


def normalize_label(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(char for char in text if not unicodedata.combining(char)).casefold().split())


def operational_balance_item(record: dict) -> tuple[str, float] | None:
    """Convert imported point-in-time positions into signed balance items."""
    description = normalize_label(record.get("Histórico"))
    if description.startswith("saldos disponiveis superlogica"):
        label = "Superlógica — repasses a clientes"
    elif "recebimentos atrasados" in description and "meses anteriores" in description:
        label = "Recebimentos atrasados — meses anteriores"
    elif "recebimentos atrasados" in description and "mes atual" in description:
        label = "Recebimentos atrasados — mês atual"
    elif description == "emprestimo marcos veloso":
        label = "Empréstimo a receber — Marcos Veloso"
    elif description == "emprestimo compra sala clsw 304":
        label = "Empréstimo a receber — Compra Sala CLSW 304"
    else:
        return None

    value = parse_money(record.get("Valor Previsto (R$)"))
    if value == 0:
        value = parse_money(record.get("Valor (R$)"))
    signed_value = abs(value) if normalize_type(record.get("Tipo de Operação")) == "Receita" else -abs(value)
    return label, signed_value


def normalize_launches(records: list[dict], default_year: int = 2026) -> pd.DataFrame:
    rows = []
    for sheet_row, record in enumerate(records, start=2):
        if operational_balance_item(record) is not None:
            continue
        competence = month_start(record.get("Competência") or record.get("Mês"), default_year)
        due = parse_date(record.get("Vencimento"), default_year)
        if pd.isna(due) and pd.notna(competence):
            due = competence
                    
            
        planned = parse_money(record.get("Valor Previsto (R$)"))
        if planned == 0:
            planned = parse_money(record.get("Valor (R$)"))
        actual = parse_money(record.get("Valor Realizado (R$)"))
        raw_status = str(record.get("Status") or "").strip().lower()
        status = normalize_status(raw_status)
        if raw_status == "confirmado" and actual == 0:
            actual = planned
        launch_type = normalize_type(record.get("Tipo de Operação"))
        currency = str(record.get("Moeda") or "BRL").strip().upper()
        currency_value = parse_money(record.get("Valor na Moeda"))
        quotation = parse_money(record.get("Cotação Utilizada"))
        considered = parse_money(record.get("Percentual Considerado")) or 100.0
        if currency == "USD" and currency_value and quotation:
            planned = currency_value * quotation * considered / 100.0
        rows.append(
            {
                "sheet_row": sheet_row,
                "id": str(record.get("ID") or "").strip(),
                "competencia": competence,
                "vencimento": due,
                "tipo": launch_type,
                "categoria": str(record.get("Categoria") or "OUTRO").strip(),
                "envolvido": str(record.get("Corretor / Envolvido") or "").strip(),
                "historico": str(record.get("Histórico") or "").strip(),
                "previsto": planned,
                "realizado": actual,
                "status": status,
                "observacao": str(record.get("Observação") or "").strip(),
                "conta": str(record.get("Conta") or "").strip(),
                "natureza": str(record.get("Natureza") or "Operacional").strip(),
                "serie_id": str(record.get("Série ID") or "").strip(),
                "moeda": currency,
                "valor_moeda": currency_value,
                "cotacao": quotation,
                "percentual": considered,
            }
        )
    return pd.DataFrame(rows)


def open_launches(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df[df["status"].str.lower().isin(STATUS_ABERTOS)].copy()


def monthly_forecast(df: pd.DataFrame, year: int) -> pd.DataFrame:
    months = pd.DataFrame(
        {
            "competencia": pd.date_range(f"{year}-01-01", f"{year}-12-01", freq="MS"),
        }
    )
    months["mes"] = months["competencia"].dt.month.map(MESES)
    opened = open_launches(df)
    if opened.empty:
        months["receitas"] = 0.0
        months["despesas"] = 0.0
        months["resultado"] = 0.0
        return months
    opened = opened[opened["competencia"].dt.year == year].copy()
    opened["signed"] = opened["previsto"].where(opened["tipo"] == "Receita", -opened["previsto"])
    grouped = opened.groupby(["competencia", "tipo"], dropna=False)["previsto"].sum().unstack(fill_value=0)
    grouped = grouped.rename(columns={"Receita": "receitas", "Despesa": "despesas"}).reset_index()
    months = months.merge(grouped, on="competencia", how="left").fillna(0.0)
    for column in ("receitas", "despesas"):
        if column not in months:
            months[column] = 0.0
    months["resultado"] = months["receitas"] - months["despesas"]
    return months


def projection(monthly: pd.DataFrame, bank_balance: float, from_date: date) -> pd.DataFrame:
    result = monthly.copy()
    cutoff = pd.Timestamp(from_date.year, from_date.month, 1)
    result["aplicavel"] = result["competencia"] >= cutoff
    result["movimento"] = result["resultado"].where(result["aplicavel"], 0.0)
    result["saldo_projetado"] = bank_balance + result["movimento"].cumsum()
    return result


def variance(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    settled = df[df["status"].str.lower().isin(STATUS_QUITADOS)].copy()
    settled["variacao"] = settled["realizado"] - settled["previsto"]
    return settled


def new_id(prefix: str = "LAN") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def make_recurrence_rows(
    *,
    description: str,
    launch_type: str,
    category: str,
    involved: str,
    planned_value: float,
    start_date: date,
    occurrences: int,
    interval_months: int,
    due_day: int,
    account: str,
    nature: str,
    notes: str,
) -> tuple[str, list[dict]]:
    series_id = new_id("SER")
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    rows = []
    for index in range(occurrences):
        due = add_months(start_date, index * interval_months, due_day)
        rows.append(
            {
                "Mês": MESES[due.month],
                "Tipo de Operação": normalize_type(launch_type),
                "Categoria": category,
                "Corretor / Envolvido": involved,
                "Histórico": description,
                "Valor (R$)": format_brl(planned_value),
                "Status": "Previsto",
                "Observação": notes,
                "ID": new_id(),
                "Competência": due.strftime("%m/%Y"),
                "Vencimento": due.strftime("%d/%m/%Y"),
                "Valor Previsto (R$)": format_brl(planned_value),
                "Valor Realizado (R$)": "",
                "Data Quitação": "",
                "Conta": account,
                "Natureza": nature,
                "Série ID": series_id,
                "Criado Em": now,
                "Atualizado Em": now,
                "Moeda": "BRL",
                "Valor na Moeda": "",
                "Cotação Utilizada": "",
                "Percentual Considerado": 100,
            }
        )
    return series_id, rows


def safe_day(value: int) -> int:
    return max(1, min(int(value), 31))


def clean_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value).strip().lower()).strip("_")
