import streamlit as st
import sqlite3
import hashlib
import secrets
import hmac
import calendar
import csv
import io
from datetime import date, datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ============================================================
# CỘT SỐNG MUU SINH — CHẤM CÔNG
# Streamlit + SQLite + Multi-user + Audit log
# ============================================================

st.set_page_config(
    page_title="CỘT SỐNG MUU SINH",
    page_icon="🕐",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DB_FILE = Path("cham_cong.db")

# ============================================================
# GIAO DIỆN
# ============================================================

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

html, body, [class*="css"] {
    font-family: Inter, sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at 0% 0%, rgba(124, 92, 255, .14), transparent 28%),
        radial-gradient(circle at 100% 0%, rgba(0, 200, 255, .10), transparent 25%),
        #f6f7fb;
}

.block-container {
    max-width: 1450px;
    padding: 1.4rem 2rem 3rem;
}

.hero {
    padding: 28px 30px;
    border-radius: 28px;
    color: #fff;
    background: linear-gradient(135deg, #141529, #31285e 55%, #14576b);
    box-shadow: 0 18px 45px rgba(25, 24, 55, .18);
    margin-bottom: 22px;
}

.hero-title {
    font-size: 34px;
    font-weight: 900;
    letter-spacing: -1px;
}

.hero-sub {
    margin-top: 5px;
    opacity: .76;
}

.stat-card {
    background: rgba(255,255,255,.90);
    border: 1px solid rgba(255,255,255,.95);
    border-radius: 21px;
    padding: 17px 19px;
    box-shadow: 0 10px 30px rgba(40,45,75,.07);
}

.stat-icon {
    font-size: 22px;
}

.stat-number {
    font-size: 27px;
    font-weight: 900;
    margin-top: 2px;
}

.stat-label {
    color: #777b89;
    font-size: 13px;
}

.calendar-head {
    text-align: center;
    font-weight: 800;
    color: #747785;
    padding: 7px 0;
}

.day-title {
    text-align: center;
    font-size: 18px;
    font-weight: 900;
    margin: 2px 0 6px;
}

.day-total {
    text-align: center;
    font-size: 13px;
    font-weight: 900;
    margin-top: 6px;
}

.day-empty {
    text-align: center;
    color: #aaa;
    font-size: 11px;
    margin-top: 6px;
}

.login-title {
    text-align: center;
    font-size: clamp(42px, 6vw, 78px);
    line-height: 1.05;
    font-weight: 900;
    letter-spacing: -2px;
    color: #15162a;
    margin: 28px 0 34px;
}

.section-title {
    font-size: 24px;
    font-weight: 900;
}

.footer {
    text-align: center;
    color: #999;
    font-size: 12px;
    margin-top: 30px;
}

div[data-testid="stButton"] button {
    border-radius: 12px !important;
    font-weight: 800 !important;
    transition: all .18s ease !important;
}

div[data-testid="stButton"] button:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 18px rgba(70,65,120,.14);
}
</style>
""",
    unsafe_allow_html=True,
)

# ============================================================
# DATABASE
# ============================================================

def get_conn():
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            morning REAL NOT NULL DEFAULT 5.5,
            afternoon REAL NOT NULL DEFAULT 5.5,
            evening REAL NOT NULL DEFAULT 5.5,
            salary REAL NOT NULL DEFAULT 25000
        );

        CREATE TABLE IF NOT EXISTS user_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'employee'
                CHECK(role IN ('employee','admin')),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            work_date TEXT NOT NULL,
            ca_sang INTEGER NOT NULL DEFAULT 0,
            ca_chieu INTEGER NOT NULL DEFAULT 0,
            ca_toi INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, work_date),
            FOREIGN KEY(user_id)
                REFERENCES user_accounts(id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT NOT NULL,
            work_date TEXT NOT NULL,
            action TEXT NOT NULL,
            old_value TEXT NOT NULL,
            new_value TEXT NOT NULL,
            changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES user_accounts(id)
                ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_attendance_user_date
            ON attendance(user_id, work_date);

        CREATE INDEX IF NOT EXISTS idx_audit_changed
            ON audit_log(changed_at DESC);
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO settings
        (id, morning, afternoon, evening, salary)
        VALUES (1, 5.5, 5.5, 5.5, 25000)
        """
    )

    conn.commit()
    conn.close()


init_db()

# ============================================================
# MẬT KHẨU
# ============================================================

def make_password(password, salt=None):
    salt = salt or secrets.token_hex(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        180000,
    ).hex()

    return salt, digest


def check_password(password, salt, password_hash):
    _, candidate = make_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_settings():
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM settings WHERE id=1"
    ).fetchone()
    conn.close()
    return dict(row)


