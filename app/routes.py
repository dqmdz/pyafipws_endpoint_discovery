import json
from flask import request
from flask_restx import Namespace, Resource, fields
from app.logger_setup import logger
from app.factura_electronica import facturar, consultar_comprobante
from app.factura_exportacion import facturar_exportacion
from app.otel_setup import get_tracer
from typing import Dict

# Crear namespace para Flask-RESTX
afipws_ns = Namespace('afipws', description='Operaciones de facturación AFIP')

# Variable global para almacenar la configuración
_afip_config = {}

# Modelos para Swagger
factura_model = afipws_ns.model('Factura', {
    'tipo_afip': fields.Integer(required=True, description='Tipo de comprobante AFIP', example=1),
    'punto_venta': fields.Integer(required=True, description='Punto de venta', example=1),
    'tipo_documento': fields.Integer(required=True, description='Tipo de documento del receptor', example=80),
    'documento': fields.String(required=True, description='Número de documento del receptor', example='20123456789'),
    'total': fields.Float(required=True, description='Importe total', example=1210.0),
    'id_condicion_iva': fields.Integer(required=True, description='ID de condición IVA del receptor', example=1),
    'neto': fields.Float(description='Importe neto gravado', example=1000.0),
    'iva': fields.Float(description='Importe IVA 21%', example=210.0),
    'neto105': fields.Float(description='Importe neto gravado 10.5%', example=0.0),
    'iva105': fields.Float(description='Importe IVA 10.5%', example=0.0),
    'asociado_tipo_afip': fields.Integer(description='Tipo de comprobante asociado'),
    'asociado_punto_venta': fields.Integer(description='Punto de venta del comprobante asociado'),
    'asociado_numero_comprobante': fields.Integer(description='Número de comprobante asociado'),
    'asociado_fecha_comprobante': fields.String(description='Fecha del comprobante asociado')
})

item_exportacion_model = afipws_ns.model('ItemExportacion', {
    'pro_codigo': fields.String(required=True, description='Código del producto'),
    'pro_ds': fields.String(required=True, description='Descripción del producto'),
    'pro_qty': fields.Float(required=True, description='Cantidad'),
    'pro_umed': fields.Integer(required=True, description='Unidad de medida AFIP'),
    'pro_precio_uni': fields.Float(required=True, description='Precio unitario'),
    'pro_total_item': fields.Float(required=True, description='Total del item'),
    'pro_bonificacion': fields.Float(description='Bonificación')
})

factura_exportacion_model = afipws_ns.model('FacturaExportacion', {
    'tipo_afip': fields.Integer(required=True, description='Tipo de comprobante AFIP (e.g. 19)', example=19),
    'punto_venta': fields.Integer(required=True, description='Punto de venta', example=1),
    'cliente': fields.String(required=True, description='Nombre del cliente importador'),
    'pais_dst_cmp': fields.Integer(required=True, description='Código de país de destino (AFIP)', example=200),
    'total': fields.Float(required=True, description='Importe total', example=1000.0),
    'moneda_id': fields.String(required=True, description='Código de moneda (e.g. DOL)', example='DOL'),
    'moneda_ctz': fields.Float(required=True, description='Cotización de la moneda', example=1000.0),
    'items': fields.List(fields.Nested(item_exportacion_model), required=True, description='Items de la factura'),
    'cuit_pais_cliente': fields.Integer(description='CUIT/TaxID del cliente en su país', default=0),
    'domicilio_cliente': fields.String(description='Domicilio del cliente'),
    'id_impositivo': fields.String(description='ID Impositivo del cliente'),
    'incoterms': fields.String(description='Código Incoterms (e.g. FOB)'),
    'incoterms_ds': fields.String(description='Descripción Incoterms'),
    'obs_comerciales': fields.String(description='Observaciones comerciales'),
    'obs_generales': fields.String(description='Observaciones generales'),
    'forma_pago': fields.String(description='Forma de pago'),
    'permiso_existente': fields.String(description='Permiso de embarque existente (S/N)', default='N'),
    'tipo_expo': fields.Integer(description='Tipo de exportación (1=Bienes, 2=Servicios)', default=1),
    'idioma_cbte': fields.Integer(description='Idioma (1=Español)', default=1),
    'numero_comprobante': fields.Integer(description='Número de comprobante (opcional, si no se envía se calcula el siguiente)'),
    'fecha_comprobante': fields.String(description='Fecha del comprobante YYYYMMDD (opcional, default hoy)')
})

