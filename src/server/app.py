from __future__ import annotations
import os
import uuid
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from myntra_shopify.transform import transform, write_output
from myntra_shopify.io import read_rows
from myntra_shopify.images import extract_sku, list_images, list_images_shallow, base_from_variant_sku
from myntra_shopify import shopify_client as sc
import base64
from . import db
from . import settings as app_settings


ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "uploads"
RESULTS = ROOT / "results"
UPLOADS.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)
TEMPLATES_DIR = ROOT / "src" / "server" / "templates"
STATIC_DIR = ROOT / "src" / "server" / "static"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Myntra → Shopify API", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
db.init_db(ROOT / "data" / "app.sqlite3")
app_settings.init_settings(ROOT / "data" / "settings.json")


class JobStatus(str):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class Job(BaseModel):
    id: str
    kind: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    params: Dict
    result_path: Optional[str] = None
    error: Optional[str] = None
    counters: Dict = {}


JOBS: Dict[str, Job] = {}


class FileInfo(BaseModel):
    id: str
    name: str
    path: str
    size: int
    created_at: datetime


FILES: Dict[str, FileInfo] = {}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


# --- Minimal HTML UI ---
def _layout(body: str) -> str:
    return f"""
<!doctype html>
<html>
  <head>
    <meta charset='utf-8'/>
    <meta name='viewport' content='width=device-width, initial-scale=1'/>
    <title>Myntra → Shopify</title>
    <style>
      body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;}}
      h1,h2{{margin:12px 0}}
      form{{border:1px solid #eee;padding:12px;border-radius:8px;margin:16px 0}}
      label{{display:block;margin:8px 0 4px;font-weight:600}}
      input,select{{padding:8px;width:100%;max-width:420px}}
      button{{padding:8px 12px;margin-top:8px}}
      table{{border-collapse:collapse;width:100%;}}
      th,td{{border:1px solid #eee;padding:6px;text-align:left}}
      .muted{{color:#666;font-size:90%}}
      .ok{{color:#167d2f}}
      .err{{color:#b10000}}
      .chip{{display:inline-block;padding:2px 8px;border-radius:12px;background:#eee;margin-left:6px}}
    </style>
  </head>
  <body>
    <h1>Myntra → Shopify</h1>
    {body}
  </body>
 </html>
"""


@app.get("/", response_class=HTMLResponse)
def ui_home():
    files_rows = "".join(
        f"<tr><td>{f.id}</td><td>{f.name}</td><td>{f.size}</td><td class='muted'>{Path(f.path).name}</td></tr>"
        for f in list(FILES.values())[-10:]
    )
    jobs_rows = "".join(
        f"<tr><td><a href='/ui/jobs/{j.id}'>{j.id[:8]}</a></td><td>{j.kind}</td><td>{j.status}</td><td>{j.counters.get('rows') or j.counters.get('files') or ''}</td><td class='muted'>{j.created_at}</td></tr>"
        for j in list(JOBS.values())[-10:]
    )
    body = f"""
    <p class='muted'>Quickstart: Upload a CSV, create a transform job, then download the Shopify CSV. Or try an images dry-run to preview SKU extraction.</p>

    <h2>Upload CSV</h2>
    <form method='post' action='/ui/files' enctype='multipart/form-data'>
      <label>CSV File</label>
      <input type='file' name='file' accept='.csv' required />
      <br/>
      <button type='submit'>Upload</button>
    </form>

    <h2>Create Transform Job</h2>
    <form method='post' action='/ui/jobs/transform'>
      <label>File ID</label>
      <input type='text' name='file_id' placeholder='paste a file id from table below' required />
      <label>Default Qty</label>
      <input type='number' name='default_qty' value='{int(os.getenv("DEFAULT_QTY","50"))}' />
      <label>Default Grams</label>
      <input type='number' name='default_grams' value='{int(os.getenv("DEFAULT_GRAMS","400"))}' />
      <label>LLM</label>
      <select name='llm_enable'><option value='false'>Disabled</option><option value='true'>Enabled</option></select>
      <label>LLM Prefer</label>
      <select name='llm_prefer'><option value='false'>No</option><option value='true'>Yes</option></select>
      <label>LLM Max Products</label>
      <input type='number' name='llm_max_products' value='0' />
      <label>Variant Qty Blank</label>
      <select name='variant_qty_blank'><option value='false'>No</option><option value='true'>Yes</option></select>
      <button type='submit'>Create Job</button>
    </form>

    <h2>Images by SKU (Dry-Run)</h2>
    <form method='post' action='/ui/jobs/images/by-sku'>
      <label>Images Directory (server path)</label>
      <input type='text' name='images_dir' placeholder='/absolute/or/repo/path' required />
      <label>SKU Mode</label>
      <select name='sku_mode'><option>stem</option><option>prefix</option><option>parent</option></select>
      <label>SKU Regex (optional)</label>
      <input type='text' name='sku_regex' />
      <label>Parent Depth (when mode=parent)</label>
      <input type='number' name='parent_depth' />
      <label>Parent Regex (when mode=parent)</label>
      <input type='text' name='parent_regex' />
      <button type='submit'>Preview</button>
    </form>

    <h2>Recent Files</h2>
    <table><thead><tr><th>ID</th><th>Name</th><th>Size</th><th>Stored</th></tr></thead><tbody>{files_rows or '<tr><td colspan=4 class="muted">No files yet</td></tr>'}</tbody></table>

    <h2>Recent Jobs</h2>
    <table><thead><tr><th>ID</th><th>Kind</th><th>Status</th><th>Count</th><th>Created</th></tr></thead><tbody>{jobs_rows or '<tr><td colspan=5 class="muted">No jobs yet</td></tr>'}</tbody></table>
    <p class='muted'>API docs: <a href='/docs'>/docs</a></p>
    """
    from fastapi.responses import RedirectResponse as _RR
    return _RR(url="/ui", status_code=302)


