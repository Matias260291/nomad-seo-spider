"""
SEO Spider — Web App
Stack: Streamlit + aiohttp + BeautifulSoup
Deploy: Streamlit Cloud (gratis)
"""

import asyncio
import aiohttp
import re
import time
import io
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse

import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup

# ── Patch para asyncio en entornos con loop ya corriendo ────────────────────
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass


# ════════════════════════════════════════════════════════════════════════════
#  UTILIDADES
# ════════════════════════════════════════════════════════════════════════════

def normalize_url(url):
    p = urlparse(url)
    path = p.path.rstrip("/") if p.path != "/" else p.path
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", p.query, ""))

def is_same_domain(url, domain):
    host = urlparse(url).netloc.lower()
    return host == domain or host.endswith("." + domain)

def should_exclude(url, patterns):
    for pattern in patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False

def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()


EXCLUDE_PATTERNS = [
    r"\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|mp4|mp3|css|js)(\?.*)?$",
    r"/(tag|autor|author|feed|wp-json|wp-admin|xmlrpc)/",
]


# ════════════════════════════════════════════════════════════════════════════
#  EXTRACCIÓN SEO
# ════════════════════════════════════════════════════════════════════════════

def extract_seo(url, fetch, domain):
    base = {
        "url": url,
        "final_url": fetch.get("final_url", url),
        "status_code": fetch.get("status_code"),
        "response_time_s": fetch.get("response_time"),
        "content_type": fetch.get("content_type", ""),
        "is_redirect": url != fetch.get("final_url", url),
        "redirect_chain": " → ".join(fetch.get("redirect_chain", [])),
        "error": fetch.get("error", ""),
    }

    html = fetch.get("html", "")
    if not html:
        return {**base, "internal_links_raw": []}

    soup = BeautifulSoup(html, "lxml")

    title_tag   = soup.find("title")
    title       = clean_text(title_tag.get_text()) if title_tag else ""

    meta_desc   = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    description = clean_text(meta_desc["content"]) if meta_desc and meta_desc.get("content") else ""

    h1s = [clean_text(h.get_text()) for h in soup.find_all("h1")]
    h2s = [clean_text(h.get_text()) for h in soup.find_all("h2")]
    h3s = [clean_text(h.get_text()) for h in soup.find_all("h3")]

    robots_tag  = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    robots_meta = clean_text(robots_tag["content"]) if robots_tag and robots_tag.get("content") else ""
    is_noindex  = "noindex" in robots_meta.lower()

    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    canonical     = canonical_tag.get("href", "").strip() if canonical_tag else ""
    is_self_canon = canonical == "" or normalize_url(canonical) == normalize_url(url)

    hreflang_tags = soup.find_all("link", attrs={"rel": "alternate", "hreflang": True})
    hreflang      = ", ".join(t.get("hreflang", "") for t in hreflang_tags)

    og_title  = (soup.find("meta", property="og:title")       or {}).get("content", "")
    og_desc   = (soup.find("meta", property="og:description") or {}).get("content", "")
    og_image  = (soup.find("meta", property="og:image")       or {}).get("content", "")
    og_type   = (soup.find("meta", property="og:type")        or {}).get("content", "")

    json_ld_tags = soup.find_all("script", attrs={"type": "application/ld+json"})
    schema_types = []
    for tag in json_ld_tags:
        m = re.findall(r'"@type"\s*:\s*"([^"]+)"', tag.get_text())
        schema_types.extend(m)
    schema_types_str = ", ".join(sorted(set(schema_types)))

    body       = soup.find("body")
    word_count = len(body.get_text(" ", strip=True).split()) if body else 0

    internal_links, external_links, nofollow_links = [], [], []
    for a in soup.find_all("a", href=True):
        href    = a["href"].strip()
        rel     = a.get("rel") or []
        rel_str = " ".join(rel).lower() if isinstance(rel, list) else str(rel).lower()
        abs_url = urljoin(url, href)
        norm    = normalize_url(abs_url)
        parsed  = urlparse(norm)
        if parsed.scheme not in ("http", "https"):
            continue
        if is_same_domain(norm, domain):
            internal_links.append(norm)
            if "nofollow" in rel_str:
                nofollow_links.append(norm)
        else:
            external_links.append(norm)

    images     = soup.find_all("img")
    imgs_no_alt = sum(1 for img in images if not img.get("alt", "").strip())

    next_link = soup.find("link", attrs={"rel": "next"})
    prev_link = soup.find("link", attrs={"rel": "prev"})

    return {
        **base,
        "title": title, "title_length": len(title),
        "title_issues": _issues_title(title),
        "meta_description": description, "meta_desc_length": len(description),
        "meta_desc_issues": _issues_meta(description),
        "h1": " | ".join(h1s), "h1_count": len(h1s),
        "h2_count": len(h2s), "h2_sample": " | ".join(h2s[:4]),
        "h3_count": len(h3s),
        "robots_meta": robots_meta, "is_noindex": is_noindex,
        "canonical": canonical, "is_self_canonical": is_self_canon,
        "hreflang": hreflang, "hreflang_count": len(hreflang_tags),
        "og_title": og_title, "og_description": og_desc,
        "og_image": og_image, "og_type": og_type,
        "schema_types": schema_types_str,
        "word_count": word_count,
        "internal_links_count": len(set(internal_links)),
        "external_links_count": len(set(external_links)),
        "nofollow_links_count": len(set(nofollow_links)),
        "images_total": len(images), "images_no_alt": imgs_no_alt,
        "rel_next": next_link.get("href", "") if next_link else "",
        "rel_prev": prev_link.get("href", "") if prev_link else "",
        "internal_links_raw": list(set(internal_links)),
    }


