# Epical Intelligence System — Agente Conversacional
## Spec técnico para el sistema que genera reportes de inteligencia reputacional

---

## QUÉ ES

Un agente de IA que recibe un brief + archivos, procesa todo autónomamente, genera un reporte de inteligencia reputacional completo, y consulta al analista humano en 3 checkpoints clave. El analista dirige, no ejecuta.

El agente NO es un chatbot genérico. Tiene herramientas específicas (pipeline de datos vía SentimIA API, generador de HTML, calculadora de métricas, Playwright para PDF) y reglas editoriales codificadas que son IP de Epical.

---

## ARQUITECTURA

```
Analista de Epical
       │
       │  brief + archivos + feedback en checkpoints
       ▼
┌──────────────────────────────────────────────────┐
│          AGENTE CONVERSACIONAL                    │
│          (Claude Sonnet 4.6 / Opus 4.6)          │
│                                                   │
│  System prompt: reglas de Epical                  │
│  Tools:                                           │
│    1. SentimIA API (procesar datos)               │
│    2. Python executor (cálculos, co-ocurrencias)  │
│    3. HTML builder (generar reporte)              │
│    4. Playwright (screenshots, PDF)               │
│    5. File reader (leer uploads del analista)     │
│                                                   │
│  Flujo autónomo con 3 checkpoints humanos         │
└──────────────────────────────────────────────────┘
       │
       │  API calls
       ▼
┌──────────────────────┐
│  SentimIA Backend    │
│  (Capa 0 + 1 + 2)   │
└──────────────────────┘
```

---

## FLUJO DEL AGENTE

### INPUT
El analista envía:
```
"Acá tenés el export de YouScan de Avianca y el scrapping de sus perfiles 
y los de Cossio. Período marzo-abril 2026. Es para el Director de 
Comunicaciones Corporativas de Avianca. Queremos prospectarlo como cliente."
```
+ adjunta los archivos CSV/Excel

### FASE 1: PROCESAMIENTO AUTÓNOMO (sin intervención humana, ~30-45 min)

El agente ejecuta en secuencia:

**1.1 Análisis de inputs**
- Lee los archivos subidos
- Detecta formato (YouScan export, scrapping manual, CSV genérico)
- Cuenta filas, detecta columnas, identifica plataformas

**1.2 Envío a SentimIA**
- Crea proyecto en SentimIA API con el contexto del brief
- Sube los archivos
- Lanza procesamiento (Capa 0 + 1 + 2)
- Hace polling hasta que termine

**1.3 Recibe datos procesados**
- Obtiene resultados agregados de SentimIA API
- Obtiene menciones individuales con clasificación

**1.4 Auditoría automática**
- Toma muestra de 200 menciones (50 por categoría: relevant negativo, relevant positivo, irrelevant, tangential)
- Verifica que las clasificaciones tienen sentido
- Calcula % de confianza high/medium/low
- Si accuracy estimada < 75%, flaggea al analista

**1.5 Cálculos propios (Python, sin IA)**
- Co-ocurrencia de conceptos para grafos de narrativas
- Métricas de engagement por plataforma (total, promedio, share)
- Visualizaciones y alcance potencial deduplicado por cuenta
- Timeline diario con detección de spikes
- Categorización de críticas hacia la marca (si aplica)
- Análisis de impacto temporal (pre/post comunicado si hay evento identificable)
- Detección de efecto catalizador (tangenciales negativas)
- Detección de contagio sectorial (competidores mencionados)

**1.6 Síntesis narrativa (Capa 3)**
- Una llamada a Sonnet 4.6 con todos los datos agregados
- Genera: tesis principal, 3 hallazgos, narrativas en juego, escenarios, lecturas estratégicas

**1.7 Generación de HTML borrador**
- Usa el template editorial de Epical (basado en el v10 de Avianca)
- Llena con datos reales, charts, grafos SVG computados, menciones mock con engagement real
- Aplica reglas de diseño (light mode, Playfair + DM Sans, cards con sombra, charts con height wrapper)

