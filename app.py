import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# -----------------------------------------------------------------------------
# 1. CONFIGURAÇÃO DA PÁGINA
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Gestão Financeira | MRC Imóveis", page_icon="💰", layout="wide")

try:
    st.image("https://raw.githubusercontent.com/mrcimoveis-coder/portal-intranet/main/logo.jpeg", width=260)
except Exception:
    pass

# -----------------------------------------------------------------------------
# 2. CONEXÃO GOOGLE SHEETS
# -----------------------------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def conectar_google_sheets(nome_aba="Matriz_2026"):
    credenciais_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in credenciais_dict:
        credenciais_dict["private_key"] = credenciais_dict["private_key"].replace("\\n", "\n")
    
    credentials = Credentials.from_service_account_info(credenciais_dict, scopes=SCOPES)
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key("1WaIP5FJpudjKvOXw0pQe7YfJlTPrISAmaBDZswuCsxM")
    
    try:
        return spreadsheet.worksheet(nome_aba)
    except Exception:
        return spreadsheet.add_worksheet(title=nome_aba, rows="200", cols="20")

# -----------------------------------------------------------------------------
# 3. AUTENTICAÇÃO DE ACESSO
# -----------------------------------------------------------------------------
USUARIOS = {
    "admin": "431360#In",
    "marcelo": "431360Fi",
    "marcio": "Mpve2804",
    "pedro.martinez": "431360xxxx",
    "manoel.iglesias": "431360xxxx",
    "marcos.junior": "431360xxxxxx"
}

if "autenticado_fin" not in st.session_state:
    st.session_state.autenticado_fin = False

if not st.session_state.autenticado_fin:
    st.title("🔒 Acesso Restrito — Módulo Financeiro")
    usuario_input = st.text_input("Usuário:").lower().strip()
    senha_input = st.text_input("Senha:", type="password")
    
    if st.button("Entrar", type="primary"):
        if usuario_input in USUARIOS and USUARIOS[usuario_input] == senha_input:
            st.session_state.autenticado_fin = True
            st.rerun()
        else:
            st.error("❌ Usuário ou senha incorretos.")
    st.stop()

# -----------------------------------------------------------------------------
# 4. INTERFACE MATRICIAL INTERATIVA (EXCEL NO APP)
# -----------------------------------------------------------------------------
sheet_matriz = conectar_google_sheets("Matriz_2026")
dados_raw = sheet_matriz.get_all_records()

MESES = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]
COLUNAS_PADRAO = ["Tipo", "Item / Categoria"] + MESES

