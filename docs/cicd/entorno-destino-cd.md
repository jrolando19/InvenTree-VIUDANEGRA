# Configuración del entorno destino para Despliegue Continuo de InvenTree

## 1. Objetivo

El objetivo de esta documentación es describir la configuración y verificación del entorno destino utilizado para el Despliegue Continuo de InvenTree. Este entorno permite ejecutar el sistema mediante contenedores Docker, facilitando una instalación reproducible, controlada y verificable.

## 2. Repositorio utilizado

El despliegue se trabajó sobre el repositorio del sistema:

```text
jrolando19/InvenTree-VIDUANEGRA
```

La rama utilizada para la configuración fue:

```text
master
```

Este repositorio contiene el código fuente del sistema InvenTree, la configuración de Docker, los archivos de despliegue y los workflows de GitHub Actions relacionados con el proceso CI/CD.

## 3. Entorno destino definido

El entorno destino corresponde a una máquina local con sistema Linux preparada para ejecutar InvenTree mediante Docker y Docker Compose.

Este entorno funciona como servidor local de despliegue para validar que el sistema pueda levantarse correctamente antes de ser considerado dentro de un flujo de Despliegue Continuo.

## 4. Herramientas verificadas

Se verificó la instalación de Docker y Docker Compose mediante los siguientes comandos:

```bash
docker --version
docker compose version
```

Resultado obtenido:

```text
Docker version 29.5.3
Docker Compose version v5.1.4
```

Esto confirma que el entorno cuenta con las herramientas necesarias para ejecutar servicios contenedorizados.

## 5. Carpeta de despliegue

El despliegue se ejecutó desde la carpeta de contenedores del proyecto:

```bash
cd ~/Documentos/InvenTree-VIUDANEGRA/contrib/container
```

En esta carpeta se encuentran los archivos principales para el despliegue:

```text
docker-compose.yml
Caddyfile
.env
docker.dev.env
nginx.conf
```

## 6. Configuración de URL del sistema

Se revisó el archivo `.env` y se identificó la URL configurada para el sistema:

```text
INVENTREE_SITE_URL="http://inventree.localhost"
```

Por ello, la dirección utilizada para acceder al despliegue local fue:

```text
http://inventree.localhost
```

Esta configuración es importante porque el proxy Caddy utiliza la variable `INVENTREE_SITE_URL` para determinar la dirección desde la cual se servirá la aplicación.

## 7. Ejecución del despliegue

El sistema fue levantado mediante Docker Compose con el siguiente comando:

```bash
docker compose up -d
```

Como resultado, se iniciaron correctamente los servicios principales de InvenTree.

## 8. Servicios desplegados

Se verificó el estado de los contenedores mediante:

```bash
docker compose ps
```

Los servicios levantados fueron:

| Servicio | Función |
|---|---|
| inventree-cache | Servicio Redis utilizado como caché |
| inventree-db | Base de datos PostgreSQL |
| inventree-server | Servidor principal de InvenTree |
| inventree-worker | Procesamiento de tareas en segundo plano |
| inventree-proxy | Proxy web mediante Caddy |

El proxy quedó expuesto en los puertos:

```text
80/tcp
443/tcp
```

Esto permite acceder al sistema desde el navegador mediante la URL configurada.

## 9. Verificación de respuesta HTTP

Se validó la respuesta del proxy con el siguiente comando:

```bash
curl -I http://localhost
```

Resultado obtenido:

```text
HTTP/1.1 200 OK
Server: Caddy
```

También se verificó la respuesta interna del servidor InvenTree:

```bash
docker compose exec inventree-server curl -I http://localhost:8000
```

Resultado obtenido:

```text
HTTP/1.1 302 Found
Location: /accounts/login/?next=/
```

Esta respuesta indica que el backend de InvenTree se encuentra activo y redirige correctamente hacia la pantalla de inicio de sesión.

## 10. Resultado de la verificación

Se confirmó que el entorno destino local permite desplegar InvenTree correctamente mediante Docker Compose. Los servicios principales fueron levantados, el proxy quedó expuesto en los puertos correspondientes y el sistema fue accesible desde navegador mediante:

```text
http://inventree.localhost
```

Con esto se demuestra que el entorno destino se encuentra preparado para ejecutar el sistema InvenTree de forma contenedorizada.

## 11. Relación con CI/CD

Esta configuración forma parte del proceso de Despliegue Continuo, ya que define y valida el entorno donde puede ejecutarse InvenTree mediante contenedores.

Además, se complementa con el workflow de integración continua configurado en GitHub Actions:

```text
CI - Automated Tests
```

Este workflow permite automatizar la ejecución de pruebas ante eventos `push` y `pull_request` sobre la rama `master`, mientras que el entorno Docker documentado permite validar el despliegue del sistema.

## 12. Evidencias consideradas

Para sustentar esta configuración se consideran las siguientes evidencias:

- Verificación de Docker y Docker Compose instalados.
- Ejecución de `docker compose up -d`.
- Verificación de contenedores mediante `docker compose ps`.
- Revisión de la variable `INVENTREE_SITE_URL` en el archivo `.env`.
- Respuesta HTTP 200 OK desde el proxy Caddy.
- Respuesta 302 Found desde el backend interno de InvenTree.
- Acceso correcto al sistema desde navegador mediante `http://inventree.localhost`.

## 13. Conclusión

El entorno destino local para el Despliegue Continuo de InvenTree fue configurado y verificado correctamente. Se comprobó que Docker y Docker Compose se encuentran disponibles, que los servicios principales del sistema se levantan mediante contenedores y que el sistema responde desde la URL configurada. Esta configuración permite contar con una base técnica para el despliegue automatizado del proyecto dentro del flujo CI/CD.
