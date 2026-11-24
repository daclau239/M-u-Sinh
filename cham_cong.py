import streamlit as st
import pandas as pd
import requests
import hashlib
import hmac
import io
import calendar
from datetime import date, datetime

# ============================================================
# 🕘 CHẤM CÔNG LỊCH 3 CA — BẢN GIAO DIỆN MỚI
# ============================================================
# Luồng (giữ nguyên):
# 1) Mở lịch tháng.
# 2) Tick ca Sáng / Chiều / Tối.
# 3) Checkbox chỉ thay đổi "bản nháp" trong session.
# 4) Bấm DUY NHẤT 1 LẦN: "LƯU LỊCH THÁNG".
# 5) App đồng bộ TOÀN BỘ tháng lên Supabase.
#
# Secrets:
# SUPABASE_URL = "https://....supabase.co"
# SUPABASE_SECRET_KEY = "sb_secret_..."
# ============================================================

st.set_page_config(
    page_title="Web Chấm Công",
    page_icon="🕘",
    layout="wide",
    initial_sidebar_state="expanded",
)

SHIFTS = ["Sáng", "Chiều", "Tối"]
SHIFT_ICONS = {"Sáng": "☀️", "Chiều": "🌤️", "Tối": "🌙"}
# Mã ASCII cho từng ca — dùng làm key widget để CSS tô màu theo ca
SHIFT_CODE = {"Sáng": "sang", "Chiều": "chieu", "Tối": "toi"}

WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

# ============================================================
# SECRETS
# ============================================================
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"].strip().rstrip("/")
    SUPABASE_SECRET_KEY = st.secrets["SUPABASE_SECRET_KEY"].strip()
except Exception:
    SUPABASE_URL = ""
    SUPABASE_SECRET_KEY = ""

REST_URL = f"{SUPABASE_URL}/rest/v1" if SUPABASE_URL else ""


# ============================================================
# SQL SETUP / MIGRATION
# ============================================================
SQL_SETUP = r"""
-- CHẠY 1 LẦN TRONG SUPABASE SQL EDITOR

-- 1. Users
create table if not exists public.users (
    id uuid primary key default gen_random_uuid(),
    username text unique not null,
    password_hash text not null,
    full_name text not null,
    role text not null default 'employee'
        check (role in ('admin','employee')),
    department text default '',
    position text default '',
    active boolean not null default true,
    created_at timestamptz not null default now()
);

-- 2. Attendance / lịch ca
create table if not exists public.attendance (
    id uuid primary key default gen_random_uuid(),
    username text not null,
    work_date date not null,
    shift text not null default 'Sáng',
    scheduled boolean not null default true,
    hours numeric(8,2) not null default 0,
    check_in text default '',
    check_out text default '',
    status text default 'Đã xếp ca',
    note text default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Nếu attendance cũ đã tồn tại thì bổ sung cột
alter table public.attendance
add column if not exists shift text;

alter table public.attendance
add column if not exists scheduled boolean default true;

alter table public.attendance
add column if not exists hours numeric(8,2) default 0;

alter table public.attendance
add column if not exists updated_at timestamptz default now();

update public.attendance
set shift = 'Sáng'
where shift is null or shift = '';

update public.attendance
set scheduled = true
where scheduled is null;

update public.attendance
set hours = 0
where hours is null;

alter table public.attendance
alter column shift set not null;

alter table public.attendance
alter column scheduled set not null;

alter table public.attendance
alter column hours set not null;

-- Xóa unique cũ nếu có
alter table public.attendance
drop constraint if exists attendance_username_work_date_key;

alter table public.attendance
drop constraint if exists attendance_user_date_unique;

alter table public.attendance
drop constraint if exists attendance_username_work_date_shift_key;

-- Mỗi nhân viên + ngày + ca chỉ có 1 record
alter table public.attendance
add constraint attendance_username_work_date_shift_key
unique (username, work_date, shift);

create index if not exists attendance_lookup_idx
on public.attendance(username, work_date, shift);

-- 3. Cấu hình tháng:
-- nhập 1 lần: số giờ ca Sáng/Chiều/Tối + lương/giờ
create table if not exists public.monthly_shift_settings (
    id uuid primary key default gen_random_uuid(),
    username text not null,
    year integer not null,
    month integer not null,
    morning_hours numeric(8,2) not null default 4,
    afternoon_hours numeric(8,2) not null default 4,
    evening_hours numeric(8,2) not null default 4,
    hourly_rate numeric(12,2) not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(username, year, month)
);

-- 4. Admin mặc định: admin / admin123
insert into public.users
(username, password_hash, full_name, role, department, position, active)
values
(
    'admin',
    '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9',
    'Quản trị viên',
    'admin',
    'Quản trị',
    'Administrator',
    true
)
on conflict (username) do nothing;
"""


# ============================================================
# API
# ============================================================
def headers():
    return {
        "apikey": SUPABASE_SECRET_KEY,
        "Content-Type": "application/json",
    }


def sb_request(method, table, params=None, payload=None, prefer=None):
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        raise RuntimeError("Chưa cấu hình Supabase Secrets.")

    h = headers()
    if prefer:
        h["Prefer"] = prefer

    r = requests.request(
        method,
        f"{REST_URL}/{table}",
        params=params or {},
        json=payload,
        headers=h,
        timeout=30,
    )

    if not r.ok:
        raise RuntimeError(f"Supabase {r.status_code}: {r.text}")

    return r.json() if r.text else []


def select_rows(table, params=None):
    return sb_request("GET", table, params=params)


