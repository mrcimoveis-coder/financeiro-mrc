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
- A aba Obras controla valor cobrado, recebimentos, custo previsto, pagamentos, prestador e PIX; o lucro previsto é calculado por competência.
- O saldo Acertos de obras pendentes é calculado automaticamente pela soma do que ainda falta pagar aos prestadores.
- Pagamentos de obras não alteram o saldo bancário automaticamente; o banco continua sendo atualizado manualmente na aba Saldos.
- A reserva em dólar é informada em USD nos Saldos e convertida pela PTAX de venda ou por uma cotação manual.
- A reserva para juros de cauções é alimentada manualmente nos Saldos e fica protegida da distribuição.
- Ao encerrar um lançamento, o valor previsto deixa de afetar a projeção, mesmo que o valor final seja diferente.
- O valor realizado permanece no histórico para mostrar o andamento e as diferenças finais.
- O forecast gera ocorrências mensais, trimestrais, semestrais ou anuais para qualquer ano.
- O sistema sugere o forecast do ano seguinte com base no ano selecionado. Cada sugestão pode ser ajustada, aprovada ou recusada antes de virar lançamento.
- Os anos são isolados: lançamentos de 2027 não alteram pendências, saldos ou sobra/falta de 2026. Na virada do calendário, o novo ano passa a ser aberto automaticamente como ano corrente.
- As metas definidas nas reuniões dos sócios ficam vinculadas ao respectivo ano e mostram o valor atingido com base nas receitas realizadas ou em uma apuração manual.
- A aba Retiradas registra por mês o pró-labore, a distribuição de lucros e as retiradas adicionais, com total e média por sócio. É um controle histórico e não reduz novamente o saldo bancário.
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

