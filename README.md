# Previsão Financeira MRC

Aplicativo Streamlit integrado ao Google Sheets `Financeiro_MRC`.

## Como funciona

- O saldo bancário atualizado representa tudo que já ocorreu.
- Somente receitas e despesas abertas entram na projeção futura.
- Cada lançamento mantém o valor previsto, o total já pago ou recebido e o saldo pendente.
- Pagamentos e recebimentos parciais reduzem somente o que ainda falta na projeção.
- Posições variáveis, como empréstimos e acertos de obras pendentes, são tratadas como saldos e não como novas receitas recorrentes.
- O Superlógica representa repasses a clientes: saldo positivo reduz a distribuição e saldo negativo aumenta a distribuição.
- Acertos de obras pendentes e boletos pagos adiantados seguem a mesma regra: valores positivos reduzem a distribuição.
- A reserva em dólar é informada em USD nos Saldos e convertida pela PTAX de venda ou por uma cotação manual.
- A reserva para juros de cauções é alimentada manualmente nos Saldos e fica protegida da distribuição.
- Ao encerrar um lançamento, o valor previsto deixa de afetar a projeção, mesmo que o valor final seja diferente.
- O valor realizado permanece no histórico para mostrar o andamento e as diferenças finais.
- O forecast gera ocorrências mensais, trimestrais, semestrais ou anuais para qualquer ano.
- O Histórico preserva o consolidado mensal de receitas e despesas realizadas e os lançamentos antigos ainda pendentes.
- Lançamentos em dólar podem utilizar automaticamente a PTAX de venda do Banco Central.

## Configuração no Streamlit

Além da seção já existente `gcp_service_account`, configure os usuários fora do GitHub:

```toml
[usuarios_financeiro]
usuario1 = "defina-uma-senha-nova"
usuario2 = "defina-outra-senha-nova"
```

Nunca publique o arquivo de segredos no repositório.

Na primeira execução, o aplicativo preserva as linhas existentes e acrescenta os campos e páginas necessários no Google Sheets.