def upsert_rows(table, rows, conflict):
    if not rows:
        return []

    return sb_request(
        "POST",
        table,
        params={"on_conflict": conflict},
        payload=rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def delete_rows(table, params=None):
    return sb_request(
        "DELETE",
        table,
        params=params,
        prefer="return=minimal",
    )


def safe_error(e):
    s = str(e)
    if SUPABASE_SECRET_KEY:
        s = s.replace(SUPABASE_SECRET_KEY, "[HIDDEN]")
    return s


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ============================================================
# DATABASE HELPERS
# ============================================================
def get_user(username):
    rows = select_rows(
        "users",
        {
            "select": "*",
            "username": f"eq.{username}",
            "limit": "1",
        },
    )
    return rows[0] if rows else None


def get_users():
    return pd.DataFrame(
        select_rows(
            "users",
            {
                "select": "*",
                "order": "created_at.asc",
            },
        )
    )


def get_month_attendance(username, year, month):
    # Lấy TOÀN BỘ attendance của user rồi lọc tháng trong Python.
    df = pd.DataFrame(
        select_rows(
            "attendance",
            {
                "select": "*",
                "username": f"eq.{username}",
                "order": "work_date.asc,shift.asc",
            },
        )
    )

    if df.empty:
        return df

    df["work_date"] = df["work_date"].astype(str).str[:10]

    prefix = f"{int(year):04d}-{int(month):02d}-"

    df = df[df["work_date"].str.startswith(prefix)].copy()

    if "scheduled" not in df.columns:
        df["scheduled"] = True

    df["_scheduled"] = df["scheduled"].map(
        lambda x: (
            x if isinstance(x, bool)
            else str(x).strip().lower() in ("true", "1", "yes")
        )
    )

    return df


def get_month_settings(username, year, month):
    rows = select_rows(
        "monthly_shift_settings",
        {
            "select": "*",
            "username": f"eq.{username}",
            "year": f"eq.{int(year)}",
            "month": f"eq.{int(month)}",
            "limit": "1",
        },
    )
    return rows[0] if rows else None


def save_month_settings(
    username,
    year,
    month,
    morning,
    afternoon,
    evening,
    hourly_rate,
):
    upsert_rows(
        "monthly_shift_settings",
        [{
            "username": username,
            "year": int(year),
            "month": int(month),
            "morning_hours": float(morning),
            "afternoon_hours": float(afternoon),
            "evening_hours": float(evening),
            "hourly_rate": float(hourly_rate),
            "updated_at": datetime.utcnow().isoformat(),
        }],
        "username,year,month",
    )


def shift_hours(settings, shift):
    if not settings:
        return 0.0

    if shift == "Sáng":
        return float(settings.get("morning_hours", 0) or 0)
    if shift == "Chiều":
        return float(settings.get("afternoon_hours", 0) or 0)
    return float(settings.get("evening_hours", 0) or 0)


def sync_full_month(
    username,
    year,
    month,
    selected_keys,
    settings,
):
    """
    Đồng bộ toàn bộ tháng:
    - selected_keys: toàn bộ các ô đang tick trên lịch.
    - Những ô tick => upsert.
    - Những ô đã tồn tại nhưng bị bỏ tick => delete.
    """

    current = get_month_attendance(username, year, month)

    existing_keys = set()

    if not current.empty:
        for _, row in current.iterrows():
            if bool(row.get("_scheduled", False)):
                existing_keys.add((
                    str(row["work_date"])[:10],
                    str(row.get("shift", "Sáng")),
                ))

    rows_to_upsert = []

    for work_date, shift in selected_keys:
        rows_to_upsert.append({
            "username": username,
            "work_date": work_date,
            "shift": shift,
            "scheduled": True,
            "hours": shift_hours(settings, shift),
            "check_in": "",
            "check_out": "",
            "status": "Đã xếp ca",
            "note": "",
            "updated_at": datetime.utcnow().isoformat(),
        })

    # Ghi toàn bộ các dòng đã tick trong MỘT request.
    if rows_to_upsert:
        upsert_rows(
            "attendance",
            rows_to_upsert,
            "username,work_date,shift",
        )

    desired_keys = set(selected_keys)

    # Những ca trước đó có nhưng hiện tại bỏ tick.
    to_delete = existing_keys - desired_keys

    if to_delete:
        for work_date, shift in to_delete:
            delete_rows(
                "attendance",
                {
                    "username": f"eq.{username}",
                    "work_date": f"eq.{work_date}",
                    "shift": f"eq.{shift}",
                },
            )

    # Đọc lại DB để xác nhận.
    verified = get_month_attendance(username, year, month)

    saved_count = (
        int(verified["_scheduled"].sum())
        if not verified.empty
        else 0
    )

    return saved_count


# ============================================================
# GIAO DIỆN — CSS
# ============================================================
# Bảng màu:
#   Phong cách Liquid Glass: nền gradient sáng + thẻ kính mờ
#   Mực       #15303B  (chữ)
#   Xanh ngọc #12A5A0 → Xanh dương #3B82F6 (nút, nhấn)
#   Ca Sáng   #C77F00 / nền #FFF3D6
#   Ca Chiều  #1C77B0 / nền #E0F0FA
#   Ca Tối    #5646B0 / nền #ECE8FA
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap');

:root {
    --ink: #15303B;
    --ink-soft: #3C5A66;
    --muted: #6A8591;
    --teal: #12A5A0;
    --teal-dark: #0B7F83;
    --blue: #3B82F6;
    --glass: rgba(255,255,255,0.52);
    --glass-strong: rgba(255,255,255,0.72);
    --glass-border: rgba(255,255,255,0.75);
    --glass-shadow: 0 8px 32px rgba(40,90,110,0.12), inset 0 1px 0 rgba(255,255,255,0.95);
    --sang: #B76E00;  --sang-bg: rgba(255,214,102,0.38);  --sang-on: rgba(255,200,64,0.62);
    --chieu: #176FB0; --chieu-bg: rgba(125,200,255,0.34); --chieu-on: rgba(88,180,250,0.58);
    --toi: #5B47C0;   --toi-bg: rgba(178,160,255,0.34);   --toi-on: rgba(150,128,250,0.58);
}

/* ---------- Nền kính: các vệt màu mềm ---------- */
.stApp {
    color: var(--ink);
    background:
        radial-gradient(900px 600px at 8% -5%,  rgba(94,234,212,0.55), transparent 60%),
        radial-gradient(800px 600px at 95% 5%,  rgba(147,197,253,0.60), transparent 60%),
        radial-gradient(900px 700px at 85% 95%, rgba(196,181,253,0.50), transparent 60%),
        radial-gradient(700px 600px at 0% 100%, rgba(253,224,150,0.50), transparent 60%),
        #EAF2F7;
    background-attachment: fixed;
}

.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea,
.stApp button, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp [data-baseweb="select"], .stApp [data-testid="stMarkdownContainer"] {
    font-family: 'Be Vietnam Pro', 'Segoe UI', sans-serif;
}

.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1280px; }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }
h2, h3 { color: var(--ink); font-weight: 700; letter-spacing: -0.01em; }

