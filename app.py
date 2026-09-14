import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
from datetime import datetime

# -----------------------------------------------------------------------------
# 1. CONFIGURAÇÃO DA PÁGINA E LOGO
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
def conectar_google_sheets(nome_aba=None):
    credenciais_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in credenciais_dict:
        credenciais_dict["private_key"] = credenciais_dict["private_key"].replace("\\n", "\n")
    
    credentials = Credentials.from_service_account_info(credenciais_dict, scopes=SCOPES)
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key("1WaIP5FJpudjKvOXw0pQe7YfJlTPrISAmaBDZswuCsxM")
    
    if nome_aba:
        try:
            return spreadsheet.worksheet(nome_aba)
        except Exception:
            return spreadsheet.add_worksheet(title=nome_aba, rows="200", cols="20")
    return spreadsheet.sheet1

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
# 4. INTERFACE PRINCIPAL - 5 ABAS
# -----------------------------------------------------------------------------
try:
    sheet = conectar_google_sheets()
except Exception as e:
    st.error(f"❌ Erro de conexão com o Google Sheets: {e}")
    st.stop()

st.title("💰 Painel Financeiro — MRC Imóveis")
st.write("Controle de receitas, despesas, comissões, projeções e DRE anual.")

aba_dash, aba_consulta, aba_lancamento, aba_editar, aba_dre = st.tabs([
    "📊 Dashboard & Gráficos", 
    "🔍 Pesquisa & Histórico", 
    "➕ Novo Lançamento", 
    "✏️ Editar / Excluir",
    "📅 Planilha Matricial & DRE Anual"
])

def tratar_valor_num_inteligente(val):
    if pd.isna(val):
        return 0.0
    val_str = str(val).replace("R$", "").strip()
    if not val_str:
        return 0.0
    
    if "." in val_str and "," in val_str:
        dot_idx = val_str.rfind(".")
        comma_idx = val_str.rfind(",")
        if comma_idx > dot_idx:
            val_str = val_str.replace(".", "").replace(",", ".")
        else:
            val_str = val_str.replace(",", "")
    elif "," in val_str:
        val_str = val_str.replace(",", ".")
    elif "." in val_str:
        parts = val_str.split(".")
        if len(parts) == 2 and len(parts[1]) in [1, 2]:
            pass
        else:
            val_str = val_str.replace(".", "")
            
    try:
        return float(val_str)
    except Exception:
        return 0.0

# Carregar Dados Principais (Aba 1 do Sheets)
dados_raw = sheet.get_all_records()
df = pd.DataFrame(dados_raw) if dados_raw else pd.DataFrame()

col_data = df.columns[0] if not df.empty else "Data"

MONTH_MAP = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARÇO": 3, "ABRIL": 4,
    "MAIO": 5, "JUNHO": 6, "JULHO": 7, "AGOSTO": 8,
    "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12
}

MONTH_NAMES_PT = {
    1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
    5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
    9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO"
}

def extrair_periodo(val):
    val_str = str(val).strip().upper()
    if val_str in MONTH_MAP:
        return pd.Period(year=2026, month=MONTH_MAP[val_str], freq='M')
    try:
        dt = pd.to_datetime(val_str, format='%d/%m/%Y', errors='coerce')
        if pd.notna(dt):
            return dt.to_period('M')
    except Exception:
        pass
    try:
        dt = pd.to_datetime(val_str, errors='coerce')
        if pd.notna(dt):
            return dt.to_period('M')
    except Exception:
        pass
    return pd.Period(year=2026, month=1, freq='M')

def formatar_rotulo_mes(periodo):
    m_nome = MONTH_NAMES_PT.get(periodo.month, "OUTRO")
    return f"{m_nome}/{periodo.year}"

if not df.empty:
    df["Periodo"] = df[col_data].apply(extrair_periodo)
    df["Mes_Ano_Label"] = df["Periodo"].apply(formatar_rotulo_mes)
    
    if "Valor (R$)" in df.columns:
        df["Valor_Num"] = df["Valor (R$)"].apply(tratar_valor_num_inteligente)
    else:
        df["Valor_Num"] = 0.0
