import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px

# 1. Configuração da Página
st.set_page_config(page_title="Gestão Financeira | MRC Imóveis", page_icon="💰", layout="wide")

try:
    st.image("https://raw.githubusercontent.com/mrcimoveis-coder/portal-intranet/main/logo.jpeg", width=260)
except Exception:
    pass

# 2. Conexão com Google Sheets via ID
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def conectar_google_sheets():
    credenciais_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in credenciais_dict:
        credenciais_dict["private_key"] = credenciais_dict["private_key"].replace("\\n", "\n")
    
    credentials = Credentials.from_service_account_info(credenciais_dict, scopes=SCOPES)
    client = gspread.authorize(credentials)
    return client.open_by_key("1WaIP5FJpudjKvOXw0pQe7YfJlTPrISAmaBDZswuCsxM").sheet1

# 3. Autenticação de Acesso (Usuários Atualizados)
USUARIOS = {
    "admin": "431360",
    "marcelo": "431360",
    "pedro": "431360",
    "marcio": "Mpve2804"
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

# 4. Interface Principal
try:
    sheet = conectar_google_sheets()
except Exception as e:
    st.error(f"❌ Erro de conexão com o Google Sheets: {e}")
    st.stop()

st.title("💰 Painel Financeiro — MRC Imóveis")
st.write("Controle de receitas, despesas, comissões e análise gráfica.")

aba_dash, aba_consulta, aba_lancamento, aba_editar = st.tabs([
    "📊 Dashboard & Gráficos", 
    "🔍 Pesquisa & Histórico", 
    "➕ Novo Lançamento", 
    "✏️ Editar / Excluir"
])

# Carregar Dados
dados_raw = sheet.get_all_records()
df = pd.DataFrame(dados_raw) if dados_raw else pd.DataFrame(columns=[
    "Mês", "Tipo de Operação", "Categoria", "Corretor / Envolvido", "Histórico", "Valor (R$)", "Status", "Observação"
])

# Tratamento da coluna Valor
if not df.empty and "Valor (R$)" in df.columns:
    df["Valor_Num"] = (
        df["Valor (R$)"]
        .astype(str)
        .str.replace("R$", "", regex=False)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.strip()
    )
    df["Valor_Num"] = pd.to_numeric(df["Valor_Num"], errors="coerce").fillna(0.0)
else:
    df["Valor_Num"] = 0.0

# --- ABA 1: DASHBOARD & GRÁFICOS ---
with aba_dash:
    if df.empty:
        st.info("Nenhum registro cadastrado no financeiro para gerar indicadores.")
    else:
        st.subheader("Indicadores Gerais")
        
        tot_receita = df[df["Tipo de Operação"] == "Receita"]["Valor_Num"].sum() if "Tipo de Operação" in df.columns else 0.0
        tot_despesa = df[df["Tipo de Operação"] == "Despesa"]["Valor_Num"].sum() if "Tipo de Operação" in df.columns else df["Valor_Num"].sum()
        saldo = tot_receita - tot_despesa
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Receitas", f"R$ {tot_receita:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        c2.metric("Total Despesas", f"R$ {tot_despesa:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        c3.metric("Saldo do Período", f"R$ {saldo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), delta=f"{saldo:,.2f}")
        
        st.markdown("---")
        col_g1, col_g2 = st.columns(2)
        
        with col_g1:
            st.subheader("Despesas por Categoria")
            df_despesas = df[df["Tipo de Operação"] == "Despesa"] if "Tipo de Operação" in df.columns else df
            if not df_despesas.empty and "Categoria" in df_despesas.columns:
                fig_cat = px.pie(df_despesas, names="Categoria", values="Valor_Num", hole=0.4, color_discrete_sequence=px.colors.sequential.RdBu)
                st.plotly_chart(fig_cat, use_container_width=True)
            else:
                st.info("Sem despesas cadastradas.")
                
        with col_g2:
            st.subheader("Evolução Mensal")
            if "Mês" in df.columns:
                col_cor = "Tipo de Operação" if "Tipo de Operação" in df.columns else None
                df_mes = df.groupby(["Mês", "Tipo de Operação"])["Valor_Num"].sum().reset_index() if col_cor else df.groupby("Mês")["Valor_Num"].sum().reset_index()
                
                fig_mes = px.bar(
                    df_mes, x="Mês", y="Valor_Num", 
                    color=col_cor, 
                    barmode="group",
                    color_discrete_map={"Receita": "#2E7D32", "Despesa": "#C4001A"}
                )
                st.plotly_chart(fig_mes, use_container_width=True)

# --- ABA 2: PESQUISA E HISTÓRICO ---
with aba_consulta:
    st.subheader("Filtros Avançados de Pesquisa")
    if not df.empty:
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            meses_opt = ["Todos"] + df["Mês"].dropna().unique().tolist() if "Mês" in df.columns else ["Todos"]
            sel_mes = st.selectbox("Mês:", meses_opt)
        with f_col2:
            cats_opt = ["Todas"] + df["Categoria"].dropna().unique().tolist() if "Categoria" in df.columns else ["Todas"]
            sel_cat = st.selectbox("Categoria / Tipo:", cats_opt)
        with f_col3:
            env_opt = ["Todos"] + df["Corretor / Envolvido"].dropna().unique().tolist() if "Corretor / Envolvido" in df.columns else ["Todos"]
            sel_env = st.selectbox("Corretor / Envolvido:", env_opt)
            
        busca_kw = st.text_input("🔎 Palavra-chave no Histórico (Ex: Facebook, Cartório, Salário):")
        
        # Filtragem
        df_f = df.copy()
        if sel_mes != "Todos" and "Mês" in df_f.columns:
            df_f = df_f[df_f["Mês"] == sel_mes]
        if sel_cat != "Todas" and "Categoria" in df_f.columns:
            df_f = df_f[df_f["Categoria"] == sel_cat]
        if sel_env != "Todos" and "Corretor / Envolvido" in df_f.columns:
            df_f = df_f[df_f["Corretor / Envolvido"] == sel_env]
        if busca_kw and "Histórico" in df_f.columns:
            df_f = df_f[df_f["Histórico"].astype(str).str.lower().str.contains(busca_kw.lower())]
            
        st.write(f"**Registros encontrados:** {len(df_f)} | **Subtotal:** R$ {df_f['Valor_Num'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        
        cols_desejadas = ["Mês", "Tipo de Operação", "Categoria", "Corretor / Envolvido", "Histórico", "Valor (R$)", "Status", "Observação"]
        cols_existentes = [c for c in cols_desejadas if c in df_f.columns]
        st.dataframe(df_f[cols_existentes], use_container_width=True, hide_index=True)

# --- ABA 3: NOVO LANÇAMENTO ---
with aba_lancamento:
    st.subheader("Registrar Nova Operação Financeira")
    with st.form("form_financeiro", clear_on_submit=True):
        c_l1, c_l2 = st.columns(2)
        with c_l1:
            mes = st.selectbox("Mês de Referência *", ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"])
            tipo_op = st.radio("Tipo de Operação *", ["Despesa", "Receita"], horizontal=True)
            categoria = st.selectbox("Categoria / Tipo *", [
                "SALÁRIO", "COMERCIAL", "DESPESA ADM", "PRÓ-LABORE", "IMPOSTOS", 
                "GESTÃO - TI", "BANCO", "RECEITA ALUGUEL", "RECEITA VENDA", "OUTRO"
            ])
            envolvido = st.text_input("Corretor / Envolvido", placeholder="Ex: PEDRO, CAIXINHA, MANOEL, MARCOS JR...")
        with c_l2:
            historico = st.text_input("Histórico / Descrição *", placeholder="Ex: Cartão de Crédito, Imposto Mensal, Comissão...")
            valor = st.number_input("Valor (R$) *", min_value=0.0, format="%.2f")
            status = st.selectbox("Status", ["confirmado", "pendente"])
            obs = st.text_area("Observações Adicionais")
            
        btn_salvar = st.form_submit_button("💾 Salvar Registro", type="primary")
        
        if btn_salvar:
            if valor <= 0 or not historico:
                st.error("⚠️ Preencha o histórico e um valor maior que R$ 0,00.")
            else:
                try:
                    valor_fmt = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    nova_linha = [mes, tipo_op, categoria, envolvido, historico, valor_fmt, status, obs]
                    sheet.append_row(nova_linha)
                    st.success("✅ Registro financeiro adicionado com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

# --- ABA 4: EDITAR E EXCLUIR ---
with aba_editar:
    st.subheader("Gerenciar e Apagar Registros")
    if not df.empty and "Histórico" in df.columns:
        df["ID_Item"] = df.index.astype(str) + " - " + df["Mês"].astype(str) + " | " + df["Histórico"].astype(str)
        item_sel = st.selectbox("Selecione o registro para alterar ou apagar:", [""] + df["ID_Item"].tolist())
        
        if item_sel:
            idx = int(item_sel.split(" - ")[0])
            linha_real = idx + 2
            dados_item = df.iloc[idx]
            
            st.info(f"Registro selecionado: **{dados_item.get('Histórico', '')}** ({dados_item.get('Valor (R$)', '')})")
            
            st.markdown("---")
            st.markdown("### ❌ Excluir Lançamento")
            confirmar = st.checkbox("Confirmo que desejo apagar permanentemente este lançamento.")
            if confirmar:
                if st.button("🗑️ Apagar Lançamento Definitivamente"):
                    sheet.delete_row(linha_real)
                    st.success("✅ Lançamento excluído com sucesso!")
                    st.rerun()
