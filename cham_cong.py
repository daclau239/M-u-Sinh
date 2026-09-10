import streamlit as st
import sqlite3
import hashlib
import secrets
import hmac
import calendar
import csv
import io
import textwrap
from datetime import date, datetime
from pathlib import Path

# ============================================================
# WORKTIME — CHẤM CÔNG NHIỀU NGƯỜI
# SQLite • Streamlit • Modern UI • Audit log
# ============================================================

st.set_page_config(
    page_title="CỘT SỐNG MUU SINH",
    page_icon="🕐",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DB_FILE = Path("cham_cong.db")

# ============================================================
# MODERN UI
# ============================================================

st.markdown(textwrap.dedent("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: Inter, sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at 0% 0%, rgba(124,92,255,.13), transparent 26%),
        radial-gradient(circle at 100% 0%, rgba(0,196,255,.10), transparent 25%),
        #f6f7fb;
}

.block-container {
    max-width: 1450px;
    padding: 1.4rem 2rem 3rem;
}

.hero {
    padding: 26px 30px;
    border-radius: 28px;
    color: white;
    background: linear-gradient(135deg,#15162a,#30265e 55%,#14546b);
    box-shadow: 0 18px 45px rgba(25,24,55,.18);
    margin-bottom: 22px;
}

.hero-title {
    font-size: 35px;
    font-weight: 800;
    letter-spacing: -1px;
}

.hero-sub {
    opacity: .75;
    margin-top: 5px;
}

.stat-card {
    background: rgba(255,255,255,.88);
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
    font-weight: 800;
    margin-top: 3px;
}

.stat-label {
    color: #777b89;
    font-size: 13px;
}

.day-title {
    font-size: 18px;
    font-weight: 800;
    margin-bottom: 4px;
}

.day-total {
    text-align: center;
    font-weight: 800;
    font-size: 13px;
    margin-top: 4px;
}

.day-empty {
    text-align: center;
    color: #a4a4ad;
    font-size: 11px;
}

.week-title {
    text-align: center;
    font-weight: 800;
    color: #777;
    padding: 6px;
}

.login-box {
    max-width: 470px;
    margin: 7vh auto;
}

.login-title {
    text-align: center;
    font-size: 43px;
    font-weight: 800;
}

.login-sub {
    text-align: center;
    color: #777;
    margin-bottom: 25px;
}

.admin-title {
    font-size: 25px;
    font-weight: 800;
}

div[data-testid="stButton"] button {
    border-radius: 12px !important;
    font-weight: 700 !important;
    transition: all .18s ease !important;
}

div[data-testid="stButton"] button:hover {
    transform: translateY(-2px);
    box-shadow: 0 7px 18px rgba(70,65,120,.13);
}
</style>
"""), unsafe_allow_html=True)


# ============================================================
# DATABASE
# ============================================================

def get_conn():
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()

    conn.executescript("""
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
    """)

    conn.execute("""
        INSERT OR IGNORE INTO settings
        (id, morning, afternoon, evening, salary)
        VALUES (1, 5.5, 5.5, 5.5, 25000)
    """)

    conn.commit()
    conn.close()


init_db()


# ============================================================
# PASSWORD
# ============================================================

def make_password(password, salt=None):
    salt = salt or secrets.token_hex(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        180000
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

    row = conn.execute("""
        SELECT *
        FROM user_accounts
        WHERE username=?
        AND active=1
    """, (username,)).fetchone()

    conn.close()

    return dict(row) if row else None


def get_all_users():
    conn = get_conn()

    rows = conn.execute("""
        SELECT id, username, full_name,
               role, active, created_at
        FROM user_accounts
        ORDER BY full_name COLLATE NOCASE
    """).fetchall()

    conn.close()

    return [dict(x) for x in rows]


def attendance_for_month(user_id, year, month):
    first = f"{year}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    last = f"{year}-{month:02d}-{last_day}"

    conn = get_conn()

    rows = conn.execute("""
        SELECT *
        FROM attendance
        WHERE user_id=?
        AND work_date BETWEEN ? AND ?
        ORDER BY work_date
    """, (user_id, first, last)).fetchall()

    conn.close()

    return {
        row["work_date"]: dict(row)
        for row in rows
    }


def get_day_shifts(record):
    if not record:
        return []

    result = []

    if record["ca_sang"]:
        result.append("Ca sáng")

    if record["ca_chieu"]:
        result.append("Ca chiều")

    if record["ca_toi"]:
        result.append("Ca tối")

    return result


def shift_columns(shifts):
    return (
        1 if "Ca sáng" in shifts else 0,
        1 if "Ca chiều" in shifts else 0,
        1 if "Ca tối" in shifts else 0
    )


def save_attendance(user, work_date, new_shifts):
    conn = get_conn()

    old = conn.execute("""
        SELECT *
        FROM attendance
        WHERE user_id=?
        AND work_date=?
    """, (user["id"], work_date)).fetchone()

    old_shifts = get_day_shifts(old)

    if old_shifts == new_shifts:
        conn.close()
        return

    sang, chieu, toi = shift_columns(new_shifts)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        if old:
            conn.execute("""
                UPDATE attendance
                SET ca_sang=?,
                    ca_chieu=?,
                    ca_toi=?,
                    updated_at=?
                WHERE user_id=?
                AND work_date=?
            """, (
                sang, chieu, toi,
                now,
                user["id"],
                work_date
            ))
        else:
            conn.execute("""
                INSERT INTO attendance
                (user_id, work_date,
                 ca_sang, ca_chieu, ca_toi,
                 updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                user["id"],
                work_date,
                sang,
                chieu,
                toi,
                now
            ))

        conn.execute("""
            INSERT INTO audit_log
            (user_id, username, work_date,
             action, old_value, new_value, changed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user["id"],
            user["username"],
            work_date,
            "UPDATE_ATTENDANCE",
            ", ".join(old_shifts) if old_shifts else "Không chấm",
            ", ".join(new_shifts) if new_shifts else "Không chấm",
            now
        ))

        conn.commit()

    finally:
        conn.close()


def update_settings(morning, afternoon, evening, salary):
    conn = get_conn()

    conn.execute("""
        UPDATE settings
        SET morning=?,
            afternoon=?,
            evening=?,
            salary=?
        WHERE id=1
    """, (
        morning,
        afternoon,
        evening,
        salary
    ))

    conn.commit()
    conn.close()


# ============================================================
# LOGIN
# ============================================================

if "current_user" not in st.session_state:
    st.session_state.current_user = None


# Tạo admin mặc định lần đầu
def ensure_default_admin():
    conn = get_conn()

    count = conn.execute(
        "SELECT COUNT(*) FROM user_accounts"
    ).fetchone()[0]

    if count == 0:
        salt, password_hash = make_password("1")

        conn.execute("""
            INSERT INTO user_accounts
            (username, full_name,
             password_hash, salt,
             role, active)
            VALUES (?, ?, ?, ?, 'admin', 1)
        """, (
            "Lâu",
            "Quản trị viên",
            password_hash,
            salt
        ))

        conn.commit()

    conn.close()


ensure_default_admin()


if st.session_state.current_user is None:

    st.markdown(textwrap.dedent("""
    <div class="login-box" style="max-width: 900px; margin-top: 5vh;">

        <div style="
            text-align:center;
            font-size: clamp(42px, 6vw, 78px);
            line-height: 1.05;
            font-weight: 900;
            letter-spacing: -2px;
            margin-bottom: 32px;
            color: #15162a;
        ">
            CỘT SỐNG MUU SINH
        </div>

    </div>
    """), unsafe_allow_html=True)

    with st.container(border=True):

        st.subheader("🔐 Đăng nhập")

        username = st.text_input(
            "Tên đăng nhập",
            placeholder="Nhập tài khoản"
        )

        password = st.text_input(
            "Mật khẩu",
            type="password",
            placeholder="Nhập mật khẩu"
        )

        if st.button(
            "🚀 Đăng nhập",
            type="primary",
            use_container_width=True
        ):

            user = get_user(
                username.strip()
            )

            if (
                user
                and check_password(
                    password,
                    user["salt"],
                    user["password_hash"]
                )
            ):

                st.session_state.current_user = user
                st.rerun()

            else:

                st.error(
                    "Sai tài khoản hoặc mật khẩu."
                )

    st.caption(
        "Tài khoản quản trị lần đầu: **Lâu / 1**"
    )

    st.stop()


# ============================================================
# CURRENT USER
# ============================================================

user = st.session_state.current_user
settings = get_settings()


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown("## 👤 Tài khoản")

    st.write(
        f"**{user['full_name']}**"
    )

    st.caption(
        f"@{user['username']} · "
        f"{'Quản trị viên' if user['role']=='admin' else 'Nhân viên'}"
    )

    st.divider()

    if st.button(
        "🚪 Đăng xuất",
        use_container_width=True
    ):

        st.session_state.current_user = None
        st.rerun()


# ============================================================
# MONTH
# ============================================================

if "year" not in st.session_state:

    today = date.today()

    st.session_state.year = today.year
    st.session_state.month = today.month


year = st.session_state.year
month = st.session_state.month


# ============================================================
# HEADER
# ============================================================

st.markdown(textwrap.dedent(f"""
    <div class="hero">

        <div class="hero-title">
            Xin chào, {user['full_name']} 👋
        </div>

        <div class="hero-sub">
            Tháng {month:02d}/{year}
            · Chấm ca trực tiếp ngay trên lịch
        </div>

    </div>
    """), unsafe_allow_html=True)


# ============================================================
# PERSONAL ATTENDANCE
# ============================================================

attendance = attendance_for_month(
    user["id"],
    year,
    month
)


working_days = sum(
    bool(get_day_shifts(row))
    for row in attendance.values()
)


total_shifts = sum(
    len(get_day_shifts(row))
    for row in attendance.values()
)


# Tính giờ theo cấu hình ca
hour_map = {
    "Ca sáng": float(settings["morning"]),
    "Ca chiều": float(settings["afternoon"]),
    "Ca tối": float(settings["evening"])
}

total_hours = sum(
    sum(
        hour_map[s]
        for s in get_day_shifts(row)
    )
    for row in attendance.values()
)

total_money = (
    total_hours
    * float(settings["salary"])
)


# ============================================================
# STATS
# ============================================================

c1, c2, c3, c4 = st.columns(4)

for col, icon, number, label in [

    (
        c1,
        "📅",
        working_days,
        "Ngày làm"
    ),

    (
        c2,
        "🎫",
        total_shifts,
        "Tổng ca"
    ),

    (
        c3,
        "⏱️",
        f"{total_hours:g}",
        "Tổng giờ"
    ),

    (
        c4,
        "💰",
        f"{total_money:,.0f} đ",
        "Tiền công"
    )

]:

    with col:

        st.markdown(textwrap.dedent(f"""
            <div class="stat-card">

                <div class="stat-icon">
                    {icon}
                </div>

                <div class="stat-number">
                    {number}
                </div>

                <div class="stat-label">
                    {label}
                </div>

            </div>
            """), unsafe_allow_html=True)


st.write("")


# ============================================================
# MONTH NAVIGATION
# ============================================================

left, center, right = st.columns(
    [1, 2, 1]
)

with left:

    if st.button(
        "← Tháng trước",
        use_container_width=True
    ):

        if month == 1:

            st.session_state.year = (
                year - 1
            )

            st.session_state.month = 12

        else:

            st.session_state.month = (
                month - 1
            )

        st.rerun()


with center:

    st.markdown(textwrap.dedent(f"""
        <h2 style="
            text-align:center;
            margin:0;
        ">
            📅 {month:02d}/{year}
        </h2>
        """), unsafe_allow_html=True)


with right:

    if st.button(
        "Tháng sau →",
        use_container_width=True
    ):

        if month == 12:

            st.session_state.year = (
                year + 1
            )

            st.session_state.month = 1

        else:

            st.session_state.month = (
                month + 1
            )

        st.rerun()


st.caption(
    "💡 Bấm trực tiếp **S / C / T** trong từng ngày. "
    "Nút ✓ = đã chấm. Bấm lại = bỏ chấm."
)


# ============================================================
# CALENDAR
# ============================================================

weekdays = [
    "T2",
    "T3",
    "T4",
    "T5",
    "T6",
    "T7",
    "CN"
]

headers = st.columns(7)

for i, weekday in enumerate(weekdays):

    with headers[i]:

        st.markdown(textwrap.dedent(f"""
            <div class="week-title">
                {weekday}
            </div>
            """), unsafe_allow_html=True)


icons = {
    "Ca sáng": "🌅",
    "Ca chiều": "🌇",
    "Ca tối": "🌙"
}

short = {
    "Ca sáng": "S",
    "Ca chiều": "C",
    "Ca tối": "T"
}

order = [
    "Ca sáng",
    "Ca chiều",
    "Ca tối"
]


for week in calendar.monthcalendar(
    year,
    month
):

    columns = st.columns(7)

    for i, day in enumerate(week):

        with columns[i]:

            if day == 0:

                st.write("")
                continue


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
                    day
                )
                == date.today()
            )


            st.markdown(textwrap.dedent(f"""
                <div class="day-title">
                    {day:02d}
                    {" • HÔM NAY" if is_today else ""}
                </div>
                """), unsafe_allow_html=True)


            # =============================================
            # CHẤM CA NGAY TRÊN LỊCH
            # =============================================

            for shift in order:

                checked = (
                    shift in current
                )


                label = (

                    f"✓ {icons[shift]} {short[shift]}"

                    if checked

                    else

                    f"+ {icons[shift]} {short[shift]}"

                )


                if st.button(

                    label,

                    key=(
                        f"{work_date}_"
                        f"{short[shift]}"
                    ),

                    use_container_width=True,

                    type=(
                        "primary"
                        if checked
                        else "secondary"
                    )

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
                        new_shifts
                    )


                    st.rerun()


            daily_hours = sum(
                hour_map[s]
                for s in current
            )


            if daily_hours:

                st.markdown(textwrap.dedent(f"""
                    <div class="day-total">
                        ⏱️ {daily_hours:g} giờ
                    </div>
                    """), unsafe_allow_html=True)

            else:

                st.markdown(textwrap.dedent("""
                    <div class="day-empty">
                        Chưa chấm
                    </div>
                    """), unsafe_allow_html=True)


# ============================================================
# EXPORT PERSONAL
# ============================================================

st.divider()

st.subheader(
    "📥 Xuất bảng công cá nhân"
)


rows = [[
    "Ngày",
    "Ca sáng",
    "Ca chiều",
    "Ca tối",
    "Tổng giờ",
    "Tiền công"
]]


for day in range(
    1,
    calendar.monthrange(
        year,
        month
    )[1] + 1
):

    work_date = (
        f"{year}-"
        f"{month:02d}-"
        f"{day:02d}"
    )


    current = get_day_shifts(
        attendance.get(work_date)
    )


    daily_hours = sum(
        hour_map[s]
        for s in current
    )


    rows.append([
        work_date,
        "Có" if "Ca sáng" in current else "",
        "Có" if "Ca chiều" in current else "",
        "Có" if "Ca tối" in current else "",
        daily_hours,
        daily_hours * float(settings["salary"])
    ])


csv_buffer = io.StringIO()

csv.writer(
    csv_buffer
).writerows(rows)


st.download_button(
    "⬇️ Tải CSV",
    csv_buffer.getvalue().encode("utf-8-sig"),
    f"cham_cong_{year}_{month:02d}.csv",
    "text/csv",
    use_container_width=True
)


# ============================================================
# ADMIN
# ============================================================

if user["role"] == "admin":

    st.divider()

    st.markdown(
        '<div class="admin-title">👨‍💼 Trung tâm quản trị</div>',
        unsafe_allow_html=True
    )

    tabs = st.tabs([
        "👥 Nhân viên",
        "📊 Bảng công",
        "🛡️ Đối chứng",
        "⚙️ Cài đặt"
    ])


    # ========================================================
    # EMPLOYEES
    # ========================================================

    with tabs[0]:

        st.subheader(
            "Quản lý nhân viên"
        )


        users = get_all_users()


        for employee in users:

            c1, c2, c3, c4 = st.columns(
                [2.5, 2, 1, 1]
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
                    else "🔴 Khóa"
                )


        st.write("")


        # ----------------------------------------------------
        # CREATE
        # ----------------------------------------------------

        with st.expander(
            "➕ Tạo tài khoản mới"
        ):

            nu = st.text_input(
                "Tên đăng nhập",
                key="new_username"
            )

            nn = st.text_input(
                "Họ và tên",
                key="new_fullname"
            )

            np = st.text_input(
                "Mật khẩu",
                type="password",
                key="new_password"
            )

            nr = st.selectbox(
                "Vai trò",
                [
                    "employee",
                    "admin"
                ],
                key="new_role"
            )


            if st.button(
                "Tạo tài khoản",
                type="primary"
            ):

                if not (
                    nu
                    and nn
                    and np
                ):

                    st.error(
                        "Vui lòng điền đủ thông tin."
                    )

                elif len(np) < 6:

                    st.error(
                        "Mật khẩu phải có ít nhất 6 ký tự."
                    )

                elif get_user(
                    nu.strip()
                ):

                    st.error(
                        "Tên đăng nhập đã tồn tại."
                    )

                else:

                    salt, password_hash = (
                        make_password(np)
                    )


                    conn = get_conn()

                    conn.execute("""
                        INSERT INTO user_accounts
                        (username,
                         full_name,
                         password_hash,
                         salt,
                         role,
                         active)
                        VALUES (?, ?, ?, ?, ?, 1)
                    """, (
                        nu.strip(),
                        nn.strip(),
                        password_hash,
                        salt,
                        nr
                    ))

                    conn.commit()
                    conn.close()

                    st.success(
                        "Đã tạo tài khoản."
                    )

                    st.rerun()


        # ----------------------------------------------------
        # RESET PASSWORD
        # ----------------------------------------------------

        with st.expander(
            "🔑 Đặt lại mật khẩu"
        ):

            employees = [
                x
                for x in users
                if x["active"]
            ]


            if employees:

                selected = st.selectbox(
                    "Tài khoản",
                    employees,
                    format_func=lambda x:
                        f"{x['full_name']} "
                        f"(@{x['username']})"
                )


                new_pw = st.text_input(
                    "Mật khẩu mới",
                    type="password"
                )


                if st.button(
                    "Đổi mật khẩu"
                ):

                    if len(new_pw) < 6:

                        st.error(
                            "Mật khẩu tối thiểu 6 ký tự."
                        )

                    else:

                        salt, password_hash = (
                            make_password(new_pw)
                        )


                        conn = get_conn()

                        conn.execute("""
                            UPDATE user_accounts
                            SET salt=?,
                                password_hash=?
                            WHERE id=?
                        """, (
                            salt,
                            password_hash,
                            selected["id"]
                        ))

                        conn.commit()
                        conn.close()

                        st.success(
                            "Đã đổi mật khẩu."
                        )


        # ----------------------------------------------------
        # LOCK / UNLOCK
        # ----------------------------------------------------

        with st.expander(
            "🔒 Khóa / mở tài khoản"
        ):

            manageable = [
                x
                for x in users
                if x["id"] != user["id"]
            ]


            if manageable:

                selected = st.selectbox(
                    "Tài khoản",
                    manageable,
                    format_func=lambda x:
                        f"{x['full_name']} "
                        f"(@{x['username']})",
                    key="lock_user"
                )


                if selected["active"]:

                    if st.button(
                        "🔒 Khóa tài khoản"
                    ):

                        conn = get_conn()

                        conn.execute("""
                            UPDATE user_accounts
                            SET active=0
                            WHERE id=?
                        """, (
                            selected["id"],
                        ))

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

                        conn.execute("""
                            UPDATE user_accounts
                            SET active=1
                            WHERE id=?
                        """, (
                            selected["id"],
                        ))

                        conn.commit()
                        conn.close()

                        st.success(
                            "Đã mở tài khoản."
                        )

                        st.rerun()


    # ========================================================
    # ALL STAFF ATTENDANCE
    # ========================================================

    with tabs[1]:

        st.subheader(
            f"📊 Bảng công {month:02d}/{year}"
        )


        users = [
            x
            for x in get_all_users()
            if x["active"]
        ]


        table = [[
            "Nhân viên",
            "Ngày làm",
            "Tổng ca",
            "Tổng giờ",
            "Tiền công"
        ]]


        for employee in users:

            aa = attendance_for_month(
                employee["id"],
                year,
                month
            )


            employee_days = sum(
                bool(get_day_shifts(x))
                for x in aa.values()
            )


            employee_shifts = sum(
                len(get_day_shifts(x))
                for x in aa.values()
            )


            employee_hours = sum(
                sum(
                    hour_map[s]
                    for s in get_day_shifts(x)
                )
                for x in aa.values()
            )


            employee_money = (
                employee_hours
                * float(settings["salary"])
            )


            table.append([
                employee["full_name"],
                employee_days,
                employee_shifts,
                employee_hours,
                employee_money
            ])


        st.dataframe(
            table[1:],
            column_config={
                0: "Nhân viên",
                1: "Ngày làm",
                2: "Tổng ca",
                3: st.column_config.NumberColumn(
                    "Tổng giờ",
                    format="%.1f"
                ),
                4: st.column_config.NumberColumn(
                    "Tiền công",
                    format="%.0f đ"
                )
            },
            hide_index=True,
            use_container_width=True
        )


        output = io.StringIO()

        csv.writer(
            output
        ).writerows(table)


        st.download_button(
            "⬇️ Xuất bảng công",
            output.getvalue().encode("utf-8-sig"),
            f"bang_cong_{year}_{month:02d}.csv",
            "text/csv",
            use_container_width=True
        )


    # ========================================================
    # AUDIT
    # ========================================================

    with tabs[2]:

        st.subheader(
            "🛡️ Lịch sử đối chứng"
        )


        conn = get_conn()

        logs = conn.execute("""
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
        """).fetchall()

        conn.close()


        if logs:

            audit_table = []

            for log in logs:

                audit_table.append([
                    log["changed_at"],
                    log["username"],
                    log["work_date"],
                    log["old_value"],
                    log["new_value"]
                ])


            st.dataframe(
                audit_table,
                column_config={
                    0: "Thời gian",
                    1: "Tài khoản",
                    2: "Ngày",
                    3: "Trước",
                    4: "Sau"
                },
                hide_index=True,
                use_container_width=True
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
                    "Sau"
                ]
            ] + audit_table)


            st.download_button(
                "⬇️ Tải nhật ký đối chứng",
                output.getvalue().encode("utf-8-sig"),
                "audit_log.csv",
                "text/csv",
                use_container_width=True
            )

        else:

            st.info(
                "Chưa có lịch sử chấm công."
            )


    # ========================================================
    # SETTINGS
    # ========================================================

    with tabs[3]:

        st.subheader(
            "⚙️ Cấu hình hệ thống"
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
                step=0.5
            )


        with c2:

            afternoon = st.number_input(
                "🌇 Ca chiều",
                min_value=0.0,
                max_value=24.0,
                value=float(
                    settings["afternoon"]
                ),
                step=0.5
            )


        with c3:

            evening = st.number_input(
                "🌙 Ca tối",
                min_value=0.0,
                max_value=24.0,
                value=float(
                    settings["evening"]
                ),
                step=0.5
            )


        salary = st.number_input(
            "💰 Lương mỗi giờ",
            min_value=0,
            max_value=10000000,
            value=int(
                settings["salary"]
            ),
            step=1000
        )


        if st.button(
            "💾 Lưu cấu hình",
            type="primary",
            use_container_width=True
        ):

            update_settings(
                morning,
                afternoon,
                evening,
                salary
            )

            st.success(
                "Đã lưu cấu hình."
            )

            st.rerun()


# ============================================================
# FOOTER
# ============================================================

st.markdown(textwrap.dedent("""
    <div class="footer">
        WorkTime • SQLite • Multi-user • Audit-ready
    </div>
    """), unsafe_allow_html=True)
