
import streamlit as st
import pandas as pd
import requests
import hashlib
import hmac
import io
import calendar
from datetime import date, datetime

# ============================================================
# 🕘 CHẤM CÔNG LỊCH 3 CA — BẢN ỔN ĐỊNH
# ============================================================
# Luồng:
# 1) Mở lịch tháng.
# 2) Tick ca Sáng / Chiều / Tối.
# 3) Checkbox chỉ thay đổi "bản nháp" trong session.
# 4) Bấm DUY NHẤT 1 LẦN: "LƯU LỊCH THÁNG".
# 5) App đồng bộ TOÀN BỘ tháng lên Supabase.
#
# Không lưu database khi người dùng chỉ mới tick.
# Vì vậy không có chuyện tick 15 nhưng database chỉ có 9.
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
    # Quan trọng: lấy TOÀN BỘ attendance của user,
    # sau đó lọc tháng trong Python.
    # Không truyền đồng thời gte/lte bằng dict cùng key.
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

    df["work_date"] = (
        df["work_date"].astype(str).str[:10]
    )

    prefix = f"{int(year):04d}-{int(month):02d}-"

    df = df[
        df["work_date"].str.startswith(prefix)
    ].copy()

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

    current = get_month_attendance(
        username,
        year,
        month,
    )

    existing_keys = set()

    if not current.empty:
        for _, row in current.iterrows():
            if bool(row.get("_scheduled", False)):
                existing_keys.add((
                    str(row["work_date"])[:10],
                    str(row.get("shift", "Sáng")),
                ))

    # Toàn bộ ca đang tick.
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
    verified = get_month_attendance(
        username,
        year,
        month,
    )

    saved_count = (
        int(verified["_scheduled"].sum())
        if not verified.empty
        else 0
    )

    return saved_count