response_model = afipws_ns.model('Response', {
    'success': fields.Boolean(description='Indica si la operación fue exitosa'),
    'data': fields.Raw(description='Datos de respuesta'),
    'error': fields.String(description='Mensaje de error si aplica')
})

factura_response_model = afipws_ns.model('FacturaResponse', {
    'tipo_documento': fields.Integer(description='Tipo de documento del receptor'),
    'documento': fields.String(description='Número de documento del receptor'),
    'tipo_afip': fields.Integer(description='Tipo de comprobante AFIP'),
    'punto_venta': fields.Integer(description='Punto de venta'),
    'total': fields.Float(description='Importe total'),
    'exento': fields.Float(description='Importe exento'),
    'neto': fields.Float(description='Importe neto gravado'),
    'neto105': fields.Float(description='Importe neto gravado 10.5%'),
    'iva': fields.Float(description='Importe IVA 21%'),
    'iva105': fields.Float(description='Importe IVA 10.5%'),
    'resultado': fields.String(description='Resultado de la autorización'),
    'cae': fields.String(description='Número de CAE'),
    'vencimiento_cae': fields.String(description='Fecha de vencimiento del CAE'),
    'numero_comprobante': fields.Integer(description='Número de comprobante'),
    'fecha_comprobante': fields.String(description='Fecha del comprobante'),
    'asociado_tipo_afip': fields.Integer(description='Tipo de comprobante asociado'),
    'asociado_punto_venta': fields.Integer(description='Punto de venta del comprobante asociado'),
    'asociado_numero_comprobante': fields.Integer(description='Número de comprobante asociado'),
    'asociado_fecha_comprobante': fields.String(description='Fecha del comprobante asociado'),
    'id_condicion_iva': fields.Integer(description='ID de condición IVA del receptor')
})

factura_exportacion_response_model = afipws_ns.model('FacturaExportacionResponse', {
    'resultado': fields.String(description='Resultado de la autorización'),
    'cae': fields.String(description='Número de CAE'),
    'vencimiento_cae': fields.String(description='Fecha de vencimiento del CAE'),
    'numero_comprobante': fields.Integer(description='Número de comprobante'),
    'fecha_comprobante': fields.String(description='Fecha del comprobante'),
    'tipo_afip': fields.Integer(description='Tipo de comprobante AFIP'),
    'punto_venta': fields.Integer(description='Punto de venta'),
    'cliente': fields.String(description='Cliente'),
    'total': fields.Float(description='Total'),
    'moneda_id': fields.String(description='Moneda'),
    'moneda_ctz': fields.Float(description='Cotización')
})

test_response_model = afipws_ns.model('TestResponse', {
    'test': fields.String(description='Mensaje de prueba', example='ok')
})

consulta_parser = afipws_ns.parser()
consulta_parser.add_argument('tipo_cbte', type=int, required=True, help='Tipo de comprobante AFIP', location='args')
consulta_parser.add_argument('punto_vta', type=int, required=True, help='Punto de venta', location='args')
consulta_parser.add_argument('cbte_nro', type=int, required=True, help='Número de comprobante', location='args')

consulta_response_model = afipws_ns.model('ConsultaResponse', {
    'mensaje': fields.String(description='Mensaje devuelto por AFIP'),
    'factura': fields.Raw(description='Datos del comprobante consultado (si existe)', required=False)
})


@afipws_ns.route('/test')
class TestResource(Resource):
    @afipws_ns.doc('test_endpoint')
    @afipws_ns.marshal_with(test_response_model)
    def get(self):
        """Endpoint de prueba para verificar el estado del servicio."""
        tracer = get_tracer()
        if tracer:
            with tracer.start_as_current_span("test_endpoint") as span:
                span.set_attribute("endpoint", "/test")
                span.set_attribute("method", "GET")
                logger.info("test")
                return {"test": "ok"}
        else:
            logger.info("test")
            return {"test": "ok"}


