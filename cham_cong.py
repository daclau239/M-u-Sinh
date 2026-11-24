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
#   Mực đậm  #12232B   (chữ, sidebar, banner)
#   Xanh ngọc #0E7C7B  (màu chính)
#   Nền       #F2F5F6
#   Ca Sáng   #C77F00 / nền #FFF3D6
#   Ca Chiều  #1C77B0 / nền #E0F0FA
#   Ca Tối    #5646B0 / nền #ECE8FA
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap');

:root {
    --ink: #12232B;
    --ink-soft: #1C3540;
    --teal: #0E7C7B;
    --teal-dark: #0A5C5B;
    --teal-tint: #E3F3F2;
    --bg: #F2F5F6;
    --card: #FFFFFF;
    --line: #DDE5E8;
    --muted: #64757D;
    --sang: #C77F00;  --sang-bg: #FFF3D6;
    --chieu: #1C77B0; --chieu-bg: #E0F0FA;
    --toi: #5646B0;   --toi-bg: #ECE8FA;
}

/* ---------- Nền & font ---------- */
.stApp { background: var(--bg); }

.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea,
.stApp button, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp [data-baseweb="select"], .stApp [data-testid="stMarkdownContainer"] {
    font-family: 'Be Vietnam Pro', 'Segoe UI', sans-serif;
}

.block-container {
    padding-top: 1.6rem;
    padding-bottom: 3rem;
    max-width: 1280px;
}

header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }

h2, h3 { color: var(--ink); font-weight: 700; letter-spacing: -0.01em; }

