
import streamlit as st
import pandas as pd
import requests
import hashlib
import hmac
import io
import calendar
from datetime import date, datetime

# ============================================================
# 🕘 WEB CHẤM CÔNG 3 CA / NGÀY
# Sáng - Chiều - Tối
# Dữ liệu lưu online trên Supabase
# ============================================================

st.set_page_config(
    page_title="Web Chấm Công",
    page_icon="🕘",
    layout="wide",
    initial_sidebar_state="expanded",
)

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

SHIFTS = ["Sáng", "Chiều", "Tối"]
STATUSES = ["Đi làm", "Nghỉ phép", "Nghỉ", "Đi trễ", "Về sớm", "WFH"]

# ============================================================
# SQL MIGRATION - CHẠY 1 LẦN NẾU DATABASE CŨ ĐÃ CÓ
# ============================================================
MIGRATION_SQL = """
-- Giữ dữ liệu chấm công cũ và mặc định các dòng cũ là ca Sáng.
ALTER TABLE public.attendance
ADD COLUMN IF NOT EXISTS shift text;

UPDATE public.attendance
SET shift = 'Sáng'
WHERE shift IS NULL OR shift = '';

ALTER TABLE public.attendance
ALTER COLUMN shift SET DEFAULT 'Sáng';

ALTER TABLE public.attendance
ALTER COLUMN shift SET NOT NULL;

-- Xóa unique cũ theo username + ngày.
ALTER TABLE public.attendance
DROP CONSTRAINT IF EXISTS attendance_username_work_date_key;

ALTER TABLE public.attendance
DROP CONSTRAINT IF EXISTS attendance_user_date_unique;

-- Mỗi người / ngày / ca chỉ có 1 bản ghi.
ALTER TABLE public.attendance
ADD CONSTRAINT attendance_username_work_date_shift_key
UNIQUE (username, work_date, shift);

CREATE INDEX IF NOT EXISTS attendance_shift_idx
ON public.attendance(username, work_date, shift);
"""

