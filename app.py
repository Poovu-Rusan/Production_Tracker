"""
Midwest Production Log — Flask Web Application
Roles: admin | hr | user  (custom roles supported)
Run: python app.py
"""
import sqlite3, json, io, os, socket
from datetime import datetime, date, timedelta
from functools import wraps
import numpy as np
import pandas as pd
from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, send_file, flash)

app = Flask(__name__)
app.secret_key = "midwest_prod_secret_2024_xK9mQ"
DB_NAME = os.path.join(os.path.dirname(__file__), "midwest_production.db")

# ─────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _add_col(c, table, col, defn):
    try: c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
    except: pass

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # USERS
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        emp_id TEXT DEFAULT '',
        full_name TEXT DEFAULT '',
        password TEXT DEFAULT '',
        pin TEXT DEFAULT '',
        role TEXT DEFAULT 'user',
        status TEXT DEFAULT 'active',
        department TEXT DEFAULT '',
        emp_type TEXT DEFAULT 'Coder',
        default_work_type TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    for col,defn in [
        ("emp_id","TEXT DEFAULT ''"),("department","TEXT DEFAULT ''"),
        ("emp_type","TEXT DEFAULT 'Coder'"),("default_work_type","TEXT DEFAULT ''"),
        ("created_at","TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),("pin","TEXT DEFAULT ''"),
    ]:
        _add_col(c,"users",col,defn)

    # PRODUCTION
    c.execute("""CREATE TABLE IF NOT EXISTS production (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        username TEXT,
        emp_id TEXT DEFAULT '',
        emp_name TEXT DEFAULT '',
        role TEXT DEFAULT '',
        work_type TEXT DEFAULT '',
        target REAL DEFAULT 0,
        production REAL DEFAULT 0,
        remarks TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT DEFAULT ''
    )""")
    for col,defn in [
        ("emp_id","TEXT DEFAULT ''"),("created_by","TEXT DEFAULT ''"),
    ]:
        _add_col(c,"production",col,defn)

    # WORK TYPES
    c.execute("""CREATE TABLE IF NOT EXISTS work_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        category TEXT DEFAULT 'General',
        is_active INTEGER DEFAULT 1
    )""")
    for wt,cat in [("Coding Review","Coder"),("Rebilling","Biller"),
                   ("Add Hold","Coder"),("Other Work","General")]:
        c.execute("INSERT OR IGNORE INTO work_types (name,category) VALUES (?,?)",(wt,cat))

    # TARGETS
    c.execute("""CREATE TABLE IF NOT EXISTS targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_type TEXT UNIQUE,
        target_value REAL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS date_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, target_date TEXT, work_type TEXT, target_value REAL DEFAULT 0,
        UNIQUE(username,target_date,work_type)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS common_date_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_date TEXT, work_type TEXT, target_value REAL DEFAULT 0,
        UNIQUE(target_date,work_type)
    )""")

    # CUSTOM ROLES
    c.execute("""CREATE TABLE IF NOT EXISTS custom_roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        label TEXT DEFAULT '',
        default_work_type TEXT DEFAULT ''
    )""")
    for nm,lbl,dwt in [("Coder","Coder","Coding Review"),("Biller","Biller","Rebilling")]:
        c.execute("INSERT OR IGNORE INTO custom_roles (name,label,default_work_type) VALUES (?,?,?)",(nm,lbl,dwt))

    # APP CONFIG
    c.execute("""CREATE TABLE IF NOT EXISTS app_config (
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT ''
    )""")
    for k,v in [("app_name","Midwest"),("app_subtitle","Production Log"),
                ("login_logo","📊"),("accent_color","#6366f1")]:
        c.execute("INSERT OR IGNORE INTO app_config (key,value) VALUES (?,?)",(k,v))

    # ACTIVITY LOG
    c.execute("""CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        username TEXT, action TEXT, detail TEXT
    )""")

    # Default admin
    if not c.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
        c.execute("""INSERT INTO users (username,emp_id,full_name,password,pin,role,status,emp_type)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  ("admin","ADM001","System Administrator","admin123","1234","admin","active","Admin"))

    conn.commit(); conn.close()

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def log_activity(action, detail=""):
    try:
        conn = get_conn()
        conn.execute("INSERT INTO activity_log (username,action,detail) VALUES (?,?,?)",
                     (session.get("username","?"), action, detail))
        conn.commit(); conn.close()
    except: pass

def safe_pct(prod, tgt):
    try:
        p,t = float(prod or 0), float(tgt or 0)
        return round((p/t*100),1) if t > 0 else 0.0
    except: return 0.0

def resolve_target(username, work_type, for_date):
    conn = get_conn()
    # Individual date target (highest priority)
    row = conn.execute(
        "SELECT target_value FROM date_targets WHERE username=? AND target_date=? AND work_type=?",
        (username, for_date, work_type)).fetchone()
    if row: conn.close(); return float(row[0])
    # Common date target
    row = conn.execute(
        "SELECT target_value FROM common_date_targets WHERE target_date=? AND work_type=?",
        (for_date, work_type)).fetchone()
    if row: conn.close(); return float(row[0])
    # Default target
    row = conn.execute("SELECT target_value FROM targets WHERE work_type=?", (work_type,)).fetchone()
    conn.close()
    return float(row[0]) if row else 0.0

def get_app_config():
    conn = get_conn()
    rows = conn.execute("SELECT key,value FROM app_config").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

def get_work_types(active_only=True):
    conn = get_conn()
    q = "SELECT name FROM work_types WHERE is_active=1 ORDER BY name" if active_only else "SELECT name FROM work_types ORDER BY name"
    wts = [r[0] for r in conn.execute(q).fetchall()]
    conn.close()
    return wts or ["Coding Review","Rebilling","Add Hold","Other Work"]

def rows_to_list(rows): return [dict(r) for r in rows]

def load_production(username=None):
    """Load production records, enriched with emp_id from users table."""
    conn = get_conn()
    me, urole = session.get("username"), session.get("role")
    base = """
        SELECT p.*, COALESCE(p.emp_id, u.emp_id, '') AS emp_id_resolved
        FROM production p
        LEFT JOIN users u ON p.username = u.username
    """
    if urole in ("admin","hr"):
        if username:
            rows = conn.execute(base + " WHERE p.username=? ORDER BY p.date DESC,p.id DESC",(username,)).fetchall()
        else:
            rows = conn.execute(base + " ORDER BY p.date DESC,p.id DESC").fetchall()
    else:
        rows = conn.execute(base + " WHERE p.username=? ORDER BY p.date DESC,p.id DESC",(me,)).fetchall()
    conn.close()
    data = rows_to_list(rows)
    for r in data:
        p = float(r.get("production") or 0)
        t = float(r.get("target") or 0)
        r["achievement_pct"] = round((p/t*100),1) if t > 0 else 0.0
        # Use resolved emp_id
        r["emp_id"] = r.get("emp_id_resolved") or r.get("emp_id","")
    return data

def recalc_targets(data):
    """Re-resolve targets for all records (used after date-target changes)."""
    conn = get_conn()
    for r in data:
        tgt = resolve_target(r["username"], r["work_type"], r["date"])
        r["target"] = tgt
        p = float(r.get("production") or 0)
        r["achievement_pct"] = safe_pct(p, tgt)
    conn.close()
    return data

def login_required(f):
    @wraps(f)
    def dec(*a,**k):
        if not session.get("logged_in"): return redirect(url_for("login"))
        return f(*a,**k)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a,**k):
        if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
        return f(*a,**k)
    return dec

# ─────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────
@app.route("/", methods=["GET","POST"])
def login():
    if session.get("logged_in"): return redirect(url_for("dashboard"))
    cfg = get_app_config()
    error = None
    if request.method == "POST":
        action = request.form.get("action","login")
        if action == "login":
            u = request.form.get("username","").strip()
            p = request.form.get("password","").strip()
            conn = get_conn()
            user = conn.execute(
                "SELECT * FROM users WHERE username=? AND password=? AND status='active'",(u,p)).fetchone()
            conn.close()
            if user:
                session.update({"logged_in":True,"username":user["username"],
                    "full_name":user["full_name"] or user["username"],
                    "role":user["role"],"emp_type":user["emp_type"] or "Coder",
                    "emp_id":user["emp_id"] or ""})
                log_activity("LOGIN")
                return redirect(url_for("dashboard"))
            error = "Invalid username or password."
        elif action == "reset":
            u,pin,np_ = (request.form.get(x,"").strip() for x in ["r_username","r_pin","r_newpass"])
            conn = get_conn()
            row = conn.execute("SELECT 1 FROM users WHERE username=? AND pin=?",(u,pin)).fetchone()
            if row:
                conn.execute("UPDATE users SET password=? WHERE username=?",(np_,u))
                conn.commit()
                flash("Password reset successfully.","success")
            else:
                flash("Invalid username or PIN.","error")
            conn.close()
    return render_template("login.html", error=error, cfg=cfg)

@app.route("/logout")
def logout():
    log_activity("LOGOUT"); session.clear()
    return redirect(url_for("login"))

# ─────────────────────────────────────────────────────────────
# PAGES
# ─────────────────────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard(): return render_template("base.html", page="dashboard")

@app.route("/add-production")
@login_required
def add_production():
    return render_template("base.html", page="add_production")

@app.route("/reports")
@login_required
def reports(): return render_template("base.html", page="reports")

@app.route("/analytics")
@login_required
def analytics(): return render_template("base.html", page="analytics")

@app.route("/admin")
@login_required
def admin_panel():
    if session.get("role") != "admin": return redirect(url_for("dashboard"))
    return render_template("base.html", page="admin")

# ─────────────────────────────────────────────────────────────
# API — SESSION / CONFIG
# ─────────────────────────────────────────────────────────────
@app.route("/api/session")
def api_session():
    return jsonify({
        "logged_in": session.get("logged_in", False),
        "username":  session.get("username",""),
        "full_name": session.get("full_name",""),
        "role":      session.get("role",""),
        "emp_type":  session.get("emp_type","Coder"),
        "emp_id":    session.get("emp_id",""),
    })

@app.route("/api/app-config", methods=["GET","POST"])
@login_required
def api_app_config():
    conn = get_conn()
    if request.method == "POST":
        if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
        d = request.json
        for k,v in d.items():
            conn.execute("INSERT OR REPLACE INTO app_config (key,value) VALUES (?,?)",(k,str(v)))
        conn.commit(); conn.close()
        log_activity("UPDATE_CONFIG", str(list(d.keys())))
        return jsonify({"ok":True})
    rows = conn.execute("SELECT key,value FROM app_config").fetchall()
    conn.close()
    return jsonify({r["key"]:r["value"] for r in rows})

# ─────────────────────────────────────────────────────────────
# API — CUSTOM ROLES
# ─────────────────────────────────────────────────────────────
@app.route("/api/custom-roles", methods=["GET","POST","DELETE"])
@login_required
def api_custom_roles():
    conn = get_conn()
    if request.method == "POST":
        if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
        d = request.json
        try:
            conn.execute("INSERT OR REPLACE INTO custom_roles (name,label,default_work_type) VALUES (?,?,?)",
                         (d["name"],d.get("label",d["name"]),d.get("default_work_type","")))
            conn.commit()
            return jsonify({"ok":True})
        except Exception as e:
            return jsonify({"error":str(e)}),400
        finally: conn.close()
    elif request.method == "DELETE":
        if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
        d = request.json
        conn.execute("DELETE FROM custom_roles WHERE name=?",(d["name"],))
        conn.commit(); conn.close()
        return jsonify({"ok":True})
    rows = rows_to_list(conn.execute("SELECT * FROM custom_roles ORDER BY name").fetchall())
    conn.close()
    return jsonify(rows)

# ─────────────────────────────────────────────────────────────
# API — DASHBOARD
# ─────────────────────────────────────────────────────────────
@app.route("/api/dashboard-data")
@login_required
def api_dashboard_data():
    username_filter = request.args.get("username")
    data = load_production(username=username_filter)
    today = date.today().isoformat()
    role  = session.get("role")

    total_prod = sum(r["production"] for r in data)
    total_tgt  = sum(r["target"]     for r in data)
    today_data = [r for r in data if r["date"]==today]
    today_prod = sum(r["production"] for r in today_data)
    today_tgt  = sum(r["target"]     for r in today_data)

    result = {
        "kpis": {
            "total_prod": int(total_prod), "total_tgt": int(total_tgt),
            "total_ach":  safe_pct(total_prod,total_tgt),
            "today_prod": int(today_prod),  "today_tgt": int(today_tgt),
            "today_ach":  safe_pct(today_prod,today_tgt),
            "entries":    len(data),
        },
        "recent": data[:30], "role": role,
    }

    from collections import defaultdict
    if role in ("admin","hr"):
        rg = defaultdict(lambda:{"Production":0,"Target":0,"Entries":0})
        for r in data:
            k=r.get("role","Unknown"); rg[k]["Production"]+=r["production"]; rg[k]["Target"]+=r["target"]; rg[k]["Entries"]+=1
        result["role_groups"] = [{"role":k,"Production":int(v["Production"]),"Target":int(v["Target"]),
            "Entries":v["Entries"],"Achievement%":safe_pct(v["Production"],v["Target"])} for k,v in rg.items()]

        eg = defaultdict(lambda:{"Production":0,"Target":0,"days":set(),"emp_id":""})
        for r in data:
            k=(r["username"],r.get("emp_name") or r["username"],r.get("role",""))
            eg[k]["Production"]+=r["production"]; eg[k]["Target"]+=r["target"]
            eg[k]["days"].add(r["date"]); eg[k]["emp_id"]=r.get("emp_id","")
        emp_list=[{"username":u,"emp_id":v["emp_id"],"emp_name":nm,"role":rl,
            "Production":int(v["Production"]),"Target":int(v["Target"]),
            "Days":len(v["days"]),"Achievement%":safe_pct(v["Production"],v["Target"])}
            for (u,nm,rl),v in eg.items()]
        emp_list.sort(key=lambda x:-x["Production"])
        result["emp_perf"] = emp_list

        # Load all users for filter dropdown
        conn = get_conn()
        result["all_users"] = rows_to_list(conn.execute(
            "SELECT username,full_name,emp_id FROM users WHERE status='active' ORDER BY full_name").fetchall())
        conn.close()
    else:
        wt_g = defaultdict(lambda:{"Production":0,"Target":0,"Entries":0})
        for r in data:
            k=r.get("work_type","Other"); wt_g[k]["Production"]+=r["production"]; wt_g[k]["Target"]+=r["target"]; wt_g[k]["Entries"]+=1
        dg = defaultdict(lambda:{"Production":0,"Target":0,"Entries":0})
        for r in data:
            dg[r["date"]]["Production"]+=r["production"]; dg[r["date"]]["Target"]+=r["target"]; dg[r["date"]]["Entries"]+=1
        result["wt_breakdown"]=[{"work_type":k,"Production":int(v["Production"]),"Target":int(v["Target"]),
            "Entries":v["Entries"],"Achievement%":safe_pct(v["Production"],v["Target"])} for k,v in wt_g.items()]
        result["daily"]=[{"date":d,"Production":int(v["Production"]),"Target":int(v["Target"]),
            "Entries":v["Entries"],"Achievement%":safe_pct(v["Production"],v["Target"])} for d,v in sorted(dg.items(),reverse=True)]
        result["unique_days"] = len(dg)
        # Leaderboard position for regular user
        all_data = load_production()  # all users' data for ranking
        emp_totals = defaultdict(lambda:{"Production":0,"Target":0,"emp_name":""})
        for r in all_data:
            k=r["username"]; emp_totals[k]["Production"]+=r["production"]; emp_totals[k]["Target"]+=r["target"]; emp_totals[k]["emp_name"]=r.get("emp_name","")
        ranked = sorted(emp_totals.items(), key=lambda x:-x[1]["Production"])
        my_rank = next((i+1 for i,(u,_) in enumerate(ranked) if u==session.get("username")), "-")
        result["my_rank"] = my_rank
        result["total_users"] = len(ranked)
    return jsonify(result)

# ─────────────────────────────────────────────────────────────
# API — PRODUCTION CRUD
# ─────────────────────────────────────────────────────────────
@app.route("/api/production", methods=["GET"])
@login_required
def api_get_production():
    username = request.args.get("username")
    return jsonify(load_production(username=username))

@app.route("/api/production", methods=["POST"])
@login_required
def api_add_production():
    d = request.json
    sel_user = d.get("username") if session.get("role") in ("admin","hr") else session["username"]
    date_str  = d.get("date", date.today().isoformat())
    work_type = d.get("work_type","")
    production= float(d.get("production",0))
    emp_role  = d.get("role","Coder")
    remarks   = d.get("remarks","")

    # ── Duplicate check: same user + date + work_type already exists
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM production WHERE username=? AND date=? AND work_type=?",
        (sel_user, date_str, work_type)).fetchone()
    if existing:
        conn.close()
        return jsonify({"error":f"Duplicate: an entry for {work_type} on {date_str} already exists for this user (ID #{existing[0]}). Edit it instead."}), 409

    tgt = resolve_target(sel_user, work_type, date_str)
    nm  = conn.execute("SELECT full_name,emp_id FROM users WHERE username=?",(sel_user,)).fetchone()
    emp_nm = nm["full_name"] if nm and nm["full_name"] else sel_user
    emp_id = nm["emp_id"]  if nm else ""

    conn.execute("""INSERT INTO production
        (date,username,emp_id,emp_name,role,work_type,target,production,remarks,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (date_str,sel_user,emp_id,emp_nm,emp_role,work_type,tgt,production,remarks,session["username"]))
    conn.commit(); conn.close()
    log_activity("ADD_PRODUCTION",f"user={sel_user} date={date_str} work={work_type} prod={production}")
    return jsonify({"ok":True,"target":tgt,"achievement":safe_pct(production,tgt),"emp_name":emp_nm,"emp_id":emp_id})

@app.route("/api/production/<int:pid>", methods=["PUT"])
@login_required
def api_edit_production(pid):
    if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
    d = request.json
    conn = get_conn()
    conn.execute("""UPDATE production
        SET date=?,emp_name=?,role=?,work_type=?,target=?,production=?,remarks=? WHERE id=?""",
        (d["date"],d["emp_name"],d["role"],d["work_type"],
         float(d["target"]),float(d["production"]),d.get("remarks",""),pid))
    conn.commit(); conn.close()
    log_activity("EDIT_ENTRY",f"id={pid}")
    return jsonify({"ok":True})

@app.route("/api/production/<int:pid>", methods=["DELETE"])
@login_required
def api_delete_production(pid):
    if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
    conn = get_conn()
    conn.execute("DELETE FROM production WHERE id=?",(pid,))
    conn.commit(); conn.close()
    log_activity("DELETE_ENTRY",f"id={pid}")
    return jsonify({"ok":True})

@app.route("/api/resolve-target")
@login_required
def api_resolve_target():
    u  = request.args.get("username") or session["username"]
    wt = request.args.get("work_type","")
    dt = request.args.get("date", date.today().isoformat())
    return jsonify({"target": resolve_target(u, wt, dt)})

# ─────────────────────────────────────────────────────────────
# API — USERS
# ─────────────────────────────────────────────────────────────
@app.route("/api/users", methods=["GET"])
@login_required
def api_users():
    conn = get_conn()
    rows = rows_to_list(conn.execute(
        "SELECT id,username,emp_id,full_name,role,emp_type,default_work_type,department,status,pin FROM users ORDER BY full_name").fetchall())
    conn.close()
    return jsonify(rows)

@app.route("/api/users", methods=["POST"])
@login_required
def api_create_user():
    if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
    d = request.json
    conn = get_conn()
    try:
        conn.execute("""INSERT INTO users
            (username,emp_id,full_name,password,pin,role,status,department,emp_type,default_work_type)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (d["username"],d.get("emp_id",""),d["full_name"],d["password"],
             d.get("pin",""),d.get("role","user"),"active",
             d.get("department",""),d.get("emp_type","Coder"),d.get("default_work_type","")))
        conn.commit()
        log_activity("CREATE_USER",d["username"])
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"error":str(e)}),400
    finally: conn.close()

@app.route("/api/users/<username>", methods=["PUT"])
@login_required
def api_update_user(username):
    if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
    d = request.json
    conn = get_conn()
    # Build dynamic SET clause
    allowed = ["emp_id","full_name","password","pin","role","status","department","emp_type","default_work_type"]
    sets = {k:v for k,v in d.items() if k in allowed}
    if sets:
        sql = "UPDATE users SET " + ",".join(f"{k}=?" for k in sets) + " WHERE username=?"
        conn.execute(sql, list(sets.values())+[username])
        # If emp_id changed, cascade to all production records for this user
        if "emp_id" in sets:
            conn.execute("UPDATE production SET emp_id=? WHERE username=?",
                         (sets["emp_id"], username))
        conn.commit()
    conn.close()
    log_activity("UPDATE_USER",f"{username} fields={list(sets.keys())}")
    return jsonify({"ok":True})

@app.route("/api/users/<username>", methods=["DELETE"])
@login_required
def api_delete_user(username):
    if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
    if username == "admin": return jsonify({"error":"Cannot delete default admin"}),400
    conn = get_conn()
    conn.execute("DELETE FROM users WHERE username=?",(username,))
    conn.commit(); conn.close()
    log_activity("DELETE_USER",username)
    return jsonify({"ok":True})

# ─────────────────────────────────────────────────────────────
# API — WORK TYPES
# ─────────────────────────────────────────────────────────────
@app.route("/api/work-types", methods=["GET"])
@login_required
def api_work_types():
    conn = get_conn()
    rows = rows_to_list(conn.execute("SELECT * FROM work_types ORDER BY name").fetchall())
    conn.close()
    return jsonify(rows)

@app.route("/api/work-types", methods=["POST"])
@login_required
def api_add_work_type():
    if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
    d = request.json
    conn = get_conn()
    try:
        conn.execute("INSERT INTO work_types (name,category) VALUES (?,?)",(d["name"],d.get("category","General")))
        conn.commit(); return jsonify({"ok":True})
    except: return jsonify({"error":"Already exists"}),400
    finally: conn.close()

@app.route("/api/work-types/<name>", methods=["PUT"])
@login_required
def api_update_work_type(name):
    if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
    d = request.json
    conn = get_conn()
    # Toggle active status
    if "is_active" in d:
        conn.execute("UPDATE work_types SET is_active=? WHERE name=?",(d["is_active"],name))
    # Rename work type
    if "new_name" in d and d["new_name"].strip() and d["new_name"].strip() != name:
        new_name = d["new_name"].strip()
        try:
            conn.execute("UPDATE work_types SET name=? WHERE name=?",(new_name, name))
            # Cascade rename to all production records
            conn.execute("UPDATE production SET work_type=? WHERE work_type=?",(new_name, name))
            # Cascade to targets tables
            conn.execute("UPDATE targets SET work_type=? WHERE work_type=?",(new_name, name))
            conn.execute("UPDATE date_targets SET work_type=? WHERE work_type=?",(new_name, name))
            conn.execute("UPDATE common_date_targets SET work_type=? WHERE work_type=?",(new_name, name))
            conn.execute("UPDATE custom_roles SET default_work_type=? WHERE default_work_type=?",(new_name, name))
            conn.execute("UPDATE users SET default_work_type=? WHERE default_work_type=?",(new_name, name))
            log_activity("RENAME_WORK_TYPE", f"{name} → {new_name}")
        except Exception as e:
            conn.close()
            return jsonify({"error": str(e)}), 400
    conn.commit(); conn.close()
    return jsonify({"ok":True})


@app.route("/api/sync-emp-ids")
@login_required
def api_sync_emp_ids():
    """Back-fill emp_id on all production records from the users table."""
    if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
    conn = get_conn()
    cur = conn.execute("""
        UPDATE production SET emp_id = (
            SELECT u.emp_id FROM users u WHERE u.username = production.username
        )
        WHERE (production.emp_id IS NULL OR production.emp_id = '')
          AND EXISTS (SELECT 1 FROM users u WHERE u.username = production.username)
    """)
    updated = cur.rowcount
    conn.commit(); conn.close()
    log_activity("SYNC_EMP_IDS", f"updated={updated}")
    return jsonify({"ok": True, "updated": updated})

@app.route("/api/work-types/<name>", methods=["DELETE"])
@login_required
def api_delete_work_type(name):
    if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
    conn = get_conn()
    conn.execute("DELETE FROM work_types WHERE name=?",(name,))
    conn.commit(); conn.close()
    log_activity("DELETE_WORK_TYPE",name)
    return jsonify({"ok":True})

# ─────────────────────────────────────────────────────────────
# API — TARGETS
# ─────────────────────────────────────────────────────────────
@app.route("/api/targets", methods=["GET","POST"])
@login_required
def api_targets():
    conn = get_conn()
    if request.method == "POST":
        if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
        d = request.json
        work_type = d["work_type"]
        tgt_value = float(d["target_value"])
        conn.execute("INSERT OR REPLACE INTO targets (work_type,target_value) VALUES (?,?)",
                     (work_type, tgt_value))
        # Overwrite target on existing production rows for this work_type
        # ONLY where no date-specific override exists (individual or common)
        cur = conn.execute("""
            UPDATE production SET target=?
            WHERE work_type=?
            AND NOT EXISTS (
                SELECT 1 FROM common_date_targets
                WHERE target_date=production.date AND work_type=production.work_type
            )
            AND NOT EXISTS (
                SELECT 1 FROM date_targets
                WHERE username=production.username
                  AND target_date=production.date
                  AND work_type=production.work_type
            )""",
            (tgt_value, work_type))
        updated_rows = cur.rowcount
        conn.commit(); conn.close()
        log_activity("SET_TARGET",f"{work_type}={tgt_value} rows_updated={updated_rows}")
        return jsonify({"ok":True, "updated_rows": updated_rows,
                        "message": f"Default target set to {tgt_value}. Updated {updated_rows} production record(s)."})
    rows = rows_to_list(conn.execute("SELECT * FROM targets").fetchall())
    conn.close()
    return jsonify(rows)

@app.route("/api/date-targets", methods=["GET","POST","DELETE"])
@login_required
def api_date_targets():
    conn = get_conn()
    if request.method == "POST":
        if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
        d = request.json
        scope      = d.get("scope","common")
        tgt_date   = d["date"]
        work_type  = d["work_type"]
        tgt_value  = float(d["value"])
        updated_rows = 0

        if scope == "individual":
            username = d["username"]
            # 1. Save / overwrite the date target
            conn.execute(
                "INSERT OR REPLACE INTO date_targets (username,target_date,work_type,target_value) VALUES (?,?,?,?)",
                (username, tgt_date, work_type, tgt_value))
            # 2. Overwrite target on ALL existing production rows for this user+date+work_type
            cur = conn.execute(
                "UPDATE production SET target=? WHERE username=? AND date=? AND work_type=?",
                (tgt_value, username, tgt_date, work_type))
            updated_rows = cur.rowcount
        else:
            # 1. Save / overwrite the common date target
            conn.execute(
                "INSERT OR REPLACE INTO common_date_targets (target_date,work_type,target_value) VALUES (?,?,?)",
                (tgt_date, work_type, tgt_value))
            # 2. Overwrite target on ALL existing production rows for this date+work_type
            #    BUT only for users who do NOT have an individual override for the same date
            cur = conn.execute("""
                UPDATE production SET target=?
                WHERE date=? AND work_type=?
                AND username NOT IN (
                    SELECT username FROM date_targets
                    WHERE target_date=? AND work_type=?
                )""",
                (tgt_value, tgt_date, work_type, tgt_date, work_type))
            updated_rows = cur.rowcount

        conn.commit()
        log_activity("SET_DATE_TARGET",
            f"scope={scope} date={tgt_date} wt={work_type} tgt={tgt_value} rows_updated={updated_rows}")
        conn.close()
        return jsonify({"ok": True, "updated_rows": updated_rows,
                        "message": f"Target set to {tgt_value}. Updated {updated_rows} existing production record(s)."})

    elif request.method == "DELETE":
        if session.get("role") != "admin": return jsonify({"error":"Admin only"}),403
        d = request.json
        scope = d.get("scope","common")

        if scope == "individual":
            # Fetch the record first so we can re-resolve after deletion
            row = conn.execute(
                "SELECT username,target_date,work_type FROM date_targets WHERE id=?", (d["id"],)).fetchone()
            conn.execute("DELETE FROM date_targets WHERE id=?",(d["id"],))
            if row:
                # Re-resolve (will now fall back to common or default)
                new_tgt = resolve_target(row["username"], row["work_type"], row["target_date"])
                conn.execute(
                    "UPDATE production SET target=? WHERE username=? AND date=? AND work_type=?",
                    (new_tgt, row["username"], row["target_date"], row["work_type"]))
        else:
            row = conn.execute(
                "SELECT target_date,work_type FROM common_date_targets WHERE id=?", (d["id"],)).fetchone()
            conn.execute("DELETE FROM common_date_targets WHERE id=?",(d["id"],))
            if row:
                # Re-resolve for all users (fall back to default target)
                new_tgt = resolve_target("__fallback__", row["work_type"], row["target_date"])
                conn.execute(
                    """UPDATE production SET target=?
                       WHERE date=? AND work_type=?
                       AND username NOT IN (
                           SELECT username FROM date_targets
                           WHERE target_date=? AND work_type=?
                       )""",
                    (new_tgt, row["target_date"], row["work_type"], row["target_date"], row["work_type"]))

        conn.commit(); conn.close()
        return jsonify({"ok":True})

    # GET — include user display names
    common = rows_to_list(conn.execute("SELECT * FROM common_date_targets ORDER BY target_date DESC").fetchall())
    indiv  = rows_to_list(conn.execute("""
        SELECT dt.*, u.full_name FROM date_targets dt
        LEFT JOIN users u ON dt.username=u.username
        ORDER BY dt.target_date DESC""").fetchall())
    conn.close()
    return jsonify({"common":common,"individual":indiv})

# ─────────────────────────────────────────────────────────────
# API — ANALYTICS
# ─────────────────────────────────────────────────────────────
@app.route("/api/analytics")
@login_required
def api_analytics():
    from collections import defaultdict
    data     = load_production()          # scoped to role
    lb_data  = _load_all_production()     # all records for global leaderboard
    me       = session.get("username")

    # ── By Employee (scoped) ──
    eg = defaultdict(lambda:{"Production":0,"Target":0,"days":set(),"Entries":0,"emp_id":""})
    for r in data:
        k=(r["username"],r.get("emp_name") or r["username"],r.get("role",""))
        eg[k]["Production"]+=r["production"]; eg[k]["Target"]+=r["target"]
        eg[k]["days"].add(r["date"]); eg[k]["Entries"]+=1
        eg[k]["emp_id"]=r.get("emp_id","")
    by_emp=[{"username":u,"emp_id":v["emp_id"],"emp_name":nm,"role":rl,
        "Production":int(v["Production"]),"Target":int(v["Target"]),
        "Days":len(v["days"]),"Entries":v["Entries"],
        "Achievement%":safe_pct(v["Production"],v["Target"])}
        for (u,nm,rl),v in eg.items()]
    by_emp.sort(key=lambda x:-x["Production"])

    # ── By Work Type (scoped) ──
    wg = defaultdict(lambda:{"Production":0,"Target":0,"Entries":0})
    for r in data:
        k=r.get("work_type","Other")
        wg[k]["Production"]+=r["production"]
        wg[k]["Target"]+=r["target"]
        wg[k]["Entries"]+=1
    by_wt=[{"work_type":k,"Production":int(v["Production"]),"Target":int(v["Target"]),
             "Entries":v["Entries"],"Achievement%":safe_pct(v["Production"],v["Target"])}
            for k,v in wg.items()]
    by_wt.sort(key=lambda x:-x["Production"])

    # ── Over Time (scoped) ──
    dg = defaultdict(lambda:{"Production":0,"Target":0})
    for r in data:
        dg[r["date"]]["Production"]+=r["production"]; dg[r["date"]]["Target"]+=r["target"]
    over_time=[{"date":d,"Production":int(v["Production"]),"Target":int(v["Target"])}
               for d,v in sorted(dg.items())]

    # ── Global Leaderboard (all users) ──
    lb_g = defaultdict(lambda:{"Production":0,"Target":0,"emp_name":"","emp_id":"",
                                 "work_types":defaultdict(lambda:{"Production":0,"Target":0})})
    for r in lb_data:
        u = r["username"]
        lb_g[u]["Production"] += r["production"]
        lb_g[u]["Target"]     += r["target"]
        lb_g[u]["emp_name"]    = r.get("emp_name","")
        lb_g[u]["emp_id"]      = r.get("emp_id","")
        wt = r.get("work_type","Other")
        lb_g[u]["work_types"][wt]["Production"] += r["production"]
        lb_g[u]["work_types"][wt]["Target"]     += r["target"]

    leaderboard=[]
    for u,v in lb_g.items():
        wt_breakdown=[{"work_type":wt,"Production":int(d["Production"]),"Target":int(d["Target"]),
                        "Achievement%":safe_pct(d["Production"],d["Target"])}
                       for wt,d in v["work_types"].items()]
        wt_breakdown.sort(key=lambda x:-x["Production"])
        leaderboard.append({
            "username":u,"emp_id":v["emp_id"],"emp_name":v["emp_name"],
            "Production":int(v["Production"]),"Target":int(v["Target"]),
            "Achievement%":safe_pct(v["Production"],v["Target"]),
            "wt_breakdown":wt_breakdown,
        })
    leaderboard.sort(key=lambda x:-x["Production"])
    for i,r in enumerate(leaderboard):
        r["rank"]=i+1; r["is_me"]=(r["username"]==me)

    # ── Per-Work-Type Leaderboard (global) ──
    wt_lb = defaultdict(lambda: defaultdict(lambda:{"Production":0,"Target":0,"emp_name":"","emp_id":""}))
    for r in lb_data:
        wt  = r.get("work_type","Other")
        u   = r["username"]
        wt_lb[wt][u]["Production"] += r["production"]
        wt_lb[wt][u]["Target"]     += r["target"]
        wt_lb[wt][u]["emp_name"]    = r.get("emp_name","")
        wt_lb[wt][u]["emp_id"]      = r.get("emp_id","")
    per_wt_leaderboard = {}
    for wt, users in wt_lb.items():
        ranked = sorted(
            [{"username":u,"emp_id":d["emp_id"],"emp_name":d["emp_name"],
              "Production":int(d["Production"]),"Target":int(d["Target"]),
              "Achievement%":safe_pct(d["Production"],d["Target"]),"is_me":(u==me)}
             for u,d in users.items()],
            key=lambda x:-x["Production"]
        )
        for i,r in enumerate(ranked): r["rank"]=i+1
        per_wt_leaderboard[wt] = ranked

    return jsonify({"by_emp":by_emp,"by_wt":by_wt,"over_time":over_time,
                    "leaderboard":leaderboard,"per_wt_leaderboard":per_wt_leaderboard})

def _load_all_production():
    """Load all production records regardless of role (for leaderboard)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.*, COALESCE(p.emp_id, u.emp_id, '') AS emp_id_resolved
        FROM production p LEFT JOIN users u ON p.username=u.username
        ORDER BY p.date DESC""").fetchall()
    conn.close()
    data = rows_to_list(rows)
    for r in data:
        p=float(r.get("production") or 0); t=float(r.get("target") or 0)
        r["achievement_pct"]=round((p/t*100),1) if t>0 else 0.0
        r["emp_id"]=r.get("emp_id_resolved") or r.get("emp_id","")
    return data

# ─────────────────────────────────────────────────────────────
# API — EXPORT
# ─────────────────────────────────────────────────────────────
@app.route("/api/export")
@login_required
def api_export():
    username = request.args.get("username")
    date_from= request.args.get("from")
    date_to  = request.args.get("to")
    role_f   = request.args.get("role")
    wt_f     = request.args.get("work_type")
    fmt      = request.args.get("format","csv")

    data = load_production(username=username)
    if date_from: data=[r for r in data if r["date"]>=date_from]
    if date_to:   data=[r for r in data if r["date"]<=date_to]
    if role_f and role_f!="All": data=[r for r in data if r.get("role")==role_f]
    if wt_f   and wt_f!="All":  data=[r for r in data if r.get("work_type")==wt_f]

    if not data: return jsonify({"error":"No data"}),400
    df = pd.DataFrame(data)

    # Reorder / rename columns for download
    want = ["id","date","emp_id","emp_name","role","work_type","target","production","achievement_pct","remarks","created_at"]
    cols = [c for c in want if c in df.columns] + [c for c in df.columns if c not in want and c not in ("emp_id_resolved",)]
    df = df[[c for c in cols if c in df.columns]]
    df.rename(columns={"achievement_pct":"Achievement%","emp_name":"Employee","emp_id":"EMP_ID"}, inplace=True)

    if fmt == "xlsx":
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="Production Report")
        buf.seek(0)
        return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name="production_report.xlsx")
    else:
        buf = io.StringIO(); df.to_csv(buf, index=False); buf.seek(0)
        return send_file(io.BytesIO(buf.getvalue().encode()), mimetype="text/csv",
                         as_attachment=True, download_name="production_report.csv")

# ─────────────────────────────────────────────────────────────
# API — ACTIVITY LOG
# ─────────────────────────────────────────────────────────────
@app.route("/api/activity-log")
@login_required
def api_activity_log():
    if session.get("role") != "admin": return jsonify([])
    conn = get_conn()
    rows = rows_to_list(conn.execute("SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT 500").fetchall())
    conn.close()
    return jsonify(rows)

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5011))
    app.run(host="0.0.0.0", port=port)
