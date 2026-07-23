import os
from datetime import datetime, date, timedelta
from functools import wraps
from io import BytesIO

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, Column, Integer, String, Float, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# CONEXÃO COM O BANCO DE DADOS
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'sistema.db')}")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
Session = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave-por-uma-secreta-e-aleatoria")

FORNECEDORES = ["texpharma", "leticia"]
FORNECEDOR_LABEL = {"texpharma": "Texpharma", "leticia": "Letícia"}


# ---------------------------------------------------------------------------
# MODELOS (TABELAS)
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="admin")
    # roles: admin | texpharma (só visualiza logística) | funcionario (visualiza + lança logística)


class CmConfig(Base):
    __tablename__ = "cm_config"
    id = Column(Integer, primary_key=True)
    cm = Column(Integer, nullable=False)
    fornecedor = Column(String(20), nullable=False, default="texpharma")
    sacos_por_fardo = Column(Integer, nullable=False, default=0)
    valor_pacote = Column(Float, nullable=False, default=0.15)
    valor_fardo = Column(Float, nullable=False, default=0)


class Entrada(Base):
    __tablename__ = "entradas"
    id = Column(Integer, primary_key=True)
    data = Column(String(10), nullable=False)
    cm = Column(Integer, nullable=False)
    fornecedor = Column(String(20), nullable=False, default="texpharma")
    qtd_fardos = Column(Integer, nullable=False)
    obs = Column(String(255))


class Saida(Base):
    __tablename__ = "saidas"
    id = Column(Integer, primary_key=True)
    data = Column(String(10), nullable=False)
    cm = Column(Integer, nullable=False)
    fornecedor = Column(String(20), nullable=False, default="texpharma")
    qtd_fardos = Column(Integer, nullable=False)
    obs = Column(String(255))


class Despesa(Base):
    __tablename__ = "despesas"
    id = Column(Integer, primary_key=True)
    data = Column(String(10), nullable=False)
    descricao = Column(String(255), nullable=False)
    valor = Column(Float, nullable=False)


# ---------------------------------------------------------------------------
# MIGRAÇÃO AUTOMÁTICA (para bancos já existentes, criados antes destas mudanças)
# ---------------------------------------------------------------------------
def run_migrations():
    insp = inspect(engine)
    with engine.begin() as conn:
        if insp.has_table("users"):
            cols = [c["name"] for c in insp.get_columns("users")]
            if "role" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'admin'"))

        if insp.has_table("cm_config"):
            cols = [c["name"] for c in insp.get_columns("cm_config")]
            if "fornecedor" not in cols:
                # schema antigo (sem fornecedor/id) — a tabela é só configuração de preço,
                # fácil de reconfigurar, então recriamos do zero com o schema novo.
                conn.execute(text("DROP TABLE cm_config"))

        if insp.has_table("entradas"):
            cols = [c["name"] for c in insp.get_columns("entradas")]
            if "fornecedor" not in cols:
                conn.execute(text("ALTER TABLE entradas ADD COLUMN fornecedor VARCHAR(20) DEFAULT 'texpharma'"))

        if insp.has_table("saidas"):
            cols = [c["name"] for c in insp.get_columns("saidas")]
            if "fornecedor" not in cols:
                conn.execute(text("ALTER TABLE saidas ADD COLUMN fornecedor VARCHAR(20) DEFAULT 'texpharma'"))


