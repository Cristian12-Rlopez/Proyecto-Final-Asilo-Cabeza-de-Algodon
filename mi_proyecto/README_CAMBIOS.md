# Despliegue: Render (web) + Aiven (MySQL)

## Local (sin cambios)
Sin variable DATABASE_URL usa tu MySQL local (127.0.0.1:3307). `makemigrations`, `migrate`, `runserver` como siempre.

## Aiven
1. Crea el servicio MySQL y descarga el *CA certificate* -> guárdalo como `certs/aiven-ca.pem`.
2. Copia el *Service URI* (mysql://avnadmin:...@host:puerto/defaultdb?ssl-mode=REQUIRED).

## Render (Web Service, conectado al repo de GitHub)
- Build Command:  `./build.sh`        (o `bash build.sh`)
- Start Command:  `gunicorn mi_proyecto.wsgi:application`
- Variables de entorno:
    PYTHON_VERSION = 3.11.9
    DATABASE_URL   = (Service URI de Aiven)
    SECRET_KEY     = (una cadena larga y aleatoria)
    DEBUG          = False
    DJANGO_SUPERUSER_USERNAME / DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD
    (opcional, correo real) EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD

IMPORTANTE: sube a GitHub la carpeta core/migrations/ (con el 0001_initial.py que generaste con makemigrations),
el archivo certs/aiven-ca.pem y build.sh. Render ejecuta `migrate` pero NO crea migraciones.
