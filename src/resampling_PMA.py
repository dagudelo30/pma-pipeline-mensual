#!/usr/bin/env python3
"""
PMA Early Warnings - Recomendacion agroclimatica estacional.
Version script (.py) para ejecucion desatendida en GitHub Actions (sin Colab).

Parametros y credenciales via variables de entorno:
    PMA_MONTH, PMA_YEAR, PMA_K, PMA_DEPARTMENTS  (opcionales; hay defaults)
    GEO_USER, GEO_PWD                            (requeridas para publicar en GeoServer)

Uso local para pruebas:
    export GEO_USER=usuario GEO_PWD=clave
    export PMA_MONTH=3 PMA_YEAR=2026
    cd notebooks && python resampling_PMA.py
"""
import matplotlib
matplotlib.use("Agg")   # backend headless: guarda los PNG sin necesidad de pantalla


# ===== Celda 3 =====
# ============================================================
# PARAMETROS - MODIFICA AQUI
# ============================================================

# Periodo objetivo
import os  # leer parametros desde variables de entorno (en local usa los defaults)
MONTH = int(os.environ.get("PMA_MONTH", 3))     # mes objetivo (1-12) - en Actions lo inyecta el workflow
YEAR  = int(os.environ.get("PMA_YEAR", 2026))   # anio objetivo - idem

# URL base pronóstico IDEAM
# Plantilla: ENSAMBLE_PREC_MENSUAL_{MM}_{YYYY}.nc
IDEAM_BASE_URL = "https://bart.ideam.gov.co/wrfideam/new_modelo/CPT/netcdf/PREC"

# Archivo historico de precipitacion y SPEI
# En Colab se descarga desde GitHub; en local apunta a tu copia.
HIST_GITHUB_URL = (
    "https://raw.githubusercontent.com/dagudelo30/PMA-early_warnings/main/"
    "data/precip_spei_mensual.nc"
)
HIST_LOCAL_PATH = "../data/precip_spei_mensual.nc"

# Departamentos a procesar
_dept_env = os.environ.get("PMA_DEPARTMENTS", "").strip()
DEPARTMENTS = [d.strip() for d in _dept_env.split(",") if d.strip()] or ["Caquet\u00e1"]  # override: PMA_DEPARTMENTS="Caquet\u00e1,Amazonas,Putumayo"
DEPT_NE_NAMES = {
    "Caquet\u00e1":  "Caquet\u00e1",
    "Amazonas": "Amazonas",
    "Putumayo": "Putumayo",
}

# Control de calidad (QC)
QC_UPPER_FACTOR = 3.0   # si pred > factor * clim -> se trunca
QC_CAP_FACTOR   = 1.1   # cap: pred truncada a cap * clim

# Parametro K (top-K analogos para moda de SPEI)
K = int(os.environ.get("PMA_K", 3))   # numero de anios analogos

# Directorio de salida
OUTPUT_DIR = "../outputs"

# ============================================================
# No modificar debajo de esta linea
# ============================================================
import os
MONTH_STR = f"{MONTH:02d}"
PERIOD_TAG = f"{MONTH_STR}_{YEAR}"
os.makedirs(OUTPUT_DIR, exist_ok=True)
print(f"Periodo objetivo: {MONTH_STR}/{YEAR}")
print(f"Directorio de salida: {os.path.abspath(OUTPUT_DIR)}")

# ===== Celda 5 =====
import sys, os, warnings
import requests
import numpy as np
import xarray as xr
import rioxarray
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap, BoundaryNorm, LinearSegmentedColormap, Normalize
from netCDF4 import Dataset
from xarray.backends import NetCDF4DataStore
from rasterio.enums import Resampling

warnings.filterwarnings('ignore')
print('Librerias importadas correctamente.')

# ===== Celda 7 =====
ideam_url = f"{IDEAM_BASE_URL}/ENSAMBLE_PREC_MENSUAL_{MONTH_STR}_{YEAR}.nc"
print(f"Descargando pronóstico IDEAM: {ideam_url}")

# Descarga con reintentos ante caidas temporales del servidor del IDEAM.
import time as _time
_intentos = int(os.environ.get("PMA_HTTP_RETRIES", 4))
_espera   = int(os.environ.get("PMA_HTTP_BACKOFF", 20))
r = None
for _i in range(1, _intentos + 1):
    try:
        r = requests.get(ideam_url, timeout=180)
        r.raise_for_status()
        break
    except Exception as _e:
        print(f"  Intento {_i}/{_intentos} de descarga fallo: {_e}")
        if _i == _intentos:
            raise
        _time.sleep(_espera)