def init_db():
    run_migrations()
    Base.metadata.create_all(engine)
    db = Session()

    seed_users = [
        ("gansotrue", "130502", "admin"),
        ("texpharma", "tex123", "texpharma"),
        ("funcionario", "fun123", "funcionario"),
    ]
    for username, pwd, role in seed_users:
        existing = db.query(User).filter_by(username=username).first()
        if not existing:
            db.add(User(username=username, password_hash=generate_password_hash(pwd), role=role))
        elif not existing.role:
            existing.role = role

    # Configurações padrão por fornecedor
    defaults_texpharma = [(6, 0, 0.15), (8, 0, 0.15), (10, 125, 0.15), (15, 72, 0.15), (20, 54, 0.15)]
    defaults_leticia = [(6, 0, 0.15), (8, 0, 0.15), (10, 0, 0.15), (15, 0, 0.15), (20, 0, 0.15)]

    for cm, sacos, valor_pacote in defaults_texpharma:
        if not db.query(CmConfig).filter_by(cm=cm, fornecedor="texpharma").first():
            db.add(CmConfig(cm=cm, fornecedor="texpharma", sacos_por_fardo=sacos,
                             valor_pacote=valor_pacote, valor_fardo=round(sacos * valor_pacote, 2)))

    for cm, sacos, valor_pacote in defaults_leticia:
        if not db.query(CmConfig).filter_by(cm=cm, fornecedor="leticia").first():
            db.add(CmConfig(cm=cm, fornecedor="leticia", sacos_por_fardo=sacos,
                             valor_pacote=valor_pacote, valor_fardo=round(sacos * valor_pacote, 2)))

    db.commit()
    db.close()


@app.teardown_appcontext
def remove_session(exception=None):
    Session.remove()