/* ---------- Banner đầu trang ---------- */
.hero {
    background: linear-gradient(120deg, var(--ink) 0%, var(--ink-soft) 70%, #1E4650 100%);
    color: #fff;
    border-radius: 20px;
    padding: 26px 30px;
    margin-bottom: 22px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
}
.hero-title { font-size: 1.75rem; font-weight: 800; line-height: 1.25; letter-spacing: -0.015em; }
.hero-sub { color: #A9C2C9; font-size: 0.95rem; margin-top: 4px; }
.hero-chip {
    background: rgba(255,255,255,0.10);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 999px;
    padding: 8px 16px;
    font-size: 0.88rem;
    font-weight: 600;
    white-space: nowrap;
}

/* ---------- Tiêu đề mục ---------- */
.section-title {
    font-size: 1.15rem; font-weight: 700; color: var(--ink);
    margin: 6px 0 2px 0;
}
.section-sub { color: var(--muted); font-size: 0.9rem; margin-bottom: 10px; }

/* ---------- Thẻ KPI ---------- */
.kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 8px 0 18px; }
.kpi {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 18px 20px;
    border-left: 5px solid var(--teal);
}
.kpi.hours { border-left-color: var(--chieu); }
.kpi.money { border-left-color: var(--sang); }
.kpi-label { color: var(--muted); font-size: 0.85rem; font-weight: 500; }
.kpi-value { color: var(--ink); font-size: 1.85rem; font-weight: 800; line-height: 1.2; margin-top: 2px; }
.kpi-note { color: var(--muted); font-size: 0.82rem; margin-top: 4px; }
@media (max-width: 760px) { .kpi-grid { grid-template-columns: 1fr; } }

/* ---------- Chú thích ca ---------- */
.legend { display: flex; gap: 10px; flex-wrap: wrap; margin: 4px 0 12px; }
.legend span {
    font-size: 0.85rem; font-weight: 600; border-radius: 999px; padding: 5px 13px;
}
.legend .l-sang  { background: var(--sang-bg);  color: var(--sang); }
.legend .l-chieu { background: var(--chieu-bg); color: var(--chieu); }
.legend .l-toi   { background: var(--toi-bg);   color: var(--toi); }

/* ---------- Form & thẻ ---------- */
[data-testid="stForm"] {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 18px;
    padding: 20px 22px;
    box-shadow: 0 1px 2px rgba(18,35,43,0.04);
}

/* ---------- Ô lịch ---------- */
[class*="st-key-calendar_form"] [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    overflow-x: auto;
    gap: 8px;
}
[class*="st-key-calendar_form"] [data-testid="stColumn"] { min-width: 128px !important; }

[class*="st-key-calendar_form"] [data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid var(--line);
    border-radius: 14px;
    background: #FBFCFC;
    padding: 2px 4px 4px;
}

.wd-head {
    text-align: center; font-weight: 700; font-size: 0.85rem;
    color: var(--muted); padding: 6px 0;
}
.wd-head.weekend { color: #B4452F; }

.day-number {
    font-weight: 800; font-size: 1rem; color: var(--ink);
    margin: 2px 0 4px 2px;
    display: inline-block; min-width: 28px; text-align: center;
    border-radius: 999px; padding: 1px 6px;
}
.day-number.today { background: var(--teal); color: #fff; }
.day-number.weekend { color: #B4452F; }
.day-count { float: right; font-size: 0.72rem; color: var(--muted); font-weight: 600; margin-top: 5px; }

/* Checkbox ca — tô màu theo từng ca */
[class*="st-key-cal_"] [data-testid="stCheckbox"] {
    border-radius: 9px;
    padding: 3px 8px;
    margin-bottom: 4px;
    border: 1px solid transparent;
    transition: background 0.15s, border-color 0.15s;
}
[class*="st-key-cal_"] [data-testid="stCheckbox"] label p { font-size: 0.85rem; font-weight: 600; }

[class*="st-key-cal_"][class*="_sang"]  [data-testid="stCheckbox"] { background: var(--sang-bg);  color: var(--sang); }
[class*="st-key-cal_"][class*="_chieu"] [data-testid="stCheckbox"] { background: var(--chieu-bg); color: var(--chieu); }
[class*="st-key-cal_"][class*="_toi"]   [data-testid="stCheckbox"] { background: var(--toi-bg);   color: var(--toi); }

[class*="st-key-cal_"][class*="_sang"]  [data-testid="stCheckbox"]:has(input:checked) { border-color: var(--sang);  background: #FFE6A8; }
[class*="st-key-cal_"][class*="_chieu"] [data-testid="stCheckbox"]:has(input:checked) { border-color: var(--chieu); background: #BFE0F5; }
[class*="st-key-cal_"][class*="_toi"]   [data-testid="stCheckbox"]:has(input:checked) { border-color: var(--toi);   background: #D8D1F6; }

[class*="st-key-cal_"] [data-testid="stCheckbox"] label p { color: inherit; }

/* ---------- Nút ---------- */
.stApp .stButton > button,
.stApp [data-testid="stFormSubmitButton"] > button,
.stApp [data-testid="stDownloadButton"] > button {
    border-radius: 12px;
    font-weight: 700;
    border: 1px solid var(--line);
    padding: 0.6rem 1rem;
    transition: transform 0.08s, box-shadow 0.15s;
}
.stApp [data-testid="stFormSubmitButton"] > button,
.stApp [data-testid="stDownloadButton"] > button {
    background: var(--teal);
    color: #fff;
    border-color: var(--teal);
}
.stApp [data-testid="stFormSubmitButton"] > button:hover,
.stApp [data-testid="stDownloadButton"] > button:hover {
    background: var(--teal-dark);
    border-color: var(--teal-dark);
    color: #fff;
    box-shadow: 0 4px 14px rgba(14,124,123,0.28);
}
.stApp [data-testid="stFormSubmitButton"] > button:active { transform: scale(0.99); }

/* ---------- Ô nhập ---------- */
.stApp [data-baseweb="input"], .stApp [data-baseweb="select"] > div {
    border-radius: 10px;
}

/* ---------- Tab ---------- */
.stTabs [data-baseweb="tab-list"] {
    gap: 6px; background: var(--card); padding: 6px;
    border-radius: 14px; border: 1px solid var(--line);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px; padding: 8px 18px; font-weight: 600; height: auto;
}
.stTabs [aria-selected="true"] { background: var(--teal-tint); color: var(--teal-dark); }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none; }

/* ---------- Bảng ---------- */
[data-testid="stDataFrame"] {
    border: 1px solid var(--line); border-radius: 14px; overflow: hidden;
}

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] { background: var(--ink); }
[data-testid="stSidebar"] * { color: #E6EEF0; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.12); }
[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.18);
    color: #fff;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.16);
    border-color: rgba(255,255,255,0.3);
}
.side-brand { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.01em; }
.side-card {
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 14px; padding: 14px; margin-top: 10px;
}
.avatar {
    width: 42px; height: 42px; border-radius: 50%;
    background: var(--teal); color: #fff !important;
    display: flex; align-items: center; justify-content: center;
    font-weight: 800; font-size: 1.05rem; margin-bottom: 8px;
}
.side-name { font-weight: 700; font-size: 1rem; }
.side-meta { color: #9DB5BC !important; font-size: 0.82rem; }
.role-pill {
    display: inline-block; margin-top: 8px; padding: 2px 10px; border-radius: 999px;
    background: rgba(14,124,123,0.35); font-size: 0.78rem; font-weight: 600;
}

/* ---------- Đăng nhập ---------- */
.login-brand { text-align: center; margin: 3vh 0 18px; }
.login-logo {
    width: 64px; height: 64px; border-radius: 18px; margin: 0 auto 12px;
    background: linear-gradient(135deg, var(--teal), var(--ink));
    display: flex; align-items: center; justify-content: center; font-size: 1.9rem;
}
.login-title { font-size: 1.7rem; font-weight: 800; color: var(--ink); letter-spacing: -0.015em; }
.login-sub { color: var(--muted); font-size: 0.92rem; margin-top: 4px; }
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

    st.dataframe(report, use_container_width=True, hide_index=True)

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

            st.dataframe(
                display[[
                    "Tài khoản", "Họ tên", "Vai trò",
                    "Bộ phận", "Chức vụ", "Trạng thái",
                ]],
                use_container_width=True,
                hide_index=True,
            )

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

                st.dataframe(
                    report,
                    use_container_width=True,
                    hide_index=True,
                )

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
