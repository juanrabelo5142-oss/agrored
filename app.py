from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
import psycopg2  # Cambiado de mysql.connector
from psycopg2.extras import RealDictCursor # Para mantener la compatibilidad con diccionarios
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

# --- FUNCIÓN DE CONEXIÓN CORREGIDA PARA POSTGRESQL ---
def get_db_connection():
    # Obtiene la URL de la variable de entorno que configuraste en Render
    database_url = os.environ.get('DATABASE_URL')
    
    # Corrección necesaria: SQLAlchemy y psycopg2 a veces requieren 'postgresql://' en lugar de 'postgres://'
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    # Conexión a PostgreSQL en Render
    conn = psycopg2.connect(database_url)
    return conn

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
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM productos ORDER BY id DESC LIMIT 8")
        productos = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('index.html', productos=productos)
    except Exception as e:
        print(f"Error en index: {e}")
        return render_template('index.html', productos=[])

@app.route('/registrarse', methods=['GET', 'POST'])
def registrarse():
    if request.method == 'POST':
        nombre = request.form['nombre']
        email = request.form['email']
        password = request.form['password']
        rol = request.form.get('rol', 'cliente')
        
        hashed_password = generate_password_hash(password)
        
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO datos (nombre, email, password, rol) VALUES (%s, %s, %s, %s)", 
                       (nombre, email, hashed_password, rol))
            conn.commit()
            cur.close()
            conn.close()
            flash('Registro exitoso. Ahora puedes iniciar sesión.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            print(f"Error al registrar: {e}")
            flash('Error al registrar usuario. El correo podría ya existir.', 'error')
            
    return render_template('registrarse.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM datos WHERE email = %s", (email,))
            user = cur.fetchone()
            cur.close()
            conn.close()
            
            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['user_nombre'] = user['nombre']
                session['user_rol'] = user['rol']
                flash(f'Bienvenido, {user["nombre"]}!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Correo o contraseña incorrectos.', 'error')
        except Exception as e:
            print(f"Error en login: {e}")
            flash('Error en la base de datos.', 'error')
            
    return render_template('login.html')

@app.route('/productos/<categoria>')
def ver_productos(categoria):
    titulo = CATEGORIA_TITULOS.get(categoria, 'Productos')
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM productos WHERE categoria = %s", (categoria,))
        productos = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('productos.html', productos=productos, titulo=titulo)
    except Exception as e:
        print(f"Error en productos: {e}")
        return render_template('productos.html', productos=[], titulo=titulo)

@app.route('/perfil')
@login_required
def perfil():
    return render_template('perfil.html')

@app.route('/vendedor/subir', methods=['GET', 'POST'])
@login_required
def subir_producto():
    if session.get('user_rol') != 'vendedor':
        flash('Solo los vendedores pueden subir productos.', 'error')
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        nombre = request.form['nombre']
        precio = request.form['precio']
        categoria = request.form['categoria']
        descripcion = request.form['descripcion']
        stock = request.form['stock']
        imagen = request.files['imagen']
        
        if imagen:
            filename = secure_filename(imagen.filename)
            imagen.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO productos (nombre, precio, categoria, descripcion, imagen, vendedor_id, stock) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (nombre, precio, categoria, descripcion, filename, session['user_id'], stock))
                conn.commit()
                cur.close()
                conn.close()
                flash('Producto publicado con éxito.', 'success')
                return redirect(url_for('index'))
            except Exception as e:
                print(f"Error al subir: {e}")
                flash('Error al guardar en la base de datos.', 'error')
                
    return render_template('subir_producto.html')

@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if request.method == 'POST':
        nombre = request.form['nombre']
        mensaje = request.form['mensaje']
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO feedback (nombre, mensaje) VALUES (%s, %s)", (nombre, mensaje))
            conn.commit()
            cur.close()
            conn.close()
            flash('Gracias por tus comentarios.', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            print(f"Error en feedback: {e}")
    return render_template('feedback.html')

@app.route('/carrito/agregar/<int:producto_id>')
@login_required
def agregar_al_carrito(producto_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO carrito (usuario_id, producto_id) VALUES (%s, %s)", (session['user_id'], producto_id))
        conn.commit()
        cur.close()
        conn.close()
        flash('Producto añadido al carrito.', 'success')
    except Exception as e:
        print(f"Error carrito: {e}")
    return redirect(request.referrer or url_for('index'))

@app.route('/carrito')
@login_required
def ver_carrito():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT c.id as carrito_id, p.* FROM carrito c 
            JOIN productos p ON c.producto_id = p.id 
            WHERE c.usuario_id = %s
        """, (session['user_id'],))
        items = cur.fetchall()
        total = sum(item['precio'] for item in items)
        cur.close()
        conn.close()
        return render_template('carrito.html', items=items, total=total)
    except Exception as e:
        print(f"Error ver carrito: {e}")
        return render_template('carrito.html', items=[], total=0)

@app.route('/comprar', methods=['POST'])
@login_required
def procesar_compra():
    user_id = session.get('user_id')
    if user_id:
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # 1. Obtener productos del carrito para restar el stock
            cursor.execute("SELECT producto_id, COUNT(*) as cantidad FROM carrito WHERE usuario_id = %s GROUP BY producto_id", (user_id,))
            items_carrito = cursor.fetchall()

            if not items_carrito:
                flash("El carrito está vacío", "warning")
                return redirect(url_for('ver_carrito'))

            # 2. Por cada producto, restamos el stock
            for item in items_carrito:
                query_stock = """
                    UPDATE productos 
                    SET stock = stock - %s 
                    WHERE id = %s AND stock >= %s
                """
                cursor.execute(query_stock, (item['cantidad'], item['producto_id'], item['cantidad']))

            # 3. Limpiamos el carrito
            cursor.execute("DELETE FROM carrito WHERE usuario_id = %s", (user_id,))
            
            conn.commit()
            flash('¡Compra realizada! El stock ha sido actualizado 🚀', 'success')
            
        except Exception as e:
            conn.rollback()
            print(f"Error al procesar compra: {e}")
            flash('Hubo un error al procesar tu pedido', 'error')
        finally:
            conn.close()
            
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('index'))

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)