# ---------------------------------------------------------------------------
# AUTENTICAÇÃO E PERMISSÕES
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    """Só permite acesso a quem estiver com um dos papéis (roles) informados."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("Você não tem permissão para acessar essa área.", "error")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def is_admin():
    return session.get("role") == "admin"


def pode_lancar():
    """Admin e funcionário podem adicionar entradas/saídas; texpharma só visualiza."""
    return session.get("role") in ("admin", "funcionario")


app.jinja_env.globals["is_admin"] = is_admin
app.jinja_env.globals["pode_lancar"] = pode_lancar
app.jinja_env.globals["FORNECEDOR_LABEL"] = FORNECEDOR_LABEL


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = Session()
        user = db.query(User).filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role
            return redirect(url_for("dashboard"))
        flash("Usuário ou senha inválidos.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/trocar-senha", methods=["GET", "POST"])
@login_required
def trocar_senha():
    if request.method == "POST":
        atual = request.form.get("senha_atual", "")
        nova = request.form.get("nova_senha", "")
        db = Session()
        user = db.query(User).get(session["user_id"])
        if user and check_password_hash(user.password_hash, atual):
            user.password_hash = generate_password_hash(nova)
            db.commit()
            flash("Senha alterada com sucesso.", "success")
        else:
            flash("Senha atual incorreta.", "error")
        return redirect(url_for("trocar_senha"))
    return render_template("trocar_senha.html")


# ---------------------------------------------------------------------------
# HELPERS DE CÁLCULO
# ---------------------------------------------------------------------------
def get_cm_config():
    db = Session()
    rows = db.query(CmConfig).order_by(CmConfig.fornecedor, CmConfig.cm).all()
    return {(row.cm, row.fornecedor): {
        "cm": row.cm, "fornecedor": row.fornecedor, "sacos_por_fardo": row.sacos_por_fardo,
        "valor_pacote": row.valor_pacote, "valor_fardo": row.valor_fardo
    } for row in rows}


def valor_fardo(cm, fornecedor, config=None):
    config = config or get_cm_config()
    c = config.get((cm, fornecedor))
    return c["valor_fardo"] if c else 0


def month_bounds(year, month):
    first = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last = next_month - timedelta(days=1)
    return first, last


def week_bounds(ref_date):
    """Retorna (segunda, domingo) da semana que contém ref_date."""
    inicio = ref_date - timedelta(days=ref_date.weekday())
    fim = inicio + timedelta(days=6)
    return inicio, fim


# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    hoje = date.today()
    ano = int(request.args.get("ano", hoje.year))
    mes = int(request.args.get("mes", hoje.month))

    primeiro_dia, ultimo_dia = month_bounds(ano, mes)
    config = get_cm_config()

    db = Session()

    saidas_mes = db.query(Saida).filter(
        Saida.data >= primeiro_dia.isoformat(), Saida.data <= ultimo_dia.isoformat()
    ).all()
    entradas_mes = db.query(Entrada).filter(
        Entrada.data >= primeiro_dia.isoformat(), Entrada.data <= ultimo_dia.isoformat()
    ).all()
    despesas_mes = db.query(Despesa).filter(
        Despesa.data >= primeiro_dia.isoformat(), Despesa.data <= ultimo_dia.isoformat()
    ).all()

    faturamento_mes = sum(row.qtd_fardos * valor_fardo(row.cm, row.fornecedor, config) for row in saidas_mes)
    total_despesas = sum(row.valor for row in despesas_mes)
    lucro_mes = faturamento_mes - total_despesas

    total_fardos_saida = sum(row.qtd_fardos for row in saidas_mes)
    total_fardos_entrada = sum(row.qtd_fardos for row in entradas_mes)

    dias_no_mes = (ultimo_dia - primeiro_dia).days + 1
    if ano == hoje.year and mes == hoje.month:
        dias_considerados = hoje.day
    else:
        dias_considerados = dias_no_mes

    media_diaria_faturamento = faturamento_mes / dias_considerados if dias_considerados else 0
    media_diaria_fardos = total_fardos_saida / dias_considerados if dias_considerados else 0
    media_semanal_faturamento = media_diaria_faturamento * 7
    media_semanal_fardos = media_diaria_fardos * 7

    dias_labels, dias_fardos_saida, dias_fardos_entrada, dias_faturamento = [], [], [], []
    cursor_dia = primeiro_dia
    saidas_por_dia, entradas_por_dia = {}, {}
    for row in saidas_mes:
        saidas_por_dia.setdefault(row.data, []).append(row)
    for row in entradas_mes:
        entradas_por_dia.setdefault(row.data, []).append(row)

    while cursor_dia <= min(ultimo_dia, hoje if (ano == hoje.year and mes == hoje.month) else ultimo_dia):
        iso = cursor_dia.isoformat()
        dias_labels.append(cursor_dia.strftime("%d/%m"))
        fardos_dia = sum(r.qtd_fardos for r in saidas_por_dia.get(iso, []))
        fat_dia = sum(r.qtd_fardos * valor_fardo(r.cm, r.fornecedor, config) for r in saidas_por_dia.get(iso, []))
        entradas_dia = sum(r.qtd_fardos for r in entradas_por_dia.get(iso, []))
        dias_fardos_saida.append(fardos_dia)
        dias_fardos_entrada.append(entradas_dia)
        dias_faturamento.append(round(fat_dia, 2))
        cursor_dia += timedelta(days=1)

    breakdown = {}
    for row in saidas_mes:
        chave = (row.cm, row.fornecedor)
        breakdown.setdefault(chave, {"fardos": 0, "faturamento": 0.0})
        breakdown[chave]["fardos"] += row.qtd_fardos
        breakdown[chave]["faturamento"] += row.qtd_fardos * valor_fardo(row.cm, row.fornecedor, config)

    breakdown_list = [
        {"cm": cm, "fornecedor": forn, "fardos": v["fardos"], "faturamento": round(v["faturamento"], 2)}
        for (cm, forn), v in sorted(breakdown.items())
    ]

    meses_nomes = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                   "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

    return render_template(
        "dashboard.html",
        ano=ano, mes=mes, mes_nome=meses_nomes[mes],
        faturamento_mes=round(faturamento_mes, 2),
        total_despesas=round(total_despesas, 2),
        lucro_mes=round(lucro_mes, 2),
        total_fardos_saida=total_fardos_saida,
        total_fardos_entrada=total_fardos_entrada,
        media_diaria_faturamento=round(media_diaria_faturamento, 2),
        media_semanal_faturamento=round(media_semanal_faturamento, 2),
        media_diaria_fardos=round(media_diaria_fardos, 1),
        media_semanal_fardos=round(media_semanal_fardos, 1),
        dias_labels=dias_labels,
        dias_fardos_saida=dias_fardos_saida,
        dias_fardos_entrada=dias_fardos_entrada,
        dias_faturamento=dias_faturamento,
        breakdown_list=breakdown_list,
        hoje=hoje,
    )


# ---------------------------------------------------------------------------
# ENTRADAS (fardos recebidos)
# ---------------------------------------------------------------------------
@app.route("/entradas", methods=["GET", "POST"])
@login_required
def entradas():
    db = Session()
    if request.method == "POST":
        if not pode_lancar():
            flash("Você não tem permissão para adicionar registros.", "error")
            return redirect(url_for("entradas"))
        data_reg = request.form.get("data") or date.today().isoformat()
        cm = int(request.form.get("cm"))
        fornecedor = request.form.get("fornecedor", "texpharma")
        qtd = int(request.form.get("qtd_fardos"))
        obs = request.form.get("obs", "")
        db.add(Entrada(data=data_reg, cm=cm, fornecedor=fornecedor, qtd_fardos=qtd, obs=obs))
        db.commit()
        flash("Entrada registrada com sucesso!", "success")
        return redirect(url_for("entradas"))

    registros = db.query(Entrada).order_by(Entrada.data.desc(), Entrada.id.desc()).limit(200).all()
    cms = sorted({r.cm for r in db.query(CmConfig).all()})
    return render_template("entradas.html", registros=registros, cms=cms, fornecedores=FORNECEDORES)


@app.route("/entradas/excluir/<int:id>", methods=["POST"])
@role_required("admin")
def excluir_entrada(id):
    db = Session()
    reg = db.query(Entrada).get(id)
    if reg:
        db.delete(reg)
        db.commit()
    flash("Registro excluído.", "success")
    return redirect(url_for("entradas"))


# ---------------------------------------------------------------------------
# SAÍDAS (fardos entregues / produzidos)
# ---------------------------------------------------------------------------
@app.route("/saidas", methods=["GET", "POST"])
@login_required
def saidas():
    db = Session()
    if request.method == "POST":
        if not pode_lancar():
            flash("Você não tem permissão para adicionar registros.", "error")
            return redirect(url_for("saidas"))
        data_reg = request.form.get("data") or date.today().isoformat()
        cm = int(request.form.get("cm"))
        fornecedor = request.form.get("fornecedor", "texpharma")
        qtd = int(request.form.get("qtd_fardos"))
        obs = request.form.get("obs", "")
        db.add(Saida(data=data_reg, cm=cm, fornecedor=fornecedor, qtd_fardos=qtd, obs=obs))
        db.commit()
        flash("Saída registrada com sucesso!", "success")
        return redirect(url_for("saidas"))

    registros = db.query(Saida).order_by(Saida.data.desc(), Saida.id.desc()).limit(200).all()
    cms = sorted({r.cm for r in db.query(CmConfig).all()})
    config_map = get_cm_config()
    return render_template("saidas.html", registros=registros, cms=cms, fornecedores=FORNECEDORES, config_map=config_map)


@app.route("/saidas/excluir/<int:id>", methods=["POST"])
@role_required("admin")
def excluir_saida(id):
    db = Session()
    reg = db.query(Saida).get(id)
    if reg:
        db.delete(reg)
        db.commit()
    flash("Registro excluído.", "success")
    return redirect(url_for("saidas"))


# ---------------------------------------------------------------------------
# DESPESAS (só admin)
# ---------------------------------------------------------------------------
@app.route("/despesas", methods=["GET", "POST"])
@role_required("admin")
def despesas():
    db = Session()
    if request.method == "POST":
        data_reg = request.form.get("data") or date.today().isoformat()
        descricao = request.form.get("descricao", "")
        valor = float(request.form.get("valor", 0))
        db.add(Despesa(data=data_reg, descricao=descricao, valor=valor))
        db.commit()
        flash("Despesa registrada.", "success")
        return redirect(url_for("despesas"))

    registros = db.query(Despesa).order_by(Despesa.data.desc(), Despesa.id.desc()).limit(200).all()
    return render_template("despesas.html", registros=registros)


@app.route("/despesas/excluir/<int:id>", methods=["POST"])
@role_required("admin")
def excluir_despesa(id):
    db = Session()
    reg = db.query(Despesa).get(id)
    if reg:
        db.delete(reg)
        db.commit()
    flash("Despesa excluída.", "success")
    return redirect(url_for("despesas"))


# ---------------------------------------------------------------------------
# CONFIGURAÇÃO DE VALORES POR ESPESSURA + FORNECEDOR (só admin)
# ---------------------------------------------------------------------------
@app.route("/configuracoes", methods=["GET", "POST"])
@role_required("admin")
def configuracoes():
    db = Session()
    if request.method == "POST":
        cfg_id = int(request.form.get("id"))
        sacos_por_fardo = int(request.form.get("sacos_por_fardo"))
        valor_pacote = float(request.form.get("valor_pacote"))
        valor_fardo_calc = round(sacos_por_fardo * valor_pacote, 2)
        cfg = db.query(CmConfig).get(cfg_id)
        if cfg:
            cfg.sacos_por_fardo = sacos_por_fardo
            cfg.valor_pacote = valor_pacote
            cfg.valor_fardo = valor_fardo_calc
            db.commit()
        flash("Configuração atualizada.", "success")
        return redirect(url_for("configuracoes"))

    novo_cm = request.args.get("novo_cm")
    novo_fornecedor = request.args.get("novo_fornecedor")
    if novo_cm and novo_fornecedor in FORNECEDORES:
        try:
            novo_cm = int(novo_cm)
            if not db.query(CmConfig).filter_by(cm=novo_cm, fornecedor=novo_fornecedor).first():
                db.add(CmConfig(cm=novo_cm, fornecedor=novo_fornecedor, sacos_por_fardo=0,
                                 valor_pacote=0.15, valor_fardo=0))
                db.commit()
        except ValueError:
            pass

    configs_texpharma = db.query(CmConfig).filter_by(fornecedor="texpharma").order_by(CmConfig.cm).all()
    configs_leticia = db.query(CmConfig).filter_by(fornecedor="leticia").order_by(CmConfig.cm).all()
    return render_template("configuracoes.html", configs_texpharma=configs_texpharma, configs_leticia=configs_leticia)


# ---------------------------------------------------------------------------
# RELATÓRIOS EM PDF (só admin)
# ---------------------------------------------------------------------------
@app.route("/relatorios")
@role_required("admin", "texpharma")
def relatorios():
    hoje = date.today()
    return render_template("relatorios.html", hoje=hoje)


def periodo_from_args(args):
    tipo_periodo = args.get("periodo", "mensal")
    hoje = date.today()
    if tipo_periodo == "semanal":
        ref = args.get("data_ref")
        ref_date = datetime.strptime(ref, "%Y-%m-%d").date() if ref else hoje
        inicio, fim = week_bounds(ref_date)
        titulo_periodo = f"Semana de {inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"
    else:
        ano = int(args.get("ano", hoje.year))
        mes = int(args.get("mes", hoje.month))
        inicio, fim = month_bounds(ano, mes)
        meses_nomes = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                       "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        titulo_periodo = f"{meses_nomes[mes]} de {ano}"
    return inicio, fim, titulo_periodo


@app.route("/relatorios/gerar")
@role_required("admin", "texpharma")
def gerar_relatorio():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    tipo_relatorio = request.args.get("tipo", "logistico")  # logistico | financeiro
    if tipo_relatorio == "financeiro" and not is_admin():
        flash("Você não tem permissão para gerar o relatório financeiro.", "error")
        return redirect(url_for("relatorios"))
    inicio, fim, titulo_periodo = periodo_from_args(request.args)

    db = Session()
    config = get_cm_config()

    entradas = db.query(Entrada).filter(
        Entrada.data >= inicio.isoformat(), Entrada.data <= fim.isoformat()
    ).order_by(Entrada.data).all()
    saidas = db.query(Saida).filter(
        Saida.data >= inicio.isoformat(), Saida.data <= fim.isoformat()
    ).order_by(Saida.data).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    titulo_style = ParagraphStyle("TituloCustom", parent=styles["Title"], alignment=TA_CENTER, fontSize=18)
    sub_style = ParagraphStyle("SubCustom", parent=styles["Normal"], alignment=TA_CENTER, fontSize=11,
                                textColor=colors.HexColor("#555555"))

    story = []
    nome_relatorio = "Resumo Logístico" if tipo_relatorio == "logistico" else "Resumo Financeiro"
    story.append(Paragraph("Embalagem de Ataduras", titulo_style))
    story.append(Paragraph(f"{nome_relatorio} — {titulo_periodo}", sub_style))
    story.append(Spacer(1, 18))

    header_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6fb")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ])

    if tipo_relatorio == "logistico":
        total_entrada = sum(r.qtd_fardos for r in entradas)
        total_saida = sum(r.qtd_fardos for r in saidas)

        resumo_data = [["Indicador", "Valor"],
                        ["Total de fardos recebidos (entrada)", str(total_entrada)],
                        ["Total de fardos entregues (saída)", str(total_saida)],
                        ["Saldo (entrada - saída)", str(total_entrada - total_saida)]]
        t = Table(resumo_data, colWidths=[10 * cm, 6 * cm])
        t.setStyle(header_style)
        story.append(t)
        story.append(Spacer(1, 18))

        # Quebra por cm + fornecedor
        story.append(Paragraph("Detalhamento por espessura e fornecedor", styles["Heading3"]))
        story.append(Spacer(1, 6))
        detalhe = {}
        for r in entradas:
            k = (r.cm, r.fornecedor)
            detalhe.setdefault(k, {"entrada": 0, "saida": 0})
            detalhe[k]["entrada"] += r.qtd_fardos
        for r in saidas:
            k = (r.cm, r.fornecedor)
            detalhe.setdefault(k, {"entrada": 0, "saida": 0})
            detalhe[k]["saida"] += r.qtd_fardos

        det_data = [["Espessura", "Fornecedor", "Entrada (fardos)", "Saída (fardos)"]]
        for (cm_v, forn), v in sorted(detalhe.items()):
            det_data.append([f"{cm_v} cm", FORNECEDOR_LABEL.get(forn, forn), str(v["entrada"]), str(v["saida"])])
        if len(det_data) == 1:
            det_data.append(["-", "-", "-", "-"])
        t2 = Table(det_data, colWidths=[4 * cm, 4 * cm, 4 * cm, 4 * cm])
        t2.setStyle(header_style)
        story.append(t2)

    else:  # financeiro
        faturamento = sum(r.qtd_fardos * valor_fardo(r.cm, r.fornecedor, config) for r in saidas)
        despesas = db.query(Despesa).filter(
            Despesa.data >= inicio.isoformat(), Despesa.data <= fim.isoformat()
        ).all()
        total_despesas = sum(d.valor for d in despesas)
        lucro = faturamento - total_despesas

        def fmt(v):
            return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        resumo_data = [["Indicador", "Valor"],
                        ["Faturamento (fardos entregues)", fmt(faturamento)],
                        ["Despesas no período", fmt(total_despesas)],
                        ["Lucro no período", fmt(lucro)]]
        t = Table(resumo_data, colWidths=[10 * cm, 6 * cm])
        t.setStyle(header_style)
        story.append(t)
        story.append(Spacer(1, 18))

        story.append(Paragraph("Detalhamento por espessura e fornecedor", styles["Heading3"]))
        story.append(Spacer(1, 6))
        detalhe = {}
        for r in saidas:
            k = (r.cm, r.fornecedor)
            detalhe.setdefault(k, {"fardos": 0, "valor": 0.0})
            detalhe[k]["fardos"] += r.qtd_fardos
            detalhe[k]["valor"] += r.qtd_fardos * valor_fardo(r.cm, r.fornecedor, config)

        det_data = [["Espessura", "Fornecedor", "Fardos entregues", "Faturamento"]]
        for (cm_v, forn), v in sorted(detalhe.items()):
            det_data.append([f"{cm_v} cm", FORNECEDOR_LABEL.get(forn, forn), str(v["fardos"]), fmt(v["valor"])])
        if len(det_data) == 1:
            det_data.append(["-", "-", "-", "-"])
        t2 = Table(det_data, colWidths=[4 * cm, 4 * cm, 4 * cm, 4 * cm])
        t2.setStyle(header_style)
        story.append(t2)

    story.append(Spacer(1, 24))
    rodape_style = ParagraphStyle("Rodape", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    story.append(Paragraph(f"Relatório gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", rodape_style))

    doc.build(story)
    buffer.seek(0)

    nome_arquivo = f"relatorio_{tipo_relatorio}_{inicio.isoformat()}_a_{fim.isoformat()}.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=nome_arquivo)


init_db()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
