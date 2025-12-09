import streamlit as st
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
import hashlib
import io
import gspread
from google.oauth2.service_account import Credentials
import pycountry
import geonamescache

# ==================== FUNCIONES DE CÁLCULO ====================

def calcular_tipo_organizacion_score(tipo_org):
    scores = {
        'Empresa grande (más de 100 personas)': 10,
        'Empresa mediana (entre 50 y 100 personas)': 8,
        'Empresa pequeña (menos de 50 personas)': 5,
        'Emprendimiento': 2,
        'Organización educativa privada': -2,
        'Asociación civil, ONG, cooperativa o colectivo': -5,
        'Organización educativa pública': -7,
        'Organización pública': -10
    }
    return scores.get(tipo_org, 0)

def calcular_nivel_formalizacion(respuesta):
    puntaje = 0
    jerarquia_scores = {
        'Altamente jerarquizadas': 25,
        'En general menos de 3 niveles jerárquicos': 18,
        'Nos repartimos los liderazgos y funciones': 10,
        'No reconozco jerarquías': 0
    }
    puntaje += jerarquia_scores.get(respuesta.get('jerarquia', ''), 0)

    planeacion_scores = {
        'Hago o llevo un plan estratégico periódico y se revisa por la dirección': 25,
        'Tengo un plan estratégico que se comunica de manera oficial': 20,
        'Tengo un plan estratégico pero no lo comunico': 15,
        'Participo en el desarrollo del plan estratégico en colectivo': 10,
        'No tengo ninguna planeación': 0
    }
    puntaje += planeacion_scores.get(respuesta.get('planeacion', ''), 0)

    funciones_scores = {
        'Roles claramente identificados y bajo contrato': 25,
        'Roles identificados y formalizados': 20,
        'Roles informales pero identificables': 12,
        'Roles informales fluidos': 6,
        'No tengo roles definidos': 0
    }
    puntaje += funciones_scores.get(respuesta.get('funciones', ''), 0)

    identidad_scores = {
        'Marca con manual definido': 25,
        'Marca definida, identidad informal': 18,
        'Una marca más bien fluida': 12,
        'Llevo una marca por línea de trabajo': 8,
        'Sin identidad definida': 0
    }
    puntaje += identidad_scores.get(respuesta.get('identidad', ''), 0)

    return puntaje

def calcular_nivel_digitalizacion(respuesta):
    puntaje = 0
    num_herramientas = respuesta.get('num_herramientas', 0)
    puntaje += min(num_herramientas * 5, 40)

    num_ias = respuesta.get('num_ias', 0)
    puntaje += min(num_ias * 5, 30)

    num_ias_pagadas = respuesta.get('num_ias_pagadas', 0)
    puntaje += min(num_ias_pagadas * 5, 15)

    num_comunidades = respuesta.get('num_comunidades', 0)
    puntaje += min(num_comunidades * 3, 15)

    return min(puntaje, 100)

def calcular_tipo_org_score_total(organizaciones):
    """Calcula el score total de tipo de organización"""
    total = 0
    for org in organizaciones:
        total += calcular_tipo_organizacion_score(org.get('tipo', ''))
    return total

# ==================== GOOGLE SHEETS ====================

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def conectar_google_sheets():
    """Conecta con Google Sheets usando las credenciales de Streamlit Secrets"""
    try:
        # Verificar que existan los secrets
        if "gcp_service_account" not in st.secrets:
            st.warning("⚠️ No se encontró 'gcp_service_account' en Secrets. Configura los secrets en Streamlit Cloud.")
            return None
        if "google_sheets" not in st.secrets:
            st.warning("⚠️ No se encontró 'google_sheets' en Secrets. Configura los secrets en Streamlit Cloud.")
            return None

        credentials = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=SCOPES
        )
        client = gspread.authorize(credentials)
        spreadsheet_id = st.secrets["google_sheets"]["spreadsheet_id"]
        sheet = client.open_by_key(spreadsheet_id).sheet1
        return sheet
    except Exception as e:
        st.error(f"❌ Error conectando con Google Sheets: {e}")
        return None

