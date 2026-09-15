
import streamlit as st
import sqlite3
import hashlib
import hmac
import io
import calendar
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

# =========================================================
# CẤU HÌNH
# =========================================================
APP_TITLE = "🕘 CHẤM CÔNG NHÂN VIÊN"
DB_PATH = Path("cham_cong.db")

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
    .main-title {
        font-size: 30px;
        font-weight: 800;
        margin-bottom: 4px;
    }
    .sub-title {
        color: #6b7280;
        margin-bottom: 20px;
    }
    .login-box {
        max-width: 430px;
        margin: 70px auto 0 auto;
        padding: 30px;
        border-radius: 18px;
        border: 1px solid #e5e7eb;
        box-shadow: 0 8px 30px rgba(0,0,0,.08);
        background: white;
    }
    .stat-card {
        padding: 18px;
        border-radius: 14px;
        border: 1px solid #e5e7eb;
        background: #ffffff;
    }
    .small-muted {
        color: #6b7280;
        font-size: 13px;
    }
    div[data-testid="stMetric"] {
        border: 1px solid #e5e7eb;
        padding: 12px;
        border-radius: 12px;
    }
</style>
""", unsafe_allow_html=True)


# =========================================================
# DATABASE
# =========================================================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def init_db():
    conn = get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'employee',
                department TEXT DEFAULT '',
                position TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                work_date TEXT NOT NULL,
                check_in TEXT DEFAULT '',
                check_out TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Đi làm',
                note TEXT DEFAULT '',
                UNIQUE(username, work_date)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_attendance_date
            ON attendance(work_date)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_attendance_user_date
            ON attendance(username, work_date)
        """)

        # FIX QUAN TRỌNG:
        # Không INSERT admin mù -> tránh sqlite3.IntegrityError khi admin đã tồn tại.
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (DEFAULT_ADMIN,)
        ).fetchone()

        if existing is None:
            conn.execute("""
                INSERT INTO users
                (username, password_hash, full_name, role, department, position, active)
                VALUES (?, ?, ?, 'admin', ?, ?, 1)
            """, (
                DEFAULT_ADMIN,
                hash_password(DEFAULT_ADMIN_PASSWORD),
                "Quản trị viên",
                "Quản trị",
                "Administrator",
            ))

        conn.commit()
    finally:
        conn.close()


def query_df(sql, params=()):
    conn = get_conn()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