### ⏸️ CHECKPOINT 1: PRESENTACIÓN AL ANALISTA

El agente presenta:
```
"Procesé [X] menciones → [Y] relevantes.

TESIS PRINCIPAL: [la tesis que generó la Capa 3]

HALLAZGOS:
1. [hallazgo 1 con dato]
2. [hallazgo 2 con dato]  
3. [hallazgo 3 con dato]

AUDITORÍA: revisé 200 menciones, accuracy estimada [Z]%.
[Si hay problemas, los reporta aquí]

HTML borrador adjunto. ¿Estás de acuerdo con el enfoque o 
querés cambiar algo?"
```

**Posibles respuestas del analista:**
- "Ok, seguí" → pasa a Fase 2
- "La tesis está mal, el enfoque debería ser X" → agente reescribe
- "Agregá análisis de Y" → agente calcula y agrega
- "Los números de Z no me cierran, revisá" → agente reaudita
- "El diseño es muy X, hacelo más Y" → agente ajusta

### FASE 2: REFINAMIENTO (con el feedback del checkpoint 1)

El agente:
- Incorpora todos los ajustes pedidos
- Regenera las secciones afectadas del HTML
- Recalcula si el feedback cambió algún dato
- Regenera HTML v2

### ⏸️ CHECKPOINT 2: REPORTE REFINADO

```
"HTML v2 listo con los ajustes. 

Cambios:
- [lista de cambios]

¿Querés agregar screenshots de posts, ajustar algo más, 
o está listo para PDF?"
```

**Posibles respuestas:**
- "Acá van screenshots de estos posts" + adjunta imágenes → agente los integra
- "Ajustá X y Y" → agente corrige
- "Listo, generá el PDF" → pasa a Fase 3

### FASE 3: ENTREGA

El agente:
- Integra screenshots si los hay
- Verificación final de cifras (suma de tablas, porcentajes, consistencia)
- Verificación de reglas (no menciona herramientas internas, etc.)
- Genera PDF con Playwright
- Presenta ambos archivos (HTML + PDF)

### ⏸️ CHECKPOINT 3: ENTREGA FINAL

```
"HTML y PDF listos. 

Verificación final:
✅ Cifras consistentes
✅ Sin menciones de herramientas internas
✅ Charts renderizados
✅ [N] slides, [M] charts, [K] menciones con engagement

Archivos adjuntos."
```

---

## REGLAS DEL AGENTE (SYSTEM PROMPT)

Estas son las reglas que el agente sigue SIEMPRE sin preguntarle al analista. Son IP de Epical, construidas caso a caso.

### Reglas de auditoría de datos
1. NUNCA confiar en los datos crudos del pipeline sin auditar. Siempre verificar una muestra.
2. SIEMPRE separar dirección de sentimiento en crisis multi-actor. "Negativo + marca mencionada" NO es lo mismo que "negativo HACIA la marca".
3. SIEMPRE deduplicar alcance potencial por cuenta única. No inflar números.
4. SIEMPRE verificar que engagement y menciones sumen correctamente en las tablas.
5. SIEMPRE chequear que las menciones de otras marcas/aerolíneas/competidores no estén contaminando los datos.
6. Si la accuracy de la muestra auditada es < 75%, detener y reportar al analista.
7. Los porcentajes se redondean a 1 decimal. Las cifras grandes se redondean (692K, 29M, 233M).

### Reglas editoriales
8. Las recomendaciones son "lecturas estratégicas" con tag "Señal →". NUNCA instrucciones operativas. No le decimos al cliente qué hacer — le damos las señales para que decida.
9. NUNCA mencionar YouScan, SentimIA, Claude, Haiku, Brandwatch, ni ninguna herramienta por nombre. Usar "Epical Perception Engine" para el motor emocional y "modelos propietarios de clasificación" para la IA.
10. Los grafos de narrativas son COMPUTADOS con co-ocurrencia real, no editoriales/conceptuales.
11. Las menciones mock en el reporte usan datos REALES del dataset (usernames, engagement, fechas, plataformas).
12. Email de contacto: hi@epical.digital

