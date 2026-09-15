import streamlit as st
import pandas as pd
import requests
import hashlib
import hmac
import io
from datetime import datetime, date
import calendar

# ============================================================
# 🕘 WEB CHẤM CÔNG - SUPABASE DATABASE
# Dữ liệu được lưu ONLINE trên Supabase, không dùng SQLite,
# không dùng Google Sheet.
#
# Cần 2 Secrets:
# SUPABASE_URL = "https://xxxx.supabase.co"
# SUPABASE_SERVICE_ROLE_KEY = "eyJ..."
# ============================================================

st.set_page_config(
    page_title="Chấm công",
    page_icon="🕘",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------
# SUPABASE CONFIG
# ------------------------------------------------------------
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"].strip().rstrip("/")
    SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"].strip()
except Exception:
    SUPABASE_URL = ""
    SUPABASE_KEY = ""

# ------------------------------------------------------------
# SQL TẠO DATABASE - CHỈ CHẠY 1 LẦN TRONG SUPABASE SQL EDITOR
# ------------------------------------------------------------
DATABASE_SQL = r"""
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

create table if not exists public.attendance (
    id uuid primary key default gen_random_uuid(),
    username text not null,
    work_date date not null,
    check_in text default '',
    check_out text default '',
    status text not null default 'Đi làm',
    note text default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(username, work_date)
);

create index if not exists attendance_work_date_idx
on public.attendance(work_date);

create index if not exists attendance_username_idx
on public.attendance(username);

-- Tạo admin mặc định:
-- username: admin
-- password: admin123
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
# CSS
# ============================================================
st.markdown("""
<style>
.block-container {
    padding-top: 2rem;
}
.big-title {
    font-size: 2.1rem;
    font-weight: 800;
}
.small-muted {
    color: #6b7280;
}
.card {
    padding: 1rem;
    border: 1px solid #e5e7eb;
    border-radius: 16px;
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# SUPABASE REST
# ============================================================
def headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def sb_get(table, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    r = requests.get(
        url,
        headers=headers(),
        params=params or {},
        timeout=30,
    )

    if not r.ok:
        raise RuntimeError(
            f"Supabase GET {table}: "
            f"{r.status_code} - {r.text}"
        )

    return r.json()


def sb_post(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"

    h = headers()
    h["Prefer"] = "return=representation"

    r = requests.post(
        url,
        headers=h,
        json=data,
        timeout=30,
    )

    if not r.ok:
        raise RuntimeError(
            f"Supabase POST {table}: "
            f"{r.status_code} - {r.text}"
        )

    return r.json()


def sb_patch(table, params, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"

    h = headers()
    h["Prefer"] = "return=representation"

    r = requests.patch(
        url,
        headers=h,
        params=params,
        json=data,
        timeout=30,
    )

    if not r.ok:
        raise RuntimeError(
            f"Supabase PATCH {table}: "
            f"{r.status_code} - {r.text}"
        )

    return r.json()


def sb_delete(table, params):
    url = f"{SUPABASE_URL}/rest/v1/{table}"

    r = requests.delete(
        url,
        headers=headers(),
        params=params,
        timeout=30,
    )

    if not r.ok:
        raise RuntimeError(
            f"Supabase DELETE {table}: "
            f"{r.status_code} - {r.text}"
        )

    return r.json() if r.text else []


# ============================================================
# HELPERS
# ============================================================
def sha256(text):
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def safe_error(e):
    msg = str(e)

    # Không hiện service key nếu có lỗi.
    if SUPABASE_KEY:
        msg = msg.replace(
            SUPABASE_KEY,
            "[HIDDEN]"
        )

    return msg


def get_users():
    return pd.DataFrame(
        sb_get(
            "users",
            {
                "select": "*",
                "order": "created_at.desc",
            }
        )
    )


def get_attendance():
    return pd.DataFrame(
        sb_get(
            "attendance",
            {
                "select": "*",
                "order": "work_date.desc",
            }
        )
    )


def get_user(username):
    rows = sb_get(
        "users",
        {
            "select": "*",
            "username": f"eq.{username}",
            "limit": "1",
        }
    )

    return rows[0] if rows else None


def authenticate(username, password):
    u = get_user(username)

    if not u:
        return None

    if not bool(u.get("active", False)):
        return None

    if hmac.compare_digest(
        str(u["password_hash"]),
        sha256(password)
    ):
        return u

    return None


def get_today_attendance(username):
    today = date.today().isoformat()

    rows = sb_get(
        "attendance",
        {
            "select": "*",
            "username": f"eq.{username}",
            "work_date": f"eq.{today}",
            "limit": "1",
        }
    )

    return rows[0] if rows else None


def save_attendance(
    username,
    work_date,
    check_in,
    check_out,
    status,
    note,
):
    # UPSERT:
    # cùng username + ngày => sửa bản ghi cũ,
    # không tạo bản ghi trùng.
    url = f"{SUPABASE_URL}/rest/v1/attendance"
    h = headers()
    h["Prefer"] = "resolution=merge-duplicates,return=representation"

    r = requests.post(
        url,
        headers=h,
        params={"on_conflict": "username,work_date"},
        json={
            "username": username,
            "work_date": work_date,
            "check_in": check_in,
            "check_out": check_out,
            "status": status,
            "note": note,
            "updated_at": datetime.utcnow().isoformat(),
        },
        timeout=30,
    )

    if not r.ok:
        raise RuntimeError(
            f"Supabase UPSERT attendance: "
            f"{r.status_code} - {r.text}"
        )

    return r.json()


def make_month_table(
    username,
    year,
    month,
):
    df = get_attendance()

    if not df.empty:
        df["work_date"] = (
            df["work_date"]
            .astype(str)
            .str[:10]
        )

        df = df[
            (df["username"].astype(str) == str(username)) &
            (
                df["work_date"].str.startswith(
                    f"{int(year):04d}-{int(month):02d}-"
                )
            )
        ]

    rows = []

    total_days = calendar.monthrange(
        int(year),
        int(month),
    )[1]

    weekday_names = [
        "T2", "T3", "T4",
        "T5", "T6", "T7", "CN"
    ]

    for d in range(1, total_days + 1):

        dt = date(
            int(year),
            int(month),
            d,
        )

        x = (
            df[
                df["work_date"] == dt.isoformat()
            ]
            if not df.empty
            else pd.DataFrame()
        )

        if not x.empty:
            r = x.iloc[0]

            rows.append({
                "Ngày": dt.strftime("%d/%m/%Y"),
                "Thứ": weekday_names[dt.weekday()],
                "Giờ vào": r.get("check_in", ""),
                "Giờ ra": r.get("check_out", ""),
                "Trạng thái": r.get("status", ""),
                "Ghi chú": r.get("note", ""),
            })
        else:
            rows.append({
                "Ngày": dt.strftime("%d/%m/%Y"),
                "Thứ": weekday_names[dt.weekday()],
                "Giờ vào": "",
                "Giờ ra": "",
                "Trạng thái": "",
                "Ghi chú": "",
            })

    return pd.DataFrame(rows)


# ============================================================
# CHƯA CẤU HÌNH SUPABASE
# ============================================================
if not SUPABASE_URL or not SUPABASE_KEY:

    st.markdown(
        '<div class="big-title">🕘 WEB CHẤM CÔNG</div>',
        unsafe_allow_html=True,
    )

    st.warning(
        "Chưa cấu hình Supabase."
    )

    st.markdown("""
### Em chỉ cần cấu hình Supabase một lần

#### Bước 1 — Tạo project Supabase

Tạo project mới trên Supabase.

#### Bước 2 — Tạo bảng

Vào **SQL Editor → New query**.

Xóa nội dung cũ và dán **toàn bộ SQL bên dưới** → Run.

#### Bước 3 — Lấy thông tin kết nối

Vào phần **Project Settings → API** và lấy:

- Project URL
- `service_role` key

⚠️ `service_role` key là khóa bí mật. Chỉ đặt trong **Streamlit Secrets**, không đưa vào code công khai.

#### Bước 4 — Streamlit Secrets

Vào:

**Manage app → Settings → Secrets**

dán:

```toml
SUPABASE_URL = "https://xxxxxxxx.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "YOUR_SERVICE_ROLE_KEY"
```

Sau đó **Save → Reboot app**.
""")

    with st.expander("📋 SQL DATABASE — COPY TOÀN BỘ"):
        st.code(DATABASE_SQL, language="sql")

    st.stop()


# ============================================================
# TEST SUPABASE
# ============================================================
try:

    test = sb_get(
        "users",
        {
            "select": "id",
            "limit": "1",
        }
    )

except Exception as e:

    st.error(
        "❌ Không kết nối được Supabase."
    )

    st.code(
        safe_error(e)
    )

    st.markdown("""
### Nếu đây là lần đầu cài:

1. Kiểm tra `SUPABASE_URL`.
2. Kiểm tra `SUPABASE_SERVICE_ROLE_KEY`.
3. Đảm bảo em đã chạy SQL tạo bảng `users` và `attendance`.
4. Save Secrets rồi Reboot app.
""")

    st.stop()


# ============================================================
# LOGIN
# ============================================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:

    st.markdown(
        '<div style="max-width:430px;margin:70px auto;">'
        '<div class="big-title">🕘 Chấm công</div>'
        '<p class="small-muted">Đăng nhập hệ thống</p>',
        unsafe_allow_html=True,
    )

    with st.form("login_form"):

        username = st.text_input(
            "Tên đăng nhập"
        )

        password = st.text_input(
            "Mật khẩu",
            type="password",
        )

        submit = st.form_submit_button(
            "🔐 ĐĂNG NHẬP",
            use_container_width=True,
        )

        if submit:

            if not username or not password:
                st.error(
                    "Vui lòng nhập tài khoản và mật khẩu."
                )
            else:

                try:
                    u = authenticate(
                        username.strip(),
                        password,
                    )

                    if u:
                        st.session_state.logged_in = True
                        st.session_state.username = u["username"]
                        st.rerun()
                    else:
                        st.error(
                            "Sai tài khoản, mật khẩu hoặc tài khoản đã bị khóa."
                        )

                except Exception as e:
                    st.error(
                        "Có lỗi khi đăng nhập."
                    )
                    st.code(
                        safe_error(e)
                    )

    st.caption(
        "Tài khoản admin mặc định: admin / admin123"
    )

    st.markdown("</div>", unsafe_allow_html=True)

    st.stop()


# ============================================================
# LOAD CURRENT USER
# ============================================================
try:

    user = get_user(
        st.session_state.username
    )

except Exception as e:

    st.error(
        "Không tải được tài khoản."
    )
    st.code(
        safe_error(e)
    )
    st.stop()


if not user or not bool(user.get("active", False)):

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
        f"👤 **{user['full_name']}**"
    )

    st.caption(
        f"Tài khoản: {user['username']}"
    )

    st.caption(
        f"Vai trò: {user['role']}"
    )

    if user.get("department"):
        st.caption(
            f"🏢 {user['department']}"
        )

    if user.get("position"):
        st.caption(
            f"💼 {user['position']}"
        )

    st.divider()

    if st.button(
        "🚪 Đăng xuất",
        use_container_width=True,
    ):
        st.session_state.clear()
        st.rerun()


# ============================================================
# EMPLOYEE
# ============================================================
def employee_page():

    today = date.today()

    try:
        current = get_today_attendance(
            user["username"]
        )
    except Exception as e:
        st.error("Không tải được dữ liệu hôm nay.")
        st.code(safe_error(e))
        return

    st.markdown(
        f'<div class="big-title">'
        f'Xin chào, {user["full_name"]} 👋'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<p class="small-muted">'
        'Dữ liệu được lưu trực tiếp trên database online.'
        '</p>',
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "📅 Hôm nay",
        today.strftime("%d/%m/%Y"),
    )

    c2.metric(
        "🟢 Giờ vào",
        (current or {}).get("check_in") or "—",
    )

    c3.metric(
        "🔴 Giờ ra",
        (current or {}).get("check_out") or "—",
    )

    t1, t2, t3 = st.tabs([
        "📝 Chấm công",
        "📅 Bảng công",
        "📊 Xuất Excel",
    ])

    # --------------------------------------------------------
    # CHẤM CÔNG
    # --------------------------------------------------------
    with t1:

        with st.form("employee_attendance"):

            now = datetime.now().time()

            check_in_default = now
            check_out_default = now

            if current:

                try:
                    if current.get("check_in"):
                        check_in_default = datetime.strptime(
                            current["check_in"],
                            "%H:%M",
                        ).time()

                    if current.get("check_out"):
                        check_out_default = datetime.strptime(
                            current["check_out"],
                            "%H:%M",
                        ).time()

                except Exception:
                    pass

            c1, c2 = st.columns(2)

            check_in = c1.time_input(
                "🟢 Giờ vào",
                value=check_in_default,
            )

            check_out = c2.time_input(
                "🔴 Giờ ra",
                value=check_out_default,
            )

            statuses = [
                "Đi làm",
                "Nghỉ phép",
                "Nghỉ",
                "Đi trễ",
                "Về sớm",
                "WFH",
            ]

            current_status = (
                current.get("status")
                if current
                else None
            )

            status = st.selectbox(
                "Trạng thái",
                statuses,
                index=(
                    statuses.index(current_status)
                    if current_status in statuses
                    else 0
                ),
            )

            note = st.text_input(
                "Ghi chú",
                value=(
                    current.get("note", "")
                    if current
                    else ""
                ),
            )

            save = st.form_submit_button(
                "💾 LƯU CHẤM CÔNG",
                use_container_width=True,
            )

            if save:

                try:

                    result = save_attendance(
                        user["username"],
                        today.isoformat(),
                        check_in.strftime("%H:%M"),
                        check_out.strftime("%H:%M"),
                        status,
                        note,
                    )

                    st.success(
                        "✅ Đã lưu thành công vào database."
                    )

                    st.rerun()

                except Exception as e:

                    st.error(
                        "❌ Không lưu được."
                    )

                    st.code(
                        safe_error(e)
                    )

    # --------------------------------------------------------
    # BẢNG CÔNG
    # --------------------------------------------------------
    with t2:

        c1, c2 = st.columns(2)

        year = c1.number_input(
            "Năm",
            min_value=2020,
            max_value=2100,
            value=today.year,
            step=1,
        )

        month = c2.selectbox(
            "Tháng",
            list(range(1, 13)),
            index=today.month - 1,
        )

        try:

            table = make_month_table(
                user["username"],
                year,
                month,
            )

            st.dataframe(
                table,
                use_container_width=True,
                hide_index=True,
            )

        except Exception as e:

            st.error(
                "Không tải được bảng công."
            )

            st.code(
                safe_error(e)
            )

    # --------------------------------------------------------
    # EXCEL
    # --------------------------------------------------------
    with t3:

        c1, c2 = st.columns(2)

        ex_year = c1.number_input(
            "Năm xuất",
            2020,
            2100,
            today.year,
            key="ex_year",
        )

        ex_month = c2.selectbox(
            "Tháng xuất",
            list(range(1, 13)),
            today.month - 1,
            key="ex_month",
        )

        try:

            export_df = make_month_table(
                user["username"],
                ex_year,
                ex_month,
            )

            output = io.BytesIO()

            with pd.ExcelWriter(
                output,
                engine="openpyxl",
            ) as writer:

                export_df.to_excel(
                    writer,
                    index=False,
                    sheet_name="BangCong",
                )

            output.seek(0)

            st.download_button(
                "⬇️ TẢI BẢNG CÔNG EXCEL",
                output.getvalue(),
                file_name=(
                    f"Bang_cong_"
                    f"{user['username']}_"
                    f"{int(ex_month):02d}_"
                    f"{int(ex_year)}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                use_container_width=True,
            )

        except Exception as e:

            st.error(
                "Không tạo được file Excel."
            )

            st.code(
                safe_error(e)
            )


# ============================================================
# ADMIN
# ============================================================
def admin_page():

    st.markdown(
        '<div class="big-title">🛠️ TRUNG TÂM QUẢN TRỊ</div>',
        unsafe_allow_html=True,
    )

    st.caption(
        "Quản lý nhân viên và dữ liệu chấm công online."
    )

    try:
        users = get_users()
        att = get_attendance()
    except Exception as e:
        st.error("Không tải được dữ liệu quản trị.")
        st.code(safe_error(e))
        return

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "👥 Tài khoản",
        len(users),
    )

    c2.metric(
        "🟢 Đang hoạt động",
        int(users["active"].sum())
        if not users.empty and "active" in users.columns
        else 0,
    )

    c3.metric(
        "📝 Lượt chấm công",
        len(att),
    )

    t1, t2, t3, t4 = st.tabs([
        "👥 Nhân viên",
        "📝 Chấm công",
        "📊 Bảng công",
        "💾 Database",
    ])

    # --------------------------------------------------------
    # NHÂN VIÊN
    # --------------------------------------------------------
    with t1:

        if not users.empty:

            show = users.copy()

            show["Trạng thái"] = show[
                "active"
            ].map({
                True: "Đang hoạt động",
                False: "Đã khóa",
            })

            show = show.rename(columns={
                "username": "Tài khoản",
                "full_name": "Họ tên",
                "role": "Vai trò",
                "department": "Bộ phận",
                "position": "Chức vụ",
            })

            columns = [
                "Tài khoản",
                "Họ tên",
                "Vai trò",
                "Bộ phận",
                "Chức vụ",
                "Trạng thái",
            ]

            st.dataframe(
                show[
                    [c for c in columns if c in show.columns]
                ],
                use_container_width=True,
                hide_index=True,
            )

        with st.expander(
            "➕ TẠO NHÂN VIÊN"
        ):

            with st.form("create_user"):

                c1, c2 = st.columns(2)

                un = c1.text_input(
                    "Tên đăng nhập *"
                )

                fn = c1.text_input(
                    "Họ tên *"
                )

                pw = c1.text_input(
                    "Mật khẩu *",
                    type="password",
                )

                role = c2.selectbox(
                    "Vai trò",
                    ["employee", "admin"],
                )

                dep = c2.text_input(
                    "Bộ phận"
                )

                pos = c2.text_input(
                    "Chức vụ"
                )

                submit = st.form_submit_button(
                    "➕ TẠO TÀI KHOẢN",
                    use_container_width=True,
                )

                if submit:

                    if not un.strip() or not fn.strip() or not pw:
                        st.error(
                            "Vui lòng nhập đủ thông tin."
                        )
                    else:

                        try:

                            sb_post(
                                "users",
                                {
                                    "username": un.strip(),
                                    "password_hash": sha256(pw),
                                    "full_name": fn.strip(),
                                    "role": role,
                                    "department": dep.strip(),
                                    "position": pos.strip(),
                                    "active": True,
                                },
                            )

                            st.success(
                                "✅ Đã tạo tài khoản."
                            )

                            st.rerun()

                        except Exception as e:

                            st.error(
                                "❌ Không tạo được tài khoản."
                            )

                            st.code(
                                safe_error(e)
                            )

    # --------------------------------------------------------
    # ADMIN CHẤM CÔNG
    # --------------------------------------------------------
    with t2:

        employees = (
            users[
                users["role"] == "employee"
            ]
            if not users.empty
            else pd.DataFrame()
        )

        if employees.empty:

            st.info(
                "Chưa có nhân viên."
            )

        else:

            options = {
                f"{r['full_name']} ({r['username']})":
                r["username"]
                for _, r in employees.iterrows()
            }

            label = st.selectbox(
                "Nhân viên",
                list(options.keys()),
            )

            selected_username = options[label]

            work_date = st.date_input(
                "Ngày",
                date.today(),
            )

            existing = None

            if not att.empty:

                temp = att.copy()

                temp["work_date"] = (
                    temp["work_date"]
                    .astype(str)
                    .str[:10]
                )

                x = temp[
                    (temp["username"].astype(str) == selected_username) &
                    (temp["work_date"] == work_date.isoformat())
                ]

                if not x.empty:
                    existing = x.iloc[0].to_dict()

            with st.form("admin_attendance"):

                c1, c2 = st.columns(2)

                ci = c1.text_input(
                    "🟢 Giờ vào",
                    value=(
                        existing.get("check_in", "")
                        if existing
                        else ""
                    ),
                )

                co = c1.text_input(
                    "🔴 Giờ ra",
                    value=(
                        existing.get("check_out", "")
                        if existing
                        else ""
                    ),
                )

                statuses = [
                    "Đi làm",
                    "Nghỉ phép",
                    "Nghỉ",
                    "Đi trễ",
                    "Về sớm",
                    "WFH",
                ]

                current_status = (
                    existing.get("status")
                    if existing
                    else None
                )

                status = c2.selectbox(
                    "Trạng thái",
                    statuses,
                    index=(
                        statuses.index(current_status)
                        if current_status in statuses
                        else 0
                    ),
                )

                note = c2.text_input(
                    "Ghi chú",
                    value=(
                        existing.get("note", "")
                        if existing
                        else ""
                    ),
                )

                a, b = st.columns(2)

                save = a.form_submit_button(
                    "💾 LƯU / SỬA",
                    use_container_width=True,
                )

                delete = b.form_submit_button(
                    "🗑️ XÓA",
                    use_container_width=True,
                )

                if save:

                    try:

                        save_attendance(
                            selected_username,
                            work_date.isoformat(),
                            ci.strip(),
                            co.strip(),
                            status,
                            note.strip(),
                        )

                        st.success(
                            "✅ Đã lưu."
                        )

                        st.rerun()

                    except Exception as e:

                        st.error(
                            "❌ Không lưu được."
                        )

                        st.code(
                            safe_error(e)
                        )

                if delete:

                    try:

                        sb_delete(
                            "attendance",
                            {
                                "username": f"eq.{selected_username}",
                                "work_date": f"eq.{work_date.isoformat()}",
                            },
                        )

                        st.success(
                            "🗑️ Đã xóa."
                        )

                        st.rerun()

                    except Exception as e:

                        st.error(
                            "❌ Không xóa được."
                        )

                        st.code(
                            safe_error(e)
                        )

    # --------------------------------------------------------
    # BẢNG CÔNG
    # --------------------------------------------------------
    with t3:

        c1, c2 = st.columns(2)

        year = c1.number_input(
            "Năm",
            2020,
            2100,
            date.today().year,
            key="admin_year",
        )

        month = c2.selectbox(
            "Tháng",
            list(range(1, 13)),
            date.today().month - 1,
            key="admin_month",
        )

        employee_options = ["Tất cả"]

        if not users.empty:

            employee_options += users[
                users["role"] == "employee"
            ]["username"].tolist()

        employee = st.selectbox(
            "Nhân viên",
            employee_options,
            key="admin_employee",
        )

        if not att.empty:

            show = att.copy()

            show["work_date"] = (
                show["work_date"]
                .astype(str)
                .str[:10]
            )

            show = show[
                show["work_date"].str.startswith(
                    f"{int(year):04d}-{int(month):02d}-"
                )
            ]

            if employee != "Tất cả":
                show = show[
                    show["username"].astype(str)
                    == employee
                ]

            if not show.empty:

                if not users.empty:

                    show = show.merge(
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

                show = show.rename(columns={
                    "username": "Tài khoản",
                    "full_name": "Họ tên",
                    "department": "Bộ phận",
                    "work_date": "Ngày",
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
                    "Giờ vào",
                    "Giờ ra",
                    "Trạng thái",
                    "Ghi chú",
                ]

                st.dataframe(
                    show[
                        [c for c in cols if c in show.columns]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

                output = io.BytesIO()

                with pd.ExcelWriter(
                    output,
                    engine="openpyxl",
                ) as writer:

                    show.to_excel(
                        writer,
                        index=False,
                        sheet_name="BangCong",
                    )

                output.seek(0)

                st.download_button(
                    "⬇️ XUẤT EXCEL",
                    output.getvalue(),
                    file_name=(
                        f"Bang_cong_"
                        f"{int(month):02d}_"
                        f"{int(year)}.xlsx"
                    ),
                    mime=(
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                    use_container_width=True,
                )

            else:
                st.info(
                    "Tháng này chưa có dữ liệu."
                )

        else:
            st.info(
                "Chưa có dữ liệu chấm công."
            )

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------
    with t4:

        st.success(
            "🟢 Dữ liệu đang được lưu trên Supabase."
        )

        st.write(
            "Website không sử dụng SQLite để lưu dữ liệu chấm công."
        )

        st.write(
            "Vì vậy Streamlit reboot/redeploy không làm mất dữ liệu."
        )

        st.caption(
            "Database gồm 2 bảng: users và attendance."
        )


# ============================================================
# RUN
# ============================================================
if user["role"] == "admin":
    admin_page()
else:
    employee_page()
