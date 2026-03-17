# 🕷 Nomad SEO Spider

Herramienta interna Nomadic — alternativa ligera a Screaming Frog.

## Deploy en Streamlit Cloud (gratis, 5 minutos)

### 1. Subir a GitHub
1. Crear un repo en GitHub (puede ser privado)
2. Subir los dos archivos: `app.py` y `requirements.txt`

### 2. Deploy en Streamlit Cloud
1. Ir a [share.streamlit.io](https://share.streamlit.io)
2. Conectar con tu cuenta de GitHub
3. Elegir el repo y el branch
4. En **Main file path** poner: `app.py`
5. Click en **Deploy** — listo en ~2 minutos

### 3. Compartir con el equipo
- Streamlit Cloud genera una URL pública o privada
- Con cuenta gratuita: hasta 3 apps, acceso público
- Con cuenta Teams (gratis para equipos pequeños): acceso restringido por email

---

## Uso

1. Ingresar la URL del sitio a auditar
2. Configurar parámetros en el sidebar:
   - **Máx. URLs**: cuántas páginas rastrear (500 recomendado para auditorías rápidas)
   - **Profundidad**: cuántos niveles de links seguir
   - **Concurrencia**: requests simultáneos (bajar a 5-8 si el sitio es lento)
3. Click en **Iniciar crawl**
4. Descargar el Excel con 4 hojas:
   - **Crawl**: todos los datos por URL
   - **Issues**: resumen de problemas detectados
   - **Redirects**: URLs con redirección
   - **Errors**: URLs con errores

---

## Qué analiza

- Status HTTP, tiempos de respuesta, cadenas de redirección
- Título (texto, longitud, issues)
- Meta description (texto, longitud, issues)
- Headings H1 / H2 / H3
- Robots meta, noindex
- Canonical (URL + si es self-canonical)
- Hreflang
- Open Graph completo
- Structured data / Schema.org types
- Word count
- Links internos, externos, nofollow
- Imágenes sin alt
- rel=next / rel=prev

---

## Próximas funciones planeadas
- [ ] Sitemap.xml como fuente de URLs
- [ ] Core Web Vitals via PageSpeed API
- [ ] Integración Google Drive (exportar directo)
- [ ] Detección de LBP (Live Blog Posts)
