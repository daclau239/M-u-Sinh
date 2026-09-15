import streamlit as st
import pandas as pd
import requests, hashlib, hmac, io, calendar
from datetime import datetime, date
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title='Chấm công', page_icon='🕘', layout='wide')

try:
    SHEETS_API_URL = st.secrets['SHEETS_API_URL'].strip()
except Exception:
    SHEETS_API_URL = ''

ADMIN_USER = 'admin'
ADMIN_PASS = 'admin123'

APPS_SCRIPT = r'''const USERS='Users'; const ATT='Attendance';
function out(x){return ContentService.createTextOutput(JSON.stringify(x)).setMimeType(ContentService.MimeType.JSON)}
function sheet(name,headers){const ss=SpreadsheetApp.getActive();let s=ss.getSheetByName(name);if(!s){s=ss.insertSheet(name);s.getRange(1,1,1,headers.length).setValues([headers]);s.setFrozenRows(1)}return s}
function setup(){const u=sheet(USERS,['id','username','password_hash','full_name','role','department','position','active','created_at']); sheet(ATT,['id','username','work_date','check_in','check_out','status','note','created_at','updated_at']); if(u.getLastRow()<2) u.appendRow([Utilities.getUuid(),'admin','240be518fabd2724d59f7e9c2fbe9cbf1d96f9cc14b2b0d5c8ad4d4f3f6b0d6','Quản trị viên','admin','Quản trị','Administrator',true,new Date()])}
function rows(s){const v=s.getDataRange().getValues(),o=[];for(let i=1;i<v.length;i++)if(v[i][0])o.push(v[i]);return o}
function doGet(e){setup();let a=e.parameter.action||'ping';if(a==='ping')return out({ok:true});if(a==='users'){let s=sheet(USERS,['id','username','password_hash','full_name','role','department','position','active','created_at']);return out({ok:true,data:rows(s).map(r=>({id:r[0],username:r[1],password_hash:r[2],full_name:r[3],role:r[4],department:r[5],position:r[6],active:String(r[7]).toLowerCase()==='true',created_at:r[8]}))})}if(a==='attendance'){let s=sheet(ATT,['id','username','work_date','check_in','check_out','status','note','created_at','updated_at']);return out({ok:true,data:rows(s).map(r=>({id:r[0],username:r[1],work_date:r[2] instanceof Date?Utilities.formatDate(r[2],Session.getScriptTimeZone(),'yyyy-MM-dd'):String(r[2]).slice(0,10),check_in:r[3]||'',check_out:r[4]||'',status:r[5]||'',note:r[6]||'',created_at:r[7],updated_at:r[8]}))})}return out({ok:false,error:'Unknown action'})}
function doPost(e){setup();let b={};try{b=JSON.parse(e.postData.contents||'{}')}catch(x){return out({ok:false,error:'Invalid JSON'})}if(b.action==='upsert_user'){let s=sheet(USERS,['id','username','password_hash','full_name','role','department','position','active','created_at']),v=s.getDataRange().getValues(),r=-1;for(let i=1;i<v.length;i++)if(String(v[i][1])===String(b.username)){r=i+1;break}if(r<0)s.appendRow([Utilities.getUuid(),b.username,b.password_hash,b.full_name,b.role||'employee',b.department||'',b.position||'',b.active!==false,new Date()]);else{s.getRange(r,2,1,8).setValues([[b.username,b.password_hash,b.full_name,b.role||'employee',b.department||'',b.position||'',b.active!==false,v[r-1][8]]])}return out({ok:true})}
if(b.action==='update_user'){let s=sheet(USERS,['id','username','password_hash','full_name','role','department','position','active','created_at']),v=s.getDataRange().getValues(),r=-1;for(let i=1;i<v.length;i++)if(String(v[i][0])===String(b.id)){r=i+1;break}if(r<0)return out({ok:false,error:'User not found'});s.getRange(r,2,1,8).setValues([[b.username,b.password_hash||v[r-1][2],b.full_name,b.role,b.department||'',b.position||'',b.active!==false,v[r-1][8]]]);return out({ok:true})}
if(b.action==='upsert_attendance'){let s=sheet(ATT,['id','username','work_date','check_in','check_out','status','note','created_at','updated_at']),v=s.getDataRange().getValues(),r=-1;for(let i=1;i<v.length;i++){let d=v[i][2] instanceof Date?Utilities.formatDate(v[i][2],Session.getScriptTimeZone(),'yyyy-MM-dd'):String(v[i][2]).slice(0,10);if(String(v[i][1])===String(b.username)&&d===String(b.work_date)){r=i+1;break}}let now=new Date();if(r<0)s.appendRow([Utilities.getUuid(),b.username,b.work_date,b.check_in||'',b.check_out||'',b.status||'Đi làm',b.note||'',now,now]);else s.getRange(r,3,1,7).setValues([[b.work_date,b.check_in||'',b.check_out||'',b.status||'Đi làm',b.note||'',v[r-1][7]||now,now]]);return out({ok:true})}
if(b.action==='delete_attendance'){let s=sheet(ATT,['id','username','work_date','check_in','check_out','status','note','created_at','updated_at']),v=s.getDataRange().getValues();for(let i=v.length-1;i>=1;i--){let d=v[i][2] instanceof Date?Utilities.formatDate(v[i][2],Session.getScriptTimeZone(),'yyyy-MM-dd'):String(v[i][2]).slice(0,10);if(String(v[i][1])===String(b.username)&&d===String(b.work_date))s.deleteRow(i+1)}return out({ok:true})}return out({ok:false,error:'Unknown action'})}'''

