from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
from . import store

STAFF_KEY = os.getenv("ADMITCREW_STAFF_KEY", "replace-with-private-staff-secret")
N8N_KEY = os.getenv("ADMITCREW_N8N_KEY", "replace-with-private-n8n-secret")
UPLOAD_DIR = Path(os.getenv("ADMITCREW_UPLOAD_DIR", str(ROOT / "uploads")))
UPLOAD_LIMIT = 8 * 1024 * 1024

app = FastAPI(title="AdmitCrew API", version="2.0.0", description="Supabase-backed API for the AdmitCrew admissions team.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"], allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-Staff-Key", "X-N8N-Key", "Authorization"])

def now(): return datetime.now(timezone.utc).isoformat()

def staff_auth(x_staff_key: str = Header(default="")):
    if not STAFF_KEY or STAFF_KEY.startswith("replace-") or not secrets.compare_digest(x_staff_key, STAFF_KEY):
        raise HTTPException(401, "Valid staff key required. Configure ADMITCREW_STAFF_KEY in .env.")

def n8n_auth(x_n8n_key: str = Header(default="")):
    if not N8N_KEY or N8N_KEY.startswith("replace-") or not secrets.compare_digest(x_n8n_key, N8N_KEY):
        raise HTTPException(401, "Valid n8n key required. Configure ADMITCREW_N8N_KEY in .env.")

