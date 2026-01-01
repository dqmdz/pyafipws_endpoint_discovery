# -*- coding: utf8 -*-
from pyafipws.wsaa import WSAA
from pyafipws.wsfexv1 import WSFEXv1
from app.logger_setup import logger
import os
import datetime
from typing import Dict, Any, List

# URL Configuration for Export (WSFEXv1)
URL_WSAA_HOMO = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?wsdl"
URL_WSAA_PROD = "https://wsaa.afip.gov.ar/ws/services/LoginCms?wsdl"
URL_WSFEXv1_HOMO = "https://wswhomo.afip.gov.ar/wsfexv1/service.asmx?WSDL"
URL_WSFEXv1_PROD = "https://servicios1.afip.gov.ar/wsfexv1/service.asmx?WSDL"

CUIT = os.getenv("CUIT")
CERT = os.getenv("CERT")
PRIVATEKEY = os.getenv("PRIVATEKEY")
CACHE = "" 

def facturar_exportacion(json_data: Dict[str, Any], production: bool = False) -> Dict[str, Any]:
    """
    Emite facturas electrónicas de exportación con CAE AFIP Argentina (WSFEXv1)
    """
    logger.debug(f"Iniciando facturación de exportación con datos: {json_data}")

    required_fields = ['tipo_afip', 'punto_venta', 'cliente', 'pais_dst_cmp', 'total', 'moneda_id', 'moneda_ctz', 'items', 'domicilio_cliente']
    if not all(field in json_data for field in required_fields):
        missing_fields = [field for field in required_fields if field not in json_data]
        raise ValueError(f"Faltan campos requeridos: {missing_fields}")

    # Validation: Either cuit_pais_cliente or id_impositivo must be present
    cuit_pais = json_data.get('cuit_pais_cliente', 0)
    id_impositivo = json_data.get('id_impositivo', '')
    if not cuit_pais and not id_impositivo:
        raise ValueError("Debe indicar 'cuit_pais_cliente' o 'id_impositivo' (al menos uno es obligatorio).")

    try:
        URL_WSAA = URL_WSAA_PROD if production else URL_WSAA_HOMO
        URL_WSFEX = URL_WSFEXv1_PROD if production else URL_WSFEXv1_HOMO
        
        # Authentication
        wsaa = WSAA()
        
        # Using 'wsfex' service for export
        try:
            ta = wsaa.Autenticar("wsfex", CERT, PRIVATEKEY, wsdl=URL_WSAA, cache=CACHE, debug=True)
        except Exception as auth_error:
            logger.error(f"Error en autenticación WSAA: {str(auth_error)}")
            raise

        wsfex = WSFEXv1()
        wsfex.Cuit = int(CUIT)
        wsfex.SetTicketAcceso(ta)
        wsfex.Conectar(CACHE, URL_WSFEX)
        
        # Get Last ID
        tipo_cbte = json_data['tipo_afip']
        punto_vta = json_data['punto_venta']
        
        # If number is not provided, get next
        cbte_nro = json_data.get('numero_comprobante')
        if not cbte_nro:
            last_cmp = wsfex.GetLastCMP(tipo_cbte, punto_vta)
            cbte_nro = int(last_cmp) + 1
            
        # Get Last Request ID for Authorization
        last_id = wsfex.GetLastID()
        request_id = int(last_id) + 1
        
        fecha_cbte = json_data.get('fecha_comprobante', datetime.date.today().strftime("%Y%m%d"))
        
        tipo_expo = json_data.get('tipo_expo', 1)

        # Calculate payment date (default 30 days) ONLY if not Goods (1)
        # AFIP Error 1673: Do not report payment date for goods
        fecha_pago = None
        if tipo_expo != 1:
            fecha_pago = json_data.get('fecha_pago')
            if not fecha_pago:
                f_cbte = datetime.datetime.strptime(fecha_cbte, "%Y%m%d")
                fecha_pago = (f_cbte + datetime.timedelta(days=30)).strftime("%Y%m%d")
        
        # Create Invoice Header
        # Using correct parameter names for WSFEXv1.CrearFactura (snake_case)
        factura_args = {
            'tipo_cbte': tipo_cbte,
            'punto_vta': punto_vta,
            'cbte_nro': cbte_nro,
            'fecha_cbte': fecha_cbte,
            'imp_total': json_data['total'],
            'tipo_expo': tipo_expo,
            'permiso_existente': json_data.get('permiso_existente', 'N'),
            'pais_dst_cmp': json_data['pais_dst_cmp'],
            'nombre_cliente': json_data['cliente'],
            'cuit_pais_cliente': json_data.get('cuit_pais_cliente', 0),
            'domicilio_cliente': json_data.get('domicilio_cliente', ''),
            'id_impositivo': json_data.get('id_impositivo', ''),
            'moneda_id': json_data['moneda_id'],
            'moneda_ctz': json_data['moneda_ctz'],
            'obs_comerciales': json_data.get('obs_comerciales', ''),
            'obs_generales': json_data.get('obs_generales', ''),
            'forma_pago': json_data.get('forma_pago', ''),
            'incoterms': json_data.get('incoterms', ''),
            'idioma_cbte': json_data.get('idioma_cbte', 1),
            'incoterms_ds': json_data.get('incoterms_ds', ''),
            'fecha_pago': fecha_pago,
        }

        # Remove None values (optional, but good practice)
        factura_args = {k: v for k, v in factura_args.items() if v is not None}
        
        # Ensure cuit_pais_cliente is present (defaults to 0 if missing in json)
        # If it was 0, it might have been removed by the filter above if we aren't careful.
        # But 0 != ''. 0 is not None. 0 is False-y but v != '' checks string.
        # Wait, if v is 0. 0 != '' is True. So it is kept.
        
        logger.info(f"Creando factura exportación: {factura_args}")
        wsfex.CrearFactura(**factura_args)
        
        # Add Items
        items = json_data.get('items', [])
        for item in items:
            item_args = {
                'codigo': item.get('pro_codigo'),
                'ds': item.get('pro_ds'),
                'qty': item.get('pro_qty'),
                'umed': item.get('pro_umed'),
                'precio': item.get('pro_precio_uni'),
                'importe': item.get('pro_total_item'),
            }
            logger.info(f"Agregando item: {item_args}")
            wsfex.AgregarItem(**item_args)
            
        # Authorize
        logger.info(f"Autorizando comprobante exportación ID {request_id}...")
        wsfex.Authorize(request_id)
        
        if wsfex.CAE:
            logger.info(f"Factura exportación autorizada: CAE={wsfex.CAE} Vto={wsfex.FchVencCAE}")
            json_data['cae'] = wsfex.CAE
            json_data['vencimiento_cae'] = wsfex.FchVencCAE
            json_data['resultado'] = wsfex.Resultado
            json_data['numero_comprobante'] = cbte_nro
            json_data['fecha_comprobante'] = fecha_cbte
            return json_data
        else:
            error_msg = f"Error AFIP: {wsfex.ErrMsg} - {wsfex.Obs}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    except Exception as e:
        logger.exception("Error durante la facturación de exportación")
        raise e
