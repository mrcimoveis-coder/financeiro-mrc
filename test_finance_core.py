import unittest
from datetime import date

from finance_core import (
    customer_pass_through_distribution_effect,
    distributable_balance,
    monthly_forecast,
    monthly_realized_history,
    normalize_launches,
    operational_balance_item,
    fx_balance_brl,
    is_advance_customer_payment_balance,
    is_caution_interest_reserve,
    is_customer_pass_through_balance,
    is_distribution_liability_balance,
    is_pending_construction_adjustment_balance,
    projection,
    realization_tracking,
    variance,
)


def launch(description, launch_type, planned, actual, status):
    return {
        "Mês": "SETEMBRO",
        "Competência": "09/2026",
        "Vencimento": "15/09/2026",
        "Tipo de Operação": launch_type,
        "Histórico": description,
        "Valor Previsto (R$)": planned,
        "Valor Realizado (R$)": actual,
        "Status": status,
    }


class PartialRealizationTests(unittest.TestCase):
    def test_legacy_confirmed_rows_remain_in_monthly_history(self):
        legacy_revenue = {
            "Mês": "10/01/2026",
            "Tipo de Operação": "Receita",
            "Histórico": "Receita mensal consolidada",
            "Valor (R$)": 100_000,
            "Status": "confirmado",
        }
        legacy_expense = {
            "Mês": "JANEIRO",
            "Tipo de Operação": "Despesa",
            "Histórico": "Despesa consolidada",
            "Valor (R$)": 70_000,
            "Status": "confirmado",
        }
        normalized = normalize_launches([legacy_revenue, legacy_expense])
        january = monthly_realized_history(normalized, 2026).iloc[0]

        self.assertEqual(january["receitas_realizadas"], 100_000)
        self.assertEqual(january["despesas_realizadas"], 70_000)
        self.assertEqual(january["resultado_realizado"], 30_000)

    def test_balance_liabilities_reduce_distribution_when_positive(self):
        self.assertTrue(is_advance_customer_payment_balance("Boletos pagos adiantados"))
        self.assertTrue(is_pending_construction_adjustment_balance("Acertos de obras pendentes"))
        self.assertTrue(is_distribution_liability_balance("Boletos pagos adiantados"))
        self.assertTrue(is_distribution_liability_balance("Acertos de obras pendentes"))
        self.assertEqual(distributable_balance(100_000, 0, 10_000), 90_000)
        self.assertEqual(distributable_balance(100_000, 0, -10_000), 110_000)

    def test_corrupted_caution_label_is_still_protected(self):
        self.assertTrue(is_caution_interest_reserve("Reserva protegida - Juros de caucoes"))
        self.assertTrue(is_caution_interest_reserve("Reserva protegida � Juros de cau��es"))

    def test_customer_pass_through_uses_inverted_distribution_sign(self):
        self.assertTrue(is_customer_pass_through_balance("Superlógica — repasses a clientes"))
        self.assertTrue(is_customer_pass_through_balance("Saldos Disponíveis Superlogica"))
        self.assertEqual(customer_pass_through_distribution_effect(25_000), -25_000)
        self.assertEqual(customer_pass_through_distribution_effect(-25_000), 25_000)

    def test_dollar_reserve_is_a_balance_and_uses_selected_percentage(self):
        record = launch("Reserva em Dolares (ultima coluna)", "Receita", 9_823, 0, "Previsto")

        self.assertEqual(operational_balance_item(record), ("Reserva em dólar", 9_823))
        self.assertTrue(normalize_launches([record]).empty)
        self.assertEqual(fx_balance_brl(2_000, 5.17, 95), 9_823)

    def test_caution_interest_fund_is_a_protected_balance(self):
        record = launch("CAUÇÃO ALUGUEL (JUROS DO ANO)", "Despesa", 30_000, 0, "Previsto")

        self.assertTrue(is_caution_interest_reserve(record["Histórico"]))
        self.assertEqual(
            operational_balance_item(record),
            ("Reserva protegida — Juros de cauções", -30_000),
        )
        self.assertTrue(normalize_launches([record]).empty)

    def test_pending_construction_adjustments_are_treated_as_a_balance(self):
        record = launch("Acerto Obras Pendentes", "Receita", 25_000, 0, "Pendente")

        self.assertEqual(
            operational_balance_item(record),
            ("Acertos de obras pendentes", 25_000),
        )
        self.assertTrue(normalize_launches([record]).empty)

    def test_partial_receipts_and_expenses_use_only_the_remaining_amount(self):
        rows = [
            launch("Aluguel", "Receita", 85_000, 82_000, "Parcial"),
            launch("Advogado", "Despesa", 10_000, 4_000, "Parcial"),
        ]
        normalized = normalize_launches(rows)
        september = monthly_forecast(normalized, 2026).iloc[8]

        self.assertEqual(september["receitas"], 3_000)
        self.assertEqual(september["despesas"], 6_000)
        self.assertEqual(september["resultado"], -3_000)

    def test_closed_item_with_final_difference_no_longer_affects_forecast(self):
        normalized = normalize_launches([
            launch("Serviço encerrado", "Despesa", 1_000, 800, "Pago"),
        ])

        september = monthly_forecast(normalized, 2026).iloc[8]
        closed = variance(normalized).iloc[0]
        tracked = realization_tracking(normalized).iloc[0]

        self.assertEqual(september["despesas"], 0)
        self.assertEqual(closed["variacao"], -200)
        self.assertEqual(tracked["pendente"], 0)

    def test_bank_balance_plus_only_outstanding_values_drives_projection(self):
        normalized = normalize_launches([
            launch("Aluguel", "Receita", 85_000, 82_000, "Parcial"),
        ])
        monthly = monthly_forecast(normalized, 2026)
        projected = projection(monthly, 100_000, date(2026, 9, 15))

        self.assertEqual(projected.iloc[8]["saldo_projetado"], 103_000)
        self.assertEqual(projected.iloc[-1]["saldo_projetado"], 103_000)


if __name__ == "__main__":
    unittest.main()
