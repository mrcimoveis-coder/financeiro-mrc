import unittest
from datetime import date

from finance_core import (
    monthly_forecast,
    normalize_launches,
    operational_balance_item,
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