def guardar_respuesta_sheets(respuesta):
    """Guarda una respuesta en Google Sheets"""
    sheet = conectar_google_sheets()
    if sheet is None:
        return False

    try:
        # Preparar los datos para la fila
        fila = [
            respuesta.get('demograficos', {}).get('timestamp', ''),
            respuesta.get('num_organizaciones', 0),
            respuesta.get('num_proyectos', 0),
            '|'.join([org.get('tipo', '') for org in respuesta.get('organizaciones', [])]),
            '|'.join([org.get('cargo', '') for org in respuesta.get('organizaciones', [])]),
            '|'.join([proy.get('nombre', '') for proy in respuesta.get('proyectos', [])]),
            '|'.join([proy.get('cargo', '') for proy in respuesta.get('proyectos', [])]),
            respuesta.get('herramientas_admin', {}).get('jerarquia', ''),
            respuesta.get('herramientas_admin', {}).get('planeacion', ''),
            respuesta.get('herramientas_admin', {}).get('ecosistema', ''),
            respuesta.get('herramientas_admin', {}).get('redes', ''),
            respuesta.get('herramientas_admin', {}).get('funciones', ''),
            respuesta.get('herramientas_admin', {}).get('liderazgo', ''),
            respuesta.get('herramientas_admin', {}).get('identidad', ''),
            '|'.join(respuesta.get('herramientas_digitales', {}).get('herramientas', [])),
            '|'.join(respuesta.get('herramientas_digitales', {}).get('herramientas_pagadas', [])),
            '|'.join(respuesta.get('herramientas_digitales', {}).get('ias', [])),
            '|'.join(respuesta.get('herramientas_digitales', {}).get('ias_pagadas', [])),
            '|'.join(respuesta.get('herramientas_digitales', {}).get('comunidades', [])),
            respuesta.get('demograficos', {}).get('pais', ''),
            respuesta.get('demograficos', {}).get('ciudad', ''),
            respuesta.get('demograficos', {}).get('edad', ''),
            respuesta.get('demograficos', {}).get('nivel_academico', ''),
            respuesta.get('demograficos', {}).get('nombre', ''),
            respuesta.get('demograficos', {}).get('correo', ''),
            respuesta.get('demograficos', {}).get('telefono', ''),
            respuesta.get('demograficos', {}).get('entrevista', ''),
            '|'.join(respuesta.get('demograficos', {}).get('convocatorias', [])),
            calcular_tipo_org_score_total(respuesta.get('organizaciones', [])),
            calcular_nivel_formalizacion(respuesta.get('herramientas_admin', {})),
            calcular_nivel_digitalizacion(respuesta.get('herramientas_digitales', {}))
        ]

        sheet.append_row(fila)
        return True
    except Exception as e:
        st.error(f"❌ Error guardando respuesta: {e}")
        return False

def cargar_respuestas_sheets():
    """Carga todas las respuestas desde Google Sheets"""
    sheet = conectar_google_sheets()
    if sheet is None:
        return []

    try:
        datos = sheet.get_all_records()
        return datos
    except Exception as e:
        st.error(f"❌ Error cargando respuestas: {e}")
        return []

# ==================== AUTENTICACIÓN ====================

ADMIN_USER = "admin_tramas"
ADMIN_PASSWORD = "tramas2025"

def verificar_credenciales(username, password):
    return username == ADMIN_USER and password == ADMIN_PASSWORD

def inicializar_sesion():
    if 'autenticado' not in st.session_state:
        st.session_state.autenticado = False
    if 'username' not in st.session_state:
        st.session_state.username = None

def login():
    st.session_state.autenticado = True
    st.session_state.username = ADMIN_USER

def logout():
    st.session_state.autenticado = False
    st.session_state.username = None

def esta_autenticado():
    return st.session_state.get('autenticado', False)

# ==================== EXPORTACIÓN CSV ====================

def preparar_datos_csv(respuestas):
    if not respuestas:
        return None

    datos_procesados = []
    for respuesta in respuestas:
        dato = {
            'timestamp': respuesta.get('timestamp', ''),
            'pais': respuesta.get('pais', ''),
            'ciudad': respuesta.get('ciudad', ''),
            'edad': respuesta.get('edad', ''),
            'nivel_academico': respuesta.get('nivel_academico', ''),
            'num_organizaciones': respuesta.get('num_organizaciones', 0),
            'num_proyectos': respuesta.get('num_proyectos', 0),
            'jerarquia': respuesta.get('jerarquia', ''),
            'planeacion': respuesta.get('planeacion', ''),
            'nivel_formalizacion': respuesta.get('nivel_formalizacion', 0),
            'nivel_digitalizacion': respuesta.get('nivel_digitalizacion', 0),
            'tipo_org_score': respuesta.get('tipo_org_score', 0)
        }
        datos_procesados.append(dato)

    return pd.DataFrame(datos_procesados)

def generar_csv(df):
    if df is None or df.empty:
        return None
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, encoding='utf-8-sig')
    buffer.seek(0)
    return buffer.getvalue()

def mostrar_boton_descarga():
    if not esta_autenticado():
        return

    respuestas = cargar_respuestas_sheets()

    if not respuestas:
        st.info("ℹ️ No hay datos disponibles para descargar")
        return

    df = preparar_datos_csv(respuestas)

    if df is None or df.empty:
        st.warning("⚠️ No hay datos procesados para descargar")
        return

    csv_data = generar_csv(df)

    if csv_data:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_archivo = f"mapeo_gestion_cultural_{timestamp}.csv"

        col1, col2 = st.columns([2, 1])
        with col1:
            st.success(f"📊 **{len(df)} respuestas** listas para descargar")
        with col2:
            st.download_button(
                label="⬇️ Descargar CSV",
                data=csv_data,
                file_name=nombre_archivo,
                mime="text/csv",
                use_container_width=True
            )

        with st.expander("👁️ Vista previa de los datos"):
            st.dataframe(df.head(10), use_container_width=True)
            st.caption(f"Mostrando las primeras 10 de {len(df)} filas")

# ==================== FUNCIONES DE VISUALIZACIÓN ====================