@afipws_ns.route('/facturador_exportacion')
class FacturadorExportacionResource(Resource):
    @afipws_ns.doc('facturar_exportacion')
    @afipws_ns.expect(factura_exportacion_model)
    @afipws_ns.marshal_with(factura_exportacion_response_model)
    def post(self):
        """Endpoint para procesar facturas de exportación AFIP (WSFEXv1)."""
        tracer = get_tracer()
        if tracer:
            with tracer.start_as_current_span("facturar_exportacion_endpoint") as span:
                span.set_attribute("endpoint", "/facturador_exportacion")
                span.set_attribute("method", "POST")
                try:
                    json_data = request.get_json()
                    if json_data is None:
                        span.set_attribute("error", "No se proporcionó un JSON válido")
                        afipws_ns.abort(400, "No se proporcionó un JSON válido")

                    logger.info("facturando exportacion ...")
                    production = _afip_config.get('production', False)
                    
                    with tracer.start_as_current_span("facturar_exportacion_afip") as factura_span:
                        factura_span.set_attribute("afip.production", production)
                        result = facturar_exportacion(json_data, production=production)
                    
                    return result
                except Exception as e:
                    span.set_attribute("error", str(e))
                    logger.error(f'Error al facturar exportacion: {str(e)}')
                    return {"success": False, "error": str(e)}, 500
        else:
            try:
                json_data = request.get_json()
                if json_data is None:
                    afipws_ns.abort(400, "No se proporcionó un JSON válido")
                
                logger.info("facturando exportacion ...")
                production = _afip_config.get('production', False)
                result = facturar_exportacion(json_data, production=production)
                return result
            except Exception as e:
                logger.error(f'Error al facturar exportacion: {str(e)}')
                return {"success": False, "error": str(e)}, 500



@afipws_ns.route('/consulta_comprobante')
class ConsultaComprobanteResource(Resource):
    @afipws_ns.doc('consultar_comprobante')
    @afipws_ns.expect(consulta_parser)
    @afipws_ns.marshal_with(consulta_response_model)
    def get(self):
        """Endpoint para consultar un comprobante electrónico AFIP."""
        tracer = get_tracer()

        if tracer:
            with tracer.start_as_current_span("consulta_comprobante_endpoint") as span:
                span.set_attribute("endpoint", "/consulta_comprobante")
                span.set_attribute("method", "GET")

                try:
                    args = consulta_parser.parse_args()
                    tipo_cbte = args['tipo_cbte']
                    punto_vta = args['punto_vta']
                    cbte_nro = args['cbte_nro']

                    span.set_attribute("comprobante.tipo", tipo_cbte)
                    span.set_attribute("comprobante.punto_vta", punto_vta)
                    span.set_attribute("comprobante.cbte_nro", cbte_nro)

                    logger.info(f"Consultando comprobante: tipo={tipo_cbte}, pto_vta={punto_vta}, nro={cbte_nro}")

                    production = _afip_config.get('production', False)

                    with tracer.start_as_current_span("consultar_comprobante_afip") as consulta_span:
                        consulta_span.set_attribute("afip.production", production)
                        result = consultar_comprobante(tipo_cbte, punto_vta, cbte_nro, production=production)

                    logger.info(f"Resultado de la consulta: {result}")
                    
                    if result.get("factura") is None:
                        # Comprobante no encontrado, pero la operación fue "exitosa" en el sentido de que no hubo un error de sistema.
                        return result, 200
                    
                    return result

                except Exception as e:
                    span.set_attribute("error", str(e))
                    span.set_attribute("error.type", type(e).__name__)
                    logger.error(f'Error al consultar comprobante: {str(e)}')
                    return {"mensaje": f"Error interno del servidor: {str(e)}", "factura": None}, 500
        else:
            # No tracer
            try:
                args = consulta_parser.parse_args()
                tipo_cbte = args['tipo_cbte']
                punto_vta = args['punto_vta']
                cbte_nro = args['cbte_nro']

                logger.info(f"Consultando comprobante: tipo={tipo_cbte}, pto_vta={punto_vta}, nro={cbte_nro}")

                production = _afip_config.get('production', False)

                result = consultar_comprobante(tipo_cbte, punto_vta, cbte_nro, production=production)

                logger.info(f"Resultado de la consulta: {result}")

                if result.get("factura") is None:
                    return result, 200

                return result

            except Exception as e:
                logger.error(f'Error al consultar comprobante: {str(e)}')
                return {"mensaje": f"Error interno del servidor: {str(e)}", "factura": None}, 500