nc  = Dataset("inmemory.nc", memory=r.content)
ds  = xr.open_dataset(NetCDF4DataStore(nc)).rename({"latitude": "y", "longitude": "x"})
ds  = ds.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=False)
ds  = ds.rio.write_crs("EPSG:4326", inplace=False)

print(f"Pronóstico cargado. Variables: {list(ds.data_vars)}")
print(f"Extension: x=[{float(ds.x.min()):.2f}, {float(ds.x.max()):.2f}]  y=[{float(ds.y.min()):.2f}, {float(ds.y.max()):.2f}]")
ds

# ===== Celda 9 =====
IN_COLAB = 'google.colab' in sys.modules

if IN_COLAB or not os.path.exists(HIST_LOCAL_PATH):
    print("Descargando historico desde GitHub...")
    r2 = requests.get(HIST_GITHUB_URL, timeout=300)
    r2.raise_for_status()
    nc2 = Dataset("hist_inmemory.nc", memory=r2.content)
    hist = xr.open_dataset(NetCDF4DataStore(nc2)).transpose("time", "y", "x")
else:
    print(f"Cargando historico local: {HIST_LOCAL_PATH}")
    hist = xr.open_dataset(HIST_LOCAL_PATH).transpose("time", "y", "x")

ds_filter = hist.sel(time=hist["time"].dt.month == MONTH)
print(f"Historico cargado. Variables: {list(ds_filter.data_vars)}")
print(f"Anios disponibles: {len(ds_filter.time)}")
ds_filter

# ===== Celda 11 =====
lat_min = float(ds_filter["y"].min())
lat_max = float(ds_filter["y"].max())
lon_min = float(ds_filter["x"].min())
lon_max = float(ds_filter["x"].max())

lat = ds["y"]
if lat[0] < lat[-1]:
    ds_clip = ds.sel(y=slice(lat_min, lat_max), x=slice(lon_min, lon_max))
else:
    ds_clip = ds.sel(y=slice(lat_max, lat_min), x=slice(lon_min, lon_max))

precip = ds_filter["precip"].rio.reproject_match(ds_clip, resampling=Resampling.bilinear)
spei   = ds_filter["spei"].rio.reproject_match(ds_clip, resampling=Resampling.nearest).round()

print(f"Grillas alineadas. Pronóstico: {dict(ds_clip.sizes)}  Historico: {dict(precip.sizes)}")

# ===== Celda 13 =====
print("Descargando limites administrativos Colombia (Natural Earth 10m)...")
url_adm1 = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip"
adm1     = gpd.read_file(url_adm1)
col_adm1 = adm1[adm1["admin"].str.lower() == "colombia"].copy()

depts = {}
for dept in DEPARTMENTS:
    ne_name = DEPT_NE_NAMES[dept]
    gdf     = col_adm1[col_adm1["name"] == ne_name]
    if gdf.empty:
        gdf = col_adm1[col_adm1["name"].str.contains(ne_name, case=False, na=False)]
    depts[dept] = gdf
    print(f"  {dept}: {len(gdf)} poligono(s)")

print("Limites cargados.")

# ===== Celda 15 =====
clim = precip.mean("time", skipna=True)
pred = ds_clip["Prediccion(mm)"].clip(min=0)
pred_qc = xr.where(pred > QC_UPPER_FACTOR * clim, QC_CAP_FACTOR * clim, pred)
ds_clip["Prediccion_QC(mm)"] = pred_qc

changed   = (pred_qc != pred) & pred.notnull()
n_changed = int(changed.sum())
n_total   = int(pred.notnull().sum())
print(f"QC completado: {n_changed} / {n_total} pixeles modificados ({100*n_changed/n_total:.2f}%)")

fig, ax = plt.subplots(figsize=(7, 4))
changed.astype('int8').plot(ax=ax, cmap='Reds', add_colorbar=False)

# --- Limite departamental sobre el mapa de QC ---
dept_qc = DEPARTMENTS[0]
gdf_qc = depts[dept_qc].set_crs("EPSG:4326", allow_override=True)
gdf_qc.boundary.plot(ax=ax, linewidth=1.3, color="black", zorder=5)

