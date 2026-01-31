import streamlit as st
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
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
        'Planeación intuitiva': 5,
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
    # Multiplicadores de importancia
    multiplicadores_herramientas = {
        "Totalmente fundamentales": 1.0,
        "Fundamentales para algunas tareas": 0.75,
        "Muy poco fundamentales": 0.5,
        "Nada no las uso tanto": 0.25
    }
    multiplicadores_ias = {
        "Totalmente fundamentales": 1.0,
        "Fundamentales para algunas tareas": 0.75,
        "Me aportan muy poco no las uso tanto": 0.5,
        "No sé utilizarlas muy bien quisiera manejarlas mejor": 0.25
    }
    multiplicadores_comunidades = {
        "Totalmente fundamentales participo de forma activa": 1.0,
        "Fundamentales en algunos casos": 0.75,
        "Muy poco fundamentales no participo casi nunca": 0.5,
        "No las uso solo estoy inscrito pero no participo": 0.25
    }

    # Obtener multiplicadores según respuestas
    mult_herr = multiplicadores_herramientas.get(respuesta.get('importancia_herramientas', ''), 1.0)
    mult_ias = multiplicadores_ias.get(respuesta.get('importancia_ias', ''), 1.0)
    mult_com = multiplicadores_comunidades.get(respuesta.get('importancia_comunidades', ''), 1.0)

    puntaje = 0

    # Herramientas utilizadas: 30 pts máx
    num_herramientas = respuesta.get('num_herramientas', 0)
    puntaje += min(num_herramientas * 3, 30) * mult_herr

    # Herramientas pagadas: 10 pts máx
    num_herramientas_pagadas = respuesta.get('num_herramientas_pagadas', 0)
    puntaje += min(num_herramientas_pagadas * 2, 10) * mult_herr

    # IAs utilizadas: 30 pts máx
    num_ias = respuesta.get('num_ias', 0)
    puntaje += min(num_ias * 4, 30) * mult_ias

    # IAs pagadas: 10 pts máx
    num_ias_pagadas = respuesta.get('num_ias_pagadas', 0)
    puntaje += min(num_ias_pagadas * 2, 10) * mult_ias

    # Comunidades: 20 pts máx
    num_comunidades = respuesta.get('num_comunidades', 0)
    puntaje += min(num_comunidades * 3, 20) * mult_com

    return round(min(puntaje, 100))

def calcular_tipo_org_score_total(organizaciones):
    """Calcula el score total de tipo de organización (limitado a -10 a +10)"""
    total = 0
    for org in organizaciones:
        total += calcular_tipo_organizacion_score(org.get('tipo', ''))
    return max(-10, min(total, 10))

# ==================== GOOGLE SHEETS ====================
# CÓDIGO MODIFICADO PARA FUNCIONAR EN RAILWAY Y STREAMLIT CLOUD

import time
import os
import json

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def obtener_credenciales_google():
    """
    Obtiene las credenciales de Google desde:
    1. Variables de entorno (Railway, Render, etc.)
    2. Streamlit Secrets (Streamlit Cloud)
    """
    # Opción 1: Variable de entorno GOOGLE_CREDENTIALS (Railway/Render)
    if os.environ.get('GOOGLE_CREDENTIALS'):
        try:
            creds_json = json.loads(os.environ['GOOGLE_CREDENTIALS'])
            spreadsheet_id = os.environ.get('SPREADSHEET_ID', '')
            return creds_json, spreadsheet_id, None
        except json.JSONDecodeError as e:
            return None, None, f"Error parseando GOOGLE_CREDENTIALS: {e}"

    # Opción 2: Streamlit Secrets (Streamlit Cloud)
    try:
        if "gcp_service_account" in st.secrets:
            creds = dict(st.secrets["gcp_service_account"])
            spreadsheet_id = st.secrets.get("google_sheets", {}).get("spreadsheet_id", "")
            return creds, spreadsheet_id, None
    except Exception:
        pass

    return None, None, "No se encontraron credenciales de Google (ni en variables de entorno ni en Streamlit Secrets)"

@st.cache_resource(ttl=300)  # Cache por 5 minutos
def obtener_cliente_gspread():
    """Obtiene cliente gspread con caché para evitar múltiples autenticaciones"""
    try:
        creds_info, _, error = obtener_credenciales_google()

        if error:
            return None, error

        if creds_info is None:
            return None, "No se encontraron credenciales de Google"

        required_fields = ["type", "project_id", "private_key", "client_email"]
        for field in required_fields:
            if field not in creds_info:
                return None, f"Falta el campo '{field}' en las credenciales"

        credentials = Credentials.from_service_account_info(
            creds_info,
            scopes=SCOPES
        )
        client = gspread.authorize(credentials)
        return client, None
    except Exception as e:
        return None, str(e)

@st.cache_resource(ttl=300)  # Cache la hoja por 5 minutos
def obtener_spreadsheet():
    """Obtiene el spreadsheet completo con caché"""
    client, error = obtener_cliente_gspread()
    if client is None:
        return None, error
    try:
        _, spreadsheet_id, error = obtener_credenciales_google()
        if error or not spreadsheet_id:
            return None, "No se encontró el ID del spreadsheet"
        spreadsheet = client.open_by_key(spreadsheet_id)
        return spreadsheet, None
    except Exception as e:
        return None, str(e)

def conectar_google_sheets(mostrar_errores=True):
    """Conecta con Google Sheets usando spreadsheet cacheado"""
    try:
        spreadsheet, error = obtener_spreadsheet()
        if spreadsheet is None:
            if mostrar_errores:
                st.error(f"❌ {error}")
            return None
        return spreadsheet.sheet1
    except gspread.exceptions.SpreadsheetNotFound:
        if mostrar_errores:
            st.error("❌ No se encontró la hoja de cálculo. Verifica el ID del spreadsheet.")
        return None
    except gspread.exceptions.APIError as e:
        if mostrar_errores:
            st.error(f"❌ Error de API de Google: {e}")
        return None
    except Exception as e:
        if mostrar_errores:
            st.error(f"❌ Error conectando: {type(e).__name__}: {e}")
        return None

HEADERS_SHEETS = [
    'timestamp', 'num_organizaciones', 'num_proyectos', 'artista_independiente',
    'organizaciones_tipos', 'organizaciones_cargos', 'proyectos_nombres', 'proyectos_cargos',
    'jerarquia', 'planeacion', 'ecosistema', 'redes', 'funciones', 'liderazgo', 'liderazgo_propio',
    'identidad', 'importancia_formalidad', 'herramientas_admin_conoce', 'herramientas_admin_aplica',
    'herramientas', 'herramientas_pagadas', 'importancia_herramientas',
    'ias', 'ias_pagadas', 'importancia_ias', 'comunidades', 'importancia_comunidades',
    'pais', 'ciudad', 'edad', 'nivel_academico', 'nombre', 'correo', 'telefono',
    'entrevista', 'convocatorias', 'tipo_org_score', 'nivel_formalizacion',
    'nivel_digitalizacion'
]

