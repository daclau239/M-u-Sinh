
import streamlit as st
import pandas as pd
import requests
import hashlib
import hmac
import io
from datetime import date, datetime
import calendar

st.set_page_config(
    page_title="Chấm công",
    page_icon="🕘",
    layout="wide"
)

# ============================================================
# CẤU HÌNH
# ============================================================
try:
    API_URL = st.secrets["SHEETS_API_URL"].strip()
except Exception:
    API_URL = ""

APPS_SCRIPT = '\nconst USERS="Users";\nconst ATT="Attendance";\n\nfunction out(x){\n  return ContentService.createTextOutput(JSON.stringify(x))\n    .setMimeType(ContentService.MimeType.JSON);\n}\n\nfunction sheet(name,headers){\n  const ss=SpreadsheetApp.getActiveSpreadsheet();\n  let s=ss.getSheetByName(name);\n  if(!s){\n    s=ss.insertSheet(name);\n    s.getRange(1,1,1,headers.length).setValues([headers]);\n    s.setFrozenRows(1);\n  }\n  return s;\n}\n\nfunction setup(){\n  const u=sheet(USERS,[\n    "id","username","password_hash","full_name",\n    "role","department","position","active","created_at"\n  ]);\n  sheet(ATT,[\n    "id","username","work_date","check_in","check_out",\n    "status","note","created_at","updated_at"\n  ]);\n\n  const v=u.getDataRange().getValues();\n  let found=false;\n\n  for(let i=1;i<v.length;i++){\n    if(String(v[i][1])==="admin"){found=true;break;}\n  }\n\n  if(!found){\n    u.appendRow([\n      Utilities.getUuid(),\n      "admin",\n      "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",\n      "Quản trị viên",\n      "admin",\n      "Quản trị",\n      "Administrator",\n      true,\n      new Date()\n    ]);\n  }\n}\n\nfunction doGet(e){\n  setup();\n  const a=e.parameter.action||"ping";\n\n  if(a==="ping") return out({ok:true});\n\n  if(a==="users"){\n    const s=sheet(USERS,[\n      "id","username","password_hash","full_name",\n      "role","department","position","active","created_at"\n    ]);\n    const v=s.getDataRange().getValues();\n    const data=[];\n\n    for(let i=1;i<v.length;i++){\n      if(!v[i][0]) continue;\n      data.push({\n        id:String(v[i][0]),\n        username:String(v[i][1]),\n        password_hash:String(v[i][2]),\n        full_name:String(v[i][3]),\n        role:String(v[i][4]),\n        department:String(v[i][5]||""),\n        position:String(v[i][6]||""),\n        active:String(v[i][7]).toLowerCase()==="true",\n        created_at:String(v[i][8]||"")\n      });\n    }\n    return out({ok:true,data:data});\n  }\n\n  if(a==="attendance"){\n    const s=sheet(ATT,[\n      "id","username","work_date","check_in","check_out",\n      "status","note","created_at","updated_at"\n    ]);\n    const v=s.getDataRange().getValues();\n    const data=[];\n\n    for(let i=1;i<v.length;i++){\n      if(!v[i][0]) continue;\n      let d=v[i][2];\n\n      if(d instanceof Date){\n        d=Utilities.formatDate(\n          d,\n          Session.getScriptTimeZone(),\n          "yyyy-MM-dd"\n        );\n      }\n\n      data.push({\n        id:String(v[i][0]),\n        username:String(v[i][1]),\n        work_date:String(d),\n        check_in:String(v[i][3]||""),\n        check_out:String(v[i][4]||""),\n        status:String(v[i][5]||""),\n        note:String(v[i][6]||"")\n      });\n    }\n    return out({ok:true,data:data});\n  }\n\n  return out({ok:false,error:"Unknown action"});\n}\n\nfunction doPost(e){\n  setup();\n\n  let b={};\n  try{\n    b=JSON.parse(e.postData.contents||"{}");\n  }catch(err){\n    return out({ok:false,error:"JSON không hợp lệ"});\n  }\n\n  if(b.action==="create_user"){\n    const s=sheet(USERS,[\n      "id","username","password_hash","full_name",\n      "role","department","position","active","created_at"\n    ]);\n    const v=s.getDataRange().getValues();\n\n    for(let i=1;i<v.length;i++){\n      if(String(v[i][1])===String(b.username)){\n        return out({ok:false,error:"Tên đăng nhập đã tồn tại"});\n      }\n    }\n\n    s.appendRow([\n      Utilities.getUuid(),\n      b.username,\n      b.password_hash,\n      b.full_name,\n      b.role||"employee",\n      b.department||"",\n      b.position||"",\n      true,\n      new Date()\n    ]);\n    return out({ok:true});\n  }\n\n  if(b.action==="save_attendance"){\n    const s=sheet(ATT,[\n      "id","username","work_date","check_in","check_out",\n      "status","note","created_at","updated_at"\n    ]);\n    const v=s.getDataRange().getValues();\n\n    for(let i=1;i<v.length;i++){\n      let d=v[i][2];\n\n      if(d instanceof Date){\n        d=Utilities.formatDate(\n          d,\n          Session.getScriptTimeZone(),\n          "yyyy-MM-dd"\n        );\n      }\n\n      if(\n        String(v[i][1])===String(b.username) &&\n        String(d)===String(b.work_date)\n      ){\n        s.getRange(i+1,3,1,7).setValues([[\n          b.work_date,\n          b.check_in||"",\n          b.check_out||"",\n          b.status||"Đi làm",\n          b.note||"",\n          v[i][7]||new Date(),\n          new Date()\n        ]]);\n        return out({ok:true,mode:"updated"});\n      }\n    }\n\n    const now=new Date();\n    s.appendRow([\n      Utilities.getUuid(),\n      b.username,\n      b.work_date,\n      b.check_in||"",\n      b.check_out||"",\n      b.status||"Đi làm",\n      b.note||"",\n      now,\n      now\n    ]);\n\n    return out({ok:true,mode:"created"});\n  }\n\n  if(b.action==="delete_attendance"){\n    const s=sheet(ATT,[\n      "id","username","work_date","check_in","check_out",\n      "status","note","created_at","updated_at"\n    ]);\n    const v=s.getDataRange().getValues();\n\n    for(let i=v.length-1;i>=1;i--){\n      let d=v[i][2];\n\n      if(d instanceof Date){\n        d=Utilities.formatDate(\n          d,\n          Session.getScriptTimeZone(),\n          "yyyy-MM-dd"\n        );\n      }\n\n      if(\n        String(v[i][1])===String(b.username) &&\n        String(d)===String(b.work_date)\n      ){\n        s.deleteRow(i+1);\n      }\n    }\n\n    return out({ok:true});\n  }\n\n  return out({ok:false,error:"Unknown action"});\n}\n'