/* ---------- Kính dùng chung ---------- */
[data-testid="stForm"],
.kpi,
.hero,
.side-card,
[data-testid="stDataFrame"],
.stTabs [data-baseweb="tab-list"],
[data-testid="stExpander"],
[data-testid="stMetric"],
[data-testid="stAlert"] {
    background: var(--glass) !important;
    backdrop-filter: blur(22px) saturate(180%);
    -webkit-backdrop-filter: blur(22px) saturate(180%);
    border: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow);
}

/* ---------- Banner ---------- */
.hero {
    border-radius: 26px;
    padding: 26px 32px;
    margin-bottom: 22px;
    display: flex; justify-content: space-between; align-items: center;
    gap: 16px; flex-wrap: wrap;
    background:
        linear-gradient(120deg, rgba(18,165,160,0.28), rgba(59,130,246,0.20) 60%, rgba(167,139,250,0.22)),
        var(--glass) !important;
    position: relative; overflow: hidden;
}
.hero::after {
    content: ""; position: absolute; top: -60%; left: -10%; width: 60%; height: 200%;
    background: linear-gradient(100deg, transparent, rgba(255,255,255,0.45), transparent);
    transform: rotate(8deg); pointer-events: none;
}
.hero-title { font-size: 1.75rem; font-weight: 800; line-height: 1.25; letter-spacing: -0.015em; color: var(--ink); }
.hero-sub { color: var(--ink-soft); font-size: 0.95rem; margin-top: 4px; }
.hero-chip {
    background: var(--glass-strong);
    border: 1px solid var(--glass-border);
    box-shadow: inset 0 1px 0 #fff;
    border-radius: 999px; padding: 8px 18px;
    font-size: 0.88rem; font-weight: 600; color: var(--teal-dark);
    white-space: nowrap; position: relative; z-index: 1;
}

.section-title { font-size: 1.15rem; font-weight: 700; color: var(--ink); margin: 6px 0 2px 0; }
.section-sub { color: var(--muted); font-size: 0.9rem; margin-bottom: 10px; }

/* ---------- KPI ---------- */
.kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 8px 0 18px; }
.kpi { border-radius: 22px; padding: 20px 22px; position: relative; overflow: hidden; }
.kpi::before {
    content: ""; position: absolute; right: -30px; top: -30px; width: 110px; height: 110px;
    border-radius: 50%; background: radial-gradient(circle, rgba(18,165,160,0.35), transparent 70%);
}
.kpi.hours::before { background: radial-gradient(circle, rgba(59,130,246,0.35), transparent 70%); }
.kpi.money::before { background: radial-gradient(circle, rgba(250,190,60,0.45), transparent 70%); }
.kpi-label { color: var(--ink-soft); font-size: 0.85rem; font-weight: 500; position: relative; }
.kpi-value { color: var(--ink); font-size: 1.85rem; font-weight: 800; line-height: 1.2; margin-top: 2px; position: relative; }
.kpi-note { color: var(--muted); font-size: 0.82rem; margin-top: 4px; position: relative; }
@media (max-width: 760px) { .kpi-grid { grid-template-columns: 1fr; } }

/* ---------- Chú thích ca ---------- */
.legend { display: flex; gap: 10px; flex-wrap: wrap; margin: 4px 0 12px; }
.legend span {
    font-size: 0.85rem; font-weight: 600; border-radius: 999px; padding: 6px 14px;
    border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255,255,255,0.8);
    backdrop-filter: blur(10px);
}
.legend .l-sang  { background: var(--sang-bg);  color: var(--sang); }
.legend .l-chieu { background: var(--chieu-bg); color: var(--chieu); }
.legend .l-toi   { background: var(--toi-bg);   color: var(--toi); }

[data-testid="stForm"] { border-radius: 24px; padding: 22px 24px; }

/* ---------- Lịch ---------- */
[class*="st-key-calendar_form"] [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important; overflow-x: auto; gap: 8px;
}
[class*="st-key-calendar_form"] [data-testid="stColumn"] { min-width: 128px !important; }

[class*="st-key-calendar_form"] [data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid var(--glass-border) !important;
    border-radius: 18px;
    background: rgba(255,255,255,0.48);
    backdrop-filter: blur(12px);
    box-shadow: 0 2px 10px rgba(40,90,110,0.07), inset 0 1px 0 rgba(255,255,255,0.9);
    padding: 2px 4px 4px;
}