def _issues_title(t):
    if not t: return "AUSENTE"
    if len(t) < 30: return "MUY_CORTO"
    if len(t) > 60: return "MUY_LARGO"
    return ""

def _issues_meta(d):
    if not d: return "AUSENTE"
    if len(d) < 70: return "MUY_CORTA"
    if len(d) > 160: return "MUY_LARGA"
    return ""


# ════════════════════════════════════════════════════════════════════════════
#  FETCH ASYNC
# ════════════════════════════════════════════════════════════════════════════

async def fetch_url(session, url, timeout):
    redirect_chain = []
    try:
        t0 = time.perf_counter()
        async with session.get(
            url, allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=timeout), max_redirects=10,
        ) as resp:
            elapsed = round(time.perf_counter() - t0, 3)
            for hist in resp.history:
                redirect_chain.append(str(hist.url))
            redirect_chain.append(str(resp.url))
            ct = resp.headers.get("content-type", "")
            if "html" not in ct:
                return {"url": url, "final_url": str(resp.url),
                        "status_code": resp.status, "response_time": elapsed,
                        "content_type": ct, "html": "", "redirect_chain": redirect_chain}
            html = await resp.text(errors="replace")
            return {"url": url, "final_url": str(resp.url),
                    "status_code": resp.status, "response_time": elapsed,
                    "content_type": ct, "html": html, "redirect_chain": redirect_chain}
    except asyncio.TimeoutError:
        return {"url": url, "error": "TIMEOUT", "status_code": None}
    except Exception as e:
        return {"url": url, "error": str(e)[:120], "status_code": None}


# ════════════════════════════════════════════════════════════════════════════
#  SPIDER
# ════════════════════════════════════════════════════════════════════════════