# --- Jinja2-based polished UI (optional) ---
@app.get("/ui", response_class=HTMLResponse)
def ui_dashboard(request: Request):
    try:
        files = db.list_files()[:10]
    except Exception:
        files = list(FILES.values())[-10:]
    try:
        jobs = db.list_jobs()[:10]
    except Exception:
        jobs = list(JOBS.values())[-10:]
    return templates.TemplateResponse("dashboard.html", {"request": request, "files": files, "jobs": jobs})


@app.get("/ui/files", response_class=HTMLResponse)
def ui_files(request: Request):
    try:
        files = db.list_files()
    except Exception:
        files = list(FILES.values())[::-1]
    return templates.TemplateResponse("files.html", {"request": request, "files": files})


@app.get("/ui/jobs", response_class=HTMLResponse)
def ui_jobs(request: Request):
    try:
        jobs = db.list_jobs()
    except Exception:
        jobs = list(JOBS.values())[::-1]
    return templates.TemplateResponse("jobs_list.html", {"request": request, "jobs": jobs})


@app.get("/ui/jobs/{job_id}", response_class=HTMLResponse)
def ui_job_detail(request: Request, job_id: str):
    try:
        j = db.get_job(job_id)
    except Exception:
        j = None
    if not j:
        j = JOBS.get(job_id)
    data_preview = None
    result_path = (j.get("result_path") if isinstance(j, dict) else j.result_path) if j else None
    if j and result_path and str(result_path).endswith('.json'):
        try:
            data_preview = Path(result_path).read_text()[:20000]
        except Exception:
            data_preview = None
    return templates.TemplateResponse("job_detail.html", {"request": request, "job": j, "data_preview": data_preview})


@app.get("/ui/transform", response_class=HTMLResponse)
def ui_transform(request: Request):
    try:
        files = db.list_files()
    except Exception:
        files = list(FILES.values())[::-1]
    s = app_settings.get_settings()
    return templates.TemplateResponse("transform_new.html", {"request": request, "files": files, "defaults": {"qty": s.get("default_qty", 50), "grams": s.get("default_grams", 400)}})


@app.get("/ui/images", response_class=HTMLResponse)
def ui_images(request: Request):
    s = app_settings.get_settings()
    return templates.TemplateResponse("images.html", {"request": request, "defaults": s})


@app.post("/ui/jobs/images/by-sku/upload")
def ui_images_by_sku_upload(
    images_dir: str = Form(...),
    sku_mode: str = Form("stem"),
    sku_regex: Optional[str] = Form(None),
    parent_depth: Optional[int] = Form(None),
    parent_regex: Optional[str] = Form(None),
    match_multiple: str = Form("first"),
    link_to_variant: str = Form("false"),
    alt_from: str = Form("none"),
    delay: float = Form(0.5),
    bg: BackgroundTasks = None,
):
    req = ImageBySkuUpload(
        images_dir=images_dir,
        sku_mode=sku_mode,
        sku_regex=sku_regex or None,
        parent_depth=parent_depth,
        parent_regex=parent_regex or None,
        match_multiple=match_multiple,
        link_to_variant=(link_to_variant == "true"),
        alt_from=alt_from,
        delay=delay,
    )
    job = create_images_by_sku_upload(req, bg)
    return RedirectResponse(url=f"/ui/jobs/{job.id}", status_code=302)


@app.get("/ui/settings", response_class=HTMLResponse)
def ui_get_settings(request: Request):
    s = app_settings.get_settings()
    return templates.TemplateResponse("settings.html", {"request": request, "s": s})