.wd-head { text-align: center; font-weight: 700; font-size: 0.85rem; color: var(--muted); padding: 6px 0; }
.wd-head.weekend { color: #D2573F; }

.day-number {
    font-weight: 800; font-size: 1rem; color: var(--ink);
    margin: 2px 0 4px 2px; display: inline-block; min-width: 28px; text-align: center;
    border-radius: 999px; padding: 1px 6px;
}
.day-number.today {
    background: linear-gradient(135deg, var(--teal), var(--blue)); color: #fff;
    box-shadow: 0 3px 10px rgba(18,165,160,0.4);
}
.day-number.weekend { color: #D2573F; }
.day-count { float: right; font-size: 0.72rem; color: var(--muted); font-weight: 600; margin-top: 5px; }

[class*="st-key-cal_"] [data-testid="stCheckbox"] {
    border-radius: 12px; padding: 3px 8px; margin-bottom: 4px;
    border: 1px solid rgba(255,255,255,0.7);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.8);
    transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
}
[class*="st-key-cal_"] [data-testid="stCheckbox"] label p { font-size: 0.85rem; font-weight: 600; color: inherit; }

[class*="st-key-cal_"][class*="_sang"]  [data-testid="stCheckbox"] { background: var(--sang-bg);  color: var(--sang); }
[class*="st-key-cal_"][class*="_chieu"] [data-testid="stCheckbox"] { background: var(--chieu-bg); color: var(--chieu); }
[class*="st-key-cal_"][class*="_toi"]   [data-testid="stCheckbox"] { background: var(--toi-bg);   color: var(--toi); }

[class*="st-key-cal_"][class*="_sang"]  [data-testid="stCheckbox"]:has(input:checked) { background: var(--sang-on);  border-color: var(--sang);  box-shadow: 0 3px 10px rgba(230,160,20,0.30); }
[class*="st-key-cal_"][class*="_chieu"] [data-testid="stCheckbox"]:has(input:checked) { background: var(--chieu-on); border-color: var(--chieu); box-shadow: 0 3px 10px rgba(40,140,230,0.28); }
[class*="st-key-cal_"][class*="_toi"]   [data-testid="stCheckbox"]:has(input:checked) { background: var(--toi-on);   border-color: var(--toi);   box-shadow: 0 3px 10px rgba(110,90,230,0.28); }

/* ---------- Nút (kính bóng) ---------- */
.stApp .stButton > button,
.stApp [data-testid="stFormSubmitButton"] > button,
.stApp [data-testid="stDownloadButton"] > button {
    border-radius: 14px; font-weight: 700; padding: 0.62rem 1rem;
    transition: transform 0.08s, box-shadow 0.18s, filter 0.18s;
}
.stApp [data-testid="stFormSubmitButton"] > button,
.stApp [data-testid="stDownloadButton"] > button {
    background: linear-gradient(135deg, #14B8A6 0%, #3B82F6 100%);
    color: #fff; border: 1px solid rgba(255,255,255,0.6);
    box-shadow: 0 6px 18px rgba(30,140,200,0.30), inset 0 1px 0 rgba(255,255,255,0.55);
}
.stApp [data-testid="stFormSubmitButton"] > button:hover,
.stApp [data-testid="stDownloadButton"] > button:hover {
    color: #fff; filter: brightness(1.06); border-color: rgba(255,255,255,0.8);
    box-shadow: 0 10px 26px rgba(30,140,200,0.38), inset 0 1px 0 rgba(255,255,255,0.6);
}
.stApp [data-testid="stFormSubmitButton"] > button:active { transform: scale(0.99); }

.stApp .stButton > button {
    background: var(--glass-strong); color: var(--ink);
    border: 1px solid var(--glass-border);
    box-shadow: 0 4px 14px rgba(40,90,110,0.10), inset 0 1px 0 #fff;
}
.stApp .stButton > button:hover { color: var(--teal-dark); border-color: var(--teal); }

/* ---------- Ô nhập ---------- */
.stApp [data-baseweb="input"], .stApp [data-baseweb="select"] > div, .stApp [data-baseweb="base-input"] {
    border-radius: 12px;
    background: rgba(255,255,255,0.62) !important;
    border: 1px solid rgba(255,255,255,0.85) !important;
    box-shadow: inset 0 1px 2px rgba(40,90,110,0.06);
}
.stApp [data-baseweb="input"] input { background: transparent !important; color: var(--ink); }
.stApp [data-baseweb="input"]:focus-within, .stApp [data-baseweb="select"] > div:focus-within {
    border-color: var(--teal) !important;
    box-shadow: 0 0 0 3px rgba(18,165,160,0.18);
}

/* ---------- Tab ---------- */
.stTabs [data-baseweb="tab-list"] { gap: 6px; padding: 6px; border-radius: 18px; }
.stTabs [data-baseweb="tab"] { border-radius: 13px; padding: 8px 18px; font-weight: 600; height: auto; color: var(--ink-soft); }
.stTabs [aria-selected="true"] {
    background: var(--glass-strong); color: var(--teal-dark);
    box-shadow: 0 3px 10px rgba(40,90,110,0.12), inset 0 1px 0 #fff;
}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none; }

[data-testid="stDataFrame"] { border-radius: 18px; overflow: hidden; }
[data-testid="stMetric"] { border-radius: 18px; padding: 14px 18px; }
[data-testid="stExpander"] { border-radius: 18px; }
[data-testid="stAlert"] { border-radius: 14px; }

/* ---------- Sidebar kính sáng ---------- */
[data-testid="stSidebar"] {
    background: rgba(255,255,255,0.40);
    backdrop-filter: blur(26px) saturate(180%);
    -webkit-backdrop-filter: blur(26px) saturate(180%);
    border-right: 1px solid var(--glass-border);
}
[data-testid="stSidebar"] hr { border-color: rgba(21,48,59,0.10); }
.side-brand { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.01em; color: var(--ink); }
.side-card { border-radius: 20px; padding: 16px; margin-top: 12px; }
.avatar {
    width: 44px; height: 44px; border-radius: 50%;
    background: linear-gradient(135deg, var(--teal), var(--blue)); color: #fff;
    display: flex; align-items: center; justify-content: center;
    font-weight: 800; font-size: 1.05rem; margin-bottom: 8px;
    box-shadow: 0 4px 12px rgba(30,140,200,0.35), inset 0 1px 0 rgba(255,255,255,0.5);
}
.side-name { font-weight: 700; font-size: 1rem; color: var(--ink); }
.side-meta { color: var(--muted); font-size: 0.82rem; }
.role-pill {
    display: inline-block; margin-top: 8px; padding: 3px 12px; border-radius: 999px;
    background: rgba(18,165,160,0.16); color: var(--teal-dark);
    border: 1px solid rgba(18,165,160,0.25); font-size: 0.78rem; font-weight: 600;
}

/* ---------- Đăng nhập ---------- */
.login-brand { text-align: center; margin: 3vh 0 18px; }
.login-logo {
    width: 68px; height: 68px; border-radius: 22px; margin: 0 auto 12px;
    background: linear-gradient(135deg, rgba(20,184,166,0.9), rgba(59,130,246,0.9));
    border: 1px solid rgba(255,255,255,0.7);
    box-shadow: 0 10px 28px rgba(30,140,200,0.35), inset 0 1px 0 rgba(255,255,255,0.6);
    display: flex; align-items: center; justify-content: center; font-size: 1.9rem;
}
.login-title { font-size: 1.7rem; font-weight: 800; color: var(--ink); letter-spacing: -0.015em; }
.login-sub { color: var(--muted); font-size: 0.92rem; margin-top: 4px; }

@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
/* ============================================================
   ÉP GIAO DIỆN SÁNG: bỏ màu đen/tối của chế độ dark
   ============================================================ */
:root, .stApp, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
    color-scheme: light !important;
}