# =========================================================
# USER
# =========================================================
def authenticate(username, password):
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT *
            FROM users
            WHERE username = ? AND active = 1
            LIMIT 1
        """, (username.strip(),)).fetchone()

        if not row:
            return None

        if hmac.compare_digest(
            row["password_hash"],
            hash_password(password)
        ):
            return dict(row)
        return None
    finally:
        conn.close()


def create_user(username, password, full_name, role="employee",
                department="", position=""):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO users
            (username, password_hash, full_name, role, department, position, active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (
            username.strip(),
            hash_password(password),
            full_name.strip(),
            role,
            department.strip(),
            position.strip(),
        ))
        conn.commit()
        return True, "Tạo tài khoản thành công."
    except sqlite3.IntegrityError:
        return False, "Tên đăng nhập đã tồn tại."
    except Exception as e:
        return False, f"Lỗi: {e}"
    finally:
        conn.close()


def update_user(user_id, full_name, department, position, role, active, password=None):
    conn = get_conn()
    try:
        if password:
            conn.execute("""
                UPDATE users
                SET full_name=?, department=?, position=?, role=?, active=?,
                    password_hash=?
                WHERE id=?
            """, (
                full_name.strip(),
                department.strip(),
                position.strip(),
                role,
                int(active),
                hash_password(password),
                user_id,
            ))
        else:
            conn.execute("""
                UPDATE users
                SET full_name=?, department=?, position=?, role=?, active=?
                WHERE id=?
            """, (
                full_name.strip(),
                department.strip(),
                position.strip(),
                role,
                int(active),
                user_id,
            ))
        conn.commit()
        return True, "Đã cập nhật."
    except Exception as e:
        return False, f"Lỗi: {e}"
    finally:
        conn.close()


def get_user(username):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? LIMIT 1",
            (username,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# =========================================================
# ATTENDANCE
# =========================================================
def get_attendance(username, work_date):
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT *
            FROM attendance
            WHERE username=? AND work_date=?
            LIMIT 1
        """, (username, work_date)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_attendance(username, work_date, check_in="", check_out="",
                      status="Đi làm", note=""):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO attendance
            (username, work_date, check_in, check_out, status, note)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, work_date)
            DO UPDATE SET
                check_in=excluded.check_in,
                check_out=excluded.check_out,
                status=excluded.status,
                note=excluded.note
        """, (
            username, work_date, check_in, check_out, status, note
        ))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Không thể lưu chấm công: {e}")
        return False
    finally:
        conn.close()


def delete_attendance(username, work_date):
    conn = get_conn()
    try:
        conn.execute("""
            DELETE FROM attendance
            WHERE username=? AND work_date=?
        """, (username, work_date))
        conn.commit()
    finally:
        conn.close()


def get_month_attendance(username, year, month):
    start = f"{year:04d}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end = f"{year:04d}-{month:02d}-{last_day:02d}"

    return query_df("""
        SELECT *
        FROM attendance
        WHERE username=?
          AND work_date BETWEEN ? AND ?
        ORDER BY work_date
    """, (username, start, end))


def get_all_month_attendance(year, month, username=None):
    start = f"{year:04d}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end = f"{year:04d}-{month:02d}-{last_day:02d}"

    if username:
        return query_df("""
            SELECT a.*, u.full_name, u.department, u.position
            FROM attendance a
            LEFT JOIN users u ON u.username=a.username
            WHERE a.work_date BETWEEN ? AND ?
              AND a.username=?
            ORDER BY a.work_date
        """, (start, end, username))

    return query_df("""
        SELECT a.*, u.full_name, u.department, u.position
        FROM attendance a
        LEFT JOIN users u ON u.username=a.username
        WHERE a.work_date BETWEEN ? AND ?
        ORDER BY u.full_name, a.work_date
    """, (start, end))


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
            ws.column_dimensions[col_letter].width = min(max(max_length + 2, 12), 35)

    output.seek(0)
    return output.getvalue()


# =========================================================
# FONT CHO ẢNH A4
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
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        ((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - bbox[1]),
        text,
        font=font,
        fill=fill,
    )


def create_month_sheet(username, year, month):
    user = get_user(username)
    if not user:
        return None

    # A4 landscape @ 150 DPI
    W, H = 1754, 1240
    margin = 55

    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    font_title = get_font(42, True)
    font_sub = get_font(25, False)
    font_head = get_font(22, True)
    font_cell = get_font(20, False)
    font_small = get_font(17, False)

    title = "BẢNG CHẤM CÔNG"
    text_center(draw, (margin, 30, W-margin, 95), title, font_title)

    info1 = f"Họ và tên: {user['full_name']}"
    info2 = f"Mã đăng nhập: {user['username']}"
    info3 = f"Phòng/Bộ phận: {user.get('department') or '—'}"
    info4 = f"Chức vụ: {user.get('position') or '—'}"

    draw.text((margin, 115), info1, font=font_sub, fill=(20,20,20))
    draw.text((margin, 150), info2, font=font_sub, fill=(20,20,20))
    draw.text((700, 115), info3, font=font_sub, fill=(20,20,20))
    draw.text((700, 150), info4, font=font_sub, fill=(20,20,20))

    month_name = f"THÁNG {month:02d}/{year}"
    text_center(draw, (margin, 185, W-margin, 230), month_name, font_head)

    days = calendar.monthrange(year, month)[1]
    data = get_month_attendance(username, year, month)
    by_date = {
        str(row["work_date"]): row
        for _, row in data.iterrows()
    }

    # Bảng 31 ngày; A4 landscape, mỗi ô ngày nhỏ.
    table_x = margin
    table_y = 255
    table_w = W - margin * 2
    table_h = 790

    # 1 cột STT + 31 ngày
    label_w = 115
    day_w = (table_w - label_w) / days

    # Header
    draw.rectangle(
        (table_x, table_y, table_x + table_w, table_y + 58),
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
        font_head,
    )

    for d in range(1, days + 1):
        x1 = table_x + label_w + (d-1)*day_w
        x2 = table_x + label_w + d*day_w
        draw.line((x2, table_y, x2, table_y + table_h),
                  fill=(0,0,0), width=1)

        dt = date(year, month, d)
        weekday = ["T2","T3","T4","T5","T6","T7","CN"][dt.weekday()]
        text_center(
            draw,
            (x1, table_y, x2, table_y + 58),
            f"{d}\n{weekday}",
            font_small,
        )

    # Các dòng
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

        draw.line((table_x, y1, table_x + table_w, y1),
                  fill=(0,0,0), width=1)

        text_center(draw, (table_x, y1, table_x + label_w, y2),
                    label, font_head)

        for d in range(1, days + 1):
            x1 = table_x + label_w + (d-1)*day_w
            x2 = table_x + label_w + d*day_w
            work_date = f"{year:04d}-{month:02d}-{d:02d}"
            row = by_date.get(work_date)

            value = ""
            if row:
                value = str(row.get(key) or "")

            # rút gọn cho ô nhỏ
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

            text_center(draw, (x1, y1, x2, y2), value, font_cell)

    # Tổng kết
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

    draw.text((margin, footer_y), summary, font=font_sub, fill=(20,20,20))

    draw.text(
        (margin, H - 65),
        f"Xuất từ hệ thống chấm công • {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        font=font_small,
        fill=(90,90,90),
    )

    output = io.BytesIO()
    img.save(output, format="PNG", dpi=(150,150))
    output.seek(0)
    return output.getvalue()


# =========================================================
# SESSION
# =========================================================
def logout():
    for key in [
        "logged_in",
        "username",
        "user",
    ]:
        st.session_state.pop(key, None)


# =========================================================
# LOGIN
# =========================================================
def login_page():
    st.markdown(
        '<div class="login-box">',
        unsafe_allow_html=True
    )
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
                check_in = st.time_input(
                    "Giờ vào",
                    value=(
                        datetime.strptime(current["check_in"], "%H:%M").time()
                        if current and current.get("check_in")
                        else datetime.now().time()
                    ),
                )

            with col2:
                default_out = (
                    datetime.strptime(current["check_out"], "%H:%M").time()
                    if current and current.get("check_out")
                    else datetime.now().time()
                )
                check_out = st.time_input("Giờ ra", value=default_out)

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
                "💾 Lưu chấm công",
                use_container_width=True,
            )

            if save:
                upsert_attendance(
                    user["username"],
                    today_str,
                    check_in.strftime("%H:%M"),
                    check_out.strftime("%H:%M"),
                    status,
                    note,
                )
                st.success("Đã lưu chấm công hôm nay.")
                st.rerun()

    with tab2:
        year = st.number_input(
            "Năm",
            min_value=2020,
            max_value=2100,
            value=today.year,
            step=1,
        )
        month = st.selectbox(
            "Tháng",
            list(range(1, 13)),
            index=today.month - 1,
        )

        df = get_month_attendance(user["username"], int(year), int(month))

        days = calendar.monthrange(int(year), int(month))[1]
        rows = []

        for d in range(1, days + 1):
            work_date = date(int(year), int(month), d)
            found = df[df["work_date"] == work_date.isoformat()]

            if len(found):
                r = found.iloc[0]
                rows.append({
                    "Ngày": work_date.strftime("%d/%m/%Y"),
                    "Thứ": ["T2","T3","T4","T5","T6","T7","CN"][work_date.weekday()],
                    "Vào": r["check_in"],
                    "Ra": r["check_out"],
                    "Trạng thái": r["status"],
                    "Ghi chú": r["note"],
                })
            else:
                rows.append({
                    "Ngày": work_date.strftime("%d/%m/%Y"),
                    "Thứ": ["T2","T3","T4","T5","T6","T7","CN"][work_date.weekday()],
                    "Vào": "",
                    "Ra": "",
                    "Trạng thái": "",
                    "Ghi chú": "",
                })

        month_df = pd.DataFrame(rows)
        st.dataframe(month_df, use_container_width=True, hide_index=True)

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

        if st.button("🖼️ Tạo bảng công A4", use_container_width=True):
            png = create_month_sheet(
                user["username"],
                int(year),
                int(month),
            )
            st.session_state["export_png"] = png
            st.session_state["export_name"] = (
                f"Bang_cong_{user['username']}_{int(month):02d}_{int(year)}.png"
            )

        if st.session_state.get("export_png"):
            st.image(st.session_state["export_png"], use_container_width=True)
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
        '<div class="sub-title">Quản lý nhân viên và bảng chấm công</div>',
        unsafe_allow_html=True,
    )

    users_df = query_df("""
        SELECT id, username, full_name, role, department,
               position, active, created_at
        FROM users
        ORDER BY
            CASE WHEN role='admin' THEN 0 ELSE 1 END,
            full_name
    """)

    attendance_df = query_df("""
        SELECT COUNT(*) AS total
        FROM attendance
    """)

    total_users = len(users_df)
    active_users = int(users_df["active"].sum()) if not users_df.empty else 0
    total_records = int(attendance_df.iloc[0]["total"])

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
            display["active"] = display["active"].map(
                {1: "Đang hoạt động", 0: "Đã khóa"}
            )
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
                    password = st.text_input("Mật khẩu *", type="password")
                with c2:
                    role = st.selectbox("Vai trò", ["employee", "admin"])
                    department = st.text_input("Bộ phận")
                    position = st.text_input("Chức vụ")

                create = st.form_submit_button(
                    "Tạo tài khoản",
                    use_container_width=True,
                )

                if create:
                    if not username.strip() or not full_name.strip() or not password:
                        st.error("Vui lòng nhập đủ tên đăng nhập, họ tên và mật khẩu.")
                    else:
                        ok, msg = create_user(
                            username, password, full_name,
                            role, department, position
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

        with st.expander("✏️ Chỉnh sửa tài khoản"):
            if users_df.empty:
                st.info("Chưa có tài khoản.")
            else:
                usernames = users_df["username"].tolist()
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
                                value=selected["department"] or "",
                            )
                            position = st.text_input(
                                "Chức vụ",
                                value=selected["position"] or "",
                            )

                        with c2:
                            role_options = ["employee", "admin"]
                            role = st.selectbox(
                                "Vai trò",
                                role_options,
                                index=(
                                    role_options.index(selected["role"])
                                    if selected["role"] in role_options else 0
                                ),
                            )
                            active = st.checkbox(
                                "Tài khoản đang hoạt động",
                                value=bool(selected["active"]),
                            )
                            new_password = st.text_input(
                                "Mật khẩu mới (để trống nếu không đổi)",
                                type="password",
                            )

                        save = st.form_submit_button(
                            "💾 Lưu thay đổi",
                            use_container_width=True,
                        )

                        if save:
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
    # ADMIN ATTENDANCE EDIT
    # -----------------------------------------------------
    with tab2:
        st.subheader("Nhập / sửa chấm công")

        employee_df = query_df("""
            SELECT username, full_name
            FROM users
            WHERE role='employee' AND active=1
            ORDER BY full_name
        """)

        if employee_df.empty:
            st.info("Chưa có nhân viên.")
        else:
            employee_options = {
                f"{r['full_name']} ({r['username']})": r["username"]
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
                work_date.isoformat(),
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
                            if existing and existing.get("status") in status_options
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
                    upsert_attendance(
                        selected_username,
                        work_date.isoformat(),
                        check_in.strip(),
                        check_out.strip(),
                        status,
                        note.strip(),
                    )
                    st.success("Đã lưu.")
                    st.rerun()

                if remove:
                    delete_attendance(
                        selected_username,
                        work_date.isoformat(),
                    )
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

        emp = st.selectbox(
            "Nhân viên",
            ["Tất cả"] + list(
                users_df.loc[users_df["role"] == "employee", "username"]
            ),
            key="admin_table_emp",
        )

        username_filter = None if emp == "Tất cả" else emp
        df = get_all_month_attendance(
            int(year), int(month), username_filter
        )

        if df.empty:
            st.info("Chưa có dữ liệu chấm công trong tháng này.")
        else:
            st.dataframe(
                df.rename(columns={
                    "username": "Tài khoản",
                    "full_name": "Họ tên",
                    "department": "Bộ phận",
                    "position": "Chức vụ",
                    "work_date": "Ngày",
                    "check_in": "Giờ vào",
                    "check_out": "Giờ ra",
                    "status": "Trạng thái",
                    "note": "Ghi chú",
                }),
                use_container_width=True,
                hide_index=True,
            )

            excel_data = make_excel(df)
            st.download_button(
                "⬇️ Xuất Excel",
                data=excel_data,
                file_name=f"Bang_cong_{int(month):02d}_{int(year)}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
                f"{r['full_name']} ({r['username']})": r["username"]
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
                png = create_month_sheet(
                    selected_username,
                    int(year),
                    int(month),
                )
                st.session_state["admin_export_png"] = png
                st.session_state["admin_export_name"] = (
                    f"Bang_cong_{selected_username}_{int(month):02d}_{int(year)}.png"
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
init_db()

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