def get_user(username):
    conn = get_conn()

    row = conn.execute(
        """
        SELECT *
        FROM user_accounts
        WHERE username=?
        AND active=1
        LIMIT 1
        """,
        (username,),
    ).fetchone()

    conn.close()

    return dict(row) if row else None


def get_all_users():
    conn = get_conn()

    rows = conn.execute(
        """
        SELECT id, username, full_name, role, active, created_at
        FROM user_accounts
        ORDER BY full_name COLLATE NOCASE
        """
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_month_attendance(user_id, year, month):
    first_day = f"{year}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    last_date = f"{year}-{month:02d}-{last_day}"

    conn = get_conn()

    rows = conn.execute(
        """
        SELECT *
        FROM attendance
        WHERE user_id=?
          AND work_date BETWEEN ? AND ?
        ORDER BY work_date
        """,
        (user_id, first_day, last_date),
    ).fetchall()

    conn.close()

    return {
        row["work_date"]: dict(row)
        for row in rows
    }


def get_day_shifts(record):
    if not record:
        return []

    shifts = []

    if record["ca_sang"]:
        shifts.append("Ca sáng")

    if record["ca_chieu"]:
        shifts.append("Ca chiều")

    if record["ca_toi"]:
        shifts.append("Ca tối")

    return shifts


def calculate_hours(shifts, settings):
    hour_map = {
        "Ca sáng": float(settings["morning"]),
        "Ca chiều": float(settings["afternoon"]),
        "Ca tối": float(settings["evening"]),
    }

    return sum(hour_map.get(shift, 0) for shift in shifts)


def shift_columns(shifts):
    return (
        1 if "Ca sáng" in shifts else 0,
        1 if "Ca chiều" in shifts else 0,
        1 if "Ca tối" in shifts else 0,
    )


def save_attendance(user, work_date, new_shifts):
    conn = get_conn()

    old = conn.execute(
        """
        SELECT *
        FROM attendance
        WHERE user_id=?
          AND work_date=?
        LIMIT 1
        """,
        (user["id"], work_date),
    ).fetchone()

    old_shifts = get_day_shifts(old)

    if old_shifts == new_shifts:
        conn.close()
        return

    sang, chieu, toi = shift_columns(new_shifts)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        if old:
            conn.execute(
                """
                UPDATE attendance
                SET ca_sang=?,
                    ca_chieu=?,
                    ca_toi=?,
                    updated_at=?
                WHERE user_id=?
                  AND work_date=?
                """,
                (
                    sang,
                    chieu,
                    toi,
                    now,
                    user["id"],
                    work_date,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO attendance
                (
                    user_id,
                    work_date,
                    ca_sang,
                    ca_chieu,
                    ca_toi,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    work_date,
                    sang,
                    chieu,
                    toi,
                    now,
                ),
            )

        conn.execute(
            """
            INSERT INTO audit_log
            (
                user_id,
                username,
                work_date,
                action,
                old_value,
                new_value,
                changed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                user["username"],
                work_date,
                "UPDATE_ATTENDANCE",
                ", ".join(old_shifts) if old_shifts else "Không chấm",
                ", ".join(new_shifts) if new_shifts else "Không chấm",
                now,
            ),
        )

        conn.commit()

    finally:
        conn.close()


def update_settings(morning, afternoon, evening, salary):
    conn = get_conn()

    conn.execute(
        """
        UPDATE settings
        SET morning=?,
            afternoon=?,
            evening=?,
            salary=?
        WHERE id=1
        """,
        (
            morning,
            afternoon,
            evening,
            salary,
        ),
    )

    conn.commit()
    conn.close()


# ============================================================
# ADMIN MẶC ĐỊNH
# ============================================================

def ensure_default_admin():
    conn = get_conn()

    row = conn.execute(
        """
        SELECT id
        FROM user_accounts
        WHERE username=?
        LIMIT 1
        """,
        ("Lâu",),
    ).fetchone()

    salt, password_hash = make_password("1")

    if row is None:
        conn.execute(
            """
            INSERT INTO user_accounts
            (
                username,
                full_name,
                password_hash,
                salt,
                role,
                active
            )
            VALUES (?, ?, ?, ?, 'admin', 1)
            """,
            (
                "Lâu",
                "Quản trị viên",
                password_hash,
                salt,
            ),
        )
    else:
        # Đảm bảo tài khoản Lâu luôn đăng nhập được bằng mật khẩu 1.
        conn.execute(
            """
            UPDATE user_accounts
            SET password_hash=?,
                salt=?,
                role='admin',
                active=1
            WHERE username=?
            """,
            (
                password_hash,
                salt,
                "Lâu",
            ),
        )

    conn.commit()
    conn.close()


ensure_default_admin()

# ============================================================
# LOGIN
# ============================================================

if "current_user" not in st.session_state:
    st.session_state.current_user = None


if st.session_state.current_user is None:

    st.markdown(
        '<div class="login-title">CỘT SỐNG MUU SINH</div>',
        unsafe_allow_html=True,
    )

    with st.container(border=True):

        st.subheader("🔐 Đăng nhập")

        username = st.text_input(
            "Tên đăng nhập",
            placeholder="Nhập tên đăng nhập",
        )

        password = st.text_input(
            "Mật khẩu",
            type="password",
            placeholder="Nhập mật khẩu",
        )

        if st.button(
            "🚀 Đăng nhập",
            type="primary",
            use_container_width=True,
        ):

            user = get_user(
                username.strip()
            )

            if (
                user
                and check_password(
                    password,
                    user["salt"],
                    user["password_hash"],
                )
            ):
                st.session_state.current_user = user
                st.rerun()

            else:
                st.error(
                    "Tên đăng nhập hoặc mật khẩu không đúng."
                )

    st.stop()


# ============================================================
# APP CHÍNH
# ============================================================

user = st.session_state.current_user
settings = get_settings()

if "year" not in st.session_state:
    now_date = date.today()
    st.session_state.year = now_date.year
    st.session_state.month = now_date.month

year = st.session_state.year
month = st.session_state.month

attendance = get_month_attendance(
    user["id"],
    year,
    month,
)

hour_map = {
    "Ca sáng": float(settings["morning"]),
    "Ca chiều": float(settings["afternoon"]),
    "Ca tối": float(settings["evening"]),
}

working_days = sum(
    1
    for row in attendance.values()
    if get_day_shifts(row)
)

total_shifts = sum(
    len(get_day_shifts(row))
    for row in attendance.values()
)

total_hours = sum(
    sum(
        hour_map[shift]
        for shift in get_day_shifts(row)
    )
    for row in attendance.values()
)

total_money = (
    total_hours
    * float(settings["salary"])
)

# ============================================================
# HEADER
# ============================================================

st.markdown(
    f'<div class="hero"><div class="hero-title">CỘT SỐNG MUU SINH</div><div class="hero-sub">Xin chào, {user["full_name"]} 👋 · Tháng {month:02d}/{year} · Chấm ca trực tiếp trên lịch</div></div>',
    unsafe_allow_html=True,
)

# ============================================================
# STATS
# ============================================================

c1, c2, c3, c4 = st.columns(4)

stats = [
    (c1, "📅", working_days, "Ngày làm"),
    (c2, "🎫", total_shifts, "Tổng ca"),
    (c3, "⏱️", f"{total_hours:g}", "Tổng giờ"),
    (c4, "💰", f"{total_money:,.0f} đ", "Tiền công"),
]

for col, icon, number, label in stats:
    with col:
        st.markdown(
            f'<div class="stat-card"><div class="stat-icon">{icon}</div><div class="stat-number">{number}</div><div class="stat-label">{label}</div></div>',
            unsafe_allow_html=True,
        )

st.write("")

# ============================================================
# THÁNG
# ============================================================

left, center, right = st.columns([1, 2, 1])

with left:

    if st.button(
        "← Tháng trước",
        use_container_width=True,
    ):

        if month == 1:
            st.session_state.year = year - 1
            st.session_state.month = 12
        else:
            st.session_state.month = month - 1

        st.rerun()


with center:

    st.markdown(
        f'<h2 style="text-align:center;margin:0">📅 {month:02d}/{year}</h2>',
        unsafe_allow_html=True,
    )


with right:

    if st.button(
        "Tháng sau →",
        use_container_width=True,
    ):

        if month == 12:
            st.session_state.year = year + 1
            st.session_state.month = 1
        else:
            st.session_state.month = month + 1

        st.rerun()


st.caption(
    "💡 Chấm trực tiếp trên lịch: "
    "**S = sáng · C = chiều · T = tối**. "
    "Bấm lại ca đã ✓ để bỏ chấm."
)

# ============================================================
# LỊCH
# ============================================================

weekdays = [
    "T2",
    "T3",
    "T4",
    "T5",
    "T6",
    "T7",
    "CN",
]

headers = st.columns(7)

for i, weekday in enumerate(weekdays):
    with headers[i]:
        st.markdown(
            f'<div class="calendar-head">{weekday}</div>',
            unsafe_allow_html=True,
        )


icons = {
    "Ca sáng": "🌅",
    "Ca chiều": "🌇",
    "Ca tối": "🌙",
}

short = {
    "Ca sáng": "S",
    "Ca chiều": "C",
    "Ca tối": "T",
}

order = [
    "Ca sáng",
    "Ca chiều",
    "Ca tối",
]


for week in calendar.monthcalendar(
    year,
    month,
):

    columns = st.columns(7)

    for index, day in enumerate(week):

        with columns[index]:

            if day == 0:
                # Giữ khoảng trống cho các ngày ngoài tháng.
                st.write("")
                continue

            # Mỗi ngày là một ô có viền riêng.
            with st.container(border=True):

                work_date = (
                    f"{year}-"
                    f"{month:02d}-"
                    f"{day:02d}"
                )

                record = attendance.get(
                    work_date
                )

                current = get_day_shifts(
                    record
                )

                is_today = (
                    date(
                        year,
                        month,
                        day,
                    )
                    == date.today()
                )

                st.markdown(
                    f'<div class="day-title">{day:02d}{" · HÔM NAY" if is_today else ""}</div>',
                    unsafe_allow_html=True,
                )

                for shift in order:

                    checked = shift in current

                    label = (
                        f"✓ {icons[shift]} {short[shift]}"
                        if checked
                        else f"+ {icons[shift]} {short[shift]}"
                    )

                    if st.button(
                        label,
                        key=f"{work_date}_{short[shift]}",
                        use_container_width=True,
                        type=(
                            "primary"
                            if checked
                            else "secondary"
                        ),
                    ):

                        new_shifts = list(
                            current
                        )

                        if shift in new_shifts:
                            new_shifts.remove(
                                shift
                            )
                        else:
                            new_shifts.append(
                                shift
                            )

                        new_shifts.sort(
                            key=order.index
                        )

                        save_attendance(
                            user,
                            work_date,
                            new_shifts,
                        )

                        st.rerun()

                daily_hours = sum(
                    hour_map[shift]
                    for shift in current
                )

                if daily_hours > 0:

                    st.markdown(
                        f'<div class="day-total">⏱️ {daily_hours:g} giờ</div>',
                        unsafe_allow_html=True,
                    )

                else:

                    st.markdown(
                        '<div class="day-empty">Chưa chấm</div>',
                        unsafe_allow_html=True,
                    )


# ============================================================
# XUẤT BẢNG CÔNG CÁ NHÂN
# ============================================================

st.divider()

st.subheader("📥 Xuất bảng công của tôi")

st.caption(
    f"Bảng công riêng của {user['username']} · "
    f"Tháng {month:02d}/{year}. "
    "Ảnh xuất ra là lịch trọn tháng trên 1 trang A4 ngang."
)

personal_rows = [[
    "Ngày",
    "Sáng",
    "Chiều",
    "Tối",
    "Số ca",
    "Tổng giờ",
    "Tiền công",
]]

for day in range(
    1,
    calendar.monthrange(year, month)[1] + 1
):
    work_date = f"{year}-{month:02d}-{day:02d}"

    shifts = get_day_shifts(
        attendance.get(work_date)
    )

    daily_hours = sum(
        hour_map[shift]
        for shift in shifts
    )

    personal_rows.append([
        f"{day:02d}/{month:02d}/{year}",
        "✓" if "Ca sáng" in shifts else "",
        "✓" if "Ca chiều" in shifts else "",
        "✓" if "Ca tối" in shifts else "",
        len(shifts),
        daily_hours,
        daily_hours * float(settings["salary"]),
    ])

c1, c2 = st.columns(2)

with c1:
    csv_buffer = io.StringIO()
    csv.writer(csv_buffer).writerows(personal_rows)

    st.download_button(
        "⬇️ Tải CSV",
        csv_buffer.getvalue().encode("utf-8-sig"),
        f"bang_cong_{user['username']}_{year}_{month:02d}.csv",
        "text/csv",
        use_container_width=True,
    )


def font(size, bold=False):
    candidates = []

    if bold:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ])
    else:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ])

    candidates.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ])

    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)

    return ImageFont.load_default()


def make_a4_calendar_png():
    # A4 landscape at roughly 300 dpi.
    W, H = 3508, 2480

    img = Image.new(
        "RGB",
        (W, H),
        "white"
    )

    draw = ImageDraw.Draw(img)

    title_font = font(92, True)
    subtitle_font = font(46, True)
    name_font = font(38, True)
    weekday_font = font(34, True)
    date_font = font(40, True)
    shift_font = font(29, True)
    normal_font = font(27, False)
    summary_font = font(34, True)
    footer_font = font(22, False)

    margin_x = 115
    top = 95

    # ---- Title ----
    title = "CỘT SỐNG MUU SINH"

    bbox = draw.textbbox(
        (0, 0),
        title,
        font=title_font
    )

    draw.text(
        (
            (W - (bbox[2] - bbox[0])) / 2,
            top,
        ),
        title,
        fill="#1b1c2e",
        font=title_font,
    )

    title_bottom = top + (bbox[3] - bbox[1])

    subtitle = (
        f"BẢNG CHẤM CÔNG CÁ NHÂN • "
        f"THÁNG {month:02d}/{year}"
    )

    bbox2 = draw.textbbox(
        (0, 0),
        subtitle,
        font=subtitle_font
    )

    draw.text(
        (
            (W - (bbox2[2] - bbox2[0])) / 2,
            title_bottom + 20,
        ),
        subtitle,
        fill="#3b3d4f",
        font=subtitle_font,
    )

    name = (
        f"Nhân viên: {user['username']} "
        f"• {user['full_name']}"
    )

    bbox3 = draw.textbbox(
        (0, 0),
        name,
        font=name_font
    )

    draw.text(
        (
            (W - (bbox3[2] - bbox3[0])) / 2,
            title_bottom + 82,
        ),
        name,
        fill="#616475",
        font=name_font,
    )

    # ---- Calendar ----
    cal_top = title_bottom + 155
    cal_left = margin_x
    cal_width = W - margin_x * 2

    last_day = calendar.monthrange(
        year,
        month
    )[1]

    weeks = calendar.monthcalendar(
        year,
        month
    )

    # All months fit in 6 rows.
    rows = len(weeks)
    weekday_h = 70
    cell_w = cal_width / 7
    cell_h = 250

    # Weekday headers
    weekdays = [
        "T2",
        "T3",
        "T4",
        "T5",
        "T6",
        "T7",
        "CN",
    ]

    for i, wd in enumerate(weekdays):
        x0 = cal_left + i * cell_w
        x1 = x0 + cell_w

        draw.rounded_rectangle(
            (
                int(x0 + 4),
                int(cal_top),
                int(x1 - 4),
                int(cal_top + weekday_h),
            ),
            radius=18,
            fill="#eceef4",
            outline="#d3d6df",
            width=2,
        )

        bb = draw.textbbox(
            (0, 0),
            wd,
            font=weekday_font,
        )

        draw.text(
            (
                (x0 + x1 - (bb[2] - bb[0])) / 2,
                cal_top + 18,
            ),
            wd,
            fill="#4d5060",
            font=weekday_font,
        )

    # Shift colors
    shift_fill = {
        "Ca sáng": "#FFF0B8",
        "Ca chiều": "#DDEBFF",
        "Ca tối": "#EADFFF",
    }

    shift_short = {
        "Ca sáng": "SÁNG",
        "Ca chiều": "CHIỀU",
        "Ca tối": "TỐI",
    }

    shift_order = [
        "Ca sáng",
        "Ca chiều",
        "Ca tối",
    ]

    for r, week in enumerate(weeks):

        for c, day in enumerate(week):

            x0 = cal_left + c * cell_w
            y0 = cal_top + weekday_h + r * cell_h
            x1 = x0 + cell_w
            y1 = y0 + cell_h

            draw.rounded_rectangle(
                (
                    int(x0 + 4),
                    int(y0 + 4),
                    int(x1 - 4),
                    int(y1 - 4),
                ),
                radius=18,
                fill="#fbfcfe",
                outline="#cfd2db",
                width=3,
            )

            if day == 0:
                continue

            work_date = (
                f"{year}-"
                f"{month:02d}-"
                f"{day:02d}"
            )

            shifts = get_day_shifts(
                attendance.get(work_date)
            )

            # Date
            draw.text(
                (
                    int(x0 + 18),
                    int(y0 + 18),
                ),
                f"{day:02d}",
                fill="#242638",
                font=date_font,
            )

            # Shift pills
            pill_y = y0 + 80

            for shift in shift_order:

                is_checked = shift in shifts

                text_label = (
                    f"✓ {shift_short[shift]}"
                    if is_checked
                    else f"– {shift_short[shift]}"
                )

                fill = (
                    shift_fill[shift]
                    if is_checked
                    else "#f1f2f5"
                )

                outline = (
                    "#aeb4c2"
                    if is_checked
                    else "#d9dbe2"
                )

                pill_h = 46

                draw.rounded_rectangle(
                    (
                        int(x0 + 17),
                        int(pill_y),
                        int(x1 - 17),
                        int(pill_y + pill_h),
                    ),
                    radius=16,
                    fill=fill,
                    outline=outline,
                    width=2,
                )

                bb = draw.textbbox(
                    (0, 0),
                    text_label,
                    font=shift_font,
                )

                draw.text(
                    (
                        (x0 + x1 - (bb[2] - bb[0])) / 2,
                        pill_y + 6,
                    ),
                    text_label,
                    fill="#303343",
                    font=shift_font,
                )

                pill_y += 55

            daily_hours = sum(
                hour_map[s]
                for s in shifts
            )

            if daily_hours > 0:

                hour_label = (
                    f"⏱ {daily_hours:g} giờ"
                )

                bb = draw.textbbox(
                    (0, 0),
                    hour_label,
                    font=normal_font,
                )

                draw.text(
                    (
                        (x0 + x1 - (bb[2] - bb[0])) / 2,
                        y1 - 45,
                    ),
                    hour_label,
                    fill="#333649",
                    font=normal_font,
                )

    # ---- Summary ----
    summary_y = cal_top + weekday_h + rows * cell_h + 48

    draw.rounded_rectangle(
        (
            margin_x,
            summary_y,
            W - margin_x,
            summary_y + 105,
        ),
        radius=22,
        fill="#f1f2f7",
        outline="#d3d6df",
        width=2,
    )

    summary_text = (
        f"Ngày làm: {working_days}    •    "
        f"Tổng ca: {total_shifts}    •    "
        f"Tổng giờ: {total_hours:g}    •    "
        f"Tiền công: {total_money:,.0f} VNĐ"
    )

    draw.text(
        (
            margin_x + 35,
            summary_y + 30,
        ),
        summary_text,
        fill="#2b2e3f",
        font=summary_font,
    )

    # ---- Footer ----
    footer = (
        f"Xuất từ tài khoản {user['username']} • "
        f"Dữ liệu tháng {month:02d}/{year}"
    )

    draw.text(
        (
            margin_x,
            summary_y + 135,
        ),
        footer,
        fill="#8a8d99",
        font=footer_font,
    )

    output = io.BytesIO()

    img.save(
        output,
        format="PNG",
        optimize=True,
    )

    output.seek(0)

    return output.getvalue()


with c2:

    st.download_button(
        "🖼️ Xuất HÌNH ẢNH A4",
        make_a4_calendar_png(),
        f"bang_cong_{user['username']}_{year}_{month:02d}_A4.png",
        "image/png",
        use_container_width=True,
    )


# ============================================================
# ADMIN
# ============================================================


if user["role"] == "admin":

    st.divider()

    st.markdown(
        '<div class="section-title">👨‍💼 Trung tâm quản trị</div>',
        unsafe_allow_html=True,
    )

    tabs = st.tabs([
        "👥 Nhân viên",
        "📊 Bảng công",
        "🛡️ Đối chứng",
        "⚙️ Cài đặt",
    ])


    # --------------------------------------------------------
    # NHÂN VIÊN
    # --------------------------------------------------------

    with tabs[0]:

        st.subheader(
            "Quản lý tài khoản"
        )

        users = get_all_users()

        for employee in users:

            c1, c2, c3, c4 = st.columns(
                [2.5, 2, 1.2, 1]
            )

            with c1:
                st.write(
                    f"**{employee['full_name']}**"
                )

            with c2:
                st.caption(
                    f"@{employee['username']}"
                )

            with c3:
                st.caption(
                    "👑 Admin"
                    if employee["role"] == "admin"
                    else "👤 Nhân viên"
                )

            with c4:
                st.caption(
                    "🟢 Hoạt động"
                    if employee["active"]
                    else "🔴 Đã khóa"
                )

        st.write("")

        with st.expander(
            "➕ Tạo tài khoản"
        ):

            new_username = st.text_input(
                "Tên đăng nhập",
                key="new_username",
            )

            new_fullname = st.text_input(
                "Họ và tên",
                key="new_fullname",
            )

            new_password = st.text_input(
                "Mật khẩu",
                type="password",
                key="new_password",
            )

            new_role = st.selectbox(
                "Vai trò",
                [
                    "employee",
                    "admin",
                ],
                key="new_role",
            )

            if st.button(
                "Tạo tài khoản",
                type="primary",
            ):

                if not (
                    new_username
                    and new_fullname
                    and new_password
                ):

                    st.error(
                        "Vui lòng điền đủ thông tin."
                    )

                elif len(
                    new_password
                ) < 1:

                    st.error(
                        "Mật khẩu không được để trống."
                    )

                elif get_user(
                    new_username.strip()
                ):

                    st.error(
                        "Tên đăng nhập đã tồn tại."
                    )

                else:

                    salt, password_hash = (
                        make_password(
                            new_password
                        )
                    )

                    conn = get_conn()

                    conn.execute(
                        """
                        INSERT INTO user_accounts
                        (
                            username,
                            full_name,
                            password_hash,
                            salt,
                            role,
                            active
                        )
                        VALUES (?, ?, ?, ?, ?, 1)
                        """,
                        (
                            new_username.strip(),
                            new_fullname.strip(),
                            password_hash,
                            salt,
                            new_role,
                        ),
                    )

                    conn.commit()
                    conn.close()

                    st.success(
                        "Đã tạo tài khoản."
                    )

                    st.rerun()


        with st.expander(
            "🔑 Đặt lại mật khẩu"
        ):

            active_users = [
                employee
                for employee in users
                if employee["active"]
            ]

            if active_users:

                selected = st.selectbox(
                    "Tài khoản",
                    active_users,
                    format_func=lambda x:
                        f"{x['full_name']} "
                        f"(@{x['username']})",
                )

                reset_password = st.text_input(
                    "Mật khẩu mới",
                    type="password",
                )

                if st.button(
                    "Đổi mật khẩu"
                ):

                    if not reset_password:

                        st.error(
                            "Mật khẩu không được để trống."
                        )

                    else:

                        salt, password_hash = (
                            make_password(
                                reset_password
                            )
                        )

                        conn = get_conn()

                        conn.execute(
                            """
                            UPDATE user_accounts
                            SET salt=?,
                                password_hash=?
                            WHERE id=?
                            """,
                            (
                                salt,
                                password_hash,
                                selected["id"],
                            ),
                        )

                        conn.commit()
                        conn.close()

                        st.success(
                            "Đã đổi mật khẩu."
                        )

                        st.rerun()


        with st.expander(
            "🔒 Khóa / mở tài khoản"
        ):

            manageable = [
                employee
                for employee in users
                if employee["id"] != user["id"]
            ]

            if manageable:

                selected = st.selectbox(
                    "Tài khoản",
                    manageable,
                    format_func=lambda x:
                        f"{x['full_name']} "
                        f"(@{x['username']})",
                    key="lock_user",
                )

                if selected["active"]:

                    if st.button(
                        "🔒 Khóa tài khoản"
                    ):

                        conn = get_conn()

                        conn.execute(
                            """
                            UPDATE user_accounts
                            SET active=0
                            WHERE id=?
                            """,
                            (selected["id"],),
                        )

                        conn.commit()
                        conn.close()

                        st.success(
                            "Đã khóa tài khoản."
                        )

                        st.rerun()

                else:

                    if st.button(
                        "🔓 Mở tài khoản"
                    ):

                        conn = get_conn()

                        conn.execute(
                            """
                            UPDATE user_accounts
                            SET active=1
                            WHERE id=?
                            """,
                            (selected["id"],),
                        )

                        conn.commit()
                        conn.close()

                        st.success(
                            "Đã mở tài khoản."
                        )

                        st.rerun()


    # --------------------------------------------------------
    # BẢNG CÔNG
    # --------------------------------------------------------

    with tabs[1]:

        st.subheader(
            f"📊 Bảng công tháng {month:02d}/{year}"
        )

        users = [
            employee
            for employee in get_all_users()
            if employee["active"]
        ]

        admin_rows = []

        for employee in users:

            employee_attendance = get_month_attendance(
                employee["id"],
                year,
                month,
            )

            employee_days = sum(
                1
                for row in employee_attendance.values()
                if get_day_shifts(row)
            )

            employee_shifts = sum(
                len(get_day_shifts(row))
                for row in employee_attendance.values()
            )

            employee_hours = sum(
                sum(
                    hour_map[shift]
                    for shift in get_day_shifts(row)
                )
                for row in employee_attendance.values()
            )

            employee_money = (
                employee_hours
                * float(settings["salary"])
            )

            admin_rows.append({
                "Tên đăng nhập": employee["username"],
                "Họ tên": employee["full_name"],
                "Ngày làm": employee_days,
                "Tổng ca": employee_shifts,
                "Tổng giờ": employee_hours,
                "Tiền công": employee_money,
            })

        # Dữ liệu được đưa vào dataframe dạng dict để không bị lệch cột.
        try:
            import pandas as pd

            admin_df = pd.DataFrame(admin_rows)

            st.dataframe(
                admin_df,
                column_config={
                    "Tên đăng nhập": st.column_config.TextColumn(
                        "Tên đăng nhập"
                    ),
                    "Họ tên": st.column_config.TextColumn(
                        "Họ tên"
                    ),
                    "Ngày làm": st.column_config.NumberColumn(
                        "Ngày làm",
                        format="%d"
                    ),
                    "Tổng ca": st.column_config.NumberColumn(
                        "Tổng ca",
                        format="%d"
                    ),
                    "Tổng giờ": st.column_config.NumberColumn(
                        "Tổng giờ",
                        format="%.1f"
                    ),
                    "Tiền công": st.column_config.NumberColumn(
                        "Tiền công",
                        format="%.0f đ"
                    ),
                },
                hide_index=True,
                use_container_width=True,
            )

        except ImportError:
            st.table(admin_rows)

        grand_days = sum(
            row["Ngày làm"]
            for row in admin_rows
        )

        grand_shifts = sum(
            row["Tổng ca"]
            for row in admin_rows
        )

        grand_hours = sum(
            row["Tổng giờ"]
            for row in admin_rows
        )

        grand_money = sum(
            row["Tiền công"]
            for row in admin_rows
        )

        st.write("")

        g1, g2, g3, g4 = st.columns(4)

        with g1:
            st.metric(
                "📅 Tổng ngày",
                grand_days
            )

        with g2:
            st.metric(
                "🎫 Tổng ca",
                grand_shifts
            )

        with g3:
            st.metric(
                "⏱️ Tổng giờ",
                f"{grand_hours:g}"
            )

        with g4:
            st.metric(
                "💰 Tổng tiền",
                f"{grand_money:,.0f} đ"
            )

        # Xuất CSV bảng công Admin.
        admin_csv = io.StringIO()

        writer = csv.writer(admin_csv)

        writer.writerow([
            "Tên đăng nhập",
            "Họ tên",
            "Ngày làm",
            "Tổng ca",
            "Tổng giờ",
            "Tiền công",
        ])

        for row in admin_rows:
            writer.writerow([
                row["Tên đăng nhập"],
                row["Họ tên"],
                row["Ngày làm"],
                row["Tổng ca"],
                row["Tổng giờ"],
                row["Tiền công"],
            ])

        st.download_button(
            "⬇️ Xuất bảng công toàn bộ nhân viên",
            admin_csv.getvalue().encode("utf-8-sig"),
            f"bang_cong_toan_bo_{year}_{month:02d}.csv",
            "text/csv",
            use_container_width=True,
        )


    # --------------------------------------------------------
    # AUDIT
    # --------------------------------------------------------

    with tabs[2]:

        st.subheader(
            "🛡️ Lịch sử đối chứng"
        )

        conn = get_conn()

        logs = conn.execute(
            """
            SELECT
                changed_at,
                username,
                work_date,
                action,
                old_value,
                new_value
            FROM audit_log
            ORDER BY id DESC
            LIMIT 500
            """
        ).fetchall()

        conn.close()

        if logs:

            audit_rows = []

            for log in logs:

                audit_rows.append([
                    log["changed_at"],
                    log["username"],
                    log["work_date"],
                    log["old_value"],
                    log["new_value"],
                ])

            st.dataframe(
                audit_rows,
                column_config={
                    0: "Thời gian",
                    1: "Tài khoản",
                    2: "Ngày",
                    3: "Trước",
                    4: "Sau",
                },
                hide_index=True,
                use_container_width=True,
            )

            output = io.StringIO()

            csv.writer(
                output
            ).writerows([
                [
                    "Thời gian",
                    "Tài khoản",
                    "Ngày",
                    "Trước",
                    "Sau",
                ]
            ] + audit_rows)

            st.download_button(
                "⬇️ Tải nhật ký đối chứng",
                output.getvalue().encode("utf-8-sig"),
                "audit_log.csv",
                "text/csv",
                use_container_width=True,
            )

        else:

            st.info(
                "Chưa có lịch sử chấm công."
            )


    # --------------------------------------------------------
    # SETTINGS
    # --------------------------------------------------------

    with tabs[3]:

        st.subheader(
            "⚙️ Cấu hình ca & lương"
        )

        c1, c2, c3 = st.columns(3)

        with c1:

            morning = st.number_input(
                "🌅 Ca sáng",
                min_value=0.0,
                max_value=24.0,
                value=float(
                    settings["morning"]
                ),
                step=0.5,
            )

        with c2:

            afternoon = st.number_input(
                "🌇 Ca chiều",
                min_value=0.0,
                max_value=24.0,
                value=float(
                    settings["afternoon"]
                ),
                step=0.5,
            )

        with c3:

            evening = st.number_input(
                "🌙 Ca tối",
                min_value=0.0,
                max_value=24.0,
                value=float(
                    settings["evening"]
                ),
                step=0.5,
            )

        salary = st.number_input(
            "💰 Lương mỗi giờ",
            min_value=0,
            max_value=10000000,
            value=int(
                settings["salary"]
            ),
            step=1000,
        )

        if st.button(
            "💾 Lưu cấu hình",
            type="primary",
            use_container_width=True,
        ):

            update_settings(
                morning,
                afternoon,
                evening,
                salary,
            )

            st.success(
                "Đã lưu cấu hình."
            )

            st.rerun()


# ============================================================
# FOOTER
# ============================================================

st.markdown(
    '<div class="footer">CỘT SỐNG MUU SINH • Multi-user • SQLite • Audit-ready</div>',
    unsafe_allow_html=True,
)