@app.post("/ui/settings")
def ui_post_settings(
    default_qty: int = Form(50),
    default_grams: int = Form(400),
    llm_enable_default: str = Form("false"),
    llm_prefer_default: str = Form("false"),
    llm_max_products_default: int = Form(0),
    images_delay_default: float = Form(0.5),
    shopify_store: str = Form(""),
    shopify_api_version: str = Form("2024-07"),
    shopify_access_token: str = Form(""),
    brand_strip_value: str = Form("zummer"),
    vendor_name: str = Form("Zummer"),
    brand_name: str = Form("Zummer"),
    brand_audience: str = Form("Modern Indian women, 25–35"),
):
    cur = app_settings.get_settings()
    cur.update({
        "default_qty": default_qty,
        "default_grams": default_grams,
        "llm_enable_default": (llm_enable_default == "true"),
        "llm_prefer_default": (llm_prefer_default == "true"),
        "llm_max_products_default": llm_max_products_default,
        "images_delay_default": images_delay_default,
        "shopify_store": shopify_store.strip(),
        "shopify_api_version": shopify_api_version.strip() or "2024-07",
        "shopify_access_token": shopify_access_token.strip(),
        "brand_strip_value": brand_strip_value.strip() or "zummer",
        "vendor_name": vendor_name.strip() or "Zummer",
        "brand_name": brand_name.strip() or "Zummer",
        "brand_audience": brand_audience.strip() or "",
    })
    app_settings.save_settings(cur)
    return RedirectResponse(url="/ui/settings", status_code=302)