def crear_scatter_dual(df_filtrado):
    """Crea scatter plot dual con puntos de Formalización y Digitalización"""
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df_filtrado['tipo_org_score'],
        y=df_filtrado['nivel_formalizacion'],
        mode='markers',
        name='Formalización',
        marker=dict(
            size=df_filtrado['total_entidades'] * 5 + 5,
            color='#5D80B5',
            opacity=0.6,
            line=dict(width=1, color='white')
        ),
        text=df_filtrado.apply(
            lambda row: f"País: {row['pais']}<br>Orgs: {row['num_organizaciones']}<br>Proyectos: {row['num_proyectos']}<br>Formalización: {row['nivel_formalizacion']}",
            axis=1
        ),
        hovertemplate='%{text}<extra></extra>'
    ))

    fig.add_trace(go.Scatter(
        x=df_filtrado['tipo_org_score'],
        y=df_filtrado['nivel_digitalizacion'],
        mode='markers',
        name='Digitalización',
        marker=dict(
            size=df_filtrado['total_entidades'] * 5 + 5,
            color='#A870B0',
            opacity=0.6,
            line=dict(width=1, color='white')
        ),
        text=df_filtrado.apply(
            lambda row: f"País: {row['pais']}<br>Orgs: {row['num_organizaciones']}<br>Proyectos: {row['num_proyectos']}<br>Digitalización: {row['nivel_digitalizacion']}",
            axis=1
        ),
        hovertemplate='%{text}<extra></extra>'
    ))

    fig.update_layout(
        xaxis_title="Tipo de organización: de muy gubernamental (-10) a muy empresarial (+10)",
        yaxis_title="Nivel (0-100)",
        height=600,
        hovermode='closest',
        plot_bgcolor='white',
        xaxis=dict(gridcolor='#f0f0f0', range=[-12, 12]),
        yaxis=dict(gridcolor='#f0f0f0', range=[-5, 105])
    )

    return fig

def crear_grafico_barras_dual(data1, data2, label1, label2, color1='#5D80B5', color2='#A870B0'):
    """Crea gráfico de barras comparativo con dos series"""
    fig = go.Figure()

    fig.add_trace(go.Bar(
        name=label1,
        x=list(data1.index),
        y=list(data1.values),
        marker_color=color1
    ))

    fig.add_trace(go.Bar(
        name=label2,
        x=list(data2.index),
        y=list(data2.values),
        marker_color=color2
    ))

    fig.update_layout(
        barmode='group',
        xaxis_tickangle=-45,
        height=400
    )

    return fig

def filtrar_datos(df, filtros):
    """Aplica filtros demográficos a un DataFrame"""
    df_filtrado = df.copy()

    if filtros.get('pais', 'Todos') != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['pais'] == filtros['pais']]

    if filtros.get('ciudad', 'Todos') != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['ciudad'] == filtros['ciudad']]

    if filtros.get('edad', 'Todos') != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['edad'] == filtros['edad']]

    if filtros.get('nivel_academico', 'Todos') != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['nivel_academico'] == filtros['nivel_academico']]

    return df_filtrado

# ==================== FUNCIÓN MOSTRAR MAPAS ====================