### Reglas de diseño
13. Diseño profesional-moderno. No austero corporativo (McKinsey), no agencia creativa (dark mode agresivo). Balance: cover y transiciones en navy oscuro, contenido en fondo claro.
14. Tipografía: Playfair Display (títulos) + DM Sans (cuerpo) + JetBrains Mono (datos). Google Fonts via <link> tag, no @import.
15. Charts de Chart.js SIEMPRE dentro de un div con position:relative y height explícita. Sin esto los charts colapsan.
16. KPIs grandes usan DM Sans bold, no JetBrains Mono (demasiado duro para cifras).
17. Callout boxes: azul claro para insights, naranja para "so what"/lecturas, rojo para riesgos.
18. Logos de plataformas como SVG inline en la slide de plataformas.
19. Charts con Chart.js 4.4.1 via CDN de Cloudflare.

### Reglas de narrativa
20. La tesis del reporte NO es obvia. Si los datos dicen "70% negativo", el análisis pregunta "negativo hacia quién". Si la respuesta obvia es "la marca está en crisis", verificar si es realmente así.
21. SIEMPRE buscar el efecto catalizador: ¿el incidente amplificó insatisfacción preexistente?
22. SIEMPRE analizar impacto temporal: ¿hubo un comunicado/evento? ¿Qué pasó antes y después?
23. SIEMPRE verificar contagio sectorial: ¿los competidores se vieron afectados?
24. SIEMPRE identificar la narrativa minoritaria de riesgo — la que hoy es chica pero puede crecer.
25. El cierre del reporte SIEMPRE compara "lo que muestra un monitoreo estándar" vs "lo que revela el análisis profundo". Esto es el pitch implícito de Epical.

---

## TEMPLATE HTML

El template base es el avianca_crisis_report_v10_FINAL.html. El agente lo usa como referencia estructural pero adapta el contenido al caso.

### Estructura estándar de slides:
1. Cover (navy, logos marca + Epical, título provocativo)
2. Resumen ejecutivo (3 hallazgos)
3. Dimensión del impacto (KPIs: menciones, engagement, views, reach)
4. Nota metodológica (funnel de datos, transparencia)
5. Los datos (KPIs de sentimiento + charts)
6. Transición (los actores)
7-9. Un slide por actor con sentimiento, quotes mock, lectura estratégica
10. Efecto catalizador (si aplica — tangenciales negativas)
11. Plataformas con logos y engagement share
12. Timeline con spikes
13. Impacto del comunicado (si aplica)
14. Transición (narrativas)
15-17. Un slide por narrativa con grafo de co-ocurrencia computado
18. Escenarios a 30 días
19. Lecturas estratégicas (señales)
20. Aplicaciones para el área del cliente
21. Cierre (monitoreo estándar vs análisis profundo)
22. Slide de agradecimiento con contacto

### Slides opcionales (el agente decide si incluirlas según el caso):
- Efecto catalizador (solo si hay tangenciales significativas)
- Impacto del comunicado (solo si hay un evento temporal claro)
- Contagio sectorial (solo si se detectaron competidores)

---

## HERRAMIENTAS DEL AGENTE

### 1. SentimIA API
```python
class SentimiaClient:
    def create_project(self, name, brand, context, actors) -> project_id
    def upload_file(self, project_id, file, source_type) -> upload_id
    def process(self, project_id, options) -> job_id
    def get_status(self, project_id) -> status
    def get_results(self, project_id) -> aggregated_data
    def get_mentions(self, project_id, filters) -> mentions_list
    def export_csv(self, project_id) -> csv_file
```

