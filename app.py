"""
SEO Spider — Web App
Stack: Streamlit + requests + BeautifulSoup + ThreadPoolExecutor
Deploy: Streamlit Cloud (gratis)
"""

import re
import time
import io
import queue
import threading
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup


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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}


# ════════════════════════════════════════════════════════════════════════════
#  FETCH (sincrono, con requests)
# ════════════════════════════════════════════════════════════════════════════

def fetch_url(url, timeout=20):
    redirect_chain = []
    try:
        t0 = time.perf_counter()
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        elapsed = round(time.perf_counter() - t0, 3)
        for r in resp.history:
            redirect_chain.append(str(r.url))
        redirect_chain.append(str(resp.url))
        ct = resp.headers.get("content-type", "")
        if "html" not in ct:
            return {"url": url, "final_url": str(resp.url),
                    "status_code": resp.status_code, "response_time": elapsed,
                    "content_type": ct, "html": "", "redirect_chain": redirect_chain}
        return {"url": url, "final_url": str(resp.url),
                "status_code": resp.status_code, "response_time": elapsed,
                "content_type": ct, "html": resp.text,
                "redirect_chain": redirect_chain}
    except requests.exceptions.Timeout:
        return {"url": url, "error": "TIMEOUT", "status_code": None,
                "html": "", "redirect_chain": [], "final_url": url}
    except Exception as e:
        return {"url": url, "error": str(e)[:120], "status_code": None,
                "html": "", "redirect_chain": [], "final_url": url}


# ════════════════════════════════════════════════════════════════════════════
#  EXTRACCION SEO
# ════════════════════════════════════════════════════════════════════════════