ax.set_title(f'Pixeles modificados por QC - {dept_qc} ({MONTH_STR}/{YEAR})')
ax.set_xlabel('Longitud'); ax.set_ylabel('Latitud')
plt.tight_layout()
plt.savefig(f"{OUTPUT_DIR}/qc_pixels_{PERIOD_TAG}.png", dpi=150)
plt.show()

# ===== Celda 17 =====
eps = 1e-6
cambio_pct = xr.where(clim > eps, (pred_qc - clim) / clim * 100, 0)
chg_hist   = xr.where(clim > eps, (precip - clim)  / clim * 100, 0)
print(f"Cambio porcentual: [{float(cambio_pct.min()):.1f}%, {float(cambio_pct.max()):.1f}%]")

# ===== Celda 19 =====
print(f"Calculando Top-{K} analogos por pixel...")

diff  = xr.apply_ufunc(np.abs, chg_hist - cambio_pct).transpose("time", "y", "x")
spei2 = spei.transpose("time", "y", "x")

d        = diff.values
T, Y, X  = d.shape
N        = Y * X
d2       = d.reshape(T, N)

idx  = np.argpartition(d2, K-1, axis=0)[:K, :]
dK   = np.take_along_axis(d2, idx, axis=0)
ordK = np.argsort(dK, axis=0)
idxK = np.take_along_axis(idx, ordK, axis=0)

spei_np   = spei2.values.reshape(T, N)
spei_topK = spei_np[idxK, np.arange(N)]

mode   = np.full(N, np.nan, dtype=np.float32)
p_mode = np.full(N, np.nan, dtype=np.float32)

for j in range(N):
    a = spei_topK[:, j]
    a = a[np.isfinite(a)]
    if a.size == 0:
        continue
    a = a.astype(np.int32)
    vals, cnts = np.unique(a, return_counts=True)
    m        = vals[np.argmax(cnts)]
    mode[j]  = m
    p_mode[j] = (a == m).mean()

spei_mode = xr.DataArray(
    mode.reshape(Y, X).astype("int16"),
    dims=("y", "x"),
    coords={"y": diff["y"], "x": diff["x"]},
    name="spei_moda"
)
spei_mode = spei_mode.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=False)
spei_mode = spei_mode.rio.write_crs("EPSG:4326", inplace=False)

print(f"Analogos calculados (K={K}).")
cats, cnt = np.unique(mode[np.isfinite(mode)].astype(int), return_counts=True)
label_map = {1: 'Muy seco', 2: 'Normal', 3: 'Muy humedo'}
for c, n in zip(cats, cnt):
    print(f"  Cat {c} ({label_map.get(c,'?')}): {n} pixeles ({100*n/N:.1f}%)")

# ===== Celda 21 =====
import math
from pyproj import Geod
from rasterio.features import geometry_mask
from shapely.geometry import mapping

def add_north_arrow(ax, lon, lat, size_deg=0.3):
    """Triangulo bicolor (negro/blanco) igual al notebook original."""
    arrow_len = size_deg
    half = size_deg * 0.35
    tri_n = plt.Polygon(
        [[lon, lat], [lon - half, lat - arrow_len], [lon + half, lat - arrow_len]],
        closed=True, facecolor="0.15", edgecolor="0.15", linewidth=0.6, zorder=25
    )
    tri_e = plt.Polygon(
        [[lon, lat], [lon + half, lat - arrow_len], [lon, lat - arrow_len * 0.5]],
        closed=True, facecolor="white", edgecolor="0.15", linewidth=0.6, zorder=26
    )
    ax.add_patch(tri_n)
    ax.add_patch(tri_e)
    ax.text(lon, lat + size_deg * 0.25, "N",
            ha="center", va="bottom", fontsize=9,
            fontweight="bold", color="0.15", zorder=27)