@app.post("/ui/settings/test")
def ui_test_shopify():
    """Ping Shopify with current settings and return identity confirmation."""
    try:
        cfg = _get_shopify_cfg()
        session = sc.build_session(cfg)
        shop = sc.get_shop_info(session, cfg)
        # Return essential identifiers to confirm ownership
        return {"ok": True, "shop": {"name": shop.get("name"), "domain": shop.get("myshopify_domain") or shop.get("myshopify_domain") or shop.get("domain")}}
    except HTTPException as e:
        return {"ok": False, "error": str(e.detail)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Shopify staged uploads: browser direct → server finalize ---
class StagedFile(BaseModel):
    filename: str
    mimeType: str = "image/jpeg"
    fileSize: int = 0


@app.post("/uploads/staged/params")
def get_staged_upload_params(files: List[StagedFile]):
    cfg = _get_shopify_cfg()
    session = sc.build_session(cfg)
    targets = sc.staged_uploads_create(session, cfg, [f.model_dump() for f in files])
    return {"ok": True, "targets": targets}


class StagedAttachItem(BaseModel):
    filename: str
    resourceUrl: str
    sku: Optional[str] = None
    alt: Optional[str] = None
    product_id: Optional[int] = None
    variant_id: Optional[int] = None


class StagedAttachRequest(BaseModel):
    items: List[StagedAttachItem]
    match_multiple: str = "first"
    link_to_variant: bool = False
    delay: float = 0.5


@app.post("/jobs/images/staged/attach-by-sku", response_model=Job)
def create_staged_attach_job(req: StagedAttachRequest, bg: BackgroundTasks):
    job_id = uuid.uuid4().hex
    job = Job(
        id=job_id,
        kind="images/staged/attach-by-sku",
        status=JobStatus.queued,
        created_at=datetime.utcnow(),
        params=req.model_dump(),
    )
    JOBS[job_id] = job
    try:
        db.add_job(job.model_dump())
    except Exception:
        pass

    def run():
        j = JOBS[job_id]
        j.status = JobStatus.running
        j.started_at = datetime.utcnow()
        uploaded = skipped = errors = 0
        try:
            cfg = _get_shopify_cfg()
            session = sc.build_session(cfg)
            for it in req.items:
                try:
                    product_id = None
                    variant_id = None
                    if it.product_id:
                        product_id = int(it.product_id)
                        if req.link_to_variant and it.variant_id:
                            variant_id = int(it.variant_id)
                    else:
                        sku = (it.sku or "").strip()
                        if not sku:
                            errors += 1
                            continue
                        variants = sc.find_variants_by_sku(session, cfg, sku)
                        if not variants:
                            errors += 1
                            continue
                        chosen = [variants[0]] if req.match_multiple == "first" else variants
                        product_id = int(chosen[0]["product_id"])
                        if req.link_to_variant:
                            variant_id = int(chosen[0]["id"])

                    alt_text = (it.alt or "").strip() or None
                    sc.upload_image_from_src(
                        session=session,
                        cfg=cfg,
                        product_id=int(product_id),
                        src_url=it.resourceUrl,
                        filename=it.filename,
                        alt_text=alt_text,
                        variant_id=variant_id,
                    )
                    uploaded += 1
                    if req.delay and req.delay > 0:
                        time.sleep(req.delay)
                except Exception:
                    errors += 1
            out = RESULTS / f"{job_id}.json"
            out.write_text(__import__("json").dumps({
                "summary": {"attached": uploaded, "errors": errors, "skipped": skipped},
            }, indent=2))
            j.counters = {"attached": uploaded, "errors": errors, "skipped": skipped}
            j.result_path = str(out)
            j.status = JobStatus.succeeded if errors == 0 else JobStatus.failed
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        except Exception as e:
            j.status = JobStatus.failed
            j.error = str(e)
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        finally:
            j.finished_at = datetime.utcnow()
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass

    bg.add_task(run)
    return job


@app.post("/ui/jobs/images/by-base/upload")
def ui_images_by_base_upload(
    images_dir: str = Form(...),
    bases_depth: int = Form(1),
    bases: Optional[str] = Form(None),
    limit_bases: Optional[int] = Form(None),
    offset_bases: int = Form(0),
    limit_files_per_base: Optional[int] = Form(None),
    one_level: str = Form("false"),
    only_empty_products: str = Form("false"),
    product_only: str = Form("false"),
    link_to_variant: str = Form("false"),
    alt_from: str = Form("none"),
    delay: float = Form(0.5),
    bg: BackgroundTasks = None,
):
    req = ImageByBaseUpload(
        images_dir=images_dir,
        bases_depth=bases_depth,
        bases=[b.strip() for b in (bases or '').split(',') if b.strip()] or None,
        limit_bases=limit_bases,
        offset_bases=offset_bases,
        limit_files_per_base=limit_files_per_base,
        one_level=(one_level == "true"),
        only_empty_products=(only_empty_products == "true"),
        product_only=(product_only == "true"),
        link_to_variant=(link_to_variant == "true"),
        alt_from=alt_from,
        delay=delay,
    )
    job = create_images_by_base_upload(req, bg)
    return RedirectResponse(url=f"/ui/jobs/{job.id}", status_code=302)


@app.post("/ui/jobs/images/broadcast")
async def ui_broadcast_image(
    file: UploadFile = File(...),
    alt_text: Optional[str] = Form(None),
    product_ids: Optional[str] = Form(None),
    limit: Optional[int] = Form(None),
    skip_if_alt_exists: str = Form("false"),
    delay: float = Form(0.5),
    bg: BackgroundTasks = None,
):
    job = await create_broadcast_image_job(
        file=file,
        alt_text=alt_text,
        product_ids=product_ids,
        limit=limit,
        skip_if_alt_exists=(skip_if_alt_exists == "true"),
        delay=delay,
        bg=bg,
    )
    return RedirectResponse(url=f"/ui/jobs/{job.id}", status_code=302)


@app.post("/ui/files")
async def ui_upload_file(file: UploadFile = File(...)):
    await upload_file(file)
    return RedirectResponse(url="/ui", status_code=302)


@app.get("/ui/jobs/legacy/{job_id}", response_class=HTMLResponse)
def ui_job(job_id: str):
    if job_id not in JOBS:
        return HTMLResponse(_layout(f"<p class='err'>Job not found: {job_id}</p><p><a href='/'>Back</a></p>"), status_code=404)
    j = JOBS[job_id]
    link = f"<a href='/jobs/{j.id}/download'>Download CSV</a>" if j.status == JobStatus.succeeded and j.result_path and str(j.result_path).endswith('.csv') else ''
    preview = ''
    if j.status == JobStatus.succeeded and j.result_path and str(j.result_path).endswith('.json'):
        try:
            data = Path(j.result_path).read_text()[:20000]
            preview = f"<h3>Result Preview</h3><pre style='white-space:pre-wrap'>{data}</pre>"
        except Exception:
            pass
    refresh = "<meta http-equiv='refresh' content='2'/>" if j.status in (JobStatus.queued, JobStatus.running) else ''
    body = f"""
    {refresh}
    <p><a href='/'>← Back</a></p>
    <h2>Job {j.id}</h2>
    <p>Status: <span class='chip'>{j.status}</span></p>
    <p>Kind: {j.kind}</p>
    <p>Created: {j.created_at} | Started: {j.started_at or '-'} | Finished: {j.finished_at or '-'}</p>
    <p>Counts: {j.counters}</p>
    <p class='ok'>{link}</p>
    <h3>Params</h3>
    <pre style='white-space:pre-wrap'>{j.params}</pre>
    {preview}
    """
    return _layout(body)


@app.post("/ui/jobs/transform")
def ui_create_transform_job(
    file_id: str = Form(...),
    default_qty: int = Form(50),
    default_grams: int = Form(400),
    llm_enable: str = Form("false"),
    llm_prefer: str = Form("false"),
    llm_max_products: int = Form(0),
    variant_qty_blank: str = Form("false"),
    bg: BackgroundTasks = None,
):
    req = TransformRequest(
        file_id=file_id,
        default_qty=default_qty,
        default_grams=default_grams,
        llm_enable=(llm_enable == "true"),
        llm_prefer=(llm_prefer == "true"),
        llm_max_products=llm_max_products,
        variant_qty_blank=(variant_qty_blank == "true"),
    )
    job = create_transform_job(req, bg)
    return RedirectResponse(url=f"/ui/jobs/{job.id}", status_code=302)


@app.post("/ui/jobs/images/by-sku")
def ui_create_images_by_sku_job(
    images_dir: str = Form(...),
    sku_mode: str = Form("stem"),
    sku_regex: Optional[str] = Form(None),
    parent_depth: Optional[int] = Form(None),
    parent_regex: Optional[str] = Form(None),
    bg: BackgroundTasks = None,
):
    req = ImageBySkuRequest(
        images_dir=images_dir,
        sku_mode=sku_mode,
        sku_regex=sku_regex or None,
        parent_depth=parent_depth,
        parent_regex=parent_regex or None,
        dry_run=True,
    )
    job = create_images_by_sku_job(req, bg)
    return RedirectResponse(url=f"/ui/jobs/{job.id}", status_code=302)


@app.post("/files", response_model=FileInfo)
async def upload_file(file: UploadFile = File(...)):
    fid = uuid.uuid4().hex
    dest = UPLOADS / f"{fid}_{file.filename}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    info = FileInfo(id=fid, name=file.filename, path=str(dest), size=dest.stat().st_size, created_at=datetime.utcnow())
    FILES[fid] = info
    # persist
    try:
        db.add_file(info.model_dump())
    except Exception:
        pass
    return info


@app.get("/files", response_model=List[FileInfo])
def list_files() -> List[FileInfo]:
    return list(FILES.values())


class TransformRequest(BaseModel):
    file_id: str
    default_qty: int = int(os.getenv("DEFAULT_QTY", "50"))
    default_grams: int = int(os.getenv("DEFAULT_GRAMS", "400"))
    llm_enable: bool = False
    llm_prefer: bool = False
    llm_max_products: int = 0
    variant_qty_blank: bool = False


@app.post("/jobs/transform", response_model=Job)
def create_transform_job(req: TransformRequest, bg: BackgroundTasks):
    if req.file_id not in FILES:
        raise HTTPException(404, "file_id not found")
    job_id = uuid.uuid4().hex
    job = Job(
        id=job_id,
        kind="transform",
        status=JobStatus.queued,
        created_at=datetime.utcnow(),
        params=req.model_dump(),
    )
    JOBS[job_id] = job
    try:
        db.add_job(job.model_dump())
    except Exception:
        pass

    def run():
        j = JOBS[job_id]
        j.status = JobStatus.running
        j.started_at = datetime.utcnow()
        try:
            # Apply brand/vendor defaults into env for transformer
            try:
                s = app_settings.get_settings()
                if s.get("vendor_name"):
                    os.environ["VENDOR"] = s.get("vendor_name") or ""
                if s.get("brand_strip_value"):
                    os.environ["BRAND_STRIP_VALUE"] = s.get("brand_strip_value") or ""
                if s.get("brand_name"):
                    os.environ["LLM_BRAND"] = s.get("brand_name") or ""
                if s.get("brand_audience"):
                    os.environ["LLM_AUDIENCE"] = s.get("brand_audience") or ""
            except Exception:
                pass
            src_path = Path(FILES[req.file_id].path)
            llm_cfg = None
            if req.llm_enable:
                llm_cfg = {
                    "enabled": True,
                    "prefer": bool(req.llm_prefer),
                    "base_url": os.getenv("LLM_BASE_URL", "https://api.openai.com"),
                    "endpoint": os.getenv("LLM_ENDPOINT", "chat"),
                    "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
                    "api_key_env": os.getenv("LLM_API_KEY_ENV", "OPENAI_API_KEY"),
                    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
                    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "250")),
                    "timeout": int(os.getenv("LLM_TIMEOUT", "30")),
                    "cache_dir": os.getenv("LLM_CACHE_DIR", ""),
                    "rate_sleep": float(os.getenv("LLM_RATE_SLEEP", "0.0")),
                    "brand": os.getenv("LLM_BRAND", ""),
                    "audience": os.getenv("LLM_AUDIENCE", ""),
                }
            rows = transform(
                src_path,
                default_qty=req.default_qty,
                default_grams=req.default_grams,
                llm_cfg=llm_cfg,
                limit_products=0,
                llm_max_products=req.llm_max_products,
                inventory_qty_blank=req.variant_qty_blank,
            )
            out = RESULTS / f"{job_id}.csv"
            write_output(out, rows)
            j.counters = {"rows": len(rows)}
            j.result_path = str(out)
            j.status = JobStatus.succeeded
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        except Exception as e:
            j.status = JobStatus.failed
            j.error = str(e)
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        finally:
            j.finished_at = datetime.utcnow()
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass

    bg.add_task(run)
    return job