async def run_spider(start_url, max_pages, max_depth, concurrency,
                     respect_noindex, progress_bar, status_text):
    domain  = urlparse(start_url).netloc.lower().lstrip("www.")
    visited = set()
    queue   = deque()
    results = []

    start_norm = normalize_url(start_url)
    queue.append((start_norm, 0))
    visited.add(start_norm)

    connector = aiohttp.TCPConnector(limit=concurrency, ssl=False)
    headers   = {"User-Agent": "Mozilla/5.0 (compatible; NomadSEOSpider/1.0)"}

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        while queue and len(results) < max_pages:
            batch = []
            while queue and len(batch) < concurrency:
                batch.append(queue.popleft())

            tasks   = [fetch_url(session, url, 20) for url, _ in batch]
            fetched = await asyncio.gather(*tasks)

            for (url, depth), fetch_result in zip(batch, fetched):
                seo_data = extract_seo(url, fetch_result, domain)
                results.append(seo_data)

                pct = min(len(results) / max_pages, 1.0)
                progress_bar.progress(pct)
                status_text.text(
                    f"🕷 {len(results)}/{max_pages} — "
                    f"[{seo_data.get('status_code','?')}] {url[-70:]}"
                )

                if respect_noindex and seo_data.get("is_noindex"):
                    continue

                if depth < max_depth:
                    for link in seo_data.get("internal_links_raw", []):
                        norm = normalize_url(link)
                        if (norm not in visited
                                and not should_exclude(norm, EXCLUDE_PATTERNS)
                                and len(visited) < max_pages * 3):
                            visited.add(norm)
                            queue.append((norm, depth + 1))

            await asyncio.sleep(0.05)

    return results


# ════════════════════════════════════════════════════════════════════════════
#  RESUMEN ISSUES
# ════════════════════════════════════════════════════════════════════════════

def build_issues_summary(df):
    checks = {
        "Sin título":             df["title"].str.strip().eq(""),
        "Título muy largo (>60)": df["title_length"].gt(60),
        "Título muy corto (<30)": df["title_length"].gt(0) & df["title_length"].lt(30),
        "Sin meta description":   df["meta_description"].str.strip().eq(""),
        "Meta desc muy larga":    df["meta_desc_length"].gt(160),
        "Sin H1":                 df["h1_count"].eq(0),
        "Múltiples H1":           df["h1_count"].gt(1),
        "Noindex":                df["is_noindex"].eq(True),
        "Sin canonical":          df["canonical"].str.strip().eq(""),
        "Canonical no self":      df["is_self_canonical"].eq(False),
        "Imágenes sin alt":       df["images_no_alt"].gt(0),
        "4xx":                    df["status_code"].between(400, 499),
        "5xx":                    df["status_code"].between(500, 599),
        "Redirect (3xx)":         df["status_code"].between(300, 399),
        "Sin schema markup":      df["schema_types"].str.strip().eq(""),
        "Word count bajo (<300)": df["word_count"].gt(0) & df["word_count"].lt(300),
    }
    rows = [
        {"Issue": k, "URLs afectadas": int(v.sum()),
         "% del total": f"{v.mean()*100:.1f}%"}
        for k, v in checks.items() if v.sum() > 0
    ]
    return pd.DataFrame(rows).sort_values("URLs afectadas", ascending=False)


def to_excel_bytes(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        clean = df.drop(columns=["internal_links_raw"], errors="ignore")
        clean.to_excel(writer, index=False, sheet_name="Crawl")
        build_issues_summary(clean).to_excel(writer, index=False, sheet_name="Issues")
        df[df["is_redirect"] == True][
            ["url","final_url","status_code","redirect_chain"]
        ].to_excel(writer, index=False, sheet_name="Redirects")
        err = df[df["error"].astype(str).str.len() > 0][["url","status_code","error"]]
        err.to_excel(writer, index=False, sheet_name="Errors")
    return output.getvalue()


# ════════════════════════════════════════════════════════════════════════════
#  UI STREAMLIT
# ════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Nomad SEO Spider",
    page_icon="🕷",
    layout="wide",
)

st.title("🕷 Nomad SEO Spider")
st.caption("Herramienta interna Nomadic · alternativa a Screaming Frog")