def shash(s): return hashlib.sha256(s.encode()).hexdigest()

def api_get(action):
    r=requests.get(SHEETS_API_URL,params={'action':action},timeout=30); r.raise_for_status(); return r.json()

def api_post(payload):
    r=requests.post(SHEETS_API_URL,json=payload,timeout=30); r.raise_for_status(); return r.json()

def get_users_df():
    return pd.DataFrame(api_get('users').get('data',[]))

def get_att_df():
    return pd.DataFrame(api_get('attendance').get('data',[]))

def user_by_username(username):
    df=get_users_df()
    if df.empty:return None
    x=df[df.username.astype(str)==str(username)]
    return x.iloc[0].to_dict() if not x.empty else None

def auth(username,password):
    u=user_by_username(username.strip())
    if not u or str(u.get('active')).lower()!='true':return None
    return u if hmac.compare_digest(str(u['password_hash']),shash(password)) else None

def att_one(username,ds):
    df=get_att_df()
    if df.empty:return None
    x=df[(df.username.astype(str)==str(username))&(df.work_date.astype(str).str[:10]==ds)]
    return x.iloc[0].to_dict() if not x.empty else None

def save_att(username,ds,ci,co,status,note):
    return api_post({'action':'upsert_attendance','username':username,'work_date':ds,'check_in':ci,'check_out':co,'status':status,'note':note}).get('ok',False)

def delete_att(username,ds):
    return api_post({'action':'delete_attendance','username':username,'work_date':ds}).get('ok',False)

def font(n,b=False):
    p='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if b else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    try:return ImageFont.truetype(p,n)
    except:return ImageFont.load_default()

def ctext(d,box,text,f):
    a,b,c,e=box; z=d.multiline_textbbox((0,0),text,font=f,spacing=2);tw=z[2]-z[0];th=z[3]-z[1];d.multiline_text(((a+c-tw)/2,(b+e-th)/2-z[1]),text,font=f,fill=(20,20,20),align='center',spacing=2)