@app.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str) -> Job:
    if job_id in JOBS:
        return JOBS[job_id]
    try:
        j = db.get_job(job_id)
        if j:
            return Job(**j)
    except Exception:
        pass
    raise HTTPException(404, "job not found")


@app.get("/jobs/{job_id}/download")
def download_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        dj = db.get_job(job_id)
        if not dj:
            raise HTTPException(404, "job not found")
        if (dj.get("status") != JobStatus.succeeded) or not dj.get("result_path"):
            raise HTTPException(400, "job not completed or no result available")
        return FileResponse(path=dj.get("result_path"), filename=f"shopify_{job_id}.csv", media_type="text/csv")
    if job.status != JobStatus.succeeded or not job.result_path:
        raise HTTPException(400, "job not completed or no result available")
    return FileResponse(path=job.result_path, filename=f"shopify_{job_id}.csv", media_type="text/csv")


class ImageBySkuRequest(BaseModel):
    # For now, accept directory path on server to keep simple; UI can upload via /files later
    images_dir: str
    sku_mode: str = "stem"  # stem|prefix|parent
    sku_regex: Optional[str] = None
    parent_depth: Optional[int] = None
    parent_regex: Optional[str] = None
    dry_run: bool = True
    match_multiple: str = "first"  # first|all
    link_to_variant: bool = False
    alt_from: str = "none"  # none|stem
    delay: float = 0.5