# ============================================================
# CSS
# ============================================================
st.markdown("""
<style>
.block-container {
    padding-top: 1.5rem;
}
.main-title {
    font-size: 2rem;
    font-weight: 800;
    margin-bottom: .2rem;
}
.sub-title {
    color: #6b7280;
    margin-bottom: 1rem;
}
.day-box {
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    padding: 8px;
    min-height: 96px;
}
.shift-line {
    font-size: 12px;
    line-height: 1.6;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# SUPABASE REST
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
        raise RuntimeError(
            f"Supabase {r.status_code}: {r.text}"
        )

    if not r.text:
        return []

    return r.json()

def select_rows(table, params=None):
    return sb_request("GET", table, params=params)

def insert_row(table, payload):
    return sb_request(
        "POST",
        table,
        payload=payload,
        prefer="return=representation",
    )

def upsert_row(table, payload):
    return sb_request(
        "POST",
        table,
        payload=payload,
        prefer="resolution=merge-duplicates,return=representation",
    )

def update_rows(table, params, payload):
    return sb_request(
        "PATCH",
        table,
        params=params,
        payload=payload,
        prefer="return=representation",
    )

def delete_rows(table, params):
    return sb_request(
        "DELETE",
        table,
        params=params,
        prefer="return=minimal",
    )

def safe_error(e):
    text = str(e)
    if SUPABASE_SECRET_KEY:
        text = text.replace(SUPABASE_SECRET_KEY, "[HIDDEN]")
    return text

def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

# ============================================================
# DATA
# ============================================================
def get_users_df():
    return pd.DataFrame(select_rows(
        "users",
        {
            "select": "*",
            "order": "created_at.asc",
        },
    ))

def get_attendance_df():
    return pd.DataFrame(select_rows(
        "attendance",
        {
            "select": "*",
            "order": "work_date.desc,shift.asc",
        },
    ))

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

def get_day_shift(username, work_date, shift):
    rows = select_rows(
        "attendance",
        {
            "select": "*",
            "username": f"eq.{username}",
            "work_date": f"eq.{work_date}",
            "shift": f"eq.{shift}",
            "limit": "1",
        },
    )
    return rows[0] if rows else None

def authenticate(username, password):
    u = get_user(username.strip())
    if not u or not bool(u.get("active")):
        return None
    if hmac.compare_digest(
        str(u.get("password_hash", "")),
        sha256(password),
    ):
        return u
    return None

def save_shift(username, work_date, shift, check_in, check_out, status, note):
    return upsert_row(
        "attendance",
        {
            "username": username,
            "work_date": work_date,
            "shift": shift,
            "check_in": check_in,
            "check_out": check_out,
            "status": status,
            "note": note,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

def delete_shift(username, work_date, shift):
    return delete_rows(
        "attendance",
        {
            "username": f"eq.{username}",
            "work_date": f"eq.{work_date}",
            "shift": f"eq.{shift}",
        },
    )

def shift_icon(record):
    if not record:
        return "⬜"
    status = record.get("status", "")
    return {
        "Đi làm": "✅",
        "Nghỉ phép": "🟦",
        "Nghỉ": "❌",
        "Đi trễ": "🟡",
        "Về sớm": "🟠",
        "WFH": "🔵",
    }.get(status, "⬜")

def calendar_statuses(username, year, month):
    data = get_attendance_df()

    result = {}

    if data.empty:
        return result

    data["work_date"] = data["work_date"].astype(str).str[:10]

    data = data[
        (data["username"].astype(str) == str(username))
        & data["work_date"].str.startswith(
            f"{int(year):04d}-{int(month):02d}-"
        )
    ]

    for _, row in data.iterrows():
        day = str(row["work_date"])
        shift = str(row.get("shift", "Sáng"))
        result.setdefault(day, {})
        result[day][shift] = row.to_dict()

    return result

# ============================================================
# SETUP PAGE
# ============================================================
if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    st.title("🕘 WEB CHẤM CÔNG 3 CA")
    st.warning("Chưa cấu hình Supabase.")

    st.markdown("""
### Secrets cần có trên Streamlit

```toml
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_..."
```

### SQL cần chạy trong Supabase

Nếu đây là database chấm công cũ, hãy chạy **SQL migration** bên dưới một lần.
Các bản ghi cũ sẽ được xem là **ca Sáng**.
""")

    st.code(MIGRATION_SQL, language="sql")
    st.stop()

# ============================================================
# TEST DB
# ============================================================
try:
    select_rows(
        "attendance",
        {
            "select": "id,shift",
            "limit": "1",
        },
    )
except Exception as e:
    st.error("❌ Bảng attendance chưa được nâng cấp lên cơ chế 3 ca.")
    st.code(safe_error(e))
    st.markdown("""
### Cách sửa

Vào **Supabase → SQL Editor → New query**, dán toàn bộ file
`migration_cham_cong_3_ca.sql` rồi bấm **Run**.

Migration này:
- thêm cột `shift`
- giữ dữ liệu cũ
- chuyển dữ liệu cũ thành **ca Sáng**
- cho phép mỗi nhân viên có **3 ca/ngày**
- tạo khóa duy nhất theo **nhân viên + ngày + ca**

Sau khi Run thành công, quay lại Streamlit và **Reboot app**.
""")
    st.stop()

# ============================================================
# LOGIN
# ============================================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.markdown(
        '<div class="main-title">🕘 WEB CHẤM CÔNG</div>',
        unsafe_allow_html=True,
    )
    st.caption("Mỗi ngày có 3 ca: Sáng · Chiều · Tối")

    with st.form("login"):
        username = st.text_input("Tên đăng nhập")
        password = st.text_input("Mật khẩu", type="password")
        submit = st.form_submit_button(
            "🔐 ĐĂNG NHẬP",
            use_container_width=True,
        )

        if submit:
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
    st.caption(f"Tài khoản: `{current_user['username']}`")
    st.caption(f"Vai trò: `{current_user['role']}`")
    st.divider()

    if st.button("🚪 Đăng xuất", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# ============================================================
# CALENDAR UI
# ============================================================
def render_calendar(username, key_prefix):
    today = date.today()

    c1, c2 = st.columns(2)
    year = c1.number_input(
        "Năm",
        2020,
        2100,
        today.year,
        key=f"{key_prefix}_year",
    )
    month = c2.selectbox(
        "Tháng",
        list(range(1, 13)),
        today.month - 1,
        key=f"{key_prefix}_month",
    )

    data = calendar_statuses(
        username,
        int(year),
        int(month),
    )

    month_cal = calendar.Calendar(firstweekday=0)
    weeks = month_cal.monthdayscalendar(
        int(year),
        int(month),
    )

    st.caption(
        "✅ Đi làm  |  🟦 Nghỉ phép  |  ❌ Nghỉ  |  "
        "🟡 Đi trễ  |  🟠 Về sớm  |  ⬜ Chưa chấm"
    )

    weekdays = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    header_cols = st.columns(7)

    for i, w in enumerate(weekdays):
        header_cols[i].markdown(
            f"**{w}**"
        )

    for week_index, week in enumerate(weeks):
        cols = st.columns(7)

        for col_index, day in enumerate(week):
            with cols[col_index]:
                if day == 0:
                    st.write("")
                    continue

                ds = f"{int(year):04d}-{int(month):02d}-{day:02d}"
                day_data = data.get(ds, {})

                s1 = shift_icon(day_data.get("Sáng"))
                s2 = shift_icon(day_data.get("Chiều"))
                s3 = shift_icon(day_data.get("Tối"))

                label = (
                    f"**{day}**\n\n"
                    f"S {s1}  C {s2}  T {s3}"
                )

                if st.button(
                    label,
                    key=f"{key_prefix}_{ds}",
                    use_container_width=True,
                ):
                    st.session_state[
                        f"{key_prefix}_selected_date"
                    ] = ds
                    st.rerun()

    return (
        int(year),
        int(month),
        st.session_state.get(
            f"{key_prefix}_selected_date",
            today.isoformat()
            if today.year == int(year) and today.month == int(month)
            else f"{int(year):04d}-{int(month):02d}-01",
        ),
    )

# ============================================================
# EMPLOYEE
# ============================================================
def employee_page():
    st.markdown(
        f'<div class="main-title">'
        f'Xin chào, {current_user["full_name"]} 👋'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.caption(
        "Bấm vào một ngày trên lịch để chấm 3 ca: Sáng · Chiều · Tối."
    )

    year, month, selected_date = render_calendar(
        current_user["username"],
        "employee_calendar",
    )

    st.divider()

    st.subheader(
        f"📅 Chấm công ngày "
        f"{datetime.strptime(selected_date, '%Y-%m-%d').strftime('%d/%m/%Y')}"
    )

    # 3 ca hiển thị cùng lúc.
    for shift in SHIFTS:
        record = get_day_shift(
            current_user["username"],
            selected_date,
            shift,
        )

        icon = shift_icon(record)

        with st.expander(
            f"{icon} CA {shift.upper()}",
            expanded=True,
        ):
            with st.form(
                f"employee_{selected_date}_{shift}"
            ):
                c1, c2 = st.columns(2)

                default_in = datetime.now().time()
                default_out = datetime.now().time()

                if record:
                    try:
                        if record.get("check_in"):
                            default_in = datetime.strptime(
                                record["check_in"],
                                "%H:%M",
                            ).time()
                        if record.get("check_out"):
                            default_out = datetime.strptime(
                                record["check_out"],
                                "%H:%M",
                            ).time()
                    except Exception:
                        pass

                check_in = c1.time_input(
                    "Giờ vào",
                    value=default_in,
                    key=f"in_{selected_date}_{shift}",
                )
                check_out = c2.time_input(
                    "Giờ ra",
                    value=default_out,
                    key=f"out_{selected_date}_{shift}",
                )

                current_status = (
                    record.get("status")
                    if record
                    else None
                )

                status = st.selectbox(
                    "Trạng thái",
                    STATUSES,
                    index=(
                        STATUSES.index(current_status)
                        if current_status in STATUSES
                        else 0
                    ),
                    key=f"status_{selected_date}_{shift}",
                )

                note = st.text_input(
                    "Ghi chú",
                    value=(record or {}).get("note", ""),
                    key=f"note_{selected_date}_{shift}",
                )

                a, b = st.columns(2)

                save = a.form_submit_button(
                    "💾 LƯU CA",
                    use_container_width=True,
                )
                delete = b.form_submit_button(
                    "🗑️ XÓA CA",
                    use_container_width=True,
                )

                if save:
                    try:
                        save_shift(
                            current_user["username"],
                            selected_date,
                            shift,
                            check_in.strftime("%H:%M"),
                            check_out.strftime("%H:%M"),
                            status,
                            note,
                        )
                        st.success(
                            f"✅ Đã lưu ca {shift}."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(
                            f"Không lưu được ca {shift}."
                        )
                        st.code(safe_error(e))

                if delete:
                    try:
                        delete_shift(
                            current_user["username"],
                            selected_date,
                            shift,
                        )
                        st.success(
                            f"🗑️ Đã xóa ca {shift}."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(
                            f"Không xóa được ca {shift}."
                        )
                        st.code(safe_error(e))

    # --------------------------------------------------------
    # BẢNG CÔNG 3 CA DẠNG EXCEL
    # --------------------------------------------------------
    st.divider()
    st.subheader("📊 Bảng công tháng")

    try:
        df = get_attendance_df()

        if not df.empty:
            df["work_date"] = df["work_date"].astype(str).str[:10]
            month_df = df[
                (df["username"].astype(str) == current_user["username"])
                & (
                    df["work_date"].str.startswith(
                        f"{year:04d}-{month:02d}-"
                    )
                )
            ].copy()
        else:
            month_df = pd.DataFrame()

        show = []

        total_days = calendar.monthrange(year, month)[1]

        for d in range(1, total_days + 1):
            ds = f"{year:04d}-{month:02d}-{d:02d}"
            day_rows = (
                month_df[month_df["work_date"] == ds]
                if not month_df.empty
                else pd.DataFrame()
            )

            for shift in SHIFTS:
                r = (
                    day_rows[day_rows["shift"] == shift]
                    if not day_rows.empty
                    else pd.DataFrame()
                )

                if not r.empty:
                    row = r.iloc[0]
                    show.append({
                        "Ngày": datetime.strptime(
                            ds,
                            "%Y-%m-%d",
                        ).strftime("%d/%m/%Y"),
                        "Ca": shift,
                        "Giờ vào": row.get("check_in", ""),
                        "Giờ ra": row.get("check_out", ""),
                        "Trạng thái": row.get("status", ""),
                        "Ghi chú": row.get("note", ""),
                    })
                else:
                    show.append({
                        "Ngày": datetime.strptime(
                            ds,
                            "%Y-%m-%d",
                        ).strftime("%d/%m/%Y"),
                        "Ca": shift,
                        "Giờ vào": "",
                        "Giờ ra": "",
                        "Trạng thái": "",
                        "Ghi chú": "",
                    })

        report = pd.DataFrame(show)
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
                sheet_name="BangCong3Ca",
            )

        output.seek(0)

        st.download_button(
            "⬇️ XUẤT EXCEL THÁNG",
            output.getvalue(),
            file_name=(
                f"Bang_cong_3_ca_"
                f"{current_user['username']}_"
                f"{month:02d}_{year}.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            use_container_width=True,
        )

    except Exception as e:
        st.error("Không tạo được bảng công.")
        st.code(safe_error(e))

# ============================================================
# ADMIN
# ============================================================
def admin_page():
    st.markdown(
        '<div class="main-title">🛠️ TRUNG TÂM QUẢN TRỊ</div>',
        unsafe_allow_html=True,
    )

    users = get_users_df()

    if users.empty:
        st.info("Chưa có tài khoản.")
    else:
        employee_options = {
            f"{r['full_name']} ({r['username']})":
            r["username"]
            for _, r in users[
                users["role"] == "employee"
            ].iterrows()
        }

        tab1, tab2, tab3 = st.tabs([
            "👥 Nhân viên",
            "🗓️ Lịch chấm công",
            "📊 Báo cáo",
        ])

        # ----------------------------------------------------
        # USERS
        # ----------------------------------------------------
        with tab1:
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
                })[
                    [
                        "Tài khoản",
                        "Họ tên",
                        "Vai trò",
                        "Bộ phận",
                        "Chức vụ",
                        "Trạng thái",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

            with st.expander("➕ Tạo tài khoản"):
                with st.form("create_user"):
                    c1, c2 = st.columns(2)

                    username = c1.text_input("Tên đăng nhập *")
                    full_name = c1.text_input("Họ tên *")
                    password = c1.text_input(
                        "Mật khẩu *",
                        type="password",
                    )

                    role = c2.selectbox(
                        "Vai trò",
                        ["employee", "admin"],
                    )
                    department = c2.text_input("Bộ phận")
                    position = c2.text_input("Chức vụ")

                    if st.form_submit_button(
                        "➕ TẠO TÀI KHOẢN",
                        use_container_width=True,
                    ):
                        if not username.strip() or not full_name.strip() or not password:
                            st.error("Vui lòng nhập đủ thông tin.")
                        else:
                            try:
                                insert_user(
                                    "users",
                                    {
                                        "username": username.strip(),
                                        "password_hash": sha256(password),
                                        "full_name": full_name.strip(),
                                        "role": role,
                                        "department": department.strip(),
                                        "position": position.strip(),
                                        "active": True,
                                    },
                                )
                                st.success("✅ Đã tạo tài khoản.")
                                st.rerun()
                            except Exception as e:
                                st.error("Không tạo được tài khoản.")
                                st.code(safe_error(e))

        # ----------------------------------------------------
        # ADMIN CALENDAR
        # ----------------------------------------------------
        with tab2:
            if not employee_options:
                st.info("Chưa có nhân viên.")
            else:
                selected_label = st.selectbox(
                    "Chọn nhân viên",
                    list(employee_options.keys()),
                    key="admin_calendar_employee",
                )
                selected_username = employee_options[selected_label]

                year, month, selected_date = render_calendar(
                    selected_username,
                    "admin_calendar",
                )

                st.divider()
                st.subheader(
                    f"📅 {datetime.strptime(
                        selected_date, '%Y-%m-%d'
                    ).strftime('%d/%m/%Y')}"
                )

                for shift in SHIFTS:
                    record = get_day_shift(
                        selected_username,
                        selected_date,
                        shift,
                    )

                    with st.expander(
                        f"{shift_icon(record)} CA {shift.upper()}",
                        expanded=True,
                    ):
                        with st.form(
                            f"admin_{selected_date}_{shift}"
                        ):
                            c1, c2 = st.columns(2)

                            ci = c1.text_input(
                                "Giờ vào",
                                value=(record or {}).get(
                                    "check_in", ""
                                ),
                            )
                            co = c2.text_input(
                                "Giờ ra",
                                value=(record or {}).get(
                                    "check_out", ""
                                ),
                            )

                            old_status = (
                                record.get("status")
                                if record
                                else None
                            )

                            status = st.selectbox(
                                "Trạng thái",
                                STATUSES,
                                index=(
                                    STATUSES.index(old_status)
                                    if old_status in STATUSES
                                    else 0
                                ),
                                key=f"adm_status_{selected_date}_{shift}",
                            )

                            note = st.text_input(
                                "Ghi chú",
                                value=(record or {}).get("note", ""),
                                key=f"adm_note_{selected_date}_{shift}",
                            )

                            a, b = st.columns(2)

                            save = a.form_submit_button(
                                "💾 LƯU",
                                use_container_width=True,
                            )

                            delete = b.form_submit_button(
                                "🗑️ XÓA",
                                use_container_width=True,
                            )

                            if save:
                                try:
                                    save_shift(
                                        selected_username,
                                        selected_date,
                                        shift,
                                        ci.strip(),
                                        co.strip(),
                                        status,
                                        note.strip(),
                                    )
                                    st.success(f"Đã lưu ca {shift}.")
                                    st.rerun()
                                except Exception as e:
                                    st.error("Không lưu được.")
                                    st.code(safe_error(e))

                            if delete:
                                try:
                                    delete_shift(
                                        selected_username,
                                        selected_date,
                                        shift,
                                    )
                                    st.success(f"Đã xóa ca {shift}.")
                                    st.rerun()
                                except Exception as e:
                                    st.error("Không xóa được.")
                                    st.code(safe_error(e))

        # ----------------------------------------------------
        # REPORT
        # ----------------------------------------------------
        with tab3:
            c1, c2 = st.columns(2)

            year = c1.number_input(
                "Năm",
                2020,
                2100,
                date.today().year,
                key="report_year",
            )

            month = c2.selectbox(
                "Tháng",
                range(1, 13),
                date.today().month - 1,
                key="report_month",
            )

            employee_options_report = ["Tất cả"] + list(
                employee_options.values()
            )

            employee = st.selectbox(
                "Nhân viên",
                employee_options_report,
                key="report_employee",
            )

            df = get_attendance_df()

            if not df.empty:
                df["work_date"] = df["work_date"].astype(str).str[:10]

                report = df[
                    df["work_date"].str.startswith(
                        f"{int(year):04d}-{int(month):02d}-"
                    )
                ].copy()

                if employee != "Tất cả":
                    report = report[
                        report["username"].astype(str) == employee
                    ]

                if not report.empty:
                    report = report.merge(
                        users[
                            [
                                "username",
                                "full_name",
                                "department",
                            ]
                        ],
                        on="username",
                        how="left",
                    )

                    report = report.rename(columns={
                        "username": "Tài khoản",
                        "full_name": "Họ tên",
                        "department": "Bộ phận",
                        "work_date": "Ngày",
                        "shift": "Ca",
                        "check_in": "Giờ vào",
                        "check_out": "Giờ ra",
                        "status": "Trạng thái",
                        "note": "Ghi chú",
                    })

                    cols = [
                        "Tài khoản",
                        "Họ tên",
                        "Bộ phận",
                        "Ngày",
                        "Ca",
                        "Giờ vào",
                        "Giờ ra",
                        "Trạng thái",
                        "Ghi chú",
                    ]

                    st.dataframe(
                        report[
                            [c for c in cols if c in report.columns]
                        ],
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
                            sheet_name="BangCong3Ca",
                        )
                    output.seek(0)

                    st.download_button(
                        "⬇️ XUẤT EXCEL",
                        output.getvalue(),
                        file_name=(
                            f"Bang_cong_3_ca_"
                            f"{int(month):02d}_{int(year)}.xlsx"
                        ),
                        mime=(
                            "application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet"
                        ),
                        use_container_width=True,
                    )
                else:
                    st.info("Tháng này chưa có dữ liệu.")
            else:
                st.info("Chưa có dữ liệu chấm công.")


# ============================================================
# RUN
# ============================================================
if current_user["role"] == "admin":
    admin_page()
else:
    employee_page()
