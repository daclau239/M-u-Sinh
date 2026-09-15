
import streamlit as st
import pandas as pd
import requests
import hashlib
import hmac
import io
import calendar
from datetime import date, datetime

# ============================================================
# 🕘 WEB CHẤM CÔNG - LỊCH CA + GIỜ LÀM + LƯƠNG THEO GIỜ
# ============================================================
# Cơ chế:
# - Mỗi ngày trên lịch có 3 ca: Sáng / Chiều / Tối.
# - Admin/nhân viên có thể tích sẵn ca làm trên lịch.
# - Khi ca đã tích, chỉ cần nhập SỐ GIỜ thực tế của ca.
# - Mỗi tháng nhập LƯƠNG/ GIỜ một lần.
# - Hệ thống tự tính tổng giờ + tổng lương tháng.
# - Dữ liệu lưu trực tiếp trên Supabase.
#
# Streamlit Secrets:
# SUPABASE_URL = "https://....supabase.co"
# SUPABASE_SECRET_KEY = "sb_secret_..."
# ============================================================

st.set_page_config(
    page_title="Web Chấm Công",
    page_icon="🕘",
    layout="wide",
)

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"].strip().rstrip("/")
    SUPABASE_SECRET_KEY = st.secrets["SUPABASE_SECRET_KEY"].strip()
except Exception:
    SUPABASE_URL = ""
    SUPABASE_SECRET_KEY = ""

REST_URL = f"{SUPABASE_URL}/rest/v1" if SUPABASE_URL else ""

SHIFTS = ["Sáng", "Chiều", "Tối"]
SHIFT_ICONS = {"Sáng": "☀️", "Chiều": "🌤️", "Tối": "🌙"}

# ============================================================
# SQL
# ============================================================
SQL_SETUP = """
-- CHẤM CÔNG LỊCH 3 CA + GIỜ + LƯƠNG

-- Bảng users giữ nguyên từ hệ thống cũ.

-- 1. Thêm cột ca, giờ làm, tích ca
ALTER TABLE public.attendance
ADD COLUMN IF NOT EXISTS shift text;

ALTER TABLE public.attendance
ADD COLUMN IF NOT EXISTS hours numeric(8,2) DEFAULT 0;

ALTER TABLE public.attendance
ADD COLUMN IF NOT EXISTS scheduled boolean DEFAULT true;

UPDATE public.attendance
SET shift = 'Sáng'
WHERE shift IS NULL OR shift = '';

UPDATE public.attendance
SET hours = 0
WHERE hours IS NULL;

UPDATE public.attendance
SET scheduled = true
WHERE scheduled IS NULL;

ALTER TABLE public.attendance
ALTER COLUMN shift SET DEFAULT 'Sáng';

ALTER TABLE public.attendance
ALTER COLUMN shift SET NOT NULL;

ALTER TABLE public.attendance
ALTER COLUMN hours SET DEFAULT 0;

ALTER TABLE public.attendance
ALTER COLUMN scheduled SET DEFAULT true;

ALTER TABLE public.attendance
ALTER COLUMN hours SET NOT NULL;

ALTER TABLE public.attendance
ALTER COLUMN scheduled SET NOT NULL;

-- 2. Unique theo người + ngày + ca
ALTER TABLE public.attendance
DROP CONSTRAINT IF EXISTS attendance_username_work_date_key;

ALTER TABLE public.attendance
DROP CONSTRAINT IF EXISTS attendance_user_date_unique;

ALTER TABLE public.attendance
DROP CONSTRAINT IF EXISTS attendance_username_work_date_shift_key;

ALTER TABLE public.attendance
ADD CONSTRAINT attendance_username_work_date_shift_key
UNIQUE (username, work_date, shift);

-- 3. Bảng lương theo tháng
CREATE TABLE IF NOT EXISTS public.monthly_wages (
    id uuid primary key default gen_random_uuid(),
    username text not null,
    year integer not null,
    month integer not null,
    hourly_rate numeric(12,2) not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    UNIQUE(username, year, month)
);

CREATE INDEX IF NOT EXISTS attendance_calendar_idx
ON public.attendance(username, work_date, shift);

CREATE INDEX IF NOT EXISTS monthly_wages_lookup_idx
ON public.monthly_wages(username, year, month);
"""

