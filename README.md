# 🌧️ PMA Early Warnings — Recomendación Agroclimática Estacional

**Proyecto:** Plataforma de Monitoreo Agroclimático (PMA)
**Departamentos:** Caquetá · Amazonas · Putumayo
**Fuentes:** IDEAM (pronóstico estacional) + CHIRPS / AgERA5 (histórico)

Para un mes objetivo, el proceso descarga el pronóstico de precipitación del IDEAM,
lo cruza con la climatología histórica (1982–2025), genera los productos
(cambio porcentual de precipitación y categoría SPEI modal) y **publica los GeoTIFF
en el GeoServer de AClimate** para su visualización.

Este repositorio está diseñado para ejecutarse **de forma desatendida en GitHub Actions,
una vez al mes**. Ya no depende de Google Colab.

---

## ⚙️ Cómo funciona

Cada mes, el workflow `.github/workflows/pma-mensual.yml`:

1. Prepara el entorno (Python + dependencias de `requirements.txt`).
2. Ejecuta `src/resampling_PMA.py`, que genera los productos en `outputs/` y los publica en el GeoServer.
3. Guarda los mapas y GeoTIFF como **artefacto** descargable de la corrida.
4. Hace un **commit de bitácora** (`logs/corridas.log`) para mantener activo el workflow programado.
5. Envía un **correo** de éxito (con los mapas adjuntos) o de error.

---

## 📁 Estructura

```
.
├── .github/workflows/pma-mensual.yml   ← Automatización mensual
├── src/resampling_PMA.py               ← Proceso principal
├── data/precip_spei_mensual.nc         ← Histórico CHIRPS/AgERA5 (1982–2025)
├── outputs/                            ← Salidas (se crea en cada corrida; no se versiona)
├── requirements.txt
├── env.txt.example
└── README.md
```

---

## 🔐 Configuración de credenciales (GitHub Secrets)

Las credenciales **nunca** van en el código. Se cargan como *secrets* cifrados:

1. En el repo: **Settings → Secrets and variables → Actions → New repository secret**.
2. Crea estos cuatro:

| Secret          | Contenido                                                        |
| --------------- | ---------------------------------------------------------------- |
| `GEO_USER`      | Usuario del GeoServer de AClimate                                |
| `GEO_PWD`       | Contraseña del GeoServer                                         |
| `MAIL_USER`     | Correo emisor de notificaciones                                  |
| `MAIL_PASSWORD` | Contraseña del correo (para Gmail: **App Password** con 2FA)     |

> El workflow trae `environment: production`. Si no quieres usar Environments,
> borra esa línea del YAML y usa Repository secrets. Si la dejas, crea el Environment
> llamado exactamente `production` en **Settings → Environments** y pon ahí los secrets.

Antes de subir los destinatarios, edita las líneas `to:` del YAML con los correos reales.

---

## 🧪 Parámetros (variables de entorno)

El proceso lee su configuración de variables de entorno; si no están, usa valores por defecto.

| Variable          | Default              | Descripción                                    |
| ----------------- | -------------------- | ---------------------------------------------- |
| `PMA_MONTH`       | mes actual (Actions) | Mes objetivo (1–12)                            |
| `PMA_YEAR`        | año actual (Actions) | Año objetivo                                   |
| `PMA_K`           | `3`                  | Nº de años análogos para la moda SPEI          |
| `PMA_DEPARTMENTS` | `Caquetá`            | Lista separada por comas                       |

En el disparo manual, el workflow permite fijar mes, año y departamentos.

---

## ▶️ Probar el proceso

### En GitHub (end-to-end)

1. Sube el repo a `main` (el workflow debe estar en la rama por defecto).
2. **Actions → PMA Early Warnings (mensual) → Run workflow**. Opcional: fija `month`/`year`.
3. Revisa los logs, descarga el artefacto y confirma el correo.

> ⚠️ Una corrida completa **publica de verdad** en el GeoServer (sube el granule del periodo).

### En local (sin publicar, para validar la generación)

```bash
pip install -r requirements.txt
export PMA_MONTH=3 PMA_YEAR=2026     # sin GEO_USER/GEO_PWD
cd src && python resampling_PMA.py
```

Sin credenciales, se generan todos los mapas en `../outputs/` y el proceso
falla limpio justo en el paso de publicación. Exporta `GEO_USER`/`GEO_PWD`
para hacer el flujo completo incluida la publicación.

---

## 📦 Productos generados

Para cada departamento y periodo: cambio porcentual de precipitación (`.tif` + `.png`),
categoría SPEI modal (`.tif` + `.png`) y un mapa de diagnóstico del control de calidad.
Los GeoTIFF son *Cloud Optimized GeoTIFF* (EPSG:4326) y quedan disponibles vía WMS/WCS en AClimate.

---

## Licencia

Uso libre para instituciones y personas interesadas en servicios agroclimáticos.
Si lo usas o adaptas, cita el repositorio y las fuentes originales (IDEAM, CHIRPS, AgERA5).
