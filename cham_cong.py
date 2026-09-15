import streamlit as st
import pandas as pd
import requests
import hashlib
import hmac
import io
from datetime import date, datetime
import calendar

# ============================================================
# 🕘 WEB CHẤM CÔNG - SUPABASE ONLINE
# ============================================================
# Dữ liệu chấm công lưu trực tiếp trên Supabase Database.
#
# STREAMLIT SECRETS:
# SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
# SUPABASE_SECRET_KEY = "sb_secret_..."
#
# KHÔNG đặt Secret Key trong code/GitHub.
# ============================================================

st.set_page_config(
    page_title="Web Chấm Công",
    page_icon="🕘",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# LẤY SECRETS
# ============================================================
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"].strip().rstrip("/")
    SUPABASE_SECRET_KEY = st.secrets["SUPABASE_SECRET_KEY"].strip()
except Exception:
    SUPABASE_URL = ""
    SUPABASE_SECRET_KEY = ""

REST_URL = f"{SUPABASE_URL}/rest/v1" if SUPABASE_URL else ""

# ============================================================
# CSS
# ============================================================
st.markdown("""
<style>
.block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
}
.main-title {
    font-size: 2.15rem;
    font-weight: 800;
    margin-bottom: .2rem;
}
.sub-title {
    color: #6b7280;
    margin-bottom: 1.25rem;
}
.login-box {
    max-width: 430px;
    margin: 70px auto;
    padding: 28px;
    border: 1px solid #e5e7eb;
    border-radius: 18px;
    box-shadow: 0 8px 30px rgba(0,0,0,.08);
}
.success-box {
    padding: 14px 16px;
    border-radius: 12px;
    border: 1px solid #bbf7d0;
    background: #f0fdf4;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# HASH
# ============================================================
def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

# ============================================================
# SUPABASE REST
# Supabase mới yêu cầu sb_secret_... đi qua apikey header,
# KHÔNG dùng Authorization: Bearer cho secret key.
# ============================================================
def auth_headers():
    return {
        "apikey": SUPABASE_SECRET_KEY,
        "Content-Type": "application/json",
    }


def sb_request(method, table, params=None, payload=None, prefer=None):
    if not REST_URL or not SUPABASE_SECRET_KEY:
        raise RuntimeError("Thiếu Supabase Secrets.")

    headers = auth_headers()
    if prefer:
        headers["Prefer"] = prefer

    response = requests.request(
        method=method,
        url=f"{REST_URL}/{table}",
        params=params or {},
        json=payload,
        headers=headers,
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"Supabase {response.status_code}: {response.text}"
        )

    if not response.text:
        return []

    return response.json()


def sb_select(table, params=None):
    return sb_request("GET", table, params=params)


def sb_insert(table, payload):
    return sb_request(
        "POST",
        table,
        payload=payload,
        prefer="return=representation",
    )


def sb_upsert(table, payload):
    return sb_request(
        "POST",
        table,
        payload=payload,
        prefer="resolution=merge-duplicates,return=representation",
    )


def sb_update(table, params, payload):
    return sb_request(
        "PATCH",
        table,
        params=params,
        payload=payload,
        prefer="return=representation",
    )


def sb_delete(table, params):
    return sb_request(
        "DELETE",
        table,
        params=params,
        prefer="return=minimal",
    )


def safe_error(err):
    msg = str(err)
    if SUPABASE_SECRET_KEY:
        msg = msg.replace(SUPABASE_SECRET_KEY, "[HIDDEN]")
    return msg


# ============================================================
# DATA
# ============================================================
def get_users_df():
    rows = sb_select(
        "users",
        {
            "select": "id,username,password_hash,full_name,role,department,position,active,created_at",
            "order": "created_at.asc",
        },
    )
    return pd.DataFrame(rows)


def get_attendance_df():
    rows = sb_select(
        "attendance",
        {
            "select": "id,username,work_date,check_in,check_out,status,note,created_at,updated_at",
            "order": "work_date.desc",
        },
    )
    return pd.DataFrame(rows)


def get_user(username):
    rows = sb_select(
        "users",
        {
            "select": "*",
            "username": f"eq.{username}",
            "limit": "1",
        },
    )
    return rows[0] if rows else None


def get_today_attendance(username):
    rows = sb_select(
        "attendance",
        {
            "select": "*",
            "username": f"eq.{username}",
            "work_date": f"eq.{date.today().isoformat()}",
            "limit": "1",
        },
    )
    return rows[0] if rows else None


def authenticate(username, password):
    user = get_user(username.strip())
    if not user:
        return None
    if not bool(user.get("active")):
        return None

    stored_hash = str(user.get("password_hash", ""))
    if hmac.compare_digest(stored_hash, sha256(password)):
        return user
    return None


def save_attendance(username, work_date, check_in, check_out, status, note):
    # Unique(username, work_date) trong DB đảm bảo mỗi người
    # chỉ có một dòng cho một ngày. UPSERT sẽ cập nhật dòng cũ.
    return sb_upsert(
        "attendance",
        {
            "username": username,
            "work_date": work_date,
            "check_in": check_in,
            "check_out": check_out,
            "status": status,
            "note": note,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )


def create_user(username, password, full_name, role, department, position):
    return sb_insert(
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


def update_user(
    user_id,
    full_name,
    role,
    department,
    position,
    active,
    new_password=None,
):
    payload = {
        "full_name": full_name.strip(),
        "role": role,
        "department": department.strip(),
        "position": position.strip(),
        "active": bool(active),
    }

    if new_password:
        payload["password_hash"] = sha256(new_password)

    return sb_update(
        "users",
        {"id": f"eq.{user_id}"},
        payload,
    )


def delete_attendance(username, work_date):
    return sb_delete(
        "attendance",
        {
            "username": f"eq.{username}",
            "work_date": f"eq.{work_date}",
        },
    )


def make_month_table(username, year, month):
    df = get_attendance_df()

    if not df.empty:
        df["work_date"] = (
            df["work_date"].astype(str).str[:10]
        )
        df = df[
            (df["username"].astype(str) == str(username))
            & (
                df["work_date"].str.startswith(
                    f"{int(year):04d}-{int(month):02d}-"
                )
            )
        ]

    rows = []
    total_days = calendar.monthrange(int(year), int(month))[1]
    weekday_names = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

    for d in range(1, total_days + 1):
        dt = date(int(year), int(month), d)

        match = (
            df[df["work_date"] == dt.isoformat()]
            if not df.empty
            else pd.DataFrame()
        )

        if not match.empty:
            r = match.iloc[0]
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


def month_records_for_admin(year, month, username=None):
    df = get_attendance_df()

    if df.empty:
        return df

    df["work_date"] = df["work_date"].astype(str).str[:10]

    mask = df["work_date"].str.startswith(
        f"{int(year):04d}-{int(month):02d}-"
    )

    if username:
        mask &= df["username"].astype(str) == str(username)

    return df[mask].copy()


# ============================================================
# SECRETS CHƯA CÓ
# ============================================================
if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    st.markdown(
        '<div class="main-title">🕘 WEB CHẤM CÔNG</div>',
        unsafe_allow_html=True,
    )
    st.warning("Chưa cấu hình Supabase.")

    st.markdown("""
### Điền Secrets trên Streamlit Cloud

Vào **Manage app → Settings → Secrets** và dán:

```toml
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_..."
```

Sau đó bấm **Save → Reboot app**.

Secret key phải nằm trong Secrets, không nằm trong file Python/GitHub.
""")
    st.stop()


# ============================================================
# TEST DATABASE
# ============================================================
try:
    sb_select(
        "users",
        {
            "select": "id",
            "limit": "1",
        },
    )
except Exception as e:
    st.error("❌ Không kết nối được database Supabase.")
    st.code(safe_error(e))
    st.markdown("""
Kiểm tra:
1. `SUPABASE_URL` đúng.
2. `SUPABASE_SECRET_KEY` đúng.
3. Hai bảng `users` và `attendance` đã được tạo trong SQL Editor.
""")
    st.stop()


# ============================================================
# LOGIN
# ============================================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.markdown(
        '<div class="login-box">',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="main-title">🕘 WEB CHẤM CÔNG</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="sub-title">Đăng nhập hệ thống</div>',
        unsafe_allow_html=True,
    )

    with st.form("login_form"):
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
                    st.error(
                        "Sai tên đăng nhập, mật khẩu hoặc tài khoản đã bị khóa."
                    )
            except Exception as e:
                st.error("Lỗi khi đăng nhập.")
                st.code(safe_error(e))

    st.caption("Tài khoản mặc định: admin / admin123")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


# ============================================================
# LOAD CURRENT USER
# ============================================================
try:
    current_user = get_user(
        st.session_state.username
    )
except Exception as e:
    st.error("Không đọc được tài khoản.")
    st.code(safe_error(e))
    st.stop()

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

    if current_user.get("department"):
        st.caption(f"🏢 {current_user['department']}")
    if current_user.get("position"):
        st.caption(f"💼 {current_user['position']}")

    st.divider()

    if st.button("🚪 Đăng xuất", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# ============================================================
# EMPLOYEE PAGE
# ============================================================
def employee_page():
    today = date.today()

    try:
        current = get_today_attendance(
            current_user["username"]
        )
    except Exception as e:
        st.error("Không tải được dữ liệu hôm nay.")
        st.code(safe_error(e))
        return

    st.markdown(
        f'<div class="main-title">'
        f'Xin chào, {current_user["full_name"]} 👋'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="sub-title">'
        'Dữ liệu được lưu trực tiếp trên database online.'
        '</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("📅 Hôm nay", today.strftime("%d/%m/%Y"))
    c2.metric("🟢 Giờ vào", (current or {}).get("check_in") or "—")
    c3.metric("🔴 Giờ ra", (current or {}).get("check_out") or "—")

    tab1, tab2, tab3 = st.tabs([
        "📝 Chấm công",
        "📅 Bảng công",
        "📊 Xuất Excel",
    ])

    # --------------------------------------------------------
    # CHẤM CÔNG
    # --------------------------------------------------------
    with tab1:
        with st.form("attendance_form"):
            ci_default = datetime.now().time()
            co_default = datetime.now().time()

            if current:
                try:
                    if current.get("check_in"):
                        ci_default = datetime.strptime(
                            current["check_in"],
                            "%H:%M",
                        ).time()
                    if current.get("check_out"):
                        co_default = datetime.strptime(
                            current["check_out"],
                            "%H:%M",
                        ).time()
                except Exception:
                    pass

            c1, c2 = st.columns(2)

            check_in = c1.time_input(
                "🟢 Giờ vào",
                value=ci_default,
            )
            check_out = c2.time_input(
                "🔴 Giờ ra",
                value=co_default,
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
                if current else None
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
                value=(current or {}).get("note", ""),
            )

            save = st.form_submit_button(
                "💾 LƯU CHẤM CÔNG",
                use_container_width=True,
            )

            if save:
                try:
                    save_attendance(
                        current_user["username"],
                        today.isoformat(),
                        check_in.strftime("%H:%M"),
                        check_out.strftime("%H:%M"),
                        status,
                        note,
                    )
                    st.success(
                        "✅ Đã lưu. Dữ liệu đã được lưu trên website/database."
                    )
                    st.rerun()
                except Exception as e:
                    st.error("Không lưu được chấm công.")
                    st.code(safe_error(e))

    # --------------------------------------------------------
    # BẢNG CÔNG
    # --------------------------------------------------------
    with tab2:
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
                current_user["username"],
                year,
                month,
            )
            st.dataframe(
                table,
                use_container_width=True,
                hide_index=True,
            )
        except Exception as e:
            st.error("Không tải được bảng công.")
            st.code(safe_error(e))

    # --------------------------------------------------------
    # EXCEL
    # --------------------------------------------------------
    with tab3:
        c1, c2 = st.columns(2)

        year = c1.number_input(
            "Năm xuất",
            min_value=2020,
            max_value=2100,
            value=today.year,
            step=1,
            key="export_year",
        )

        month = c2.selectbox(
            "Tháng xuất",
            list(range(1, 13)),
            index=today.month - 1,
            key="export_month",
        )

        try:
            export_df = make_month_table(
                current_user["username"],
                year,
                month,
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
                    f"Bang_cong_{current_user['username']}_"
                    f"{int(month):02d}_{int(year)}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                use_container_width=True,
            )
        except Exception as e:
            st.error("Không tạo được Excel.")
            st.code(safe_error(e))


# ============================================================
# ADMIN PAGE
# ============================================================
def admin_page():
    st.markdown(
        '<div class="main-title">🛠️ TRUNG TÂM QUẢN TRỊ</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="sub-title">'
        'Quản lý nhân viên và dữ liệu chấm công.'
        '</div>',
        unsafe_allow_html=True,
    )

    try:
        users = get_users_df()
        attendance = get_attendance_df()
    except Exception as e:
        st.error("Không tải được dữ liệu quản trị.")
        st.code(safe_error(e))
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("👥 Tài khoản", len(users))
    c2.metric(
        "🟢 Đang hoạt động",
        int(users["active"].sum())
        if not users.empty and "active" in users.columns
        else 0,
    )
    c3.metric("📝 Lượt chấm công", len(attendance))

    tab1, tab2, tab3 = st.tabs([
        "👥 Nhân viên",
        "📝 Chấm công",
        "📊 Bảng công",
    ])

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------
    with tab1:
        if not users.empty:
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

            cols = [
                "Tài khoản",
                "Họ tên",
                "Vai trò",
                "Bộ phận",
                "Chức vụ",
                "Trạng thái",
            ]

            st.dataframe(
                display[
                    [c for c in cols if c in display.columns]
                ],
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("➕ Tạo tài khoản"):
            with st.form("create_user_form"):
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
                            create_user(
                                username,
                                password,
                                full_name,
                                role,
                                department,
                                position,
                            )
                            st.success("✅ Đã tạo tài khoản.")
                            st.rerun()
                        except Exception as e:
                            st.error("Không tạo được tài khoản.")
                            st.code(safe_error(e))

        with st.expander("✏️ Chỉnh sửa tài khoản"):
            if users.empty:
                st.info("Chưa có tài khoản.")
            else:
                usernames = users["username"].tolist()

                selected_username = st.selectbox(
                    "Chọn tài khoản",
                    usernames,
                    key="edit_username",
                )

                selected_user = get_user(selected_username)

                if selected_user:
                    with st.form("edit_user_form"):
                        c1, c2 = st.columns(2)

                        full_name = c1.text_input(
                            "Họ tên",
                            value=selected_user["full_name"],
                        )
                        department = c1.text_input(
                            "Bộ phận",
                            value=selected_user.get("department", ""),
                        )
                        position = c1.text_input(
                            "Chức vụ",
                            value=selected_user.get("position", ""),
                        )

                        roles = ["employee", "admin"]

                        role = c2.selectbox(
                            "Vai trò",
                            roles,
                            index=(
                                roles.index(selected_user["role"])
                                if selected_user["role"] in roles
                                else 0
                            ),
                        )

                        active = c2.checkbox(
                            "Đang hoạt động",
                            value=bool(selected_user["active"]),
                        )

                        new_password = c2.text_input(
                            "Mật khẩu mới (để trống nếu không đổi)",
                            type="password",
                        )

                        if st.form_submit_button(
                            "💾 LƯU THAY ĐỔI",
                            use_container_width=True,
                        ):
                            if (
                                selected_user["username"]
                                == current_user["username"]
                                and not active
                            ):
                                st.error(
                                    "Không thể tự khóa tài khoản đang đăng nhập."
                                )
                            else:
                                try:
                                    update_user(
                                        selected_user["id"],
                                        full_name,
                                        role,
                                        department,
                                        position,
                                        active,
                                        new_password or None,
                                    )
                                    st.success("✅ Đã cập nhật.")
                                    st.rerun()
                                except Exception as e:
                                    st.error("Không cập nhật được.")
                                    st.code(safe_error(e))

    # --------------------------------------------------------
    # ADMIN ATTENDANCE
    # --------------------------------------------------------
    with tab2:
        employees = (
            users[users["role"] == "employee"].copy()
            if not users.empty
            else pd.DataFrame()
        )

        if employees.empty:
            st.info("Chưa có nhân viên.")
        else:
            options = {
                f"{r['full_name']} ({r['username']})":
                r["username"]
                for _, r in employees.iterrows()
            }

            selected_label = st.selectbox(
                "Nhân viên",
                list(options.keys()),
                key="admin_employee_select",
            )
            selected_username = options[selected_label]

            work_date = st.date_input(
                "Ngày",
                date.today(),
                key="admin_work_date",
            )

            existing = None

            if not attendance.empty:
                temp = attendance.copy()
                temp["work_date"] = (
                    temp["work_date"].astype(str).str[:10]
                )
                match = temp[
                    (temp["username"].astype(str) == selected_username)
                    & (temp["work_date"] == work_date.isoformat())
                ]
                if not match.empty:
                    existing = match.iloc[0].to_dict()

            with st.form("admin_attendance_form"):
                c1, c2 = st.columns(2)

                check_in = c1.text_input(
                    "Giờ vào",
                    value=(existing or {}).get("check_in", ""),
                )
                check_out = c1.text_input(
                    "Giờ ra",
                    value=(existing or {}).get("check_out", ""),
                )

                statuses = [
                    "Đi làm",
                    "Nghỉ phép",
                    "Nghỉ",
                    "Đi trễ",
                    "Về sớm",
                    "WFH",
                ]

                old_status = (
                    existing.get("status")
                    if existing
                    else None
                )

                status = c2.selectbox(
                    "Trạng thái",
                    statuses,
                    index=(
                        statuses.index(old_status)
                        if old_status in statuses
                        else 0
                    ),
                )

                note = c2.text_input(
                    "Ghi chú",
                    value=(existing or {}).get("note", ""),
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
                            check_in.strip(),
                            check_out.strip(),
                            status,
                            note.strip(),
                        )
                        st.success("✅ Đã lưu.")
                        st.rerun()
                    except Exception as e:
                        st.error("Không lưu được.")
                        st.code(safe_error(e))

                if delete:
                    try:
                        delete_attendance(
                            selected_username,
                            work_date.isoformat(),
                        )
                        st.success("🗑️ Đã xóa.")
                        st.rerun()
                    except Exception as e:
                        st.error("Không xóa được.")
                        st.code(safe_error(e))

    # --------------------------------------------------------
    # MONTHLY REPORT
    # --------------------------------------------------------
    with tab3:
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
            key="admin_filter_employee",
        )

        try:
            report = month_records_for_admin(
                year,
                month,
                None if employee == "Tất cả" else employee,
            )

            if report.empty:
                st.info("Tháng này chưa có dữ liệu.")
            else:
                if not users.empty:
                    report = report.merge(
                        users[
                            ["username", "full_name", "department", "position"]
                        ],
                        on="username",
                        how="left",
                    )

                report = report.rename(columns={
                    "username": "Tài khoản",
                    "full_name": "Họ tên",
                    "department": "Bộ phận",
                    "position": "Chức vụ",
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
                    "Chức vụ",
                    "Ngày",
                    "Giờ vào",
                    "Giờ ra",
                    "Trạng thái",
                    "Ghi chú",
                ]

                report = report[
                    [c for c in cols if c in report.columns]
                ]

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

        except Exception as e:
            st.error("Không tải được báo cáo.")
            st.code(safe_error(e))


# ============================================================
# RUN
# ============================================================
if current_user["role"] == "admin":
    admin_page()
else:
    employee_page()