else:
    df = pd.DataFrame(columns=[
        "Data", "Tipo de Operação", "Categoria", "Corretor / Envolvido", "Histórico", "Valor (R$)", "Status", "Observação"
    ])
    df["Valor_Num"] = 0.0
    df["Periodo"] = None
    df["Mes_Ano_Label"] = None

# -----------------------------------------------------------------------------
# ABA 1: DASHBOARD & GRÁFICOS
# -----------------------------------------------------------------------------
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
            st.subheader("Evolução de Receitas e Despesas")
            if not df.empty:
                col_cor = "Tipo de Operação" if "Tipo de Operação" in df.columns else None
                
                if col_cor:
                    df_mes = df.groupby(["Periodo", "Mes_Ano_Label", col_cor])["Valor_Num"].sum().reset_index()
                else:
                    df_mes = df.groupby(["Periodo", "Mes_Ano_Label"])["Valor_Num"].sum().reset_index()
                
                df_mes = df_mes.sort_values("Periodo")
                ordem_cronologica = df_mes["Mes_Ano_Label"].unique().tolist()
                
                fig_mes = px.bar(
                    df_mes, 
                    x="Mes_Ano_Label", 
                    y="Valor_Num", 
                    color=col_cor, 
                    barmode="group",
                    color_discrete_map={"Receita": "#2E7D32", "Despesa": "#C4001A"},
                    labels={"Mes_Ano_Label": "Mês/Ano", "Valor_Num": "Valor (R$)"}
                )
                
                fig_mes.update_xaxes(categoryorder="array", categoryarray=ordem_cronologica)
                st.plotly_chart(fig_mes, use_container_width=True)

        st.markdown("---")
        st.subheader("📈 Resultado Líquido Mês a Mês (Receita − Despesa)")
        
        all_periods = df[["Periodo", "Mes_Ano_Label"]].drop_duplicates()
        
        df_rec_m = df[df["Tipo de Operação"] == "Receita"].groupby(["Periodo", "Mes_Ano_Label"])["Valor_Num"].sum().reset_index().rename(columns={"Valor_Num": "Receita"}) if "Tipo de Operação" in df.columns else pd.DataFrame(columns=["Periodo", "Mes_Ano_Label", "Receita"])
        df_des_m = df[df["Tipo de Operação"] == "Despesa"].groupby(["Periodo", "Mes_Ano_Label"])["Valor_Num"].sum().reset_index().rename(columns={"Valor_Num": "Despesa"}) if "Tipo de Operação" in df.columns else df.groupby(["Periodo", "Mes_Ano_Label"])["Valor_Num"].sum().reset_index().rename(columns={"Valor_Num": "Despesa"})
        
        df_res_m = pd.merge(all_periods, df_rec_m, on=["Periodo", "Mes_Ano_Label"], how="left")
        df_res_m = pd.merge(df_res_m, df_des_m, on=["Periodo", "Mes_Ano_Label"], how="left").fillna(0.0)
        df_res_m["Resultado"] = df_res_m["Receita"] - df_res_m["Despesa"]
        df_res_m["Situação"] = df_res_m["Resultado"].apply(lambda x: "Lucro" if x >= 0 else "Prejuízo")
        df_res_m = df_res_m.sort_values("Periodo")
        
        ordem_res_cronologica = df_res_m["Mes_Ano_Label"].tolist()
        
        fig_res = px.bar(
            df_res_m,
            x="Mes_Ano_Label",
            y="Resultado",
            color="Situação",
            color_discrete_map={"Lucro": "#2E7D32", "Prejuízo": "#C4001A"},
            labels={"Mes_Ano_Label": "Mês/Ano", "Resultado": "Resultado Líquido (R$)"},
            text_auto=".2f"
        )
        fig_res.update_xaxes(categoryorder="array", categoryarray=ordem_res_cronologica)
        st.plotly_chart(fig_res, use_container_width=True)

