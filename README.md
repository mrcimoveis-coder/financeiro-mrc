# Manual do Financeiro MRC

O Financeiro MRC acompanha receitas, despesas, obrigações e disponibilidades da empresa. Acesse o módulo pelo portal da intranet, entre com seu usuário e confira o ano selecionado antes de consultar ou alterar dados. O aplicativo registra as informações no Google Sheets `Financeiro_MRC`.

**Escopo desta revisão.** O manual cobre a operação da versão de referência `c22be85` e, na seção [Painel e categorias](#painel-e-categorias), descreve as mudanças do PR #1. Use essa seção quando a aba **Receitas e Despesas** estiver disponível no Streamlit.

## Rotina de trabalho

1. Em **Novo lançamento** ou **Forecast**, registre os valores previstos e revise o vencimento.
2. Em **Pendências**, informe os pagamentos e recebimentos conforme forem ocorrendo.
3. Em **Saldos**, atualize o saldo real das contas após conferir os extratos.
4. Em **Resumo**, acompanhe a sobra ou falta projetada, os valores ainda abertos e as metas do ano.
5. Em **Histórico**, confira os valores realizados e corrija baixas quando necessário. Use **Receitas e Despesas**, quando disponível, para detalhar o peso de cada categoria.

### Como ler os valores

| Campo | O que representa |
| --- | --- |
| Previsto | Valor planejado para o lançamento. |
| Realizado | Valor pago ou recebido acumulado. Para baixas legadas reconhecidas como quitadas sem valor realizado informado, o sistema usa o valor previsto. |
| Pendente | Parcela que ainda falta pagar ou receber de um lançamento aberto. A baixa integral encerra a pendência mesmo que o valor final seja diferente do previsto. |
| Saldo bancário | Posição real informada em **Saldos**. Atualize após conferir os movimentos ocorridos. |
| Sobra projetada | Estimativa baseada na posição bancária, nos lançamentos abertos e nos ajustes aplicáveis. |
| Total distribuível | Estimativa para distribuição após considerar as reservas e obrigações aplicáveis. |

Exemplo. Uma despesa aberta de R$ 1.000 com R$ 600 pagos fica com R$ 600 realizados e R$ 400 pendentes. Se o fornecedor aceitar R$ 600 como quitação final, mantenha o valor realizado e encerre o lançamento. A pendência será zerada. Ao atualizar o saldo bancário pelo extrato, os R$ 600 pagos já estarão refletidos na posição real.

A competência organiza os relatórios por mês e ano. Os controles anuais usam o ano selecionado, e o ano corrente acompanha a virada do calendário. Confira a competência antes de comparar meses ou gerar ocorrências futuras.

## Resumo

Use **Resumo** para consultar os saldos, a projeção e as metas do ano selecionado. Consulte **Receitas e despesas realizadas até o momento** para ver o consolidado mensal e abrir o detalhamento de um mês. Consulte **Valores que ainda faltam** para verificar o que permanece em aberto.

As retiradas aparecem separadas na leitura do resultado. Na projeção mensal, o resultado operacional considera receitas e despesas operacionais conforme a classificação por natureza usada pelo aplicativo. O movimento de caixa previsto também considera as retiradas programadas. A aba **Retiradas** registra a série histórica dos valores por sócio.

## Novo lançamento

1. Escolha **Receita** ou **Despesa** e descreva o lançamento.
2. Informe categoria, vencimento, moeda e valor previsto. Preencha natureza, envolvido, conta e observações conforme o caso.
3. Em **Situação do lançamento**, selecione **Enviar para pendências** para um movimento futuro ou **Já pago / recebido** para um movimento que já ocorreu e já está refletido no saldo bancário.
4. Clique em **Salvar lançamento**. Confira o registro em **Pendências** ou **Histórico**, de acordo com a situação escolhida.

A descrição pode detalhar fornecedor, serviço ou referência. Use **Envolvido** para identificar a pessoa ou empresa que você quer filtrar. Em USD, o sistema calcula o valor em reais com a cotação aplicável e os parâmetros configurados.

## Pendências

1. Selecione o mês e filtre pelo tipo de lançamento, se necessário.
2. Para uma baixa parcial, atualize **Pago / recebido acumulado** com a soma de tudo que já foi pago ou recebido. Se já constam R$ 200 e você pagou outros R$ 150, informe R$ 350.
3. Quando a obrigação estiver quitada ou o recebimento concluído, confira o valor acumulado e marque **Encerrar**.
4. Clique em **Salvar alterações do mês** e confira o saldo real da conta.

A coluna **A pagar / receber** mostra a diferença ainda aberta. Se você corrigir o valor previsto de uma recorrência, a opção **Aplicar mudanças no valor previsto também aos meses seguintes da mesma série** propaga a alteração aos meses seguintes. Use-a quando o novo valor valer para a série.

## Forecast e matriz anual

### Programar ocorrências

Em **Programar lançamentos futuros**, informe nome, tipo, categoria, valor por ocorrência, primeiro vencimento, periodicidade, quantidade, dia de vencimento e natureza. Complete envolvido, conta e observações quando aplicável. Use **Criar forecast** para gerar a série mensal, trimestral, semestral ou anual. Cada ocorrência pode ser baixada individualmente.

### Editar a matriz

Na **Matriz anual**, cada linha organiza uma série ou um lançamento, com colunas de janeiro a dezembro. Os valores mensais representam o que está pendente. Para alterar uma previsão, edite o mês correspondente e salve a matriz. Ao editar a identificação da linha, como categoria, descrição ou envolvido, a alteração pode alcançar as ocorrências da série representadas na matriz. Revise a linha inteira antes de salvar.

Use **Alterar valores a partir de um mês** quando o novo valor passar a valer dali em diante para a mesma série. Use o **Resumo mensal do forecast** e o **Fechamento anual** para conferir o efeito das alterações.

### Preparar o ano seguinte

Em **Preparar forecast**, revise as sugestões geradas a partir do ano de referência. Confira descrição, categoria, valor, periodicidade, primeiro vencimento e número de ocorrências. Selecione **Aprovar** para gerar os lançamentos, **Não incluir** para recusar ou **Pendente** para continuar a revisão depois. Clique em **Salvar rascunho e processar decisões**. Depois da aprovação, confira o ano de destino.

## Painel e categorias

*Recursos documentados no PR #1, com publicação no Streamlit a confirmar.*

### Consultar o painel

1. Selecione o ano e abra **Receitas e Despesas**.
2. Escolha um ou mais meses. Sem seleção, o painel considera o ano selecionado.
3. Escolha **Despesa** ou **Receita** e alterne entre **Realizado** e **Pendente**. Use **Natureza** para separar, por exemplo, itens operacionais e retiradas.
4. Refine por **Categoria**, **Envolvido** ou **Buscar descrição**.
5. Confira **Total do período**, **Total filtrado** e **Participação no período**. O total do período considera mês, tipo, natureza e a visão escolhida. O total filtrado aplica também categoria, envolvido e busca.

O gráfico empilha as categorias por mês. A tabela de categorias mostra a participação no total do período, e a lista **Lançamentos** mostra a competência, categoria, categoria original, histórico, envolvido, natureza e valores. Para comparar o peso de uma despesa com o total geral de despesas, deixe o filtro **Natureza** sem seleção. Para calcular sua participação entre despesas operacionais, filtre a natureza antes de escolher a categoria.

O painel consulta os lançamentos do Financeiro e o histórico correspondente. Obras, vendas, acertos e retiradas mantidos exclusivamente nos respectivos controles têm consultas próprias. Uma retirada programada como lançamento aparece no painel pela sua natureza.

### Escolher ou criar uma categoria

O **Tipo** identifica se o lançamento é receita ou despesa. A **Categoria** identifica o grupo, como **SALÁRIO**, **GESTÃO - TI**, **COMISSÕES**, **BANCO** ou **IMPOSTOS**. A **Natureza** informa o tratamento do lançamento, como **Operacional** ou retirada. O **Histórico** guarda a descrição livre.

- Em **Novo lançamento** e **Programar lançamentos futuros**, selecione uma categoria existente. Para criar uma, selecione **Criar nova categoria**, preencha **Nome da nova categoria** e salve.
- Ao tentar salvar sem categoria válida, o sistema bloqueia o lançamento. Se reconhecer a descrição, mostra uma sugestão para você selecionar ou substituir.
- Para usar uma categoria nova na matriz ou na revisão do ano seguinte, abra **Cadastrar categoria para a matriz e as sugestões**, cadastre o nome e volte à linha para selecioná-lo.
- Novas linhas ou ocorrências na matriz e sugestões aprovadas no Forecast precisam de categoria cadastrada. Uma correção de categoria no **Histórico** também exige um nome cadastrado.

### Revisar séries e lançamentos antigos

No Forecast, abra **Sugestões para classificar séries existentes**. A lista mostra a descrição, a categoria atual e a sugestão, quando houver. Selecione a categoria na matriz e salve para aplicá-la à série representada. Por exemplo, confira se **Telefone Net** corresponde a **INTERNET E TELEFONIA** e se **Superlogica - Software** corresponde a **GESTÃO - TI**.

Categorias antigas sem correspondência no catálogo aparecem no painel como **A classificar**. A coluna **Categoria original** ajuda na conferência. Use **Histórico** para corrigir individualmente um lançamento baixado. Na versão documentada do PR, a importação inicial em **Configurações** grava a categoria do arquivo. Revise as categorias do arquivo antes da importação.

## Obras

Em **Obras do mês e pendências anteriores**, consulte obras em andamento e obrigações anteriores. Para cadastrar, informe a identificação da obra, a competência, o valor cobrado e o custo previsto. Registre recebimentos do cliente e pagamentos ao prestador conforme ocorrerem. Use os campos de prestador e PIX quando aplicável.

O resultado mensal acompanha o lucro previsto por competência. O valor ainda devido aos prestadores alimenta **Acertos de obras pendentes** em **Saldos**. Atualize a posição bancária manualmente depois de conferir o pagamento ou recebimento no extrato.

## Vendas

Em **Vendas e comissões**, cadastre a venda e mantenha os valores, as comissões e o andamento atualizados. Consulte **Vendas do mês e pendências anteriores** para acompanhar os registros em aberto e **Resumo de faturamento** para a visão mensal. Uma venda pendente fica no controle comercial. Quando receber, registre a realização no controle e atualize o saldo da conta conforme o extrato.

## Retiradas

Selecione o ano e registre, por mês e por sócio, **Pró-labore**, **Retirada de lucros** e **Retirada adicional**. Clique em **Salvar retiradas** e confira o total e a média no resumo. Esta aba é um controle histórico. As saídas já ocorridas estão refletidas nos saldos bancários quando estes são atualizados pelo extrato. Para uma retirada futura que precisa entrar na projeção, consulte ou programe o lançamento com a natureza correspondente no Forecast.

## Saldos e reservas

Atualize **Saldos bancários e investimentos em reais** com a posição das contas. Confira também os ajustes que afetam a distribuição.

| Controle | Como interpretar |
| --- | --- |
| Superlógica | Representa repasses a clientes. Um saldo positivo reduz a distribuição estimada. Um saldo negativo aumenta a estimativa. |
| Boletos pagos adiantados | Um saldo positivo reduz a distribuição estimada. |
| Acertos de obras pendentes | Vem automaticamente do saldo a pagar aos prestadores registrado em **Obras**. |
| Reserva em dólar | Informe o valor em USD e escolha **PTAX automática** ou **Cotação manual**. Confira a cotação e o equivalente em reais. |
| Reserva para juros de cauções | Informe o valor em **Saldos**. A reserva fica protegida da distribuição. |

Em **Configurações**, confira a integração com a Gestão de Cauções. Se estiver temporariamente indisponível, o aplicativo informa o uso do valor manual salvo até a próxima sincronização. A reserva de juros é um controle separado.

## Histórico e correções

Consulte **Histórico consolidado mensal**, **Lançamentos históricos** e **Diferenças de lançamentos encerrados**. O histórico reúne o realizado e preserva a consulta a pendências antigas.

Para corrigir uma baixa, localize **Corrigir receita ou despesa já baixada**, selecione o registro e confira a descrição, a categoria, a natureza, o valor e a data de quitação. Marque **Reabrir este lançamento como pendente** se a parte ainda não realizada precisar voltar à projeção. Informe o motivo e salve. Quando for necessário excluir um lançamento incorreto, use a opção de exclusão e informe o motivo. O sistema arquiva uma cópia e registra a operação para rastreabilidade. Confira a posição bancária separadamente quando a correção envolver dinheiro já movimentado.

## Acertos

- **Empréstimos.** Registre os movimentos no controle da contraparte e confira o saldo em aberto. O controle com Marcos Veloso oferece o registro de juros de 1%. Os saldos de empréstimos são posições variáveis.
- **Acertos particulares.** Selecione a competência do sócio e informe a data real. Despesas pagas pessoalmente entram com valor positivo a reembolsar. Créditos, receitas e acertos no salário entram com valor negativo. Ao encerrar a competência, o saldo residual segue para a seguinte. Saldo positivo reduz a sobra projetada e saldo negativo aumenta a sobra até a regularização.
- **Reservas de imóveis.** Registre pretendente, imóvel, valor e observação. A reserva ativa reduz a sobra projetada. Encerre a reserva quando resolvida e consulte o registro no histórico de reservas.

## Configurações

### Reservas e distribuição

Confira os parâmetros de reservas e os percentuais dos sócios. Os dois percentuais devem somar 100%. Salve e verifique **Distribuição estimada no final do ano**. O total distribuível é uma projeção sujeita à atualização dos saldos, das reservas e das obrigações.

### Metas anuais

Selecione o ano e cadastre o nome da meta, data da reunião, tipo de apuração e valor-alvo. As opções incluem receitas realizadas no ano, receitas realizadas no mês, renda mensal estabilizada informada manualmente e apuração manual. Quando aplicável, use **Filtro do lançamento** para restringir as receitas consideradas. Confira o resultado em **Resumo**.

### Importação inicial

Use **Importar previsão** para carregar a previsão inicial em CSV separado por ponto e vírgula ou TSV separado por tabulação, com todas as colunas esperadas pelo aplicativo. O importador ignora IDs já existentes na base. Revise o arquivo, os IDs, os anos e as categorias, confira a contagem de novas linhas e selecione **Importar novas linhas**.

## Administração do aplicativo

O aplicativo é publicado no Streamlit e usa uma conta de serviço para acessar o Google Sheets. Configure `gcp_service_account` e os usuários em **Secrets** do Streamlit. Use credenciais próprias de cada ambiente e mantenha os valores reais fora do repositório.

```toml
[usuarios_financeiro]
usuario1 = "defina-uma-senha-nova"
usuario2 = "defina-outra-senha-nova"
```

Na inicialização, o sistema prepara as abas e os campos de que precisa na planilha. O PR #1 acrescenta a aba `Categorias_Financeiras`, usada para persistir as categorias cadastradas pela equipe.

## Referências

- [Financeiro MRC na intranet](https://financeiro-mrc-mrcimoveis.streamlit.app/)
- [Revisão de referência](https://github.com/mrcimoveis-coder/financeiro-mrc/commit/c22be859486746c8adfd07c7c4aab2a7c1a45f02)
- [PR do painel e das categorias](https://github.com/mrcimoveis-coder/financeiro-mrc/pull/1)