def guardar_respuesta_sheets(respuesta, max_reintentos=3):
    """Guarda una respuesta en Google Sheets con reintentos para rate limiting"""

    # Preparar los datos para la fila ANTES de conectar (para minimizar tiempo de conexión)
    fila = [
        respuesta.get('demograficos', {}).get('timestamp', ''),
        respuesta.get('num_organizaciones', 0),
        respuesta.get('num_proyectos', 0),
        '|'.join(respuesta.get('labores_profesionales', [])),
        respuesta.get('artista_independiente', ''),
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
        respuesta.get('herramientas_admin', {}).get('liderazgo_propio', ''),
        respuesta.get('herramientas_admin', {}).get('identidad', ''),
        respuesta.get('herramientas_admin', {}).get('importancia_formalidad', ''),
        '|'.join(respuesta.get('herramientas_admin', {}).get('herramientas_admin_conoce', [])),
        '|'.join(respuesta.get('herramientas_admin', {}).get('herramientas_admin_aplica', [])),
        '|'.join(respuesta.get('herramientas_digitales', {}).get('herramientas', [])),
        '|'.join(respuesta.get('herramientas_digitales', {}).get('herramientas_pagadas', [])),
        respuesta.get('herramientas_digitales', {}).get('importancia_herramientas', ''),
        '|'.join(respuesta.get('herramientas_digitales', {}).get('ias', [])),
        '|'.join(respuesta.get('herramientas_digitales', {}).get('ias_pagadas', [])),
        respuesta.get('herramientas_digitales', {}).get('importancia_ias', ''),
        '|'.join(respuesta.get('herramientas_digitales', {}).get('comunidades', [])),
        respuesta.get('herramientas_digitales', {}).get('importancia_comunidades', ''),
        respuesta.get('demograficos', {}).get('pais', ''),
        respuesta.get('demograficos', {}).get('ciudad', ''),
        respuesta.get('demograficos', {}).get('edad', ''),
        respuesta.get('demograficos', {}).get('nivel_academico', ''),
        respuesta.get('demograficos', {}).get('nombre', ''),
        respuesta.get('demograficos', {}).get('correo', ''),
        respuesta.get('demograficos', {}).get('telefono', ''),
        respuesta.get('demograficos', {}).get('entrevista', ''),
        '|'.join(respuesta.get('demograficos', {}).get('convocatorias', [])),
        respuesta.get('demograficos', {}).get('mascaras', ''),
        calcular_tipo_org_score_total(respuesta.get('organizaciones', [])),
        calcular_nivel_formalizacion(respuesta.get('herramientas_admin', {})),
        calcular_nivel_digitalizacion(respuesta.get('herramientas_digitales', {}))
    ]

    for intento in range(max_reintentos):
        try:
            sheet = conectar_google_sheets(mostrar_errores=(intento == max_reintentos - 1))
            if sheet is None:
                if intento < max_reintentos - 1:
                    time.sleep(2 ** intento)  # Backoff exponencial: 1s, 2s, 4s
                    continue
                st.error("❌ No se pudo conectar con Google Sheets")
                return False

            sheet.append_row(fila)
            st.success("✅ Respuesta guardada correctamente")
            return True
        except gspread.exceptions.APIError as e:
            if "429" in str(e) and intento < max_reintentos - 1:
                time.sleep(2 ** intento)
                continue
            st.error(f"❌ Error de API al guardar: {e}")
            st.info("💡 Verifica que la cuenta de servicio tenga permisos de Editor en el Sheet")
            return False
        except Exception as e:
            st.error(f"❌ Error guardando respuesta: {type(e).__name__}: {e}")
            return False

    return False

def cargar_respuestas_sheets():
    """Carga todas las respuestas desde Google Sheets"""
    sheet = conectar_google_sheets()
    if sheet is None:
        return []

    try:
        # Verificar si hay datos
        all_values = sheet.get_all_values()
        if len(all_values) <= 1:  # Solo headers o vacío
            return []

        datos = sheet.get_all_records()
        return datos
    except gspread.exceptions.APIError as e:
        st.error(f"❌ Error de API al cargar datos: {e}")
        return []
    except Exception as e:
        st.error(f"❌ Error cargando respuestas: {type(e).__name__}: {e}")
        return []

# ==================== GOOGLE SHEETS - STREAMING (Hoja2) ====================

def conectar_google_sheets_streaming(mostrar_errores=True):
    """Conecta con la Hoja2 de Google Sheets usando spreadsheet cacheado"""
    try:
        spreadsheet, error = obtener_spreadsheet()
        if spreadsheet is None:
            if mostrar_errores:
                st.error(f"❌ {error}")
            return None
        return spreadsheet.worksheet("Hoja2")
    except gspread.exceptions.WorksheetNotFound:
        if mostrar_errores:
            st.error("❌ No se encontró 'Hoja2'. Créala en tu Google Sheets.")
        return None
    except gspread.exceptions.APIError as e:
        if mostrar_errores:
            st.error(f"❌ Error de API de Google: {e}")
        return None
    except Exception as e:
        if mostrar_errores:
            st.error(f"❌ Error conectando a Hoja2: {type(e).__name__}: {e}")
        return None

def guardar_respuesta_streaming(respuesta, max_reintentos=3):
    """Guarda una respuesta de streaming en Google Sheets Hoja2"""

    # Preparar fila con columnas separadas para ingresos y streams
    plataformas = respuesta.get('plataformas', {})

    fila = [
        respuesta.get('timestamp', ''),
        respuesta.get('pais', ''),
        respuesta.get('tipo_distribucion', ''),
        plataformas.get('Spotify', {}).get('ingresos', 0),
        plataformas.get('Spotify', {}).get('reproducciones', 0),
        plataformas.get('Apple Music', {}).get('ingresos', 0),
        plataformas.get('Apple Music', {}).get('reproducciones', 0),
        plataformas.get('YouTube', {}).get('ingresos', 0),
        plataformas.get('YouTube', {}).get('reproducciones', 0),
        plataformas.get('Tidal', {}).get('ingresos', 0),
        plataformas.get('Tidal', {}).get('reproducciones', 0),
        plataformas.get('Amazon Music', {}).get('ingresos', 0),
        plataformas.get('Amazon Music', {}).get('reproducciones', 0),
        plataformas.get('Otros', {}).get('ingresos', 0),
        plataformas.get('Otros', {}).get('reproducciones', 0)
    ]

    for intento in range(max_reintentos):
        try:
            sheet = conectar_google_sheets_streaming(mostrar_errores=(intento == max_reintentos - 1))
            if sheet is None:
                if intento < max_reintentos - 1:
                    time.sleep(2 ** intento)
                    continue
                return False

            sheet.append_row(fila)
            st.success("✅ Respuesta guardada correctamente")
            return True
        except gspread.exceptions.APIError as e:
            if "429" in str(e) and intento < max_reintentos - 1:
                time.sleep(2 ** intento)
                continue
            st.error(f"❌ Error de API al guardar: {e}")
            return False
        except Exception as e:
            st.error(f"❌ Error guardando: {type(e).__name__}: {e}")
            return False

    return False

