from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
import psycopg2  
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from functools import wraps
from flask import session, redirect, url_for, render_template

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'agrored_secret_key_2026')

# --- CONFIGURACIÓN DE CARPETAS ---
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 

CATEGORIA_TITULOS = {
    'verduras': 'Verduras Frescas',
    'granos': 'Granos y Cereales',
    'frutas': 'Frutas de Temporada',
}

# ----------------- Funciones de Utilidad -----------------

def get_db_connection():
    try:
        database_url = os.environ.get('DATABASE_URL')

        if database_url.startswith("postgres://"):
            database_url = database_url.replace(
                "postgres://",
                "postgresql://",
                1
            )

        conn = psycopg2.connect(database_url)
        return conn

    except Exception as err:
        print(f"Error PostgreSQL: {err}")
        return None
    
def login_required(f):  # <-- AQUÍ: Debes agregar (f)
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Verifica si el email del usuario está en la sesión
        if 'email' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 1. Creamos un "decorador" para proteger rutas de admin
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('rol') != 'administrador':
            return redirect(url_for('index')) # Si no es admin, lo manda al inicio
        return f(*args, **kwargs)
    return decorated_function

# 2. La ruta para ver a los usuarios
@app.route('/admin/usuarios')
@admin_required 
def paginaadministrador():
    # 1. Usamos tu función para conectar a agrored_db
    conn = get_db_connection()
    if conn is None:
        return "Error de conexión a la base de datos", 500

    cur = conn.cursor(cursor_factory=RealDictCursor) # dictionary=True ayuda a que el HTML entienda 'user.nombre'
    
    # 2. Ejecutamos la consulta en la tabla 'datos'
    cur.execute("SELECT id, nombre, email, telefono, rol, numero_documento, tipo_documento FROM datos")
    usuarios_db = cur.fetchall()
    
    # 3. Cerramos todo
    cur.close()
    conn.close()
    
    return render_template('pagina_administrador.html', usuarios=usuarios_db)
# ----------------- Rutas Principales -----------------

@app.route('/')
def index():
    # 1. Capturamos lo que el usuario escribió
    query_param = request.args.get('q', '').strip()
    user_id = session.get('user_id') # IMPORTANTE: Capturamos el ID del usuario
    
    conn = get_db_connection()
    productores_data = {}
    
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # 2. Base de la consulta con el subquery de favoritos (LA MAGIA)
            # Si el usuario está logueado, cuenta si el producto está en su tabla favoritos
            query = """
                SELECT p.*, u.nombre as nombre_productor, u.nombre_finca,
                (SELECT COUNT(*) FROM favoritos f 
                WHERE f.producto_id = p.id AND f.usuario_id = %s) as es_favorito
                FROM productos p 
                JOIN datos u ON p.productor_id = u.id 
            """
            
            # 3. Filtros de búsqueda
            if query_param:
                query += " WHERE (p.nombreproducto ILIKE %s OR u.nombre_finca ILIKE %s)"
                query += " ORDER BY u.nombre ASC"
                # Pasamos user_id primero por el subquery, luego los términos de búsqueda
                cursor.execute(query, (user_id, f"%{query_param}%", f"%{query_param}%"))
            else:
                query += " ORDER BY u.nombre ASC"
                cursor.execute(query, (user_id,))
            
            productos = cursor.fetchall()
            
            # 4. Lógica de agrupamiento original
            for prod in productos:
                nombre = prod['nombre_productor']
                if nombre not in productores_data:
                    productores_data[nombre] = []
                productores_data[nombre].append(prod)
                
        except psycopg2.Error as err:
            print(f"Error en index: {err}")
        finally:
            conn.close()

    # 5. Renderizado
    return render_template('index.html', productores=productores_data, busqueda=query_param)