@afipws_ns.route('/facturador')
class FacturadorResource(Resource):
    @afipws_ns.doc('facturar')
    @afipws_ns.expect(factura_model)
    @afipws_ns.marshal_with(factura_response_model)
    def post(self):
        """Endpoint para procesar facturas electrónicas AFIP."""
        tracer = get_tracer()
        
        if tracer:
            with tracer.start_as_current_span("facturar_endpoint") as span:
                span.set_attribute("endpoint", "/facturador")
                span.set_attribute("method", "POST")
                
                try:
                    json_data = request.get_json()
                    
                    if json_data is None:
                        span.set_attribute("error", "No se proporcionó un JSON válido")
                        afipws_ns.abort(400, "No se proporcionó un JSON válido")
                    
                    # Agregar atributos del span con información de la factura
                    span.set_attribute("factura.tipo_afip", json_data.get('tipo_afip', 0))
                    span.set_attribute("factura.punto_venta", json_data.get('punto_venta', 0))
                    span.set_attribute("factura.documento", json_data.get('documento', ''))
                    span.set_attribute("factura.total", json_data.get('total', 0.0))
                    
                    logger.info("facturando ...")
                    logger.info(f"json_data=\n{json.dumps(json_data, indent=2)}")
                    logger.info("llamando a facturar ...")
                    
                    # Obtener la configuración desde la variable global
                    production = _afip_config.get('production', False)
                    
                    with tracer.start_as_current_span("facturar_afip") as factura_span:
                        factura_span.set_attribute("afip.production", production)
                        result = facturar(json_data, production=production)
                    
                    logger.info(f"json_data (after)={result}")
                    
                    # Logging detallado para debug
                    logger.info(f"Resultado final JSON: {json.dumps(result, indent=2)}")
                    logger.info(f"Tipos en resultado: {[(k, type(v)) for k, v in result.items()]}")
                    
                    return result
                    
                except Exception as e:
                    span.set_attribute("error", str(e))
                    span.set_attribute("error.type", type(e).__name__)
                    logger.error(f'Error al facturar: {str(e)}')
                    return {"success": False, "error": str(e)}, 500
        else:
            # Código original sin trazas
            try:
                json_data = request.get_json()
                
                if json_data is None:
                    afipws_ns.abort(400, "No se proporcionó un JSON válido")
                
                logger.info("facturando ...")
                logger.info(f"json_data=\n{json.dumps(json_data, indent=2)}")
                logger.info("llamando a facturar ...")
                
                # Obtener la configuración desde la variable global
                production = _afip_config.get('production', False)
                
                result = facturar(json_data, production=production)
                logger.info(f"json_data (after)={result}")
                
                # Logging detallado para debug
                logger.info(f"Resultado final JSON: {json.dumps(result, indent=2)}")
                logger.info(f"Tipos en resultado: {[(k, type(v)) for k, v in result.items()]}")
                
                return result
                
            except Exception as e:
                logger.error(f'Error al facturar: {str(e)}')
                return {"success": False, "error": str(e)}, 500


@afipws_ns.route('/health')
class HealthResource(Resource):
    @afipws_ns.doc('health_check')
    def get(self):
        """Endpoint de chequeo de salud para Consul."""
        return {"status": "ok"}


def register_routes(config: Dict, api):
    """Configura y registra las rutas con la API de Flask-RESTX."""
    # Guardar la configuración en la variable global
    global _afip_config
    _afip_config = config
    
    # Agregar namespace a la API
    api.add_namespace(afipws_ns)