def cargar_respuestas_streaming():
    """Carga todas las respuestas de streaming desde Hoja2"""
    sheet = conectar_google_sheets_streaming(mostrar_errores=True)
    if sheet is None:
        return []

    try:
        all_values = sheet.get_all_values()

        if len(all_values) <= 1:
            return []

        datos = []

        def safe_int(valor):
            """Convierte a entero de forma segura"""
            try:
                if not valor:
                    return 0
                return int(float(str(valor).replace(',', '')))
            except:
                return 0

        def safe_get(row, index, default=''):
            """Obtiene un valor de la fila de forma segura"""
            return row[index] if index < len(row) else default

        for row in all_values[1:]:
            if len(row) >= 3:  # Mínimo: timestamp, pais, tipo_dist
                datos.append({
                    'timestamp': safe_get(row, 0),
                    'pais': safe_get(row, 1),
                    'tipo_distribucion': safe_get(row, 2),
                    'plataformas': {
                        'Spotify': {
                            'ingresos': safe_int(safe_get(row, 3)),
                            'reproducciones': safe_int(safe_get(row, 4))
                        },
                        'Apple Music': {
                            'ingresos': safe_int(safe_get(row, 5)),
                            'reproducciones': safe_int(safe_get(row, 6))
                        },
                        'YouTube': {
                            'ingresos': safe_int(safe_get(row, 7)),
                            'reproducciones': safe_int(safe_get(row, 8))
                        },
                        'Tidal': {
                            'ingresos': safe_int(safe_get(row, 9)),
                            'reproducciones': safe_int(safe_get(row, 10))
                        },
                        'Amazon Music': {
                            'ingresos': safe_int(safe_get(row, 11)),
                            'reproducciones': safe_int(safe_get(row, 12))
                        },
                        'Otros': {
                            'ingresos': safe_int(safe_get(row, 13)),
                            'reproducciones': safe_int(safe_get(row, 14))
                        }
                    }
                })

        return datos
    except gspread.exceptions.APIError as e:
        st.error(f"❌ Error de API al cargar datos: {e}")
        return []
    except Exception as e:
        st.error(f"❌ Error cargando respuestas streaming: {type(e).__name__}: {e}")
        return []

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
        herramientas_pagadas_str = str(resp.get('herramientas_pagadas', ''))
        ias_str = str(resp.get('ias', ''))
        ias_pagadas_str = str(resp.get('ias_pagadas', ''))
        comunidades_str = str(resp.get('comunidades', ''))
        labores_str = str(resp.get('labores_profesionales', ''))

        num_herramientas = len([h for h in herramientas_str.split('|') if h]) if herramientas_str else 0
        num_herramientas_pagadas = len([h for h in herramientas_pagadas_str.split('|') if h]) if herramientas_pagadas_str else 0
        num_ias = len([i for i in ias_str.split('|') if i and i != 'Ninguna']) if ias_str else 0
        num_ias_pagadas = len([i for i in ias_pagadas_str.split('|') if i]) if ias_pagadas_str else 0
        num_comunidades = len([c for c in comunidades_str.split('|') if c]) if comunidades_str else 0
        labores_list = [l for l in labores_str.split('|') if l] if labores_str else []
        num_labores = len(labores_list)

        datos_procesados.append({
            'num_organizaciones': resp.get('num_organizaciones', 0),
            'num_proyectos': resp.get('num_proyectos', 0),
            'total_entidades': resp.get('num_organizaciones', 0) + resp.get('num_proyectos', 0),
            'tipo_org_score': max(-10, min(int(resp.get('tipo_org_score', 0) or 0), 10)),
            'nivel_formalizacion': min(int(resp.get('nivel_formalizacion', 0) or 0), 100),
            'nivel_digitalizacion': min(int(resp.get('nivel_digitalizacion', 0) or 0), 100),
            'jerarquia': resp.get('jerarquia', ''),
            'planeacion': resp.get('planeacion', ''),
            'ecosistema': resp.get('ecosistema', ''),
            'redes': resp.get('redes', ''),
            'liderazgo': resp.get('liderazgo', ''),
            'artista_independiente': resp.get('artista_independiente', ''),
            'labores_profesionales': labores_str,
            'num_labores': num_labores,
            'num_herramientas': num_herramientas,
            'num_herramientas_pagadas': num_herramientas_pagadas,
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

    # Filtros de medición
    st.markdown("### Filtros de Medición")
    col5, col6, col7 = st.columns(3)

    with col5:
        # Rangos para nivel de digitalización
        rangos_digitalizacion = ['Todos', 'Bajo (0-33)', 'Medio (34-66)', 'Alto (67-100)']
        filtro_digitalizacion = st.selectbox("Nivel de Digitalización:", rangos_digitalizacion, key="f_digitalizacion")

    with col6:
        # Rangos para nivel de formalización
        rangos_formalizacion = ['Todos', 'Bajo (0-33)', 'Medio (34-66)', 'Alto (67-100)']
        filtro_formalizacion = st.selectbox("Nivel de Formalización:", rangos_formalizacion, key="f_formalizacion")

    with col7:
        # Tipo de artista independiente
        tipos_artista = ['Todos'] + sorted([a for a in df_datos['artista_independiente'].unique().tolist() if a])
        filtro_artista = st.selectbox("Nivel de independencia:", tipos_artista, key="f_artista")

    # Aplicar filtros
    filtros = {
        'pais': filtro_pais,
        'ciudad': filtro_ciudad,
        'edad': filtro_edad,
        'nivel_academico': filtro_nivel
    }

    df_filtrado = filtrar_datos(df_datos, filtros)

    # Aplicar filtros de medición
    if filtro_digitalizacion != 'Todos':
        if filtro_digitalizacion == 'Bajo (0-33)':
            df_filtrado = df_filtrado[df_filtrado['nivel_digitalizacion'] <= 33]
        elif filtro_digitalizacion == 'Medio (34-66)':
            df_filtrado = df_filtrado[(df_filtrado['nivel_digitalizacion'] > 33) & (df_filtrado['nivel_digitalizacion'] <= 66)]
        elif filtro_digitalizacion == 'Alto (67-100)':
            df_filtrado = df_filtrado[df_filtrado['nivel_digitalizacion'] > 66]

    if filtro_formalizacion != 'Todos':
        if filtro_formalizacion == 'Bajo (0-33)':
            df_filtrado = df_filtrado[df_filtrado['nivel_formalizacion'] <= 33]
        elif filtro_formalizacion == 'Medio (34-66)':
            df_filtrado = df_filtrado[(df_filtrado['nivel_formalizacion'] > 33) & (df_filtrado['nivel_formalizacion'] <= 66)]
        elif filtro_formalizacion == 'Alto (67-100)':
            df_filtrado = df_filtrado[df_filtrado['nivel_formalizacion'] > 66]

    if filtro_artista != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['artista_independiente'] == filtro_artista]

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

    # 1. Participación promedio y labores profesionales
    st.markdown("#### 1. Participación promedio")

    # Calcular estadísticas de labores profesionales
    total_encuestados = len(df_filtrado)
    total_labores = df_filtrado['num_labores'].sum()
    prom_labores = df_filtrado['num_labores'].mean() if total_encuestados > 0 else 0

    # Contar cada tipo de labor
    labores_opciones = ["Creación", "Producción", "Gestión", "Educación formal",
                        "Educación informal", "Representación de artistas", "Inversionista", "Estudiante"]
    labores_conteo = {labor: 0 for labor in labores_opciones}

    for labores_str in df_filtrado['labores_profesionales']:
        if labores_str:
            for labor in str(labores_str).split('|'):
                labor = labor.strip()
                if labor in labores_conteo:
                    labores_conteo[labor] += 1

    # Mostrar totales
    st.markdown(f"""
    <div style="background-color: #f8f9fa; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
        <p style="font-size: 1.1rem; margin: 0;"><strong>Total encuestados:</strong> {total_encuestados}</p>
        <p style="font-size: 1.1rem; margin: 0.5rem 0 0 0;"><strong>Total labores que realizan:</strong> {total_labores}</p>
    </div>
    """, unsafe_allow_html=True)

    # Gráfico de barras de labores profesionales
    fig_labores = go.Figure(data=[
        go.Bar(
            x=list(labores_conteo.keys()),
            y=list(labores_conteo.values()),
            marker_color=['#1e3a5f', '#0077b6', '#00b4d8', '#48cae4', '#7b2cbf', '#c77dff', '#2d6a4f', '#40916c'],
            text=list(labores_conteo.values()),
            textposition='outside'
        )
    ])
    fig_labores.update_layout(
        yaxis_title="Cantidad de personas",
        xaxis_title="Labores profesionales",
        height=400,
        showlegend=False,
        plot_bgcolor='white',
        yaxis=dict(gridcolor='#e0e0e0'),
        xaxis=dict(tickangle=-45)
    )
    st.plotly_chart(fig_labores, use_container_width=True)

    # Promedios de organizaciones, proyectos y labores
    prom_orgs = df_filtrado['num_organizaciones'].mean()
    prom_proys = df_filtrado['num_proyectos'].mean()

    col_prom1, col_prom2, col_prom3 = st.columns(3)
    with col_prom1:
        st.markdown(f"""
        <div style="background-color: #5D80B5; color: white; padding: 1.5rem; border-radius: 10px; text-align: center;">
            <p style="font-size: 1.1rem; margin-bottom: 0.5rem;">Promedio de organizaciones a las que pertenecen las personas:</p>
            <p style="font-size: 2.5rem; font-weight: bold; margin: 0;">{prom_orgs:.1f}</p>
        </div>
        """, unsafe_allow_html=True)
    with col_prom2:
        st.markdown(f"""
        <div style="background-color: #A870B0; color: white; padding: 1.5rem; border-radius: 10px; text-align: center;">
            <p style="font-size: 1.1rem; margin-bottom: 0.5rem;">Promedio de proyectos en los que participan las personas:</p>
            <p style="font-size: 2.5rem; font-weight: bold; margin: 0;">{prom_proys:.1f}</p>
        </div>
        """, unsafe_allow_html=True)
    with col_prom3:
        st.markdown(f"""
        <div style="background-color: #2d6a4f; color: white; padding: 1.5rem; border-radius: 10px; text-align: center;">
            <p style="font-size: 1.1rem; margin-bottom: 0.5rem;">Promedio de labores por persona:</p>
            <p style="font-size: 2.5rem; font-weight: bold; margin: 0;">{prom_labores:.1f}</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("")

    # 2. Gráficas de círculo para jerarquía y planeación
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 2a. Tipos de jerarquía")
        jer_counts = df_filtrado['jerarquia'].value_counts()
        # Colores azules con alto contraste
        colores_azul = ['#03045e', '#0077b6', '#00b4d8', '#90e0ef', '#caf0f8']
        fig_jer = go.Figure(data=[go.Pie(
            labels=jer_counts.index.tolist(),
            values=jer_counts.values.tolist(),
            hole=0.3,
            marker_colors=colores_azul[:len(jer_counts)],
            textinfo='percent',
            textposition='outside'
        )])
        fig_jer.update_layout(
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5, font=dict(size=10)),
            height=350,
            margin=dict(t=20, b=80, l=20, r=20)
        )
        st.plotly_chart(fig_jer, use_container_width=True)

    with col2:
        st.markdown("#### 2b. Tipos de planeación")
        plan_counts = df_filtrado['planeacion'].value_counts()
        # Colores morados con alto contraste
        colores_morado = ['#4a0080', '#7b2cbf', '#c77dff', '#e0aaff', '#f3d5ff', '#fce4ff']
        fig_plan = go.Figure(data=[go.Pie(
            labels=plan_counts.index.tolist(),
            values=plan_counts.values.tolist(),
            hole=0.3,
            marker_colors=colores_morado[:len(plan_counts)],
            textinfo='percent',
            textposition='outside'
        )])
        fig_plan.update_layout(
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5, font=dict(size=10)),
            height=350,
            margin=dict(t=20, b=80, l=20, r=20)
        )
        st.plotly_chart(fig_plan, use_container_width=True)

    # 3. Gráficas de ecosistemas y redes
    col3a, col3b = st.columns(2)

    with col3a:
        st.markdown("#### 3a. Tipos de ecosistemas")
        eco_counts = df_filtrado['ecosistema'].value_counts()
        # Colores azules con alto contraste
        colores_azul_eco = ['#03045e', '#0077b6', '#00b4d8', '#90e0ef', '#caf0f8']
        fig_eco = go.Figure(data=[go.Pie(
            labels=eco_counts.index.tolist(),
            values=eco_counts.values.tolist(),
            hole=0.3,
            marker_colors=colores_azul_eco[:len(eco_counts)],
            textinfo='percent',
            textposition='outside'
        )])
        fig_eco.update_layout(
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5, font=dict(size=10)),
            height=350,
            margin=dict(t=20, b=80, l=20, r=20)
        )
        st.plotly_chart(fig_eco, use_container_width=True)

    with col3b:
        st.markdown("#### 3b. Tipos de redes")
        redes_counts = df_filtrado['redes'].value_counts()
        # Colores morados con alto contraste
        colores_morado_redes = ['#4a0080', '#7b2cbf', '#c77dff', '#e0aaff', '#f3d5ff', '#fce4ff']
        fig_redes = go.Figure(data=[go.Pie(
            labels=redes_counts.index.tolist(),
            values=redes_counts.values.tolist(),
            hole=0.3,
            marker_colors=colores_morado_redes[:len(redes_counts)],
            textinfo='percent',
            textposition='outside'
        )])
        fig_redes.update_layout(
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5, font=dict(size=10)),
            height=350,
            margin=dict(t=20, b=80, l=20, r=20)
        )
        st.plotly_chart(fig_redes, use_container_width=True)

    # 4. Tipos de liderazgo
    st.markdown("#### 4. Tipos de liderazgo")
    lider_counts = df_filtrado['liderazgo'].value_counts()
    # Colores azules con alto contraste
    colores_azul_lider = ['#03045e', '#0077b6', '#00b4d8', '#90e0ef', '#caf0f8']
    fig_lider = go.Figure(data=[go.Pie(
        labels=lider_counts.index.tolist(),
        values=lider_counts.values.tolist(),
        hole=0.3,
        marker_colors=colores_azul_lider[:len(lider_counts)],
        textinfo='percent',
        textposition='outside'
    )])
    fig_lider.update_layout(
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5, font=dict(size=10)),
        height=400,
        margin=dict(t=20, b=80, l=20, r=20)
    )
    st.plotly_chart(fig_lider, use_container_width=True)

    # 5. Promedios de herramientas digitales
    st.markdown("#### 5. Uso promedio de herramientas digitales por persona")

    prom_herramientas = df_filtrado['num_herramientas'].mean()
    prom_herr_pagadas = df_filtrado['num_herramientas_pagadas'].mean()
    prom_ias = df_filtrado['num_ias'].mean()
    prom_ias_pagadas = df_filtrado['num_ias_pagadas'].mean()
    prom_comunidades = df_filtrado['num_comunidades'].mean()

    categorias = ['Herramientas\ndigitales', 'Herramientas\npagadas', 'IAs\nusadas', 'IAs\npagadas', 'Comunidades']
    promedios = [prom_herramientas, prom_herr_pagadas, prom_ias, prom_ias_pagadas, prom_comunidades]
    # Colores con alto contraste
    colores_barras = ['#1e3a5f', '#0077b6', '#7b2cbf', '#c77dff', '#2d6a4f']

    fig_herr = go.Figure(data=[
        go.Bar(
            x=categorias,
            y=promedios,
            marker_color=colores_barras,
            text=[f"{p:.1f}" for p in promedios],
            textposition='outside'
        )
    ])
    fig_herr.update_layout(
        yaxis_title="Promedio por persona",
        height=400,
        showlegend=False,
        plot_bgcolor='white',
        yaxis=dict(gridcolor='#e0e0e0')
    )
    st.plotly_chart(fig_herr, use_container_width=True)

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
    <div class="question-box" style="margin-top: 1.5rem; border-left: 4px solid #A870B0;">
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
    
    # Checkbox de consentimiento
    acepta_datos = st.checkbox(
        "He leído y acepto el tratamiento de mis datos personales.",
        key="acepta_datos"
    )

    if acepta_datos:
        if st.button("INICIAR ENCUESTA ➡️", use_container_width=True):
            st.session_state.encuesta_page = 1
            st.rerun()
    else:
        st.button("INICIAR ENCUESTA ➡️", use_container_width=True, disabled=True)
        st.caption("Debes aceptar el tratamiento de datos para continuar.")
    
    # Aviso de tratamiento de datos
    st.markdown("""
    <div class="question-box">
        <h4 style="font-family: 'Roboto', sans-serif; margin-bottom: 1rem;">Aviso de Tratamiento de Datos Personales</h4>
        <p style="line-height: 1.6; font-size: 0.95rem;">
            Al participar en esta encuesta, autorizas el tratamiento de tus datos personales conforme a lo siguiente:
        </p>
        <p style="line-height: 1.6; margin-top: 0.8rem; font-size: 0.95rem;">
            <strong>Responsables:</strong> El Chorro Producciones (Colombia) y Huika Mexihco (México),
            en el marco del proyecto de investigación enmarcado en la plataforma "TRAMAS: Tejidos en Red, Análisis y Mapeos Sociales".
        </p>
        <p style="line-height: 1.6; margin-top: 0.8rem; font-size: 0.95rem;">
            <strong>Finalidad:</strong> Tus respuestas serán utilizadas exclusivamente para fines de investigación
            académica. Los resultados se presentarán de forma agregada y anónima.
        </p>
        <p style="line-height: 1.6; margin-top: 0.8rem; font-size: 0.95rem;">
            <strong>Datos recopilados:</strong> Información sobre tu participación en organizaciones y proyectos
            culturales, herramientas de gestión y digitales que utilizas, y datos demográficos básicos
            (país, ciudad, rango de edad, nivel académico).
        </p>
        <p style="line-height: 1.6; margin-top: 0.8rem; font-size: 0.95rem;">
            <strong>Datos opcionales:</strong> Nombre, correo electrónico y teléfono son voluntarios y solo se
            usarán para contactarte si aceptas participar en entrevistas o convocatorias.
        </p>
        <p style="line-height: 1.6; margin-top: 0.8rem; font-size: 0.95rem;">
            <strong>Derechos:</strong> Puedes solicitar acceso, corrección o eliminación de tus datos escribiendo a
            <a href="mailto:info@elchorro.com.co" style="color: #A870B0;">info@elchorro.com.co</a>.
        </p>
        <p style="line-height: 1.6; margin-top: 0.8rem; font-size: 0.95rem;">
            <strong>Protección:</strong> Tus datos se almacenan de forma segura y no serán compartidos con terceros
            fuera del equipo de investigación.
        </p>
    </div>
    """, unsafe_allow_html=True)

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

    st.markdown("### De los siguientes, ¿qué labores desarrollas en tu ámbito profesional? (selecciona todas las que apliquen en tu trabajo, independientemente de cuántos tengas, cuántos proyectos haces o a cuántas organizaciones perteneces)")
    labores_profesionales = st.multiselect(
        "Selecciona todas las que apliquen:",
        [
            "Creación",
            "Producción",
            "Gestión",
            "Educación formal",
            "Educación informal",
            "Representación de artistas",
            "Inversionista",
            "Estudiante"
        ],
        key="labores_profesionales"
    )

    st.markdown("### ¿Te reconoces como artista independiente?")
    artista_independiente = st.selectbox(
        "Selecciona una opción:",
        [
            "Sí totalmente",
            "Sí pero quisiera estar en otro segmento",
            "Medianamente (trabajo con empresas tradicionales del sector)",
            "Medianamente (participo activamente con organizaciones públicas o gobierno)",
            "No porque trabajo principalmente con empresas de producción masiva"
        ],
        key="artista_independiente"
    )

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
                    'labores_profesionales': labores_profesionales,
                    'artista_independiente': artista_independiente,
                    'organizaciones': orgs_data,
                    'proyectos': proyectos_data
                })
                st.session_state.encuesta_page = 2
                st.rerun()

def pagina_herramientas_admin():
    st.markdown("### Herramientas Administrativas y Gestivas")
 
    jerarquia = st.selectbox(
        "**1. ¿Cómo son tus relaciones de trabajo?**",
        ["Altamente jerarquizadas", "En general menos de 3 niveles jerárquicos",
         "Nos repartimos los liderazgos y funciones", "No reconozco jerarquías"]
    )

    planeacion = st.selectbox(
        "**2. ¿Cómo es tu forma de planeación?**",
        ["Hago o llevo un plan estratégico periódico y se revisa por la dirección",
         "Tengo un plan estratégico que se comunica de manera oficial",
         "Tengo un plan estratégico pero no lo comunico",
         "Participo en el desarrollo del plan estratégico en colectivo",
         "Planeación intuitiva",
         "No tengo ninguna planeación"]
    )

    ecosistema = st.selectbox(
        "**3. ¿Reconoces el ecosistema al que perteneces?** (por ecosistema se entiende: la configuración del sector creativo al que perteneces donde participan e intermedian personas de múltiples disciplinas)",
        ["Participo formalmente con otras organizaciones de diferentes sectores",
         "Participo informalmente con organizaciones de diferentes sectores",
         "Participo con organizaciones del mismo sector",
         "No reconozco participación con nadie más"]
    )

    funciones = st.selectbox(
        "**4. ¿Cómo son tus funciones y labores?**",
        ["Roles claramente identificados y bajo contrato",
         "Roles identificados y formalizados",
         "Roles informales pero identificables",
         "Roles informales fluidos",
         "No tengo roles definidos"]
    )

    liderazgo = st.selectbox(
        "**5. ¿Cómo es el liderazgo de otras personas en tus espacios de trabajo?**",
        ["Líderes específicos para cada área",
         "Líderes específicos según el proyecto",
         "Liderazgo compartido por conocimiento",
         "Sin liderazgo claro"]
    )

    liderazgo_propio = st.selectbox(
        "**6. ¿Cómo es tu tipo de liderazgo?**",
        ["Es específico para un área o departamento",
         "Lidero todos mis proyectos",
         "Lidero algunos proyectos",
         "Comparto el liderazgo",
         "No soy líder de mis proyectos"]
    )

    identidad = st.selectbox(
        "**7. ¿Tienes una identidad definida?**",
        ["Marca con manual definido",
         "Marca definida, identidad informal",
         "Una marca más bien fluida",
         "Llevo una marca por línea de trabajo",
         "Sin identidad definida"]
    )
    
    importancia_formalidad = st.selectbox(
        "**8. ¿Qué tan importante es la formalidad en tus relaciones laborales para lograr un buen desempeño de tus proyectos?** (por formalidad se entiende: tener manuales y procedimientos escritos, reglamentación, seguimiento para asegurar el cumplimiento y divulgación de estos documentos)",
        ["Muy importantes",
         "Mucho pero a veces dificulta relaciones",
         "No tanto prefiero relaciones más fluidas",
         "No es nada importante"]
    )

    herramientas_admin_conoce = st.multiselect(
        "**9. ¿Conoces alguna de estas herramientas?**, Selecciona las que conoces:",
        ["Planeación estratégica", "Recursos Humanos", "Mercadotecnia",
         "Control de gestión", "Proceso administrativo (planear, organizar, controlar, dirigir)",
         "Otras", "Ninguna"],
        key="herramientas_admin_conoce"
    )

    if herramientas_admin_conoce and "Ninguna" not in herramientas_admin_conoce:
        st.markdown("**10. ¿Aplicas alguna de ellas?**")
        herramientas_admin_aplica = st.multiselect(
            "Selecciona las que aplicas:",
            [h for h in herramientas_admin_conoce if h != "Otras"],
            key="herramientas_admin_aplica"
        )
    else:
        herramientas_admin_aplica = []

    redes = st.selectbox(
        "**11. ¿Tienes una red de trabajo consolidada?** (por red se entiende: las relaciones con las personas u organizaciones con quienes trabajas)",
        ["Participo activamente con organizaciones del sector",
         "Reconozco organizaciones pero no me reconocen",
         "Estoy consolidando lazos",
         "No participo con nadie"]
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
                'liderazgo_propio': liderazgo_propio,
                'identidad': identidad,
                'importancia_formalidad': importancia_formalidad,
                'herramientas_admin_conoce': herramientas_admin_conoce,
                'herramientas_admin_aplica': herramientas_admin_aplica
            }
            st.session_state.encuesta_page = 3
            st.rerun()

def pagina_herramientas_digitales():
    st.markdown("### Uso de Herramientas Digitales")

    herramientas = st.multiselect(
        "**1. De las siguientes, ¿qué herramientas utilizas?**",
        ["Redes sociales", "Página web", "Almacenamiento en la nube",
         "Banca en línea (recibimos pagos)", "Banca en línea (no recibimos pagos)",
         "Correo personalizado", "Plataformas de llamadas virtuales",
         "Software de oficina", "Software especializado", "Otras", "Ninguna"]
    )

    if herramientas:
        st.markdown("**2. ¿Cuáles pagas?**")
        herramientas_pagadas = st.multiselect("Selecciona:", herramientas, key="herr_pag")
    else:
        herramientas_pagadas = []

    importancia_herramientas = st.selectbox(
        "**3. ¿Estas herramientas son importantes para tu trabajo?**",
        ["Totalmente fundamentales",
         "Fundamentales para algunas tareas",
         "Muy poco fundamentales",
         "Nada no las uso tanto"],
        key="importancia_herramientas"
    )

    ias = st.multiselect(
        "**4. De las siguientes, ¿qué inteligencias artificiales utilizas?**",
        ["Generador de texto (ChatGPT, Claude, etc.)",
         "Asistente de escritura", "Traductor", "Asistente de oficina",
         "Generador de imágenes", "Herramienta pedagógica",
         "Herramienta de código", "Otras", "Ninguna"],
        key="ias"
    )

    if ias and "Ninguna" not in ias:
        st.markdown("**5. ¿Cuáles pagas?**")
        ias_pagadas = st.multiselect("Selecciona:", [ia for ia in ias if ia != "Ninguna"], key="ias_pag")
    else:
        ias_pagadas = []

    importancia_ias = st.selectbox(
        "**6. ¿Estas herramientas son importantes para tu trabajo?**",
        ["Totalmente fundamentales",
         "Fundamentales para algunas tareas",
         "Me aportan muy poco no las uso tanto",
         "No sé utilizarlas muy bien quisiera manejarlas mejor"],
        key="importancia_ias"
    )

    comunidades = st.multiselect(
        "**7. ¿Perteneces a alguna comunidad en línea?**",
        ["Grupos de WhatsApp/Telegram", "Grupos de difusión",
         "Grupos de redes sociales", "Comunidades especializadas en línea",
         "Comunidades híbridas", "Otras", "Ninguna"],
        key="comunidades"
    )

    importancia_comunidades = st.selectbox(
        "**8. ¿Estas comunidades son importantes para tu trabajo?**",
        ["Totalmente fundamentales participo de forma activa",
         "Fundamentales en algunos casos",
         "Muy poco fundamentales no participo casi nunca",
         "No las uso solo estoy inscrito pero no participo"],
        key="importancia_comunidades"
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
                'importancia_herramientas': importancia_herramientas,
                'ias': ias,
                'ias_pagadas': ias_pagadas,
                'importancia_ias': importancia_ias,
                'comunidades': comunidades,
                'importancia_comunidades': importancia_comunidades,
                'num_herramientas': len([h for h in herramientas if h != "Ninguna"]),
                'num_herramientas_pagadas': len(herramientas_pagadas),
                'num_ias': len([ia for ia in ias if ia != "Ninguna"]),
                'num_ias_pagadas': len(ias_pagadas),
                'num_comunidades': len([c for c in comunidades if c != "Ninguna"])
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
    entrevista = st.radio("¿Te gustaría que te contactemos para entrevistas de esta investigación?", ["No", "Sí"])
    convocatorias = st.multiselect("¿Te interesa participar en?", ["Talleres de autogestión", "Ferias de arte"])
    mascaras = st.radio("""¿Te gustaría participar en la serie web "Máscaras Ciberpiratas"?, Si no la has visto, te invitamos a verla en el vínculo de abajo""", ["Si, ¿cuánto cuesta?", "No"])
    st.markdown("""
    <a href="https://www.youtube.com/watch?v=0x9rbnCRHR0&list=PLlmVVBH4XMZCIh1DXFh3XmYZqkLbiToyH" target="_blank" style="text-decoration: none;">
        <button style="width: 40%; background-color: #A870B0; color: #62CBE6; font-family: 'Roboto', sans-serif, margin-left;
                       font-weight: 700; border-radius: 10px; padding: 0.75rem; border: none; font-size: 1rem; cursor: pointer;">
            🤖¡Mira la serie web "Máscaras Ciberpiratas" acá!
        </button>
    </a>
    <br>
    """, unsafe_allow_html=True)    
    st.markdown(" ")
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
            if st.button("Finalizar ✅ \u2028 (si muestra error, vuelve a dar click acá, no te regreses)", use_container_width=True):
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
                        'mascaras': mascaras,
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

# ==================== MAPEO 2: STREAMING ====================

def mapeo_streaming():
    """Mapeo completo de pagos de plataformas de streaming a artistas"""

    # Inicializar estado
    if 'streaming_page' not in st.session_state:
        st.session_state.streaming_page = 0
    if 'streaming_data' not in st.session_state:
        st.session_state.streaming_data = []

    PLATAFORMAS = ['Spotify', 'Apple Music', 'YouTube', 'Tidal', 'Amazon Music', 'Otros']

    # ===== PÁGINA 0: INTRODUCCIÓN =====
    if st.session_state.streaming_page == 0:
        st.markdown("""
        <div class="question-box" style="margin-top: 1.5rem; border-left: 4px solid #A870B0;">
            <p style="line-height: 1.8;">
                En esta encuesta mostramos el porcentaje total de ingresos que obtienen los artistas
                por las plataformas más reconocidas y la comparamos con el porcentaje de reproducciones
                en cada una. De esa manera, buscamos identificar qué plataforma paga mejor.
            </p>
            <p style="line-height: 1.8; margin-top: 1rem; font-weight: 600;">
                En esta encuesta no te pediremos ningún dato personal y la información se manejará
                de manera totalmente anónima.
            </p>
        </div>
        """, unsafe_allow_html=True)

        # Checkbox de consentimiento
        acepta = st.checkbox(
            "Acepto participar en esta encuesta anónima y que mis datos sean utilizados para fines de investigación.",
            key="acepta_streaming"
        )

        if acepta:
            if st.button("INICIAR ENCUESTA ➡️", use_container_width=True, key="btn_iniciar_streaming"):
                st.session_state.streaming_page = 1
                st.rerun()
        else:
            st.button("INICIAR ENCUESTA ➡️", use_container_width=True, disabled=True, key="btn_iniciar_streaming_disabled")

        # Texto de tratamiento de datos debajo
        st.markdown("""
        <div class="question-box">
        <h4 style="font-family: 'Roboto', sans-serif; margin-bottom: 1rem;">Aviso de Tratamiento de Datos Personales</h4>
            <p style="line-height: 1.6; font-size: 0.95rem;">Esta encuesta es completamente anónima. No recopilamos
            datos personales identificables. La información agregada será utilizada únicamente para fines
            de investigación académica por El Chorro Producciones y Huika Mexihco. Los resultados se
            presentarán de forma agregada. Contacto: <a href="mailto:info@elchorro.com.co" style="color: #A870B0;">info@elchorro.com.co</a></p>
        </div>
        """, unsafe_allow_html=True)

    # ===== PÁGINA 1: ENCUESTA =====
    elif st.session_state.streaming_page == 1:
        st.markdown("### Encuesta de Ingresos por Streaming")

        # Pregunta 1: País
        paises = sorted([country.name for country in pycountry.countries])
        pais = st.selectbox("1. ¿En qué país resides?", ["Selecciona..."] + paises, key="streaming_pais")

        # Pregunta 2: Gestor de derechos
        gestor = st.radio(
            "2. ¿Eres el gestor de tus derechos de distribución?",
            ["Sí", "No"],
            key="streaming_gestor",
            horizontal=True
        )

        # Pregunta 3: Tipo de distribución
        tipo_dist = st.selectbox(
            "3. ¿Qué tipo de distribución tienes?",
            ["Selecciona...", "Disquera", "Disquera o distribuidora pequeña y regional",
             "Plataforma de gestión independiente", "Totalmente independiente"],
            key="streaming_tipo_dist"
        )

        # Pregunta 4: Ingresos y reproducciones por plataforma
        st.markdown("### 4. ¿Cuántos ingresos y reproducciones recibes en cada plataforma?")
        st.caption("Ingresa solo números sin puntos ni comas. Deja en 0 si no usas la plataforma.")

        datos_plataformas = {}
        for plataforma in PLATAFORMAS:
            with st.expander(f"📀 {plataforma}", expanded=True):
                col1, col2 = st.columns(2)
                with col1:
                    ingresos = st.number_input(
                        f"Ingresos ($USD)",
                        min_value=0,
                        value=0,
                        key=f"ing_{plataforma}"
                    )
                with col2:
                    reproducciones = st.number_input(
                        f"Reproducciones",
                        min_value=0,
                        value=0,
                        key=f"rep_{plataforma}"
                    )
                datos_plataformas[plataforma] = {'ingresos': ingresos, 'reproducciones': reproducciones}

        # Navegación
        col_prev, col_next = st.columns([1, 1])
        with col_prev:
            if st.button("⬅️ Regresar", use_container_width=True, key="streaming_back"):
                st.session_state.streaming_page = 0
                st.rerun()
        with col_next:
            campos_ok = pais != "Selecciona..." and tipo_dist != "Selecciona..."
            if campos_ok:
                if st.button("Enviar respuesta ✅ (si muestra error, solo vuelve a dar click acá, no te regreses)", use_container_width=True, key="streaming_submit"):
                    respuesta = {
                        'timestamp': datetime.now().isoformat(),
                        'pais': pais,
                        'gestor': gestor,
                        'tipo_distribucion': tipo_dist,
                        'plataformas': datos_plataformas
                    }
                    # Guardar en Google Sheets (Hoja2)
                    if guardar_respuesta_streaming(respuesta):
                        st.session_state.streaming_page = 2
                        st.rerun()
                    else:
                        st.error("Error al guardar la respuesta. Por favor intenta de nuevo.")
            else:
                st.button("Enviar respuesta ✅", use_container_width=True, disabled=True, key="streaming_submit_disabled")
                st.caption("Completa país y tipo de distribución para continuar.")

    # ===== PÁGINA 2: GRACIAS =====
    elif st.session_state.streaming_page == 2:
        st.markdown("""
        <div class="thanks-message">
            ¡Gracias por participar!<br>
            Tu respuesta nos ayuda a entender mejor el ecosistema del streaming musical.
        </div>
        """, unsafe_allow_html=True)

    # ===== PÁGINA 3: VISUALIZACIÓN =====
    elif st.session_state.streaming_page == 3:
        mostrar_visualizacion_streaming()

def mostrar_visualizacion_streaming():
    """Muestra la visualización del mapeo de streaming"""

    PLATAFORMAS = ['Spotify', 'Apple Music', 'YouTube', 'Tidal', 'Amazon Music', 'Otros']

    # Cargar datos desde Google Sheets (Hoja2)
    datos = cargar_respuestas_streaming()

    if not datos:
        st.info("📊 Aún no hay respuestas. ¡Sé el primero en participar!")
        return

    # Convertir a DataFrame para filtrado
    df = pd.DataFrame(datos)

    # ===== FILTROS =====
    st.markdown("### Filtros")
    col1, col2 = st.columns(2)

    with col1:
        paises_disponibles = ['Todos'] + sorted(df['pais'].unique().tolist())
        filtro_pais = st.selectbox("País:", paises_disponibles, key="filtro_streaming_pais")

    with col2:
        tipos_disponibles = ['Todos'] + sorted(df['tipo_distribucion'].unique().tolist())
        filtro_tipo = st.selectbox("Tipo de distribución:", tipos_disponibles, key="filtro_streaming_tipo")

    # Aplicar filtros
    df_filtrado = df.copy()
    if filtro_pais != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['pais'] == filtro_pais]
    if filtro_tipo != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['tipo_distribucion'] == filtro_tipo]

    st.info(f"📊 Mostrando {len(df_filtrado)} de {len(df)} respuestas")

    if len(df_filtrado) == 0:
        st.warning("No hay datos con los filtros seleccionados.")
        return

    # ===== CALCULAR TOTALES POR PLATAFORMA =====
    totales_ingresos = {p: 0 for p in PLATAFORMAS}
    totales_reproducciones = {p: 0 for p in PLATAFORMAS}

    for _, row in df_filtrado.iterrows():
        plataformas_data = row['plataformas']
        for plataforma in PLATAFORMAS:
            if plataforma in plataformas_data:
                totales_ingresos[plataforma] += plataformas_data[plataforma].get('ingresos', 0)
                totales_reproducciones[plataforma] += plataformas_data[plataforma].get('reproducciones', 0)

    # Calcular porcentajes
    total_ing = sum(totales_ingresos.values())
    total_rep = sum(totales_reproducciones.values())

    if total_ing == 0 and total_rep == 0:
        st.warning("No hay datos de ingresos o reproducciones para mostrar.")
        return

    pct_ingresos = {p: (v / total_ing * 100) if total_ing > 0 else 0 for p, v in totales_ingresos.items()}
    pct_reproducciones = {p: (v / total_rep * 100) if total_rep > 0 else 0 for p, v in totales_reproducciones.items()}

    # ===== GRÁFICO DE BARRAS =====
    st.markdown("### Comparativa: % Ingresos vs % Reproducciones por Plataforma")

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name='% Ingresos',
        x=PLATAFORMAS,
        y=[pct_ingresos[p] for p in PLATAFORMAS],
        marker_color='#5D80B5',
        text=[f"{pct_ingresos[p]:.1f}%" for p in PLATAFORMAS],
        textposition='outside'
    ))

    fig.add_trace(go.Bar(
        name='% Reproducciones',
        x=PLATAFORMAS,
        y=[pct_reproducciones[p] for p in PLATAFORMAS],
        marker_color='#A870B0',
        text=[f"{pct_reproducciones[p]:.1f}%" for p in PLATAFORMAS],
        textposition='outside'
    ))

    fig.update_layout(
        barmode='group',
        xaxis_title="Plataforma",
        yaxis_title="Porcentaje (%)",
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        plot_bgcolor='white',
        yaxis=dict(gridcolor='#f0f0f0', range=[0, max(max(pct_ingresos.values()), max(pct_reproducciones.values())) * 1.2])
    )

    st.plotly_chart(fig, use_container_width=True)

    # ===== TABLA RESUMEN =====
    st.markdown("### Resumen por Plataforma")

    resumen_data = []
    for p in PLATAFORMAS:
        # Ratio = promedio de pago por stream (ingresos / reproducciones)
        pago_por_stream = (totales_ingresos[p] / totales_reproducciones[p]) if totales_reproducciones[p] > 0 else 0
        resumen_data.append({
            'Plataforma': p,
            'Total Ingresos ($)': f"${totales_ingresos[p]:,.0f}",
            'Total Streams': f"{totales_reproducciones[p]:,.0f}",
            '% Ingresos': f"{pct_ingresos[p]:.1f}%",
            '% Streams': f"{pct_reproducciones[p]:.1f}%",
            'Pago/Stream': f"${pago_por_stream:.2f}"
        })

    df_resumen = pd.DataFrame(resumen_data)
    st.dataframe(df_resumen, use_container_width=True, hide_index=True)

    st.caption("**Pago/Stream:** Promedio de dólares pagados por cada reproducción en la plataforma.")

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
        background-color: #000000; color: white; padding: 0.3rem 0.2rem;
        border-radius: 10px; font-family: 'Roboto', sans-serif; font-weight: 700;
        font-size: 2.5rem; text-align: center; margin-bottom: 0.1rem;
        display: flex; align-items: center; justify-content: center; gap: 0.1rem;
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
        st.session_state.encuesta_page = 0
        st.rerun()

    if st.button("🎵 Pagos de Streaming a Artistas", use_container_width=True, key="btn_mapeo2"):
        st.session_state.seccion = 'mapeo2'
        st.session_state.streaming_page = 0
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

# ==================== PÁGINA INTRO ====================
if st.session_state.seccion == 'intro':
    st.markdown('<p style="font-family: \'Roboto Slab\', serif; font-size: 1.2rem; text-align: center; color: #000000;"><strong>Tejidos en Red: Análisis y Mapeos Sociales</strong>', unsafe_allow_html=True)

    st.markdown("""
    <div class="question-box">
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

# ==================== MAPEO STREAMING ====================
elif st.session_state.seccion == 'mapeo2':
    st.markdown('<div class="mapeo-title">¿Cuánto le pagan las plataformas de streaming a los artistas?</div>', unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["📝 Participar en Encuesta", "📊 Ver Resultados"])

    with tab1:
        mapeo_streaming()

    with tab2:
        mostrar_visualizacion_streaming()