def student_token(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    if len(token) < 24: raise HTTPException(401, "Student session token required.")
    return token

def normalize_phone(phone: str):
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7: raise HTTPException(422, "Enter a valid phone number.")
    return digits

async def audit(actor, action, entity, entity_id=None, detail=None):
    await store.insert("audit_log", {"actor":actor,"action":action,"entity_type":entity,"entity_id":entity_id,"details":json.dumps(detail or {},ensure_ascii=False),"created_at":now()})

def program_dict(row):
    d=dict(row)
    raw=d.get("documents_needed") or "[]"
    try: d["documents"] = json.loads(raw) if isinstance(raw,str) else raw
    except Exception: d["documents"] = [x.strip() for x in str(raw).split(",") if x.strip()]
    d["is_published"] = bool(d.pop("active",False))
    d["source_note"] = "Practice sample—not a real offer" if d.get("is_demo") else "Office-provided practice data"
    return d

class ProgramIn(BaseModel):
    university: str = Field(min_length=2,max_length=180)
    country: str = Field(min_length=2,max_length=80)
    program: str = Field(min_length=2,max_length=180)
    annual_fee: str = Field(min_length=1,max_length=120)
    deadline: str = Field(min_length=4,max_length=40)
    min_marks: str = Field(min_length=1,max_length=20)
    min_ielts: str = Field(min_length=1,max_length=20)
    documents: list[str] = Field(default_factory=list)
    is_published: bool = True
    source_note: str = "Office-provided"

class LeadIn(BaseModel):
    name: str = Field(min_length=2,max_length=120)
    phone: str = Field(min_length=7,max_length=40)
    country: Optional[str] = None
    marks: Optional[str] = None
    ielts: Optional[str] = None
    budget: Optional[str] = None
    access_token: Optional[str] = None

class ChatIn(BaseModel):
    phone: str
    message: str = Field(min_length=1,max_length=5000)
    name: Optional[str] = None
    country: Optional[str] = None
    marks: Optional[str] = None
    ielts: Optional[str] = None
    budget: Optional[str] = None
    access_token: Optional[str] = None

class AgentReply(BaseModel):
    chat_id: int
    reply: str = Field(min_length=1,max_length=5000)
    needs_staff: bool = False
    source_program_ids: list[int] = Field(default_factory=list)

class DocReview(BaseModel):
    document_type: str
    name_on_document: Optional[str] = None
    expiry_date: Optional[str] = None
    marks: Optional[str] = None
    ielts_score: Optional[str] = None
    notes: Optional[str] = None

class AgentDocReview(BaseModel):
    name_on_document: Optional[str] = None
    expiry_date: Optional[str] = None
    marks: Optional[str] = None
    ielts_score: Optional[str] = None
    notes: Optional[str] = None

class DraftIn(BaseModel):
    lead_id: int
    body: str = Field(min_length=1,max_length=3000)
    channel: str = "website"
    kind: str = "follow_up"

@app.get("/health")
async def health():
    configured=bool(store.SUPABASE_URL and store.SUPABASE_SECRET_KEY and not store.SUPABASE_SECRET_KEY.startswith("replace-"))
    return {"status":"ok" if configured else "needs_configuration","service":"admitcrew-api","database":"supabase" if configured else "not_configured","project_url":store.SUPABASE_URL or None}

async def fetch_programs(search=None,country=None,include_unpublished=False):
    params={"order":"country.asc,university.asc,program.asc"}
    if not include_unpublished: params["active"]="eq.true"
    if country: params["country"]=f"ilike.{country}"
    if search:
        term=search.replace("%"," ").replace("_"," ").strip()
        if term: params["or"]=f"(university.ilike.*{term}*,program.ilike.*{term}*,country.ilike.*{term}*)"
    rows=await store.select("programs",params=params)
    return [program_dict(x) for x in rows]

@app.get("/api/public/programs")
async def public_programs(search:Optional[str]=None,country:Optional[str]=None): return await fetch_programs(search,country)

@app.get("/api/programs",dependencies=[Depends(staff_auth)])
async def staff_programs(search:Optional[str]=None,country:Optional[str]=None,include_unpublished:bool=True): return await fetch_programs(search,country,include_unpublished)

def program_row(payload):
    d=payload.model_dump()
    return {"university":d["university"],"country":d["country"],"program":d["program"],"annual_fee":d["annual_fee"],"deadline":d["deadline"],"min_marks":d["min_marks"],"min_ielts":d["min_ielts"],"documents_needed":json.dumps(d["documents"]),"active":d["is_published"],"is_demo":"practice" in d["source_note"].lower() or "demo" in d["source_note"].lower(),"created_at":now()}

@app.post("/api/staff/programs",dependencies=[Depends(staff_auth)],status_code=201)
async def create_program(payload:ProgramIn):
    row=await store.insert("programs",program_row(payload)); await audit("staff","create","program",row.get("id"),payload.model_dump()); return program_dict(row)

@app.patch("/api/staff/programs/{program_id}",dependencies=[Depends(staff_auth)])
async def update_program(program_id:int,payload:dict):
    allowed={"university","country","program","annual_fee","deadline","min_marks","min_ielts","documents","is_published","source_note"}
    changes={k:v for k,v in payload.items() if k in allowed}
    mapped={}
    for k,v in changes.items():
        if k=="documents": mapped["documents_needed"]=json.dumps(v)
        elif k=="is_published": mapped["active"]=bool(v)
        elif k=="source_note": mapped["is_demo"]="practice" in str(v).lower() or "demo" in str(v).lower()
        else: mapped[k]=v
    if not mapped: raise HTTPException(400,"No supported fields provided.")
    rows=await store.patch("programs",{"id":f"eq.{program_id}"},mapped)
    if not rows: raise HTTPException(404,"Program not found.")
    await audit("staff","update","program",program_id,changes); return program_dict(rows[0])

@app.delete("/api/staff/programs/{program_id}",dependencies=[Depends(staff_auth)])
async def archive_program(program_id:int):
    rows=await store.patch("programs",{"id":f"eq.{program_id}"},{"active":False})
    if not rows: raise HTTPException(404,"Program not found.")
    await audit("staff","archive","program",program_id); return {"archived":True,"program_id":program_id}

@app.post("/api/staff/programs/import-csv",dependencies=[Depends(staff_auth)])
async def import_programs(file:UploadFile=File(...)):
    if not file.filename.lower().endswith(".csv"): raise HTTPException(415,"Upload a CSV file.")
    raw=await file.read(2_000_001)
    if len(raw)>2_000_000: raise HTTPException(413,"CSV is too large.")
    try: records=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    except Exception as exc: raise HTTPException(400,"Could not read CSV.") from exc
    needed={"university","country","program","annual_fee","deadline","min_marks","min_ielts","documents"}
    if not records or not needed.issubset(records[0]): raise HTTPException(422,"CSV headers required: "+", ".join(sorted(needed)))
    rows=[]
    for r in records:
        rows.append({"university":r["university"],"country":r["country"],"program":r["program"],"annual_fee":r["annual_fee"],"deadline":r["deadline"],"min_marks":r["min_marks"],"min_ielts":r["min_ielts"],"documents_needed":json.dumps([x.strip() for x in r["documents"].split("|") if x.strip()]),"active":r.get("is_published","true").lower() not in {"false","0","no"},"is_demo":"practice" in (r.get("source_note") or "").lower(),"created_at":now()})
    result=await store.request("POST","programs",body=rows,prefer="return=representation")
    await audit("staff","import_csv","programs",None,{"count":len(result),"filename":file.filename})
    return {"imported":len(result)}

async def find_lead_by_phone(phone):
    norm=normalize_phone(phone)
    rows=await store.select("leads",params={"select":"*","phone":f"eq.{norm}","limit":"1"})
    if rows:return rows[0]
    # Legacy phone spellings are normalized by the additive migration; this fallback handles any future formatting drift.
    rows=await store.select("leads",params={"select":"*","limit":"500"})
    for lead in rows:
        if normalize_phone(lead.get("phone") or "") == norm:return lead
    return None

async def upsert_lead(name,phone,country=None,marks=None,ielts=None,budget=None,token=None):
    phone=normalize_phone(phone); lead=await find_lead_by_phone(phone); created=False
    if lead:
        if token and not secrets.compare_digest(str(lead.get("access_token") or ""),token): raise HTTPException(403,"This phone number is linked to another student session.")
        # Do not disclose a pre-seeded lead's session token to a visitor who only knows their phone.
        changes={k:v for k,v in {"name":name,"country":country,"marks":marks,"ielts":ielts,"budget":budget,"updated_at":now()}.items() if v is not None and v!=""}
        if token and changes:
            updated=await store.patch("leads",{"id":f"eq.{lead['id']}"},changes); lead=updated[0] if updated else lead
    else:
        token=secrets.token_urlsafe(32)
        lead=await store.insert("leads",{"name":name or "New student","phone":phone,"country":country,"marks":marks,"ielts":ielts,"budget":budget,"access_token":token,"created_at":now(),"updated_at":now()})
        created=True
    return lead,created,token if created or token else None

@app.post("/api/public/leads",status_code=201)
async def save_lead(payload:LeadIn):
    lead,created,token=await upsert_lead(payload.name,payload.phone,payload.country,payload.marks,payload.ielts,payload.budget,payload.access_token)
    await audit("student","intake","lead",lead["id"],{"created":created})
    return {"lead":{"id":lead["id"],"name":lead.get("name"),"country":lead.get("country")},"created":created,"access_token":token,"message":"Your details have been saved."}

@app.post("/api/public/chat",status_code=201)
async def inbound_chat(payload:ChatIn):
    lead,created,token=await upsert_lead(payload.name,payload.phone,payload.country,payload.marks,payload.ielts,payload.budget,payload.access_token)
    if not token and not payload.access_token: raise HTTPException(401,"This lead already exists. Use its student session or contact staff to connect it.")
    if payload.access_token and not secrets.compare_digest(str(lead.get("access_token") or ""),payload.access_token): raise HTTPException(403,"Student session token is invalid.")
    row=await store.insert("chats",{"lead_id":lead["id"],"role":"student","body":payload.message,"created_at":now(),"workflow_status":"pending_agent","needs_staff":False,"source_program_ids":[]})
    await store.patch("leads",{"id":f"eq.{lead['id']}"},{"last_reply_at":now(),"updated_at":now()})
    await audit("student","send","chat",row.get("id"),{"lead_id":lead["id"]})
    return {"chat_id":row["id"],"lead_id":lead["id"],"created_lead":created,"status":"received","message":"Thanks. Your question has been received. A staff-reviewed reply will appear in your student inbox."}

@app.get("/api/public/conversation")
async def public_conversation(token:str=Depends(student_token)):
    leads=await store.select("leads",params={"access_token":f"eq.{token}","select":"id,name"})
    if not leads: raise HTTPException(401,"Student session not found.")
    lead=leads[0]
    chats=await store.select("chats",params={"lead_id":f"eq.{lead['id']}","select":"id,role,body,created_at,workflow_status","order":"created_at.asc"})
    safe=[m for m in chats if m.get("role")=="student" or (m.get("role")=="assistant" and m.get("workflow_status")=="sent")]
    reminders=await store.select("outbound_messages",params={"lead_id":f"eq.{lead['id']}","status":"eq.sent","message_type":"eq.follow_up","select":"id,body,created_at"})
    safe.extend({"id":m["id"],"role":"assistant","body":m["body"],"created_at":m["created_at"],"workflow_status":"sent"} for m in reminders)
    safe.sort(key=lambda x:x.get("created_at") or "")
    return {"student_name":lead.get("name"),"messages":safe}

@app.get("/api/staff/leads",dependencies=[Depends(staff_auth)])
async def list_leads(search:Optional[str]=None):
    rows=await store.select("leads",params={"order":"updated_at.desc","limit":"500"})
    if search: rows=[x for x in rows if search.lower() in (x.get("name") or "").lower() or search in (x.get("phone") or "")]
    return [{k:v for k,v in r.items() if k!="access_token"} for r in rows]

@app.get("/api/staff/leads/{lead_id}",dependencies=[Depends(staff_auth)])
async def lead_detail(lead_id:int):
    leads=await store.select("leads",params={"id":f"eq.{lead_id}","limit":"1"})
    if not leads: raise HTTPException(404,"Lead not found.")
    lead={k:v for k,v in leads[0].items() if k!="access_token"}
    chats=await store.select("chats",params={"lead_id":f"eq.{lead_id}","order":"created_at.asc"})
    docs=await store.select("document_reviews",params={"lead_id":f"eq.{lead_id}","order":"created_at.desc"})
    messages=await store.select("outbound_messages",params={"lead_id":f"eq.{lead_id}","order":"created_at.desc"})
    return {"lead":lead,"chats":chats,"documents":docs,"messages":messages}

@app.get("/api/n8n/inbox",dependencies=[Depends(n8n_auth)])
async def n8n_inbox():
    chats=await store.select("chats",params={"role":"eq.student","workflow_status":"eq.pending_agent","order":"created_at.asc","limit":"100"})
    published=await fetch_programs()
    result=[]
    for chat in chats:
        leads=await store.select("leads",params={"id":f"eq.{chat['lead_id']}","select":"id,name,phone,country,marks,ielts,budget","limit":"1"})
        if leads: result.append({**chat,**leads[0],"published_programs":published})
    return result

@app.get("/api/n8n/programs",dependencies=[Depends(n8n_auth)])
async def n8n_program_lookup(search:Optional[str]=None,country:Optional[str]=None): return await fetch_programs(search,country)

@app.post("/api/n8n/replies",dependencies=[Depends(n8n_auth)],status_code=201)
async def n8n_reply(payload:AgentReply):
    rows=await store.select("chats",params={"id":f"eq.{payload.chat_id}","role":"eq.student","limit":"1"})
    if not rows: raise HTTPException(404,"Student chat not found.")
    inbound=rows[0]
    if inbound.get("workflow_status")!="pending_agent": raise HTTPException(409,"This chat has already been processed.")
    draft=await store.insert("chats",{"lead_id":inbound["lead_id"],"role":"assistant","body":payload.reply,"created_at":now(),"workflow_status":"pending_approval","needs_staff":payload.needs_staff,"source_program_ids":payload.source_program_ids})
    await store.patch("chats",{"id":f"eq.{payload.chat_id}"},{"workflow_status":"awaiting_approval"})
    msg=await store.insert("outbound_messages",{"lead_id":inbound["lead_id"],"chat_id":draft["id"],"body":payload.reply,"status":"pending_approval","event_key":str(uuid.uuid4()),"message_type":"chat_reply","channel":"website","created_at":now()})
    await audit("n8n","draft","chat_reply",msg.get("id"),{"chat_id":draft.get("id"),"program_ids":payload.source_program_ids,"needs_staff":payload.needs_staff})
    return {"message_id":msg["id"],"draft_chat_id":draft["id"],"status":"pending_approval","sent":False}

async def quiet_leads(days_quiet:int):
    cutoff=datetime.now(timezone.utc)-timedelta(days=max(1,days_quiet))
    leads=await store.select("leads",params={"select":"id,name,phone,country,last_reply_at","order":"last_reply_at.asc","limit":"500"})
    result=[]
    for lead in leads:
        value=lead.get("last_reply_at")
        if not value: continue
        try:
            parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
            if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
            if parsed>cutoff: continue
        except ValueError: continue
        existing=await store.select("outbound_messages",params={"lead_id":f"eq.{lead['id']}","message_type":"eq.follow_up","status":"in.(pending_approval,approved)","select":"id","limit":"1"})
        if not existing: result.append(lead)
    return result

@app.get("/api/n8n/quiet-leads",dependencies=[Depends(n8n_auth)])
async def n8n_quiet_leads(days_quiet:int=3): return await quiet_leads(days_quiet)

async def create_reminder(lead):
    first=(lead.get("name") or "there").split()[0]
    body=f"Hi {first}, just checking in on your study abroad plans. Reply here if you would like help reviewing suitable programs or next steps."
    msg=await store.insert("outbound_messages",{"lead_id":lead["id"],"body":body,"status":"pending_approval","event_key":str(uuid.uuid4()),"message_type":"follow_up","channel":"website","created_at":now()})
    await audit("reminder_agent","draft","outbound_message",msg.get("id"),{"lead_id":lead["id"]})
    return msg

@app.post("/api/n8n/reminders/draft",dependencies=[Depends(n8n_auth)],status_code=201)
async def n8n_draft_reminder(payload:DraftIn):
    msg=await store.insert("outbound_messages",{"lead_id":payload.lead_id,"body":payload.body,"status":"pending_approval","event_key":str(uuid.uuid4()),"message_type":payload.kind,"channel":payload.channel,"created_at":now()})
    await audit("reminder_agent","draft","outbound_message",msg.get("id"),{"lead_id":payload.lead_id})
    return {"message_id":msg["id"],"status":msg["status"],"sent":False}

@app.post("/api/staff/reminders/run",dependencies=[Depends(staff_auth)])
async def run_reminders(days_quiet:int=3):
    leads=await quiet_leads(days_quiet); drafted=[]
    for lead in leads: drafted.append(await create_reminder(lead))
    return {"drafted":len(drafted),"message_ids":[x["id"] for x in drafted],"sent":0}

@app.get("/api/staff/messages",dependencies=[Depends(staff_auth)])
async def staff_messages(status:Optional[str]=None):
    params={"order":"created_at.desc","limit":"500"}
    if status: params["status"]=f"eq.{status}"
    messages=await store.select("outbound_messages",params=params)
    leads=await store.select("leads",params={"select":"id,name,phone","limit":"500"}); byid={x["id"]:x for x in leads}
    return [{**m,"student_name":byid.get(m["lead_id"],{}).get("name"),"phone":byid.get(m["lead_id"],{}).get("phone"),"kind":m.get("message_type","chat_reply")} for m in messages]

@app.post("/api/staff/messages/{message_id}/approve",dependencies=[Depends(staff_auth)])
async def approve_message(message_id:int,approver:str="staff"):
    rows=await store.patch("outbound_messages",{"id":f"eq.{message_id}","status":"eq.pending_approval"},{"status":"approved","approved_by":approver,"approved_at":now()})
    if not rows:
        old=await store.select("outbound_messages",params={"id":f"eq.{message_id}","limit":"1"})
        if not old: raise HTTPException(404,"Message not found.")
        raise HTTPException(409,"Only pending messages can be approved.")
    await audit(approver,"approve","outbound_message",message_id)
    return {"message_id":message_id,"status":"approved","sent":False}

@app.get("/api/n8n/approved-messages",dependencies=[Depends(n8n_auth)])
async def approved_messages():
    rows=await store.select("outbound_messages",params={"status":"eq.approved","order":"approved_at.asc","limit":"100"})
    leads=await store.select("leads",params={"select":"id,name,phone","limit":"500"}); byid={x["id"]:x for x in leads}
    return [{**m,"student_name":byid.get(m["lead_id"],{}).get("name"),"phone":byid.get(m["lead_id"],{}).get("phone")} for m in rows]

@app.post("/api/n8n/messages/{message_id}/mark-sent",dependencies=[Depends(n8n_auth)])
async def mark_sent(message_id:int):
    old=await store.select("outbound_messages",params={"id":f"eq.{message_id}","status":"eq.approved","limit":"1"})
    if not old:
        anyrow=await store.select("outbound_messages",params={"id":f"eq.{message_id}","limit":"1"})
        if not anyrow: raise HTTPException(404,"Message not found.")
        raise HTTPException(409,"Message is not approved or was already sent.")
    msg=old[0]
    updated=await store.patch("outbound_messages",{"id":f"eq.{message_id}","status":"eq.approved"},{"status":"sent","sent_at":now()})
    if not updated: raise HTTPException(409,"Message was already processed.")
    if msg.get("chat_id"):
        await store.patch("chats",{"id":f"eq.{msg['chat_id']}"},{"workflow_status":"sent"})
    if msg.get("channel")=="website":
        await store.insert("student_inbox",{"message_id":msg["id"],"lead_id":msg["lead_id"],"body":msg["body"],"created_at":now()})
    await audit("n8n","mark_sent","outbound_message",message_id)
    return {"message_id":message_id,"status":"sent"}

@app.post("/api/staff/documents/{lead_id}",dependencies=[Depends(staff_auth)],status_code=201)
async def upload_document(lead_id:int,document_type:str=Form(...),file:UploadFile=File(...),review:Optional[str]=Form(None)):
    leads=await store.select("leads",params={"id":f"eq.{lead_id}","select":"id,name","limit":"1"})
    if not leads: raise HTTPException(404,"Lead not found.")
    suffix=Path(file.filename or "upload.bin").suffix.lower()
    if suffix not in {".pdf",".png",".jpg",".jpeg",".webp"}: raise HTTPException(415,"Only PDF or image files are accepted.")
    data=await file.read(UPLOAD_LIMIT+1)
    if len(data)>UPLOAD_LIMIT: raise HTTPException(413,"Document must be 8 MB or smaller.")
    if not (data[:4].startswith(b"%PDF") or data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8") or data.startswith(b"RIFF")): raise HTTPException(415,"File does not look like a supported PDF or image.")
    UPLOAD_DIR.mkdir(parents=True,exist_ok=True); stored=f"{lead_id}_{secrets.token_hex(8)}{suffix}"; path=UPLOAD_DIR/stored; path.write_bytes(data)
    parsed=None
    if review:
        try: parsed=DocReview.model_validate_json(review)
        except Exception as exc: path.unlink(missing_ok=True); raise HTTPException(422,"review must be valid structured review JSON.") from exc
    status="pending_ocr"; reason="Awaiting document extraction"; extracted_name=None; expiry=None; score=None; ielts=None; notes=None
    if parsed:
        if parsed.document_type.lower()!=document_type.strip().lower(): path.unlink(missing_ok=True); raise HTTPException(422,"document type does not match review fields.")
        extracted_name=parsed.name_on_document; expiry=parsed.expiry_date; score=parsed.marks or parsed.ielts_score; ielts=parsed.ielts_score; notes=parsed.notes; status="ok"; reason=""
        if not extracted_name: status="needs_review"; reason="document name missing or unreadable"
        elif re.sub(r"\s+"," ",extracted_name.strip().lower())!=re.sub(r"\s+"," ",leads[0]["name"].strip().lower()): status="problem"; reason="name doesn't match"
        if expiry:
            try:
                if date.fromisoformat(expiry)<date.today(): status="problem"; reason="expired"
            except ValueError: status="needs_review"; reason="expiry date could not be verified"
        elif document_type.lower()=="passport": status="needs_review"; reason="passport expiry date missing"
        if document_type.lower() in {"transcript","academic transcript"} and not score: status="needs_review"; reason="transcript marks missing"
        if document_type.lower() in {"ielts","ielts result"} and not ielts: status="needs_review"; reason="IELTS score missing"
    row=await store.insert("document_reviews",{"lead_id":lead_id,"document_type":document_type,"filename":file.filename,"storage_path":str(path),"extracted_name":extracted_name,"expiry_date":expiry,"score":score,"extracted_ielts":ielts,"status":status,"reason":reason,"created_at":now()})
    await audit("staff","upload_document","document_review",row.get("id"),{"status":status,"reason":reason})
    return {"document_id":row["id"],"status":status,"reason":reason,"filename":file.filename}

@app.get("/api/staff/documents",dependencies=[Depends(staff_auth)])
async def list_documents():
    rows=await store.select("document_reviews",params={"order":"created_at.desc","limit":"500"}); leads=await store.select("leads",params={"select":"id,name,phone","limit":"500"}); byid={x["id"]:x for x in leads}
    return [{**x,"student_name":byid.get(x["lead_id"],{}).get("name"),"phone":byid.get(x["lead_id"],{}).get("phone")} for x in rows]

@app.get("/api/n8n/documents/pending",dependencies=[Depends(n8n_auth)])
async def pending_documents():
    docs=await store.select("document_reviews",params={"status":"eq.pending_ocr","order":"created_at.asc","limit":"50"}); leads=await store.select("leads",params={"select":"id,name","limit":"500"}); byid={x["id"]:x for x in leads}
    return [{**d,"student_name":byid.get(d["lead_id"],{}).get("name")} for d in docs]

@app.get("/api/n8n/documents/{document_id}/file",dependencies=[Depends(n8n_auth)])
async def n8n_document_file(document_id:int):
    rows=await store.select("document_reviews",params={"id":f"eq.{document_id}","limit":"1"})
    if not rows: raise HTTPException(404,"Document not found.")
    path=Path(rows[0].get("storage_path") or "")
    if not path.is_file() or UPLOAD_DIR.resolve() not in path.resolve().parents: raise HTTPException(404,"Stored document file is unavailable to this API instance.")
    return FileResponse(path,filename=rows[0].get("filename") or path.name)

@app.post("/api/n8n/documents/{document_id}/review",dependencies=[Depends(n8n_auth)])
async def n8n_document_review(document_id:int,payload:AgentDocReview):
    docs=await store.select("document_reviews",params={"id":f"eq.{document_id}","limit":"1"})
    if not docs: raise HTTPException(404,"Document not found.")
    doc=docs[0]; leads=await store.select("leads",params={"id":f"eq.{doc['lead_id']}","select":"id,name","limit":"1"})
    status="ok"; reason=""
    if not payload.name_on_document: status="needs_review"; reason="document name missing or unreadable"
    elif payload.name_on_document.strip().lower()!=leads[0]["name"].strip().lower(): status="problem"; reason="name doesn't match"
    if payload.expiry_date:
        try:
            if date.fromisoformat(payload.expiry_date)<date.today(): status="problem"; reason="expired"
        except ValueError: status="needs_review"; reason="expiry date could not be verified"
    elif doc["document_type"].lower()=="passport": status="needs_review"; reason="passport expiry date missing"
    if doc["document_type"].lower() in {"transcript","academic transcript"} and not payload.marks: status="needs_review"; reason="transcript marks missing"
    if doc["document_type"].lower() in {"ielts","ielts result"} and not payload.ielts_score: status="needs_review"; reason="IELTS score missing"
    updated=await store.patch("document_reviews",{"id":f"eq.{document_id}"},{"extracted_name":payload.name_on_document,"expiry_date":payload.expiry_date,"score":payload.marks or payload.ielts_score,"extracted_ielts":payload.ielts_score,"status":status,"reason":reason})
    await audit("n8n","review_document","document_review",document_id,{"status":status,"reason":reason})
    return {"document_id":document_id,"status":status,"reason":reason}

@app.get("/api/staff/dashboard",dependencies=[Depends(staff_auth)])
async def dashboard():
    programs=await store.select("programs",params={"active":"eq.true","select":"id"}); leads=await store.select("leads",params={"select":"id"}); chats=await store.select("chats",params={"role":"eq.student","workflow_status":"eq.pending_agent","select":"id"}); docs=await store.select("document_reviews",params={"status":"in.(problem,needs_review,pending_ocr)","select":"id"}); messages=await store.select("outbound_messages",params={"status":"eq.pending_approval","select":"id"}); sent=await store.select("outbound_messages",params={"status":"eq.sent","select":"id"})
    return {"leads":len(leads),"published_programs":len(programs),"pending_chats":len(chats),"documents_to_review":len(docs),"messages_waiting_approval":len(messages),"messages_sent":len(sent)}

@app.get("/api/staff/audit",dependencies=[Depends(staff_auth)])
async def audit_events(limit:int=100): return await store.select("audit_log",params={"order":"id.desc","limit":str(min(max(limit,1),500))})

app.mount("/",StaticFiles(directory=str(ROOT/"static"),html=True),name="frontend")
