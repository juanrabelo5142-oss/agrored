from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
import psycopg2  
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'agrored_secret_key_2026')

# --- CONFIGURACIÓN DE CARPETAS ---
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 

def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(database_url)

CATEGORIA_TITULOS = {
    'verduras': 'Verduras Frescas',
    'granos': 'Granos y Cereales',
    'frutas': 'Frutas de Temporada',
}

# ----------------- Funciones de Utilidad -----------------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión para acceder.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ----------------- Rutas -----------------

@app.route('/')
def index():
    query_param = request.args.get('q', '').strip()
    user_id = session.get('user_id')
    productores_data = {}
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT p.*, u.nombre as nombre_productor, u.nombre_finca,
            (SELECT COUNT(*) FROM favoritos f WHERE f.producto_id = p.id AND f.usuario_id = %s) as es_favorito
            FROM productos p 
            JOIN datos u ON p.productor_id = u.id 
        """
        
        if query_param:
            cur.execute(query + " WHERE (p.nombreproducto ILIKE %s OR u.nombre_finca ILIKE %s) ORDER BY u.nombre ASC", 
                       (user_id, f'%{query_param}%', f'%{query_param}%'))
        else:
            cur.execute(query + " ORDER BY u.nombre ASC", (user_id,))
            
        productos = cur.fetchall()
        for prod in productos:
            nombre = prod['nombre_productor']
            if nombre not in productores_data:
                productores_data[nombre] = []
            productores_data[nombre].append(prod)
            
        cur.close()
        conn.close()
        return render_template('index.html', productores=productores_data, busqueda=query_param)
    except Exception as e:
        print(f"Error en index: {e}")
        return render_template('index.html', productores={}, busqueda=query_param)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        contrasena = request.form.get('password') or request.form.get('contrasena')
        
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute('SELECT * FROM datos WHERE email = %s', (email,))
            usuario = cur.fetchone()
            cur.close()
            conn.close()
            
            if usuario and check_password_hash(usuario['contrasena'], contrasena):
                session.update({
                    'email': usuario['email'], 
                    'rol': usuario['rol'],
                    'user_id': usuario['id'], 
                    'nombre': usuario['nombre'],
                    'nombre_finca': usuario.get('nombre_finca')
                })
                if usuario['rol'] == 'administrador': return redirect(url_for('paginaadministrador'))
                if usuario['rol'] == 'productor': return redirect(url_for('paginaproductor'))
                return redirect(url_for('paginacliente'))
            else:
                flash('Correo o contraseña incorrectos.', 'error')
        except Exception as e:
            print(f"Error en login: {e}")
            flash('Error de conexión.', 'error')
            
    return render_template('iniciosesion.html')

@app.route('/registrarse', methods=['GET', 'POST'])
def registrarse():
    if request.method == 'POST':
        data = request.form
        pwd_hash = generate_password_hash(data.get('password') or data.get('contrasena'))
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""INSERT INTO datos (nombre, email, contrasena, tipo_documento, numero_documento, telefono, direccion, departamento, municipio, codigo_postal, rol, nombre_finca) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", 
                (data.get('nombre'), data.get('email'), pwd_hash, data.get('tipo_documento'), data.get('numero_documento'), 
                 data.get('telefono'), data.get('direccion'), data.get('departamento'), data.get('municipio'), data.get('codigo_postal'), data.get('rol'), data.get('nombre_finca')))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Registro exitoso!', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            print(f"Error en registro: {e}")
            flash('Error: El correo o documento ya existen.', 'error')
    return render_template('registrarse.html')

@app.route('/productos/<cat_slug>')
def mostrar_categoria(cat_slug):
    titulo = CATEGORIA_TITULOS.get(cat_slug, 'Productos')
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM productos WHERE categoria = %s", (cat_slug,))
        productos = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('productos.html', productos=productos, titulo=titulo)
    except Exception as e:
        print(f"Error en productos: {e}")
        return render_template('productos.html', productos=[], titulo=titulo)

@app.route('/carrito')
@login_required
def ver_carrito():
    usuario_id = session.get('user_id')
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT c.id as carrito_id, c.cantidad, p.nombreproducto, p.precio, p.ruta_imagen 
            FROM carrito c 
            JOIN productos p ON c.producto_id = p.id 
            WHERE c.usuario_id = %s
        """, (usuario_id,))
        items = cur.fetchall()
        subtotal = sum(i['precio'] * i['cantidad'] for i in items)
        cur.close()
        conn.close()
        return render_template('carrito.html', items_carrito=items, subtotal=subtotal, envio=5000 if items else 0, total=subtotal + (5000 if items else 0))
    except Exception as e:
        print(f"Error en carrito: {e}")
        return render_template('carrito.html', items_carrito=[], subtotal=0, total=0)

@app.route('/carrito/agregar/<int:id>', methods=['POST', 'GET'])
@login_required
def agregar_al_carrito(id):
    usuario_id = session.get('user_id')
    cantidad = int(request.form.get('cantidad', 1))
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, cantidad FROM carrito WHERE usuario_id = %s AND producto_id = %s", (usuario_id, id))
        item = cur.fetchone()
        if item:
            cur.execute("UPDATE carrito SET cantidad = cantidad + %s WHERE id = %s", (cantidad, item['id']))
        else:
            cur.execute("INSERT INTO carrito (usuario_id, producto_id, cantidad, fecha_agregado) VALUES (%s, %s, %s, NOW())", (usuario_id, id, cantidad))
        conn.commit()
        cur.close()
        conn.close()
        flash('Añadido al carrito', 'success')
    except Exception as e:
        print(f"Error al agregar: {e}")
    return redirect(request.referrer or url_for('index'))

@app.route('/comprar', methods=['POST'])
@login_required
def procesar_compra():
    user_id = session.get('user_id')
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT producto_id, cantidad FROM carrito WHERE usuario_id = %s", (user_id,))
        items = cursor.fetchall()
        if not items:
            return redirect(url_for('ver_carrito'))
        for item in items:
            cursor.execute("UPDATE productos SET stock = stock - %s WHERE id = %s AND stock >= %s", 
                          (item['cantidad'], item['producto_id'], item['cantidad']))
        cursor.execute("DELETE FROM carrito WHERE usuario_id = %s", (user_id,))
        conn.commit()
        conn.close()
        flash('Compra realizada!', 'success')
    except Exception as e:
        print(f"Error compra: {e}")
    return redirect(url_for('index'))

@app.route('/agregarpro', methods=['POST'])
@login_required
def agregarpro():
    if session.get('rol') != 'productor': return redirect(url_for('index'))
    f = request.files.get('imagen_archivo')
    ruta_db = 'uploads/productos/default.jpg'
    if f:
        fname = secure_filename(f.filename)
        os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'productos'), exist_ok=True)
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], 'productos', fname))
        ruta_db = f'uploads/productos/{fname}'
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""INSERT INTO productos (nombreproducto, precio, stock, categoria, descripcion, ruta_imagen, productor_id) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                   (request.form.get('nombreproducto'), request.form.get('precio'), request.form.get('stock'), 
                    request.form.get('categoria'), request.form.get('descripcion'), ruta_db, session['user_id']))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error agregar producto: {e}")
    return redirect(url_for('paginaproductor'))

@app.route('/administrador')
@login_required
def paginaadministrador(): return render_template('administrador.html')

@app.route('/productor')
@login_required
def paginaproductor(): return render_template('productor.html')

@app.route('/cliente')
@login_required
def paginacliente(): return render_template('cliente.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)