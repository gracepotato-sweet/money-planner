import os
from datetime import date, datetime
from calendar import monthrange
from functools import wraps
from flask import Flask, request, redirect, url_for, session, flash, render_template_string
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, func
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'development-only-change-this-key')
url = os.getenv('DATABASE_URL', 'sqlite:///moneyplanner.db')
if url.startswith('postgres://'): url = url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('RENDER') == 'true'
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    kind = db.Column(db.String(10), nullable=False)
    __table_args__ = (UniqueConstraint('user_id','name','kind'),)
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    kind = db.Column(db.String(10), nullable=False)
    amount = db.Column(db.Numeric(12,2), nullable=False)
    day = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(255), default='')
class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    amount = db.Column(db.Numeric(12,2), nullable=False)
    start = db.Column(db.Date, nullable=False)
    end = db.Column(db.Date, nullable=False)
class Comparison(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)
class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    comparison_id = db.Column(db.Integer, db.ForeignKey('comparison.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    price = db.Column(db.Numeric(12,2), nullable=False)
    qty = db.Column(db.Numeric(12,2), nullable=False)
    unit = db.Column(db.String(20), nullable=False)

with app.app_context(): db.create_all()

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get('uid'): return redirect(url_for('auth'))
        return fn(*a, **kw)
    return wrapper

def owned(model, item_id):
    return model.query.filter_by(id=item_id, user_id=session['uid']).first_or_404()

def categories(kind=None):
    q=Category.query.filter_by(user_id=session['uid'])
    if kind: q=q.filter_by(kind=kind)
    return q.order_by(Category.name).all()

def num(field):
    v=float(request.form.get(field, '0'))
    if not 0 < v <= 1e10: raise ValueError('จำนวนเงิน/ปริมาณต้องมากกว่า 0')
    return v

def day(field): return date.fromisoformat(request.form[field])

def start_end():
    today=date.today()
    return today.replace(day=1),today.replace(day=monthrange(today.year,today.month)[1])

@app.route('/auth', methods=['GET','POST'])
def auth():
    if request.method=='POST':
        username=request.form.get('username','').strip().lower()
        password=request.form.get('password','')
        user=User.query.filter_by(username=username).first()
        if request.form.get('mode')=='register':
            if len(username)<3 or len(password)<8: flash('ชื่อผู้ใช้อย่างน้อย 3 ตัว และรหัสผ่านอย่างน้อย 8 ตัว')
            elif user: flash('ชื่อผู้ใช้นี้ถูกใช้แล้ว')
            else:
                user=User(username=username,password_hash=generate_password_hash(password)); db.session.add(user); db.session.flush()
                for name,kind in [('อาหาร','expense'),('เดินทาง','expense'),('ของใช้','expense'),('ที่พัก','expense'),('บันเทิง','expense'),('อื่น ๆ','expense'),('เงินเดือน','income'),('รายได้พิเศษ','income'),('อื่น ๆ','income')]:
                    db.session.add(Category(user_id=user.id,name=name,kind=kind))
                db.session.commit(); session.clear(); session['uid']=user.id; return redirect('/')
        elif user and check_password_hash(user.password_hash,password):
            session.clear(); session['uid']=user.id; return redirect('/')
        else: flash('ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง')
    return render_template_string(AUTH)

@app.route('/logout', methods=['POST'])
def logout(): session.clear(); return redirect('/auth')

@app.route('/')
@login_required
def home():
    first,last=start_end()
    page=request.args.get('page','home')
    if page not in ('home','transactions','budgets','categories','compare','reports'): page='home'
    transactions=Transaction.query.filter_by(user_id=session['uid']).order_by(Transaction.day.desc(),Transaction.id.desc()).all()
    cats=categories(); catmap={c.id:c for c in cats}
    month=[t for t in transactions if first<=t.day<=last]
    income=sum(float(t.amount) for t in month if t.kind=='income')
    expense=sum(float(t.amount) for t in month if t.kind=='expense')
    budgets=Budget.query.filter_by(user_id=session['uid']).order_by(Budget.start.desc()).all()
    budget_data=[]
    for b in budgets:
        spent=sum(float(t.amount) for t in transactions if t.kind=='expense' and b.start<=t.day<=b.end and (b.category_id is None or b.category_id==t.category_id))
        budget_data.append(dict(obj=b,spent=spent,remaining=float(b.amount)-spent,pct=spent/float(b.amount)*100,name=catmap[b.category_id].name if b.category_id in catmap else 'รวมทุกหมวด'))
    comparisons=Comparison.query.filter_by(user_id=session['uid']).order_by(Comparison.created.desc()).all()
    itemmap={c.id:Item.query.filter_by(comparison_id=c.id).all() for c in comparisons}
    return render_template_string(UI,page=page,first=first,last=last,transactions=transactions,cats=cats,catmap=catmap,income=income,expense=expense,budgets=budget_data,comparisons=comparisons,itemmap=itemmap,username=User.query.get(session['uid']).username)

@app.route('/save/<what>',methods=['POST'])
@login_required
def save(what):
    try:
        uid=session['uid']; ident=request.form.get('id'); obj=None
        if what=='transaction':
            obj=owned(Transaction,int(ident)) if ident else Transaction(user_id=uid)
            c=owned(Category,int(request.form['category_id']))
            obj.category_id=c.id; obj.kind=c.kind; obj.amount=num('amount'); obj.day=day('day'); obj.note=request.form.get('note','')[:255]
        elif what=='category':
            obj=owned(Category,int(ident)) if ident else Category(user_id=uid)
            obj.name=request.form['name'].strip()[:100]; obj.kind=request.form['kind']
            if obj.kind not in ('income','expense') or not obj.name: raise ValueError('กรอกหมวดหมู่ให้ถูกต้อง')
            if ident and Transaction.query.filter_by(user_id=uid,category_id=obj.id).first() and obj.kind!=Category.query.get(obj.id).kind: raise ValueError('ไม่สามารถเปลี่ยนประเภทหมวดหมู่ที่มีรายการอยู่')
        elif what=='budget':
            obj=owned(Budget,int(ident)) if ident else Budget(user_id=uid)
            cid=request.form.get('category_id')
            if cid:
                c=owned(Category,int(cid))
                if c.kind!='expense': raise ValueError('งบต้องเป็นหมวดรายจ่าย')
                obj.category_id=c.id
            else: obj.category_id=None
            obj.amount=num('amount'); obj.start=day('start'); obj.end=day('end')
            if obj.end<obj.start: raise ValueError('วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่ม')
        elif what=='comparison':
            obj=Comparison(user_id=uid); db.session.add(obj); db.session.flush()
            names=request.form.getlist('name'); prices=request.form.getlist('price'); qtys=request.form.getlist('qty'); units=request.form.getlist('unit')
            if len(names)<2 or len(names)>12: raise ValueError('ต้องมีสินค้า 2–12 รายการ')
            for n,p,q,u in zip(names,prices,qtys,units):
                if u not in ('g','kg','ml','L','ชิ้น','ฟอง','ขวด','แพ็ค','ห่อ','กล่อง'): raise ValueError('หน่วยสินค้าไม่ถูกต้อง')
                if not n.strip() or float(p)<=0 or float(q)<=0: raise ValueError('กรอกข้อมูลสินค้าให้ครบ')
                db.session.add(Item(comparison_id=obj.id,name=n.strip()[:150],price=float(p),qty=float(q),unit=u))
        else: raise ValueError('ไม่รู้จักรายการ')
        if what!='comparison': db.session.add(obj)
        db.session.commit(); flash('บันทึกเรียบร้อย')
    except Exception as e:
        db.session.rollback(); flash('ไม่สามารถบันทึกได้: '+str(e))
    return redirect('/?page='+{'transaction':'transactions','category':'categories','budget':'budgets','comparison':'compare'}.get(what,'home'))

@app.route('/delete/<what>/<int:ident>',methods=['POST'])
@login_required
def delete(what,ident):
    models={'transaction':Transaction,'category':Category,'budget':Budget,'comparison':Comparison}
    if what not in models: return redirect('/')
    obj=owned(models[what],ident)
    if what=='category' and (Transaction.query.filter_by(user_id=session['uid'],category_id=ident).first() or Budget.query.filter_by(user_id=session['uid'],category_id=ident).first()): flash('หมวดหมู่นี้มีรายการใช้งานอยู่ ลบไม่ได้')
    else:
        if what=='comparison': Item.query.filter_by(comparison_id=ident).delete()
        db.session.delete(obj); db.session.commit(); flash('ลบเรียบร้อย')
    return redirect('/?page='+{'transaction':'transactions','category':'categories','budget':'budgets','comparison':'compare'}[what])

AUTH='''<!doctype html><html lang="th"><meta name="google-site-verification" content="v6bSqACGIo0PYFkabWQMR20DZvlickzEzzLmi5bRkSs" /><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Money Planner</title><style>body{margin:0;font-family:system-ui,sans-serif;background:#f8f9fa;color:#2b2d42;display:grid;place-items:center;min-height:100vh}.box{background:white;border-radius:25px;padding:35px;width:min(360px,85vw);box-shadow:0 12px 40px #1c47341a}h1{color:#2d6a4f}input,button{box-sizing:border-box;width:100%;padding:14px;margin:8px 0;border-radius:12px;border:1px solid #ddd;font:inherit}button{background:#2d6a4f;color:white;border:0;font-weight:700;cursor:pointer}a{color:#2d6a4f}.msg{color:#d34b4b}</style><div class="box"><h1>Money Planner</h1><p>จัดการเงินของคุณได้ง่ายขึ้น</p>{% for m in get_flashed_messages() %}<p class="msg">{{m}}</p>{% endfor %}<form method="post"><input name="username" placeholder="ชื่อผู้ใช้" required minlength="3"><input name="password" type="password" placeholder="รหัสผ่าน (อย่างน้อย 8 ตัวสำหรับสมัคร)" required><input type="hidden" name="mode" id="mode" value="login"><button id="submit">เข้าสู่ระบบ</button></form><p><a href="#" onclick="event.preventDefault();let x=document.getElementById('mode'),b=document.getElementById('submit');x.value=x.value==='login'?'register':'login';b.textContent=x.value==='login'?'เข้าสู่ระบบ':'สมัครสมาชิก';this.textContent=x.value==='login'?'ยังไม่มีบัญชี? สมัครสมาชิก':'มีบัญชีแล้ว? เข้าสู่ระบบ'">ยังไม่มีบัญชี? สมัครสมาชิก</a></p></div></html>'''

UI='''<!doctype html><html lang="th"><head><meta name="google-site-verification" content="v6bSqACGIo0PYFkabWQMR20DZvlickzEzzLmi5bRkSs" /><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#2D6A4F"><title>Money Planner</title><style>
:root{--green:#2d6a4f;--mint:#52b788;--bg:#f8f9fa;--text:#2b2d42;--red:#ff6b6b;--blue:#4d96ff}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,'Segoe UI',sans-serif}a{text-decoration:none;color:inherit}.layout{max-width:1200px;margin:auto;display:grid;grid-template-columns:230px 1fr;min-height:100vh}.side{background:white;padding:25px 16px;border-right:1px solid #e9ecef}.brand{font-size:24px;font-weight:800;color:var(--green);padding:10px}.nav{display:block;padding:13px 15px;border-radius:13px;margin:5px 0}.nav.active{background:#e3f4eb;color:var(--green);font-weight:700}.main{padding:28px;min-width:0}h1{font-size:28px;margin:0 0 8px}h2{font-size:19px;margin:26px 0 14px}p.muted,small{color:#818793}.card{background:white;border-radius:20px;padding:20px;box-shadow:0 3px 20px #253d3010;margin-bottom:16px}.balance{background:linear-gradient(120deg,#2d6a4f,#52b788);color:white}.balance small{color:#e0f4e8}.amount{font-size:35px;font-weight:800;margin:10px 0}.stats{display:flex;justify-content:space-between;gap:14px}.stats>div{flex:1}.money{font-size:20px;font-weight:700}.green{color:#2b9348}.red{color:#ff6b6b}.bar{height:9px;background:#e9ecef;border-radius:20px;overflow:hidden;margin:12px 0}.fill{height:100%;background:#52b788;border-radius:20px}.warn{background:#f0b44c}.over{background:#ff6b6b}.flex{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.rowline{padding:14px 0;border-bottom:1px solid #f0f0f0}.rowline:last-child{border:0}button,.btn{border:0;background:var(--green);color:white;padding:11px 16px;border-radius:12px;cursor:pointer;font:inherit;font-weight:600;display:inline-block}.btn.blue{background:var(--blue)}button.danger{background:#ffe9e9;color:#c43e3e}.tiny{padding:7px 10px;font-size:12px}input,select{width:100%;padding:12px;border:1px solid #e0e5e5;border-radius:11px;background:white;font:inherit;min-width:0}label{display:block;font-size:13px;font-weight:600;margin:8px 0}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.fields .full{grid-column:1/-1}.pill{display:inline-block;border-radius:20px;padding:5px 10px;background:#e6f6eb;color:var(--green);font-size:12px}.alert{background:#fff2df;padding:13px;border-radius:12px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left}th,td{padding:12px;border-bottom:1px solid #edf0ef;white-space:nowrap}th{font-size:12px;color:#7d8589}.bottom{display:none}.desktop-only{display:block}@media(max-width:750px){.layout{display:block}.side{display:none}.main{padding:20px 15px 95px}.grid{grid-template-columns:1fr}.bottom{position:fixed;bottom:0;left:0;right:0;display:flex;background:white;box-shadow:0 -4px 20px #0001;justify-content:space-around;padding:9px 2px max(9px,env(safe-area-inset-bottom));z-index:5}.bottom a{font-size:11px;text-align:center;color:#52625a;flex:1}.bottom a span{display:block;font-size:21px}.amount{font-size:31px}.fields{grid-template-columns:1fr}.stats{gap:8px}.money{font-size:17px}}
</style></head><body><div class="layout"><aside class="side"><div class="brand">Money Planner</div><p class="muted" style="padding-left:15px">สวัสดี {{username}}</p>{% for key,label,ico in [('home','ภาพรวม','⌂'),('transactions','รายรับ–รายจ่าย','⇄'),('budgets','งบประมาณ','▤'),('categories','หมวดหมู่','◫'),('compare','เปรียบเทียบสินค้า','⚖'),('reports','รายงาน','▥')] %}<a class="nav {{'active' if page==key else ''}}" href="/?page={{key}}">{{ico}} &nbsp;{{label}}</a>{% endfor %}<form action="/logout" method="post"><button style="background:#edf5f0;color:#2d6a4f;width:100%;margin-top:20px">ออกจากระบบ</button></form></aside><main class="main">
{% for m in get_flashed_messages() %}<div class="alert">{{m}}</div>{% endfor %}
{% if page=='home' %}<h1>ภาพรวมการเงิน</h1><p class="muted">ประจำเดือน {{first.strftime('%m/%Y')}}</p><div class="card balance"><small>ยอดเงินคงเหลือสุทธิของเดือน</small><div class="amount">฿{{'%.2f'|format(income-expense)}}</div><div class="stats"><div><small>↓ รายรับ</small><div class="money">฿{{'%.2f'|format(income)}}</div></div><div><small>↑ รายจ่าย</small><div class="money">฿{{'%.2f'|format(expense)}}</div></div></div></div><div class="flex"><h2>รายการล่าสุด</h2><a class="btn" href="/?page=transactions">+ เพิ่มรายการ</a></div><div class="card">{% for t in transactions[:8] %}<div class="flex rowline"><div><b>{{catmap[t.category_id].name}}</b><br><small>{{t.day}} · {{t.note}}</small></div><b class="{{'green' if t.kind=='income' else 'red'}}">{{'+' if t.kind=='income' else '-'}}฿{{'%.2f'|format(t.amount)}}</b></div>{% else %}<p class="muted">ยังไม่มีรายการ เริ่มบันทึกรายรับหรือรายจ่ายได้เลย</p>{% endfor %}</div><h2>สถานะงบประมาณ</h2>{% for b in budgets if b.obj.start<=last and b.obj.end>=first %}<div class="card"><div class="flex"><b>{{b.name}}</b><span>฿{{'%.2f'|format(b.spent)}} / ฿{{b.obj.amount}}</span></div><div class="bar"><div class="fill {{'over' if b.pct>100 else 'warn' if b.pct>=80 else ''}}" style="width:{{[b.pct,100]|min}}%"></div></div><small>{{'เกินงบ' if b.pct>100 else 'ใกล้ถึงงบ' if b.pct>=80 else 'ปกติ'}} · คงเหลือ ฿{{'%.2f'|format(b.remaining)}}</small></div>{% endfor %}
{% elif page=='transactions' %}<h1>รายรับ–รายจ่าย</h1><p class="muted">บันทึกและติดตามเงินของคุณ</p><div class="card"><h2>เพิ่มรายการ</h2><form method="post" action="/save/transaction" class="fields"><div><label>หมวดหมู่</label><select name="category_id" required>{% for c in cats %}<option value="{{c.id}}">{{'รายรับ' if c.kind=='income' else 'รายจ่าย'}} · {{c.name}}</option>{% endfor %}</select></div><div><label>จำนวนเงิน (บาท)</label><input name="amount" type="number" min="0.01" step="0.01" required></div><div><label>วันที่</label><input name="day" type="date" value="{{last if last<=first else first}}" required id="txdate"></div><div><label>หมายเหตุ</label><input name="note" maxlength="255"></div><div class="full"><button>บันทึกรายการ</button></div></form></div><div class="card scroll"><table><tr><th>วันที่</th><th>หมวดหมู่</th><th>หมายเหตุ</th><th>จำนวน</th><th>จัดการ</th></tr>{% for t in transactions %}<tr><td>{{t.day}}</td><td>{{catmap[t.category_id].name}}</td><td>{{t.note}}</td><td class="{{'green' if t.kind=='income' else 'red'}}">{{'+' if t.kind=='income' else '-'}}{{t.amount}}</td><td><button class="tiny" onclick="editTx({{t.id}},{{t.category_id}},{{t.amount}},'{{t.day}}',{{t.note|tojson}})">แก้ไข</button> <form style="display:inline" method="post" action="/delete/transaction/{{t.id}}" onsubmit="return confirm('ยืนยันการลบ?')"><button class="danger tiny">ลบ</button></form></td></tr>{% endfor %}</table></div>
{% elif page=='categories' %}<h1>หมวดหมู่</h1><div class="card"><h2>เพิ่ม / แก้ไขหมวดหมู่</h2><form method="post" action="/save/category" class="fields" id="catForm"><input type="hidden" name="id"><div><label>ชื่อหมวดหมู่</label><input name="name" required></div><div><label>ประเภท</label><select name="kind"><option value="expense">รายจ่าย</option><option value="income">รายรับ</option></select></div><div class="full"><button>บันทึก</button> <button type="button" style="background:#e9ecef;color:#333" onclick="document.getElementById('catForm').reset();document.querySelector('#catForm [name=id]').value=''">ล้างค่า</button></div></form></div><div class="card">{% for c in cats %}<div class="flex rowline"><div><b>{{c.name}}</b> <small>{{'รายรับ' if c.kind=='income' else 'รายจ่าย'}}</small></div><div><button class="tiny" onclick="editCat({{c.id}},{{c.name|tojson}},{{c.kind|tojson}})">แก้ไข</button> <form method="post" action="/delete/category/{{c.id}}" style="display:inline" onsubmit="return confirm('ยืนยันการลบ?')"><button class="danger tiny">ลบ</button></form></div></div>{% endfor %}</div>
{% elif page=='budgets' %}<h1>งบประมาณ</h1><p class="muted">กำหนดวงเงินและติดตามยอดใช้จ่าย</p><div class="card"><h2>กำหนดงบประมาณ</h2><form method="post" action="/save/budget" class="fields" id="budgetForm"><input type="hidden" name="id"><div><label>หมวดหมู่</label><select name="category_id"><option value="">งบรวมทุกหมวด</option>{% for c in cats if c.kind=='expense' %}<option value="{{c.id}}">{{c.name}}</option>{% endfor %}</select></div><div><label>งบ (บาท)</label><input name="amount" type="number" step="0.01" min="0.01" required></div><div><label>เริ่ม</label><input name="start" type="date" value="{{first}}" required></div><div><label>สิ้นสุด</label><input name="end" type="date" value="{{last}}" required></div><div class="full"><button>บันทึกงบ</button></div></form></div>{% for b in budgets %}<div class="card"><div class="flex"><b>{{b.name}}</b><b>฿{{b.obj.amount}}</b></div><small>{{b.obj.start}} ถึง {{b.obj.end}}</small><div class="bar"><div class="fill {{'over' if b.pct>100 else 'warn' if b.pct>=80 else ''}}" style="width:{{[b.pct,100]|min}}%"></div></div><div class="flex"><small>ใช้แล้ว ฿{{'%.2f'|format(b.spent)}} · คงเหลือ ฿{{'%.2f'|format(b.remaining)}}</small><span class="pill">{{'เกินงบ' if b.pct>100 else 'ใกล้ถึงงบ' if b.pct>=80 else 'ปกติ'}}</span></div><div style="margin-top:12px"><button class="tiny" onclick="editBudget({{b.obj.id}},{{b.obj.category_id or 'null'}},{{b.obj.amount}},'{{b.obj.start}}','{{b.obj.end}}')">แก้ไข</button> <form style="display:inline" action="/delete/budget/{{b.obj.id}}" method="post" onsubmit="return confirm('ยืนยันการลบ?')"><button class="danger tiny">ลบ</button></form></div></div>{% endfor %}
{% elif page=='compare' %}<h1>เปรียบเทียบสินค้า</h1><p class="muted">เทียบราคาต่อหน่วย เพื่อเลือกสินค้าที่คุ้มค่ากว่า</p><div class="card"><form action="/save/comparison" method="post"><div id="items"><div class="fields product"><div><label>ชื่อสินค้า A</label><input name="name" required></div><div><label>ราคา (บาท)</label><input name="price" type="number" min="0.01" step="0.01" required></div><div><label>ปริมาณ</label><input name="qty" type="number" min="0.01" step="0.01" required></div><div><label>หน่วย</label><select name="unit">{% for u in ['g','kg','ml','L','ชิ้น','ฟอง','ขวด','แพ็ค','ห่อ','กล่อง'] %}<option>{{u}}</option>{% endfor %}</select></div></div><hr><div class="fields product"><div><label>ชื่อสินค้า B</label><input name="name" required></div><div><label>ราคา (บาท)</label><input name="price" type="number" min="0.01" step="0.01" required></div><div><label>ปริมาณ</label><input name="qty" type="number" min="0.01" step="0.01" required></div><div><label>หน่วย</label><select name="unit">{% for u in ['g','kg','ml','L','ชิ้น','ฟอง','ขวด','แพ็ค','ห่อ','กล่อง'] %}<option>{{u}}</option>{% endfor %}</select></div></div></div><div class="flex" style="margin-top:15px"><button type="button" class="blue" onclick="addItem()">+ เพิ่มสินค้า</button><button>บันทึกและเปรียบเทียบ</button></div></form></div><h2>ประวัติการเปรียบเทียบ</h2>{% for c in comparisons %}<div class="card"><div class="flex"><b>เปรียบเทียบ #{{c.id}}</b><small>{{c.created.strftime('%d/%m/%Y %H:%M')}}</small></div>{% set ns=namespace(groups={}) %}{% for i in itemmap[c.id] %}{% set grp='น้ำหนัก' if i.unit in ['g','kg'] else 'ปริมาตร' if i.unit in ['ml','L'] else i.unit %}{% set base=(i.qty|float)*(1000 if i.unit in ['kg','L'] else 1) %}{% set rate=(i.price|float)/base %}{% if grp not in ns.groups or rate<ns.groups[grp] %}{% set _=ns.groups.update({grp:rate}) %}{% endif %}{% endfor %}{% for i in itemmap[c.id] %}{% set grp='น้ำหนัก' if i.unit in ['g','kg'] else 'ปริมาตร' if i.unit in ['ml','L'] else i.unit %}{% set rate=(i.price|float)/((i.qty|float)*(1000 if i.unit in ['kg','L'] else 1)) %}<div class="flex rowline"><div><b>{{i.name}}</b> <small>฿{{i.price}} / {{i.qty}} {{i.unit}}</small></div><div><b>฿{{'%.2f'|format(rate*(100 if grp in ['น้ำหนัก','ปริมาตร'] else 1))}}</b><small> / {{'100 g' if grp=='น้ำหนัก' else '100 ml' if grp=='ปริมาตร' else '1 '+grp}}</small>{% if rate==ns.groups[grp] %} <span class="pill">คุ้มสุดในกลุ่ม</span>{% endif %}</div></div>{% endfor %}<form method="post" action="/delete/comparison/{{c.id}}" onsubmit="return confirm('ลบประวัตินี้?')"><button class="danger tiny">ลบประวัติ</button></form></div>{% else %}<p class="muted">ยังไม่มีประวัติเปรียบเทียบ</p>{% endfor %}
{% elif page=='reports' %}<h1>รายงานสรุป</h1><p class="muted">รายรับและรายจ่ายประจำเดือน {{first.strftime('%m/%Y')}}</p><div class="grid"><div class="card"><small>รายรับ</small><div class="money green">฿{{'%.2f'|format(income)}}</div></div><div class="card"><small>รายจ่าย</small><div class="money red">฿{{'%.2f'|format(expense)}}</div></div></div><div class="card"><h2>ยอดสุทธิ</h2><div class="amount">฿{{'%.2f'|format(income-expense)}}</div></div><div class="card"><h2>ค่าใช้จ่ายแยกหมวดหมู่</h2>{% for c in cats if c.kind=='expense' %}{% set total=namespace(v=0) %}{% for t in transactions if t.category_id==c.id and first<=t.day<=last %}{% set total.v=total.v+(t.amount|float) %}{% endfor %}{% if total.v>0 %}<div class="flex"><span>{{c.name}}</span><b>฿{{'%.2f'|format(total.v)}}</b></div><div class="bar"><div class="fill" style="width:{{(total.v/expense*100) if expense else 0}}%"></div></div>{% endif %}{% endfor %}</div>{% endif %}
</main></div><nav class="bottom">{% for key,label,ico in [('home','ภาพรวม','⌂'),('transactions','รายการ','⇄'),('budgets','งบ','▤'),('compare','เปรียบเทียบ','⚖'),('categories','หมวดหมู่','◫'),('reports','รายงาน','▥')] %}<a href="/?page={{key}}" style="{{'color:#2d6a4f;font-weight:800' if page==key else ''}}"><span>{{ico}}</span>{{label}}</a>{% endfor %}</nav><script>
const tx=document.getElementById('txdate');if(tx)tx.value=new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10);
function editTx(id,cat,amount,day,note){let f=document.querySelector('form[action="/save/transaction"]');f.insertAdjacentHTML('afterbegin','<input type="hidden" name="id" value="'+id+'">');f.category_id.value=cat;f.amount.value=amount;f.day.value=day;f.note.value=note;f.scrollIntoView({behavior:'smooth'})}
function editCat(id,name,kind){let f=document.getElementById('catForm');f.querySelector('[name=id]').value=id;f.querySelector('[name=name]').value=name;f.querySelector('[name=kind]').value=kind;f.scrollIntoView({behavior:'smooth'})}
function editBudget(id,cat,amount,start,end){let f=document.getElementById('budgetForm');f.querySelector('[name=id]').value=id;f.querySelector('[name=category_id]').value=cat||'';f.querySelector('[name=amount]').value=amount;f.querySelector('[name=start]').value=start;f.querySelector('[name=end]').value=end;f.scrollIntoView({behavior:'smooth'})}
function addItem(){let root=document.getElementById('items');if(root.querySelectorAll('.product').length>=12)return alert('เพิ่มได้สูงสุด 12 รายการ');let el=root.querySelector('.product').cloneNode(true);el.querySelectorAll('input').forEach(x=>x.value='');el.querySelector('label').textContent='ชื่อสินค้าเพิ่ม';root.append(document.createElement('hr'),el)}
</script></body></html>'''

if __name__=='__main__': app.run(debug=True)