def mostrar_mapas():
    """Vista de mapas con gráficos y filtros"""

    # Cargar datos desde Google Sheets
    respuestas = cargar_respuestas_sheets()

    # Verificar si hay datos
    if not respuestas:
        st.info("📊 Aún no hay respuestas. ¡Sé el primero en completar la encuesta!")
        return

    # Preparar datos para visualización
    datos_procesados = []
    for resp in respuestas:
        herramientas_str = str(resp.get('herramientas', ''))
        ias_str = str(resp.get('ias', ''))
        ias_pagadas_str = str(resp.get('ias_pagadas', ''))
        comunidades_str = str(resp.get('comunidades', ''))

        num_herramientas = len([h for h in herramientas_str.split('|') if h]) if herramientas_str else 0
        num_ias = len([i for i in ias_str.split('|') if i and i != 'Ninguna']) if ias_str else 0
        num_ias_pagadas = len([i for i in ias_pagadas_str.split('|') if i]) if ias_pagadas_str else 0
        num_comunidades = len([c for c in comunidades_str.split('|') if c]) if comunidades_str else 0

        datos_procesados.append({
            'num_organizaciones': resp.get('num_organizaciones', 0),
            'num_proyectos': resp.get('num_proyectos', 0),
            'total_entidades': resp.get('num_organizaciones', 0) + resp.get('num_proyectos', 0),
            'tipo_org_score': resp.get('tipo_org_score', 0),
            'nivel_formalizacion': resp.get('nivel_formalizacion', 0),
            'nivel_digitalizacion': resp.get('nivel_digitalizacion', 0),
            'jerarquia': resp.get('jerarquia', ''),
            'planeacion': resp.get('planeacion', ''),
            'num_herramientas': num_herramientas,
            'num_ias': num_ias,
            'num_ias_pagadas': num_ias_pagadas,
            'num_comunidades': num_comunidades,
            'pais': resp.get('pais', ''),
            'ciudad': resp.get('ciudad', ''),
            'edad': resp.get('edad', ''),
            'nivel_academico': resp.get('nivel_academico', '')
        })

    df_datos = pd.DataFrame(datos_procesados)

    # Filtros demográficos
    st.markdown("### Filtros Demográficos")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        paises_disponibles = ['Todos'] + sorted([p for p in df_datos['pais'].unique().tolist() if p])
        filtro_pais = st.selectbox("País:", paises_disponibles, key="f_pais")

    with col2:
        if filtro_pais != 'Todos':
            ciudades_disponibles = ['Todos'] + sorted([c for c in df_datos[df_datos['pais'] == filtro_pais]['ciudad'].unique().tolist() if c])
        else:
            ciudades_disponibles = ['Todos'] + sorted([c for c in df_datos['ciudad'].unique().tolist() if c])
        filtro_ciudad = st.selectbox("Ciudad:", ciudades_disponibles, key="f_ciudad")

    with col3:
        edades_disponibles = ['Todos'] + sorted([e for e in df_datos['edad'].unique().tolist() if e])
        filtro_edad = st.selectbox("Edad:", edades_disponibles, key="f_edad")

    with col4:
        niveles_disponibles = ['Todos'] + sorted([n for n in df_datos['nivel_academico'].unique().tolist() if n])
        filtro_nivel = st.selectbox("Nivel académico:", niveles_disponibles, key="f_nivel")

    # Aplicar filtros
    filtros = {
        'pais': filtro_pais,
        'ciudad': filtro_ciudad,
        'edad': filtro_edad,
        'nivel_academico': filtro_nivel
    }

    df_filtrado = filtrar_datos(df_datos, filtros)

    st.info(f"📊 Mostrando {len(df_filtrado)} de {len(df_datos)} respuestas")

    if len(df_filtrado) == 0:
        st.warning("No hay datos con los filtros seleccionados. Prueba con otros criterios.")
        return

    st.markdown("---")

    # GRÁFICO PRINCIPAL
    st.markdown("### Gráfico Principal")
    st.markdown("""
    <div style="background-color: #f0f0f0; padding: 0.8rem; border-radius: 8px; margin-bottom: 1rem;">
        En este mapa medimos, por persona, qué tan formalizadas son sus relaciones
        <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: #5D80B5; margin: 0 3px;"></span>
        y su nivel de digitalización
        <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: #A870B0; margin: 0 3px;"></span>
    </div>
    """, unsafe_allow_html=True)

    fig = crear_scatter_dual(df_filtrado)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # GRÁFICOS COMPLEMENTARIOS
    st.markdown("### Gráficos Complementarios")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 1. Cantidad de organizaciones + proyectos")
        fig1 = go.Figure(data=[
            go.Bar(x=df_filtrado['total_entidades'].value_counts().sort_index().index.tolist(),
                   y=df_filtrado['total_entidades'].value_counts().sort_index().values.tolist(),
                   marker_color='#5D80B5')
        ])
        fig1.update_layout(showlegend=False, xaxis_title="Cantidad", yaxis_title="Frecuencia")
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        st.markdown("#### 2. Tipos de jerarquías y planeación")
        jer_counts = df_filtrado['jerarquia'].value_counts()
        plan_counts = df_filtrado['planeacion'].value_counts()
        fig2 = crear_grafico_barras_dual(jer_counts, plan_counts, 'Jerarquía', 'Planeación')
        st.plotly_chart(fig2, use_container_width=True)

    col3, col4 = st.columns(2)

    with col3:
        st.markdown("#### 3. Herramientas digitales y comunidades")
        herr_counts = df_filtrado['num_herramientas'].value_counts().sort_index()
        com_counts = df_filtrado['num_comunidades'].value_counts().sort_index()
        fig3 = crear_grafico_barras_dual(herr_counts, com_counts, 'Herramientas', 'Comunidades')
        st.plotly_chart(fig3, use_container_width=True)

    with col4:
        st.markdown("#### 4. IAs utilizadas y IAs pagadas")
        ia_counts = df_filtrado['num_ias'].value_counts().sort_index()
        ia_pag_counts = df_filtrado['num_ias_pagadas'].value_counts().sort_index()
        fig4 = crear_grafico_barras_dual(ia_counts, ia_pag_counts, 'IAs usadas', 'IAs pagadas')
        st.plotly_chart(fig4, use_container_width=True)

    # Descarga para admin
    if esta_autenticado():
        st.markdown("---")
        st.markdown("### 📥 Descarga de Datos (Administrador)")
        mostrar_boton_descarga()

# ==================== FUNCIONES DE LA ENCUESTA ====================

def mostrar_encuesta():
    """Muestra el formulario de encuesta"""
    if 'encuesta_page' not in st.session_state:
        st.session_state.encuesta_page = 0

    if st.session_state.encuesta_page == 0:
        pagina_intro()
    elif st.session_state.encuesta_page == 1:
        pagina_cantidad()
    elif st.session_state.encuesta_page == 2:
        pagina_herramientas_admin()
    elif st.session_state.encuesta_page == 3:
        pagina_herramientas_digitales()
    elif st.session_state.encuesta_page == 4:
        pagina_demograficos()
    elif st.session_state.encuesta_page == 5:
        pagina_gracias()

