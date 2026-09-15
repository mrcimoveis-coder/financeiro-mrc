# Previsão Financeira MRC

Aplicativo Streamlit integrado ao Google Sheets `Financeiro_MRC`.

## Como funciona

- O saldo bancário atualizado representa tudo que já ocorreu.
- Somente receitas e despesas abertas entram na projeção futura.
- Ao quitar um lançamento, o valor previsto deixa de afetar a projeção.
- O valor realizado permanece no histórico para mostrar diferenças.
- O forecast gera ocorrências mensais, trimestrais, semestrais ou anuais para qualquer ano.
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
