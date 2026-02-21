import os
import sys
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from PIL import Image
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine

# Matplotlib only for color maps (no plotting)
import matplotlib
matplotlib.use("Agg")
from matplotlib import cm

APP_TITLE = "GeoTIFF → JPEG (with coordinates) – GUI"
DEFAULT_COLORMAP = "terrain"
CMAPS = [
    "terrain", "viridis", "plasma", "inferno", "magma", "cividis",
    "gist_earth", "gist_terrain", "Spectral", "RdYlGn", "cubehelix"
]

def clamp01(a):
    return np.clip(a, 0.0, 1.0)

def percent_clip_stretch(band, pct=2.0):
    """Simple contrast stretch: clip low/high percent and rescale to 0..1."""
    mask = np.isfinite(band)
    if not np.any(mask):
        return np.zeros_like(band, dtype=np.float32)
    vals = band[mask]
    lo = np.percentile(vals, pct)
    hi = np.percentile(vals, 100 - pct)
    if hi <= lo:
        # fallback
        lo, hi = np.min(vals), np.max(vals)
        if hi <= lo:
            return np.zeros_like(band, dtype=np.float32)
    norm = (band - lo) / (hi - lo)
    norm[~mask] = np.nan
    return clamp01(norm.astype(np.float32))

def to_uint8(img_float_0_1):
    """Float 0..1 to uint8 0..255, handling NaNs."""
    out = np.copy(img_float_0_1)
    out = np.nan_to_num(out, nan=0.0)
    out = (out * 255.0).round().astype(np.uint8)
    return out

def apply_colormap(norm_band, cmap_name):
    """Apply matplotlib colormap to normalized band -> RGB uint8."""
    cmap = cm.get_cmap(cmap_name)
    rgba = cmap(norm_band)  # H x W x 4
    rgb = (rgba[:, :, :3] * 255.0).round().astype(np.uint8)
    return rgb

def compute_scaled_transform(src_transform, src_width, src_height, out_width, out_height):
    """Return the new transform when raster is resampled to out_width/height."""
    scale_x = src_width / float(out_width)
    scale_y = src_height / float(out_height)
    return src_transform * Affine.scale(scale_x, scale_y)

def write_world_file(jpg_path, transform):
    """Write .jgw from affine transform."""
    # World file parameters:
    # line1: A: pixel size in the x-direction in map units/pixel
    # line2: D: rotation about y-axis (usually 0)
    # line3: B: rotation about x-axis (usually 0)
    # line4: E: pixel size in the y-direction in map units, typically NEGATIVE
    # line5: C: x-coordinate of the center of the upper left pixel
    # line6: F: y-coordinate of the center of the upper left pixel
    jgw = os.path.splitext(jpg_path)[0] + ".jgw"
    A = transform.a
    B = transform.b
    D = transform.d
    E = transform.e
    C = transform.c + A * 0.5 + B * 0.5
    F = transform.f + D * 0.5 + E * 0.5
    with open(jgw, "w", encoding="utf-8") as f:
        f.write(f"{A:.12f}\n")
        f.write(f"{D:.12f}\n")
        f.write(f"{B:.12f}\n")
        f.write(f"{E:.12f}\n")
        f.write(f"{C:.12f}\n")
        f.write(f"{F:.12f}\n")
    return jgw

def write_prj(jpg_path, crs):
    """Write ESRI WKT .prj if CRS exists."""
    if crs is None:
        return None
    prj_path = os.path.splitext(jpg_path)[0] + ".prj"
    try:
        wkt = crs.to_wkt("WKT1_ESRI")
    except Exception:
        # Fallback to standard WKT
        wkt = crs.to_wkt()
    with open(prj_path, "w", encoding="utf-8") as f:
        f.write(wkt)
    return prj_path

def guess_output_name(in_path, out_dir):
    base = os.path.splitext(os.path.basename(in_path))[0]
    return os.path.join(out_dir, base + ".jpg")