def add_geodesic_scalebar(ax, lon_start, lat_bar, length_km=200,
                          height_deg=0.08, linewidth=0.8):
    """Barra de escala geodesica de 4 segmentos alternos (negro/blanco)."""
    geod = Geod(ellps="WGS84")
    length_m = length_km * 1000
    ndiv = 4
    seg_m = length_m / ndiv
    h = height_deg
    lon_curr = lon_start
    for i in range(ndiv):
        lon_next, _, _ = geod.fwd(lon_curr, lat_bar, 90, seg_m)
        rect = mpatches.Rectangle(
            (lon_curr, lat_bar), (lon_next - lon_curr), h,
            facecolor=("0.15" if i % 2 == 0 else "1.0"),
            edgecolor="0.15", linewidth=linewidth, zorder=20, transform=ax.transData
        )
        ax.add_patch(rect)
        lon_curr = lon_next
    lon_end, _, _ = geod.fwd(lon_start, lat_bar, 90, length_m)
    ax.add_patch(mpatches.Rectangle(
        (lon_start, lat_bar), (lon_end - lon_start), h,
        fill=False, edgecolor="0.15", linewidth=linewidth, zorder=21, transform=ax.transData
    ))
    lon_mid, _, _ = geod.fwd(lon_start, lat_bar, 90, length_m / 2)
    ax.text(lon_start, lat_bar + h * 1.5, "0",
            ha="center", va="bottom", fontsize=7.5, color="0.15", zorder=22)
    ax.text(lon_mid,   lat_bar + h * 1.5, f"{length_km//2:.0f}",
            ha="center", va="bottom", fontsize=7.5, color="0.15", zorder=22)
    ax.text(lon_end,   lat_bar + h * 1.5, f"{length_km:.0f} km",
            ha="center", va="bottom", fontsize=7.5, color="0.15", zorder=22)


def clip_raster_exact(da, gdf):
    """
    Recorte en 2 pasos:
      1) clip_box  -> reduce el array al bounding box
      2) geometry_mask -> NaN exacto fuera del shape (sin pixeles extra en el borde)
    Devuelve float32 para soportar NaN.
    """
    geom = gdf.unary_union
    minx, miny, maxx, maxy = gpd.GeoSeries([geom], crs="EPSG:4326").total_bounds
    da_bb = da.astype("float32").rio.clip_box(minx=minx, miny=miny, maxx=maxx, maxy=maxy)
    mask = geometry_mask(
        [mapping(geom)],
        out_shape=(da_bb.sizes["y"], da_bb.sizes["x"]),
        transform=da_bb.rio.transform(),
        invert=True,
        all_touched=False
    )
    return da_bb.where(mask)


print("Funciones de visualizacion definidas.")

# ===== Celda 23 =====
# Colormap cambio porcentual
cmap_div = LinearSegmentedColormap.from_list(
    "cambio_pct",
    [(0.00, "#db1b1b"), (0.25, "#f97c2b"),
     (0.50, "#ecfc99"), (0.75, "#2fb47c"), (1.00, "#1ea0c4")],
    N=256
)

# SPEI: colores exactos del notebook original
# 1=Verano (rojo #db1b1b), 2=Normal (crema #ecfc99), 3=Invierno (azul #1ea0c4)
SPEI_CATS   = np.array([1, 2, 3])
SPEI_BOUNDS = np.array([0.5, 1.5, 2.5, 3.5])
SPEI_LABELS = {1: "Verano\n(seco)", 2: "Normal", 3: "Invierno\n(H\u00famedo)"}
cmap_spei = ListedColormap(["#db1b1b", "#ecfc99", "#1ea0c4"])
norm_spei = BoundaryNorm(SPEI_BOUNDS, cmap_spei.N)

VMIN, VMAX = -100, 100