@app.post("/jobs/images/by-sku", response_model=Job)
def create_images_by_sku_job(req: ImageBySkuRequest, bg: BackgroundTasks):
    job_id = uuid.uuid4().hex
    job = Job(
        id=job_id,
        kind="images/by-sku",
        status=JobStatus.queued,
        created_at=datetime.utcnow(),
        params=req.model_dump(),
    )
    JOBS[job_id] = job

    def run():
        j = JOBS[job_id]
        j.status = JobStatus.running
        j.started_at = datetime.utcnow()
        try:
            images_root = Path(req.images_dir)
            if not images_root.exists():
                raise FileNotFoundError(f"images_dir not found: {images_root}")
            files = [p for p in images_root.rglob("*") if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}]
            previews: List[Dict] = []
            for p in files:
                sku = extract_sku(
                    path=p,
                    mode=req.sku_mode,
                    regex=req.sku_regex,
                    images_root=images_root,
                    parent_depth=req.parent_depth,
                    parent_regex=req.parent_regex,
                )
                previews.append({"file": str(p), "sku": sku or ""})
            out = RESULTS / f"{job_id}.json"
            out.write_text(__import__("json").dumps({"dry_run": True, "files": previews}, indent=2))
            j.counters = {"files": len(files)}
            j.result_path = str(out)
            j.status = JobStatus.succeeded
        except Exception as e:
            j.status = JobStatus.failed
            j.error = str(e)
        finally:
            j.finished_at = datetime.utcnow()

    bg.add_task(run)
    return job


# --- Real image upload jobs ---

def _get_shopify_cfg() -> sc.ShopifyConfig:
    # Prefer settings.json; fallback to env vars
    try:
        s = app_settings.get_settings()
    except Exception:
        s = {}
    store = (s.get("shopify_store") or os.getenv("SHOPIFY_STORE", "")).strip()
    token = (s.get("shopify_access_token") or os.getenv("SHOPIFY_ACCESS_TOKEN", "")).strip()
    version = (s.get("shopify_api_version") or os.getenv("SHOPIFY_API_VERSION", "2024-07")).strip() or "2024-07"
    if not store or not token:
        raise HTTPException(500, "Shopify credentials missing. Set them in Settings or as environment variables.")
    return sc.ShopifyConfig(store=store, token=token, api_version=version)


class ImageBySkuUpload(BaseModel):
    images_dir: str
    sku_mode: str = "stem"
    sku_regex: Optional[str] = None
    parent_depth: Optional[int] = None
    parent_regex: Optional[str] = None
    match_multiple: str = "first"  # first|all
    link_to_variant: bool = False
    alt_from: str = "none"  # none|stem
    delay: float = 0.5


