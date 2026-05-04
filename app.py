from flask import Flask, request, jsonify, session
from flask_restx import Api, Resource, fields
from flask_cors import CORS  # Importa CORS
import firebase_admin
from firebase_admin import credentials, firestore, auth, storage
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from datetime import datetime
import logging

#Inicializar la app de Flask
app = Flask(__name__)
app.secret_key = '121003'
app.config.update(
    SESSION_COOKIE_SECURE=True,  # Solo cookies seguras bajo HTTPS
    SESSION_COOKIE_HTTPONLY=True,  # Las cookies no son accesibles desde JavaScript
    SESSION_COOKIE_SAMESITE='None'  # Necesario para compartir cookies entre dominios diferentes
)
# Configurar CORS
CORS(app, resources={r"/*": {"origins": "http://localhost:5173", "supports_credentials": True}})

#Inicializar API con Flask-RESTX
api = Api(app, version='1.0', title='Bienes Raices API', 
          description='API para gestionar bienes raíces, usuarios y boletas', 
          doc='/swagger/') #Ruta para la documentación de Swagger
#Inicializar Firebase

cred = credentials.Certificate('Proyecto-Computaci-n-en-la-Nube-master/config/bienesraicesapp-2082b-firebase-adminsdk-ouekj-b5ece7fcfb.json')
firebase_admin.initialize_app(cred, {'storageBucket':'gs://bienesraicesapp-2082b.appspot.com'})

#Inicializar Firestore
db = firestore.client()
bucket = storage.bucket('bienesraicesapp-2082b.appspot.com')
bucket_name = 'bienesraicesapp-2082b.appspot.com'
# Configuración de logging
logging.basicConfig(level=logging.DEBUG)

#Modelos para Swagger
bien_raiz_model = api.model('BienRaiz', {
    'id': fields.String(required=True, description='ID del bien raíz'),
    'nombre': fields.String(required=True, description = 'Nombre del bien raíz'),
    'precio':fields.Float(required=True, description = 'Precio del bien raíz'),
    'ubicacion': fields.String(required=True, description='Ubicación del bien raíz'),
    'descripcion': fields.String(required=True, description='Descripción del bien raíz'),  # Nueva descripción
    'habitaciones': fields.Integer(required=True, description='Cantidad de habitaciones'),  # Nueva propiedad
    'banos': fields.Integer(required=True, description='Cantidad de baños'),  # Nueva propiedad
    'imagen_url': fields.String(required=False, description='URL de la imagen del bien raíz'),  # Campo existente
    'vendedor_id': fields.String(required=True, description='ID del vendedor')
})

venta_model = api.model('Venta', {
    'bien_raiz_id': fields.String(required=True, description='ID del bien raíz vendido'),
    'comprador_id': fields.String(required=True, description='ID del comprador'),
    'vendedor_id': fields.String(required=True, description='ID del vendedor'),
    'fecha_venta': fields.String(required=False, description='Fecha de la Venta'),
    'precio_final': fields.Float(required=True, description='Precio de venta'),
    'estado': fields.String(required=True, description='Estado de la venta (ej. "pendiente", "completada", "cancelada")'),
    'forma_pago': fields.String(required=True, description='Método de pago (ej. "efectivo", "transferencia bancaria", "financiamiento")'),
    'notas': fields.String(required=False, description='Notas adicionales sobre la venta')
})

boleta_model = api.model('Boleta', {
    'boleta': fields.String(required = True, description='Archivo de la boleta')
})
subir_boleta_model = api.parser()
subir_boleta_model.add_argument('boleta', location='files', type='file', required=True, help='Archivo de la boleta a subir')

@api.route('/login')
class Login(Resource):
    @api.doc(description="Iniciar sesión con email y contraseña")
    @api.expect(api.model('Login', {
        'email': fields.String(required=True, description='Correo Electrónico del usuario'),
        'password': fields.String(required=True, description='Contraseña del usuario'),
    }))
    def post(self):
        email = request.json.get('email')
        password = request.json.get('password')
        try:
            user = auth.get_user_by_email(email)
            # Aquí podrías implementar la validación de la contraseña si es necesario
            session['user_id'] = user.uid

            user_data = db.collection('user').document(user.uid).get()

            if user_data.exists:
                user_info = user_data.to_dict()
                nombre_completo = user_info.get('nombre_completo')
                tipo_usuario = user_info.get('tipo_usuario')
                password = user_info.get('password')
                return{"message": "Inicio de sesion exitoso", 
                       "id": user.uid,
                       "email": email,
                       "nombre_completo":nombre_completo ,
                       "tipo_usuario":tipo_usuario, 
                       "password":password}, 201
            else:
                return {"error": "El usuario no tiene datos adicionales"}, 404
        except Exception as e:
            return {"error": str(e)}, 401