# ============================================================
# CSS
# ============================================================
st.markdown(
    """
<style>
.block-container {
    padding-top: 1.5rem;
}

.app-title {
    font-size: 2.1rem;
    font-weight: 800;
}

.muted {
    color: #6b7280;
}

.calendar-cell {
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    padding: 7px;
    min-height: 150px;
    margin-bottom: 8px;
}

.day-number {
    font-weight: 800;
    font-size: 17px;
    margin-bottom: 5px;
}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# CONFIG CHECK
# ============================================================
if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    st.markdown(
        '<div class="app-title">🕘 WEB CHẤM CÔNG</div>',
        unsafe_allow_html=True,
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
    select_rows(
        "users",
        {"select": "id", "limit": "1"},
    )

    select_rows(
        "attendance",
        {
            "select": "id,work_date,shift,scheduled,hours",
            "limit": "1",
        },
    )

    select_rows(
        "monthly_shift_settings",
        {"select": "id", "limit": "1"},
    )

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
    st.markdown(
        '<div class="app-title">🕘 WEB CHẤM CÔNG</div>',
        unsafe_allow_html=True,
    )

    st.caption(
        "Lịch 3 ca • Tích ca • Tự tính giờ • Tự tính lương"
    )

    with st.form("login"):
        username = st.text_input("Tên đăng nhập")
        password = st.text_input(
            "Mật khẩu",
            type="password",
        )

        if st.form_submit_button(
            "🔐 ĐĂNG NHẬP",
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
                    st.error(
                        "Sai tài khoản hoặc mật khẩu."
                    )

            except Exception as e:
                st.error("Lỗi đăng nhập.")
                st.code(safe_error(e))

    st.caption(
        "Admin mặc định: admin / admin123"
    )

    st.stop()


current_user = get_user(
    st.session_state.username
)

if not current_user or not bool(
    current_user.get("active")
):
    st.session_state.clear()
    st.error(
        "Tài khoản không tồn tại hoặc đã bị khóa."
    )
    st.stop()


# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown("## 🕘 CHẤM CÔNG")
    st.write(
        f"👤 **{current_user['full_name']}**"
    )
    st.caption(
        f"`{current_user['username']}`"
    )
    st.caption(
        f"Vai trò: `{current_user['role']}`"
    )

    st.divider()

    if st.button(
        "🚪 Đăng xuất",
        use_container_width=True,
    ):
        st.session_state.clear()
        st.rerun()


# ============================================================
# CALENDAR DRAFT
# ============================================================
def calendar_draft_key(username, year, month):
    return f"draft_{username}_{int(year)}_{int(month):02d}"


def load_draft(username, year, month):
    key = calendar_draft_key(
        username, year, month
    )

    if key in st.session_state:
        return st.session_state[key]

    df = get_month_attendance(
        username,
        year,
        month,
    )

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


def render_schedule_calendar(
    username,
    year,
    month,
    key_prefix,
):
    draft = load_draft(
        username,
        year,
        month,
    )

    # Khóa tháng hiện tại bằng form.
    with st.form(
        f"calendar_form_{key_prefix}_{year}_{month}"
    ):
        weeks = calendar.Calendar(
            firstweekday=0
        ).monthdayscalendar(
            int(year),
            int(month),
        )

        weekdays = [
            "T2", "T3", "T4",
            "T5", "T6", "T7", "CN"
        ]

        header = st.columns(7)

        for i, wd in enumerate(weekdays):
            header[i].markdown(
                f"<div style='text-align:center;font-weight:700'>{wd}</div>",
                unsafe_allow_html=True,
            )

        # IMPORTANT:
        # Không lưu database tại checkbox.
        # Checkbox chỉ cập nhật vào draft khi form submit.
        all_keys = []

        for week in weeks:
            cols = st.columns(7)

            for col_idx, day in enumerate(week):
                with cols[col_idx]:

                    if day == 0:
                        st.markdown(
                            "<div style='min-height:165px'></div>",
                            unsafe_allow_html=True,
                        )
                        continue

                    ds = (
                        f"{int(year):04d}-"
                        f"{int(month):02d}-"
                        f"{int(day):02d}"
                    )

                    st.markdown(
                        f"<div class='day-number'>{day}</div>",
                        unsafe_allow_html=True,
                    )

                    for shift in SHIFTS:
                        k = (ds, shift)
                        all_keys.append(k)

                        st.checkbox(
                            f"{SHIFT_ICONS[shift]} {shift}",
                            value=(k in draft),
                            key=(
                                f"{key_prefix}_"
                                f"{int(year)}_{int(month):02d}_"
                                f"{day}_{shift}"
                            ),
                        )

        save = st.form_submit_button(
            "💾 LƯU LỊCH THÁNG",
            use_container_width=True,
        )

    if save:
        # Read EVERY checkbox from session state.
        new_draft = set()

        for day_key in all_keys:
            ds, shift = day_key

            widget_key = (
                f"{key_prefix}_"
                f"{int(year)}_{int(month):02d}_"
                f"{int(ds[-2:])}_{shift}"
            )

            if st.session_state.get(
                widget_key,
                False,
            ):
                new_draft.add(
                    (ds, shift)
                )

        # Replace the draft with the complete month state.
        st.session_state[
            calendar_draft_key(
                username,
                year,
                month,
            )
        ] = new_draft

        # Use current month settings for hours.
        settings = get_month_settings(
            username,
            year,
            month,
        )

        if settings is None:
            settings = {
                "morning_hours": 0,
                "afternoon_hours": 0,
                "evening_hours": 0,
            }

        try:
            saved_count = sync_full_month(
                username,
                year,
                month,
                new_draft,
                settings,
            )

            # Rebuild draft directly from verified DB.
            verified_df = get_month_attendance(
                username,
                year,
                month,
            )

            verified = set()

            if not verified_df.empty:
                for _, row in verified_df.iterrows():
                    if bool(
                        row.get(
                            "_scheduled",
                            False,
                        )
                    ):
                        verified.add(
                            (
                                str(row["work_date"])[:10],
                                str(row["shift"]),
                            )
                        )

            st.session_state[
                calendar_draft_key(
                    username,
                    year,
                    month,
                )
            ] = verified

            st.success(
                f"✅ ĐÃ LƯU: {saved_count} CA. "
                f"Database đã xác nhận đúng {len(verified)} CA."
            )

            return verified

        except Exception as e:
            st.error(
                "❌ Không thể lưu toàn bộ lịch tháng."
            )
            st.code(
                safe_error(e)
            )

    return draft


# ============================================================
# MONTHLY SETTINGS
# ============================================================
def monthly_settings_form(
    username,
    year,
    month,
):
    current = get_month_settings(
        username,
        year,
        month,
    )

    st.subheader(
        f"⚙️ Cấu hình tháng {month:02d}/{year}"
    )

    st.caption(
        "Nhập **1 lần/tháng**. Sau đó không nhập lại số giờ ở từng ngày."
    )

    with st.form(
        f"settings_{username}_{year}_{month}"
    ):
        c1, c2, c3, c4 = st.columns(4)

        morning = c1.number_input(
            "☀️ Sáng (giờ)",
            min_value=0.0,
            max_value=24.0,
            step=0.5,
            value=float(
                current.get(
                    "morning_hours", 4
                )
                if current
                else 4
            ),
        )

        afternoon = c2.number_input(
            "🌤️ Chiều (giờ)",
            min_value=0.0,
            max_value=24.0,
            step=0.5,
            value=float(
                current.get(
                    "afternoon_hours", 4
                )
                if current
                else 4
            ),
        )

        evening = c3.number_input(
            "🌙 Tối (giờ)",
            min_value=0.0,
            max_value=24.0,
            step=0.5,
            value=float(
                current.get(
                    "evening_hours", 4
                )
                if current
                else 4
            ),
        )

        hourly_rate = c4.number_input(
            "💰 Lương / giờ",
            min_value=0.0,
            step=1000.0,
            format="%.0f",
            value=float(
                current.get(
                    "hourly_rate", 0
                )
                if current
                else 0
            ),
        )

        if st.form_submit_button(
            "💾 LƯU CẤU HÌNH THÁNG",
            use_container_width=True,
        ):
            try:
                save_month_settings(
                    username,
                    year,
                    month,
                    morning,
                    afternoon,
                    evening,
                    hourly_rate,
                )
                st.success(
                    "✅ Đã lưu cấu hình tháng."
                )
                st.rerun()

            except Exception as e:
                st.error(
                    "Không lưu được cấu hình tháng."
                )
                st.code(
                    safe_error(e)
                )

    return get_month_settings(
        username,
        year,
        month,
    )


# ============================================================
# EMPLOYEE
# ============================================================
def employee_page():
    today = date.today()

    st.markdown(
        f'<div class="app-title">Xin chào, '
        f'{current_user["full_name"]} 👋</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        "### 📅 LỊCH CHẤM CÔNG"
    )

    st.caption(
        "Tích ca trên toàn bộ lịch → "
        "**Lưu lịch tháng một lần**. Không tự động ghi từng checkbox."
    )

    c1, c2 = st.columns(2)

    year = c1.number_input(
        "Năm",
        2020,
        2100,
        today.year,
        key="emp_year",
    )

    month = c2.selectbox(
        "Tháng",
        range(1, 13),
        today.month - 1,
        key="emp_month",
    )

    settings = monthly_settings_form(
        current_user["username"],
        int(year),
        int(month),
    )

    st.divider()

    render_schedule_calendar(
        current_user["username"],
        int(year),
        int(month),
        "employee",
    )

    st.divider()

    df = get_month_attendance(
        current_user["username"],
        int(year),
        int(month),
    )

    if df.empty:
        total_shifts = 0
    else:
        df = df[df["_scheduled"]].copy()
        total_shifts = len(df)

    total_hours = 0.0

    if not df.empty and settings:
        total_hours = sum(
            shift_hours(settings, s)
            for s in df["shift"].tolist()
        )

    hourly_rate = float(
        settings.get("hourly_rate", 0)
        if settings
        else 0
    )

    total_salary = (
        total_hours * hourly_rate
    )

    a, b, c = st.columns(3)

    a.metric(
        "☑️ Tổng ca",
        total_shifts,
    )

    b.metric(
        "⏱️ Tổng giờ",
        f"{total_hours:g} giờ",
    )

    c.metric(
        "💵 Tổng lương",
        f"{total_salary:,.0f} đ",
    )

    # Chi tiết đã tích.
    st.subheader(
        "📋 Các ca đã tích"
    )

    if df.empty:
        st.info(
            "Chưa có ca nào được lưu."
        )
        return

    rows = []

    for _, row in df.iterrows():
        shift = str(row["shift"])
        hours = shift_hours(
            settings,
            shift,
        )

        rows.append({
            "Ngày": datetime.strptime(
                str(row["work_date"])[:10],
                "%Y-%m-%d",
            ).strftime("%d/%m/%Y"),
            "Ca": shift,
            "Số giờ": hours,
            "Lương/giờ": hourly_rate,
            "Tiền ca": hours * hourly_rate,
        })

    report = pd.DataFrame(rows)

    st.dataframe(
        report,
        use_container_width=True,
        hide_index=True,
    )

    output = io.BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl",
    ) as writer:
        report.to_excel(
            writer,
            index=False,
            sheet_name="BangCong",
        )

    output.seek(0)

    st.download_button(
        "⬇️ XUẤT EXCEL",
        output.getvalue(),
        file_name=(
            f"Bang_cong_{current_user['username']}_"
            f"{int(year)}_{int(month):02d}.xlsx"
        ),
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        use_container_width=True,
    )


# ============================================================
# ADMIN
# ============================================================
def admin_page():
    st.markdown(
        '<div class="app-title">🛠️ TRUNG TÂM QUẢN TRỊ</div>',
        unsafe_allow_html=True,
    )

    users = get_users()

    tab1, tab2, tab3 = st.tabs([
        "👥 Nhân viên",
        "📅 Xếp ca",
        "💰 Bảng lương",
    ])

    with tab1:
        if users.empty:
            st.info("Chưa có tài khoản.")
        else:
            display = users.copy()

            display["Trạng thái"] = display[
                "active"
            ].map({
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

            with st.expander(
                "➕ Tạo tài khoản"
            ):
                with st.form(
                    "create_user"
                ):
                    c1, c2 = st.columns(2)

                    username = c1.text_input(
                        "Tên đăng nhập *"
                    )

                    full_name = c1.text_input(
                        "Họ tên *"
                    )

                    password = c1.text_input(
                        "Mật khẩu *",
                        type="password",
                    )

                    role = c2.selectbox(
                        "Vai trò",
                        ["employee", "admin"],
                    )

                    department = c2.text_input(
                        "Bộ phận"
                    )

                    position = c2.text_input(
                        "Chức vụ"
                    )

                    if st.form_submit_button(
                        "➕ TẠO TÀI KHOẢN",
                        use_container_width=True,
                    ):
                        if not username.strip() or not full_name.strip() or not password:
                            st.error(
                                "Nhập đủ thông tin."
                            )
                        else:
                            try:
                                upsert_rows(
                                    "users",
                                    [{
                                        "username": username.strip(),
                                        "password_hash": sha256(
                                            password
                                        ),
                                        "full_name": full_name.strip(),
                                        "role": role,
                                        "department": department.strip(),
                                        "position": position.strip(),
                                        "active": True,
                                    }],
                                    "username",
                                )
                                st.success(
                                    "✅ Đã tạo tài khoản."
                                )
                                st.rerun()
                            except Exception as e:
                                st.error(
                                    "Không tạo được tài khoản."
                                )
                                st.code(
                                    safe_error(e)
                                )

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
                "Nhân viên",
                list(options.keys()),
                key="admin_schedule_user",
            )

            username = options[label]

            today = date.today()

            c1, c2 = st.columns(2)

            year = c1.number_input(
                "Năm",
                2020,
                2100,
                today.year,
                key="admin_year",
            )

            month = c2.selectbox(
                "Tháng",
                range(1, 13),
                today.month - 1,
                key="admin_month",
            )

            settings = monthly_settings_form(
                username,
                int(year),
                int(month),
            )

            st.divider()

            render_schedule_calendar(
                username,
                int(year),
                int(month),
                "admin",
            )

    with tab3:
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
                "Nhân viên",
                list(options.keys()),
                key="payroll_user",
            )

            username = options[label]

            today = date.today()

            c1, c2 = st.columns(2)

            year = c1.number_input(
                "Năm",
                2020,
                2100,
                today.year,
                key="pay_year",
            )

            month = c2.selectbox(
                "Tháng",
                range(1, 13),
                today.month - 1,
                key="pay_month",
            )

            settings = get_month_settings(
                username,
                int(year),
                int(month),
            )

            if not settings:
                st.warning(
                    "Chưa có cấu hình tháng."
                )
                return

            df = get_month_attendance(
                username,
                int(year),
                int(month),
            )

            if not df.empty:
                df = df[df["_scheduled"]].copy()

            total_shifts = (
                len(df)
                if not df.empty
                else 0
            )

            total_hours = 0.0

            if not df.empty:
                total_hours = sum(
                    shift_hours(
                        settings,
                        s,
                    )
                    for s in df["shift"].tolist()
                )

            hourly_rate = float(
                settings.get(
                    "hourly_rate",
                    0,
                )
            )

            salary = (
                total_hours
                * hourly_rate
            )

            a, b, c = st.columns(3)

            a.metric(
                "☑️ Tổng ca",
                total_shifts,
            )

            b.metric(
                "⏱️ Tổng giờ",
                f"{total_hours:g} giờ",
            )

            c.metric(
                "💵 Tổng lương",
                f"{salary:,.0f} đ",
            )

            if not df.empty:
                rows = []

                for _, row in df.iterrows():
                    shift = str(row["shift"])
                    hours = shift_hours(
                        settings,
                        shift,
                    )

                    rows.append({
                        "Ngày": str(
                            row["work_date"]
                        )[:10],
                        "Ca": shift,
                        "Số giờ": hours,
                        "Lương/giờ": hourly_rate,
                        "Tiền ca": (
                            hours
                            * hourly_rate
                        ),
                    })

                report = pd.DataFrame(
                    rows
                )

                st.dataframe(
                    report,
                    use_container_width=True,
                    hide_index=True,
                )

                output = io.BytesIO()

                with pd.ExcelWriter(
                    output,
                    engine="openpyxl",
                ) as writer:
                    report.to_excel(
                        writer,
                        index=False,
                        sheet_name="BangLuong",
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
                    use_container_width=True,
                )


# ============================================================
# RUN
# ============================================================
if current_user["role"] == "admin":
    admin_page()
else:
    employee_page()