def pagina_intro():
    st.markdown("""
    <div class="question-box">
        <p style="line-height: 1.8;">
            En el mundo del arte, la cultura y el emprendimiento social las personas solemos
            participar en múltiples espacios, proyectos u organizaciones. Esto lo hacemos por
            necesidades financieras en muchos casos, pero también por exploraciones estéticas,
            sociales o personales.
        </p>
        <p style="line-height: 1.8; margin-top: 1rem;">
            Definitivamente, no todos los productos o proyectos que hacemos pueden enmarcarse
            en un solo lugar, y por eso tenemos que dividirlos. Eso plantea grandes retos para
            la gestión de cada uno, especialmente afectados hoy en día por la digitalización.
        </p>
        <p style="line-height: 1.8; margin-top: 1rem;">
            En este mapa queremos conocer de qué manera divides tu trabajo, qué necesidades de
            gestión tienes y cómo estás apropiando herramientas digitales. Responde de manera
            personal pero puedes enfocarte en la organización más relevante para tu trabajo o
            en forma general.
        </p>
        <p style="line-height: 1.8; margin-top: 1rem; font-weight: 600;">
            Te agradecemos mucho tu participación, te tomará alrededor de 15 minutos.<br>
            Este estudio es clave para plantear mejoras a las formas de gestión cultural en Latinoamérica.
        </p>
    </div>
    """, unsafe_allow_html=True)

    if st.button("INICIAR ENCUESTA ➡️", use_container_width=True):
        st.session_state.encuesta_page = 1
        st.rerun()

