from typing import Dict, Any
import os
from pathlib import Path

import consul
from dotenv import load_dotenv
from flask import Flask
from flask_restx import Api

from app.logger_setup import logger
from app.routes import register_routes
from app.otel_setup import setup_otel, instrument_app

# Constantes
CONSUL_DEFAULT_PORT = 8500
CONSUL_DEFAULT_HOST = 'consul-service'
INSTANCE_DEFAULT_PORT = 5000
DEFAULT_CERT_DATE = '2019-01-01'


def load_config() -> Dict[str, Any]:
    """Carga y valida la configuración desde variables de entorno."""
    load_dotenv()

    config = {
        'production': os.getenv('PRODUCTION', 'FALSE').upper() == 'TRUE',
        'consul_port': int(os.getenv('CONSUL_PORT', CONSUL_DEFAULT_PORT)),
        'consul_host': os.getenv('CONSUL_HOST', CONSUL_DEFAULT_HOST),
        'instance_port': int(os.getenv('INSTANCE_PORT', INSTANCE_DEFAULT_PORT)),
        'cert_date': os.getenv('CERT_DATE', DEFAULT_CERT_DATE),
        'cert_path': os.getenv('CERT'),
        'privatekey_path': os.getenv('PRIVATEKEY')
    }

    # Logging de configuración
    for key, value in config.items():
        logger.info(f'{key}={value}/{os.getenv(key.upper())}')

    return config


def read_file_content(file_path: str, file_type: str) -> str:
    """Lee el contenido de un archivo de forma segura."""
    try:
        content = Path(file_path).read_text()
        logger.info(f'Contenido del archivo {file_type}:\n{content}')
        return content
    except Exception as e:
        logger.error(f'Error al leer el archivo {file_type}: {e}')
        raise RuntimeError(f'Error al leer el archivo {file_type}') from e


def create_app(config: Dict[str, Any] = None) -> Flask:
    """Crea y configura la aplicación Flask."""
    app = Flask(__name__)
    if config is None:
        config = load_config()

    # Leer archivos de certificados
    read_file_content(config['cert_path'], 'CERT')
    read_file_content(config['privatekey_path'], 'PRIVATEKEY')

    # Configurar OpenTelemetry (opcional, solo si está configurado)
    tracer = setup_otel()
    if tracer:
        instrument_app(app)

    # Configurar Consul
    consul_client = consul.Consul(host=config['consul_host'], port=config['consul_port'])
    service_name = 'pyafipws-service'
    service_port = config['instance_port']
    consul_client.agent.service.register(
        name=service_name,
        service_id=f'{service_name}-{service_port}',
        address=service_name,
        port=service_port,
        tags=['pyafipws', 'facturacion-electronica', 'afip'],
        check=consul.Check.http(f'http://{service_name}:{service_port}/api/afipws/health', interval='10s')
    )

    # Configurar Flask-RESTX con Swagger
    api = Api(
        app,
        version='2.4.0',
        title='pyafipws API',
        description='API REST para emisión de comprobantes electrónicos AFIP',
        doc='/swagger/',
        prefix='/api'
    )

    # Registrar rutas con la API
    register_routes(config, api)

    return app


# Creación de la aplicación
config = load_config()
app = create_app(config)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=config['instance_port'])