# Se a aba no Google Sheets estiver vazia, cria a estrutura inicial
if not dados_raw:
    itens_iniciais = [
        # DISPONIBILIDADE / COFRE / BANCOS
        {"Tipo": "CAIXA", "Item / Categoria": "Valor em Dinheiro (Cofre)", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 2700, "OUTUBRO": 0, "NOVEMBRO": 0, "DEZEMBRO": 0},
        {"Tipo": "BANCO", "Item / Categoria": "Saldo Fundo Investimento BB", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 38306.36, "OUTUBRO": 0, "NOVEMBRO": 0, "DEZEMBRO": 0},
        {"Tipo": "BANCO", "Item / Categoria": "Saldo Fundo Investimento Inter", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 228258.21, "OUTUBRO": 0, "NOVEMBRO": 0, "DEZEMBRO": 0},
        {"Tipo": "BANCO", "Item / Categoria": "Saldo Inter TPF - Titulo Publico Selic", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 1053105.78, "OUTUBRO": 0, "NOVEMBRO": 0, "DEZEMBRO": 0},
        
        # RECEITAS
        {"Tipo": "RECEITA", "Item / Categoria": "Receita Mensal (Aluguel)", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 3000, "OUTUBRO": 96000, "NOVEMBRO": 80000, "DEZEMBRO": 87000},
        {"Tipo": "RECEITA", "Item / Categoria": "Seg Inc + DVDB (Média 2026)", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 7000, "NOVEMBRO": 7000, "DEZEMBRO": 7000},
        {"Tipo": "RECEITA", "Item / Categoria": "Parcelamento Jamilton ref. Venc 12/25", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 1379.48, "NOVEMBRO": 1379.48, "DEZEMBRO": 2758.96},
        {"Tipo": "RECEITA", "Item / Categoria": "ALUGUEL SALA CLSW 304", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 2200, "NOVEMBRO": 2200, "DEZEMBRO": 2200},
        
        # DESPESAS
        {"Tipo": "DESPESA", "Item / Categoria": "Salário Marcos Junior", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 8000, "NOVEMBRO": 8000, "DEZEMBRO": 15000},
        {"Tipo": "DESPESA", "Item / Categoria": "Salario Pedro", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 8500, "NOVEMBRO": 8500, "DEZEMBRO": 25500},
        {"Tipo": "DESPESA", "Item / Categoria": "Salário Mensal Manoel", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 1600, "NOVEMBRO": 1600, "DEZEMBRO": 1600},
        {"Tipo": "DESPESA", "Item / Categoria": "Salário Mensal Marcos Veloso", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 1600, "NOVEMBRO": 1600, "DEZEMBRO": 1600},
        {"Tipo": "DESPESA", "Item / Categoria": "Superlogica - Software", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 505, "NOVEMBRO": 505, "DEZEMBRO": 505},
        {"Tipo": "DESPESA", "Item / Categoria": "Impostos SIMPLES NACIONAL", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 14113.11, "OUTUBRO": 12180, "NOVEMBRO": 13720, "DEZEMBRO": 11900},
        {"Tipo": "DESPESA", "Item / Categoria": "DF Imóveis", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 1475.9, "OUTUBRO": 1475.9, "NOVEMBRO": 1475.9, "DEZEMBRO": 1800},
        {"Tipo": "DESPESA", "Item / Categoria": "Comissão Vendedores sobre aluguel", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 4500, "NOVEMBRO": 4500, "DEZEMBRO": 4500},
        
        # RETIRADAS
        {"Tipo": "RETIRADA", "Item / Categoria": "Retirada Sócios", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 28000, "NOVEMBRO": 28000, "DEZEMBRO": 28000},
        {"Tipo": "RETIRADA", "Item / Categoria": "Retirada Lucros Adicionais", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 30000, "NOVEMBRO": 12500, "DEZEMBRO": 21500},
    ]
    df_matriz = pd.DataFrame(itens_iniciais)
else:
    df_matriz = pd.DataFrame(dados_raw)

st.title("📊 Planilha Financeira Anual — MRC Imóveis (2026)")
st.write("Altere qualquer valor diretamente na tabela abaixo. Os totais e a sobra do mês serão calculados em tempo real.")

# RENDERIZAÇÃO DA PLANILHA EDITÁVEL
df_editado = st.data_editor(
    df_matriz,
    use_container_width=True,
    num_rows="dynamic",
    column_config={
        "Tipo": st.column_config.SelectboxColumn("Tipo", options=["CAIXA", "BANCO", "RECEITA", "DESPESA", "RETIRADA"], required=True),
        "Item / Categoria": st.column_config.TextColumn("Item / Categoria", required=True),
        "JANEIRO": st.column_config.NumberColumn("JANEIRO", format="R$ %.2f"),
        "FEVEREIRO": st.column_config.NumberColumn("FEVEREIRO", format="R$ %.2f"),
        "MARÇO": st.column_config.NumberColumn("MARÇO", format="R$ %.2f"),
        "ABRIL": st.column_config.NumberColumn("ABRIL", format="R$ %.2f"),
        "MAIO": st.column_config.NumberColumn("MAIO", format="R$ %.2f"),
        "JUNHO": st.column_config.NumberColumn("JUNHO", format="R$ %.2f"),
        "JULHO": st.column_config.NumberColumn("JULHO", format="R$ %.2f"),
        "AGOSTO": st.column_config.NumberColumn("AGOSTO", format="R$ %.2f"),
        "SETEMBRO": st.column_config.NumberColumn("SETEMBRO", format="R$ %.2f"),
        "OUTUBRO": st.column_config.NumberColumn("OUTUBRO", format="R$ %.2f"),
        "NOVEMBRO": st.column_config.NumberColumn("NOVEMBRO", format="R$ %.2f"),
        "DEZEMBRO": st.column_config.NumberColumn("DEZEMBRO", format="R$ %.2f"),
    }
)

