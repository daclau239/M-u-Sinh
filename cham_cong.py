
import streamlit as st
import hashlib
import hmac
import io
import calendar
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from supabase import create_client, Client

# =========================================================
# CẤU HÌNH
# =========================================================
APP_TITLE = "🕘 CHẤM CÔNG NHÂN VIÊN"
DEFAULT_ADMIN = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"

st.set_page_config(
    page_title="Chấm công",
    page_icon="🕘",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# CSS
# =========================================================
st.markdown("""
<style>
.main-title{font-size:30px;font-weight:800;margin-bottom:4px}
.sub-title{color:#6b7280;margin-bottom:20px}
.login-box{max-width:430px;margin:70px auto 0;padding:30px;border-radius:18px;
border:1px solid #e5e7eb;box-shadow:0 8px 30px rgba(0,0,0,.08);background:white}
.small-muted{color:#6b7280;font-size:13px}
div[data-testid="stMetric"]{border:1px solid #e5e7eb;padding:12px;border-radius:12px}
</style>
""", unsafe_allow_html=True)

# =========================================================
# SUPABASE
# =========================================================
def get_supabase() -> Client:
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
    except Exception:
        st.error("⚠️ Chưa cấu hình Supabase Secrets.")
        st.code(
            '[supabase]\n'
            'SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"\n'
            'SUPABASE_SERVICE_ROLE_KEY = "YOUR_SERVICE_ROLE_KEY"'
        )
        st.info("Vào Streamlit Cloud → Settings → Secrets để thêm 2 giá trị này.")
        st.stop()

    return create_client(url, key)


supabase = get_supabase()

# =========================================================
# HELPERS
# =========================================================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def normalize_record(record):
    return dict(record) if record else None


# =========================================================
# DATABASE - USERS
# =========================================================
def ensure_default_admin():
    """
    Không INSERT admin mỗi lần chạy.
    Kiểm tra trước; nếu đã có thì giữ nguyên.
    """
    try:
        result = (
            supabase.table("users")
            .select("id,username")
            .eq("username", DEFAULT_ADMIN)
            .limit(1)
            .execute()
        )

        if not result.data:
            supabase.table("users").insert({
                "username": DEFAULT_ADMIN,
                "password_hash": hash_password(DEFAULT_ADMIN_PASSWORD),
                "full_name": "Quản trị viên",
                "role": "admin",
                "department": "Quản trị",
                "position": "Administrator",
                "active": True,
            }).execute()

    except Exception as e:
        st.error("Không thể khởi tạo tài khoản quản trị.")
        st.exception(e)
        st.stop()


def authenticate(username, password):
    try:
        result = (
            supabase.table("users")
            .select("*")
            .eq("username", username.strip())
            .eq("active", True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None

        user = result.data[0]

        if hmac.compare_digest(
            user["password_hash"],
            hash_password(password)
        ):
            return user

        return None
    except Exception:
        return None


def get_user(username):
    result = (
        supabase.table("users")
        .select("*")
        .eq("username", username)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_users():
    result = (
        supabase.table("users")
        .select("id,username,full_name,role,department,position,active,created_at")
        .order("full_name")
        .execute()
    )
    return pd.DataFrame(result.data or [])


def create_user(username, password, full_name, role="employee",
                department="", position=""):
    try:
        supabase.table("users").insert({
            "username": username.strip(),
            "password_hash": hash_password(password),
            "full_name": full_name.strip(),
            "role": role,
            "department": department.strip(),
            "position": position.strip(),
            "active": True,
        }).execute()
        return True, "Tạo tài khoản thành công."
    except Exception as e:
        msg = str(e)
        if "duplicate" in msg.lower() or "unique" in msg.lower():
            return False, "Tên đăng nhập đã tồn tại."
        return False, f"Lỗi tạo tài khoản: {msg}"


def update_user(user_id, full_name, department, position, role,
                active, password=None):
    try:
        payload = {
            "full_name": full_name.strip(),
            "department": department.strip(),
            "position": position.strip(),
            "role": role,
            "active": bool(active),
        }

        if password:
            payload["password_hash"] = hash_password(password)

        supabase.table("users").update(payload).eq("id", user_id).execute()
        return True, "Đã cập nhật."
    except Exception as e:
        return False, f"Lỗi: {e}"


# =========================================================
# DATABASE - ATTENDANCE
# =========================================================
def get_attendance(username, work_date):
    result = (
        supabase.table("attendance")
        .select("*")
        .eq("username", username)
        .eq("work_date", work_date)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def upsert_attendance(username, work_date, check_in="", check_out="",
                      status="Đi làm", note=""):
    """
    UPSERT theo khóa duy nhất username + work_date.
    Chấm lại cùng ngày sẽ cập nhật đúng bản ghi,
    không tạo bản ghi trùng và không xóa lịch sử các ngày khác.
    """
    try:
        payload = {
            "username": username,
            "work_date": work_date,
            "check_in": check_in,
            "check_out": check_out,
            "status": status,
            "note": note,
        }

        supabase.table("attendance").upsert(
            payload,
            on_conflict="username,work_date"
        ).execute()

        return True
    except Exception as e:
        st.error(f"Không thể lưu chấm công: {e}")
        return False


def delete_attendance(username, work_date):
    try:
        supabase.table("attendance").delete().eq(
            "username", username
        ).eq(
            "work_date", work_date
        ).execute()
        return True
    except Exception as e:
        st.error(f"Không thể xóa: {e}")
        return False


def get_month_attendance(username, year, month):
    start = f"{year:04d}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end = f"{year:04d}-{month:02d}-{last_day:02d}"

    result = (
        supabase.table("attendance")
        .select("*")
        .eq("username", username)
        .gte("work_date", start)
        .lte("work_date", end)
        .order("work_date")
        .execute()
    )

    return pd.DataFrame(result.data or [])


def get_all_month_attendance(year, month, username=None):
    start = f"{year:04d}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end = f"{year:04d}-{month:02d}-{last_day:02d}"

    query = (
        supabase.table("attendance")
        .select("*")
        .gte("work_date", start)
        .lte("work_date", end)
        .order("work_date")
    )

    if username:
        query = query.eq("username", username)

    result = query.execute()
    df = pd.DataFrame(result.data or [])

    if not df.empty:
        users = get_users()
        if not users.empty:
            users2 = users[[
                "username", "full_name", "department", "position"
            ]]
            df = df.merge(users2, on="username", how="left")

    return df


def get_all_attendance_count():
    # Supabase REST thường trả count khi count="exact".
    try:
        result = (
            supabase.table("attendance")
            .select("id", count="exact")
            .limit(1)
            .execute()
        )
        return int(result.count or 0)
    except Exception:
        return 0


# =========================================================
# EXPORT EXCEL
# =========================================================
def make_excel(df):
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="BangCong")

        ws = writer.book["BangCong"]
        for column_cells in ws.columns:
            max_length = 0
            col_letter = column_cells[0].column_letter
            for cell in column_cells:
                value = "" if cell.value is None else str(cell.value)
                max_length = max(max_length, len(value))
            ws.column_dimensions[col_letter].width = min(
                max(max_length + 2, 12), 35
            )

    output.seek(0)
    return output.getvalue()


# =========================================================
# A4 IMAGE
# =========================================================
def get_font(size=24, bold=False):
    candidates = []

    if bold:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ]
    else:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]

    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)

    return ImageFont.load_default()


def text_center(draw, box, text, font, fill=(20, 20, 20)):
    x1, y1, x2, y2 = box
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=2)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.multiline_text(
        ((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - bbox[1]),
        text,
        font=font,
        fill=fill,
        align="center",
        spacing=2,
    )


def create_month_sheet(username, year, month):
    user = get_user(username)
    if not user:
        return None

    W, H = 1754, 1240
    margin = 55

    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    font_title = get_font(42, True)
    font_sub = get_font(25)
    font_head = get_font(22, True)
    font_cell = get_font(20)
    font_small = get_font(17)

    text_center(
        draw, (margin, 30, W-margin, 95),
        "BẢNG CHẤM CÔNG",
        font_title
    )

    draw.text(
        (margin, 115),
        f"Họ và tên: {user['full_name']}",
        font=font_sub,
        fill=(20,20,20)
    )
    draw.text(
        (margin, 150),
        f"Mã đăng nhập: {user['username']}",
        font=font_sub,
        fill=(20,20,20)
    )
    draw.text(
        (700, 115),
        f"Bộ phận: {user.get('department') or '—'}",
        font=font_sub,
        fill=(20,20,20)
    )
    draw.text(
        (700, 150),
        f"Chức vụ: {user.get('position') or '—'}",
        font=font_sub,
        fill=(20,20,20)
    )

    text_center(
        draw, (margin, 185, W-margin, 230),
        f"THÁNG {month:02d}/{year}",
        font_head
    )

    days = calendar.monthrange(year, month)[1]
    data = get_month_attendance(username, year, month)

    by_date = {}
    if not data.empty:
        by_date = {
            str(row["work_date"]): row.to_dict()
            for _, row in data.iterrows()
        }

    table_x = margin
    table_y = 255
    table_w = W - margin * 2
    table_h = 790

    label_w = 115
    day_w = (table_w - label_w) / days

    draw.rectangle(
        (table_x, table_y, table_x + table_w, table_y + table_h),
        outline=(0,0,0),
        width=2,
    )

    draw.line(
        (table_x + label_w, table_y,
         table_x + label_w, table_y + table_h),
        fill=(0,0,0), width=2
    )

    text_center(
        draw,
        (table_x, table_y, table_x + label_w, table_y + 58),
        "NGÀY",
        font_head
    )

    for d in range(1, days + 1):
        x1 = table_x + label_w + (d-1)*day_w
        x2 = table_x + label_w + d*day_w
        draw.line(
            (x2, table_y, x2, table_y + table_h),
            fill=(0,0,0), width=1
        )

        dt = date(year, month, d)
        weekday = ["T2","T3","T4","T5","T6","T7","CN"][dt.weekday()]

        text_center(
            draw,
            (x1, table_y, x2, table_y + 58),
            f"{d}\n{weekday}",
            font_small,
        )

    rows = [
        ("Trạng thái", "status"),
        ("Vào", "check_in"),
        ("Ra", "check_out"),
        ("Ghi chú", "note"),
    ]

    row_h = (table_h - 58) / len(rows)

    for i, (label, key) in enumerate(rows):
        y1 = table_y + 58 + i * row_h
        y2 = table_y + 58 + (i+1) * row_h

        draw.line(
            (table_x, y1, table_x + table_w, y1),
            fill=(0,0,0), width=1
        )

        text_center(
            draw,
            (table_x, y1, table_x + label_w, y2),
            label,
            font_head
        )

        for d in range(1, days + 1):
            x1 = table_x + label_w + (d-1)*day_w
            x2 = table_x + label_w + d*day_w

            work_date = f"{year:04d}-{month:02d}-{d:02d}"
            row = by_date.get(work_date)

            value = ""
            if row:
                value = str(row.get(key) or "")

            if key == "status":
                mapping = {
                    "Đi làm": "✓",
                    "Nghỉ phép": "P",
                    "Nghỉ": "N",
                    "Đi trễ": "T",
                    "Về sớm": "S",
                    "WFH": "WFH",
                }
                value = mapping.get(value, value[:5])

            if len(value) > 10:
                value = value[:10]

            text_center(
                draw,
                (x1, y1, x2, y2),
                value,
                font_cell
            )

    footer_y = table_y + table_h + 35
    statuses = data["status"].tolist() if not data.empty else []

    counts = {
        "Đi làm": statuses.count("Đi làm"),
        "Nghỉ phép": statuses.count("Nghỉ phép"),
        "Nghỉ": statuses.count("Nghỉ"),
        "Đi trễ": statuses.count("Đi trễ"),
        "Về sớm": statuses.count("Về sớm"),
        "WFH": statuses.count("WFH"),
    }

    summary = (
        f"Đi làm: {counts['Đi làm']}    "
        f"Nghỉ phép: {counts['Nghỉ phép']}    "
        f"Nghỉ: {counts['Nghỉ']}    "
        f"Đi trễ: {counts['Đi trễ']}    "
        f"Về sớm: {counts['Về sớm']}    "
        f"WFH: {counts['WFH']}"
    )

    draw.text(
        (margin, footer_y),
        summary,
        font=font_sub,
        fill=(20,20,20)
    )

    draw.text(
        (margin, H - 65),
        f"Xuất từ hệ thống chấm công • "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')}",
        font=font_small,
        fill=(90,90,90)
    )

    output = io.BytesIO()
    img.save(output, format="PNG", dpi=(150,150))
    output.seek(0)
    return output.getvalue()


# =========================================================
# SESSION
# =========================================================
def logout():
    for key in ["logged_in", "username", "user"]:
        st.session_state.pop(key, None)


# =========================================================
# LOGIN
# =========================================================
def login_page():
    st.markdown('<div class="login-box">', unsafe_allow_html=True)

    st.markdown(
        '<div class="main-title">🕘 Chấm công</div>',
        unsafe_allow_html=True
    )
    st.markdown(
        '<div class="sub-title">Đăng nhập hệ thống</div>',
        unsafe_allow_html=True
    )

    with st.form("login_form"):
        username = st.text_input("Tên đăng nhập")
        password = st.text_input("Mật khẩu", type="password")

        submit = st.form_submit_button(
            "🔐 Đăng nhập",
            use_container_width=True,
        )

        if submit:
            user = authenticate(username, password)

            if user:
                st.session_state.logged_in = True
                st.session_state.username = user["username"]
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Tên đăng nhập hoặc mật khẩu không đúng.")

    st.caption("Tài khoản quản trị mặc định: admin / admin123")
    st.markdown("</div>", unsafe_allow_html=True)


# =========================================================
# EMPLOYEE
# =========================================================
def employee_page(user):
    st.markdown(
        f'<div class="main-title">Xin chào, {user["full_name"]} 👋</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="sub-title">Bảng chấm công cá nhân</div>',
        unsafe_allow_html=True,
    )

    today = date.today()
    today_str = today.isoformat()
    current = get_attendance(user["username"], today_str)

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric("Ngày hôm nay", today.strftime("%d/%m/%Y"))
    with c2:
        st.metric("Giờ vào", (current or {}).get("check_in") or "—")
    with c3:
        st.metric("Giờ ra", (current or {}).get("check_out") or "—")

    st.divider()

    tab1, tab2, tab3 = st.tabs([
        "📝 Chấm công hôm nay",
        "📅 Bảng công tháng",
        "🖼️ Xuất bảng công A4",
    ])

    with tab1:
        with st.form("attendance_today"):
            col1, col2 = st.columns(2)

            with col1:
                default_in = datetime.now().time()

                if current and current.get("check_in"):
                    try:
                        default_in = datetime.strptime(
                            current["check_in"], "%H:%M"
                        ).time()
                    except Exception:
                        pass

                check_in = st.time_input(
                    "Giờ vào",
                    value=default_in,
                )

            with col2:
                default_out = datetime.now().time()

                if current and current.get("check_out"):
                    try:
                        default_out = datetime.strptime(
                            current["check_out"], "%H:%M"
                        ).time()
                    except Exception:
                        pass

                check_out = st.time_input(
                    "Giờ ra",
                    value=default_out,
                )

            status_options = [
                "Đi làm",
                "Nghỉ phép",
                "Nghỉ",
                "Đi trễ",
                "Về sớm",
                "WFH",
            ]

            status = st.selectbox(
                "Trạng thái",
                status_options,
                index=(
                    status_options.index(current["status"])
                    if current and current.get("status") in status_options
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
                ok = upsert_attendance(
                    user["username"],
                    today_str,
                    check_in.strftime("%H:%M"),
                    check_out.strftime("%H:%M"),
                    status,
                    note,
                )

                if ok:
                    st.success(
                        "✅ Đã lưu thành công. Dữ liệu đã được lưu trên database online."
                    )
                    st.rerun()

    with tab2:
        year = st.number_input(
            "Năm",
            min_value=2020,
            max_value=2100,
            value=today.year,
            step=1,
            key="emp_year",
        )

        month = st.selectbox(
            "Tháng",
            list(range(1, 13)),
            index=today.month - 1,
            key="emp_month",
        )

        df = get_month_attendance(
            user["username"],
            int(year),
            int(month)
        )

        days = calendar.monthrange(int(year), int(month))[1]
        rows = []

        for d in range(1, days + 1):
            work_date = date(int(year), int(month), d)

            found = (
                df[df["work_date"] == work_date.isoformat()]
                if not df.empty
                else pd.DataFrame()
            )

            if not found.empty:
                r = found.iloc[0]

                rows.append({
                    "Ngày": work_date.strftime("%d/%m/%Y"),
                    "Thứ": ["T2","T3","T4","T5","T6","T7","CN"][
                        work_date.weekday()
                    ],
                    "Vào": r.get("check_in", ""),
                    "Ra": r.get("check_out", ""),
                    "Trạng thái": r.get("status", ""),
                    "Ghi chú": r.get("note", ""),
                })
            else:
                rows.append({
                    "Ngày": work_date.strftime("%d/%m/%Y"),
                    "Thứ": ["T2","T3","T4","T5","T6","T7","CN"][
                        work_date.weekday()
                    ],
                    "Vào": "",
                    "Ra": "",
                    "Trạng thái": "",
                    "Ghi chú": "",
                })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )

    with tab3:
        year = st.number_input(
            "Năm xuất",
            min_value=2020,
            max_value=2100,
            value=today.year,
            step=1,
            key="emp_export_year",
        )

        month = st.selectbox(
            "Tháng xuất",
            list(range(1, 13)),
            index=today.month - 1,
            key="emp_export_month",
        )

        if st.button(
            "🖼️ Tạo bảng công A4",
            use_container_width=True
        ):
            st.session_state["export_png"] = create_month_sheet(
                user["username"],
                int(year),
                int(month),
            )
            st.session_state["export_name"] = (
                f"Bang_cong_{user['username']}_"
                f"{int(month):02d}_{int(year)}.png"
            )

        if st.session_state.get("export_png"):
            st.image(
                st.session_state["export_png"],
                use_container_width=True
            )

            st.download_button(
                "⬇️ Tải ảnh bảng công A4",
                data=st.session_state["export_png"],
                file_name=st.session_state["export_name"],
                mime="image/png",
                use_container_width=True,
            )


# =========================================================
# ADMIN
# =========================================================
def admin_dashboard(user):
    st.markdown(
        '<div class="main-title">🛠️ TRUNG TÂM QUẢN TRỊ</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="sub-title">'
        'Quản lý nhân viên và bảng chấm công'
        '</div>',
        unsafe_allow_html=True,
    )

    users_df = get_users()
    total_users = len(users_df)
    active_users = (
        int(users_df["active"].sum())
        if not users_df.empty else 0
    )
    total_records = get_all_attendance_count()

    c1, c2, c3 = st.columns(3)
    c1.metric("Tổng tài khoản", total_users)
    c2.metric("Đang hoạt động", active_users)
    c3.metric("Lượt chấm công", total_records)

    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs([
        "👥 Nhân viên",
        "📝 Nhập/sửa chấm công",
        "📊 Bảng công",
        "🖼️ Xuất A4",
    ])

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------
    with tab1:
        st.subheader("Danh sách tài khoản")

        display = users_df.copy()

        if not display.empty:
            display["active"] = display["active"].map({
                True: "Đang hoạt động",
                False: "Đã khóa",
            })

            st.dataframe(
                display.rename(columns={
                    "username": "Tên đăng nhập",
                    "full_name": "Họ tên",
                    "role": "Vai trò",
                    "department": "Bộ phận",
                    "position": "Chức vụ",
                    "active": "Trạng thái",
                    "created_at": "Ngày tạo",
                }),
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("➕ Tạo tài khoản mới"):
            with st.form("create_user"):
                c1, c2 = st.columns(2)

                with c1:
                    username = st.text_input("Tên đăng nhập *")
                    full_name = st.text_input("Họ và tên *")
                    password = st.text_input(
                        "Mật khẩu *",
                        type="password"
                    )

                with c2:
                    role = st.selectbox(
                        "Vai trò",
                        ["employee", "admin"]
                    )
                    department = st.text_input("Bộ phận")
                    position = st.text_input("Chức vụ")

                create = st.form_submit_button(
                    "Tạo tài khoản",
                    use_container_width=True,
                )

                if create:
                    if not username.strip() or not full_name.strip() or not password:
                        st.error(
                            "Vui lòng nhập đủ tên đăng nhập, họ tên và mật khẩu."
                        )
                    else:
                        ok, msg = create_user(
                            username,
                            password,
                            full_name,
                            role,
                            department,
                            position,
                        )

                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

        with st.expander("✏️ Chỉnh sửa tài khoản"):
            employee_rows = users_df

            if employee_rows.empty:
                st.info("Chưa có tài khoản.")
            else:
                usernames = employee_rows["username"].tolist()

                selected_username = st.selectbox(
                    "Chọn tài khoản",
                    usernames,
                    key="edit_username",
                )

                selected = get_user(selected_username)

                if selected:
                    with st.form("edit_user"):
                        c1, c2 = st.columns(2)

                        with c1:
                            full_name = st.text_input(
                                "Họ và tên",
                                value=selected["full_name"],
                            )

                            department = st.text_input(
                                "Bộ phận",
                                value=selected.get("department") or "",
                            )

                            position = st.text_input(
                                "Chức vụ",
                                value=selected.get("position") or "",
                            )

                        with c2:
                            role_options = ["employee", "admin"]

                            role = st.selectbox(
                                "Vai trò",
                                role_options,
                                index=(
                                    role_options.index(selected["role"])
                                    if selected["role"] in role_options
                                    else 0
                                ),
                            )

                            active = st.checkbox(
                                "Tài khoản đang hoạt động",
                                value=bool(selected["active"]),
                            )

                            new_password = st.text_input(
                                "Mật khẩu mới "
                                "(để trống nếu không đổi)",
                                type="password",
                            )

                        save = st.form_submit_button(
                            "💾 Lưu thay đổi",
                            use_container_width=True,
                        )

                        if save:
                            # Không cho khóa chính mình.
                            if (
                                selected["username"] == user["username"]
                                and not active
                            ):
                                st.error(
                                    "Không thể tự khóa tài khoản đang đăng nhập."
                                )
                            else:
                                ok, msg = update_user(
                                    selected["id"],
                                    full_name,
                                    department,
                                    position,
                                    role,
                                    active,
                                    new_password or None,
                                )

                                if ok:
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)

    # -----------------------------------------------------
    # ADMIN ATTENDANCE
    # -----------------------------------------------------
    with tab2:
        st.subheader("Nhập / sửa chấm công")

        employee_df = users_df[
            users_df["role"] == "employee"
        ].copy()

        if employee_df.empty:
            st.info("Chưa có nhân viên.")
        else:
            employee_options = {
                f"{r['full_name']} ({r['username']})":
                    r["username"]
                for _, r in employee_df.iterrows()
            }

            selected_label = st.selectbox(
                "Nhân viên",
                list(employee_options.keys()),
            )

            selected_username = employee_options[selected_label]

            work_date = st.date_input(
                "Ngày",
                value=date.today(),
            )

            existing = get_attendance(
                selected_username,
                work_date.isoformat()
            )

            with st.form("admin_attendance"):
                c1, c2 = st.columns(2)

                with c1:
                    check_in = st.text_input(
                        "Giờ vào (HH:MM)",
                        value=(existing or {}).get("check_in", ""),
                    )

                    status_options = [
                        "Đi làm",
                        "Nghỉ phép",
                        "Nghỉ",
                        "Đi trễ",
                        "Về sớm",
                        "WFH",
                    ]

                    status = st.selectbox(
                        "Trạng thái",
                        status_options,
                        index=(
                            status_options.index(existing["status"])
                            if existing and existing.get("status")
                            in status_options
                            else 0
                        ),
                    )

                with c2:
                    check_out = st.text_input(
                        "Giờ ra (HH:MM)",
                        value=(existing or {}).get("check_out", ""),
                    )

                    note = st.text_input(
                        "Ghi chú",
                        value=(existing or {}).get("note", ""),
                    )

                c1, c2 = st.columns(2)

                with c1:
                    save = st.form_submit_button(
                        "💾 Lưu",
                        use_container_width=True,
                    )

                with c2:
                    remove = st.form_submit_button(
                        "🗑️ Xóa ngày này",
                        use_container_width=True,
                    )

                if save:
                    ok = upsert_attendance(
                        selected_username,
                        work_date.isoformat(),
                        check_in.strip(),
                        check_out.strip(),
                        status,
                        note.strip(),
                    )

                    if ok:
                        st.success("Đã lưu.")
                        st.rerun()

                if remove:
                    if delete_attendance(
                        selected_username,
                        work_date.isoformat()
                    ):
                        st.success("Đã xóa.")
                        st.rerun()

    # -----------------------------------------------------
    # MONTH TABLE
    # -----------------------------------------------------
    with tab3:
        st.subheader("Bảng công")

        c1, c2 = st.columns(2)

        with c1:
            year = st.number_input(
                "Năm",
                min_value=2020,
                max_value=2100,
                value=date.today().year,
                step=1,
                key="admin_table_year",
            )

        with c2:
            month = st.selectbox(
                "Tháng",
                range(1, 13),
                index=date.today().month - 1,
                key="admin_table_month",
            )

        employee_choices = ["Tất cả"] + list(
            users_df.loc[
                users_df["role"] == "employee",
                "username"
            ]
        )

        emp = st.selectbox(
            "Nhân viên",
            employee_choices,
            key="admin_table_emp",
        )

        username_filter = None if emp == "Tất cả" else emp

        df = get_all_month_attendance(
            int(year),
            int(month),
            username_filter
        )

        if df.empty:
            st.info("Chưa có dữ liệu chấm công trong tháng này.")
        else:
            show_df = df.rename(columns={
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

            st.dataframe(
                show_df,
                use_container_width=True,
                hide_index=True
            )

            excel_data = make_excel(show_df)

            st.download_button(
                "⬇️ Xuất Excel",
                data=excel_data,
                file_name=(
                    f"Bang_cong_{int(month):02d}_{int(year)}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                use_container_width=True,
            )

    # -----------------------------------------------------
    # A4
    # -----------------------------------------------------
    with tab4:
        st.subheader("Xuất bảng công thành ảnh A4")

        employee_df = users_df[
            users_df["role"] == "employee"
        ].copy()

        if employee_df.empty:
            st.info("Chưa có nhân viên.")
        else:
            employee_options = {
                f"{r['full_name']} ({r['username']})":
                    r["username"]
                for _, r in employee_df.iterrows()
            }

            selected_label = st.selectbox(
                "Chọn nhân viên",
                list(employee_options.keys()),
                key="a4_employee",
            )

            selected_username = employee_options[selected_label]

            c1, c2 = st.columns(2)

            with c1:
                year = st.number_input(
                    "Năm",
                    min_value=2020,
                    max_value=2100,
                    value=date.today().year,
                    step=1,
                    key="a4_year",
                )

            with c2:
                month = st.selectbox(
                    "Tháng",
                    range(1, 13),
                    index=date.today().month - 1,
                    key="a4_month",
                )

            if st.button(
                "🖼️ Tạo ảnh bảng công A4",
                use_container_width=True,
            ):
                st.session_state["admin_export_png"] = (
                    create_month_sheet(
                        selected_username,
                        int(year),
                        int(month),
                    )
                )

                st.session_state["admin_export_name"] = (
                    f"Bang_cong_{selected_username}_"
                    f"{int(month):02d}_{int(year)}.png"
                )

            if st.session_state.get("admin_export_png"):
                st.image(
                    st.session_state["admin_export_png"],
                    use_container_width=True,
                )

                st.download_button(
                    "⬇️ Tải ảnh A4",
                    data=st.session_state["admin_export_png"],
                    file_name=st.session_state["admin_export_name"],
                    mime="image/png",
                    use_container_width=True,
                )


# =========================================================
# MAIN
# =========================================================
# Chỉ chạy kiểm tra admin sau khi kết nối Supabase.
ensure_default_admin()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    login_page()
    st.stop()

username = st.session_state.get("username")
user = get_user(username)

if not user or not user["active"]:
    logout()
    st.rerun()

with st.sidebar:
    st.markdown("## 🕘 CHẤM CÔNG")
    st.caption(f"Xin chào **{user['full_name']}**")
    st.caption(f"Tài khoản: `{user['username']}`")
    st.caption(f"Vai trò: `{user['role']}`")

    st.divider()

    if st.button("🚪 Đăng xuất", use_container_width=True):
        logout()
        st.rerun()

if user["role"] == "admin":
    admin_dashboard(user)
else:
    employee_page(user)