# ── Sidebar: configuración ───────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuración")

    start_url = st.text_input(
        "URL de inicio", placeholder="https://cliente.com"
    )
    max_pages = st.slider("Máx. URLs a rastrear", 50, 2000, 500, step=50)
    max_depth = st.slider("Profundidad máxima", 1, 10, 5)
    concurrency = st.slider("Concurrencia (requests simultáneos)", 3, 30, 10)
    respect_noindex = st.checkbox("Respetar noindex (no seguir)", value=True)

    st.markdown("---")
    st.markdown("**Cómo usar:**")
    st.markdown("1. Ingresá la URL del sitio\n2. Ajustá los parámetros\n3. Presioná **Iniciar crawl**\n4. Descargá el Excel al finalizar")

# ── Main area ────────────────────────────────────────────────────────────────
run = st.button("🚀 Iniciar crawl", type="primary", disabled=not start_url)

if run and start_url:
    if not start_url.startswith("http"):
        st.error("La URL debe empezar con http:// o https://")
    else:
        progress_bar = st.progress(0.0)
        status_text  = st.empty()
        st.info(f"Rastreando **{start_url}** · máx. {max_pages} URLs · profundidad {max_depth}")

        with st.spinner("Crawl en progreso..."):
            results = asyncio.run(run_spider(
                start_url, max_pages, max_depth, concurrency,
                respect_noindex, progress_bar, status_text
            ))

        progress_bar.progress(1.0)
        status_text.text(f"✅ Crawl completo — {len(results)} URLs procesadas")

        df = pd.DataFrame(results)

        # ── Métricas rápidas ──────────────────────────────────────────────
        st.markdown("---")
        st.subheader("📊 Resumen")

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("URLs rastreadas",   len(df))
        col2.metric("2xx OK",            int(df["status_code"].between(200,299).sum()))
        col3.metric("3xx Redirects",     int(df["status_code"].between(300,399).sum()))
        col4.metric("4xx Errors",        int(df["status_code"].between(400,499).sum()))
        col5.metric("Sin título",        int(df["title"].str.strip().eq("").sum()))

        # ── Issues ───────────────────────────────────────────────────────
        st.subheader("⚠️ Issues detectados")
        clean = df.drop(columns=["internal_links_raw"], errors="ignore")
        issues_df = build_issues_summary(clean)
        if issues_df.empty:
            st.success("No se detectaron issues relevantes 🎉")
        else:
            st.dataframe(issues_df, use_container_width=True, hide_index=True)

        # ── Preview data ─────────────────────────────────────────────────
        st.subheader("🔍 Vista previa de datos")
        preview_cols = ["url", "status_code", "title", "title_length",
                        "meta_desc_length", "h1_count", "word_count",
                        "is_noindex", "canonical", "schema_types"]
        st.dataframe(
            clean[preview_cols].head(100),
            use_container_width=True, hide_index=True
        )

        # ── Descarga ─────────────────────────────────────────────────────
        st.markdown("---")
        domain_slug = urlparse(start_url).netloc.replace("www.", "").replace(".", "_")
        filename    = f"seo_crawl_{domain_slug}.xlsx"

        st.download_button(
            label="📥 Descargar Excel completo",
            data=to_excel_bytes(clean),
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

elif not run:
    st.markdown("""
    ### Qué analiza esta herramienta

    | Categoría | Datos extraídos |
    |---|---|
    | HTTP | Status code, tiempo de respuesta, cadena de redirecciones |
    | On-page | Título, meta description, H1/H2/H3 |
    | Indexación | Robots meta, noindex, canonical, hreflang |
    | Social | Open Graph (título, descripción, imagen, tipo) |
    | Schema | Tipos de structured data detectados |
    | Contenido | Word count |
    | Links | Internos, externos, nofollow |
    | Imágenes | Total, sin atributo alt |
    | Paginación | rel=next / rel=prev |
    """)