def pagina_cantidad():
    st.markdown("""
    <div class="question-box">
        <h4 style="font-family: 'Roboto', sans-serif; margin-bottom: 1rem;">Conceptos Clave</h4>
        <p style="line-height: 1.6;">
            Ten en cuenta los siguientes conceptos para responder esta encuesta:
        </p>
        <p style="line-height: 1.6; margin-top: 0.8rem;">
            <strong>1. ORGANIZACIÓN:</strong> Tiene límites claramente definidos, división de labores
            y mecanismos de pertenencia establecidos. Normalmente desarrolla múltiples proyectos.
        </p>
        <p style="line-height: 1.6; margin-top: 0.8rem;">
            <strong>2. PROYECTO:</strong> No tiene conformación formal necesariamente. Puede ser
            autogestionado o realizarse dentro de una organización.
        </p>
        <p style="line-height: 1.6; margin-top: 0.8rem;">
            <strong>3. ECOSISTEMA:</strong> Un ecosistema es la agrupación de campos específicos dentro
            del campo del arte y la cultura ubicados territorialmente. Permite agrupar redes de trabajo,
            organizaciones y personas de múltiples disciplinas.
        </p>
        <p style="line-height: 1.6; margin-top: 0.8rem;">
            <strong>4. RED:</strong> Una red es un campo de organizaciones usualmente del mismo segmento
            o disciplina las cuales colaboran entre sí para desarrollar proyectos específicos.
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### ¿A cuántas organizaciones perteneces formal o informalmente y en cuántos proyectos estás participando?")

    col1, col2 = st.columns(2)
    with col1:
        num_org = st.number_input("Organizaciones:", min_value=0, max_value=20, value=0, key="num_org")
    with col2:
        num_proy = st.number_input("Proyectos:", min_value=0, max_value=20, value=0, key="num_proy")

    orgs_data = []
    if num_org > 0:
        st.markdown("### Organizaciones")
        for i in range(num_org):
            with st.expander(f"Organización {i+1}"):
                tipo = st.selectbox(
                    "Tipo:",
                    ["Empresa grande (más de 100 personas)",
                     "Empresa mediana (entre 50 y 100 personas)",
                     "Empresa pequeña (menos de 50 personas)",
                     "Emprendimiento",
                     "Organización educativa privada",
                     "Asociación civil, ONG, cooperativa o colectivo",
                     "Organización educativa pública",
                     "Organización pública"],
                    key=f"tipo_org_{i}"
                )
                cargo = st.text_input("Cargo:", key=f"cargo_org_{i}")
                orgs_data.append({'tipo': tipo, 'cargo': cargo})

    proyectos_data = []
    if num_proy > 0:
        st.markdown("### Proyectos")
        for i in range(num_proy):
            with st.expander(f"Proyecto {i+1}"):
                nombre = st.text_input("Nombre:", key=f"nombre_proy_{i}")
                cargo = st.text_input("Cargo:", key=f"cargo_proy_{i}")
                proyectos_data.append({'nombre': nombre, 'cargo': cargo})

    col_prev, col_next = st.columns([1, 1])
    with col_prev:
        if st.button("⬅️ Regresar", use_container_width=True):
            st.session_state.encuesta_page = 0
            st.rerun()
    with col_next:
        if num_org + num_proy > 0:
            if st.button("Continuar ➡️", use_container_width=True):
                if 'temp_data' not in st.session_state:
                    st.session_state.temp_data = {}
                st.session_state.temp_data.update({
                    'num_organizaciones': num_org,
                    'num_proyectos': num_proy,
                    'organizaciones': orgs_data,
                    'proyectos': proyectos_data
                })
                st.session_state.encuesta_page = 2
                st.rerun()

def pagina_herramientas_admin():
    st.markdown("### Herramientas Administrativas y Gestivas")

    jerarquia = st.selectbox(
        "1. ¿Cómo son tus relaciones de trabajo?",
        ["Altamente jerarquizadas", "En general menos de 3 niveles jerárquicos",
         "Nos repartimos los liderazgos y funciones", "No reconozco jerarquías"]
    )

    planeacion = st.selectbox(
        "2. ¿Cómo es tu forma de planeación?",
        ["Hago o llevo un plan estratégico periódico y se revisa por la dirección",
         "Tengo un plan estratégico que se comunica de manera oficial",
         "Tengo un plan estratégico pero no lo comunico",
         "Participo en el desarrollo del plan estratégico en colectivo",
         "No tengo ninguna planeación"]
    )

    ecosistema = st.selectbox(
        "3. ¿Reconoces el ecosistema al que perteneces?",
        ["Participo formalmente con otras organizaciones de diferentes sectores",
         "Participo informalmente con organizaciones de diferentes sectores",
         "Participo con organizaciones del mismo sector",
         "No reconozco participación con nadie más"]
    )

    redes = st.selectbox(
        "4. ¿Tienes una red de trabajo consolidada?",
        ["Participo activamente con organizaciones del sector",
         "Reconozco organizaciones pero no me reconocen",
         "Estoy consolidando lazos",
         "No participo con nadie"]
    )

    funciones = st.selectbox(
        "5. ¿Cómo son tus funciones y labores?",
        ["Roles claramente identificados y bajo contrato",
         "Roles identificados y formalizados",
         "Roles informales pero identificables",
         "Roles informales fluidos",
         "No tengo roles definidos"]
    )

    liderazgo = st.selectbox(
        "6. ¿Cómo es el liderazgo en tu forma de trabajo?",
        ["Líderes específicos para cada área",
         "Líderes específicos según el proyecto",
         "Liderazgo compartido por conocimiento",
         "Sin liderazgo claro"]
    )

    identidad = st.selectbox(
        "7. ¿Tienes una identidad definida?",
        ["Marca con manual definido",
         "Marca definida, identidad informal",
         "Una marca más bien fluida",
         "Llevo una marca por línea de trabajo",
         "Sin identidad definida"]
    )

    col_prev, col_next = st.columns([1, 1])
    with col_prev:
        if st.button("⬅️ Regresar", use_container_width=True):
            st.session_state.encuesta_page = 1
            st.rerun()
    with col_next:
        if st.button("Continuar ➡️", use_container_width=True):
            st.session_state.temp_data['herramientas_admin'] = {
                'jerarquia': jerarquia,
                'planeacion': planeacion,
                'ecosistema': ecosistema,
                'redes': redes,
                'funciones': funciones,
                'liderazgo': liderazgo,
                'identidad': identidad
            }
            st.session_state.encuesta_page = 3
            st.rerun()

def pagina_herramientas_digitales():
    st.markdown("### Uso de Herramientas Digitales")

    st.markdown("**1. ¿Qué herramientas utilizas?**")
    herramientas = st.multiselect(
        "Selecciona:",
        ["Redes sociales", "Página web", "Almacenamiento en la nube",
         "Banca en línea (recibimos pagos)", "Banca en línea (no recibimos pagos)",
         "Correo personalizado", "Plataformas de llamadas virtuales",
         "Software de oficina", "Software especializado"]
    )

    if herramientas:
        st.markdown("**2. ¿Cuáles pagas?**")
        herramientas_pagadas = st.multiselect("Selecciona:", herramientas, key="herr_pag")
    else:
        herramientas_pagadas = []

    st.markdown("**3. ¿Qué inteligencias artificiales utilizas?**")
    ias = st.multiselect(
        "Selecciona:",
        ["Generador de texto (ChatGPT, Claude, etc.)",
         "Asistente de escritura", "Traductor", "Asistente de oficina",
         "Generador de imágenes", "Herramienta pedagógica",
         "Herramienta de código", "Otras", "Ninguna"],
        key="ias"
    )

    if ias and "Ninguna" not in ias:
        st.markdown("**4. ¿Cuáles pagas?**")
        ias_pagadas = st.multiselect("Selecciona:", [ia for ia in ias if ia != "Ninguna"], key="ias_pag")
    else:
        ias_pagadas = []

    st.markdown("**5. ¿Perteneces a alguna comunidad en línea?**")
    comunidades = st.multiselect(
        "Selecciona:",
        ["Grupos de WhatsApp/Telegram", "Grupos de difusión",
         "Grupos de redes sociales", "Comunidades especializadas en línea",
         "Comunidades híbridas"],
        key="comunidades"
    )

    col_prev, col_next = st.columns([1, 1])
    with col_prev:
        if st.button("⬅️ Regresar", use_container_width=True):
            st.session_state.encuesta_page = 2
            st.rerun()
    with col_next:
        if st.button("Continuar ➡️", use_container_width=True):
            st.session_state.temp_data['herramientas_digitales'] = {
                'herramientas': herramientas,
                'herramientas_pagadas': herramientas_pagadas,
                'ias': ias,
                'ias_pagadas': ias_pagadas,
                'comunidades': comunidades,
                'num_herramientas': len(herramientas),
                'num_ias': len([ia for ia in ias if ia != "Ninguna"]),
                'num_ias_pagadas': len(ias_pagadas),
                'num_comunidades': len(comunidades)
            }
            st.session_state.encuesta_page = 4
            st.rerun()

def pagina_demograficos():
    st.markdown("### Datos Demográficos")
    st.caption("Campos con * son obligatorios")

    st.markdown("#### Información obligatoria")

    # Lista de países con pycountry
    gc = geonamescache.GeonamesCache()
    paises = sorted([country.name for country in pycountry.countries])
    pais = st.selectbox("País *", paises)

    # Obtener ciudades del país
    country_obj = pycountry.countries.get(name=pais)
    country_code = country_obj.alpha_2 if country_obj else None

    if country_code:
        all_cities = gc.get_cities()
        ciudades = sorted([city["name"] for city in all_cities.values() if city["countrycode"] == country_code])
    else:
        ciudades = []

    ciudad = st.selectbox("Ciudad *", ciudades if ciudades else ["Seleccione un país"])

    edad = st.selectbox(
        "Rango de edad *",
        ["Selecciona...", "18-24 años", "25-34 años", "35-44 años",
         "45-54 años", "55-64 años", "65+ años"]
    )
    nivel_academico = st.selectbox(
        "Nivel académico *",
        ["Selecciona...", "Sin estudios formales", "Primaria", "Secundaria",
         "Preparatoria/Bachillerato", "Técnico", "Licenciatura/Grado",
         "Maestría/Posgrado", "Doctorado"]
    )

    st.markdown("#### Información opcional")
    nombre = st.text_input("Nombre")
    correo = st.text_input("Correo electrónico")
    telefono = st.text_input("Teléfono")
    entrevista = st.radio("¿Te contactamos para entrevistas?", ["No", "Sí"])
    convocatorias = st.multiselect("¿Te interesa participar en?", ["Talleres de autogestión", "Ferias de arte"])

    col_prev, col_next = st.columns([1, 1])
    with col_prev:
        if st.button("⬅️ Regresar", use_container_width=True):
            st.session_state.encuesta_page = 3
            st.rerun()
    with col_next:
        campos_completos = (
            pais and ciudad and ciudad != "Seleccione un país" and
            edad != "Selecciona..." and nivel_academico != "Selecciona..."
        )

        if campos_completos:
            if st.button("Finalizar ✅", use_container_width=True):
                respuesta_completa = {
                    **st.session_state.temp_data,
                    'demograficos': {
                        'pais': pais,
                        'ciudad': ciudad,
                        'edad': edad,
                        'nivel_academico': nivel_academico,
                        'nombre': nombre,
                        'correo': correo,
                        'telefono': telefono,
                        'entrevista': entrevista,
                        'convocatorias': convocatorias,
                        'timestamp': datetime.now().isoformat()
                    }
                }

                # Guardar respuesta en Google Sheets
                if guardar_respuesta_sheets(respuesta_completa):
                    st.session_state.encuesta_page = 5
                    st.rerun()
                else:
                    st.error("Error al guardar la respuesta. Por favor intenta de nuevo.")
        else:
            st.button("Finalizar ✅", use_container_width=True, disabled=True)

def pagina_gracias():
    st.markdown("""
    <div class="thanks-message">
        ¡Muchas gracias por responder y apoyarnos con este estudio!<br>
        Ahora navega por nuestros mapeos
    </div>
    """, unsafe_allow_html=True)

    if st.button("Ver mapeos y resultados", use_container_width=True):
        st.session_state.page = 'vista_mapas'
        st.rerun()

# ==================== CONFIGURACIÓN ====================
st.set_page_config(
    page_title="TRAMAS - Mapeos Sociales",
    page_icon="🕸️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== CSS PERSONALIZADO ====================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&family=Roboto+Slab:wght@400;700&display=swap');

    [data-testid="stSidebar"] { background-color: #808080; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] { color: black; }

    .tramas-logo {
        background-color: #000000; color: white; padding: 1rem 0.5rem;
        border-radius: 10px; font-family: 'Roboto', sans-serif; font-weight: 700;
        font-size: 2rem; text-align: center; margin-bottom: 0.5rem;
        display: flex; align-items: center; justify-content: center; gap: 0.3rem;
    }
    .tramas-logo-icon { font-size: 2rem; color: #808080; }

    .credits-small {
        font-family: 'Roboto Slab', serif; font-style: italic; font-size: 0.7rem;
        color: black; text-align: center; margin: 1rem 0 0.5rem 0; line-height: 1.3;
    }

    .mapeo-title {
        background-color: #000000; color: white; padding: 0.8rem 2rem;
        border-radius: 10px; font-family: 'Roboto', sans-serif; font-weight: 700;
        font-size: 1.8rem; text-align: center; margin-bottom: 1rem;
    }

    .question-box {
        background-color: white; color: black; padding: 1rem; border-radius: 8px;
        font-family: 'Roboto Slab', serif; margin: 0.5rem 0; border: 1px solid #e0e0e0;
    }

    .thanks-message {
        background-color: #A870B0; color: white; padding: 2rem; border-radius: 15px;
        text-align: center; font-family: 'Roboto', sans-serif; font-size: 1.5rem;
        font-weight: 700; margin: 1rem 0;
    }

    .stButton > button {
        background-color: #A870B0; color: #62CBE6; font-family: 'Roboto', sans-serif;
        font-weight: 700; border-radius: 10px; padding: 0.75rem 2rem;
        border: none; font-size: 1.1rem;
    }
    .stButton > button:hover { background-color: #8f5a9a; color: #4db8d4; }
</style>
""", unsafe_allow_html=True)

