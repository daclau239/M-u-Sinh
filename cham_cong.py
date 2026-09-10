import streamlit as st
from datetime import date, datetime
import calendar, hashlib, secrets, hmac, os, csv, io

st.set_page_config(page_title="WorkTime", page_icon="🕐", layout="wide")

# ========================= STYLE =========================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
* {font-family:Inter,sans-serif}
.stApp{
 background:
 radial-gradient(circle at 5% 0%,rgba(124,92,255,.14),transparent 25%),
 radial-gradient(circle at 95% 5%,rgba(0,200,255,.12),transparent 25%),
 #f6f7fb;
}
.block-container{max-width:1450px;padding:1.4rem 2rem 3rem}
.hero{padding:25px 28px;border-radius:28px;color:#fff;
 background:linear-gradient(135deg,#15162a,#30265e 55%,#14546b);
 box-shadow:0 18px 45px rgba(24,22,52,.18);margin-bottom:22px}
.hero h1{margin:0;font-size:34px;letter-spacing:-1px}
.hero p{margin:5px 0 0;opacity:.75}
.card{background:rgba(255,255,255,.86);border:1px solid rgba(255,255,255,.95);
 border-radius:21px;padding:17px 19px;box-shadow:0 10px 30px rgba(40,45,75,.07)}
.num{font-size:28px;font-weight:800}.lab{color:#777b89;font-size:13px}
.calhead{font-weight:800;color:#777;text-align:center;padding:7px}
.dayhead{font-size:18px;font-weight:800;margin-bottom:5px}
.hint{text-align:center;color:#a0a0aa;font-size:11px}
.footer{text-align:center;color:#999;font-size:12px;margin-top:25px}
div[data-testid="stButton"] button{border-radius:12px!important;font-weight:700!important;transition:.18s!important}
div[data-testid="stButton"] button:hover{transform:translateY(-2px);box-shadow:0 7px 18px rgba(70,65,120,.13)}
</style>
""", unsafe_allow_html=True)

# ========================= DB =============================
try:
    from supabase import create_client
except ImportError:
    st.error("Thiếu thư viện supabase. Chạy: pip install -r requirements.txt")
    st.stop()

URL = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL",""))
KEY = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY",""))
if not URL or not KEY:
    st.error("Chưa cấu hình SUPABASE_URL và SUPABASE_KEY trong Streamlit Secrets.")
    st.stop()
sb = create_client(URL, KEY)

# ======================= SECURITY ==========================
def hash_pw(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000).hex()
    return salt, digest

def verify_pw(password, salt, digest):
    _, candidate = hash_pw(password, salt)
    return hmac.compare_digest(candidate, digest)

def get_user(username):
    r = sb.table("users").select("*").eq("username",username).eq("active",True).limit(1).execute()
    return r.data[0] if r.data else None

def settings():
    r=sb.table("settings").select("*").eq("id",1).limit(1).execute()
    return r.data[0] if r.data else {"morning":5.5,"afternoon":5.5,"evening":5.5,"salary":25000}

def key(y,m,d): return f"{y}-{m:02d}-{d:02d}"

def hours(shifts,s):
    mp={"Ca sáng":float(s["morning"]),"Ca chiều":float(s["afternoon"]),"Ca tối":float(s["evening"])}
    return sum(mp.get(x,0) for x in shifts)

def money(x): return f"{x:,.0f} đ"

def log_change(user, work_date, old, new):
    sb.table("audit_log").insert({
        "user_id":user["id"],"username":user["username"],"work_date":work_date,
        "old_shifts":old,"new_shifts":new,"changed_at":datetime.utcnow().isoformat()
    }).execute()

def set_attendance(user, work_date, shifts):
    q=sb.table("attendance").select("*").eq("user_id",user["id"]).eq("work_date",work_date).limit(1).execute()
    old=q.data[0]["shifts"] if q.data else []
    if old == shifts: return
    if shifts:
        sb.table("attendance").upsert({
            "user_id":user["id"],"work_date":work_date,"shifts":shifts,
            "updated_at":datetime.utcnow().isoformat()
        },on_conflict="user_id,work_date").execute()
    else:
        sb.table("attendance").delete().eq("user_id",user["id"]).eq("work_date",work_date).execute()
    log_change(user,work_date,old,shifts)

def month_attendance(uid,y,m):
    last=calendar.monthrange(y,m)[1]
    r=sb.table("attendance").select("*").eq("user_id",uid).gte("work_date",f"{y}-{m:02d}-01").lte("work_date",f"{y}-{m:02d}-{last}").execute()
    return {x["work_date"]:x for x in r.data}

# ========================== LOGIN ==========================
if "user" not in st.session_state: st.session_state.user=None

if not st.session_state.user:
    st.markdown("""
    <div class="hero">
      <h1>🕐 WorkTime</h1>
      <p>Chấm công nhiều người • lịch trực tiếp • đối chứng • quản trị</p>
    </div>
    """,unsafe_allow_html=True)
    with st.container(border=True):
        st.subheader("Đăng nhập")
        u=st.text_input("Tên đăng nhập",placeholder="Ví dụ: nhanvien01")
        p=st.text_input("Mật khẩu",type="password")
        if st.button("🚀 Đăng nhập",type="primary",use_container_width=True):
            user=get_user(u.strip())
            if user and verify_pw(p,user["salt"],user["password_hash"]):
                st.session_state.user=user; st.rerun()
            else: st.error("Sai tài khoản hoặc mật khẩu.")
    st.stop()

user=st.session_state.user
S=settings()
if "year" not in st.session_state:
    t=date.today(); st.session_state.year=t.year; st.session_state.month=t.month
y,m=st.session_state.year,st.session_state.month

# ========================= SIDEBAR =========================
with st.sidebar:
    st.markdown("## 👤 Tài khoản")
    st.write(f"**{user['full_name']}**")
    st.caption(f"@{user['username']} · {user['role']}")
    if st.button("🚪 Đăng xuất",use_container_width=True):
        st.session_state.user=None; st.rerun()

# =========================== USER ==========================
st.markdown(f"""
<div class="hero">
<h1>Xin chào, {user['full_name']} 👋</h1>
<p>Tháng {m:02d}/{y} · Bấm S / C / T ngay trên lịch để chấm</p>
</div>
""",unsafe_allow_html=True)

att=month_attendance(user["id"],y,m)
total_days=sum(bool(v["shifts"]) for v in att.values())
total_shifts=sum(len(v["shifts"]) for v in att.values())
total_hours=sum(hours(v["shifts"],S) for v in att.values())
total_money=total_hours*float(S["salary"])

a,b,c,d=st.columns(4)
for col,n,lbl in [(a,total_days,"📅 Ngày làm"),(b,total_shifts,"🎫 Tổng ca"),(c,f"{total_hours:g}","⏱️ Tổng giờ"),(d,money(total_money),"💰 Tiền công")]:
    with col: st.markdown(f'<div class="card"><div class="num">{n}</div><div class="lab">{lbl}</div></div>',unsafe_allow_html=True)

st.write("")
l,mid,r=st.columns([1,2,1])
with l:
    if st.button("← Tháng trước",use_container_width=True):
        if m==1: st.session_state.year,st.session_state.month=y-1,12
        else: st.session_state.month=m-1
        st.rerun()
with mid: st.markdown(f"<h2 style='text-align:center'>📅 {m:02d}/{y}</h2>",unsafe_allow_html=True)
with r:
    if st.button("Tháng sau →",use_container_width=True):
        if m==12: st.session_state.year,st.session_state.month=y+1,1
        else: st.session_state.month=m+1
        st.rerun()

st.caption("💡 Chấm trực tiếp trên lịch: **S = sáng · C = chiều · T = tối**. Nút ✓ là đã chấm.")

# ========================== CALENDAR =======================
days=["T2","T3","T4","T5","T6","T7","CN"]
cc=st.columns(7)
for i,x in enumerate(days):
    with cc[i]: st.markdown(f"<div class='calhead'>{x}</div>",unsafe_allow_html=True)

icons={"Ca sáng":"🌅","Ca chiều":"🌇","Ca tối":"🌙"}
short={"Ca sáng":"S","Ca chiều":"C","Ca tối":"T"}
order=["Ca sáng","Ca chiều","Ca tối"]

for week in calendar.monthcalendar(y,m):
    cc=st.columns(7)
    for i,day in enumerate(week):
        with cc[i]:
            if not day: st.write(""); continue
            k=key(y,m,day)
            cur=att.get(k,{}).get("shifts",[])
            today=(date(y,m,day)==date.today())
            st.markdown(f"<div class='dayhead'>{day:02d} {'•' if today else ''}</div>",unsafe_allow_html=True)
            for s in order:
                checked=s in cur
                label=f"✓ {icons[s]} {short[s]}" if checked else f"+ {icons[s]} {short[s]}"
                if st.button(label,key=f"{k}_{short[s]}",use_container_width=True,type="primary" if checked else "secondary"):
                    new=list(cur)
                    if s in new:new.remove(s)
                    else:new.append(s)
                    new.sort(key=order.index)
                    set_attendance(user,k,new)
                    st.rerun()
            h=hours(cur,S)
            st.markdown(f"<div class='day-hours'>⏱️ {h:g}h</div>" if h else "<div class='hint'>Chưa chấm</div>",unsafe_allow_html=True)

# =========================== EXPORT ========================
st.divider()
st.subheader("📥 Xuất dữ liệu cá nhân")
rows=[["Ngày","Ca sáng","Ca chiều","Ca tối","Tổng giờ","Tiền công"]]
for dd in range(1,calendar.monthrange(y,m)[1]+1):
    k=key(y,m,dd); sh=att.get(k,{}).get("shifts",[])
    h=hours(sh,S)
    rows.append([k,"Có" if "Ca sáng" in sh else "","Có" if "Ca chiều" in sh else "","Có" if "Ca tối" in sh else "",h,h*float(S["salary"])])
buf=io.StringIO(); csv.writer(buf).writerows(rows)
st.download_button("⬇️ Tải CSV tháng này",buf.getvalue().encode("utf-8-sig"),f"cham_cong_{y}_{m:02d}.csv","text/csv",use_container_width=True)

# =========================== ADMIN =========================
if user.get("role")=="admin":
    st.divider()
    st.header("👨‍💼 Trung tâm quản trị")

    tabs=st.tabs(["👥 Nhân viên","📊 Bảng công","🛡️ Đối chứng","⚙️ Cài đặt"])

    with tabs[0]:
        st.subheader("Quản lý tài khoản")
        users=sb.table("users").select("id,username,full_name,role,active,created_at").order("full_name").execute().data
        for u in users:
            x1,x2,x3,x4=st.columns([2.5,2,1,1])
            with x1: st.write(f"**{u['full_name']}**")
            with x2: st.caption(f"@{u['username']}")
            with x3: st.caption("Admin" if u["role"]=="admin" else "Nhân viên")
            with x4: st.caption("🟢" if u["active"] else "🔴")

        st.write("")
        with st.expander("➕ Tạo tài khoản"):
            nu=st.text_input("Username",key="nu")
            nn=st.text_input("Họ tên",key="nn")
            np=st.text_input("Mật khẩu",type="password",key="np")
            nr=st.selectbox("Vai trò",["employee","admin"],key="nr")
            if st.button("Tạo tài khoản",type="primary"):
                if not nu or not nn or not np: st.error("Điền đủ thông tin.")
                elif get_user(nu.strip()): st.error("Username đã tồn tại.")
                else:
                    salt,digest=hash_pw(np)
                    sb.table("users").insert({"username":nu.strip(),"full_name":nn.strip(),"password_hash":digest,"salt":salt,"role":nr,"active":True}).execute()
                    st.success("Đã tạo tài khoản."); st.rerun()

        with st.expander("🔑 Đặt lại mật khẩu"):
            active_users=[u for u in users if u["active"]]
            pick=st.selectbox("Nhân viên",active_users,format_func=lambda x:f"{x['full_name']} (@{x['username']})",key="reset_user") if active_users else None
            rp=st.text_input("Mật khẩu mới",type="password",key="reset_pass")
            if st.button("Đổi mật khẩu",disabled=not pick):
                if len(rp)<6: st.error("Mật khẩu tối thiểu 6 ký tự.")
                else:
                    salt,digest=hash_pw(rp)
                    sb.table("users").update({"salt":salt,"password_hash":digest}).eq("id",pick["id"]).execute()
                    st.success("Đã đổi mật khẩu.")

    with tabs[1]:
        st.subheader(f"📊 Bảng công tháng {m:02d}/{y}")
        users=sb.table("users").select("id,username,full_name,role,active").eq("active",True).order("full_name").execute().data
        table=[["Nhân viên","Ngày","Ca","Giờ","Tiền"]]
        for u in users:
            aa=month_attendance(u["id"],y,m)
            td=sum(bool(v["shifts"]) for v in aa.values())
            ts=sum(len(v["shifts"]) for v in aa.values())
            th=sum(hours(v["shifts"],S) for v in aa.values())
            table.append([u["full_name"],td,ts,f"{th:g}",money(th*float(S["salary"]))])
        st.dataframe(table[1:],column_config={"0":"Nhân viên","1":"Ngày","2":"Ca","3":"Giờ","4":"Tiền"},hide_index=True,use_container_width=True)
        out=io.StringIO(); csv.writer(out).writerows(table)
        st.download_button("⬇️ Xuất bảng công CSV",out.getvalue().encode("utf-8-sig"),f"bang_cong_{y}_{m:02d}.csv","text/csv",use_container_width=True)

    with tabs[2]:
        st.subheader("🛡️ Nhật ký đối chứng")
        logs=sb.table("audit_log").select("*").order("changed_at",desc=True).limit(200).execute().data
        if logs:
            audit_rows=[]
            for z in logs:
                audit_rows.append([z["changed_at"][:19],z["username"],z["work_date"],str(z["old_shifts"]),str(z["new_shifts"])])
            st.dataframe(audit_rows,column_config={"0":"Thời gian","1":"Tài khoản","2":"Ngày","3":"Trước","4":"Sau"},hide_index=True,use_container_width=True)
            out=io.StringIO(); csv.writer(out).writerows([["Thời gian","Tài khoản","Ngày","Trước","Sau"]]+audit_rows)
            st.download_button("⬇️ Tải nhật ký đối chứng",out.getvalue().encode("utf-8-sig"),"audit_log.csv","text/csv",use_container_width=True)
        else: st.info("Chưa có lịch sử.")

    with tabs[3]:
        st.subheader("⚙️ Cấu hình ca & lương")
        x,y1,z=st.columns(3)
        with x: nm=st.number_input("🌅 Ca sáng",0.0,24.0,float(S["morning"]),0.5)
        with y1: af=st.number_input("🌇 Ca chiều",0.0,24.0,float(S["afternoon"]),0.5)
        with z: ev=st.number_input("🌙 Ca tối",0.0,24.0,float(S["evening"]),0.5)
        sal=st.number_input("💰 Lương/giờ",0,10000000,int(S["salary"]),1000)
        if st.button("💾 Lưu cấu hình",type="primary",use_container_width=True):
            sb.table("settings").upsert({"id":1,"morning":nm,"afternoon":af,"evening":ev,"salary":sal}).execute()
            st.success("Đã lưu."); st.rerun()

st.markdown("<div class='footer'>WorkTime • Multi-user • Audit-ready</div>",unsafe_allow_html=True)