# ============================================================
# CSS
# ============================================================
st.markdown("""
<style>
.block-container {padding-top: 1.5rem;}
.main-title {font-size: 2.05rem;font-weight:800;margin-bottom:.15rem;}
.sub-title {color:#6b7280;margin-bottom:1rem;}
.calendar-day {
    border:1px solid #e5e7eb;
    border-radius:14px;
    padding:8px;
    margin-bottom:6px;
    min-height:145px;
}
.day-number {font-weight:800;font-size:17px;margin-bottom:4px;}
.rate-box {
    border:1px solid #e5e7eb;
    border-radius:14px;
    padding:16px;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# SUPABASE
# ============================================================
def headers():
    return {
        "apikey": SUPABASE_SECRET_KEY,
        "Content-Type": "application/json",
    }

def sb_request(method, table, params=None, payload=None, prefer=None):
    if not REST_URL or not SUPABASE_SECRET_KEY:
        raise RuntimeError("Thiếu Supabase Secrets.")

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

def insert_row(table, payload):
    return sb_request(
        "POST", table, payload=payload,
        prefer="return=representation"
    )

def upsert_row(table, payload):
    return sb_request(
        "POST", table, payload=payload,
        prefer="resolution=merge-duplicates,return=representation"
    )

def update_rows(table, params, payload):
    return sb_request(
        "PATCH", table, params=params, payload=payload,
        prefer="return=representation"
    )

def delete_rows(table, params):
    return sb_request(
        "DELETE", table, params=params,
        prefer="return=minimal"
    )

def safe_error(e):
    s = str(e)
    if SUPABASE_SECRET_KEY:
        s = s.replace(SUPABASE_SECRET_KEY, "[HIDDEN]")
    return s

def sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

# ============================================================
# DATA HELPERS
# ============================================================
def get_user(username):
    rows = select_rows("users", {
        "select": "*",
        "username": f"eq.{username}",
        "limit": "1",
    })
    return rows[0] if rows else None

def get_users_df():
    return pd.DataFrame(select_rows("users", {
        "select": "*",
        "order": "created_at.asc",
    }))

def get_attendance_df(username=None, year=None, month=None):
    params = {
        "select": "*",
        "order": "work_date.asc,shift.asc",
    }

    filters = []

    if username:
        filters.append(("username", f"eq.{username}"))

    if year is not None and month is not None:
        first = f"{int(year):04d}-{int(month):02d}-01"
        last_day = calendar.monthrange(int(year), int(month))[1]
        last = f"{int(year):04d}-{int(month):02d}-{last_day:02d}"
        filters.append(("work_date", f"gte.{first}"))
        filters.append(("work_date", f"lte.{last}"))

    for key, value in filters:
        params[key] = value

    return pd.DataFrame(select_rows("attendance", params))

def get_shift(username, work_date, shift):
    rows = select_rows("attendance", {
        "select": "*",
        "username": f"eq.{username}",
        "work_date": f"eq.{work_date}",
        "shift": f"eq.{shift}",
        "limit": "1",
    })
    return rows[0] if rows else None

def save_shift(username, work_date, shift, scheduled, hours, note=""):
    return upsert_row("attendance", {
        "username": username,
        "work_date": work_date,
        "shift": shift,
        "scheduled": bool(scheduled),
        "hours": float(hours),
        "check_in": "",
        "check_out": "",
        "status": "Đã chấm" if scheduled else "",
        "note": note,
        "updated_at": datetime.utcnow().isoformat(),
    })

def delete_shift(username, work_date, shift):
    return delete_rows("attendance", {
        "username": f"eq.{username}",
        "work_date": f"eq.{work_date}",
        "shift": f"eq.{shift}",
    })

def get_wage(username, year, month):
    rows = select_rows("monthly_wages", {
        "select": "*",
        "username": f"eq.{username}",
        "year": f"eq.{int(year)}",
        "month": f"eq.{int(month)}",
        "limit": "1",
    })
    return rows[0] if rows else None

def save_wage(username, year, month, hourly_rate):
    return upsert_row("monthly_wages", {
        "username": username,
        "year": int(year),
        "month": int(month),
        "hourly_rate": float(hourly_rate),
        "updated_at": datetime.utcnow().isoformat(),
    })

def authenticate(username, password):
    user = get_user(username.strip())
    if not user or not bool(user.get("active")):
        return None

    if hmac.compare_digest(
        str(user.get("password_hash", "")),
        sha256(password)
    ):
        return user

    return None

# ============================================================
# CONFIG CHECK
# ============================================================
if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    st.title("🕘 WEB CHẤM CÔNG")
    st.warning("Chưa cấu hình Supabase.")
    st.code(
        'SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"\n'
        'SUPABASE_SECRET_KEY = "sb_secret_..."',
        language="toml",
    )
    st.stop()

try:
    select_rows("users", {"select": "id", "limit": "1"})
    select_rows("attendance", {"select": "id,shift,hours,scheduled", "limit": "1"})
    select_rows("monthly_wages", {"select": "id", "limit": "1"})
except Exception as e:
    st.error("❌ Database chưa đủ cột/bảng cho phiên bản này.")
    st.code(safe_error(e))
    st.markdown(
        "Vào **Supabase → SQL Editor → New query**, chạy toàn bộ "
        "SQL `SQL_SETUP` trong file Python này một lần."
    )
    st.code(SQL_SETUP, language="sql")
    st.stop()

# ============================================================
# LOGIN
# ============================================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.markdown(
        '<div class="main-title">🕘 WEB CHẤM CÔNG</div>',
        unsafe_allow_html=True
    )
    st.caption("Lịch ca 3 ca/ngày · Nhập giờ · Tự tính lương")

    with st.form("login"):
        username = st.text_input("Tên đăng nhập")
        password = st.text_input("Mật khẩu", type="password")

        if st.form_submit_button(
            "🔐 ĐĂNG NHẬP",
            use_container_width=True
        ):
            try:
                user = authenticate(username, password)
                if user:
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
    st.markdown("## 🕘 CHẤM CÔNG")
    st.write(f"👤 **{current_user['full_name']}**")
    st.caption(f"`{current_user['username']}`")
    st.divider()

    if st.button("🚪 Đăng xuất", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# ============================================================
# CALENDAR
# ============================================================
def render_calendar(username, key_prefix):
    today = date.today()

    c1, c2 = st.columns(2)
    year = c1.number_input(
        "Năm", 2020, 2100, today.year,
        key=f"{key_prefix}_year"
    )
    month = c2.selectbox(
        "Tháng", range(1, 13), today.month - 1,
        key=f"{key_prefix}_month"
    )

    df = get_attendance_df(username, int(year), int(month))
    records = {}

    if not df.empty:
        df["work_date"] = df["work_date"].astype(str).str[:10]
        for _, r in df.iterrows():
            ds = r["work_date"]
            records.setdefault(ds, {})[str(r.get("shift", "Sáng"))] = r.to_dict()

    st.caption("☀️ Sáng · 🌤️ Chiều · 🌙 Tối — **tích trực tiếp vào ca muốn làm**.")

    # Nút tích ca: mỗi ngày 3 ô checkbox.
    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(
        int(year), int(month)
    )
    weekdays = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

    head = st.columns(7)
    for i, w in enumerate(weekdays):
        head[i].markdown(
            f"<div style='text-align:center;font-weight:700'>{w}</div>",
            unsafe_allow_html=True
        )

    for week in weeks:
        cols = st.columns(7)

        for idx, day in enumerate(week):
            with cols[idx]:
                if day == 0:
                    st.markdown("<div style='min-height:150px'></div>", unsafe_allow_html=True)
                    continue

                ds = f"{int(year):04d}-{int(month):02d}-{day:02d}"
                day_records = records.get(ds, {})

                st.markdown(
                    f"<div class='day-number'>{day}</div>",
                    unsafe_allow_html=True
                )

                for shift in SHIFTS:
                    rec = day_records.get(shift)
                    checked = bool(rec and rec.get("scheduled", True))
                    hours = float(rec.get("hours", 0) or 0) if rec else 0

                    new_checked = st.checkbox(
                        f"{SHIFT_ICONS[shift]} {shift}",
                        value=checked,
                        key=f"{key_prefix}_{ds}_{shift}",
                    )

                    if new_checked != checked:
                        try:
                            if new_checked:
                                save_shift(
                                    username, ds, shift,
                                    True, hours,
                                    rec.get("note", "") if rec else ""
                                )
                            else:
                                delete_shift(username, ds, shift)
                            st.rerun()
                        except Exception as e:
                            st.error(safe_error(e))

                    if checked:
                        st.caption(f"{hours:g} giờ")

    selected_date = st.session_state.get(
        f"{key_prefix}_selected_date",
        today.isoformat()
    )

    return int(year), int(month), selected_date

# ============================================================
# EMPLOYEE
# ============================================================
def employee_page():
    st.markdown(
        f'<div class="main-title">Xin chào, {current_user["full_name"]} 👋</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        "### 📅 Lịch làm việc"
    )
    st.caption(
        "Chỉ cần **tích ca** trên lịch. Sau đó nhập số giờ thực tế cho các ca đã tích."
    )

    year, month, _ = render_calendar(
        current_user["username"],
        "emp_cal"
    )

    st.divider()

    st.subheader("⏱️ Nhập số giờ theo ca")

    df = get_attendance_df(
        current_user["username"],
        year,
        month
    )

    if df.empty:
        st.info("Chưa có ca nào được tích trong tháng này.")
    else:
        df["work_date"] = df["work_date"].astype(str).str[:10]
        df = df[df["scheduled"] == True].copy()
        df = df.sort_values(["work_date", "shift"])

        if df.empty:
            st.info("Chưa có ca nào được tích.")
        else:
            for _, r in df.iterrows():
                ds = r["work_date"]
                shift = r["shift"]
                pretty = datetime.strptime(
                    ds, "%Y-%m-%d"
                ).strftime("%d/%m/%Y")

                with st.container(border=True):
                    c1, c2, c3 = st.columns([2, 2, 3])

                    c1.markdown(
                        f"**{pretty}**  \n"
                        f"{SHIFT_ICONS.get(shift, '🕘')} **Ca {shift}**"
                    )

                    current_hours = float(r.get("hours", 0) or 0)

                    hours = c2.number_input(
                        "Số giờ",
                        min_value=0.0,
                        max_value=24.0,
                        value=current_hours,
                        step=0.5,
                        key=f"hours_{ds}_{shift}",
                    )

                    note = c3.text_input(
                        "Ghi chú",
                        value=str(r.get("note", "") or ""),
                        key=f"note_{ds}_{shift}",
                    )

                    if st.button(
                        "💾 Lưu",
                        key=f"save_{ds}_{shift}",
                    ):
                        try:
                            save_shift(
                                current_user["username"],
                                ds,
                                shift,
                                True,
                                hours,
                                note,
                            )
                            st.success(
                                f"Đã lưu {pretty} - ca {shift}."
                            )
                            st.rerun()
                        except Exception as e:
                            st.error(safe_error(e))

    # --------------------------------------------------------
    # LƯƠNG THÁNG
    # --------------------------------------------------------
    st.divider()
    st.subheader("💰 Lương theo giờ")

    wage = get_wage(
        current_user["username"],
        year,
        month
    )

    old_rate = float(
        wage.get("hourly_rate", 0) if wage else 0
    )

    c1, c2 = st.columns([2, 1])

    rate = c1.number_input(
        "Lương / giờ (nhập 1 lần cho tháng này)",
        min_value=0.0,
        value=old_rate,
        step=1000.0,
        format="%.0f",
        key=f"rate_{year}_{month}",
    )

    if c2.button(
        "💾 LƯU LƯƠNG THÁNG",
        use_container_width=True
    ):
        try:
            save_wage(
                current_user["username"],
                year,
                month,
                rate
            )
            st.success("Đã lưu mức lương tháng.")
            st.rerun()
        except Exception as e:
            st.error(safe_error(e))

    month_df = get_attendance_df(
        current_user["username"],
        year,
        month
    )

    total_hours = 0.0
    if not month_df.empty:
        month_df = month_df[month_df["scheduled"] == True]
        total_hours = float(
            pd.to_numeric(
                month_df["hours"],
                errors="coerce"
            ).fillna(0).sum()
        )

    salary = total_hours * rate

    a, b = st.columns(2)
    a.metric("⏱️ Tổng giờ", f"{total_hours:g} giờ")
    b.metric("💵 Tổng lương", f"{salary:,.0f} đ")

    # Excel
    st.divider()
    if not month_df.empty:
        export = month_df[[
            "work_date",
            "shift",
            "hours",
            "status",
            "note"
        ]].copy()

        export["work_date"] = export["work_date"].astype(str).str[:10]
        export = export.rename(columns={
            "work_date": "Ngày",
            "shift": "Ca",
            "hours": "Số giờ",
            "status": "Trạng thái",
            "note": "Ghi chú",
        })

        export["Lương/giờ"] = rate
        export["Tiền lương"] = export["Số giờ"] * rate

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            export.to_excel(
                writer,
                index=False,
                sheet_name="BangCong"
            )

        output.seek(0)

        st.download_button(
            "⬇️ XUẤT BẢNG CÔNG + LƯƠNG",
            output.getvalue(),
            file_name=(
                f"Bang_cong_luong_{year}_{month:02d}.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            use_container_width=True
        )

# ============================================================
# ADMIN
# ============================================================
def admin_page():
    st.markdown(
        '<div class="main-title">🛠️ TRUNG TÂM QUẢN TRỊ</div>',
        unsafe_allow_html=True
    )

    users = get_users_df()

    tab1, tab2, tab3 = st.tabs([
        "👥 Nhân viên",
        "📅 Xếp ca trên lịch",
        "💰 Bảng lương",
    ])

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------
    with tab1:
        if users.empty:
            st.info("Chưa có tài khoản.")
        else:
            display = users.copy()
            display["Trạng thái"] = display["active"].map({
                True: "Đang hoạt động",
                False: "Đã khóa",
            })

            st.dataframe(
                display.rename(columns={
                    "username": "Tài khoản",
                    "full_name": "Họ tên",
                    "role": "Vai trò",
                    "department": "Bộ phận",
                    "position": "Chức vụ",
                })[[
                    "Tài khoản",
                    "Họ tên",
                    "Vai trò",
                    "Bộ phận",
                    "Chức vụ",
                    "Trạng thái",
                ]],
                use_container_width=True,
                hide_index=True,
            )

    # --------------------------------------------------------
    # ADMIN SCHEDULE
    # --------------------------------------------------------
    with tab2:
        employees = users[
            users["role"] == "employee"
        ] if not users.empty else pd.DataFrame()

        if employees.empty:
            st.info("Chưa có nhân viên.")
        else:
            options = {
                f"{r['full_name']} ({r['username']})":
                r["username"]
                for _, r in employees.iterrows()
            }

            label = st.selectbox(
                "Chọn nhân viên",
                list(options.keys()),
                key="admin_schedule_user"
            )

            username = options[label]

            st.info(
                "Tích ☀️ Sáng / 🌤️ Chiều / 🌙 Tối trực tiếp trên lịch "
                "để xếp ca cho nhân viên."
            )

            render_calendar(
                username,
                "admin_cal"
            )

    # --------------------------------------------------------
    # PAYROLL
    # --------------------------------------------------------
    with tab3:
        employees = users[
            users["role"] == "employee"
        ] if not users.empty else pd.DataFrame()

        if employees.empty:
            st.info("Chưa có nhân viên.")
            return

        options = {
            f"{r['full_name']} ({r['username']})":
            r["username"]
            for _, r in employees.iterrows()
        }

        label = st.selectbox(
            "Nhân viên",
            list(options.keys()),
            key="payroll_user"
        )
        username = options[label]

        c1, c2 = st.columns(2)

        today = date.today()

        year = c1.number_input(
            "Năm",
            2020,
            2100,
            today.year,
            key="payroll_year"
        )

        month = c2.selectbox(
            "Tháng",
            range(1, 13),
            today.month - 1,
            key="payroll_month"
        )

        wage = get_wage(username, year, month)
        rate = float(
            wage.get("hourly_rate", 0)
            if wage else 0
        )

        c1, c2 = st.columns([2, 1])

        new_rate = c1.number_input(
            "Lương / giờ",
            min_value=0.0,
            value=rate,
            step=1000.0,
            format="%.0f",
            key="admin_rate"
        )

        if c2.button(
            "💾 LƯU",
            use_container_width=True
        ):
            try:
                save_wage(
                    username,
                    year,
                    month,
                    new_rate
                )
                st.success("Đã lưu lương theo giờ.")
                st.rerun()
            except Exception as e:
                st.error(safe_error(e))

        df = get_attendance_df(
            username,
            year,
            month
        )

        if df.empty:
            total_hours = 0.0
            st.info("Chưa có ca.")
        else:
            df = df[df["scheduled"] == True].copy()
            total_hours = float(
                pd.to_numeric(
                    df["hours"],
                    errors="coerce"
                ).fillna(0).sum()
            )

            report = df[[
                "work_date",
                "shift",
                "hours",
                "note"
            ]].copy()

            report = report.rename(columns={
                "work_date": "Ngày",
                "shift": "Ca",
                "hours": "Số giờ",
                "note": "Ghi chú",
            })

            report["Lương/giờ"] = new_rate
            report["Tiền lương"] = (
                report["Số giờ"] * new_rate
            )

            st.dataframe(
                report,
                use_container_width=True,
                hide_index=True
            )

        salary = total_hours * new_rate

        a, b = st.columns(2)
        a.metric("⏱️ Tổng giờ", f"{total_hours:g} giờ")
        b.metric("💵 Tổng lương", f"{salary:,.0f} đ")

        if not df.empty:
            output = io.BytesIO()
            with pd.ExcelWriter(
                output,
                engine="openpyxl"
            ) as writer:
                report.to_excel(
                    writer,
                    index=False,
                    sheet_name="BangLuong"
                )

            output.seek(0)

            st.download_button(
                "⬇️ XUẤT BẢNG LƯƠNG",
                output.getvalue(),
                file_name=(
                    f"Luong_{username}_"
                    f"{year}_{month:02d}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                use_container_width=True
            )

# ============================================================
# RUN
# ============================================================
if current_user["role"] == "admin":
    admin_page()
else:
    employee_page()