@app.post("/jobs/images/by-sku/upload", response_model=Job)
def create_images_by_sku_upload(req: ImageBySkuUpload, bg: BackgroundTasks):
    job_id = uuid.uuid4().hex
    job = Job(
        id=job_id,
        kind="images/by-sku/upload",
        status=JobStatus.queued,
        created_at=datetime.utcnow(),
        params=req.model_dump(),
    )
    JOBS[job_id] = job
    try:
        db.add_job(job.model_dump())
    except Exception:
        pass

    def run():
        j = JOBS[job_id]
        j.status = JobStatus.running
        j.started_at = datetime.utcnow()
        uploaded = skipped = errors = 0
        try:
            cfg = _get_shopify_cfg()
            session = sc.build_session(cfg)
            root = Path(req.images_dir)
            files = list_images(root)
            for path in files:
                try:
                    sku = extract_sku(
                        path=path,
                        mode=req.sku_mode,
                        regex=req.sku_regex,
                        images_root=root,
                        parent_depth=req.parent_depth,
                        parent_regex=req.parent_regex,
                    )
                    if not sku:
                        errors += 1
                        continue
                    variants = sc.find_variants_by_sku(session, cfg, sku)
                    if not variants:
                        errors += 1
                        continue
                    chosen = [variants[0]] if req.match_multiple == "first" else variants
                    product_id = int(chosen[0]["product_id"])
                    variant_id = int(chosen[0]["id"]) if req.link_to_variant else None
                    alt_text = path.stem if req.alt_from == "stem" else None
                    image_b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
                    sc.upload_image_to_product(
                        session=session,
                        cfg=cfg,
                        product_id=product_id,
                        image_b64=image_b64,
                        filename=path.name,
                        alt_text=alt_text,
                        variant_id=variant_id,
                    )
                    uploaded += 1
                    if req.delay > 0:
                        time.sleep(req.delay)
                except Exception:
                    errors += 1
            out = RESULTS / f"{job_id}.json"
            out.write_text(__import__("json").dumps({
                "summary": {"uploaded": uploaded, "errors": errors, "skipped": skipped},
                "images_dir": str(root),
            }, indent=2))
            j.counters = {"uploaded": uploaded, "errors": errors, "skipped": skipped}
            j.result_path = str(out)
            j.status = JobStatus.succeeded if errors == 0 else JobStatus.failed
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        except HTTPException as e:
            j.status = JobStatus.failed
            j.error = str(e.detail)
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        except Exception as e:
            j.status = JobStatus.failed
            j.error = str(e)
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        finally:
            j.finished_at = datetime.utcnow()
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass

    bg.add_task(run)
    return job


class ImageByBaseUpload(BaseModel):
    images_dir: str
    bases_depth: int = 1  # 1 or 2
    bases: Optional[List[str]] = None
    limit_bases: Optional[int] = None
    offset_bases: int = 0
    limit_files_per_base: Optional[int] = None
    one_level: bool = False
    only_empty_products: bool = False
    product_only: bool = False
    link_to_variant: bool = False
    alt_from: str = "none"
    delay: float = 0.5


@app.post("/jobs/images/by-base/upload", response_model=Job)
def create_images_by_base_upload(req: ImageByBaseUpload, bg: BackgroundTasks):
    job_id = uuid.uuid4().hex
    job = Job(
        id=job_id,
        kind="images/by-base/upload",
        status=JobStatus.queued,
        created_at=datetime.utcnow(),
        params=req.model_dump(),
    )
    JOBS[job_id] = job
    try:
        db.add_job(job.model_dump())
    except Exception:
        pass

    def run():
        j = JOBS[job_id]
        j.status = JobStatus.running
        j.started_at = datetime.utcnow()
        uploaded = skipped = errors = 0
        try:
            cfg = _get_shopify_cfg()
            session = sc.build_session(cfg)
            images_root = Path(req.images_dir)
            products = sc.fetch_all_products_with_variants(session, cfg)
            # Discover base folders
            bases: List[Path] = []
            sku_name_re = __import__("re").compile(r"^[A-Za-z0-9-_]+$")
            if req.bases_depth == 1:
                bases = [d for d in images_root.iterdir() if d.is_dir() and sku_name_re.match(d.name or "")]
            else:
                for cat in images_root.iterdir():
                    if not cat.is_dir():
                        continue
                    for d in cat.iterdir():
                        if d.is_dir() and sku_name_re.match(d.name or ""):
                            bases.append(d)
            if req.bases:
                wanted = set(req.bases)
                bases = [d for d in bases if d.name in wanted]
            bases.sort(key=lambda p: p.name)
            if req.offset_bases and req.offset_bases > 0:
                bases = bases[req.offset_bases :]
            if req.limit_bases and req.limit_bases > 0:
                bases = bases[: req.limit_bases]
            # Process each base folder
            for folder in bases:
                base = folder.name
                candidates = [p for p in products if any((sku or "").startswith(base) for sku in p["variant_skus"])]
                if not candidates:
                    continue
                if len(candidates) > 1:
                    narrowed = [p for p in candidates if base in {base_from_variant_sku(s) for s in p["variant_skus"]}]
                    if len(narrowed) == 1:
                        candidates = narrowed
                    else:
                        counts = []
                        for p in candidates:
                            pid = int(p["product_id"])
                            imgs = sc.get_product_images(session, cfg, pid)
                            counts.append((pid, len(imgs)))
                        counts.sort(key=lambda t: t[1])
                        chosen_pid = counts[0][0]
                        candidates = [p for p in candidates if int(p["product_id"]) == chosen_pid]
                product_id = int(candidates[0]["product_id"])
                if req.only_empty_products:
                    existing = sc.get_product_images(session, cfg, product_id)
                    if existing:
                        skipped += 1
                        continue
                files = list_images_shallow(folder) if req.one_level else list_images(folder)
                if req.limit_files_per_base and req.limit_files_per_base > 0:
                    files = files[: req.limit_files_per_base]
                for path in files:
                    try:
                        alt_text = path.stem if req.alt_from == "stem" else None
                        image_b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
                        sc.upload_image_to_product(
                            session=session,
                            cfg=cfg,
                            product_id=product_id,
                            image_b64=image_b64,
                            filename=path.name,
                            alt_text=alt_text,
                            variant_id=None if req.product_only or not req.link_to_variant else None,
                        )
                        uploaded += 1
                        if req.delay > 0:
                            time.sleep(req.delay)
                    except Exception:
                        errors += 1
            out = RESULTS / f"{job_id}.json"
            out.write_text(__import__("json").dumps({
                "summary": {"uploaded": uploaded, "errors": errors, "skipped": skipped},
                "bases_processed": len(bases),
            }, indent=2))
            j.counters = {"uploaded": uploaded, "errors": errors, "skipped": skipped}
            j.result_path = str(out)
            j.status = JobStatus.succeeded if errors == 0 else JobStatus.failed
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        except HTTPException as e:
            j.status = JobStatus.failed
            j.error = str(e.detail)
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        except Exception as e:
            j.status = JobStatus.failed
            j.error = str(e)
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        finally:
            j.finished_at = datetime.utcnow()
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass

    bg.add_task(run)
    return job


