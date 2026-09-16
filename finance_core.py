from __future__ import annotations

import calendar
import hashlib
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


def fx_balance_brl(amount: float, quotation: float, percentage: float = 100.0) -> float:
    """Convert a foreign-currency balance to BRL using the selected valuation percentage."""
    return max(0.0, float(amount)) * max(0.0, float(quotation)) * max(0.0, float(percentage)) / 100.0


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


def is_caution_interest_reserve(value: object) -> bool:
    text = normalize_label(value)
    return "juros" in text and ("caucao" in text or "reserva protegida" in text)


def is_customer_pass_through_balance(value: object) -> bool:
    text = normalize_label(value)
    return "superlogica" in text or "repasses a clientes" in text


def is_advance_customer_payment_balance(value: object) -> bool:
    text = normalize_label(value)
    return "boleto" in text and "pago" in text and "adiant" in text


def is_pending_construction_adjustment_balance(value: object) -> bool:
    text = normalize_label(value)
    return "acerto" in text and "obra" in text and "pendente" in text


def is_distribution_liability_balance(value: object) -> bool:
    return any(
        checker(value)
        for checker in (
            is_customer_pass_through_balance,
            is_advance_customer_payment_balance,
            is_pending_construction_adjustment_balance,
        )
    )


def is_profit_withdrawal_nature(value: object) -> bool:
    """Return whether a launch is a partner profit withdrawal, not an operating expense."""
    return normalize_label(value) in {
        "retirada",
        "lucros",
        "retirada de lucro",
        "retirada de lucros",
        "retirada de socio",
        "retirada de socios",
    }


def customer_pass_through_distribution_effect(value: object) -> float:
    """Positive client payables reduce distribution; negative balances increase it."""
    return -parse_money(value)


def distributable_balance(year_end: float, protected: float, liabilities: float = 0.0) -> float:
    return float(year_end) - float(protected) - float(liabilities)


def normalize_works(records: list[dict], default_year: int = 2026) -> pd.DataFrame:
    """Normalize construction jobs and calculate receivables, payables and profit."""
    rows = []
    for sheet_row, record in enumerate(records, start=2):
        competence = month_start(record.get("Competência"), default_year)
        charged = parse_money(record.get("Valor Cobrado (R$)"))
        received = parse_money(record.get("Valor Recebido (R$)"))
        planned_cost = parse_money(record.get("Custo Previsto (R$)"))
        paid = parse_money(record.get("Valor Pago (R$)"))
        raw_status = normalize_label(record.get("Status") or "Em andamento")
        if raw_status == "cancelada":
            status = "Cancelada"
        elif raw_status in {"concluida", "concluido"} or (planned_cost > 0 and paid >= planned_cost):
            status = "Concluída"
        elif received > 0 or paid > 0 or raw_status == "parcial":
            status = "Parcial"
        else:
            status = "Em andamento"
        active = status != "Cancelada"
        rows.append({
            "sheet_row": sheet_row,
            "id": str(record.get("ID") or "").strip(),
            "competencia": competence,
            "obra": str(record.get("Obra / Histórico") or "").strip(),
            "cliente": str(record.get("Locador / Cliente") or "").strip(),
            "cobrado": charged,
            "recebido": received,
            "a_receber": max(charged - received, 0.0) if active else 0.0,
            "prestador": str(record.get("Prestador") or "").strip(),
            "pix": str(record.get("PIX do Prestador") or "").strip(),
            "custo_previsto": planned_cost,
            "pago": paid,
            "falta_pagar": max(planned_cost - paid, 0.0) if active else 0.0,
            "lucro_previsto": charged - planned_cost if active else 0.0,
            "resultado_caixa": received - paid if active else 0.0,
            "status": status,
            "observacao": str(record.get("Observação") or "").strip(),
        })
    return pd.DataFrame(rows)


def construction_payables(works: pd.DataFrame) -> float:
    if works.empty or "falta_pagar" not in works:
        return 0.0
    return float(works["falta_pagar"].sum())


def monthly_work_summary(works: pd.DataFrame, year: int) -> pd.DataFrame:
    months = pd.DataFrame({"competencia": pd.date_range(f"{year}-01-01", f"{year}-12-01", freq="MS")})
    months["mes"] = months["competencia"].dt.month.map(MESES)
    value_columns = [
        "cobrado", "recebido", "a_receber", "custo_previsto", "pago",
        "falta_pagar", "lucro_previsto", "resultado_caixa",
    ]
    if works.empty:
        for column in value_columns:
            months[column] = 0.0
        return months
    valid = works[
        works["competencia"].notna()
        & (works["competencia"].dt.year == year)
        & (works["status"] != "Cancelada")
    ].copy()
    if valid.empty:
        for column in value_columns:
            months[column] = 0.0
        return months
    grouped = valid.groupby("competencia", dropna=False)[value_columns].sum().reset_index()
    return months.merge(grouped, on="competencia", how="left").fillna(0.0)