for dept in DEPARTMENTS:
    gdf = depts[dept]
    if gdf.empty:
        print(f"Sin geometria para {dept}, se omite.")
        continue

    print(f"\nProcesando {dept}...")
    gdf = gdf.set_crs("EPSG:4326", allow_override=True).copy()
    gdf["geometry"] = gdf.geometry.buffer(0)
    slug = dept.lower().replace('\u00e1','a').replace('\u00e9','e').replace('\u00fa','u').replace('\u00f3','o')
    geom_orig = gdf.unary_union

    # ---- Recorte exacto bbox + geometry_mask ----
    def clip_exact(da_in, geom):
        minx, miny, maxx, maxy = gpd.GeoSeries([geom], crs="EPSG:4326").total_bounds
        da_bb = da_in.astype("float32").rio.clip_box(minx=minx, miny=miny, maxx=maxx, maxy=maxy)
        mask = geometry_mask(
            [mapping(geom)],
            out_shape=(da_bb.sizes["y"], da_bb.sizes["x"]),
            transform=da_bb.rio.transform(),
            invert=True,
            all_touched=False
        )
        return da_bb.where(mask)

    da_chg_base = cambio_pct.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=False)
    da_chg_base = da_chg_base.rio.write_crs("EPSG:4326", inplace=False)
    da_chg_clip = clip_exact(da_chg_base, geom_orig)

    da_spei_base = spei_mode.astype("float32").rio.write_crs("EPSG:4326", inplace=False)
    da_spei_clip = clip_exact(da_spei_base, geom_orig)

    # ---- GeoTIFFs ----
    tif_chg  = f"{OUTPUT_DIR}/cambio_pct_{PERIOD_TAG}_{slug}.tif"
    tif_spei = f"{OUTPUT_DIR}/spei_moda_{PERIOD_TAG}_{slug}.tif"

    da_tmp = da_chg_clip
    if da_tmp.y.values[0] < da_tmp.y.values[-1]:
        da_tmp = da_tmp.isel(y=slice(None, None, -1)).rio.write_transform(inplace=True)
    da_tmp.rio.to_raster(tif_chg, driver="GTiff", dtype="float32", compress="LZW", nodata=float("nan"))

    da_sp = da_spei_clip
    if da_sp.y.values[0] < da_sp.y.values[-1]:
        da_sp = da_sp.isel(y=slice(None, None, -1)).rio.write_transform(inplace=True)
    da_sp.rio.to_raster(tif_spei, driver="GTiff", dtype="float32", compress="LZW", nodata=float("nan"))
    print(f"  GeoTIFFs guardados.")

    # ---- Posiciones de norte y escala (relativas al extent del mapa) ----
    x0_d = float(da_chg_clip.x.min())
    x1_d = float(da_chg_clip.x.max())
    y0_d = float(da_chg_clip.y.min())
    y1_d = float(da_chg_clip.y.max())
    dx = x1_d - x0_d
    dy = y1_d - y0_d

    LON_SCALE = x0_d + 0.03 * dx
    LAT_SCALE = y0_d + 0.04 * dy
    LON_NORTH = x0_d + 0.09 * dx
    LAT_NORTH = y0_d + 0.33 * dy
    SIZE_NORTH = 0.18 * dy

    # ============================================================
    # Mapa cambio porcentual
    # ============================================================
    # TwoSlopeNorm: ancla el cero (crema) siempre en el centro visual
    # independientemente del rango de datos del mes.
    # extend='both' muestra flechas si hay valores fuera de [-100, +100].
    from matplotlib.colors import TwoSlopeNorm
    norm_div = TwoSlopeNorm(vmin=VMIN, vcenter=0, vmax=VMAX)
    ticks_cb = list(range(VMIN, VMAX + 1, 20))  # -100,-80,...,0,...,80,100

    fig, ax = plt.subplots(figsize=(9, 6))
    im = da_chg_clip.plot(
        ax=ax, cmap=cmap_div, norm=norm_div, add_colorbar=True,
        cbar_kwargs=dict(
            shrink=0.85, pad=0.02,
            extend="both",
            ticks=ticks_cb,
            label="Cambio porcentual (%)"
        )
    )
    im.colorbar.set_ticks(ticks_cb)
    im.colorbar.set_ticklabels([str(t) for t in ticks_cb])

    gdf.boundary.plot(ax=ax, linewidth=2.2, color="white", zorder=5)
    gdf.boundary.plot(ax=ax, linewidth=1.1, color="0.15", zorder=6,
                      capstyle="round", joinstyle="round")
    add_geodesic_scalebar(ax, lon_start=LON_SCALE, lat_bar=LAT_SCALE,
                          length_km=200, height_deg=0.10)
    add_north_arrow(ax, lon=LON_NORTH, lat=LAT_NORTH, size_deg=SIZE_NORTH)
    ax.set_title(f"Pronóstico del cambio porcentual de la precipitación en {dept} - {MONTH_STR}/{YEAR}")
    ax.set_xlabel("Longitud (\u00b0)"); ax.set_ylabel("Latitud (\u00b0)")
    ax.text(0.01, 0.01,  "Fuente: Generado a partir de CHIRPS y AgERA5. Limite: División departamental, Natural Earth a 10m.",
            transform=ax.transAxes, fontsize=5.5, va='bottom')
    plt.tight_layout()
    png_chg = f"{OUTPUT_DIR}/mapa_cambio_pct_{PERIOD_TAG}_{slug}.png"
    plt.savefig(png_chg, dpi=400, bbox_inches='tight')
    plt.show()

    # ============================================================
    # Mapa SPEI
    # ============================================================
    fig2, ax2 = plt.subplots(figsize=(9, 6))
    im2 = da_spei_clip.plot(
        ax=ax2, cmap=cmap_spei, norm=norm_spei, add_colorbar=True,
        cbar_kwargs=dict(
            ticks=SPEI_CATS,
            shrink=0.85, pad=0.02,
            extend="neither",
            extendrect=True
        )
    )
    im2.colorbar.set_ticklabels([SPEI_LABELS[i] for i in SPEI_CATS])
    im2.colorbar.set_label("")

    gdf.boundary.plot(ax=ax2, linewidth=2.2, color="white", zorder=5)
    gdf.boundary.plot(ax=ax2, linewidth=1.1, color="0.15", zorder=6,
                      capstyle="round", joinstyle="round")
    add_geodesic_scalebar(ax2, lon_start=LON_SCALE, lat_bar=LAT_SCALE,
                          length_km=200, height_deg=0.10)
    add_north_arrow(ax2, lon=LON_NORTH, lat=LAT_NORTH, size_deg=SIZE_NORTH)
    ax2.set_title(f"Escenarios de riesgo agroclimático para {dept} - {MONTH_STR}/{YEAR}")
    ax2.set_xlabel("Longitud (\u00b0)"); ax2.set_ylabel("Latitud (\u00b0)")
    ax2.text(0.01, 0.01, "Fuente: Generado a partir de CHIRPS y AgERA5. Limite: División departamental, Natural Earth a 10m.",
             transform=ax2.transAxes, fontsize=5.5, va='bottom')
    plt.tight_layout()
    png_spei = f"{OUTPUT_DIR}/mapa_spei_{PERIOD_TAG}_{slug}.png"
    plt.savefig(png_spei, dpi=400, bbox_inches='tight')
    plt.show()
    print(f"  Mapas: {png_chg} | {png_spei}")