def extract_seo(url, fetch, domain):
    base = {
        "url": url,
        "final_url": fetch.get("final_url", url),
        "status_code": fetch.get("status_code"),
        "response_time_s": fetch.get("response_time"),
        "content_type": fetch.get("content_type", ""),
        "is_redirect": url != fetch.get("final_url", url),
        "redirect_chain": " > ".join(fetch.get("redirect_chain", [])),
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

    body        = soup.find("body")
    word_count  = len(body.get_text(" ", strip=True).split()) if body else 0

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

    images      = soup.find_all("img")
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
    if not t:        return "AUSENTE"
    if len(t) < 30:  return "MUY_CORTO"
    if len(t) > 60:  return "MUY_LARGO"
    return ""

def _issues_meta(d):
    if not d:        return "AUSENTE"
    if len(d) < 70:  return "MUY_CORTA"
    if len(d) > 160: return "MUY_LARGA"
    return ""


# ════════════════════════════════════════════════════════════════════════════
#  SPIDER (BFS + ThreadPoolExecutor - 100% sincrono, sin asyncio)
# ════════════════════════════════════════════════════════════════════════════

def run_spider(start_url, max_pages, max_depth, concurrency,
               respect_noindex, progress_queue):
    domain   = urlparse(start_url).netloc.lower().lstrip("www.")
    visited  = set()
    frontier = deque()
    results  = []

    start_norm = normalize_url(start_url)
    frontier.append((start_norm, 0))
    visited.add(start_norm)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        while frontier and len(results) < max_pages:
            batch = []
            while frontier and len(batch) < concurrency:
                batch.append(frontier.popleft())

            future_map = {
                executor.submit(fetch_url, url): (url, depth)
                for url, depth in batch
            }

            for future in as_completed(future_map):
                url, depth = future_map[future]
                try:
                    fetch_result = future.result()
                except Exception as e:
                    fetch_result = {"url": url, "error": str(e), "html": "",
                                    "status_code": None, "final_url": url,
                                    "redirect_chain": []}

                seo_data = extract_seo(url, fetch_result, domain)
                results.append(seo_data)

                progress_queue.put({
                    "done": len(results),
                    "total": max_pages,
                    "url": url,
                    "status": seo_data.get("status_code", "ERR"),
                })

                if len(results) >= max_pages:
                    break

                if respect_noindex and seo_data.get("is_noindex"):
                    continue

                if depth < max_depth:
                    for link in seo_data.get("internal_links_raw", []):
                        norm = normalize_url(link)
                        if (norm not in visited
                                and not should_exclude(norm, EXCLUDE_PATTERNS)
                                and len(visited) < max_pages * 3):
                            visited.add(norm)
                            frontier.append((norm, depth + 1))

    progress_queue.put(None)
    return results


# ════════════════════════════════════════════════════════════════════════════
#  HELPERS DE DATOS
# ════════════════════════════════════════════════════════════════════════════

def build_issues_summary(df):
    checks = {
        "Sin titulo":             df["title"].str.strip().eq(""),
        "Titulo muy largo (>60)": df["title_length"].gt(60),
        "Titulo muy corto (<30)": df["title_length"].gt(0) & df["title_length"].lt(30),
        "Sin meta description":   df["meta_description"].str.strip().eq(""),
        "Meta desc muy larga":    df["meta_desc_length"].gt(160),
        "Sin H1":                 df["h1_count"].eq(0),
        "Multiples H1":           df["h1_count"].gt(1),
        "Noindex":                df["is_noindex"].eq(True),
        "Sin canonical":          df["canonical"].str.strip().eq(""),
        "Canonical no self":      df["is_self_canonical"].eq(False),
        "Imagenes sin alt":       df["images_no_alt"].gt(0),
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


def normalize_df(df):
    STR_COLS  = ["title", "meta_description", "h1", "h2_sample", "robots_meta",
                 "canonical", "hreflang", "og_title", "og_description",
                 "og_image", "og_type", "schema_types", "redirect_chain",
                 "content_type", "final_url", "rel_next", "rel_prev",
                 "title_issues", "meta_desc_issues", "error"]
    INT_COLS  = ["title_length", "meta_desc_length", "h1_count", "h2_count",
                 "h3_count", "hreflang_count", "word_count",
                 "internal_links_count", "external_links_count",
                 "nofollow_links_count", "images_total", "images_no_alt"]
    BOOL_COLS = ["is_redirect", "is_noindex", "is_self_canonical"]

    for col in STR_COLS:
        if col not in df.columns: df[col] = ""
        df[col] = df[col].fillna("").astype(str)
    for col in INT_COLS:
        if col not in df.columns: df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    for col in BOOL_COLS:
        if col not in df.columns: df[col] = False
        df[col] = df[col].fillna(False).astype(bool)
    df["status_code"] = pd.to_numeric(df.get("status_code", 0), errors="coerce").fillna(0).astype(int)
    return df


def to_excel_bytes(df):
    output = io.BytesIO()
    clean  = df.drop(columns=["internal_links_raw"], errors="ignore")
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        clean.to_excel(writer, index=False, sheet_name="Crawl")
        build_issues_summary(clean).to_excel(writer, index=False, sheet_name="Issues")
        clean[clean["is_redirect"]== True][
            ["url","final_url","status_code","redirect_chain"]
        ].to_excel(writer, index=False, sheet_name="Redirects")
        clean[clean["error"].astype(str).str.len() > 0][
            ["url","status_code","error"]
        ].to_excel(writer, index=False, sheet_name="Errors")
    return output.getvalue()


# ════════════════════════════════════════════════════════════════════════════
#  UI STREAMLIT
# ════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Nomad SEO Spider", page_icon="🕷", layout="wide")
st.title("🕷 Nomad SEO Spider")
st.caption("Herramienta interna Nomadic · alternativa a Screaming Frog")

with st.sidebar:
    st.header("Configuracion")
    start_url       = st.text_input("URL de inicio", placeholder="https://cliente.com")
    max_pages       = st.slider("Max. URLs a rastrear", 50, 2000, 500, step=50)
    max_depth       = st.slider("Profundidad maxima", 1, 10, 5)
    concurrency     = st.slider("Concurrencia (requests simultaneos)", 3, 20, 8)
    respect_noindex = st.checkbox("Respetar noindex (no seguir)", value=True)
    st.markdown("---")
    st.markdown("**Como usar:**\n1. Ingresa la URL\n2. Ajusta parametros\n3. Presiona **Iniciar crawl**\n4. Descarga el Excel")

run = st.button("Iniciar crawl", type="primary", disabled=not start_url)

if run and start_url:
    if not start_url.startswith("http"):
        st.error("La URL debe empezar con http:// o https://")
    else:
        st.info(f"Rastreando **{start_url}** - max. {max_pages} URLs - profundidad {max_depth}")
        progress_bar = st.progress(0.0)
        status_text  = st.empty()

        pq = queue.Queue()
        results_holder = []

        def spider_thread():
            data = run_spider(
                start_url, max_pages, max_depth,
                concurrency, respect_noindex, pq
            )
            results_holder.extend(data)

        t = threading.Thread(target=spider_thread, daemon=True)
        t.start()

        while True:
            msg = pq.get()
            if msg is None:
                break
            pct = min(msg["done"] / msg["total"], 1.0)
            progress_bar.progress(pct)
            status_text.text(
                f"Procesando {msg['done']}/{msg['total']}  [{msg['status']}]  {msg['url'][-80:]}"
            )

        t.join()

        progress_bar.progress(1.0)
        status_text.text(f"Crawl completo - {len(results_holder)} URLs procesadas")

        df = normalize_df(pd.DataFrame(results_holder))

        st.markdown("---")
        st.subheader("Resumen")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("URLs rastreadas", len(df))
        c2.metric("2xx OK",          int(df["status_code"].between(200, 299).sum()))
        c3.metric("3xx Redirects",   int(df["status_code"].between(300, 399).sum()))
        c4.metric("4xx Errors",      int(df["status_code"].between(400, 499).sum()))
        c5.metric("Sin titulo",      int(df["title"].str.strip().eq("").sum()))

        st.subheader("Issues detectados")
        clean     = df.drop(columns=["internal_links_raw"], errors="ignore")
        issues_df = build_issues_summary(clean)
        if issues_df.empty:
            st.success("No se detectaron issues relevantes")
        else:
            st.dataframe(issues_df, use_container_width=True, hide_index=True)

        st.subheader("Vista previa de datos")
        PREVIEW      = ["url","status_code","title","title_length",
                        "meta_desc_length","h1_count","word_count",
                        "is_noindex","canonical","schema_types"]
        preview_cols = [c for c in PREVIEW if c in clean.columns]
        st.dataframe(clean[preview_cols].head(100),
                     use_container_width=True, hide_index=True)

        st.markdown("---")
        slug     = urlparse(start_url).netloc.replace("www.", "").replace(".", "_")
        filename = f"seo_crawl_{slug}.xlsx"
        st.download_button(
            label="Descargar Excel completo",
            data=to_excel_bytes(clean),
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

elif not run:
    st.markdown("""
    ### Que analiza esta herramienta

    | Categoria | Datos extraidos |
    |---|---|
    | HTTP | Status code, tiempo de respuesta, cadena de redirecciones |
    | On-page | Titulo, meta description, H1/H2/H3 |
    | Indexacion | Robots meta, noindex, canonical, hreflang |
    | Social | Open Graph (titulo, descripcion, imagen, tipo) |
    | Schema | Tipos de structured data detectados |
    | Contenido | Word count |
    | Links | Internos, externos, nofollow |
    | Imagenes | Total, sin atributo alt |
    | Paginacion | rel=next / rel=prev |
    """)