def make_a4(username,year,month):
    u=user_by_username(username); df=get_att_df(); data=pd.DataFrame() if df.empty else df[(df.username.astype(str)==str(username))&(df.work_date.astype(str).str.startswith(f'{year:04d}-{month:02d}-'))]
    W,H,m=1754,1240,55; img=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(img); ft,fs,fh,fc,sm=font(42,1),font(25),font(22,1),font(20),font(17)
    ctext(d,(m,30,W-m,95),'BẢNG CHẤM CÔNG',ft);d.text((m,115),f"Họ và tên: {u['full_name']}",font=fs,fill=(20,20,20));d.text((m,150),f"Tài khoản: {u['username']}",font=fs,fill=(20,20,20));d.text((700,115),f"Bộ phận: {u.get('department','')}",font=fs,fill=(20,20,20));d.text((700,150),f"Chức vụ: {u.get('position','')}",font=fs,fill=(20,20,20));ctext(d,(m,185,W-m,230),f'THÁNG {month:02d}/{year}',fh)
    days=calendar.monthrange(year,month)[1]; tx,ty,tw,th=m,255,W-m*2,790; lw=115;dw=(tw-lw)/days;d.rectangle((tx,ty,tx+tw,ty+th),outline=(0,0,0),width=2);ctext(d,(tx,ty,tx+lw,ty+58),'NGÀY',fh);lookup={}
    if not data.empty:
        for _,r in data.iterrows():lookup[str(r.work_date)[:10]]=r.to_dict()
    for day in range(1,days+1):
        x1=tx+lw+(day-1)*dw;x2=tx+lw+day*dw;d.line((x2,ty,x2,ty+th),fill=(0,0,0));dt=date(year,month,day);ctext(d,(x1,ty,x2,ty+58),f"{day}\n{['T2','T3','T4','T5','T6','T7','CN'][dt.weekday()]}",sm)
    rows=[('Trạng thái','status'),('Vào','check_in'),('Ra','check_out'),('Ghi chú','note')];rh=(th-58)/len(rows)
    for i,(lab,key) in enumerate(rows):
        y1=ty+58+i*rh;y2=ty+58+(i+1)*rh;d.line((tx,y1,tx+tw,y1),fill=(0,0,0));ctext(d,(tx,y1,tx+lw,y2),lab,fh)
        for day in range(1,days+1):
            x1=tx+lw+(day-1)*dw;x2=tx+lw+day*dw;ds=f'{year:04d}-{month:02d}-{day:02d}';v=str(lookup.get(ds,{}).get(key,'') or '');
            if key=='status':v={'Đi làm':'✓','Nghỉ phép':'P','Nghỉ':'N','Đi trễ':'T','Về sớm':'S','WFH':'WFH'}.get(v,v[:5])
            ctext(d,(x1,y1,x2,y2),v[:10],fc)
    statuses=[] if data.empty else data.status.tolist();d.text((m,ty+th+35),f"Đi làm: {statuses.count('Đi làm')}    Nghỉ phép: {statuses.count('Nghỉ phép')}    Nghỉ: {statuses.count('Nghỉ')}    Đi trễ: {statuses.count('Đi trễ')}    Về sớm: {statuses.count('Về sớm')}",font=fs,fill=(20,20,20));o=io.BytesIO();img.save(o,format='PNG',dpi=(150,150));o.seek(0);return o.getvalue()

if not SHEETS_API_URL:
    st.markdown('# 🕘 WEB CHẤM CÔNG')
    st.warning('Chưa kết nối Google Sheets.')
    st.markdown('''### Làm đúng 3 bước\n\n**1.** Tạo một Google Sheet.\n\n**2.** Vào `Extensions → Apps Script`, xóa code mặc định và dán đoạn code bên dưới.\n\n**3.** Bấm `Deploy → New deployment → Web app`, chọn **Execute as: Me** và **Who has access: Anyone**, Deploy rồi copy **Web app URL**.\n\nSau đó vào **Streamlit Cloud → Manage app → Settings → Secrets** và thêm:\n\n```toml\nSHEETS_API_URL = "DÁN_URL_WEB_APP_VÀO_ĐÂY"\n```''')
    st.code(APPS_SCRIPT,language='javascript'); st.stop()

try:
    if not api_get('ping').get('ok'): raise RuntimeError('Ping failed')
except Exception as e:
    st.error('Không kết nối được Google Sheets.')
    st.code(str(e)); st.stop()

if 'logged_in' not in st.session_state: st.session_state.logged_in=False
if not st.session_state.logged_in:
    st.markdown('## 🕘 Đăng nhập')
    with st.form('login'):
        un=st.text_input('Tên đăng nhập');pw=st.text_input('Mật khẩu',type='password');go=st.form_submit_button('🔐 Đăng nhập',use_container_width=True)
        if go:
            u=auth(un,pw)
            if u: st.session_state.logged_in=True;st.session_state.username=u['username'];st.rerun()
            else: st.error('Sai tài khoản hoặc mật khẩu.')
    st.caption('Admin mặc định: admin / admin123'); st.stop()

user=user_by_username(st.session_state.username)
if not user or str(user.get('active')).lower()!='true': st.session_state.clear(); st.rerun()
with st.sidebar:
    st.markdown('## 🕘 CHẤM CÔNG');st.caption(f"{user['full_name']} • {user['role']}")
    if st.button('🚪 Đăng xuất',use_container_width=True): st.session_state.clear();st.rerun()