# ==================== INICIALIZACIÓN ====================
if 'seccion' not in st.session_state:
    st.session_state.seccion = 'intro'
if 'page' not in st.session_state:
    st.session_state.page = None
if 'encuesta_page' not in st.session_state:
    st.session_state.encuesta_page = 0
if 'temp_data' not in st.session_state:
    st.session_state.temp_data = {}

inicializar_sesion()

# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("""
    <div class="tramas-logo">
        <span class="tramas-logo-icon">🕸️</span>
        <span>tramas</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    if st.button("🏠 Inicio", use_container_width=True, key="btn_inicio"):
        st.session_state.seccion = 'intro'
        st.session_state.page = None
        st.session_state.encuesta_page = 0
        st.rerun()

    if st.button("📊 Gestión Cultural y Digital", use_container_width=True, key="btn_mapeo1"):
        st.session_state.seccion = 'mapeo1'
        st.session_state.page = 'vista_mapas'
        st.rerun()

    st.markdown("---")
    st.markdown("""
    <a href="https://elchorro.com.co/contactanos/" target="_blank" style="text-decoration: none;">
        <button style="width: 100%; background-color: #A870B0; color: #62CBE6; font-family: 'Roboto', sans-serif;
                       font-weight: 700; border-radius: 10px; padding: 0.75rem; border: none; font-size: 1rem; cursor: pointer;">
            💬 ¿Te interesa hacer un mapeo? ¡Contáctanos!
        </button>
    </a>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("""
    <div class="credits-small">
        Este programa es un desarrollo en colaboración entre El Chorro Producciones y Huika Mexihco
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<a href="https://www.elchorro.com.co" target="_blank"><img src="https://elchorroco.wordpress.com/wp-content/uploads/2025/04/ch-plano.png" width="50"></a>', unsafe_allow_html=True)
    with col2:
        st.markdown('<a href="https://www.huikamexihco.com.mx" target="_blank"><img src="https://huikamexihco.com.mx/wp-content/uploads/2021/04/huika-mexihco.png" width="50"></a>', unsafe_allow_html=True)

    st.markdown("---")

    if esta_autenticado():
        st.markdown("### 👤 Sesión Activa")
        st.info(f"**Usuario:** {st.session_state.username}")
        if st.button("🚪 Cerrar sesión", use_container_width=True, key="btn_logout"):
            logout()
            st.rerun()
    else:
        st.markdown("### 🔐 Acceso Administrador")
        with st.form("login_form"):
            username = st.text_input("Usuario", placeholder="admin_tramas")
            password = st.text_input("Contraseña", type="password", placeholder="••••••••")
            submit = st.form_submit_button("Iniciar sesión", use_container_width=True)
            if submit:
                if verificar_credenciales(username, password):
                    login()
                    st.success("✅ Sesión iniciada")
                    st.rerun()
                else:
                    st.error("❌ Credenciales incorrectas")

# ==================== PÁGINA INTRO ====================
if st.session_state.seccion == 'intro':
    st.markdown('<div class="mapeo-title">TRAMAS</div>', unsafe_allow_html=True)
    st.markdown('<p style="font-family: \'Roboto Slab\', serif; font-size: 1.2rem; text-align: center; color: #666;">Tejidos en Red: Análisis y Mapeos Sociales</p>', unsafe_allow_html=True)

    st.markdown("""
    <div class="question-box">
        <h3 style="font-family: 'Roboto', sans-serif; margin-bottom: 1rem;">Bienvenida a TRAMAS</h3>
        <p style="line-height: 1.8;">
            TRAMAS es una plataforma de mapeos sociales para conocer redes y organizaciones culturales,
            sociales y creativas en América Latina. Es realizada por académicos y académicas de la región.
            Aquí podrás participar en diferentes mapeos y conocer los resultados de estas investigaciones colaborativas.
        </p>
        <p style="line-height: 1.8; margin-top: 1rem;">
            Selecciona un mapeo del menú lateral para comenzar.
            Te agradecemos todo el apoyo, tu aporte es esencial para nuestro trabajo.
        </p>
    </div>
    """, unsafe_allow_html=True)

# ==================== MAPEO GESTIÓN CULTURAL ====================
elif st.session_state.seccion == 'mapeo1':
    st.markdown('<div class="mapeo-title">Mapeo de Gestión Cultural y Digital en Latinoamérica</div>', unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["📝 Participar en Encuesta", "📊 Ver Resultados"])

    with tab1:
        mostrar_encuesta()

    with tab2:
        mostrar_mapas()