### 2. Calculadora de métricas
```python
class MetricsCalculator:
    def compute_cooccurrence(self, mentions, concepts) -> graph_data
    def compute_engagement_by_platform(self, mentions) -> platform_stats
    def compute_timeline(self, mentions) -> daily_data
    def compute_comunicado_impact(self, mentions, event_date) -> impact_data
    def compute_tangential_analysis(self, tangential_mentions) -> catalyst_data
    def compute_reach_deduplicated(self, mentions) -> reach_data
    def detect_spikes(self, daily_data) -> spikes
    def categorize_brand_criticism(self, negative_toward_brand) -> categories
```

### 3. HTML Builder
```python
class ReportBuilder:
    def generate(self, template, data, config) -> html_string
    def add_slide(self, html, slide_type, content) -> html_string
    def add_chart(self, html, chart_type, data) -> html_string
    def add_social_post_mock(self, html, mention) -> html_string
    def add_narrative_graph(self, html, cooccurrence_data) -> html_string
    def integrate_screenshot(self, html, image_path, slide_id) -> html_string
```

### 4. PDF Generator
```python
class PDFGenerator:
    def generate(self, html_path) -> pdf_path
    # Usa Playwright con Chromium
    # Inyecta CSS: print-color-adjust:exact, scroll-snap:none, 
    # .fu → .vis, page-break-after:always
    # Formato A4 landscape, margin 0
```

---

## MODELO DE IA PARA EL AGENTE

**Claude Sonnet 4.6** ($3/$15 per M tokens) como cerebro del agente.
- Suficiente inteligencia para síntesis narrativa, detección de hallazgos no obvios, y generación de HTML
- El contexto largo (1M tokens) permite meter todo el dataset agregado + el template + las reglas en una sola conversación
- Opus 4.6 solo si se necesita razonamiento más profundo en casos complejos

**Costo estimado por reporte:**
- SentimIA procesamiento (Haiku): ~$3-5
- Agente conversacional (Sonnet, ~3 turnos largos): ~$1-2
- Total: ~$5-7 en API por reporte completo

---

## PLAN DE IMPLEMENTACIÓN

### Fase 1: SentimIA API (2 semanas)
- Implementar los 7 endpoints del spec sentimia_api_spec.md
- Testear con el dataset de Avianca como caso de prueba
- Deploy en Render

### Fase 2: Calculadora de métricas (1 semana)
- Extraer los cálculos Python que hicimos en la sesión de Avianca
- Empaquetar en una clase MetricsCalculator
- Testear con datos de Avianca

### Fase 3: HTML Builder (2 semanas)
- Parametrizar el template v10 de Avianca
- Implementar generación dinámica de slides, charts, grafos SVG
- Testear generando el reporte de Avianca desde cero

### Fase 4: Agente conversacional (2-3 semanas)
- Implementar el flujo de 3 checkpoints
- Conectar con SentimIA API + MetricsCalculator + HTML Builder
- System prompt con las 25 reglas de Epical
- Testear reproduciendo la sesión de Avianca

### Fase 5: PDF Generator (3 días)
- Playwright con las inyecciones CSS que descubrimos
- Testear con el HTML generado

### Test final: reproducir el caso Avianca
- Subir los mismos archivos
- Darle el mismo brief
- Verificar que el output sea comparable al v10 que hicimos manualmente
- Medir: tiempo total, calidad del borrador, número de intervenciones humanas necesarias

---

## CRITERIO DE ÉXITO

El sistema es exitoso cuando:
1. Un analista de Epical puede producir un reporte de calidad comparable al de Avianca en UNA TARDE (4-5 horas) en vez de 1-2 semanas
2. El 80% del contenido del reporte es generado por el agente y solo requiere edición/dirección del analista
3. Los checkpoints humanos son de DIRECCIÓN ESTRATÉGICA, no de ejecución (el analista no escribe texto ni corrige código)
4. El costo en API por reporte es < $10
5. Un analista puede manejar 5+ clientes simultáneamente