# ============================================================
# API
# ============================================================
def api_get(action):
    r = requests.get(
        API_URL,
        params={"action": action},
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def api_post(data):
    r = requests.post(
        API_URL,
        json=data,
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def sha256(text):
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()

# ============================================================
# DATA
# ============================================================
def get_users():
    try:
        return pd.DataFrame(
            api_get("users").get("data", [])
        )
    except Exception:
        return pd.DataFrame()

def get_attendance():
    try:
        return pd.DataFrame(
            api_get("attendance").get("data", [])
        )
    except Exception:
        return pd.DataFrame()

def get_user(username):
    df = get_users()
    if df.empty:
        return None

    x = df[df["username"].astype(str) == str(username)]
    return x.iloc[0].to_dict() if not x.empty else None

def authenticate(username, password):
    u = get_user(username)

    if not u or not bool(u["active"]):
        return None

    if hmac.compare_digest(
        str(u["password_hash"]),
        sha256(password)
    ):
        return u

    return None

def get_today(username):
    df = get_attendance()

    if df.empty:
        return None

    today = date.today().isoformat()

    x = df[
        (df["username"].astype(str) == str(username)) &
        (df["work_date"].astype(str).str[:10] == today)
    ]

    return x.iloc[0].to_dict() if not x.empty else None

# ============================================================
# CHƯA CẤU HÌNH
# ============================================================
if not API_URL:
    st.title("🕘 WEB CHẤM CÔNG")
    st.warning("Chưa kết nối Google Sheets.")

    st.markdown("""
### Làm đúng 4 bước

**1. Tạo Google Sheet**

Google Drive → Mới → Google Trang tính.

**2. Mở Apps Script**

Trong Google Sheet:

**Extensions → Apps Script**

Xóa toàn bộ code cũ và dán code bên dưới.

**3. Deploy**

Chọn:

**Deploy → New deployment → Web app**

- Execute as: **Me**
- Who has access: **Anyone**

Bấm **Deploy**, cấp quyền nếu Google hỏi, rồi copy **Web app URL**.

**4. Kết nối website**

Vào:

**Streamlit Cloud → Manage app → Settings → Secrets**

Dán:

```toml
SHEETS_API_URL = "WEB_APP_URL_CỦA_EM"
```

Save → Reboot app.
""")

    with st.expander("📋 CODE APPS SCRIPT — COPY TOÀN BỘ"):
        st.code(APPS_SCRIPT, language="javascript")

    st.stop()

# ============================================================
# TEST
# ============================================================
try:
    result = api_get("ping")

    if not result.get("ok"):
        st.error("Google Sheets chưa phản hồi.")
        st.stop()

except Exception as e:
    st.error("❌ Không kết nối được Google Sheets.")
    st.code(str(e))
    st.stop()

# ============================================================
# LOGIN
# ============================================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🕘 Chấm công")
    st.caption("Đăng nhập hệ thống")

    with st.form("login"):
        username = st.text_input("Tên đăng nhập")
        password = st.text_input(
            "Mật khẩu",
            type="password"
        )

        submit = st.form_submit_button(
            "🔐 ĐĂNG NHẬP",
            use_container_width=True
        )

        if submit:
            u = authenticate(username, password)

            if u:
                st.session_state.logged_in = True
                st.session_state.username = u["username"]
                st.rerun()
            else:
                st.error(
                    "Sai tài khoản, mật khẩu hoặc tài khoản đã bị khóa."
                )

    st.caption("Admin mặc định: admin / admin123")
    st.stop()

user = get_user(
    st.session_state.username
)

if not user or not bool(user["active"]):
    st.session_state.clear()
    st.rerun()

with st.sidebar:
    st.markdown("## 🕘 CHẤM CÔNG")
    st.write(f"👤 **{user['full_name']}**")
    st.caption(f"Tài khoản: {user['username']}")
    st.caption(f"Vai trò: {user['role']}")
    st.divider()

    if st.button(
        "🚪 Đăng xuất",
        use_container_width=True
    ):
        st.session_state.clear()
        st.rerun()

# ============================================================
# NHÂN VIÊN
# ============================================================
def employee_page():

    today = date.today()
    current = get_today(user["username"])

    st.title(
        f"Xin chào, {user['full_name']} 👋"
    )
    st.caption("Bảng chấm công cá nhân")

    c1,c2,c3 = st.columns(3)

    c1.metric(
        "Hôm nay",
        today.strftime("%d/%m/%Y")
    )

    c2.metric(
        "Giờ vào",
        (current or {}).get("check_in") or "—"
    )

    c3.metric(
        "Giờ ra",
        (current or {}).get("check_out") or "—"
    )

    t1,t2,t3 = st.tabs([
        "📝 Chấm công",
        "📅 Bảng công",
        "📊 Xuất Excel"
    ])

    with t1:
        with st.form("attendance"):

            now = datetime.now().time()
            ci = now
            co = now

            if current:
                try:
                    if current.get("check_in"):
                        ci = datetime.strptime(
                            current["check_in"],
                            "%H:%M"
                        ).time()

                    if current.get("check_out"):
                        co = datetime.strptime(
                            current["check_out"],
                            "%H:%M"
                        ).time()
                except Exception:
                    pass

            c1,c2 = st.columns(2)

            check_in = c1.time_input(
                "Giờ vào",
                ci
            )

            check_out = c2.time_input(
                "Giờ ra",
                co
            )

            statuses = [
                "Đi làm",
                "Nghỉ phép",
                "Nghỉ",
                "Đi trễ",
                "Về sớm",
                "WFH"
            ]

            status = st.selectbox(
                "Trạng thái",
                statuses,
                index=(
                    statuses.index(current["status"])
                    if current
                    and current.get("status") in statuses
                    else 0
                )
            )

            note = st.text_input(
                "Ghi chú",
                value=(current or {}).get("note","")
            )

            if st.form_submit_button(
                "💾 LƯU CHẤM CÔNG",
                use_container_width=True
            ):

                result = api_post({
                    "action":"save_attendance",
                    "username":user["username"],
                    "work_date":today.isoformat(),
                    "check_in":check_in.strftime("%H:%M"),
                    "check_out":check_out.strftime("%H:%M"),
                    "status":status,
                    "note":note
                })

                if result.get("ok"):
                    st.success("✅ Đã lưu thành công.")
                    st.rerun()
                else:
                    st.error(
                        result.get(
                            "error",
                            "Không lưu được."
                        )
                    )

    with t2:
        c1,c2 = st.columns(2)

        year = c1.number_input(
            "Năm",
            2020,
            2100,
            today.year
        )

        month = c2.selectbox(
            "Tháng",
            range(1,13),
            today.month-1
        )

        df = get_attendance()

        if not df.empty:
            df = df[
                (df["username"].astype(str) == user["username"]) &
                (
                    df["work_date"].astype(str).str.startswith(
                        f"{int(year):04d}-{int(month):02d}-"
                    )
                )
            ]

        days = calendar.monthrange(
            int(year),
            int(month)
        )[1]

        rows = []

        for d in range(1,days+1):
            dt = date(
                int(year),
                int(month),
                d
            )

            x = (
                df[
                    df["work_date"].astype(str).str[:10]
                    == dt.isoformat()
                ]
                if not df.empty
                else pd.DataFrame()
            )

            if not x.empty:
                r = x.iloc[0]

                rows.append({
                    "Ngày":dt.strftime("%d/%m/%Y"),
                    "Thứ":[
                        "T2","T3","T4","T5",
                        "T6","T7","CN"
                    ][dt.weekday()],
                    "Giờ vào":r.get("check_in",""),
                    "Giờ ra":r.get("check_out",""),
                    "Trạng thái":r.get("status",""),
                    "Ghi chú":r.get("note","")
                })
            else:
                rows.append({
                    "Ngày":dt.strftime("%d/%m/%Y"),
                    "Thứ":[
                        "T2","T3","T4","T5",
                        "T6","T7","CN"
                    ][dt.weekday()],
                    "Giờ vào":"",
                    "Giờ ra":"",
                    "Trạng thái":"",
                    "Ghi chú":""
                })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )

    with t3:
        year = st.number_input(
            "Năm xuất",
            2020,
            2100,
            today.year,
            key="excel_year"
        )

        month = st.selectbox(
            "Tháng xuất",
            range(1,13),
            today.month-1,
            key="excel_month"
        )

        df = get_attendance()

        if not df.empty:
            df = df[
                (df["username"].astype(str)==user["username"]) &
                (
                    df["work_date"].astype(str).str.startswith(
                        f"{int(year):04d}-{int(month):02d}-"
                    )
                )
            ]

        out = io.BytesIO()

        with pd.ExcelWriter(
            out,
            engine="openpyxl"
        ) as writer:
            df.to_excel(
                writer,
                index=False,
                sheet_name="BangCong"
            )

        out.seek(0)

        st.download_button(
            "⬇️ TẢI EXCEL",
            out.getvalue(),
            file_name=(
                f"Bang_cong_{user['username']}_"
                f"{int(month):02d}_{int(year)}.xlsx"
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

    st.title("🛠️ TRUNG TÂM QUẢN TRỊ")

    users = get_users()
    att = get_attendance()

    c1,c2,c3 = st.columns(3)

    c1.metric("Tài khoản",len(users))
    c2.metric(
        "Đang hoạt động",
        int(users["active"].sum())
        if not users.empty else 0
    )
    c3.metric("Lượt chấm công",len(att))

    t1,t2,t3 = st.tabs([
        "👥 Nhân viên",
        "📝 Chấm công",
        "📊 Bảng công"
    ])

    with t1:

        if not users.empty:
            show=users.copy()

            show["active"]=show["active"].map({
                True:"Đang hoạt động",
                False:"Đã khóa"
            })

            st.dataframe(
                show.rename(columns={
                    "username":"Tài khoản",
                    "full_name":"Họ tên",
                    "role":"Vai trò",
                    "department":"Bộ phận",
                    "position":"Chức vụ",
                    "active":"Trạng thái"
                }),
                use_container_width=True,
                hide_index=True
            )

        with st.expander("➕ Tạo tài khoản"):

            with st.form("new_user"):

                c1,c2=st.columns(2)

                un=c1.text_input("Tên đăng nhập *")
                fn=c1.text_input("Họ tên *")
                pw=c1.text_input(
                    "Mật khẩu *",
                    type="password"
                )

                role=c2.selectbox(
                    "Vai trò",
                    ["employee","admin"]
                )

                dep=c2.text_input("Bộ phận")
                pos=c2.text_input("Chức vụ")

                if st.form_submit_button(
                    "Tạo tài khoản",
                    use_container_width=True
                ):

                    if not un or not fn or not pw:
                        st.error("Nhập đủ thông tin.")
                    else:

                        result=api_post({
                            "action":"create_user",
                            "username":un.strip(),
                            "password_hash":sha256(pw),
                            "full_name":fn.strip(),
                            "role":role,
                            "department":dep,
                            "position":pos
                        })

                        if result.get("ok"):
                            st.success("Đã tạo tài khoản.")
                            st.rerun()
                        else:
                            st.error(
                                result.get(
                                    "error",
                                    "Không tạo được."
                                )
                            )

    with t2:

        employees=(
            users[users["role"]=="employee"]
            if not users.empty else pd.DataFrame()
        )

        if employees.empty:
            st.info("Chưa có nhân viên.")
        else:

            options={
                f"{r['full_name']} ({r['username']})":
                r["username"]
                for _,r in employees.iterrows()
            }

            label=st.selectbox(
                "Nhân viên",
                list(options.keys())
            )

            un=options[label]

            d=st.date_input(
                "Ngày",
                date.today()
            )

            existing=None

            if not att.empty:
                x=att[
                    (att["username"].astype(str)==un) &
                    (att["work_date"].astype(str).str[:10]==d.isoformat())
                ]

                if not x.empty:
                    existing=x.iloc[0].to_dict()

            with st.form("admin_att"):

                c1,c2=st.columns(2)

                ci=c1.text_input(
                    "Giờ vào",
                    (existing or {}).get("check_in","")
                )

                co=c1.text_input(
                    "Giờ ra",
                    (existing or {}).get("check_out","")
                )

                statuses=[
                    "Đi làm",
                    "Nghỉ phép",
                    "Nghỉ",
                    "Đi trễ",
                    "Về sớm",
                    "WFH"
                ]

                status=c2.selectbox(
                    "Trạng thái",
                    statuses,
                    index=(
                        statuses.index(existing["status"])
                        if existing
                        and existing.get("status") in statuses
                        else 0
                    )
                )

                note=c2.text_input(
                    "Ghi chú",
                    (existing or {}).get("note","")
                )

                a,b=st.columns(2)

                save=a.form_submit_button(
                    "💾 LƯU",
                    use_container_width=True
                )

                delete=b.form_submit_button(
                    "🗑️ XÓA",
                    use_container_width=True
                )

                if save:

                    result=api_post({
                        "action":"save_attendance",
                        "username":un,
                        "work_date":d.isoformat(),
                        "check_in":ci,
                        "check_out":co,
                        "status":status,
                        "note":note
                    })

                    if result.get("ok"):
                        st.success("Đã lưu.")
                        st.rerun()
                    else:
                        st.error(
                            result.get(
                                "error",
                                "Lỗi."
                            )
                        )

                if delete:

                    result=api_post({
                        "action":"delete_attendance",
                        "username":un,
                        "work_date":d.isoformat()
                    })

                    if result.get("ok"):
                        st.success("Đã xóa.")
                        st.rerun()
                    else:
                        st.error(
                            result.get(
                                "error",
                                "Lỗi."
                            )
                        )

    with t3:

        c1,c2=st.columns(2)

        year=c1.number_input(
            "Năm",
            2020,
            2100,
            date.today().year,
            key="admin_year"
        )

        month=c2.selectbox(
            "Tháng",
            range(1,13),
            date.today().month-1,
            key="admin_month"
        )

        employee_options=["Tất cả"]

        if not users.empty:
            employee_options += users[
                users["role"]=="employee"
            ]["username"].tolist()

        employee=st.selectbox(
            "Nhân viên",
            employee_options
        )

        if not att.empty:

            mask=att[
                "work_date"
            ].astype(str).str.startswith(
                f"{int(year):04d}-{int(month):02d}-"
            )

            if employee!="Tất cả":
                mask &= (
                    att["username"].astype(str)
                    == employee
                )

            show=att[mask].copy()

            if not show.empty:

                if not users.empty:
                    show=show.merge(
                        users[
                            ["username","full_name","department"]
                        ],
                        on="username",
                        how="left"
                    )

                show=show.rename(columns={
                    "username":"Tài khoản",
                    "full_name":"Họ tên",
                    "department":"Bộ phận",
                    "work_date":"Ngày",
                    "check_in":"Giờ vào",
                    "check_out":"Giờ ra",
                    "status":"Trạng thái",
                    "note":"Ghi chú"
                })

                st.dataframe(
                    show,
                    use_container_width=True,
                    hide_index=True
                )

                out=io.BytesIO()

                with pd.ExcelWriter(
                    out,
                    engine="openpyxl"
                ) as writer:
                    show.to_excel(
                        writer,
                        index=False,
                        sheet_name="BangCong"
                    )

                out.seek(0)

                st.download_button(
                    "⬇️ XUẤT EXCEL",
                    out.getvalue(),
                    file_name=(
                        f"Bang_cong_"
                        f"{int(month):02d}_"
                        f"{int(year)}.xlsx"
                    ),
                    mime=(
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                    use_container_width=True
                )
            else:
                st.info("Chưa có dữ liệu.")
        else:
            st.info("Chưa có dữ liệu.")

# ============================================================
# RUN
# ============================================================
if user["role"]=="admin":
    admin_page()
else:
    employee_page()