@api.route('/signup')
class Signup(Resource):
    @api.doc(description="Registrarse con email, contraseña y tipo de usuario")
    @api.expect(api.model('Signup', {
        'email': fields.String(required=True, description='Correo Electrónico del usuario'),
        'password': fields.String(required=True, description='Contraseña del usuario'),
        'nombre_completo': fields.String(required=True, description='Nombre completo del usuario'),
        'tipo_usuario': fields.String(required=True, description='Tipo de usuario vendedor o comprador')
    }))
    def post(self):
        email = request.json.get('email')
        password = request.json.get('password')
        nombre_completo = request.json.get('nombre_completo')
        tipo_usuario = request.json.get('tipo_usuario')

        if tipo_usuario not in ['vendedor', 'comprador']:
            return {"error": "El tipo de usuario debe ser 'vendedor' o 'comprador'"}, 400
        try:
            user = auth.create_user(email=email, password=password)

            db.collection('user').document(user.uid).set({
                'email':email,
                'nombre_completo': nombre_completo,
                'tipo_usuario':tipo_usuario,
                'password': password
            })
            session['user_id'] = user.uid
            return {"message": "Registro exitoso", "tipo_usuario": tipo_usuario}, 201
        except Exception as e:
            return {"error": str(e)}, 400

@api.route('/bienes_raices')
class BienesRaices(Resource):
    # Define el parser para permitir archivos
    bien_raiz_parser = api.parser()
    bien_raiz_parser.add_argument('nombre', type=str, required=True, help='Nombre del bien raíz')
    bien_raiz_parser.add_argument('precio', type=float, required=True, help='Precio del bien raíz')
    bien_raiz_parser.add_argument('ubicacion', type=str, required=True, help='Ubicación del bien raíz')
    bien_raiz_parser.add_argument('descripcion', type=str, required=True, help='Descripción del bien raíz')
    bien_raiz_parser.add_argument('habitaciones', type=int, required=True, help='Cantidad de habitaciones')
    bien_raiz_parser.add_argument('banos', type=int, required=True, help='Cantidad de baños')
    bien_raiz_parser.add_argument('imagen', type=FileStorage, location='files', required=True, help='Imagen del bien raíz')

    @api.marshal_list_with(bien_raiz_model)
    @api.doc(description="Obtener todos los bienes raíces")
    def get(self):
        bienes_raices = []
        docs = db.collection('bienes_raices').stream()

        for doc in docs:
            bien = doc.to_dict()
            bien['id'] = doc.id  # Obtiene el ID de Firestore
            bienes_raices.append({
                'id': bien['id'],
                'user_id': bien.get('user_id'),
                'vendedor_id': bien.get('vendedor_id', 'No asignado'),
                'nombre': bien.get('nombre', 'No disponible'),
                'precio': bien.get('precio', 0),
                'ubicacion': bien.get('ubicacion', 'No disponible'),
                'descripcion': bien.get('descripcion', 'No disponible'),
                'habitaciones': bien.get('habitaciones', 0),
                'banos': bien.get('banos', 0),
                'imagen_url': bien.get('imagen_url', 'No disponible')
            })
        return bienes_raices, 200

    @api.doc(description="Agregar un nuevo bien raíz")
    @api.expect(bien_raiz_parser)
    def post(self):
        args = self.bien_raiz_parser.parse_args()
        imagen = args['imagen']  # Obtener el archivo de imagen

        if imagen is None:
            return {"error": "No se proporcionó ninguna imagen"}, 400


        vendedor_id = session.get('user_id')
        if not vendedor_id:
            return{"error": "No se encontró un usuario autenticado"}, 401

        try:
            # Obtener el nombre del archivo de imagen
            file_name = secure_filename(imagen.filename)
            content_type = imagen.content_type

            # Crear una referencia en el bucket de Firebase Storage
            blob = bucket.blob(file_name)

            # Subir el archivo de imagen al bucket
            blob.upload_from_file(imagen, content_type=content_type)

            # Hacer que el archivo sea accesible públicamente
            blob.make_public()

            # Obtener la URL pública de la imagen
            imagen_url = f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/{file_name}?alt=media"

            # Registrar el bien raíz en Firestore con la URL de la imagen
            doc_ref = db.collection('bienes_raices').add({
                'nombre': args['nombre'],
                'precio': args['precio'],
                'ubicacion': args['ubicacion'],
                'descripcion': args['descripcion'],
                'habitaciones': args['habitaciones'],
                'banos': args['banos'],
                'imagen_url': imagen_url,  # Guardar la URL pública
                'vendedor_id': vendedor_id
            })

            bien_id = doc_ref.id  # Obtener el ID del documento creado

            return {"message": "Bien raíz agregado", "id": bien_id,"vendedor_id": vendedor_id,"imagen_url": imagen_url}, 201

        except Exception as e:
            return {"error": str(e)}, 500