if st.button("💾 Salvar Alterações na Planilha", type="primary"):
    try:
        sheet_matriz.clear()
        sheet_matriz.append_row(list(df_editado.columns))
        rows_to_save = df_editado.fillna(0).values.tolist()
        for r in rows_to_save:
            sheet_matriz.append_row(r)
        st.success("✅ Planilha salva no Google Sheets com sucesso!")
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao salvar planilha: {e}")

# CÁLCULOS DINÂMICOS EM TEMPO REAL
st.markdown("---")
st.subheader("📈 Totais e Sobra / Falta Caixa Reais (Calculados em Tempo Real)")

# Garantir conversão numérica limpa dos meses
for m in MESES:
    if m in df_editado.columns:
        df_editado[m] = pd.to_numeric(df_editado[m], errors="coerce").fillna(0.0)

resumo_linhas = []

# Total Receitas
rec_row = {"Linha / Métrica": "1. TOTAL RECEITAS"}
for m in MESES:
    rec_row[m] = df_editado[df_editado["Tipo"] == "RECEITA"][m].sum()
resumo_linhas.append(rec_row)

# Total Despesas
desp_row = {"Linha / Métrica": "2. TOTAL DESPESAS"}
for m in MESES:
    desp_row[m] = df_editado[df_editado["Tipo"] == "DESPESA"][m].sum()
resumo_linhas.append(desp_row)

# Resultado Operacional
oper_row = {"Linha / Métrica": "3. RESULTADO OPERACIONAL (1 - 2)"}
for m in MESES:
    oper_row[m] = rec_row[m] - desp_row[m]
resumo_linhas.append(oper_row)

# Retiradas
ret_row = {"Linha / Métrica": "4. RETIRADAS SÓCIOS + LUCROS"}
for m in MESES:
    ret_row[m] = df_editado[df_editado["Tipo"] == "RETIRADA"][m].sum()
resumo_linhas.append(ret_row)

# Sobra / Falta Caixa
sobra_row = {"Linha / Métrica": "5. SOBRA / FALTA CAIXA DO MÊS"}
for m in MESES:
    sobra_row[m] = oper_row[m] - ret_row[m]
resumo_linhas.append(sobra_row)

df_resumo = pd.DataFrame(resumo_linhas)

def formatar_moeda_view(val):
    if isinstance(val, (int, float)):
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return val

df_resumo_fmt = df_resumo.copy()
for m in MESES:
    df_resumo_fmt[m] = df_resumo_fmt[m].apply(formatar_moeda_view)

st.dataframe(df_resumo_fmt, use_container_width=True, hide_index=True)

# DESTAQUE PONTUAL DO MÊS SELECIONADO
st.markdown("---")
st.subheader("🎯 Resumo Destaque por Mês")

mes_destaque = st.selectbox("Selecione o Mês para conferir a Sobra Livre:", MESES, index=9)

rec_dest = df_editado[df_editado["Tipo"] == "RECEITA"][mes_destaque].sum()
desp_dest = df_editado[df_editado["Tipo"] == "DESPESA"][mes_destaque].sum()
ret_dest = df_editado[df_editado["Tipo"] == "RETIRADA"][mes_destaque].sum()
sobra_dest = (rec_dest - desp_dest) - ret_dest

k1, k2, k3, k4 = st.columns(4)
k1.metric(f"Receitas ({mes_destaque})", f"R$ {rec_dest:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
k2.metric(f"Despesas ({mes_destaque})", f"R$ {desp_dest:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
k3.metric(f"Retiradas ({mes_destaque})", f"R$ {ret_dest:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
k4.metric(f"SOBRA LIVRE ({mes_destaque})", f"R$ {sobra_dest:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), delta=f"{sobra_dest:,.2f}")