@app.route('/productos/<string:cat_slug>')
def mostrar_categoria(cat_slug):
    titulo = CATEGORIA_TITULOS.get(cat_slug, "Productos")
    conn = get_db_connection()
    productos = []

    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            query = """
                SELECT p.*, u.nombre as nombre_productor, u.nombre_finca 
                FROM productos p 
                JOIN datos u ON p.productor_id = u.id 
                WHERE p.categoria = %s
            """
            cursor.execute(query, (cat_slug,))
            productos = cursor.fetchall()
        finally:
            conn.close()
            
    return render_template('productoscategoria.html', 
                            productos=productos, 
                            titulo_categoria=titulo,
                            categoria_actual=cat_slug)

# ----------------- Gestión de Usuarios -----------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        contrasena = request.form.get('contrasena')

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                # Seleccionamos todo de la tabla 'datos' (asegúrate que así se llame tu tabla de usuarios)
                cursor.execute('SELECT * FROM datos WHERE email = %s', (email,))
                usuario = cursor.fetchone()
                conn.close()

                if usuario and check_password_hash(usuario['contrasena'], contrasena):
                    # --- GUARDAR DATOS EN SESIÓN ---
                    session['email'] = usuario['email']
                    session['rol'] = usuario['rol']
                    session['user_id'] = usuario['id']
                    session['nombre'] = usuario['nombre']
                    # Usamos .get por si el campo es NULL en la DB
                    session['nombre_finca'] = usuario.get('nombre_finca')
                    
                    destinos = {
                        'administrador': 'paginaadministrador',
                        'productor': 'paginaproductor',
                        'cliente': 'paginacliente' 
                    }
                    
                    # Redirección dinámica según el rol
                    return redirect(url_for(destinos.get(usuario['rol'], 'index')))
                else:
                    flash('Correo o contraseña incorrectos.', 'error')
            except psycopg2.Error as err:
                print(f"Error: {err}") # Útil para debug
                flash('Error de conexión con la base de datos al iniciar sesión.', 'error')
                
    return render_template('iniciosesion.html')

@app.route('/registrarse', methods=['GET', 'POST'])
def registrarse():
    departamentos = ["Cundinamarca", "Boyacá", "Bogotá", "Nariño", "Meta", "Tolima", "Valle del Cauca", "Huila", "Quindío"]

    if request.method == 'POST':
        # Captura de TODOS los datos del formulario
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password_hash = generate_password_hash(request.form.get('contrasena'))
        tipo_doc = request.form.get('tipo_documento') 
        num_doc = request.form.get('numero_documento')
        telefono = request.form.get('telefono')
        direccion = request.form.get('direccion')
        departamento = request.form.get('departamento') 
        municipio = request.form.get('municipio')       
        codigo_postal = request.form.get('codigo_postal') 
        rol = request.form.get('rol')
        nombre_finca = request.form.get('nombre_finca') if rol == 'productor' else None

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                query = """INSERT INTO datos (nombre, email, contrasena, tipo_documento, 
                            numero_documento, telefono, direccion, departamento, municipio, 
                            codigo_postal, rol, nombre_finca) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                
                cursor.execute(query, (
                    nombre, email, password_hash, tipo_doc, num_doc, 
                    telefono, direccion, departamento, municipio, 
                    codigo_postal, rol, nombre_finca
                ))
                
                conn.commit()
                flash('¡Bienvenido a AgroRed! Ya puedes iniciar sesión.', 'success')
                return redirect(url_for('login'))
                
            except psycopg2.Error as err:
                print(f"Error detallado: {err}") # Esto te dirá en la consola qué falló exactamente
                if err.pgcode == '23505':  # Código de error de violación de clave única en PostgreSQL
                    flash('Error: El correo o documento ya están registrados.', 'error')
                else:
                    flash(f'Error en la base de datos: {err.pgerror}', 'error')
            finally:
                conn.close()
                
    return render_template('registrarse.html', departamentos=departamentos)

#---------------------- ACTUALIZAR DATOS PERFIL --------------------

@app.route('/perfil/actualizar', methods=['POST'])
@login_required
def actualizar_perfil():
    nombre = request.form.get('nombre')
    email = request.form.get('email')
    telefono = request.form.get('telefono')
    direccion = request.form.get('direccion')
    departamento = request.form.get('departamento')
    municipio = request.form.get('municipio')
    codigo_postal = request.form.get('codigo_postal')
    nombre_finca = request.form.get('nombre_finca') 
    
    usuario_id = session.get('user_id') 

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE datos 
                SET nombre = %s, email = %s, telefono = %s, 
                    direccion = %s, departamento = %s, municipio = %s, 
                    codigo_postal = %s, nombre_finca = %s
                WHERE id = %s
            """
            valores = (nombre, email, telefono, direccion, departamento, municipio, codigo_postal, nombre_finca, usuario_id)
            cursor.execute(sql, valores)
            conn.commit()
            
            session['nombre'] = nombre
            session['email'] = email
            if nombre_finca:
                session['nombre_finca'] = nombre_finca

            flash('¡Información de AgroRed actualizada con éxito!', 'success')
        except psycopg2.Error as err:
            flash('No se pudieron guardar los cambios en la base de datos.', 'error')
        finally:
            conn.close()
    
    return redirect(url_for('actualizar_datos_cliente')) # Regresa al formulario