@api.route('/bienes_raices/string<string:id>')
class BienRaizDetail(Resource):
    @api.expect(bien_raiz_model)
    @api.doc(description="Actualizar el ID del vendedor de un bien raíz por ID")
    def put(self, id):
        # Parse the incoming request as JSON
        data = request.get_json()  # Using get_json() to ensure the request is parsed as JSON

        # Check if the vendedor_id is provided in the JSON body
        nuevo_vendedor_id = data.get('vendedor_id')
        if not nuevo_vendedor_id:
            return {"error": "Se debe proporcionar un nuevo ID de vendedor"}, 400

        try:
            # Reference to the bien raíz document
            doc_ref = db.collection('bienes_raices').document(id)
            
            # Check if the bien raíz exists
            bien_raiz = doc_ref.get()
            if not bien_raiz.exists:
                return {"error": "Bien raíz no encontrado"}, 404
            
            # Update the 'vendedor_id' field
            doc_ref.update({
                'vendedor_id': nuevo_vendedor_id
            })
            
            return {"message": "ID de vendedor actualizado exitosamente"}, 200
        
        except Exception as e:
            return {"error": str(e)}, 500
    
    # Método DELETE para eliminar un bien raíz
    @api.doc(description="Eliminar un bien raíz por ID")
    def delete(self, id):
        try:
            # Eliminar el bien raíz de Firestore
            db.collection('bienes_raices').document(id).delete()
            return {"message": "Bien raíz eliminado exitosamente"}, 200
        except Exception as e:
            return {"error": str(e)}, 500
        