def normalize_withdrawals(records: list[dict], default_year: int = 2026) -> pd.DataFrame:
    rows = []
    for sheet_row, record in enumerate(records, start=2):
        rows.append({
            "sheet_row": sheet_row,
            "competencia": month_start(record.get("Competência"), default_year),
            "pro_labore": parse_money(record.get("Pró-labore (R$)")),
            "lucros": parse_money(record.get("Retirada de Lucros (R$)")),
            "adicional": parse_money(record.get("Retirada Adicional (R$)")),
            "observacao": str(record.get("Observação") or "").strip(),
        })
    return pd.DataFrame(rows)


def withdrawal_summary(
    withdrawals: pd.DataFrame,
    year: int,
    through_month: int,
    partner_count: int = 2,
) -> dict[str, float]:
    months = max(0, min(int(through_month), 12))
    partners = max(int(partner_count), 1)
    if withdrawals.empty or months == 0:
        pro_labore = profits = additional = 0.0
    else:
        selected = withdrawals[
            withdrawals["competencia"].notna()
            & (withdrawals["competencia"].dt.year == int(year))
            & (withdrawals["competencia"].dt.month <= months)
        ]
        pro_labore = float(selected["pro_labore"].sum())
        profits = float(selected["lucros"].sum())
        additional = float(selected["adicional"].sum())
    total = pro_labore + profits + additional
    monthly_average = total / months if months else 0.0
    return {
        "pro_labore": pro_labore,
        "lucros": profits,
        "adicional": additional,
        "total": total,
        "meses": float(months),
        "media_mensal": monthly_average,
        "media_socio_mes": monthly_average / partners,
    }


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
    elif is_pending_construction_adjustment_balance(description):
        label = "Acertos de obras pendentes"
    elif "reserva" in description and "dolar" in description:
        label = "Reserva em dólar"
    elif is_caution_interest_reserve(description):
        label = "Reserva protegida — Juros de cauções"
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
    opened = df[df["status"].str.lower().isin(STATUS_ABERTOS)].copy()
    opened["pendente"] = (opened["previsto"] - opened["realizado"]).clip(lower=0.0)
    return opened


def realization_tracking(df: pd.DataFrame) -> pd.DataFrame:
    """Add the amount still open without losing the original planned amount."""
    if df.empty:
        result = df.copy()
        result["pendente"] = pd.Series(dtype=float)
        return result
    result = df.copy()
    result["pendente"] = (result["previsto"] - result["realizado"]).clip(lower=0.0)
    closed = ~result["status"].str.lower().isin(STATUS_ABERTOS)
    result.loc[closed, "pendente"] = 0.0
    return result


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
        months["retiradas"] = 0.0
        months["resultado"] = 0.0
        months["movimento_caixa"] = 0.0
        return months
    opened = opened[opened["competencia"].dt.year == year].copy()
    opened["grupo_fluxo"] = "despesas"
    opened.loc[opened["tipo"] == "Receita", "grupo_fluxo"] = "receitas"
    opened.loc[
        (opened["tipo"] == "Despesa")
        & opened["natureza"].map(is_profit_withdrawal_nature),
        "grupo_fluxo",
    ] = "retiradas"
    grouped = opened.groupby(["competencia", "grupo_fluxo"], dropna=False)["pendente"].sum().unstack(fill_value=0).reset_index()
    months = months.merge(grouped, on="competencia", how="left").fillna(0.0)
    for column in ("receitas", "despesas", "retiradas"):
        if column not in months:
            months[column] = 0.0
    months["resultado"] = months["receitas"] - months["despesas"]
    months["movimento_caixa"] = months["resultado"] - months["retiradas"]
    return months


def monthly_realized_history(df: pd.DataFrame, year: int) -> pd.DataFrame:
    months = pd.DataFrame({"competencia": pd.date_range(f"{year}-01-01", f"{year}-12-01", freq="MS")})
    months["mes"] = months["competencia"].dt.month.map(MESES)
    tracked = realization_tracking(df)
    if tracked.empty:
        months["receitas_realizadas"] = 0.0
        months["despesas_realizadas"] = 0.0
        months["retiradas_realizadas"] = 0.0
        months["resultado_realizado"] = 0.0
        return months
    tracked = tracked[(tracked["competencia"].dt.year == year) & (tracked["realizado"] > 0)].copy()
    tracked["grupo_realizado"] = "despesas_realizadas"
    tracked.loc[tracked["tipo"] == "Receita", "grupo_realizado"] = "receitas_realizadas"
    tracked.loc[
        (tracked["tipo"] == "Despesa")
        & tracked["natureza"].map(is_profit_withdrawal_nature),
        "grupo_realizado",
    ] = "retiradas_realizadas"
    grouped = tracked.groupby(["competencia", "grupo_realizado"], dropna=False)["realizado"].sum().unstack(fill_value=0).reset_index()
    months = months.merge(grouped, on="competencia", how="left").fillna(0.0)
    for column in ("receitas_realizadas", "despesas_realizadas", "retiradas_realizadas"):
        if column not in months:
            months[column] = 0.0
    months["resultado_realizado"] = months["receitas_realizadas"] - months["despesas_realizadas"]
    return months