@app.post("/jobs/images/broadcast", response_model=Job)
async def create_broadcast_image_job(
    file: UploadFile = File(...),
    alt_text: Optional[str] = Form(None),
    product_ids: Optional[str] = Form(None),  # comma-separated ints
    limit: Optional[int] = Form(None),
    skip_if_alt_exists: bool = Form(False),
    delay: float = Form(0.5),
    bg: BackgroundTasks = None,
):
    job_id = uuid.uuid4().hex
    dest = UPLOADS / f"{job_id}_{file.filename}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    job = Job(
        id=job_id,
        kind="images/broadcast",
        status=JobStatus.queued,
        created_at=datetime.utcnow(),
        params={"filename": file.filename, "alt_text": alt_text, "product_ids": product_ids, "limit": limit, "skip_if_alt_exists": skip_if_alt_exists, "delay": delay},
    )
    JOBS[job_id] = job
    try:
        db.add_job(job.model_dump())
    except Exception:
        pass

    def run():
        j = JOBS[job_id]
        j.status = JobStatus.running
        j.started_at = datetime.utcnow()
        uploaded = skipped = errors = 0
        try:
            cfg = _get_shopify_cfg()
            session = sc.build_session(cfg)
            targets: List[int]
            if product_ids:
                targets = [int(x) for x in (product_ids or '').split(',') if x.strip().isdigit()]
            else:
                products = sc.fetch_all_products_with_variants(session, cfg)
                targets = sorted({int(p.get("product_id")) for p in products if p.get("product_id")})
            if limit and int(limit) > 0:
                targets = targets[: int(limit)]
            image_b64 = base64.b64encode(dest.read_bytes()).decode("utf-8")
            alt = alt_text or Path(dest).stem
            for pid in targets:
                try:
                    if skip_if_alt_exists and alt:
                        existing = sc.get_product_images(session, cfg, pid)
                        if any((img.get("alt") or "") == alt for img in existing):
                            skipped += 1
                            continue
                    sc.upload_image_to_product(session, cfg, pid, image_b64, dest.name, alt_text=alt, variant_id=None)
                    uploaded += 1
                    if delay and delay > 0:
                        time.sleep(delay)
                except Exception:
                    errors += 1
            out = RESULTS / f"{job_id}.json"
            out.write_text(__import__("json").dumps({
                "summary": {"uploaded": uploaded, "errors": errors, "skipped": skipped},
                "targets": len(targets),
            }, indent=2))
            j.counters = {"uploaded": uploaded, "errors": errors, "skipped": skipped}
            j.result_path = str(out)
            j.status = JobStatus.succeeded if errors == 0 else JobStatus.failed
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        except HTTPException as e:
            j.status = JobStatus.failed
            j.error = str(e.detail)
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        except Exception as e:
            j.status = JobStatus.failed
            j.error = str(e)
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass
        finally:
            j.finished_at = datetime.utcnow()
            try:
                db.update_job(j.model_dump())
            except Exception:
                pass

    bg.add_task(run)
    return job