@app.route('/perfil/actualizar_datos', methods=['GET', 'POST']) # Agregamos GET aquí
@login_required
def actualizar_datos_cliente():
    # Si alguien intenta entrar a esta URL escribiéndola o por redirección simple (GET)
    if request.method == 'GET':
        return redirect(url_for('paginacliente'))

    # Si es POST (cuando el usuario presiona el botón de guardar)
    nombre = request.form.get('nombre')
    email = request.form.get('email')
    telefono = request.form.get('telefono')
    direccion = request.form.get('direccion')
    departamento = request.form.get('departamento')
    municipio = request.form.get('municipio')
    codigo_postal = request.form.get('codigo_postal')
    nombre_finca = request.form.get('nombre_finca') 
    

    usuario_id = session.get('user_id')

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE datos 
                SET nombre = %s, email = %s, telefono = %s, 
                    direccion = %s, departamento = %s, municipio = %s
                WHERE id = %s
            """
            valores = (nombre, email, telefono, direccion, departamento, municipio, usuario_id)
            cursor.execute(sql, valores)
            conn.commit()
            
            session['nombre'] = nombre
            session['email'] = email
            flash('¡Datos actualizados correctamente!', 'success')
        except psycopg2.Error as err:
            print(f"Error: {err}")
            flash('Error al guardar en la base de datos.', 'error')
        finally:
            conn.close()
    
    return redirect(url_for('paginacliente'))

# ----------------- Rutas Protegidas por Rol -----------------

@app.route('/paginacliente') 
@login_required
def paginacliente(): 
    user_id = session.get('user_id')
    conn = get_db_connection()
    
    # Inicializamos la variable para que sea accesible estructuralmente
    usuario_db = None 

    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            # Traemos todos los datos del usuario de la tabla 'datos'
            cursor.execute('SELECT * FROM datos WHERE id = %s', (user_id,))
            usuario_db = cursor.fetchone()
        except psycopg2.Error as err:
            print(f"Error al obtener datos del cliente: {err}")
        finally:
            conn.close()
    
    # Verificamos que se hayan encontrado datos antes de mostrar la página
    if usuario_db:
        # Enviamos 'usuario' para los datos generales y 'nombre' para el saludo
        return render_template('paginacliente.html', 
                               usuario=usuario_db, 
                               nombre=usuario_db['nombre'])
    
    # Si no hay datos o falla la conexión, regresamos al inicio por seguridad
    flash('No se pudo cargar la información de tu perfil.', 'error')
    return redirect(url_for('index'))



@app.route('/productor/panel')
@login_required
def paginaproductor():
    productor_id = session.get('user_id')
    conn = get_db_connection()
    productos = []
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM productos WHERE productor_id = %s", (productor_id,))
            productos = cursor.fetchall()
        finally:
            conn.close()
    return render_template('paginaproductor.html', productos=productos)

# ----------------- Gestión de Productos -----------------

@app.route('/producto/<int:id>')
def detalle_producto(id):
    conn = get_db_connection()
    producto = None
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            query = """
                SELECT p.*, u.nombre as nombre_vendedor, u.nombre_finca 
                FROM productos p 
                JOIN datos u ON p.productor_id = u.id 
                WHERE p.id = %s
            """
            cursor.execute(query, (id,))
            producto = cursor.fetchone()
        finally:
            conn.close()
    
    if producto:
        return render_template('producto.html', producto=producto)
    flash('Producto no encontrado.', 'error')
    return redirect(url_for('index'))

# ----------------- Carrito y Otros -----------------

@app.route('/carrito/agregar/<int:id>', methods=['POST','GET'])
def agregar_al_carrito(id):
    # --- PRUEBA DE FUEGO ---
    print(f"DEBUG: Intentando agregar producto {id}")
    
    # Verifica cómo guardaste el ID al iniciar sesión. 
    # Si en el login pusiste session['id'], aquí debe ser session.get('id')
    usuario_id = session.get('user_id') or session.get('id') 
    
    print(f"DEBUG: ID de usuario en sesión: {usuario_id}")

    if not usuario_id:
        print("DEBUG: No hay usuario en sesión, redirigiendo a login")
        flash("Debes iniciar sesión.")
        return redirect(url_for('login'))

    cantidad = int(request.form.get('cantidad', 1))
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # IMPORTANTE: Revisa que el nombre de tu tabla sea exactamente 'carrito'
        query_check = "SELECT id, cantidad FROM carrito WHERE usuario_id = %s AND producto_id = %s"
        cursor.execute(query_check, (usuario_id, id))
        item_existente = cursor.fetchone()

        if item_existente:
            print(f"DEBUG: El producto ya existía, sumando cantidad")
            nueva_cantidad = item_existente['cantidad'] + cantidad
            cursor.execute("UPDATE carrito SET cantidad = %s WHERE id = %s", (nueva_cantidad, item_existente['id']))
        else:
            print(f"DEBUG: Insertando nuevo producto en la tabla carrito")
            query_insert = "INSERT INTO carrito (usuario_id, producto_id, cantidad, fecha_agregado) VALUES (%s, %s, %s, NOW())"
            cursor.execute(query_insert, (usuario_id, id, cantidad))
        
        conn.commit()
        print("DEBUG: ¡COMMIT EXITOSO!")
        flash("Producto añadido.")

    except Exception as e:
        print(f"DEBUG ERROR SQL: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('ver_carrito')) # Redirigir directo al carrito para ver el cambio

@app.route('/carrito')
def ver_carrito():
    # 1. Obtener el ID del usuario de la sesión
    usuario_id = session.get('user_id') or session.get('id')
    
    if not usuario_id:
        flash("Inicia sesión para ver tu carrito")
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # 2. SELECT con JOIN para traer los nombres y fotos de los productos
    # Ajusta los nombres de las tablas si son diferentes en tu BD
    query = """
        SELECT 
            c.id AS carrito_id, 
            c.cantidad, 
            p.nombreproducto, 
            p.precio, 
            p.ruta_imagen,
            p.id AS producto_id
        FROM carrito c
        JOIN productos p ON c.producto_id = p.id
        WHERE c.usuario_id = %s
    """
    
    try:
        cursor.execute(query, (usuario_id,))
        items_carrito = cursor.fetchall()
        
        # 3. Calcular totales para el resumen
        subtotal = sum(item['precio'] * item['cantidad'] for item in items_carrito)
        envio = 5000 if items_carrito else 0 # Envío base si hay productos
        total = subtotal + envio

    except Exception as e:
        print(f"DEBUG ERROR EN VER_CARRITO: {e}")
        items_carrito = []
        subtotal = 0
        envio = 0
        total = 0
    finally:
        cursor.close()
        conn.close()

    # 4. Enviar los datos al HTML
    return render_template('carrito.html', 
                           items_carrito=items_carrito, 
                           subtotal=subtotal, 
                           envio=envio, 
                           total=total)

@app.route('/carrito/actualizar/<int:id>/<string:accion>')
def actualizar_carrito(id, accion):
    usuario_id = session.get('user_id') or session.get('id')
    if not usuario_id:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Buscamos el item en el carrito usando su ID de la tabla carrito
        cursor.execute("SELECT cantidad FROM carrito WHERE id = %s", (id,))
        item = cursor.fetchone()

        if item:
            nueva_cantidad = item['cantidad']
            if accion == 'sumar':
                nueva_cantidad += 1
            elif accion == 'restar' and nueva_cantidad > 1:
                nueva_cantidad -= 1
            
            # Actualizamos la base de datos
            cursor.execute("UPDATE carrito SET cantidad = %s WHERE id = %s", (nueva_cantidad, id))
            conn.commit()
    except Exception as e:
        print(f"DEBUG ERROR: {e}")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('ver_carrito'))

@app.route('/carrito/eliminar/<int:id>')
def eliminar_del_carrito(id):
    # 1. Verificar sesión
    usuario_id = session.get('user_id') or session.get('id')
    if not usuario_id:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 2. Eliminar el registro usando el ID de la fila del carrito
        # Solo eliminamos si pertenece al usuario actual por seguridad
        query = "DELETE FROM carrito WHERE id = %s AND usuario_id = %s"
        cursor.execute(query, (id, usuario_id))
        conn.commit()
        print(f"DEBUG: Producto {id} eliminado del carrito")
    except Exception as e:
        print(f"DEBUG ERROR AL ELIMINAR: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('ver_carrito'))

#--------------------------pago---------------------------

@app.route('/carrito/pagar')
def procesar_pago():
    usuario_id = session.get('user_id') or session.get('id')
    if not usuario_id:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Traer los productos del carrito para el resumen lateral
    query = """
        SELECT c.cantidad, p.nombreproducto, p.precio
        FROM carrito c
        JOIN productos p ON c.producto_id = p.id
        WHERE c.usuario_id = %s
    """
    cursor.execute(query, (usuario_id,))
    items_pago = cursor.fetchall()
    
    # 2. Calcular totales
    subtotal = sum(item['precio'] * item['cantidad'] for item in items_pago)
    envio = 5000 if items_pago else 0
    total = subtotal + envio
    
    conn.close()

    # 3. Renderizar tu nuevo diseño
    return render_template('pago.html', 
                           items_pago=items_pago, 
                           subtotal=subtotal, 
                           envio=envio, 
                           total=total)
#------------------------------------perfil------------------------
# RUTA UNIFICADA CON EL NOMBRE DE TU HTML
@app.route('/perfil')
@login_required
def perfil():
    user_id = session.get('user_id')
    conn = get_db_connection()
    usuario = None
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM datos WHERE id = %s", (user_id,))
            usuario = cursor.fetchone()
        finally:
            conn.close()
    if usuario:
        # Asegúrate de que el nombre del archivo sea el correcto (ej: perfil.html o actualizar_datos.html)
        return render_template('perfil.html', usuario=usuario)
    return redirect(url_for('index'))

@app.route('/feedback')
def feedback():
    conn = get_db_connection()
    mensajes = []
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            # Traemos los mensajes, el nombre del usuario y la fecha
            query = """
                SELECT c.mensaje, c.fecha, u.nombre 
                FROM comentarios c 
                JOIN datos u ON c.usuario_id = u.id 
                ORDER BY c.fecha DESC
            """
            cursor.execute(query)
            mensajes = cursor.fetchall()
        except psycopg2.Error as err:
            print(f"Error al cargar comentarios: {err}")
        finally:
            conn.close()
    
    return render_template('feedback.html', comentarios=mensajes)

# 1. RUTA PARA VER LOS FAVORITOS (Solo una vez)
@app.route('/favoritos')
@login_required
def ver_favoritos():
    user_id = session.get('user_id')
    # Capturamos si viene del perfil o no
    origin = request.args.get('origin') 
    
    conn = get_db_connection()
    lista_favoritos = []
    
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            query = """
                SELECT p.*, u.nombre as nombre_productor 
                FROM productos p
                JOIN favoritos f ON p.id = f.producto_id
                JOIN datos u ON p.productor_id = u.id
                WHERE f.usuario_id = %s
            """
            cursor.execute(query, (user_id,))
            lista_favoritos = cursor.fetchall()
        finally:
            conn.close()
            
    # Pasamos la variable 'origin' al template
    return render_template('favoritos.html', favoritos=lista_favoritos, origin=origin)

@app.route('/toggle_favorito/<int:id>')
@login_required
def toggle_favorito(id):
    user_id = session.get('user_id')
    conn = get_db_connection()
    
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Verificamos si ya existe en favoritos
            cursor.execute("SELECT id FROM favoritos WHERE usuario_id = %s AND producto_id = %s", (user_id, id))
            favorito = cursor.fetchone()

            if favorito:
                # 2. Si ya es favorito, lo quitamos (Unfavorite)
                cursor.execute("DELETE FROM favoritos WHERE usuario_id = %s AND producto_id = %s", (user_id, id))
            else:
                # 3. Si no es favorito, lo agregamos (Favorite)
                cursor.execute("INSERT INTO favoritos (usuario_id, producto_id) VALUES (%s, %s)", (user_id, id))
            
            conn.commit()
        finally:
            conn.close()
            
    # Regresa a la página donde estaba el usuario (index o detalles)
    return redirect(request.referrer or url_for('index'))

# 2. RUTA PARA AGREGAR (Esta te faltaba en el bloque anterior)
@app.route('/favoritos/agregar/<int:producto_id>')
@login_required
def agregar_favorito(producto_id):
    user_id = session.get('user_id')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # INSERT IGNORE evita errores si el usuario intenta agregar el mismo producto dos veces
            query = """
            INSERT INTO favoritos (usuario_id, producto_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """
            cursor.execute(query, (user_id, producto_id))
            conn.commit()
            flash('Añadido a tus favoritos ❤️', 'success')
        finally:
            conn.close()
    return redirect(request.referrer or url_for('index'))

# 3. RUTA PARA ELIMINAR (La que hace funcionar el corazón roto)
@app.route('/favoritos/eliminar/<int:producto_id>')
@login_required
def eliminar_favorito(producto_id):
    user_id = session.get('user_id')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM favoritos WHERE usuario_id = %s AND producto_id = %s", (user_id, producto_id))
            conn.commit()
            flash('Producto eliminado de favoritos', 'info')
        finally:
            conn.close()
    return redirect(url_for('ver_favoritos'))

#---------------------------pedidos------------------------

@app.route('/mis-pedidos')
@login_required
def mis_pedidos():
    user_id = session.get('user_id')
    # Asegúrate de que el nombre de esta función sea el que usas para conectar
    conn = get_db_connection()
    pedidos_db = []
    
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            # CAMBIO CLAVE: Usamos 'cliente_id' para que coincida con tu CREATE TABLE
            query = "SELECT * FROM pedidos WHERE cliente_id = %s ORDER BY fecha DESC"
            cursor.execute(query, (user_id,))
            pedidos_db = cursor.fetchall()
        except Exception as e:
            print(f"Error en la consulta de pedidos: {e}")
        finally:
            # Cerramos 'conn', que es como definimos la variable arriba
            conn.close() 
            
    return render_template('mis_pedidos.html', pedidos=pedidos_db)

#----------------------------agregar producto --------------------------------

@app.route('/agregarpro', methods=['POST'])
@login_required
def agregarpro():
    if request.method == 'POST':
        # Extraemos los datos usando los 'name' exactos de tu HTML
        nombre = request.form.get('nombreproducto')
        precio = request.form.get('precio')
        stock = request.form.get('stock')
        categoria = request.form.get('categoria')
        descripcion = request.form.get('descripcion')
        imagen = request.files.get('imagen_archivo') # Coincide con tu input type="file"
        productor_id = session.get('user_id')

        # Manejo de la imagen
        if imagen and imagen.filename != '':
            filename = secure_filename(imagen.filename)
            # Guardamos la imagen en la carpeta de estáticos
            ruta_carpeta = os.path.join(app.config['UPLOAD_FOLDER'], 'productos')
            if not os.path.exists(ruta_carpeta):
                os.makedirs(ruta_carpeta)
                
            imagen.save(os.path.join(ruta_carpeta, filename))
            ruta_db = f'uploads/productos/{filename}'
        else:
            ruta_db = 'uploads/productos/default.jpg'

        # Inserción en la Base de Datos
        conn = get_db_connection() # Usa tu función de conexión
        if conn:
            try:
                cursor = conn.cursor()
                query = """
                    INSERT INTO productos 
                    (nombreproducto, precio, stock, categoria, descripcion, ruta_imagen, productor_id) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(query, (nombre, precio, stock, categoria, descripcion, ruta_db, productor_id))
                conn.commit()
                flash('¡Producto lanzado al mercado con éxito! 🚀', 'success')
            except psycopg2.Error as err:
                print(f"Error al publicar: {err}")
                flash('Hubo un error al guardar el producto.', 'error')
            finally:
                conn.close()
                
    return redirect(url_for('paginaproductor'))

@app.route('/producto/nuevo')
@login_required
def formulario_producto():
    return render_template('publicar_producto.html')

#-------------------chat------------------------------

@app.route('/chat/<int:id_productor>')
@login_required
def chat(id_productor):
    user_id = session.get('user_id')
    conn = get_db_connection()
    mensajes = []
    
    if conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Traemos los mensajes donde yo soy emisor y él receptor, O AL REVÉS
        query = """
            SELECT * FROM mensajes 
            WHERE (emisor_id = %s AND receptor_id = %s) 
            OR (emisor_id = %s AND receptor_id = %s)
            ORDER BY fecha ASC
        """
        cursor.execute(query, (user_id, id_productor, id_productor, user_id))
        mensajes = cursor.fetchall()
        
        # También buscamos el nombre del productor para el encabezado
        cursor.execute("SELECT nombre, nombre_finca FROM datos WHERE id = %s", (id_productor,))
        productor = cursor.fetchone()
        conn.close()
        # Dentro de la función chat en app.py
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE mensajes 
        SET leido = TRUE
        WHERE emisor_id = %s 
        AND receptor_id = %s 
        AND leido = FALSE
        """, (id_productor, user_id))
        conn.commit()

    return render_template('chat.html', 
                           mensajes=mensajes, 
                           productor_nombre=productor['nombre'],
                           nombre_finca=productor['nombre_finca'],
                           receptor_id=id_productor,
                           mi_id=user_id) # Pasamos nuestro ID para saber de qué lado poner la burbuja

@app.route('/enviar_mensaje/<int:receptor_id>', methods=['POST'])
@login_required
def enviar_mensaje(receptor_id):
    contenido = request.form.get('mensaje')
    emisor_id = session.get('user_id')

    if not contenido:
        return "Mensaje vacío", 400

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO mensajes (emisor_id, receptor_id, contenido) VALUES (%s, %s, %s)",
                       (emisor_id, receptor_id, contenido))
        conn.commit()
        conn.close()
        
    # IMPORTANTE: En lugar de redirect, devolvemos un estado de éxito
    return "OK", 200

#------------------bandeja de entrada-------------------------

@app.route('/bandeja')
@login_required
def bandeja():
    user_id = session.get('user_id')
    conn = get_db_connection()
    chats = []
    
    if conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Esta consulta busca a la OTRA persona de la conversación
        # Si yo soy el emisor, me trae al receptor. Si yo soy el receptor, me trae al emisor.
        query = """
            SELECT DISTINCT 
                d.id, 
                d.nombre, 
                d.nombre_finca,
                (SELECT contenido FROM mensajes 
                 WHERE (emisor_id = %s AND receptor_id = d.id) 
                    OR (emisor_id = d.id AND receptor_id = %s) 
                 ORDER BY fecha DESC LIMIT 1) as ultimo_msj
            FROM datos d
            JOIN mensajes m ON (d.id = m.emisor_id OR d.id = m.receptor_id)
            WHERE (m.emisor_id = %s OR m.receptor_id = %s)
              AND d.id != %s
        """
        cursor.execute(query, (user_id, user_id, user_id, user_id, user_id))
        chats = cursor.fetchall()
        conn.close()
    
    return render_template('bandeja.html', chats=chats)
#-----------------mensajes----------------------

# --- RUTA PARA PROCESAR EL ENVÍO DEL FEEDBACK ---
@app.route('/enviar_feedback', methods=['POST'])
@login_required# Solo usuarios registrados pueden dejar feedback
def enviar_feedback():
    user_id = session.get('user_id')
    mensaje = request.form.get('mensaje')
    calificacion = request.form.get('calificacion') # Asegúrate que tu HTML tenga un input con name="calificacion"

    if not mensaje:
        flash('El mensaje no puede estar vacío', 'warning')
        return redirect(url_for('feedback'))

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Ajusta los nombres de las columnas según tu tabla de comentarios/feedback
            query = "INSERT INTO feedback (usuario_id, mensaje, calificacion) VALUES (%s, %s, %s)"
            cursor.execute(query, (user_id, mensaje, calificacion))
            conn.commit()
            flash('¡Gracias por tu opinión! Nos ayuda mucho. 💡', 'success')
        except psycopg2.Error as err:
            print(f"Error al guardar feedback: {err}")
            flash('No se pudo enviar el comentario.', 'error')
        finally:
            conn.close()
            
    return redirect(url_for('feedback'))

#---------------------------Gestion productos--------------------------

# --- RUTA PARA EDITAR PRODUCTO ---
@app.route('/producto/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_producto(id):
    conn = get_db_connection()
    if request.method == 'POST':
        # Aquí iría la lógica para UPDATE en la base de datos
        # Por ahora, solo redirigimos para que no te dé error
        return redirect(url_for('paginaproductor'))
    
    # Si es GET, buscamos el producto para mostrarlo en un formulario
    producto = None
    if conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM productos WHERE id = %s", (id,))
        producto = cursor.fetchone()
        conn.close()
    
    return render_template('editar_producto.html', producto=producto)

# --- RUTA PARA ELIMINAR PRODUCTO ---
@app.route('/producto/eliminar/<int:id>')
@login_required
def eliminar_producto(id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM productos WHERE id = %s", (id,))
            conn.commit()
            flash('Producto eliminado correctamente', 'info')
        except psycopg2.Error as err:
            flash('No se pudo eliminar el producto', 'error')
        finally:
            conn.close()
    return redirect(url_for('paginaproductor'))

#---------------fin pago-------------------------------------------

@app.route('/finalizar_pedido', methods=['POST'])
@login_required
def finalizar_pedido():
    user_id = session.get('user_id')
    conn = get_db_connection()
    
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # 1. Obtenemos los productos que el usuario tiene en su carrito
            cursor.execute("SELECT producto_id, cantidad FROM carrito WHERE usuario_id = %s", (user_id,))
            items_carrito = cursor.fetchall()

            if not items_carrito:
                flash("Tu carrito está vacío", "warning")
                return redirect(url_for('ver_carrito'))

            # 2. Por cada producto en el carrito, restamos el stock
            for item in items_carrito:
                # Actualizamos la tabla productos restando la cantidad comprada
                query_stock = """
                    UPDATE productos 
                    SET stock = stock - %s 
                    WHERE id = %s AND stock >= %s
                """
                cursor.execute(query_stock, (item['cantidad'], item['producto_id'], item['cantidad']))

            # 3. Limpiamos el carrito del usuario después de la compra
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
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)