def suggest_next_year_forecast(
    df: pd.DataFrame,
    source_year: int,
    target_year: int,
) -> pd.DataFrame:
    """Prepare next-year operating suggestions for explicit human approval."""
    columns = [
        "origem_chave", "tipo", "categoria", "historico", "envolvido",
        "conta", "natureza", "valor_sugerido", "periodicidade",
        "primeiro_vencimento", "ocorrencias", "dia_vencimento", "observacao",
    ]
    if df.empty or "competencia" not in df:
        return pd.DataFrame(columns=columns)

    source = df[
        df["competencia"].notna()
        & (df["competencia"].dt.year == int(source_year))
        & (df["status"].str.lower() != "cancelado")
    ].copy()
    if source.empty:
        return pd.DataFrame(columns=columns)

    excluded_natures = {
        "emprestimo a receber", "investimento", "reserva",
        "retirada de socios", "outro",
    }
    source = source[~source["natureza"].map(normalize_label).isin(excluded_natures)].copy()
    source = source[(source["previsto"] > 0) | (source["realizado"] > 0)].copy()
    if source.empty:
        return pd.DataFrame(columns=columns)

    identity_columns = ["tipo", "historico", "categoria", "envolvido"]
    for column in identity_columns:
        source[f"_{column}"] = source[column].map(normalize_label)
    source["_identity"] = source[[f"_{column}" for column in identity_columns]].agg("|".join, axis=1)
    source = source.sort_values(["_identity", "competencia", "sheet_row"])
    source = source.drop_duplicates(["_identity", "competencia"], keep="last")

    suggestions: list[dict] = []
    frequency_names = {1: "Mensal", 3: "Trimestral", 6: "Semestral", 12: "Anual"}
    for identity, group in source.groupby("_identity", sort=True):
        group = group.sort_values(["competencia", "sheet_row"])
        latest = group.iloc[-1]
        months = sorted(group["competencia"].dt.month.unique().tolist())
        gaps = [later - earlier for earlier, later in zip(months, months[1:])]
        needs_review = False

        if len(months) == 1:
            interval = 12
            occurrences = 1
        elif gaps and len(set(gaps)) == 1 and gaps[0] in {1, 3, 6}:
            interval = gaps[0]
            occurrences = ((12 - months[0]) // interval) + 1
        elif len(months) >= 6:
            interval = 1
            occurrences = 12 - months[0] + 1
            needs_review = True
        else:
            interval = 12
            occurrences = 1
            needs_review = True

        planned_value = float(latest["previsto"])
        if planned_value <= 0:
            planned_value = float(latest["realizado"])
        due = latest.get("vencimento")
        due_day = int(due.day) if pd.notna(due) else 1
        first_due = date(
            int(target_year), int(months[0]),
            min(due_day, calendar.monthrange(int(target_year), int(months[0]))[1]),
        )
        source_key = hashlib.sha1(
            f"{int(source_year)}|{int(target_year)}|{identity}".encode("utf-8")
        ).hexdigest()[:16].upper()
        note = f"Sugestão baseada nos lançamentos de {int(source_year)}."
        if needs_review:
            note += " Periodicidade irregular; confirme a frequência antes de aprovar."
        suggestions.append({
            "origem_chave": source_key,
            "tipo": latest["tipo"],
            "categoria": latest["categoria"],
            "historico": latest["historico"],
            "envolvido": latest["envolvido"],
            "conta": latest["conta"],
            "natureza": latest["natureza"],
            "valor_sugerido": planned_value,
            "periodicidade": frequency_names[interval],
            "primeiro_vencimento": first_due,
            "ocorrencias": int(occurrences),
            "dia_vencimento": due_day,
            "observacao": note,
        })
    return pd.DataFrame(suggestions, columns=columns)


def projection(monthly: pd.DataFrame, bank_balance: float, from_date: date) -> pd.DataFrame:
    result = monthly.copy()
    cutoff = pd.Timestamp(from_date.year, from_date.month, 1)
    result["aplicavel"] = result["competencia"] >= cutoff
    cash_movement = result["movimento_caixa"] if "movimento_caixa" in result else result["resultado"]
    result["movimento"] = cash_movement.where(result["aplicavel"], 0.0)
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

