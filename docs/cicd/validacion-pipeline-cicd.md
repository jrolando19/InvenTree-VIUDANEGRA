# Validación del flujo completo del pipeline CI/CD

## 1. Objetivo

El objetivo de esta documentación es validar el funcionamiento del flujo completo del pipeline CI/CD configurado para el proyecto InvenTree. La validación se centra en comprobar que, al realizar un cambio en el repositorio y enviarlo mediante `push`, GitHub Actions ejecuta automáticamente las etapas definidas en el workflow sin intervención manual.

El flujo evaluado es:

```text
Push -> Test -> Deploy
```

## 2. Repositorio utilizado

La validación se realizó sobre el repositorio del sistema:

```text
jrolando19/InvenTree-VIDUANEGRA
```

La rama utilizada fue:

```text
master
```

## 3. Workflow evaluado

El workflow evaluado fue:

```text
CI - Automated Tests
```

Archivo de configuración:

```text
.github/workflows/ci-tests.yml
```

Este workflow se encuentra configurado para ejecutarse automáticamente ante eventos de tipo `push` y `pull_request` sobre la rama `master`.

## 4. Funcionamiento general del pipeline

El pipeline se activa cuando se realiza un `push` hacia la rama `master`. Al detectar el cambio, GitHub Actions crea un entorno temporal de ejecución en la nube mediante un runner basado en `ubuntu-latest`.

Dentro de este entorno, el workflow instala las herramientas necesarias, prepara dependencias de backend y frontend, ejecuta las pruebas configuradas y controla la ejecución del job de despliegue automatizado.

## 5. Jobs configurados

El workflow está compuesto por los siguientes jobs:

| Job | Descripción |
|---|---|
| `backend-tests` | Prepara un entorno Python, levanta servicios auxiliares PostgreSQL y Redis, instala dependencias y ejecuta pruebas del backend mediante `pytest`. |
| `frontend-tests` | Prepara un entorno Node.js, instala dependencias del frontend y ejecuta pruebas o validaciones disponibles mediante comandos `npm`. |
| `deploy` | Valida archivos de despliegue, revisa la configuración Docker Compose, levanta contenedores y verifica una respuesta HTTP básica del sistema. |

## 6. Condición de despliegue

El job `deploy` fue configurado con dependencia sobre los jobs de pruebas mediante `needs`:

```yaml
needs:
  - backend-tests
  - frontend-tests
```

Esto significa que la etapa de despliegue solo debe ejecutarse después de que finalicen las pruebas del backend y frontend. Si alguna prueba falla, el despliegue queda bloqueado, evitando que cambios incorrectos continúen hacia la etapa de deploy.

## 7. Flujo validado

Para validar el flujo completo, se realiza un cambio en el repositorio y se envía mediante `git push origin master`. Con ello, GitHub Actions debe iniciar automáticamente el workflow configurado.

El flujo esperado es el siguiente:

1. Se realiza un cambio en el repositorio.
2. Se ejecuta un `push` hacia la rama `master`.
3. GitHub Actions detecta el cambio.
4. Se inicia el workflow `CI - Automated Tests`.
5. Se ejecutan los jobs de pruebas del backend y frontend.
6. El job `deploy` queda condicionado al resultado de las pruebas.
7. GitHub Actions registra los logs y el resultado del pipeline.

## 8. Evidencias del pipeline

La evidencia de la ejecución queda registrada en GitHub Actions, dentro del repositorio:

```text
Actions -> CI - Automated Tests
```

En dicha sección se pueden revisar:

- La ejecución generada por el commit enviado mediante `push`.
- El evento que activó el workflow.
- Los jobs ejecutados.
- Los logs de cada paso del pipeline.
- El resultado de las pruebas.
- El estado del job de despliegue.

## 9. Criterios de validación

El pipeline se considera correctamente validado si presenta alguno de los siguientes comportamientos esperados:

- Si las pruebas pasan, el job `deploy` se ejecuta automáticamente.
- Si alguna prueba falla, el job `deploy` queda bloqueado o marcado como omitido.
- Si el job `deploy` se ejecuta, debe validar los archivos de despliegue, la configuración Docker Compose, el levantamiento de contenedores y una respuesta HTTP básica.

Estos comportamientos demuestran que el pipeline controla automáticamente la transición entre pruebas y despliegue.

## 10. Resultado esperado

El resultado esperado es que el pipeline funcione sin intervención manual luego del `push`. GitHub Actions debe encargarse de preparar el entorno, instalar dependencias, ejecutar pruebas y condicionar la etapa de despliegue según el resultado obtenido.

## 11. Relación con el proceso CI/CD

Esta validación permite comprobar la integración entre la etapa de Integración Continua y la etapa de Despliegue Continuo. La Integración Continua se evidencia mediante la ejecución automática de pruebas, mientras que el Despliegue Continuo se evidencia mediante el job `deploy`, configurado para ejecutarse únicamente después de las validaciones previas.

## 12. Conclusión

Se validó el flujo completo del pipeline CI/CD configurado para InvenTree. El workflow se activa automáticamente ante un `push` hacia la rama `master`, ejecuta las etapas de prueba definidas para backend y frontend, y controla la ejecución del despliegue mediante dependencias entre jobs. Con ello se confirma que el pipeline permite validar cambios y gestionar la etapa de despliegue sin intervención manual directa.
