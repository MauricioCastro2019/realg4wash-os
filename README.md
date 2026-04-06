RealG4Wash OS

Sistema operativo interno para la gestión de operaciones de RealG4Wash.
Permite administrar clientes, vehículos, órdenes de servicio y seguimiento del lavado.

Este sistema está diseñado para operación real en un autolavado, no como demo académico.

Filosofía del proyecto

RealG4Wash OS busca:

Simplificar la operación diaria del autolavado

Registrar cada servicio realizado

Crear historial de clientes y vehículos

Mantener control operativo del negocio

Construir una base de datos real para crecimiento futuro

Este proyecto es el núcleo digital del ecosistema RealG4Wash / Mi Auto Pro.

Funcionalidades actuales

Sistema de autenticación de usuarios
Dashboard operativo
Registro de clientes
Registro de vehículos
Creación de órdenes de servicio
Checklist de inspección del vehículo
Historial de órdenes
Asignación de paquetes de lavado

Estructura del proyecto
realg4wash-os
│
├── app
│   ├── auth
│   │   ├── routes.py
│   │   ├── forms.py
│   │   └── templates
│   │
│   ├── main
│   │   ├── routes.py
│   │   └── templates
│   │
│   ├── models.py
│   ├── extensions.py
│   ├── config.py
│   └── __init__.py
│
├── migrations
│
├── create_admin.py
├── requirements.txt
└── run.py
Requisitos

Python 3.10 o superior

Instalación paso a paso
1 Clonar el repositorio
git clone https://github.com/MauricioCastro2019/realg4wash-os.git
cd realg4wash-os
2 Crear entorno virtual

Windows

python -m venv venv
venv\Scripts\activate

Mac / Linux

python3 -m venv venv
source venv/bin/activate
3 Instalar dependencias
pip install -r requirements.txt
4 Inicializar base de datos
flask db upgrade

Si es la primera vez que se ejecuta:

flask db init
flask db migrate
flask db upgrade
5 Crear usuario administrador
python create_admin.py

Esto generará el primer usuario administrador del sistema.

6 Ejecutar la aplicación
python run.py

El sistema estará disponible en

http://127.0.0.1:5000
Flujo de operación del sistema

El flujo está diseñado para replicar la operación real del autolavado.

1 Cliente llega
2 Se registra o selecciona cliente existente
3 Se registra el vehículo
4 Se crea una orden de servicio
5 Se selecciona paquete de lavado
6 Se registra inspección del vehículo
7 Se realiza el servicio
8 Se marca la orden como completada

Paquetes de lavado

Actualmente el sistema maneja paquetes configurables en el backend.

Ejemplo:

Express
Esencial
Pro
Premium

Cada paquete puede tener precios distintos dependiendo del tipo de vehículo.

Próximas mejoras

Agenda automática de servicios
Dashboard financiero
Estadísticas de operación
Registro de pagos
Integración con WhatsApp
Sistema de recordatorios a clientes
Historial completo por vehículo
Sistema de fidelización de clientes

Roadmap del sistema

Fase 1
Sistema operativo básico funcionando

Fase 2
Control completo de órdenes

Fase 3
Automatización del negocio

Fase 4
Sistema multi sucursal


![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/Flask-3.x-black)
![License](https://img.shields.io/badge/License-Internal-lightgrey)

## Capturas

### Login
![Login](docs/screenshots/login.png)

### Dashboard
![Dashboard](docs/screenshots/dashboard.png)


Autor

Mauricio Banquells Castro

Fundador de RealG4Wash
Desarrollador del sistema operativo del negocio

Licencia

Uso interno para el proyecto RealG4Wash.

Visión

Construir el mejor sistema operativo para autolavados independientes, permitiendo que pequeños negocios operen con el nivel de control de una franquicia.