print("\nTodos los departamentos procesados.")

# ===== Celda 25 =====
import glob
files = sorted(glob.glob(f"{OUTPUT_DIR}/*{PERIOD_TAG}*"))
print(f"Archivos generados para {PERIOD_TAG}:")
for f in files:
    size = os.path.getsize(f) / 1024
    print(f"  {os.path.basename(f):55s}  {size:8.1f} KB")
print(f"\nTotal: {len(files)} archivo(s)")

# ===== Celda 27 =====
import re
import shutil

base_path_geoserver = os.path.join(OUTPUT_DIR, "geoserver")

# Crear estructura
dir_pct_change = os.path.join(base_path_geoserver, "pct_change")
dir_spei = os.path.join(base_path_geoserver, "spei")
depts_lower = ["amazonas", "caqueta", "putumayo"]

for var_dir in [dir_pct_change, dir_spei]:
    for dept in depts_lower:
        os.makedirs(os.path.join(var_dir, dept), exist_ok=True)

print(f"\n📁 Estructura de directorios creada en: {base_path_geoserver}")

# Mapeo slug -> dept
slug_to_dept = {
    "caqueta": "caqueta",
    "amazonas": "amazonas",
    "putumayo": "putumayo"
}

# Buscar TIFs generados (cambio_pct_MM_YYYY_slug.tif y spei_moda_MM_YYYY_slug.tif)
output_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "*.tif")))
files_copied = []