# -----------------------------------------------------------------------------
# ABA 2: PESQUISA E HISTÓRICO
# -----------------------------------------------------------------------------
with aba_consulta:
    st.subheader("Filtros Avançados de Pesquisa")
    if not df.empty:
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            meses_opt = ["Todos"] + list(df["Mes_Ano_Label"].dropna().unique())
            sel_mes = st.selectbox("Mês/Ano:", meses_opt, key="consulta_mes")
        with f_col2:
            cats_opt = ["Todas"] + df["Categoria"].dropna().unique().tolist() if "Categoria" in df.columns else ["Todas"]
            sel_cat = st.selectbox("Categoria / Tipo:", cats_opt, key="consulta_cat")
        with f_col3:
            env_opt = ["Todos"] + df["Corretor / Envolvido"].dropna().unique().tolist() if "Corretor / Envolvido" in df.columns else ["Todos"]
            sel_env = st.selectbox("Corretor / Envolvido:", env_opt, key="consulta_env")
            
        busca_kw = st.text_input("🔎 Palavra-chave no Histórico (Ex: Facebook, Cartório, Salário):", key="consulta_kw")
        
        df_f = df.copy()
        if sel_mes != "Todos":
            df_f = df_f[df_f["Mes_Ano_Label"] == sel_mes]
        if sel_cat != "Todas" and "Categoria" in df_f.columns:
            df_f = df_f[df_f["Categoria"] == sel_cat]
        if sel_env != "Todos" and "Corretor / Envolvido" in df_f.columns:
            df_f = df_f[df_f["Corretor / Envolvido"] == sel_env]
        if busca_kw and "Histórico" in df_f.columns:
            df_f = df_f[df_f["Histórico"].astype(str).str.lower().str.contains(busca_kw.lower())]
            
        st.write(f"**Registros encontrados:** {len(df_f)} | **Subtotal:** R$ {df_f['Valor_Num'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        
        cols_desejadas = [col_data, "Tipo de Operação", "Categoria", "Corretor / Envolvido", "Histórico", "Valor (R$)", "Status", "Observação"]
        cols_existentes = [c for c in cols_desejadas if c in df_f.columns]
        st.dataframe(df_f[cols_existentes], use_container_width=True, hide_index=True)

# -----------------------------------------------------------------------------
# ABA 3: NOVO LANÇAMENTO
# -----------------------------------------------------------------------------
with aba_lancamento:
    st.subheader("Registrar Nova Operação Financeira")
    with st.form("form_financeiro", clear_on_submit=True):
        c_l1, c_l2 = st.columns(2)
        with c_l1:
            data_op = st.date_input("Data da Operação *", value=datetime.today(), format="DD/MM/YYYY")
            tipo_op = st.radio("Tipo de Operação *", ["Despesa", "Receita"], horizontal=True)
            
            categoria = st.selectbox("Categoria / Tipo *", [
                "SALÁRIO", "COMERCIAL", "DESPESA ADM", "PRÓ-LABORE", "IMPOSTOS", 
                "GESTÃO - TI", "BANCO", 
                "RECEITA ALUGUEL", "RECEITA VENDA", 
                "Renda de Seguro Incendio", "Renda de DVDB", 
                "Renda de Juros de aplicação", "Renda Loft - Comissão", 
                "Venda Imovel MRC", "Venda Imovel Torre Forte", 
                "OUTRO"
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
                    data_str = data_op.strftime("%d/%m/%Y")
                    valor_fmt = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    nova_linha = [data_str, tipo_op, categoria, envolvido, historico, valor_fmt, status, obs]
                    sheet.append_row(nova_linha)
                    st.success("✅ Registro financeiro adicionado com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

# -----------------------------------------------------------------------------
# ABA 4: EDITAR E EXCLUIR
# -----------------------------------------------------------------------------
with aba_editar:
    st.subheader("Alterar ou Excluir Registro Financeiro")
    
    if "item_para_editar" not in st.session_state:
        st.session_state.item_para_editar = None

    if df.empty:
        st.info("Nenhum lançamento cadastrado para editar ou excluir.")
    else:
        st.markdown("##### 🔍 Filtros de Pesquisa para Localizar o Lançamento")
        fe_col1, fe_col2, fe_col3 = st.columns(3)
        with fe_col1:
            meses_opt_ed = ["Todos"] + list(df["Mes_Ano_Label"].dropna().unique())
            sel_mes_ed = st.selectbox("Mês/Ano:", meses_opt_ed, key="edit_mes")
        with fe_col2:
            cats_opt_ed = ["Todas"] + df["Categoria"].dropna().unique().tolist() if "Categoria" in df.columns else ["Todas"]
            sel_cat_ed = st.selectbox("Categoria / Tipo:", cats_opt_ed, key="edit_cat")
        with fe_col3:
            env_opt_ed = ["Todos"] + df["Corretor / Envolvido"].dropna().unique().tolist() if "Corretor / Envolvido" in df.columns else ["Todos"]
            sel_env_ed = st.selectbox("Corretor / Envolvido:", env_opt_ed, key="edit_env")
            
        busca_kw_ed = st.text_input("🔎 Palavra-chave no Histórico (Ex: Facebook, Cartório, Salário):", key="edit_kw")
        
        df_edit = df.copy()
        if sel_mes_ed != "Todos":
            df_edit = df_edit[df_edit["Mes_Ano_Label"] == sel_mes_ed]
        if sel_cat_ed != "Todas" and "Categoria" in df_edit.columns:
            df_edit = df_edit[df_edit["Categoria"] == sel_cat_ed]
        if sel_env_ed != "Todos" and "Corretor / Envolvido" in df_edit.columns:
            df_edit = df_edit[df_edit["Corretor / Envolvido"] == sel_env_ed]
        if busca_kw_ed and "Histórico" in df_edit.columns:
            df_edit = df_edit[df_edit["Histórico"].astype(str).str.lower().str.contains(busca_kw_ed.lower())]
            
        st.write(f"**Registros encontrados:** {len(df_edit)} | **Subtotal:** R$ {df_edit['Valor_Num'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        st.markdown("---")

        if df_edit.empty:
            st.warning("⚠️ Nenhum lançamento encontrado com os filtros selecionados.")
        else:
            st.markdown("##### 📋 Clique no botão ✏️ Editar do lançamento que deseja alterar ou apagar:")
            
            h_c1, h_c2, h_c3, h_c4, h_c5, h_c6, h_c7 = st.columns([1.1, 0.9, 1.2, 1.2, 2.2, 1.2, 0.9])
            h_c1.markdown("**Data**")
            h_c2.markdown("**Tipo**")
            h_c3.markdown("**Categoria**")
            h_c4.markdown("**Envolvido**")
            h_c5.markdown("**Histórico**")
            h_c6.markdown("**Valor**")
            h_c7.markdown("**Ação**")
            st.markdown("---")

            for idx_df, row in df_edit.iterrows():
                r_c1, r_c2, r_c3, r_c4, r_c5, r_c6, r_c7 = st.columns([1.1, 0.9, 1.2, 1.2, 2.2, 1.2, 0.9])
                
                r_c1.write(str(row.get(col_data, "")))
                r_c2.write(str(row.get("Tipo de Operação", "")))
                r_c3.write(str(row.get("Categoria", "")))
                r_c4.write(str(row.get("Corretor / Envolvido", "")))
                r_c5.write(str(row.get("Histórico", "")))
                r_c6.write(str(row.get("Valor (R$)", "")))
                
                if r_c7.button("✏️ Editar", key=f"btn_edit_{idx_df}"):
                    st.session_state.item_para_editar = idx_df
                    st.rerun()

        if st.session_state.item_para_editar is not None:
            idx = st.session_state.item_para_editar
            if idx in df.index:
                linha_real = idx + 2
                dados_item = df.iloc[idx]
                
                st.markdown("---")
                c_head1, c_head2 = st.columns([4, 1])
                c_head1.markdown(f"### ✏️ Editando Registro #{idx + 1}: *{dados_item.get('Histórico', '')}* ({dados_item.get('Valor (R$)', '')})")
                if c_head2.button("❌ Fechar Edição"):
                    st.session_state.item_para_editar = None
                    st.rerun()
                
                with st.form("form_editar_financeiro"):
                    col_ed1, col_ed2 = st.columns(2)
                    with col_ed1:
                        nov_data = st.text_input("Data / Mês *", value=str(dados_item.get(col_data, "")))
                        tp_atual = str(dados_item.get("Tipo de Operação", "Despesa")).strip()
                        nov_tipo = st.selectbox("Tipo de Operação *", ["Despesa", "Receita"], index=0 if tp_atual.lower() == "despesa" else 1)
                        
                        cats_lista = [
                            "SALÁRIO", "COMERCIAL", "DESPESA ADM", "PRÓ-LABORE", "IMPOSTOS", 
                            "GESTÃO - TI", "BANCO", 
                            "RECEITA ALUGUEL", "RECEITA VENDA", 
                            "Renda de Seguro Incendio", "Renda de DVDB", 
                            "Renda de Juros de aplicação", "Renda Loft - Comissão", 
                            "Venda Imovel MRC", "Venda Imovel Torre Forte", 
                            "OUTRO"
                        ]
                        cat_atual = str(dados_item.get("Categoria", "")).strip()
                        idx_cat = cats_lista.index(cat_atual) if cat_atual in cats_lista else len(cats_lista) - 1
                        nov_cat = st.selectbox("Categoria / Tipo *", cats_lista, index=idx_cat)
                        nov_env = st.text_input("Corretor / Envolvido", value=str(dados_item.get("Corretor / Envolvido", "")))
                    
                    with col_ed2:
                        nov_hist = st.text_input("Histórico / Descrição *", value=str(dados_item.get("Histórico", "")))
                        nov_val = st.text_input("Valor (R$) *", value=str(dados_item.get("Valor (R$)", "")))
                        st_atual = str(dados_item.get("Status", "")).strip().lower()
                        idx_st = 0 if st_atual == "confirmado" else 1
                        nov_status = st.selectbox("Status", ["confirmado", "pendente"], index=idx_st)
                        nov_obs = st.text_area("Observações", value=str(dados_item.get("Observação", "")))
                        
                    btn_atualizar = st.form_submit_button("🔄 Salvar Alterações", type="primary")
                    
                    if btn_atualizar:
                        try:
                            v_edit_num = tratar_valor_num_inteligente(nov_val)
                            v_edit_fmt = f"R$ {v_edit_num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                            
                            sheet.update_cell(linha_real, 1, nov_data)
                            sheet.update_cell(linha_real, 2, nov_tipo)
                            sheet.update_cell(linha_real, 3, nov_cat)
                            sheet.update_cell(linha_real, 4, nov_env)
                            sheet.update_cell(linha_real, 5, nov_hist)
                            sheet.update_cell(linha_real, 6, v_edit_fmt)
                            sheet.update_cell(linha_real, 7, nov_status)
                            sheet.update_cell(linha_real, 8, nov_obs)
                            
                            st.success("✅ Lançamento financeiro atualizado com sucesso!")
                            st.session_state.item_para_editar = None
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Erro ao atualizar lançamento: {e}")
                
                st.markdown("---")
                st.markdown("### ❌ Excluir Lançamento")
                confirmar = st.checkbox("Confirmo que desejo apagar permanentemente este lançamento.")
                if confirmar:
                    if st.button("🗑️ Apagar Lançamento Definitivamente", type="primary"):
                        try:
                            try:
                                sheet.delete_rows(linha_real)
                            except AttributeError:
                                sheet.delete_row(linha_real)
                                
                            st.success("✅ Lançamento excluído com sucesso!")
                            st.session_state.item_para_editar = None
                            st.cache_data.clear()
                            st.cache_resource.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Erro ao excluir lançamento: {e}")

# -----------------------------------------------------------------------------
# ABA 5: PLANILHA MATRICIAL INTERATIVA (O EXCEL DENTRO DO APP)
# -----------------------------------------------------------------------------
with aba_dre:
    sheet_matriz = conectar_google_sheets("Matriz_2026")
    dados_raw_matriz = sheet_matriz.get_all_records()

    MESES = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]

    # Se a aba no Google Sheets estiver vazia, carrega a estrutura padrão da MRC
    if not dados_raw_matriz:
        itens_iniciais = [
            {"Tipo": "CAIXA", "Item / Categoria": "Valor em Dinheiro (Cofre)", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 2700, "OUTUBRO": 0, "NOVEMBRO": 0, "DEZEMBRO": 0},
            {"Tipo": "BANCO", "Item / Categoria": "Saldo Fundo Investimento BB", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 38306.36, "OUTUBRO": 0, "NOVEMBRO": 0, "DEZEMBRO": 0},
            {"Tipo": "BANCO", "Item / Categoria": "Saldo Fundo Investimento Inter", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 228258.21, "OUTUBRO": 0, "NOVEMBRO": 0, "DEZEMBRO": 0},
            {"Tipo": "BANCO", "Item / Categoria": "Saldo Inter TPF - Titulo Publico Selic", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 1053105.78, "OUTUBRO": 0, "NOVEMBRO": 0, "DEZEMBRO": 0},
            
            {"Tipo": "RECEITA", "Item / Categoria": "Receita Mensal (Aluguel)", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 3000, "OUTUBRO": 96000, "NOVEMBRO": 80000, "DEZEMBRO": 87000},
            {"Tipo": "RECEITA", "Item / Categoria": "Seg Inc + DVDB (Média 2026)", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 7000, "NOVEMBRO": 7000, "DEZEMBRO": 7000},
            {"Tipo": "RECEITA", "Item / Categoria": "Parcelamento Jamilton ref. Venc 12/25", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 1379.48, "NOVEMBRO": 1379.48, "DEZEMBRO": 2758.96},
            {"Tipo": "RECEITA", "Item / Categoria": "ALUGUEL SALA CLSW 304", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 2200, "NOVEMBRO": 2200, "DEZEMBRO": 2200},
            
            {"Tipo": "DESPESA", "Item / Categoria": "Salário Marcos Junior", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 8000, "NOVEMBRO": 8000, "DEZEMBRO": 15000},
            {"Tipo": "DESPESA", "Item / Categoria": "Salario Pedro", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 8500, "NOVEMBRO": 8500, "DEZEMBRO": 25500},
            {"Tipo": "DESPESA", "Item / Categoria": "Salário Mensal Manoel", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 1600, "NOVEMBRO": 1600, "DEZEMBRO": 1600},
            {"Tipo": "DESPESA", "Item / Categoria": "Salário Mensal Marcos Veloso", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 1600, "NOVEMBRO": 1600, "DEZEMBRO": 1600},
            {"Tipo": "DESPESA", "Item / Categoria": "Superlogica - Software", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 505, "NOVEMBRO": 505, "DEZEMBRO": 505},
            {"Tipo": "DESPESA", "Item / Categoria": "Impostos SIMPLES NACIONAL", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 14113.11, "OUTUBRO": 12180, "NOVEMBRO": 13720, "DEZEMBRO": 11900},
            {"Tipo": "DESPESA", "Item / Categoria": "DF Imóveis", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 1475.9, "OUTUBRO": 1475.9, "NOVEMBRO": 1475.9, "DEZEMBRO": 1800},
            {"Tipo": "DESPESA", "Item / Categoria": "Comissão Vendedores sobre aluguel", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 4500, "NOVEMBRO": 4500, "DEZEMBRO": 4500},
            
            {"Tipo": "RETIRADA", "Item / Categoria": "Retirada Sócios", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 28000, "NOVEMBRO": 28000, "DEZEMBRO": 28000},
            {"Tipo": "RETIRADA", "Item / Categoria": "Retirada Lucros Adicionais", "JANEIRO": 0, "FEVEREIRO": 0, "MARÇO": 0, "ABRIL": 0, "MAIO": 0, "JUNHO": 0, "JULHO": 0, "AGOSTO": 0, "SETEMBRO": 0, "OUTUBRO": 30000, "NOVEMBRO": 12500, "DEZEMBRO": 21500},
        ]
        df_matriz = pd.DataFrame(itens_iniciais)
    else:
        df_matriz = pd.DataFrame(dados_raw_matriz)

    st.subheader("📊 Planilha Financeira Anual — MRC Imóveis (2026)")
    st.write("Altere qualquer valor diretamente na tabela abaixo (estilo Excel). Os totais e a Sobra Livre do Mês são recalculados automaticamente.")

    # PLANILHA INTERATIVA EDITÁVEL
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