"""@api.route('/subir_boleta')
class Boletas(Resource):
    @api.expect(subir_boleta_model)
    @api.doc(description="Subir una boleta en formato PDF")
    def post(self):
        args = subir_boleta_model.parse_args()
        file = args.get('boleta')

        if file is None:
            return {"message": "No se ha proporcionado ningún archivo"}, 400

        filename = secure_filename(file.filename)
        blob = bucket.blob(f'boletas/{filename}')

        # Subir el archivo
        blob.upload_from_file(file, content_type=file.content_type)

        # Guardar información de la boleta en Firestore
        db.collection('boletas').add({
            'filename': filename,
            'url': blob.public_url,  # O usa blob.generate_signed_url(expiration=3600) si necesitas una URL firmada
            'uploaded_at': firestore.SERVER_TIMESTAMP
        })

        return {"message": f"Boleta {filename} subida exitosamente"}, 201

@api.route('/descargar_boletas/<string:filename>')
class DescargarBoleta(Resource):
    @api.doc(description="Descargar una boleta por nombre de archivo")
    def get(self, filename):
        blob = bucket.blob(f'boletas/{filename}')

        if not blob.exists():
            return {"message": "La boleta no existe"}, 404
        
        url = blob.generate_signed_url(expiration=3600)

        return {"url": url}, 200
"""
@api.route('/generar_venta')
class GenerarVenta(Resource):
    venta_parser = api.parser()
    venta_parser.add_argument('bien_raiz_id', type=str, required=True, help='ID del bien raíz vendido')
    venta_parser.add_argument('fecha_venta', type=str, help='Fecha de la venta')
    venta_parser.add_argument('precio_final', type=float, required=True, help='Precio final de la venta')
    venta_parser.add_argument('forma_pago', type=str, required=True, help='Método de pago (efectivo, transferencia bancaria, etc.)')
    venta_parser.add_argument('estado', type=str, required=True, help='Estado de la venta (pendiente, completada, cancelada)')
    
    @api.expect(venta_parser)
    @api.doc(description="Generar una venta")
    def post(self):
        args = self.venta_parser.parse_args()

        # Obtener el user_id desde la sesión (esto debe ser parte de tu sistema de autenticación)
        user_id = session.get('user_id')
        if not user_id:
            return {"error": "No se encontró un usuario autenticado"}, 401
        
        try:
            # Obtener los datos del usuario desde Firestore para determinar su rol
            user_ref = db.collection('user').document(user_id)
            user_data = user_ref.get().to_dict()

            if not user_data:
                return {"error": "Usuario no encontrado en la base de datos"}, 404

            # Verificar que el usuario autenticado sea un comprador
            if user_data['tipo_usuario'] != 'comprador':
                return {"error": "El usuario no tiene el rol de comprador"}, 403

            comprador_id = user_id  # El comprador es el usuario autenticado

            # Validar que el bien raíz existe
            bien_raiz_ref = db.collection('bienes_raices').document(args['bien_raiz_id'])
            bien_raiz_data = bien_raiz_ref.get().to_dict()

            if not bien_raiz_data:
                return {"error": "El bien raíz no existe"}, 404

            vendedor_id = bien_raiz_data.get('vendedor_id')  # Obtener el vendedor asociado al bien raíz

            if not vendedor_id:
                return {"error": "No se ha asignado un vendedor a este bien raíz"}, 404

            # Obtener la fecha de la venta (si no se proporciona, se usa la fecha actual)
            fecha_venta = args.get('fecha_venta', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

            # Registrar la venta en Firestore
            venta_ref = db.collection('ventas').add({
                'bien_raiz_id': args['bien_raiz_id'],
                'comprador_id': comprador_id,
                'vendedor_id': vendedor_id,
                'fecha_venta': fecha_venta,
                'precio_final': args['precio_final'],
                'forma_pago': args['forma_pago'],
                'estado': args['estado'],
            })

            return {"message": "Venta registrada exitosamente", "venta_id": venta_ref[1].id}, 201

        except Exception as e:
            return {"error": str(e)}, 500
           
    @api.doc(description="Obtener las ventas registradas")
    def get(self):
        try:
            # Recuperar las ventas desde Firestore
            ventas_ref = db.collection('ventas').stream()

            # Crear una lista para almacenar las ventas
            ventas = []
            for venta in ventas_ref:
                venta_data = venta.to_dict()
                venta_data['venta_id'] = venta.id  # Agregar el ID de la venta al resultado
                ventas.append(venta_data)

            # Retornar las ventas en formato JSON
            return {"ventas": ventas}, 200

        except Exception as e:
            return {"error": str(e)}, 500
        
@api.route('/bienes_raices/<string:id>')
class BienRaizDetail(Resource):
    @api.doc(description="Obtener los detalles de un bien raíz por ID")
    def get(self, id):
        try:
            # Buscar el documento en la colección bienes_raices por el ID
            doc_ref = db.collection('bienes_raices').document(id)
            doc = doc_ref.get()

            # Verificar si el documento existe
            if doc.exists:
                bien_raiz = doc.to_dict()
                bien_raiz['id'] = doc.id  # Añadir el ID al resultado
                return {"message": "Bien raíz encontrado", "data": bien_raiz}, 200
            else:
                return {"error": f"No se encontró ningún bien raíz con ID: {id}"}, 404
        except Exception as e:
            return {"error": f"Error al obtener el bien raíz: {str(e)}"}, 500

@api.route('/compras')
class Compras(Resource):
    @api.doc(description="Obtener todas las compras realizadas por un comprador")
    def get(self):
        # Obtener el ID del comprador desde la sesión
        comprador_id = session.get('user_id')
        if not comprador_id:
            return {"error": "No se encontró un usuario autenticado"}, 401

        # Buscar todas las ventas donde el comprador_id coincida
        compras = []
        docs = db.collection('ventas').where('comprador_id', '==', comprador_id).stream()

        for doc in docs:
            compra = doc.to_dict()
            compra['id'] = doc.id  # Obtener el ID de la venta
            compras.append({
                'id': compra['id'],
                'bien_raiz_id': compra['bien_raiz_id'],
                'vendedor_id': compra['vendedor_id'],
                'fecha_venta': compra.get('fecha_venta'),
                'precio_final': compra['precio_final'],
                'estado': compra['estado'],
                'forma_pago': compra['forma_pago'],
                'notas': compra.get('notas')
            })

        return compras, 200


@api.route('/ventas')
class Ventas(Resource):
    @api.doc(description="Obtener todas las ventas realizadas por un vendedor")
    def get(self):
        # Obtener el ID del vendedor desde la sesión
        vendedor_id = session.get('user_id')
        if not vendedor_id:
            return {"error": "No se encontró un usuario autenticado"}, 401

        # Buscar todas las ventas donde el vendedor_id coincida
        ventas = []
        docs = db.collection('ventas').where('vendedor_id', '==', vendedor_id).stream()

        for doc in docs:
            venta = doc.to_dict()
            venta['id'] = doc.id  # Obtener el ID de la venta
            ventas.append({
                'id': venta['id'],
                'bien_raiz_id': venta['bien_raiz_id'],
                'comprador_id': venta['comprador_id'],
                'fecha_venta': venta.get('fecha_venta'),
                'precio_final': venta['precio_final'],
                'estado': venta['estado'],
                'forma_pago': venta['forma_pago'],
                'notas': venta.get('notas')
            })

        return ventas, 200

@api.route('/cerrar_sesion')
class CerrarSesion(Resource):
    @api.doc(description="Cerrar la sesión del usuario")
    def post(self):
        # Eliminar el ID del usuario de la sesión
        session.pop('user_id', None)

        return {"message": "Sesión cerrada correctamente"}, 200
        
if __name__ == '__main__':
    app.run(debug=True)