for src_file in output_files:
    basename = os.path.basename(src_file)

    # Extraer período (MM_YYYY) y tipo de variable
    if "cambio_pct" in basename:
        var_type = "pct_change"
        match = re.search(r"cambio_pct_(\d{2})_(\d{4})_(\w+)\.tif", basename)
        if not match:
            continue
        month_str, year_str, slug = match.groups()
        timestamp = f"{year_str}{month_str}"
    elif "spei_moda" in basename:
        var_type = "spei"
        match = re.search(r"spei_moda_(\d{2})_(\d{4})_(\w+)\.tif", basename)
        if not match:
            continue
        month_str, year_str, slug = match.groups()
        timestamp = f"{year_str}{month_str}"
    else:
        continue

    dept_folder = slug_to_dept.get(slug)
    if not dept_folder:
        print(f"⚠️  No se pudo mapear slug '{slug}' en: {basename}")
        continue

    # Copiar con nuevo nombre
    # Prefijo del nombre de los granules; por defecto = nombre del workspace (misma convencion).
    _file_prefix = (os.environ.get("GEO_FILE_PREFIX", "").strip()
                    or os.environ.get("GEO_WORKSPACE", "").strip()
                    or "pma")
    # Etiqueta opcional para diferenciar corridas (pruebas de agendamiento).
    # Se usa un formato con guiones para NO introducir grupos largos de digitos
    # que puedan confundir la deteccion de tiempo del mosaico (que lee el YYYYMM).
    _tag = os.environ.get("PMA_GRANULE_TAG", "").strip()
    _tag_suffix = f"_{_tag}" if _tag else ""
    new_filename = f"{_file_prefix}_st_{dept_folder}_{var_type}_{timestamp}{_tag_suffix}.tif"
    dst_dir = os.path.join(base_path_geoserver, var_type, dept_folder)
    dst_file = os.path.join(dst_dir, new_filename)

    shutil.copyfile(src_file, dst_file)
    files_copied.append((new_filename, var_type, dept_folder, os.path.getsize(dst_file) / 1024))
    print(f"  ✅ {new_filename} → {var_type}/{dept_folder}/")

if files_copied:
    print(f"\n{'='*75}")
    print(f"📦 Resumen: {len(files_copied)} archivo(s) preparado(s) para GeoServer")
    print(f"{'='*75}")
    for fname, vtype, dept, size in files_copied:
        print(f"  {fname:50s}  {size:8.1f} KB")

# ===== Celda 29 =====
import os

# --- Modo prueba: si PMA_SKIP_PUBLISH esta activo, se detiene aqui ---
# Los mapas ya se generaron en las celdas anteriores; solo se omite la
# publicacion en GeoServer. Sirve para validar el pipeline sin tocar produccion.
if os.environ.get("PMA_SKIP_PUBLISH", "").strip().lower() in ("1", "true", "yes", "si"):
    print(">>> PMA_SKIP_PUBLISH activo: mapas generados correctamente; se OMITE la publicacion en GeoServer.")
    raise SystemExit(0)

import glob
import shutil
from zipfile import ZipFile

from geoserver.catalog import Catalog

# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────
def _load_env_file(env_file: str = "./env.txt") -> dict:
    """
    Carga variables de configuración desde un archivo de texto plano.
    Formato esperado:
        GEO_USER=usuario
        GEO_PWD=contraseña
    """
    # Variables requeridas
    required_vars = ["GEO_USER", "GEO_PWD"]

    # 1) Prioridad: variables de entorno (GitHub Actions / local con export)
    env_config = {v: os.environ.get(v, "").strip() for v in required_vars}
    if all(env_config[v] for v in required_vars):
        print("Credenciales tomadas de variables de entorno.")
        return env_config

    # 2) Fallback: archivo env.txt (local)
    config = {}
    if not os.path.exists(env_file):
        raise FileNotFoundError(
            f"❌ Archivo de configuración no encontrado: {env_file}\n"
            f"   Por favor, copia env.txt.example a env.txt y completa los valores."
        )

    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()

    # Validar que todas las variables requeridas estén presentes
    missing_vars = [var for var in required_vars if var not in config]
    if missing_vars:
        raise ValueError(
            f"❌ Variables de configuración faltantes en {env_file}:\n"
            f"   Faltan: {', '.join(missing_vars)}\n"
            f"   Variables requeridas: {', '.join(required_vars)}"
        )

    # Validar que los valores no estén vacíos
    empty_vars = [var for var in required_vars if not config[var]]
    if empty_vars:
        raise ValueError(
            f"❌ Variables con valores vacíos en {env_file}:\n"
            f"   Vacías: {', '.join(empty_vars)}\n"
            f"   Completa estos valores en el archivo."
        )

    return config

def _list_tifs(folder: str):
    if not os.path.isdir(folder):
        return []
    return sorted(glob.glob(os.path.join(folder, "*.tif")))