class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)

        self.in_path = tk.StringVar()
        self.out_dir = tk.StringVar(value=os.getcwd())
        self.max_dim = tk.IntVar(value=4096)     # max width/height (px)
        self.jpeg_quality = tk.IntVar(value=90)  # 1..95 (Pillow)
        self.colormap = tk.StringVar(value=DEFAULT_COLORMAP)
        self.use_colormap = tk.BooleanVar(value=True)
        self.write_world = tk.BooleanVar(value=True)
        self.write_prjfile = tk.BooleanVar(value=True)
        self.clip_pct = tk.DoubleVar(value=2.0)

        # Resampling options
        self.resampling = tk.StringVar(value="average")  # good for DEM downscale

        # Layout
        pad = {"padx": 8, "pady": 6}

        frm = ttk.Frame(root)
        frm.pack(fill="both", expand=True)

        # Input
        row = 0
        ttk.Label(frm, text="Input GeoTIFF:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.in_path, width=60).grid(row=row, column=1, sticky="we", **pad)
        ttk.Button(frm, text="Browse…", command=self.browse_in).grid(row=row, column=2, **pad)

        # Output dir
        row += 1
        ttk.Label(frm, text="Output folder:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.out_dir, width=60).grid(row=row, column=1, sticky="we", **pad)
        ttk.Button(frm, text="Choose…", command=self.browse_out_dir).grid(row=row, column=2, **pad)

        # Max dimension
        row += 1
        ttk.Label(frm, text="Max width/height (px):").grid(row=row, column=0, sticky="w", **pad)
        ttk.Spinbox(frm, from_=512, to=32768, increment=256, textvariable=self.max_dim, width=12).grid(row=row, column=1, sticky="w", **pad)

        # JPEG quality
        row += 1
        ttk.Label(frm, text="JPEG quality (1–95):").grid(row=row, column=0, sticky="w", **pad)
        ttk.Spinbox(frm, from_=1, to=95, increment=1, textvariable=self.jpeg_quality, width=12).grid(row=row, column=1, sticky="w", **pad)

        # Colormap toggle + chooser
        row += 1
        ttk.Checkbutton(frm, text="Apply colormap for single-band DEM", variable=self.use_colormap).grid(row=row, column=0, sticky="w", **pad)
        ttk.Label(frm, text="Colormap:").grid(row=row, column=1, sticky="w", **pad)
        ttk.Combobox(frm, values=CMAPS, textvariable=self.colormap, width=18, state="readonly").grid(row=row, column=2, sticky="w", **pad)

        # Contrast stretch
        row += 1
        ttk.Label(frm, text="Contrast stretch (clip %, per side):").grid(row=row, column=0, sticky="w", **pad)
        ttk.Spinbox(frm, from_=0.0, to=10.0, increment=0.5, textvariable=self.clip_pct, width=12).grid(row=row, column=1, sticky="w", **pad)

        # Resampling
        row += 1
        ttk.Label(frm, text="Resampling (downscale):").grid(row=row, column=0, sticky="w", **pad)
        ttk.Combobox(frm, values=["nearest", "bilinear", "cubic", "lanczos", "average"], textvariable=self.resampling, width=18, state="readonly").grid(row=row, column=1, sticky="w", **pad)

        # Toggles
        row += 1
        ttk.Checkbutton(frm, text="Write world file (.jgw)", variable=self.write_world).grid(row=row, column=0, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Write projection (.prj)", variable=self.write_prjfile).grid(row=row, column=1, sticky="w", **pad)

        # Buttons
        row += 1
        ttk.Button(frm, text="Convert", command=self.convert).grid(row=row, column=0, **pad)
        ttk.Button(frm, text="Quit", command=root.quit).grid(row=row, column=1, **pad)

        # Status
        row += 1
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(frm, textvariable=self.status, foreground="#006400").grid(row=row, column=0, columnspan=3, sticky="w", **pad)

        frm.columnconfigure(1, weight=1)

    def browse_in(self):
        p = filedialog.askopenfilename(title="Select GeoTIFF", filetypes=[("GeoTIFF", "*.tif *.tiff"), ("All files", "*.*")])
        if p:
            self.in_path.set(p)
            # Set default out dir to input folder
            self.out_dir.set(os.path.dirname(p))

    def browse_out_dir(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self.out_dir.set(d)

    def convert(self):
        in_path = self.in_path.get().strip()
        out_dir = self.out_dir.get().strip()
        max_dim = int(self.max_dim.get())
        q = int(self.jpeg_quality.get())
        cmap = self.colormap.get()
        use_cmap = bool(self.use_colormap.get())
        clip_pct = float(self.clip_pct.get())
        resampling = self.resampling.get()
        write_world = bool(self.write_world.get())
        write_prjfile = bool(self.write_prjfile.get())

        if not os.path.isfile(in_path):
            messagebox.showerror("Error", "Please choose a valid input GeoTIFF.")
            return
        if not os.path.isdir(out_dir):
            messagebox.showerror("Error", "Please choose a valid output folder.")
            return
        if q < 1 or q > 95:
            messagebox.showerror("Error", "JPEG quality must be 1–95.")
            return

        out_jpg = guess_output_name(in_path, out_dir)

        try:
            self.status.set("Opening raster…")
            self.root.update_idletasks()
            with rasterio.open(in_path) as src:
                src_crs = src.crs
                src_transform = src.transform
                src_width, src_height = src.width, src.height
                count = src.count

                # Compute output size respecting max_dim
                scale = 1.0
                if max(src_width, src_height) > max_dim:
                    scale = max_dim / float(max(src_width, src_height))
                out_w = max(1, int(round(src_width * scale)))
                out_h = max(1, int(round(src_height * scale)))

                # Rasterio resampling map
                resampling_map = {
                    "nearest": Resampling.nearest,
                    "bilinear": Resampling.bilinear,
                    "cubic": Resampling.cubic,
                    "lanczos": Resampling.lanczos,
                    "average": Resampling.average,
                }
                rs = resampling_map.get(resampling, Resampling.average)

                self.status.set(f"Reading data ({src_width}×{src_height} → {out_w}×{out_h})…")
                self.root.update_idletasks()

                if count == 1:
                    # Single-band DEM or grayscale
                    band = src.read(
                        1,
                        out_shape=(out_h, out_w),
                        resampling=rs
                    ).astype(np.float32)

                    # Respect nodata
                    nodata = src.nodatavals[0]
                    if nodata is not None:
                        band = np.where(band == nodata, np.nan, band)

                    # Contrast stretch + normalize
                    if clip_pct > 0:
                        norm = percent_clip_stretch(band, pct=clip_pct)
                    else:
                        # 0..1 naive stretch
                        vmin = np.nanmin(band)
                        vmax = np.nanmax(band)
                        norm = (band - vmin) / max(1e-12, (vmax - vmin))
                        norm = clamp01(norm)

                    if use_cmap:
                        rgb = apply_colormap(norm, cmap)  # HxWx3 uint8
                    else:
                        # Keep it grayscale if requested
                        gray = to_uint8(norm)
                        rgb = np.stack([gray, gray, gray], axis=-1)

                else:
                    # Multi-band imagery: read first 3 bands as RGB
                    bands = min(3, count)
                    arr = src.read(
                        indexes=list(range(1, bands + 1)),
                        out_shape=(bands, out_h, out_w),
                        resampling=Resampling.bilinear
                    ).astype(np.float32)

                    # Stretch each band to 0..1 independently then to uint8
                    rgb_list = []
                    for i in range(bands):
                        b = arr[i, :, :]
                        nod = src.nodatavals[i] if i < len(src.nodatavals) else None
                        if nod is not None:
                            b = np.where(b == nod, np.nan, b)
                        if clip_pct > 0:
                            n = percent_clip_stretch(b, pct=clip_pct)
                        else:
                            vmin = np.nanmin(b)
                            vmax = np.nanmax(b)
                            n = (b - vmin) / max(1e-12, (vmax - vmin))
                            n = clamp01(n)
                        rgb_list.append(to_uint8(n))
                    # If the source has only 2 bands, pad a 3rd
                    while len(rgb_list) < 3:
                        rgb_list.append(rgb_list[-1])
                    rgb = np.dstack(rgb_list[:3])

                # Compute new transform for the resampled grid
                new_transform = compute_scaled_transform(src_transform, src_width, src_height, out_w, out_h)

                self.status.set("Saving JPEG…")
                self.root.update_idletasks()
                # Save JPEG
                im = Image.fromarray(rgb)
                im.save(out_jpg, format="JPEG", quality=q, optimize=True, subsampling=1)

                # Write world + prj if requested
                created = [out_jpg]
                if write_world:
                    jgw = write_world_file(out_jpg, new_transform)
                    created.append(jgw)
                if write_prjfile and src_crs:
                    prj = write_prj(out_jpg, src_crs)
                    if prj:
                        created.append(prj)

            self.status.set("Done.")
            messagebox.showinfo("Success", "Export completed:\n\n" + "\n".join(created))

        except Exception as e:
            self.status.set("Error.")
            messagebox.showerror("Error", f"{e}")

def main():
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