if user['role']=='employee':
    today=date.today();cur=att_one(user['username'],today.isoformat());st.markdown(f"# Xin chào, {user['full_name']} 👋")
    a,b,c=st.columns(3);a.metric('Hôm nay',today.strftime('%d/%m/%Y'));b.metric('Giờ vào',(cur or {}).get('check_in') or '—');c.metric('Giờ ra',(cur or {}).get('check_out') or '—')
    t1,t2,t3=st.tabs(['📝 Chấm công','📅 Bảng công','🖼️ Xuất A4'])
    with t1:
        with st.form('emp_att'):
            ci=datetime.now().time();co=datetime.now().time()
            try:
                if cur and cur.get('check_in'): ci=datetime.strptime(cur['check_in'],'%H:%M').time()
                if cur and cur.get('check_out'): co=datetime.strptime(cur['check_out'],'%H:%M').time()
            except: pass
            x,y=st.columns(2);ci=x.time_input('Giờ vào',ci);co=y.time_input('Giờ ra',co);sts=['Đi làm','Nghỉ phép','Nghỉ','Đi trễ','Về sớm','WFH'];status=st.selectbox('Trạng thái',sts,index=sts.index(cur['status']) if cur and cur.get('status') in sts else 0);note=st.text_input('Ghi chú',value=(cur or {}).get('note',''))
            if st.form_submit_button('💾 LƯU CHẤM CÔNG',use_container_width=True):
                if save_att(user['username'],today.isoformat(),ci.strftime('%H:%M'),co.strftime('%H:%M'),status,note):st.success('✅ Đã lưu.');st.rerun()
    with t2:
        y=st.number_input('Năm',2020,2100,today.year,key='ey');m=st.selectbox('Tháng',range(1,13),today.month-1,key='em');df=get_att_df();df=pd.DataFrame() if df.empty else df[(df.username.astype(str)==user['username'])&(df.work_date.astype(str).str.startswith(f'{int(y):04d}-{int(m):02d}-'))];rows=[]
        for d in range(1,calendar.monthrange(int(y),int(m))[1]+1):
            dt=date(int(y),int(m),d);x=df[df.work_date.astype(str).str[:10]==dt.isoformat()] if not df.empty else pd.DataFrame();r=x.iloc[0] if not x.empty else {}
            rows.append({'Ngày':dt.strftime('%d/%m/%Y'),'Thứ':['T2','T3','T4','T5','T6','T7','CN'][dt.weekday()],'Vào':r.get('check_in',''),'Ra':r.get('check_out',''),'Trạng thái':r.get('status',''),'Ghi chú':r.get('note','')})
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    with t3:
        y=st.number_input('Năm xuất',2020,2100,today.year,key='ay');m=st.selectbox('Tháng xuất',range(1,13),today.month-1,key='am')
        if st.button('🖼️ Tạo bảng A4',use_container_width=True): st.session_state.png=make_a4(user['username'],int(y),int(m))
        if st.session_state.get('png'): st.image(st.session_state.png,use_container_width=True);st.download_button('⬇️ Tải ảnh A4',st.session_state.png,file_name=f"Bang_cong_{user['username']}_{int(m):02d}_{int(y)}.png",mime='image/png',use_container_width=True)