def _zip_tifs_only(src_folder: str, tmp_dir: str, zip_dir: str, zip_name: str):
    """
    ZIP solo con TIFs reproyectados a EPSG:4326 (para harvest_uploadgranule).
    """
    tifs = _list_tifs(src_folder)
    if not tifs:
        print(f"❌ No hay .tif en {src_folder}")
        return None

    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs(zip_dir, exist_ok=True)

    # copiar tifs
    for t in tifs:
        output_file = os.path.join(tmp_dir, os.path.basename(t))
        shutil.copyfile(t, output_file)

    zip_fullpath = os.path.join(zip_dir, zip_name)
    with ZipFile(zip_fullpath, "w") as z:
        for f in glob.glob(os.path.join(tmp_dir, "*.tif")):
            z.write(f, os.path.basename(f))

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"📦 ZIP generado: {zip_fullpath}")
    return zip_fullpath

# ───────────────────────────────────────────────
# Cliente GeoServer
# ───────────────────────────────────────────────
class GeoserverClient:
    def __init__(self, url: str, user: str, pwd: str):
        self.url = url
        self.user = user
        self.pwd = pwd
        self.catalog = None
        self.workspace = None

    def connect(self):
        self.catalog = Catalog(self.url, username=self.user, password=self.pwd)
        print("✅ Conectado a GeoServer (REST).")

    def get_workspace(self, name: str):
        self.workspace = self.catalog.get_workspace(name)
        if not self.workspace:
            raise RuntimeError(f"Workspace no encontrado: {name}")
        print(f"✅ Workspace encontrado: {name}")

    def get_store(self, store_name: str):
        try:
            return self.catalog.get_store(store_name, self.workspace)
        except Exception:
            return None

    def update_mosaic(self, store, rasters_dir: str, tmp_dir: str, zip_dir: str):
        zip_path = _zip_tifs_only(rasters_dir, tmp_dir, zip_dir, "granules.zip")
        if not zip_path:
            return
        self.catalog.harvest_uploadgranule(zip_path, store)
        print(f"🔄 Mosaico '{store.name}' actualizado (harvest).")


# ───────────────────────────────────────────────
# Configuración desde env.txt
# ───────────────────────────────────────────────

print("\n" + "="*75)
print("🔌 Conectando a GeoServer...")
print("="*75)

config = _load_env_file("./env.txt")

departamentos = ["amazonas", "caqueta", "putumayo"]
variables = ["pct_change", "spei"]

# Leer desde archivo env.txt
# Todo viene de variables de entorno (GitHub Secrets). Sin defaults sensibles
# en el codigo, para no exponer URL ni workspace en un repositorio publico.
gs_url = os.environ.get("GEO_URL", "").strip()
username = config.get("GEO_USER")
password = config.get("GEO_PWD")
ws_name = os.environ.get("GEO_WORKSPACE", "").strip()
store_prefix = os.environ.get("GEO_STORE_PREFIX", "").strip() or ws_name   # vacio -> usa el nombre del workspace

if not gs_url or not ws_name:
    raise ValueError(
        "Faltan GEO_URL y/o GEO_WORKSPACE. Definelas como GitHub Secrets "
        "(o con export en local). No hay valores por defecto para no exponer "
        "datos del servidor en un repositorio publico."
    )

print(f"  URL: {gs_url}")
print(f"  Usuario: {username}")
print(f"  Workspace: {ws_name}")

try:
    geo = GeoserverClient(gs_url, username, password)
    geo.connect()
    geo.get_workspace(ws_name)

    for var in variables:
        for depar in departamentos:
            store_name = f"{store_prefix}_st_{depar}_{var}"
            rasters_dir = os.path.join(base_path_geoserver, var, depar)

            tmp_root = os.path.join(base_path_geoserver, "tmp_mosaic")
            zip_root = os.path.join(base_path_geoserver, "zip_mosaic")
            os.makedirs(tmp_root, exist_ok=True)
            os.makedirs(zip_root, exist_ok=True)

            store_obj = geo.get_store(store_name)
            if store_obj:
                print(f"  [GeoServer] Actualizando store: {store_name}")
                geo.update_mosaic(store_obj, rasters_dir, tmp_root, zip_root)
            else:
                print(f"  ⚠️  Store no existe: {store_name}")

    print("\n✅ Flujo completado exitosamente")

except Exception as e:
    print(f"\n❌ Error: {e}")
    raise