/* Chữ: luôn đậm, dễ đọc */
.stApp p, .stApp span, .stApp li, .stApp label,
.stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stWidgetLabel"] p,
.stApp [data-testid="stCheckbox"] label p,
.stApp [data-testid="stMetricLabel"] p,
.stApp [data-testid="stMetricValue"],
.stApp [data-testid="stExpander"] summary p,
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {
    color: var(--ink);
}
.stApp [data-testid="stCaptionContainer"], .stApp [data-testid="stCaptionContainer"] p {
    color: var(--ink-soft) !important;
}
.stApp [data-testid="stWidgetLabel"] p { font-weight: 600; }
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label { color: var(--ink); }
.hero-title { color: var(--ink) !important; }
.hero-sub { color: var(--ink-soft) !important; }
.hero-chip { color: var(--teal-dark) !important; }
.avatar { color: #fff !important; }
.stApp [data-testid="stFormSubmitButton"] > button p,
.stApp [data-testid="stDownloadButton"] > button p,
.day-number.today { color: #fff !important; }
[class*="st-key-cal_"][class*="_sang"]  [data-testid="stCheckbox"] label p { color: var(--sang) !important; }
[class*="st-key-cal_"][class*="_chieu"] [data-testid="stCheckbox"] label p { color: var(--chieu) !important; }
[class*="st-key-cal_"][class*="_toi"]   [data-testid="stCheckbox"] label p { color: var(--toi) !important; }

/* Ô nhập: nền TRẮNG, chữ đậm */
.stApp [data-baseweb="input"],
.stApp [data-baseweb="base-input"],
.stApp [data-baseweb="select"] > div,
.stApp [data-baseweb="textarea"],
.stApp input, .stApp textarea {
    background: #FFFFFF !important;
    color: var(--ink) !important;
    -webkit-text-fill-color: var(--ink) !important;
}
.stApp [data-baseweb="input"], .stApp [data-baseweb="select"] > div, .stApp [data-baseweb="textarea"] {
    border: 1px solid rgba(21,48,59,0.16) !important;
    box-shadow: 0 1px 3px rgba(40,90,110,0.08) !important;
}
.stApp input::placeholder, .stApp textarea::placeholder { color: #8DA3AD !important; -webkit-text-fill-color: #8DA3AD !important; }
.stApp [data-baseweb="select"] svg, .stApp [data-testid="stNumberInput"] button svg { fill: var(--ink-soft) !important; color: var(--ink-soft) !important; }
.stApp [data-testid="stNumberInput"] button { background: #F3F7F9 !important; color: var(--ink) !important; border-color: rgba(21,48,59,0.12) !important; }
.stApp [data-baseweb="select"] [data-baseweb="tag"], .stApp [data-baseweb="select"] div { color: var(--ink) !important; }

/* Danh sách xổ xuống (hiện ngoài .stApp): nền trắng */
[data-baseweb="popover"], [data-baseweb="popover"] > div,
[data-baseweb="menu"], ul[role="listbox"] {
    background: #FFFFFF !important;
    color: var(--ink) !important;
    border-radius: 14px;
}
[data-baseweb="popover"] li, [data-baseweb="menu"] li, ul[role="listbox"] li {
    background: #FFFFFF !important; color: var(--ink) !important;
}
[data-baseweb="popover"] li:hover, [data-baseweb="menu"] li:hover, ul[role="listbox"] li[aria-selected="true"] {
    background: #E6F6F5 !important; color: var(--teal-dark) !important;
}

/* Khối code (lỗi, SQL): nền sáng */
.stApp [data-testid="stCode"], .stApp [data-testid="stCode"] pre, .stApp pre, .stApp code {
    background: rgba(255,255,255,0.92) !important;
    color: #1F3B47 !important;
    border-radius: 12px;
}
.stApp [data-testid="stCode"] span { color: #1F3B47 !important; }

/* Thông báo (success / error / info / warning): chữ rõ */
.stApp [data-testid="stAlert"] p, .stApp [data-testid="stAlert"] span { color: var(--ink) !important; }

/* Expander */
.stApp [data-testid="stExpander"] details, .stApp [data-testid="stExpander"] summary { background: transparent !important; color: var(--ink); }

/* ---------- Bảng TRẮNG (thay bảng đen của Streamlit) ---------- */
.table-wrap {
    background: #FFFFFF;
    border: 1px solid rgba(21,48,59,0.10);
    border-radius: 18px;
    box-shadow: 0 6px 22px rgba(40,90,110,0.10);
    overflow-x: auto;
    margin: 6px 0 14px;
}
table.glass-table { width: 100%; border-collapse: collapse; font-size: 0.92rem; background: #FFFFFF; }
table.glass-table thead th {
    background: #EEF6F8; color: var(--ink); font-weight: 700; text-align: left;
    padding: 12px 16px; border-bottom: 1px solid rgba(21,48,59,0.10); white-space: nowrap;
}
table.glass-table tbody td {
    color: var(--ink); padding: 11px 16px; border-bottom: 1px solid rgba(21,48,59,0.06);
    background: #FFFFFF;
}
table.glass-table tbody tr:nth-child(even) td { background: #F8FBFC; }
table.glass-table tbody tr:hover td { background: #E6F6F5; }
table.glass-table tbody tr:last-child td { border-bottom: none; }
table.glass-table td.num, table.glass-table th.num { text-align: right; font-variant-numeric: tabular-nums; }
.table-empty { padding: 18px; color: var(--ink-soft); }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


# ============================================================
# GIAO DIỆN — THÀNH PHẦN DÙNG CHUNG
# ============================================================
def hero(title, subtitle="", chip=""):
    chip_html = f'<div class="hero-chip">{chip}</div>' if chip else ""
    st.markdown(
        f"""
<div class="hero">
  <div>
    <div class="hero-title">{title}</div>
    <div class="hero-sub">{subtitle}</div>
  </div>
  {chip_html}
</div>
""",
        unsafe_allow_html=True,
    )


def section(title, sub=""):
    st.markdown(
        f'<div class="section-title">{title}</div>'
        + (f'<div class="section-sub">{sub}</div>' if sub else ""),
        unsafe_allow_html=True,
    )


def shift_legend():
    st.markdown(
        '<div class="legend">'
        '<span class="l-sang">☀️ Ca sáng</span>'
        '<span class="l-chieu">🌤️ Ca chiều</span>'
        '<span class="l-toi">🌙 Ca tối</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def kpi_cards(total_shifts, total_hours, total_salary, breakdown=""):
    st.markdown(
        f"""
<div class="kpi-grid">
  <div class="kpi">
    <div class="kpi-label">☑️ Tổng ca</div>
    <div class="kpi-value">{total_shifts}</div>
    <div class="kpi-note">{breakdown or "&nbsp;"}</div>
  </div>
  <div class="kpi hours">
    <div class="kpi-label">⏱️ Tổng giờ</div>
    <div class="kpi-value">{total_hours:g} giờ</div>
    <div class="kpi-note">&nbsp;</div>
  </div>
  <div class="kpi money">
    <div class="kpi-label">💵 Tổng lương</div>
    <div class="kpi-value">{total_salary:,.0f} đ</div>
    <div class="kpi-note">&nbsp;</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def month_picker(year_key, month_key):
    today = date.today()
    c1, c2, _ = st.columns([1, 1, 2])

    year = c1.number_input("Năm", 2020, 2100, today.year, key=year_key)

    month = c2.selectbox(
        "Tháng",
        range(1, 13),
        today.month - 1,
        key=month_key,
        format_func=lambda m: f"Tháng {m}",
    )

    return int(year), int(month)


def summarize(df, settings):
    """Trả về (tổng ca, tổng giờ, tổng lương, chuỗi chi tiết ca, hourly_rate)."""
    hourly_rate = float(settings.get("hourly_rate", 0) or 0) if settings else 0.0

    if df is None or df.empty:
        return 0, 0.0, 0.0, "Chưa có ca nào", hourly_rate

    shifts = df["shift"].astype(str).tolist()
    total_hours = sum(shift_hours(settings, s) for s in shifts)

    breakdown = " • ".join(
        f"{SHIFT_ICONS[s]} {shifts.count(s)}" for s in SHIFTS
    )

    return (
        len(shifts),
        total_hours,
        total_hours * hourly_rate,
        breakdown,
        hourly_rate,
    )


def build_report(df, settings, hourly_rate, vn_date=True):
    rows = []

    for _, row in df.iterrows():
        shift = str(row["shift"])
        hours = shift_hours(settings, shift)
        d = str(row["work_date"])[:10]

        if vn_date:
            d = datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y")

        rows.append({
            "Ngày": d,
            "Ca": shift,
            "Số giờ": hours,
            "Lương/giờ": hourly_rate,
            "Tiền ca": hours * hourly_rate,
        })

    return pd.DataFrame(rows)


def to_excel_bytes(report, sheet_name):
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        report.to_excel(writer, index=False, sheet_name=sheet_name)

    output.seek(0)
    return output.getvalue()


XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument."
    "spreadsheetml.sheet"
)


def render_table(df):
    """Bảng HTML nền trắng, chữ đậm (không phụ thuộc theme tối của Streamlit)."""
    import html as _html

    if df is None or df.empty:
        st.markdown(
            '<div class="table-wrap"><div class="table-empty">Chưa có dữ liệu.</div></div>',
            unsafe_allow_html=True,
        )
        return

    num_cols = {"Số giờ", "Lương/giờ", "Tiền ca"}
    cols = list(df.columns)

    head = "".join(
        f'<th class="{"num" if c in num_cols else ""}">{_html.escape(str(c))}</th>'
        for c in cols
    )

    body = []
    for _, row in df.iterrows():
        tds = []
        for c in cols:
            v = row[c]
            if c == "Số giờ":
                txt = f"{float(v):g}"
            elif c in ("Lương/giờ", "Tiền ca"):
                txt = f"{float(v):,.0f}"
            else:
                txt = "" if pd.isna(v) else str(v)
            cls = "num" if c in num_cols else ""
            tds.append(f'<td class="{cls}">{_html.escape(txt)}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")

    st.markdown(
        '<div class="table-wrap"><table class="glass-table">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


# ============================================================
# CONFIG CHECK
# ============================================================
if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    hero(
        "🕘 Web chấm công",
        "Cần kết nối Supabase trước khi sử dụng.",
    )

    st.warning("Chưa cấu hình Supabase.")

    st.code(
        'SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"\n'
        'SUPABASE_SECRET_KEY = "sb_secret_..."',
        language="toml",
    )

    st.stop()


# ============================================================
# DATABASE CHECK
# ============================================================
try:
    select_rows("users", {"select": "id", "limit": "1"})

    select_rows(
        "attendance",
        {
            "select": "id,work_date,shift,scheduled,hours",
            "limit": "1",
        },
    )

    select_rows("monthly_shift_settings", {"select": "id", "limit": "1"})

except Exception as e:
    st.error("❌ Database chưa đúng cấu trúc.")
    st.code(safe_error(e))

    st.markdown(
        "Chạy SQL bên dưới **1 lần** trong Supabase → SQL Editor:"
    )

    st.code(SQL_SETUP, language="sql")

    st.stop()


# ============================================================
# LOGIN
# ============================================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False


if not st.session_state.logged_in:
    _, mid, _ = st.columns([1, 1.15, 1])

    with mid:
        st.markdown(
            """
<div class="login-brand">
  <div class="login-logo">🕘</div>
  <div class="login-title">Web chấm công</div>
  <div class="login-sub">Lịch 3 ca • Tự tính giờ • Tự tính lương</div>
</div>
""",
            unsafe_allow_html=True,
        )

        with st.form("login"):
            username = st.text_input("Tên đăng nhập")
            password = st.text_input("Mật khẩu", type="password")

            if st.form_submit_button(
                "🔐 Đăng nhập",
                use_container_width=True,
            ):
                try:
                    user = get_user(username.strip())

                    if (
                        user
                        and bool(user.get("active"))
                        and hmac.compare_digest(
                            str(user.get("password_hash", "")),
                            sha256(password),
                        )
                    ):
                        st.session_state.logged_in = True
                        st.session_state.username = user["username"]
                        st.rerun()
                    else:
                        st.error("Sai tài khoản hoặc mật khẩu.")

                except Exception as e:
                    st.error("Lỗi đăng nhập.")
                    st.code(safe_error(e))

        st.caption("Admin mặc định: admin / admin123")

    st.stop()


current_user = get_user(st.session_state.username)

if not current_user or not bool(current_user.get("active")):
    st.session_state.clear()
    st.error("Tài khoản không tồn tại hoặc đã bị khóa.")
    st.stop()


# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    initial = (current_user["full_name"].strip()[:1] or "?").upper()
    role_label = (
        "Quản trị viên" if current_user["role"] == "admin" else "Nhân viên"
    )

    st.markdown(
        f"""
<div class="side-brand">🕘 Chấm công</div>
<div class="side-card">
  <div class="avatar">{initial}</div>
  <div class="side-name">{current_user['full_name']}</div>
  <div class="side-meta">@{current_user['username']}</div>
  <div class="role-pill">{role_label}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.divider()

    if st.button("🚪 Đăng xuất", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# ============================================================
# CALENDAR DRAFT
# ============================================================
def calendar_draft_key(username, year, month):
    return f"draft_{username}_{int(year)}_{int(month):02d}"


def widget_key(key_prefix, year, month, day, shift):
    return (
        f"cal_{key_prefix}_"
        f"{int(year)}_{int(month):02d}_"
        f"{int(day):02d}_{SHIFT_CODE[shift]}"
    )


def load_draft(username, year, month):
    key = calendar_draft_key(username, year, month)

    if key in st.session_state:
        return st.session_state[key]

    df = get_month_attendance(username, year, month)

    draft = set()

    if not df.empty:
        for _, row in df.iterrows():
            if bool(row.get("_scheduled", False)):
                draft.add((
                    str(row["work_date"])[:10],
                    str(row["shift"]),
                ))

    st.session_state[key] = draft

    return draft


def render_schedule_calendar(username, year, month, key_prefix):
    draft = load_draft(username, year, month)
    today_str = date.today().strftime("%Y-%m-%d")

    shift_legend()

    # Khóa tháng hiện tại bằng form.
    with st.form(f"calendar_form_{key_prefix}_{year}_{month}"):
        weeks = calendar.Calendar(
            firstweekday=0
        ).monthdayscalendar(int(year), int(month))

        header = st.columns(7)

        for i, wd in enumerate(WEEKDAYS):
            weekend = " weekend" if i >= 5 else ""
            header[i].markdown(
                f"<div class='wd-head{weekend}'>{wd}</div>",
                unsafe_allow_html=True,
            )

        # Checkbox chỉ cập nhật vào draft khi form submit.
        all_keys = []

        for week in weeks:
            cols = st.columns(7)

            for col_idx, day in enumerate(week):
                with cols[col_idx]:

                    if day == 0:
                        continue

                    ds = (
                        f"{int(year):04d}-"
                        f"{int(month):02d}-"
                        f"{int(day):02d}"
                    )

                    with st.container(border=True):
                        classes = "day-number"
                        if ds == today_str:
                            classes += " today"
                        elif col_idx >= 5:
                            classes += " weekend"

                        count = sum(1 for s in SHIFTS if (ds, s) in draft)
                        count_html = (
                            f"<span class='day-count'>{count}/3 ca</span>"
                            if count else ""
                        )

                        st.markdown(
                            f"<div><span class='{classes}'>{day}</span>"
                            f"{count_html}</div>",
                            unsafe_allow_html=True,
                        )

                        for shift in SHIFTS:
                            k = (ds, shift)
                            all_keys.append(k)

                            st.checkbox(
                                f"{SHIFT_ICONS[shift]} {shift}",
                                value=(k in draft),
                                key=widget_key(
                                    key_prefix, year, month, day, shift
                                ),
                            )

        save = st.form_submit_button(
            "💾 Lưu lịch tháng",
            use_container_width=True,
        )

    if save:
        # Đọc TOÀN BỘ checkbox từ session state.
        new_draft = set()

        for ds, shift in all_keys:
            wkey = widget_key(
                key_prefix, year, month, int(ds[-2:]), shift
            )

            if st.session_state.get(wkey, False):
                new_draft.add((ds, shift))

        st.session_state[
            calendar_draft_key(username, year, month)
        ] = new_draft

        # Dùng cấu hình tháng hiện tại để tính giờ.
        settings = get_month_settings(username, year, month)

        if settings is None:
            settings = {
                "morning_hours": 0,
                "afternoon_hours": 0,
                "evening_hours": 0,
            }

        try:
            saved_count = sync_full_month(
                username, year, month, new_draft, settings,
            )

            # Dựng lại draft từ DB đã xác nhận.
            verified_df = get_month_attendance(username, year, month)

            verified = set()

            if not verified_df.empty:
                for _, row in verified_df.iterrows():
                    if bool(row.get("_scheduled", False)):
                        verified.add((
                            str(row["work_date"])[:10],
                            str(row["shift"]),
                        ))

            st.session_state[
                calendar_draft_key(username, year, month)
            ] = verified

            st.success(
                f"✅ Đã lưu {saved_count} ca. "
                f"Database xác nhận đúng {len(verified)} ca."
            )

            return verified

        except Exception as e:
            st.error("❌ Không thể lưu toàn bộ lịch tháng.")
            st.code(safe_error(e))

    return draft


# ============================================================
# MONTHLY SETTINGS
# ============================================================
def monthly_settings_form(username, year, month):
    current = get_month_settings(username, year, month)

    section(
        f"⚙️ Cấu hình tháng {month:02d}/{year}",
        "Nhập 1 lần mỗi tháng. Không cần nhập lại số giờ ở từng ngày.",
    )

    with st.form(f"settings_{username}_{year}_{month}"):
        c1, c2, c3, c4 = st.columns(4)

        morning = c1.number_input(
            "☀️ Sáng (giờ)",
            min_value=0.0,
            max_value=24.0,
            step=0.5,
            value=float(
                current.get("morning_hours", 4) if current else 4
            ),
        )

        afternoon = c2.number_input(
            "🌤️ Chiều (giờ)",
            min_value=0.0,
            max_value=24.0,
            step=0.5,
            value=float(
                current.get("afternoon_hours", 4) if current else 4
            ),
        )

        evening = c3.number_input(
            "🌙 Tối (giờ)",
            min_value=0.0,
            max_value=24.0,
            step=0.5,
            value=float(
                current.get("evening_hours", 4) if current else 4
            ),
        )

        hourly_rate = c4.number_input(
            "💰 Lương / giờ (đ)",
            min_value=0.0,
            step=1000.0,
            format="%.0f",
            value=float(
                current.get("hourly_rate", 0) if current else 0
            ),
        )

        if st.form_submit_button(
            "💾 Lưu cấu hình tháng",
            use_container_width=True,
        ):
            try:
                save_month_settings(
                    username, year, month,
                    morning, afternoon, evening, hourly_rate,
                )
                st.success("✅ Đã lưu cấu hình tháng.")
                st.rerun()

            except Exception as e:
                st.error("Không lưu được cấu hình tháng.")
                st.code(safe_error(e))

    return get_month_settings(username, year, month)


# ============================================================
# EMPLOYEE
# ============================================================
def employee_page():
    today = date.today()

    hero(
        f"Xin chào, {current_user['full_name']} 👋",
        "Tích ca trên lịch rồi lưu một lần cho cả tháng.",
        f"Hôm nay {today.strftime('%d/%m/%Y')}",
    )

    year, month = month_picker("emp_year", "emp_month")

    settings = monthly_settings_form(
        current_user["username"], year, month,
    )

    st.write("")
    section(
        "📅 Lịch chấm công",
        "Tích ca trên toàn bộ lịch → bấm Lưu lịch tháng một lần. "
        "Hệ thống không tự ghi từng checkbox.",
    )

    render_schedule_calendar(
        current_user["username"], year, month, "employee",
    )

    st.write("")

    df = get_month_attendance(current_user["username"], year, month)

    if not df.empty:
        df = df[df["_scheduled"]].copy()

    total_shifts, total_hours, total_salary, breakdown, hourly_rate = (
        summarize(df, settings)
    )

    section("📊 Tổng hợp tháng")
    kpi_cards(total_shifts, total_hours, total_salary, breakdown)

    section("📋 Các ca đã tích")

    if df.empty:
        st.info("Chưa có ca nào được lưu. Hãy tích ca trên lịch rồi bấm Lưu lịch tháng.")
        return

    report = build_report(df, settings, hourly_rate, vn_date=True)

    render_table(report)

    st.download_button(
        "⬇️ Xuất Excel",
        to_excel_bytes(report, "BangCong"),
        file_name=(
            f"Bang_cong_{current_user['username']}_"
            f"{year}_{month:02d}.xlsx"
        ),
        mime=XLSX_MIME,
        use_container_width=True,
    )


# ============================================================
# ADMIN
# ============================================================
def employee_options(users):
    employees = (
        users[users["role"] == "employee"]
        if not users.empty
        else pd.DataFrame()
    )

    if employees.empty:
        return {}

    return {
        f"{r['full_name']} ({r['username']})": r["username"]
        for _, r in employees.iterrows()
    }


def admin_page():
    hero(
        "🛠️ Trung tâm quản trị",
        "Quản lý nhân viên, xếp ca và theo dõi bảng lương.",
        f"Hôm nay {date.today().strftime('%d/%m/%Y')}",
    )

    users = get_users()

    tab1, tab2, tab3 = st.tabs([
        "👥 Nhân viên",
        "📅 Xếp ca",
        "💰 Bảng lương",
    ])

    # ---------------- Nhân viên ----------------
    with tab1:
        if users.empty:
            st.info("Chưa có tài khoản.")
        else:
            total = len(users)
            active_n = int(users["active"].sum())
            admin_n = int((users["role"] == "admin").sum())

            a, b, c = st.columns(3)
            a.metric("Tổng tài khoản", total)
            b.metric("Đang hoạt động", active_n)
            c.metric("Quản trị viên", admin_n)

            display = users.copy()

            display["Trạng thái"] = display["active"].map({
                True: "Đang hoạt động",
                False: "Đã khóa",
            })

            display = display.rename(columns={
                "username": "Tài khoản",
                "full_name": "Họ tên",
                "role": "Vai trò",
                "department": "Bộ phận",
                "position": "Chức vụ",
            })

            render_table(display[[
                    "Tài khoản", "Họ tên", "Vai trò",
                    "Bộ phận", "Chức vụ", "Trạng thái",
                ]])

        with st.expander("➕ Tạo tài khoản"):
            with st.form("create_user"):
                c1, c2 = st.columns(2)

                username = c1.text_input("Tên đăng nhập *")
                full_name = c1.text_input("Họ tên *")
                password = c1.text_input("Mật khẩu *", type="password")

                role = c2.selectbox("Vai trò", ["employee", "admin"])
                department = c2.text_input("Bộ phận")
                position = c2.text_input("Chức vụ")

                if st.form_submit_button(
                    "➕ Tạo tài khoản",
                    use_container_width=True,
                ):
                    if (
                        not username.strip()
                        or not full_name.strip()
                        or not password
                    ):
                        st.error("Nhập đủ thông tin.")
                    else:
                        try:
                            upsert_rows(
                                "users",
                                [{
                                    "username": username.strip(),
                                    "password_hash": sha256(password),
                                    "full_name": full_name.strip(),
                                    "role": role,
                                    "department": department.strip(),
                                    "position": position.strip(),
                                    "active": True,
                                }],
                                "username",
                            )
                            st.success("✅ Đã tạo tài khoản.")
                            st.rerun()
                        except Exception as e:
                            st.error("Không tạo được tài khoản.")
                            st.code(safe_error(e))

    # ---------------- Xếp ca ----------------
    with tab2:
        options = employee_options(users)

        if not options:
            st.info("Chưa có nhân viên.")
        else:
            label = st.selectbox(
                "Nhân viên",
                list(options.keys()),
                key="admin_schedule_user",
            )

            username = options[label]

            year, month = month_picker("admin_year", "admin_month")

            monthly_settings_form(username, year, month)

            st.write("")
            section(
                "📅 Lịch ca của nhân viên",
                "Tích ca rồi bấm Lưu lịch tháng một lần.",
            )

            render_schedule_calendar(username, year, month, "admin")

    # ---------------- Bảng lương ----------------
    with tab3:
        options = employee_options(users)

        if not options:
            st.info("Chưa có nhân viên.")
        else:
            label = st.selectbox(
                "Nhân viên",
                list(options.keys()),
                key="payroll_user",
            )

            username = options[label]

            year, month = month_picker("pay_year", "pay_month")

            settings = get_month_settings(username, year, month)

            if not settings:
                st.warning("Chưa có cấu hình tháng.")
                return

            df = get_month_attendance(username, year, month)

            if not df.empty:
                df = df[df["_scheduled"]].copy()

            total_shifts, total_hours, salary, breakdown, hourly_rate = (
                summarize(df, settings)
            )

            st.write("")
            kpi_cards(total_shifts, total_hours, salary, breakdown)

            if not df.empty:
                report = build_report(
                    df, settings, hourly_rate, vn_date=False,
                )

                render_table(report)

                st.download_button(
                    "⬇️ Xuất bảng lương",
                    to_excel_bytes(report, "BangLuong"),
                    file_name=f"Luong_{username}_{year}_{month:02d}.xlsx",
                    mime=XLSX_MIME,
                    use_container_width=True,
                )
            else:
                st.info("Tháng này chưa có ca nào được xếp.")


# ============================================================
# RUN
# ============================================================
if current_user["role"] == "admin":
    admin_page()
else:
    employee_page()