else:
    st.markdown('# 🛠️ TRUNG TÂM QUẢN TRỊ');ud=get_users_df();ad=get_att_df();a,b,c=st.columns(3);a.metric('Tài khoản',len(ud));b.metric('Đang hoạt động',int(ud.active.sum()) if not ud.empty else 0);c.metric('Lượt chấm công',len(ad))
    t1,t2,t3,t4=st.tabs(['👥 Nhân viên','📝 Chấm công','📊 Bảng công','🖼️ Xuất A4'])
    with t1:
        if not ud.empty: st.dataframe(ud.rename(columns={'username':'Tài khoản','full_name':'Họ tên','role':'Vai trò','department':'Bộ phận','position':'Chức vụ','active':'Hoạt động'}),use_container_width=True,hide_index=True)
        with st.expander('➕ Tạo tài khoản'):
            with st.form('new'):
                x,y=st.columns(2);un=x.text_input('Tên đăng nhập *');fn=x.text_input('Họ tên *');pw=x.text_input('Mật khẩu *',type='password');role=y.selectbox('Vai trò',['employee','admin']);dep=y.text_input('Bộ phận');pos=y.text_input('Chức vụ')
                if st.form_submit_button('Tạo',use_container_width=True):
                    if not un or not fn or not pw:st.error('Nhập đủ thông tin.')
                    else:
                        r=api_post({'action':'upsert_user','username':un.strip(),'password_hash':shash(pw),'full_name':fn.strip(),'role':role,'department':dep,'position':pos,'active':True});st.success('Đã tạo.') if r.get('ok') else st.error(r.get('error','Lỗi'));st.rerun() if r.get('ok') else None
        with st.expander('✏️ Sửa tài khoản'):
            if not ud.empty:
                sel=st.selectbox('Chọn',ud.username.tolist());u=user_by_username(sel)
                with st.form('edit'):
                    x,y=st.columns(2);fn=x.text_input('Họ tên',u['full_name']);dep=x.text_input('Bộ phận',u.get('department',''));pos=x.text_input('Chức vụ',u.get('position',''));role=y.selectbox('Vai trò',['employee','admin'],index=0 if u['role']=='employee' else 1);active=y.checkbox('Hoạt động',bool(u['active']));pw=y.text_input('Mật khẩu mới',type='password');
                    if st.form_submit_button('Lưu',use_container_width=True):
                        payload={'action':'update_user','id':u['id'],'username':u['username'],'password_hash':shash(pw) if pw else u['password_hash'],'full_name':fn,'role':role,'department':dep,'position':pos,'active':active};r=api_post(payload);st.success('Đã lưu.') if r.get('ok') else st.error(r.get('error','Lỗi'));st.rerun() if r.get('ok') else None
    with t2:
        if ud.empty: st.info('Chưa có nhân viên.')
        else:
            emp=ud[ud.role=='employee'];opt={f"{r.full_name} ({r.username})":r.username for _,r in emp.iterrows()};lab=st.selectbox('Nhân viên',list(opt.keys()));un=opt[lab];d=st.date_input('Ngày',date.today());cur=att_one(un,d.isoformat())
            with st.form('adminatt'):
                x,y=st.columns(2);ci=x.text_input('Giờ vào',(cur or {}).get('check_in',''));co=x.text_input('Giờ ra',(cur or {}).get('check_out',''));sts=['Đi làm','Nghỉ phép','Nghỉ','Đi trễ','Về sớm','WFH'];status=y.selectbox('Trạng thái',sts,index=sts.index(cur['status']) if cur and cur.get('status') in sts else 0);note=y.text_input('Ghi chú',(cur or {}).get('note',''));a,b=st.columns(2);sv=a.form_submit_button('Lưu',use_container_width=True);rm=b.form_submit_button('Xóa',use_container_width=True)
                if sv and save_att(un,d.isoformat(),ci,co,status,note):st.success('Đã lưu.');st.rerun()
                if rm and delete_att(un,d.isoformat()):st.success('Đã xóa.');st.rerun()
    with t3:
        y=st.number_input('Năm',2020,2100,date.today().year,key='ty');m=st.selectbox('Tháng',range(1,13),date.today().month-1,key='tm');empopt=['Tất cả']+(ud[ud.role=='employee'].username.tolist() if not ud.empty else []);who=st.selectbox('Nhân viên',empopt);df=get_att_df();
        if not df.empty:
            mask=df.work_date.astype(str).str.startswith(f'{int(y):04d}-{int(m):02d}-');
            if who!='Tất cả':mask &= df.username.astype(str)==who
            show=df[mask].copy()
            if not show.empty:
                show=show.merge(ud[['username','full_name','department','position']],on='username',how='left').rename(columns={'username':'Tài khoản','full_name':'Họ tên','department':'Bộ phận','position':'Chức vụ','work_date':'Ngày','check_in':'Giờ vào','check_out':'Giờ ra','status':'Trạng thái','note':'Ghi chú'});st.dataframe(show,use_container_width=True,hide_index=True);o=io.BytesIO();
                with pd.ExcelWriter(o,engine='openpyxl') as w:show.to_excel(w,index=False,sheet_name='BangCong')
                o.seek(0);st.download_button('⬇️ Xuất Excel',o.getvalue(),file_name=f'Bang_cong_{int(m):02d}_{int(y)}.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
            else:st.info('Chưa có dữ liệu.')
        else:st.info('Chưa có dữ liệu.')
    with t4:
        emp=ud[ud.role=='employee'] if not ud.empty else pd.DataFrame();
        if emp.empty:st.info('Chưa có nhân viên.')
        else:
            opt={f"{r.full_name} ({r.username})":r.username for _,r in emp.iterrows()};lab=st.selectbox('Nhân viên',list(opt.keys()),key='a4e');un=opt[lab];y=st.number_input('Năm xuất',2020,2100,date.today().year,key='a4y');m=st.selectbox('Tháng xuất',range(1,13),date.today().month-1,key='a4m');
            if st.button('🖼️ Tạo ảnh A4',use_container_width=True):st.session_state.a4=make_a4(un,int(y),int(m))
            if st.session_state.get('a4'):st.image(st.session_state.a4,use_container_width=True);st.download_button('⬇️ Tải ảnh A4',st.session_state.a4,file_name=f'Bang_cong_{un}_{int(m):02d}_{int(y)}.png',mime='image/png',use_container_width=True)
