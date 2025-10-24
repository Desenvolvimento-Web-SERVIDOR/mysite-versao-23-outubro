import os
from datetime import datetime
from flask import Flask, render_template, session, redirect, url_for, flash
from flask_bootstrap import Bootstrap
from flask_moment import Moment
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, BooleanField
from wtforms.validators import DataRequired
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)

# Configurações 
app.config['SECRET_KEY'] = 'uma string bem dificil de adivinhar'
app.config['SQLALCHEMY_DATABASE_URI'] =\
    'sqlite:///' + os.path.join(basedir, 'data.sqlite')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


app.config['SENDGRID_API_KEY'] = os.environ.get('SENDGRID_API_KEY')
app.config['API_FROM'] = os.environ.get('API_FROM')
app.config['FLASKY_ADMIN'] = os.environ.get('FLASKY_ADMIN')
app.config['STUDENT_ID'] = os.environ.get('STUDENT_ID')
app.config['STUDENT_NAME'] = os.environ.get('STUDENT_NAME')

app.config['FLASKY_MAIL_SUBJECT_PREFIX'] = '[Flasky]'

# Inicialização das Extensões
bootstrap = Bootstrap(app)
moment = Moment(app)
db = SQLAlchemy(app)
migrate = Migrate(app, db)


# Modelos do Banco de Dados
class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True)
    users = db.relationship('User', backref='role', lazy='dynamic')

    @staticmethod
    def insert_roles():
        roles = ['User', 'Administrator']
        for r in roles:
            role = Role.query.filter_by(name=r).first()
            if role is None:
                role = Role(name=r)
                db.session.add(role)
        db.session.commit()

    def __repr__(self):
        return '<Role %r>' % self.name


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))

    def __repr__(self):
        return '<User %r>' % self.username

# novo modelo para persistir e-mails
class EmailLog(db.Model):
    __tablename__ = 'emails'
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(128), index=True)
    recipient = db.Column(db.String(256), index=True)
    subject = db.Column(db.String(128))
    body = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

    def __repr__(self):
        return f'<EmailLog {self.subject}>'


# Função de Envio de E-mail
def send_email_sendgrid(to_list, subject, html_content_body, text_body):
    """Envia e-mail com SendGrid e registra no DB."""

    full_subject = f"{app.config['FLASKY_MAIL_SUBJECT_PREFIX']} {subject}"

    if len(to_list) == 1:
        destinos = to_list[0]
    else:
        destinos = tuple(to_list)

    message = Mail(
        from_email=app.config['API_FROM'],
        to_emails=destinos,  
        subject=full_subject,
        html_content=html_content_body
    )
    try:
        sg = SendGridAPIClient(app.config['SENDGRID_API_KEY'])
        response = sg.send(message)
        print(f"E-mail enviado para {to_list}, status: {response.status_code}")

        # Persistir no banco de dados
        log_entry = EmailLog(
            sender=app.config['API_FROM'],
            recipient=str(to_list), # Salva a lista de e-mails como string
            subject=full_subject,
            body=text_body # Salva a versão em texto simples
        )
        db.session.add(log_entry)
        db.session.commit()
        print("Log de e-mail salvo no banco de dados.")

        return True

    except Exception as e:
        print(f"Erro ao enviar e-mail ou salvar log: {e}")
        return False


# Formulário
class NameForm(FlaskForm):
    name = StringField('Qual é o seu nome?', validators=[DataRequired()])
    email = BooleanField('Deseja enviar e-mail para flaskaulasweb@zohomail.com?')
    submit = SubmitField('Submit')


# Contexto do Shell 
@app.shell_context_processor
def make_shell_context():
    return dict(db=db, User=User, Role=Role, EmailLog=EmailLog)


# Rotas da Aplicação 
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


@app.route('/', methods=['GET', 'POST'])
def index():
    form = NameForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.name.data).first()
        if user is None:
            user_role = Role.query.filter_by(name='User').first()
            # Se for o primeiro usuário, define como admin
            if User.query.count() == 0:
                 user_role = Role.query.filter_by(name='Administrator').first()

            user = User(username=form.name.data, role=user_role)
            db.session.add(user)
            db.session.commit()
            session['known'] = False

            # Prepara os destinatários e o corpo do e-mail
            destinatarios = [app.config['FLASKY_ADMIN']]
            if form.email.data:
                destinatarios.append("flaskaulasweb@zohomail.com")

            # Corpo do e-mail (em texto e HTML)
            new_user_name = form.name.data
            text_body = f"Novo usuário cadastrado: {new_user_name}"
            html_body = f"""
                <h3>Novo Usuário Cadastrado!</h3>
                <p><strong>Prontuário do Aluno:</strong> {app.config['STUDENT_ID']}</p>
                <p><strong>Nome do Aluno:</strong> {app.config['STUDENT_NAME']}</p>
                <hr>
                <p><strong>Nome do novo usuário:</strong> {new_user_name}</p>
            """

            # Envia e-mail usando a nova função
            success = send_email_sendgrid(
                to_list=destinatarios,
                subject='Novo usuário',
                html_content_body=html_body,
                text_body=text_body
            )
            if success:
                flash('Novo usuário cadastrado e e-mail(s) enviados com sucesso!', 'success')
            else:
                flash('Usuário salvo, mas houve um ERRO ao enviar/salvar o e-mail. Verifique os logs.', 'danger')

        else:
            session['known'] = True

        session['name'] = form.name.data
        return redirect(url_for('index'))

    # Busca todos os usuários para a tabela
    users = User.query.order_by(User.id.asc()).all()
    return render_template('index.html', form=form, name=session.get('name'),
                           known=session.get('known', False), users=users)


# NOVA ROTA PARA LISTAR E-MAILS 
@app.route('/emailsEnviados')
def emails_enviados():
    emails = EmailLog.query.order_by(EmailLog.timestamp.desc()).all()
    return render_template('emails_enviados.html', emails=emails)
